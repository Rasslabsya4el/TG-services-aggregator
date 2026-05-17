from __future__ import annotations

import hashlib
import json
from typing import Any

from .contacts import extract_contacts
from .heuristics import extract_city_signal, extract_price_signals, extract_role_category_hints
from .normalization import normalize_handle, normalize_phone, normalize_text, normalize_text_hash, normalize_url, normalize_website


PROCESSOR_VERSION = "extr_layer_01_v1"
WORKFLOW_STAGE = "extract_deterministic"
INPUT_SHAPE = "wf_fetch_03_aggregate_raw_posts_v1"


def compact_json(payload: dict[str, Any], *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _derive_raw_post_id(raw_post: dict[str, Any]) -> str:
    explicit_raw_post_id = _as_text(raw_post.get("raw_post_id")).strip()
    if explicit_raw_post_id:
        return explicit_raw_post_id

    explicit_post_key = _as_text(raw_post.get("post_key")).strip()
    if explicit_post_key:
        return explicit_post_key

    chat_id = str(raw_post.get("chat_id") or "").strip()
    message_id = str(raw_post.get("message_id") or "").strip()
    if chat_id and message_id:
        return f"tg:{chat_id}:{message_id}"

    return ""


def _derive_source_channel_key(raw_post: dict[str, Any]) -> str:
    explicit_source_key = _as_text(raw_post.get("source_channel_key")).strip()
    if explicit_source_key:
        return explicit_source_key

    chat_username = _as_text(raw_post.get("chat_username")).strip().lower()
    if chat_username:
        return chat_username

    return str(raw_post.get("chat_id") or "").strip()


def _build_author_signals(raw_post: dict[str, Any]) -> dict[str, Any]:
    return {
        "sender_id": raw_post.get("sender_id"),
        "sender_kind": raw_post.get("sender_kind"),
        "sender_title": raw_post.get("sender_title"),
        "sender_username": _as_text(raw_post.get("sender_username")).strip(),
        "sender_profile_url": _as_text(raw_post.get("sender_profile_url")).strip(),
        "sender_phone": normalize_phone(_as_text(raw_post.get("sender_phone"))),
        "post_author": _as_text(raw_post.get("post_author")).strip(),
    }


def _build_identity_signals(
    *,
    contacts: dict[str, list[str]],
    author_signals: dict[str, Any],
    text_hash_normalized: str,
) -> list[str]:
    signals: set[str] = set()

    for phone in contacts["phones"]:
        signals.add(f"phone:{phone}")
    for email in contacts["emails"]:
        signals.add(f"email:{email.lower()}")
    for handle in contacts["telegram_handles"]:
        signals.add(f"tg:{normalize_handle(handle)}")
    for link in contacts["telegram_links"]:
        signals.add(f"tg_link:{normalize_url(link)}")
    for website in contacts["websites"]:
        signals.add(f"site:{normalize_website(website)}")

    sender_username = normalize_handle(author_signals.get("sender_username"))
    if sender_username:
        signals.add(f"tg:{sender_username}")

    sender_profile_url = normalize_url(author_signals.get("sender_profile_url"))
    if sender_profile_url:
        signals.add(f"tg_link:{sender_profile_url}")

    if text_hash_normalized:
        signals.add(f"weak_text:{text_hash_normalized}")

    return sorted(signals)


def _build_content_flags(
    *,
    raw_post: dict[str, Any],
    contacts: dict[str, list[str]],
    role_category_hints: list[dict[str, Any]],
    location_signals: dict[str, Any],
    price_signals: dict[str, Any],
) -> list[str]:
    flags = []
    if raw_post.get("has_media"):
        flags.append("has_media")
    if any(contacts.values()):
        flags.append("has_contacts")
    if role_category_hints:
        flags.append("has_role_hints")
    if location_signals.get("city"):
        flags.append("has_city")
    if price_signals.get("price_texts"):
        flags.append("has_price")
    return flags


def _build_input_fingerprint(
    *,
    raw_post_id: str,
    run_id: str,
    target_key: str,
    text_hash_normalized: str,
) -> str:
    payload = compact_json(
        {
            "raw_post_id": raw_post_id,
            "run_id": run_id,
            "target_key": target_key,
            "text_hash_normalized": text_hash_normalized,
        }
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def extract_structured_post(raw_post: dict[str, Any], aggregate_run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw_post, dict):
        raise ValueError("raw_post item must be a JSON object.")

    raw_post_id = _derive_raw_post_id(raw_post)
    text_raw = _as_text(raw_post.get("text_raw")) or _as_text(raw_post.get("text"))
    if not text_raw:
        text_raw = _as_text(raw_post.get("text_normalized"))

    text_normalized = normalize_text(text_raw)
    text_hash_normalized = normalize_text_hash(text_raw)
    contacts_result = extract_contacts(text_raw)
    contacts = contacts_result.summary()
    role_category_hints = extract_role_category_hints(text_raw)
    location_signals = extract_city_signal(text_raw)
    price_signals = extract_price_signals(text_raw)
    author_signals = _build_author_signals(raw_post)

    run_id = _as_text(raw_post.get("_run_id")).strip() or (aggregate_run_id or "")
    target_key = _as_text(raw_post.get("_target_key")).strip()
    identity_signals = _build_identity_signals(
        contacts=contacts,
        author_signals=author_signals,
        text_hash_normalized=text_hash_normalized,
    )

    text_block = {
        "text_raw": text_raw,
        "text_normalized": text_normalized,
        "text_hash_normalized": text_hash_normalized,
        "text_length": len(text_normalized),
        "content_flags": _build_content_flags(
            raw_post=raw_post,
            contacts=contacts,
            role_category_hints=role_category_hints,
            location_signals=location_signals,
            price_signals=price_signals,
        ),
    }

    return {
        "raw_post_id": raw_post_id,
        "source_platform": "telegram",
        "run_id": run_id,
        "source_ref": {
            "post_key": _as_text(raw_post.get("post_key")).strip() or raw_post_id,
            "chat_id": str(raw_post.get("chat_id") or "").strip(),
            "message_id": raw_post.get("message_id"),
            "source_channel_key": _derive_source_channel_key(raw_post),
            "chat_title": _as_text(raw_post.get("chat_title")).strip(),
            "chat_kind": _as_text(raw_post.get("chat_kind")).strip(),
            "chat_username": _as_text(raw_post.get("chat_username")).strip(),
            "post_url": _as_text(raw_post.get("post_url")).strip(),
            "posted_at_utc": _as_text(raw_post.get("posted_at_utc")).strip(),
        },
        "provenance": {
            "_run_id": _as_text(raw_post.get("_run_id")).strip() or run_id,
            "_target_key": target_key,
            "_telegram_target_input": _as_text(raw_post.get("_telegram_target_input")).strip(),
            "_telegram_target_resolved": _as_text(raw_post.get("_telegram_target_resolved")).strip(),
        },
        "text": text_block,
        "author_signals": author_signals,
        "contacts": contacts,
        "contact_matches": [match.as_dict() for match in contacts_result.matches],
        "role_category_hints": role_category_hints,
        "location_signals": location_signals,
        "price_signals": price_signals,
        "identity_signals": identity_signals,
        "extraction_meta": {
            "stage": WORKFLOW_STAGE,
            "processor_type": "deterministic",
            "processor_version": PROCESSOR_VERSION,
            "input_shape": INPUT_SHAPE,
            "input_fingerprint": _build_input_fingerprint(
                raw_post_id=raw_post_id,
                run_id=run_id,
                target_key=target_key,
                text_hash_normalized=text_hash_normalized,
            ),
            "extractors_triggered": [
                "regex_base",
                "regex_normalized",
                "marker_recovery",
                "role_keyword_scoring",
                "city_keyword_lookup",
                "price_pattern_lookup",
            ],
        },
    }


def extract_structured_posts(aggregate_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(aggregate_payload, dict):
        raise ValueError("Aggregate extraction payload must be a JSON object.")

    raw_posts = aggregate_payload.get("raw_posts")
    if not isinstance(raw_posts, list):
        raise ValueError("Aggregate extraction payload must include raw_posts as a list.")

    aggregate_run_id = _as_text(aggregate_payload.get("run_id")).strip()
    structured_posts = []
    for index, raw_post in enumerate(raw_posts):
        if not isinstance(raw_post, dict):
            raise ValueError(f"raw_posts[{index}] must be a JSON object.")
        structured_posts.append(extract_structured_post(raw_post, aggregate_run_id))

    effective_run_id = aggregate_run_id or next(
        (post["run_id"] for post in structured_posts if post.get("run_id")),
        "",
    )

    return {
        "run_id": effective_run_id,
        "workflow_stage": WORKFLOW_STAGE,
        "extraction_contract_version": PROCESSOR_VERSION,
        "raw_posts_total": len(raw_posts),
        "structured_posts_total": len(structured_posts),
        "structured_posts": structured_posts,
        "fetch_summary": aggregate_payload.get("fetch_summary"),
    }
