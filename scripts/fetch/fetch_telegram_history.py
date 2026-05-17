from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
from datetime import UTC, date, datetime, timedelta, timezone
from datetime import tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TARGET_NOT_FOUND_PATTERNS = (
    re.compile(r'^No (?:user|chat|channel) has ".+" as username$', flags=re.IGNORECASE),
    re.compile(r"^Cannot find any entity corresponding to ", flags=re.IGNORECASE),
)
TELEGRAM_MESSAGE_URL_RE = re.compile(
    r"^https?://t\.me/(?:s/)?(?P<public>[^/?#]+)/(?P<message_id>\d+)$",
    flags=re.IGNORECASE,
)
TELEGRAM_MESSAGE_HANDLE_RE = re.compile(r"^@(?P<public>[^/?#]+)/(?P<message_id>\d+)$")


class PayloadValidationError(ValueError):
    pass


def decode_b64url(value: str) -> str:
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")


def load_payload(encoded: str) -> dict[str, Any]:
    try:
        payload = json.loads(decode_b64url(encoded))
    except Exception as exc:
        raise ValueError(f"Invalid --payload-b64url argument: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Decoded payload must be a JSON object.")

    return payload


def load_payload_file(input_path: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ValueError(f"Invalid --input-path payload JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Input payload file must contain a JSON object.")

    return payload


def write_output(text: str, output_path: str | None = None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return

    print(text)


def compact_json(data: dict[str, Any]) -> str:
    # Keep stdout ASCII-safe so Execute Command can consume JSON reliably.
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


def iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_utc(raw_value: Any) -> datetime | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_phone(value: str | None) -> str:
    digits = re.sub(r"\D+", "", value or "")
    return digits if len(digits) >= 8 else ""


def normalize_target(raw_target: Any) -> str:
    value = str(raw_target or "").strip()
    if not value:
        return ""

    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    if value.startswith("@"):
        match = TELEGRAM_MESSAGE_HANDLE_RE.match(value)
        if match:
            return f"@{match.group('public')}"
        return value

    if value.startswith("https://t.me/") or value.startswith("http://t.me/"):
        value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
        if value.startswith("s/"):
            value = value[2:]
        parts = [part for part in value.split("/") if part]
        if not parts:
            return ""
        if parts[0].startswith("+"):
            return parts[0]
        return parts[0]

    return value


def _append_unique_int(target: list[int], value: int) -> None:
    if value not in target:
        target.append(value)


def _parse_optional_message_ids(raw_value: Any, *, field_name: str) -> list[int]:
    if raw_value in (None, ""):
        return []
    if isinstance(raw_value, (list, tuple)):
        values = list(raw_value)
    else:
        values = [part for part in re.split(r"[\s,;]+", str(raw_value).strip()) if part]

    parsed: list[int] = []
    for value in values:
        _append_unique_int(parsed, parse_positive_int(value, field_name=field_name))
    return parsed


def parse_telegram_target_request(payload: dict[str, Any]) -> dict[str, Any]:
    raw_target = payload.get("telegram_target")
    raw_target_text = str(raw_target or "").strip()
    normalized_target = normalize_target(raw_target)
    exact_message_ids: list[int] = []
    exact_post_urls: list[str] = []
    telegram_public = ""

    cleaned_target = raw_target_text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    url_match = TELEGRAM_MESSAGE_URL_RE.match(cleaned_target)
    handle_match = TELEGRAM_MESSAGE_HANDLE_RE.match(cleaned_target)
    match = url_match or handle_match
    if match and not match.group("public").startswith("+"):
        telegram_public = match.group("public")
        message_id = parse_positive_int(match.group("message_id"), field_name="telegram_target message_id")
        _append_unique_int(exact_message_ids, message_id)
        exact_post_urls.append(f"https://t.me/{telegram_public}/{message_id}")

    for field_name in ("message_id", "exact_message_id"):
        for message_id in _parse_optional_message_ids(payload.get(field_name), field_name=field_name):
            _append_unique_int(exact_message_ids, message_id)

    for field_name in ("message_ids", "exact_message_ids"):
        for message_id in _parse_optional_message_ids(payload.get(field_name), field_name=field_name):
            _append_unique_int(exact_message_ids, message_id)

    if not telegram_public and normalized_target:
        telegram_public = normalized_target[1:] if normalized_target.startswith("@") else normalized_target
    if exact_message_ids and not exact_post_urls and telegram_public and not telegram_public.startswith("+"):
        exact_post_urls = [f"https://t.me/{telegram_public}/{message_id}" for message_id in exact_message_ids]

    return {
        "telegram_target": normalized_target,
        "telegram_public": telegram_public,
        "exact_message_request": bool(exact_message_ids),
        "exact_message_ids": exact_message_ids,
        "exact_post_urls": exact_post_urls,
    }


def is_target_not_found_value_error(exc: ValueError) -> bool:
    message = str(exc).strip()
    if not message:
        return False
    return any(pattern.search(message) for pattern in TARGET_NOT_FOUND_PATTERNS)


def derive_target_key(payload: dict[str, Any], normalized_target: str) -> str:
    explicit_target_key = str(payload.get("target_key") or "").strip()
    if explicit_target_key:
        return explicit_target_key
    if normalized_target.startswith("@"):
        return normalized_target[1:].lower()
    return normalized_target.lower()


def parse_positive_int(raw_value: Any, *, field_name: str) -> int:
    try:
        value = int(str(raw_value).strip())
    except Exception as exc:
        raise PayloadValidationError(f"{field_name} must be a positive integer.") from exc

    if value <= 0:
        raise PayloadValidationError(f"{field_name} must be a positive integer.")

    return value


def parse_checkpoint_message_id(raw_value: Any) -> int | None:
    if raw_value in (None, ""):
        return None
    return parse_positive_int(raw_value, field_name="checkpoint_message_id")


def normalize_freeze_lookup_key(raw_value: Any) -> str:
    value = str(raw_value or "").strip().lower()
    if not value:
        return ""
    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    if value.startswith("s/"):
        value = value[2:]
    if value.startswith("@"):
        value = value[1:]
    parts = [part for part in value.split("/") if part]
    return parts[0] if parts else value


def parse_max_message_id(raw_value: Any) -> int | None:
    if raw_value in (None, ""):
        return None
    return parse_positive_int(raw_value, field_name="max_message_id")


def parse_optional_positive_int(raw_value: Any) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        value = int(str(raw_value).strip())
    except Exception:
        return None
    return value if value > 0 else None


def iter_freeze_source_objects(raw_freeze: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_freeze, dict):
        return []
    raw_sources = raw_freeze.get("sources")
    if isinstance(raw_sources, list):
        return [source for source in raw_sources if isinstance(source, dict)]
    if isinstance(raw_sources, dict):
        return [source for source in raw_sources.values() if isinstance(source, dict)]
    if any(
        field in raw_freeze
        for field in ("upper_message_id", "max_message_id", "source_key", "target_key", "telegram_public")
    ):
        return [raw_freeze]
    return []


def iter_product_row_fetch_freeze_sources(raw_state: dict[str, Any]) -> list[dict[str, Any]]:
    raw_freeze = raw_state.get("fetch_freeze") or raw_state.get("product_row_fetch_freeze")
    return iter_freeze_source_objects(raw_freeze)


def freeze_lookup_keys(payload: dict[str, Any], target_request: dict[str, Any]) -> set[str]:
    lookup_keys = {
        normalize_freeze_lookup_key(payload.get("source_key")),
        normalize_freeze_lookup_key(payload.get("target_key")),
        normalize_freeze_lookup_key(payload.get("target_lookup_key")),
        normalize_freeze_lookup_key(payload.get("telegram_target")),
        normalize_freeze_lookup_key(target_request.get("telegram_public")),
    }
    lookup_keys.discard("")
    return lookup_keys


def freeze_source_matches(source: dict[str, Any], lookup_keys: set[str]) -> bool:
    source_keys = {
        normalize_freeze_lookup_key(source.get("source_key")),
        normalize_freeze_lookup_key(source.get("target_key")),
        normalize_freeze_lookup_key(source.get("target_lookup_key")),
        normalize_freeze_lookup_key(source.get("telegram_public")),
        normalize_freeze_lookup_key(source.get("telegram_target")),
    }
    source_keys.discard("")
    return bool(lookup_keys.intersection(source_keys))


def normalize_product_row_freeze_source(source: dict[str, Any]) -> dict[str, Any] | None:
    if source.get("exact_message_request") is True:
        return None
    upper_message_id = parse_optional_positive_int(
        source.get("upper_message_id")
        if source.get("upper_message_id") not in (None, "")
        else source.get("max_message_id")
    )
    if upper_message_id is None:
        return None
    normalized = dict(source)
    normalized["upper_message_id"] = upper_message_id
    normalized["exact_message_request"] = False
    return normalized


def resolve_product_row_freeze_source(
    payload: dict[str, Any],
    target_request: dict[str, Any],
) -> dict[str, Any] | None:
    lookup_keys = freeze_lookup_keys(payload, target_request)
    if not lookup_keys:
        return None

    state_path = str(
        payload.get("llm_product_row_continuation_state_path")
        or payload.get("product_row_continuation_state_path")
        or ""
    ).strip()
    if state_path:
        try:
            raw_state = json.loads(Path(state_path).read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            raw_state = {}
        except Exception as exc:
            raise PayloadValidationError(f"llm_product_row_continuation_state_path is not readable JSON: {exc}") from exc
        if isinstance(raw_state, dict):
            for raw_source in iter_product_row_fetch_freeze_sources(raw_state):
                source = normalize_product_row_freeze_source(raw_source)
                if source is not None and freeze_source_matches(source, lookup_keys):
                    return source

    for raw_freeze in (payload.get("product_row_fetch_freeze"), payload.get("llm_product_row_fetch_freeze")):
        for raw_source in iter_freeze_source_objects(raw_freeze):
            source = normalize_product_row_freeze_source(raw_source)
            if source is not None and freeze_source_matches(source, lookup_keys):
                return source
    return None


def resolve_product_row_freeze_max_message_id(
    payload: dict[str, Any],
    target_request: dict[str, Any],
) -> int | None:
    direct_value = (
        payload.get("max_message_id")
        if payload.get("max_message_id") not in (None, "")
        else payload.get("fetch_max_message_id")
    )
    direct_max_message_id = parse_max_message_id(direct_value)
    if direct_max_message_id is not None:
        return direct_max_message_id

    source = resolve_product_row_freeze_source(payload, target_request)
    return int(source["upper_message_id"]) if source is not None else None


def resolve_product_row_freeze_lower_bound(
    source: dict[str, Any] | None,
) -> tuple[datetime | None, int | None, str]:
    if not source:
        return None, None, ""
    cutoff_utc = parse_iso_utc(source.get("cutoff_utc"))
    if cutoff_utc is not None:
        return cutoff_utc, parse_optional_positive_int(source.get("lower_message_id")), "cutoff_utc"
    oldest_post_utc = parse_iso_utc(source.get("oldest_post_utc"))
    if oldest_post_utc is not None:
        return oldest_post_utc, parse_optional_positive_int(source.get("lower_message_id")), "oldest_post_utc"
    lower_message_id = parse_optional_positive_int(source.get("lower_message_id"))
    if lower_message_id is not None:
        return None, lower_message_id, "lower_message_id"
    return None, None, ""


def build_fetch_freeze(
    *,
    payload: dict[str, Any],
    target_request: dict[str, Any],
    stats: dict[str, Any],
    max_message_id: int | None,
    cutoff_utc: datetime,
    cutoff_meta: dict[str, Any],
) -> dict[str, Any]:
    if target_request["exact_message_request"]:
        return {}
    observed_upper = stats.get("upper_message_id_observed")
    upper_message_id = max_message_id or (int(observed_upper) if observed_upper else None)
    if not upper_message_id:
        return {}
    source_key = str(payload.get("source_key") or payload.get("target_key") or "").strip()
    target_key = str(payload.get("target_key") or source_key or "").strip()
    return {
        "version": "product_row_fetch_freeze_v1",
        "source_key": source_key,
        "target_key": target_key,
        "target_lookup_key": str(payload.get("target_lookup_key") or "").strip(),
        "telegram_public": target_request["telegram_public"],
        "telegram_target": target_request["telegram_target"],
        "exact_message_request": False,
        "upper_message_id": upper_message_id,
        "max_message_id_applied": max_message_id,
        "newer_posts_skipped": int(stats.get("messages_newer_than_max_message_id_skipped") or 0),
        "posts_emitted": int(stats.get("posts_emitted") or 0),
        "cutoff_utc": iso_utc(cutoff_utc),
        "cutoff_utc_source": str(cutoff_meta.get("cutoff_utc_source") or "request"),
        "oldest_post_utc": str(stats.get("oldest_post_utc") or ""),
        "lower_message_id": stats.get("lower_message_id_observed"),
        "lower_message_id_applied": stats.get("lower_message_id_used"),
        "newest_post_utc": str(stats.get("newest_post_utc") or ""),
        "stopped_reason": str(stats.get("stopped_reason") or ""),
    }


def resolve_cutoff(payload: dict[str, Any]) -> tuple[datetime, dict[str, Any]]:
    since_date_raw = payload.get("since_date")
    if since_date_raw not in (None, ""):
        since_date = str(since_date_raw).strip()
        try:
            parsed = date.fromisoformat(since_date)
        except ValueError as exc:
            raise PayloadValidationError("since_date must use YYYY-MM-DD format.") from exc
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC), {"since_date": since_date}

    days_back_raw = payload.get("days_back")
    if days_back_raw not in (None, ""):
        days_back = parse_positive_int(days_back_raw, field_name="days_back")
        return now_utc() - timedelta(days=days_back), {"days_back": days_back}

    months_back = parse_positive_int(payload.get("months_back", 2), field_name="months_back")
    return now_utc() - timedelta(days=months_back * 30), {"months_back": months_back}


def get_timezone(name: str | None) -> tuple[tzinfo, str, list[str]]:
    warnings: list[str] = []
    tz_name = (name or "UTC").strip() or "UTC"
    try:
        zone = ZoneInfo(tz_name)
        return zone, str(zone), warnings
    except Exception:
        warnings.append(f"Unknown timezone '{tz_name}', falling back to UTC.")
        return timezone.utc, "UTC", warnings


def describe_entity(entity: Any) -> tuple[str, str]:
    if getattr(entity, "broadcast", False):
        return "channel", "channel"
    if getattr(entity, "megagroup", False):
        return "supergroup", "group"
    if entity.__class__.__name__.lower() == "chat":
        return "group", "group"
    class_name = entity.__class__.__name__.lower()
    return class_name, class_name


async def resolve_sender_info(message: Any, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    post_author = (getattr(message, "post_author", None) or "").strip()
    sender_id = getattr(message, "sender_id", None)
    cache_key = f"id:{sender_id}" if sender_id is not None else f"author:{post_author}"

    if cache_key in cache:
        cached = dict(cache[cache_key])
        if post_author and not cached.get("post_author"):
            cached["post_author"] = post_author
        cached.setdefault("sender_phone", "")
        return cached

    info = {
        "sender_id": str(sender_id or ""),
        "sender_kind": "",
        "sender_title": post_author,
        "sender_username": "",
        "sender_profile_url": "",
        "sender_phone": "",
        "post_author": post_author,
    }

    try:
        sender = await message.get_sender()
    except Exception:
        sender = None

    if sender is not None:
        sender_username = getattr(sender, "username", None) or ""
        sender_title = getattr(sender, "title", None) or ""
        sender_phone = normalize_phone(getattr(sender, "phone", None) or "")
        if not sender_title:
            first_name = getattr(sender, "first_name", None) or ""
            last_name = getattr(sender, "last_name", None) or ""
            sender_title = " ".join(part for part in (first_name, last_name) if part).strip()

        info.update(
            {
                "sender_id": str(getattr(sender, "id", None) or sender_id or ""),
                "sender_kind": sender.__class__.__name__.lower(),
                "sender_title": sender_title or post_author,
                "sender_username": sender_username,
                "sender_profile_url": f"https://t.me/{sender_username}" if sender_username else "",
                "sender_phone": sender_phone,
            }
        )

    cache[cache_key] = dict(info)
    return info


def build_stats(
    *,
    checkpoint_message_id: int | None = None,
    exact_message_ids: list[int] | None = None,
    max_message_id: int | None = None,
    lower_message_id: int | None = None,
) -> dict[str, Any]:
    requested_exact_ids = exact_message_ids or []
    return {
        "messages_seen": 0,
        "posts_emitted": 0,
        "duplicates_skipped": 0,
        "service_messages_skipped": 0,
        "messages_newer_than_max_message_id_skipped": 0,
        "stopped_reason": "history_exhausted",
        "oldest_post_utc": "",
        "newest_post_utc": "",
        "checkpoint_message_id_used": checkpoint_message_id,
        "max_message_id_used": max_message_id,
        "lower_message_id_used": lower_message_id,
        "upper_message_id_observed": None,
        "lower_message_id_observed": None,
        "exact_message_request": bool(requested_exact_ids),
        "exact_message_ids_requested": requested_exact_ids,
        "exact_messages_found": 0,
        "exact_messages_missing": 0,
        "exact_message_ids_missing": [],
        "exact_message_statuses": [],
    }


def build_error_payload(
    *,
    payload: dict[str, Any],
    error_type: str,
    error_message: str,
    error_hint: str,
    http_status: int,
    telegram_target_resolved: str = "",
    warnings: list[str] | None = None,
    stats: dict[str, Any] | None = None,
    retry_after_seconds: int | None = None,
    checkpoint_message_id: int | None = None,
    max_message_id: int | None = None,
    max_messages: int | None = None,
    output_timezone: str | None = None,
) -> dict[str, Any]:
    try:
        target_request = parse_telegram_target_request(payload)
    except PayloadValidationError:
        target_request = {
            "telegram_target": normalize_target(payload.get("telegram_target")),
            "telegram_public": "",
            "exact_message_request": False,
            "exact_message_ids": [],
            "exact_post_urls": [],
        }
    normalized_target = target_request["telegram_target"]
    result: dict[str, Any] = {
        "ok": False,
        "status": "error",
        "run_id": str(payload.get("run_id") or ""),
        "started_at": str(payload.get("started_at") or ""),
        "telegram_target_input": str(payload.get("telegram_target") or ""),
        "telegram_target_resolved": telegram_target_resolved,
        "target_key": derive_target_key(payload, normalized_target),
        "output_timezone": output_timezone or str(payload.get("output_timezone") or "UTC"),
        "stats": stats or build_stats(checkpoint_message_id=checkpoint_message_id),
        "posts": [],
        "warnings": warnings or [],
        "checkpoint_message_id": checkpoint_message_id,
        "max_message_id": max_message_id,
        "max_messages": max_messages if max_messages is not None else payload.get("max_messages"),
        "google_sheet_id": str(payload.get("google_sheet_id") or ""),
        "posts_sheet_name": str(payload.get("posts_sheet_name") or "telegram_posts"),
        "runs_sheet_name": str(payload.get("runs_sheet_name") or "telegram_runs"),
        "http_status": http_status,
        "error_type": error_type,
        "error_message": error_message,
        "error_hint": error_hint,
        "telegram_public": target_request["telegram_public"],
        "exact_message_request": target_request["exact_message_request"],
        "exact_message_ids": target_request["exact_message_ids"],
        "exact_post_urls": target_request["exact_post_urls"],
    }

    if retry_after_seconds is not None:
        result["retry_after_seconds"] = retry_after_seconds

    for field_name in ("since_date", "days_back", "months_back"):
        field_value = payload.get(field_name)
        if field_value not in (None, ""):
            result[field_name] = field_value

    return result


def build_post_row(
    *,
    entity_id: Any,
    entity_title: str,
    entity_kind: str,
    entity_kind_label: str,
    entity_username: str,
    message: Any,
    output_timezone: tzinfo,
    sender_info: dict[str, Any],
) -> dict[str, Any]:
    message_dt_utc = message.date.astimezone(UTC)
    message_dt_local = message_dt_utc.astimezone(output_timezone)
    normalized_text = normalize_text(getattr(message, "message", None))
    iso_year, iso_week, _ = message_dt_local.isocalendar()
    replies = getattr(getattr(message, "replies", None), "replies", None)
    media = getattr(message, "media", None)
    grouped_id = getattr(message, "grouped_id", None)
    post_key = f"tg:{entity_id}:{message.id}"

    return {
        "chat_id": str(entity_id),
        "chat_title": entity_title,
        "chat_kind": entity_kind,
        "chat_kind_label": entity_kind_label,
        "message_id": int(message.id),
        "post_key": post_key,
        "post_url": f"https://t.me/{entity_username}/{message.id}" if entity_username else "",
        "posted_at_utc": iso_utc(message_dt_utc),
        "posted_at_local": message_dt_local.replace(microsecond=0).isoformat(),
        "posted_year": message_dt_local.year,
        "posted_month": f"{message_dt_local.month:02d}",
        "posted_day": f"{message_dt_local.day:02d}",
        "posted_year_month": f"{message_dt_local.year}-{message_dt_local.month:02d}",
        "posted_iso_week": f"{iso_year}-W{iso_week:02d}",
        "text": getattr(message, "message", None) or "",
        "text_normalized": normalized_text,
        "text_length": len(normalized_text),
        "has_media": bool(media),
        "media_type": media.__class__.__name__ if media else "",
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "replies": replies,
        "grouped_id": str(grouped_id) if grouped_id is not None else None,
        "sender_id": sender_info["sender_id"],
        "sender_kind": sender_info["sender_kind"],
        "sender_title": sender_info["sender_title"],
        "sender_username": sender_info["sender_username"],
        "sender_profile_url": sender_info["sender_profile_url"],
        "sender_phone": sender_info["sender_phone"],
        "post_author": sender_info["post_author"],
    }


def load_telethon_dependencies() -> dict[str, Any]:
    try:
        from telethon import TelegramClient
        from telethon.errors import (
            ChannelPrivateError,
            FloodWaitError,
            InviteHashExpiredError,
            InviteHashInvalidError,
            RPCError,
            SessionPasswordNeededError,
            UsernameInvalidError,
            UsernameNotOccupiedError,
        )
        from telethon.sessions import StringSession
        from telethon.tl.types import MessageService
    except Exception as exc:
        raise RuntimeError(f"Telethon dependencies are unavailable: {exc}") from exc

    return {
        "TelegramClient": TelegramClient,
        "StringSession": StringSession,
        "MessageService": MessageService,
        "ChannelPrivateError": ChannelPrivateError,
        "FloodWaitError": FloodWaitError,
        "InviteHashExpiredError": InviteHashExpiredError,
        "InviteHashInvalidError": InviteHashInvalidError,
        "RPCError": RPCError,
        "SessionPasswordNeededError": SessionPasswordNeededError,
        "UsernameInvalidError": UsernameInvalidError,
        "UsernameNotOccupiedError": UsernameNotOccupiedError,
    }


async def fetch_history(payload: dict[str, Any]) -> dict[str, Any]:
    api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    session_string = os.getenv("TG_SESSION_STRING", "").strip()

    if not api_id or not api_hash or not session_string:
        missing = [
            name
            for name, value in (
                ("TG_API_ID", api_id),
                ("TG_API_HASH", api_hash),
                ("TG_SESSION_STRING", session_string),
            )
            if not value
        ]
        return build_error_payload(
            payload=payload,
            error_type="missing_environment",
            error_message=f"Missing required environment variables: {', '.join(missing)}",
            error_hint="Set Telegram user API credentials and the StringSession on the host where the helper runs.",
            http_status=500,
        )

    try:
        target_request = parse_telegram_target_request(payload)
    except PayloadValidationError as exc:
        return build_error_payload(
            payload=payload,
            error_type="invalid_input",
            error_message=str(exc),
            error_hint="Check exact Telegram message id fields and t.me post URL format.",
            http_status=400,
        )

    telegram_target = target_request["telegram_target"]
    if not telegram_target:
        return build_error_payload(
            payload=payload,
            error_type="invalid_input",
            error_message="telegram_target is empty or unsupported.",
            error_hint="Use @username, https://t.me/username or https://t.me/s/username.",
            http_status=400,
        )

    try:
        max_messages = parse_positive_int(payload.get("max_messages", 5000), field_name="max_messages")
        exact_message_ids = target_request["exact_message_ids"]
        checkpoint_message_id = (
            None
            if exact_message_ids
            else parse_checkpoint_message_id(payload.get("checkpoint_message_id"))
        )
        product_row_freeze_source = None if exact_message_ids else resolve_product_row_freeze_source(payload, target_request)
        max_message_id = (
            None
            if exact_message_ids
            else resolve_product_row_freeze_max_message_id(payload, target_request)
        )
        cutoff_utc, cutoff_meta = resolve_cutoff(payload)
        freeze_cutoff_utc, freeze_lower_message_id, freeze_lower_bound_source = resolve_product_row_freeze_lower_bound(
            product_row_freeze_source
        )
        if product_row_freeze_source and max_message_id and not freeze_lower_bound_source:
            cutoff_meta["cutoff_utc_source"] = "missing_product_row_fetch_freeze_lower_bound"
        elif freeze_cutoff_utc is not None:
            cutoff_utc = freeze_cutoff_utc
            cutoff_meta["cutoff_utc_source"] = f"product_row_fetch_freeze.{freeze_lower_bound_source}"
        elif freeze_lower_message_id is not None:
            cutoff_utc = datetime(1970, 1, 1, tzinfo=UTC)
            cutoff_meta["cutoff_utc_source"] = "product_row_fetch_freeze.lower_message_id"
    except PayloadValidationError as exc:
        return build_error_payload(
            payload=payload,
            error_type="invalid_input",
            error_message=str(exc),
            error_hint="Check cutoff policy, checkpoint_message_id and max_messages in the helper payload.",
            http_status=400,
        )

    output_timezone, output_timezone_name, warnings = get_timezone(str(payload.get("output_timezone", "UTC")))
    stats = build_stats(
        checkpoint_message_id=checkpoint_message_id,
        exact_message_ids=target_request["exact_message_ids"],
        max_message_id=max_message_id,
        lower_message_id=freeze_lower_message_id,
    )

    if product_row_freeze_source and max_message_id and not freeze_lower_bound_source:
        stats["stopped_reason"] = "product_row_fetch_freeze_missing_lower_bound"
        result = build_error_payload(
            payload=payload,
            error_type="product_row_fetch_freeze_missing_lower_bound",
            error_message=(
                "Saved product-row fetch freeze has an upper message id but no deterministic lower-bound "
                "evidence for this source."
            ),
            error_hint=(
                "Retry from a continuation state that includes cutoff_utc, oldest_post_utc, or lower_message_id "
                "for every full-public frozen source, or start a fresh product-row chunk state."
            ),
            http_status=409,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
        result["fetch_freeze"] = dict(product_row_freeze_source)
        result["product_row_fetch_freeze_error"] = {
            "reason": "missing_lower_bound",
            "required_lower_bound_fields": ["cutoff_utc", "oldest_post_utc", "lower_message_id"],
            "source_key": str(product_row_freeze_source.get("source_key") or ""),
            "target_key": str(product_row_freeze_source.get("target_key") or ""),
            "telegram_public": str(product_row_freeze_source.get("telegram_public") or ""),
            "upper_message_id": max_message_id,
        }
        return result

    try:
        deps = load_telethon_dependencies()
    except RuntimeError as exc:
        return build_error_payload(
            payload=payload,
            error_type="telethon_import_failed",
            error_message=str(exc),
            error_hint="Install Telethon dependencies on the host before invoking the helper.",
            http_status=500,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )

    TelegramClient = deps["TelegramClient"]
    StringSession = deps["StringSession"]
    MessageService = deps["MessageService"]
    ChannelPrivateError = deps["ChannelPrivateError"]
    FloodWaitError = deps["FloodWaitError"]
    InviteHashExpiredError = deps["InviteHashExpiredError"]
    InviteHashInvalidError = deps["InviteHashInvalidError"]
    RPCError = deps["RPCError"]
    SessionPasswordNeededError = deps["SessionPasswordNeededError"]
    UsernameInvalidError = deps["UsernameInvalidError"]
    UsernameNotOccupiedError = deps["UsernameNotOccupiedError"]

    try:
        client = TelegramClient(StringSession(session_string), int(api_id), api_hash)
    except Exception as exc:
        return build_error_payload(
            payload=payload,
            error_type="telegram_client_init_failed",
            error_message=str(exc),
            error_hint="Check TG_API_ID, TG_API_HASH and TG_SESSION_STRING.",
            http_status=500,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )

    posts: list[dict[str, Any]] = []
    seen_post_keys: set[str] = set()
    sender_cache: dict[str, dict[str, Any]] = {}

    try:
        async with client:
            entity = await client.get_entity(telegram_target)
            entity_kind, entity_kind_label = describe_entity(entity)
            entity_username = getattr(entity, "username", None) or ""
            entity_title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or ""
            entity_id = getattr(entity, "id", "")
            resolved_target = f"@{entity_username}" if entity_username else str(entity_id)

            if target_request["exact_message_ids"]:
                fetched_messages = await client.get_messages(entity, ids=target_request["exact_message_ids"])
                if not isinstance(fetched_messages, (list, tuple)):
                    fetched_messages = [fetched_messages]
                messages_by_id = {
                    int(message.id): message
                    for message in fetched_messages
                    if message is not None and getattr(message, "id", None) is not None
                }

                for requested_id in target_request["exact_message_ids"]:
                    stats["messages_seen"] += 1
                    requested_url = (
                        f"https://t.me/{entity_username or target_request['telegram_public']}/{requested_id}"
                        if entity_username or target_request["telegram_public"]
                        else ""
                    )
                    message = messages_by_id.get(requested_id)
                    if message is None:
                        stats["exact_messages_missing"] += 1
                        stats["exact_message_ids_missing"].append(requested_id)
                        stats["exact_message_statuses"].append(
                            {
                                "message_id": requested_id,
                                "post_url": requested_url,
                                "status": "missing",
                            }
                        )
                        continue
                    if isinstance(message, MessageService):
                        stats["service_messages_skipped"] += 1
                        stats["exact_message_statuses"].append(
                            {
                                "message_id": requested_id,
                                "post_url": requested_url,
                                "status": "service_message_skipped",
                            }
                        )
                        continue

                    post_key = f"tg:{entity_id}:{message.id}"
                    if post_key in seen_post_keys:
                        stats["duplicates_skipped"] += 1
                        continue

                    seen_post_keys.add(post_key)
                    stats["exact_messages_found"] += 1
                    stats["exact_message_statuses"].append(
                        {
                            "message_id": requested_id,
                            "post_url": requested_url,
                            "status": "fetched",
                        }
                    )
                    sender_info = await resolve_sender_info(message, sender_cache)
                    posts.append(
                        build_post_row(
                            entity_id=entity_id,
                            entity_title=entity_title,
                            entity_kind=entity_kind,
                            entity_kind_label=entity_kind_label,
                            entity_username=entity_username or target_request["telegram_public"],
                            message=message,
                            output_timezone=output_timezone,
                            sender_info=sender_info,
                        )
                    )
            else:
                history_kwargs: dict[str, Any] = {"limit": max_messages}
                if max_message_id:
                    history_kwargs["max_id"] = max_message_id + 1
                if freeze_lower_message_id and freeze_lower_message_id > 1:
                    history_kwargs["min_id"] = freeze_lower_message_id - 1
                async for message in client.iter_messages(entity, **history_kwargs):
                    stats["messages_seen"] += 1
                    message_id = int(message.id)
                    observed_upper = stats.get("upper_message_id_observed")
                    stats["upper_message_id_observed"] = (
                        message_id
                        if not observed_upper
                        else max(int(observed_upper), message_id)
                    )

                    message_dt_utc = message.date.astimezone(UTC)
                    if checkpoint_message_id and message_id <= checkpoint_message_id:
                        stats["stopped_reason"] = "checkpoint_reached"
                        break
                    if max_message_id and message_id > max_message_id:
                        stats["messages_newer_than_max_message_id_skipped"] += 1
                        continue
                    if freeze_lower_message_id and message_id < freeze_lower_message_id:
                        stats["stopped_reason"] = "freeze_lower_message_id_reached"
                        break
                    if message_dt_utc < cutoff_utc:
                        stats["stopped_reason"] = "cutoff_reached"
                        break

                    if isinstance(message, MessageService):
                        stats["service_messages_skipped"] += 1
                        continue

                    post_key = f"tg:{entity_id}:{message.id}"
                    if post_key in seen_post_keys:
                        stats["duplicates_skipped"] += 1
                        continue

                    seen_post_keys.add(post_key)
                    sender_info = await resolve_sender_info(message, sender_cache)
                    posts.append(
                        build_post_row(
                            entity_id=entity_id,
                            entity_title=entity_title,
                            entity_kind=entity_kind,
                            entity_kind_label=entity_kind_label,
                            entity_username=entity_username,
                            message=message,
                            output_timezone=output_timezone,
                            sender_info=sender_info,
                        )
                    )

            posts.sort(key=lambda row: (row["posted_at_utc"], row["message_id"]))
            stats["posts_emitted"] = len(posts)
            if posts:
                stats["oldest_post_utc"] = posts[0]["posted_at_utc"]
                stats["newest_post_utc"] = posts[-1]["posted_at_utc"]
                message_ids = [int(row["message_id"]) for row in posts if row.get("message_id") is not None]
                if message_ids:
                    stats["lower_message_id_observed"] = min(message_ids)
            if target_request["exact_message_ids"]:
                if stats["exact_messages_missing"] > 0:
                    stats["stopped_reason"] = "exact_messages_partial"
                elif stats["exact_messages_found"] > 0:
                    stats["stopped_reason"] = "exact_messages_fetched"
                else:
                    stats["stopped_reason"] = "exact_messages_missing"
            elif stats["stopped_reason"] == "history_exhausted":
                stats["stopped_reason"] = "no_matching_posts"

            exact_messages_missing = bool(
                target_request["exact_message_ids"] and stats["exact_messages_missing"] > 0
            )
            result: dict[str, Any] = {
                "ok": not exact_messages_missing,
                "status": "partial_success" if exact_messages_missing else "success",
                "run_id": str(payload.get("run_id") or ""),
                "started_at": str(payload.get("started_at") or ""),
                "telegram_target_input": str(payload.get("telegram_target") or ""),
                "telegram_target_resolved": resolved_target,
                "target_key": derive_target_key(payload, telegram_target),
                "output_timezone": output_timezone_name,
                "stats": stats,
                "posts": posts,
                "warnings": warnings,
                "checkpoint_message_id": checkpoint_message_id,
                "max_message_id": max_message_id,
                "max_messages": max_messages,
                "google_sheet_id": str(payload.get("google_sheet_id") or ""),
                "posts_sheet_name": str(payload.get("posts_sheet_name") or "telegram_posts"),
                "runs_sheet_name": str(payload.get("runs_sheet_name") or "telegram_runs"),
                "cutoff_utc": iso_utc(cutoff_utc),
                "telegram_public": target_request["telegram_public"],
                "exact_message_request": target_request["exact_message_request"],
                "exact_message_ids": target_request["exact_message_ids"],
                "exact_post_urls": target_request["exact_post_urls"],
                "entity": {
                    "chat_id": str(entity_id),
                    "chat_title": entity_title,
                    "chat_kind": entity_kind,
                    "chat_username": entity_username,
                },
            }
            fetch_freeze = build_fetch_freeze(
                payload=payload,
                target_request=target_request,
                stats=stats,
                max_message_id=max_message_id,
                cutoff_utc=cutoff_utc,
                cutoff_meta=cutoff_meta,
            )
            if fetch_freeze:
                result["fetch_freeze"] = fetch_freeze
            if exact_messages_missing:
                result.update(
                    {
                        "http_status": 404,
                        "error_type": "telegram_exact_messages_missing",
                        "error_message": (
                            "Requested exact Telegram message ids were not returned: "
                            + ", ".join(str(value) for value in stats["exact_message_ids_missing"])
                        ),
                        "error_hint": "The message may be deleted, private, outside account access, or not available through this Telegram entity.",
                    }
                )
            result.update(cutoff_meta)
            return result
    except FloodWaitError as exc:
        return build_error_payload(
            payload=payload,
            error_type="telegram_flood_wait",
            error_message=str(exc),
            error_hint="Telegram rate limited the account. Wait and rerun after retry_after_seconds.",
            http_status=429,
            warnings=warnings,
            stats=stats,
            retry_after_seconds=int(getattr(exc, "seconds", 0) or 0),
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
    except (UsernameInvalidError, UsernameNotOccupiedError) as exc:
        return build_error_payload(
            payload=payload,
            error_type="telegram_target_not_found",
            error_message=str(exc),
            error_hint="Check the public username or t.me link. Private targets are not supported by username lookup.",
            http_status=404,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
    except ValueError as exc:
        if is_target_not_found_value_error(exc):
            return build_error_payload(
                payload=payload,
                error_type="telegram_target_not_found",
                error_message=str(exc),
                error_hint="Check the public username or t.me link. Private targets are not supported by username lookup.",
                http_status=404,
                warnings=warnings,
                stats=stats,
                checkpoint_message_id=checkpoint_message_id,
                max_message_id=max_message_id,
                max_messages=max_messages,
                output_timezone=output_timezone_name,
            )
        return build_error_payload(
            payload=payload,
            error_type="unexpected_fetch_error",
            error_message=str(exc),
            error_hint="Inspect the workflow execution data and helper payload, then rerun with the exact error attached.",
            http_status=500,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
    except (InviteHashInvalidError, InviteHashExpiredError) as exc:
        return build_error_payload(
            payload=payload,
            error_type="telegram_invite_invalid",
            error_message=str(exc),
            error_hint="This helper supports public usernames and public t.me links, not expired invite links.",
            http_status=400,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
    except ChannelPrivateError as exc:
        return build_error_payload(
            payload=payload,
            error_type="telegram_private_or_no_access",
            error_message=str(exc),
            error_hint="The account behind TG_SESSION_STRING does not have access to this chat history.",
            http_status=403,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
    except SessionPasswordNeededError as exc:
        return build_error_payload(
            payload=payload,
            error_type="telegram_session_needs_password",
            error_message=str(exc),
            error_hint="Recreate TG_SESSION_STRING with the separate session bootstrap helper and complete the 2FA step.",
            http_status=401,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
    except RPCError as exc:
        return build_error_payload(
            payload=payload,
            error_type="telegram_rpc_error",
            error_message=str(exc),
            error_hint="Telegram returned an RPC error. Recheck target access, session validity and API credentials.",
            http_status=502,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )
    except Exception as exc:
        return build_error_payload(
            payload=payload,
            error_type="unexpected_fetch_error",
            error_message=str(exc),
            error_hint="Inspect the workflow execution data and helper payload, then rerun with the exact error attached.",
            http_status=500,
            warnings=warnings,
            stats=stats,
            checkpoint_message_id=checkpoint_message_id,
            max_message_id=max_message_id,
            max_messages=max_messages,
            output_timezone=output_timezone_name,
        )


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Telegram public history and emit one greenfield fetch envelope."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--payload-b64url", help="Base64url-encoded JSON payload")
    input_group.add_argument("--input-path", help="Path to a JSON payload file")
    parser.add_argument("--output-path", help="Optional path to write the fetch envelope JSON instead of stdout.")
    args = parser.parse_args()

    try:
        payload = load_payload_file(args.input_path) if args.input_path else load_payload(args.payload_b64url)
    except Exception as exc:
        write_output(
            compact_json(
                build_error_payload(
                    payload={},
                    error_type="invalid_payload",
                    error_message=str(exc),
                    error_hint="The caller built a malformed base64url JSON payload for the fetch helper.",
                    http_status=400,
                )
            ),
            args.output_path,
        )
        return 0

    result = await fetch_history(payload)
    write_output(compact_json(result), args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
