from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

import psycopg
from psycopg.types.json import Jsonb


WORKFLOW_STAGE = "db_publish_business_rows"
DB_PUBLISH_CONTRACT_VERSION = "wf_db_publish_28_v1"
DEFAULT_DSN_ENV = "TG_SERVICES_DB_DSN"
ALLOWED_SERBIA_RELEVANCE_VERDICTS = {"", "serbia_relevant", "outside_serbia", "uncertain"}
LEGACY_SERBIA_RELEVANCE_VERDICT_ALIASES = {
    "relevant": "serbia_relevant",
}

SERVICE_RUN_COLUMNS = [
    "run_id",
    "run_status",
    "trigger_type",
    "started_at_utc",
    "finished_at_utc",
    "duration_ms",
    "requested_targets_count",
    "successful_target_count",
    "failed_target_count",
    "sync_mode",
    "max_messages",
    "cutoff_policy_type",
    "cutoff_policy_value",
    "llm_enabled",
    "raw_posts_total",
    "providers_total",
    "offers_total",
    "offers_upserted_total",
    "fetch_messages_seen_total",
    "structured_posts_total",
    "llm_calls_total",
    "llm_tokens_input_total",
    "llm_tokens_output_total",
    "llm_cost_estimate_usd",
    "llm_review_required_count",
    "error_type",
    "error_message",
    "google_sheet_id",
    "providers_sheet_name",
    "offers_sheet_name",
    "requested_targets_json",
    "successful_targets_json",
    "failed_targets_json",
    "warnings_json",
    "checkpoint_targets_json",
    "layer_resolution_counts_json",
    "field_resolution_counts_json",
    "response_json",
]

RUN_TARGET_COLUMNS = [
    "run_id",
    "target_key",
    "target_input",
    "target_resolved",
    "target_status",
    "started_at_utc",
    "finished_at_utc",
    "checkpoint_message_id",
    "raw_posts_emitted",
    "error_type",
    "error_message",
    "target_stats_json",
]

PROVIDER_COLUMNS = [
    "provider_key",
    "provider_state",
    "identity_strength",
    "display_name_best",
    "canonical_name",
    "provider_type",
    "provider_summary",
    "primary_contact_type",
    "primary_contact_value",
    "latest_post_url",
    "first_seen_at_utc",
    "last_seen_at_utc",
    "first_seen_run_id",
    "last_seen_run_id",
    "times_seen",
    "offer_count",
    "dedupe_confidence",
    "provider_merge_override_group",
    "provider_suppression_reason",
    "phones",
    "telegram_handles",
    "telegram_links",
    "instagram_handles",
    "instagram_links",
    "emails",
    "websites",
    "facebook_links",
    "city_codes",
    "service_category_hints",
    "source_channel_keys",
    "provider_quality_flags_json",
]

OFFER_COLUMNS = [
    "offer_key",
    "provider_key",
    "offer_state",
    "service_signature_key",
    "category_primary",
    "category_secondary",
    "title_best",
    "description_best",
    "description_full_best",
    "offer_summary",
    "price_text_best",
    "price_min",
    "price_max",
    "currency_code",
    "latest_post_url",
    "first_seen_at_utc",
    "last_seen_at_utc",
    "first_seen_run_id",
    "last_seen_run_id",
    "times_seen",
    "dedupe_confidence",
    "serbia_relevance_verdict",
    "offer_rejection_reason",
    "offer_merge_override_group",
    "service_tags",
    "city_codes",
    "contact_snapshot_phones",
    "contact_snapshot_telegram_handles",
    "contact_snapshot_telegram_links",
    "source_channel_keys",
    "offer_quality_flags_json",
]

RAW_POST_COLUMNS = [
    "raw_post_id",
    "source_platform",
    "chat_id",
    "message_id",
    "source_channel_key",
    "chat_title",
    "chat_kind",
    "chat_username",
    "post_url",
    "posted_at_utc",
    "text_raw",
    "text_normalized",
    "text_hash_normalized",
    "text_length",
    "has_media",
    "media_type",
    "views",
    "forwards",
    "replies",
    "grouped_id",
    "sender_id",
    "sender_kind",
    "sender_title",
    "sender_username",
    "sender_profile_url",
    "post_author",
    "first_seen_run_id",
    "first_seen_at_utc",
    "last_seen_run_id",
    "last_seen_at_utc",
    "first_seen_target_input",
    "last_seen_target_input",
    "last_seen_target_resolved",
    "output_timezone_last",
    "posted_year_month",
    "posted_iso_week",
    "content_flags_json",
]

PROVIDER_RAW_POST_EVIDENCE_COLUMNS = [
    "provider_key",
    "raw_post_id",
    "first_seen_run_id",
    "last_seen_run_id",
]

OFFER_RAW_POST_EVIDENCE_COLUMNS = [
    "offer_key",
    "raw_post_id",
    "first_seen_run_id",
    "last_seen_run_id",
]

AUDIT_ENRICHMENT_COLUMNS = [
    "audit_row_id",
    "run_id",
    "entity_type",
    "entity_id",
    "stage",
    "processor_type",
    "processor_version",
    "status",
    "decision_code",
    "created_at_utc",
    "input_fingerprint",
    "output_patch_json",
    "reason_text",
    "latency_ms",
    "review_required",
    "attempt_number",
    "model_name",
    "prompt_version",
    "tokens_input",
    "tokens_output",
    "cost_estimate_usd",
    "confidence",
    "response_excerpt",
    "upstream_audit_row_id",
    "superseded_by_audit_row_id",
]

AUDIT_SOURCE_RAW_POST_COLUMNS = [
    "audit_row_id",
    "raw_post_id",
]


def compact_json(payload: dict[str, Any], *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _load_payload(input_path: str | None) -> dict[str, Any]:
    if input_path:
        return json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    return json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))


def _write_output(text: str, output_path: str | None = None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return

    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_nullable_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n", ""}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _nullable_text(value: Any) -> str | None:
    text = _as_text(value)
    return text or None


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_json_maybe(value: Any, *, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _as_json_object(value: Any) -> dict[str, Any]:
    parsed = _parse_json_maybe(value, fallback={})
    return parsed if isinstance(parsed, dict) else {}


def _as_json_array(value: Any) -> list[Any]:
    parsed = _parse_json_maybe(value, fallback=[])
    return parsed if isinstance(parsed, list) else []


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.split("|")]
    elif isinstance(value, list):
        items = [_as_text(item) for item in value]
    else:
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _first_text(*values: Any) -> str:
    for value in values:
        text = _as_text(value)
        if text:
            return text
    return ""


def _parse_iso_datetime(value: str) -> datetime | None:
    normalized = _as_text(value)
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _text_hash_normalized(value: str) -> str:
    normalized = _as_text(value)
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _raw_post_identity(raw_post: dict[str, Any], source_ref: dict[str, Any]) -> tuple[str, str, int | None]:
    raw_post_id = _first_text(
        raw_post.get("raw_post_id"),
        raw_post.get("post_key"),
        source_ref.get("post_key"),
    )
    chat_id = _first_text(raw_post.get("chat_id"), source_ref.get("chat_id"))
    message_id = _as_nullable_int(raw_post.get("message_id") or source_ref.get("message_id"))

    if raw_post_id and (not chat_id or message_id is None):
        parts = raw_post_id.split(":", 2)
        if len(parts) == 3:
            chat_id = chat_id or parts[1]
            message_id = message_id if message_id is not None else _as_nullable_int(parts[2])

    if not raw_post_id and chat_id and message_id is not None:
        raw_post_id = f"tg:{chat_id}:{message_id}"

    return raw_post_id, chat_id, message_id


def _raw_post_periods(raw_post: dict[str, Any], posted_at_utc: str) -> tuple[str, str]:
    posted_year_month = _as_text(raw_post.get("posted_year_month"))
    posted_iso_week = _as_text(raw_post.get("posted_iso_week"))
    if posted_year_month and posted_iso_week:
        return posted_year_month, posted_iso_week

    posted_at = _parse_iso_datetime(posted_at_utc)
    if posted_at is None:
        return posted_year_month, posted_iso_week

    if not posted_year_month:
        posted_year_month = posted_at.strftime("%Y-%m")
    if not posted_iso_week:
        iso_year, iso_week, _ = posted_at.isocalendar()
        posted_iso_week = f"{iso_year}-W{iso_week:02d}"
    return posted_year_month, posted_iso_week


def _normalize_serbia_relevance_verdict(value: Any) -> str:
    normalized = _as_text(value).lower()
    if normalized in LEGACY_SERBIA_RELEVANCE_VERDICT_ALIASES:
        normalized = LEGACY_SERBIA_RELEVANCE_VERDICT_ALIASES[normalized]
    if normalized not in ALLOWED_SERBIA_RELEVANCE_VERDICTS:
        raise ValueError(
            "Unsupported serbia_relevance_verdict for DB publication: "
            f"{normalized or '<blank>'}."
        )
    return normalized


def _build_raw_post_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_posts = payload.get("raw_posts") if isinstance(payload.get("raw_posts"), list) else []
    normalized_request = payload.get("normalized_request") if isinstance(payload.get("normalized_request"), dict) else {}
    service_run_candidate = payload.get("service_run_candidate") if isinstance(payload.get("service_run_candidate"), dict) else {}
    observed_at_utc = _first_text(payload.get("started_at_utc"), service_run_candidate.get("started_at_utc"))
    rows: list[dict[str, Any]] = []

    for raw_post in raw_posts:
        if not isinstance(raw_post, dict):
            continue
        source_ref = raw_post.get("source_ref") if isinstance(raw_post.get("source_ref"), dict) else {}
        text_block = raw_post.get("text") if isinstance(raw_post.get("text"), dict) else {}
        author_signals = raw_post.get("author_signals") if isinstance(raw_post.get("author_signals"), dict) else {}
        provenance = raw_post.get("provenance") if isinstance(raw_post.get("provenance"), dict) else {}
        raw_post_id, chat_id, message_id = _raw_post_identity(raw_post, source_ref)
        if not raw_post_id or not chat_id or message_id is None:
            continue

        posted_at_utc = _first_text(raw_post.get("posted_at_utc"), source_ref.get("posted_at_utc"), observed_at_utc)
        first_seen_run_id = _first_text(
            raw_post.get("first_seen_run_id"),
            raw_post.get("_run_id"),
            provenance.get("_run_id"),
            raw_post.get("run_id"),
            payload.get("run_id"),
        )
        last_seen_run_id = _first_text(
            raw_post.get("last_seen_run_id"),
            raw_post.get("_run_id"),
            provenance.get("_run_id"),
            raw_post.get("run_id"),
            payload.get("run_id"),
            first_seen_run_id,
        )
        first_seen_at_utc = _first_text(raw_post.get("first_seen_at_utc"), observed_at_utc, posted_at_utc)
        last_seen_at_utc = _first_text(raw_post.get("last_seen_at_utc"), observed_at_utc, first_seen_at_utc)
        text_raw = _first_text(raw_post.get("text_raw"), raw_post.get("text"), text_block.get("text_raw"))
        text_normalized = _first_text(raw_post.get("text_normalized"), text_block.get("text_normalized"), text_raw)
        text_hash_normalized = _first_text(
            raw_post.get("text_hash_normalized"),
            text_block.get("text_hash_normalized"),
            _text_hash_normalized(text_normalized),
        )
        text_length = _as_int(raw_post.get("text_length") or text_block.get("text_length"))
        if text_length <= 0 and text_raw:
            text_length = len(text_raw)
        content_flags = raw_post.get("content_flags")
        if content_flags is None:
            content_flags = text_block.get("content_flags")
        posted_year_month, posted_iso_week = _raw_post_periods(raw_post, posted_at_utc)

        rows.append(
            {
                "raw_post_id": raw_post_id,
                "source_platform": _first_text(raw_post.get("source_platform"), "telegram"),
                "chat_id": chat_id,
                "message_id": message_id,
                "source_channel_key": _first_text(raw_post.get("source_channel_key"), source_ref.get("source_channel_key"), chat_id),
                "chat_title": _first_text(raw_post.get("chat_title"), source_ref.get("chat_title")),
                "chat_kind": _first_text(raw_post.get("chat_kind"), source_ref.get("chat_kind")),
                "chat_username": _first_text(raw_post.get("chat_username"), source_ref.get("chat_username")),
                "post_url": _first_text(raw_post.get("post_url"), source_ref.get("post_url")),
                "posted_at_utc": posted_at_utc,
                "text_raw": text_raw,
                "text_normalized": text_normalized,
                "text_hash_normalized": text_hash_normalized,
                "text_length": text_length,
                "has_media": _as_bool(raw_post.get("has_media")),
                "media_type": _as_text(raw_post.get("media_type")),
                "views": _as_int(raw_post.get("views")),
                "forwards": _as_int(raw_post.get("forwards")),
                "replies": _as_int(raw_post.get("replies")),
                "grouped_id": _as_nullable_int(raw_post.get("grouped_id")),
                "sender_id": _first_text(raw_post.get("sender_id"), author_signals.get("sender_id")),
                "sender_kind": _first_text(raw_post.get("sender_kind"), author_signals.get("sender_kind")),
                "sender_title": _first_text(raw_post.get("sender_title"), author_signals.get("sender_title")),
                "sender_username": _first_text(raw_post.get("sender_username"), author_signals.get("sender_username")),
                "sender_profile_url": _first_text(raw_post.get("sender_profile_url"), author_signals.get("sender_profile_url")),
                "post_author": _first_text(raw_post.get("post_author"), author_signals.get("post_author")),
                "first_seen_run_id": first_seen_run_id,
                "first_seen_at_utc": first_seen_at_utc,
                "last_seen_run_id": last_seen_run_id,
                "last_seen_at_utc": last_seen_at_utc,
                "first_seen_target_input": _first_text(
                    raw_post.get("first_seen_target_input"),
                    raw_post.get("_telegram_target_input"),
                    provenance.get("_telegram_target_input"),
                ),
                "last_seen_target_input": _first_text(
                    raw_post.get("last_seen_target_input"),
                    raw_post.get("_telegram_target_input"),
                    provenance.get("_telegram_target_input"),
                ),
                "last_seen_target_resolved": _first_text(
                    raw_post.get("last_seen_target_resolved"),
                    raw_post.get("_telegram_target_resolved"),
                    provenance.get("_telegram_target_resolved"),
                ),
                "output_timezone_last": _first_text(raw_post.get("output_timezone_last"), normalized_request.get("output_timezone")),
                "posted_year_month": posted_year_month,
                "posted_iso_week": posted_iso_week,
                "content_flags_json": _as_json_array(content_flags),
            }
        )
    return _dedupe_rows(rows, lambda row: row["raw_post_id"])


def _build_provider_raw_post_evidence_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    merge_output = payload.get("merge_output") if isinstance(payload.get("merge_output"), dict) else {}
    edge_rows = merge_output.get("provider_raw_post_evidence") if isinstance(merge_output.get("provider_raw_post_evidence"), list) else []
    if edge_rows:
        rows = []
        for edge in edge_rows:
            if not isinstance(edge, dict):
                continue
            rows.append(
                {
                    "provider_key": _as_text(edge.get("provider_key")),
                    "raw_post_id": _as_text(edge.get("raw_post_id")),
                    "first_seen_run_id": _as_text(edge.get("first_seen_run_id") or payload.get("run_id")),
                    "last_seen_run_id": _as_text(edge.get("last_seen_run_id") or payload.get("run_id")),
                }
            )
        return _dedupe_rows(rows, lambda row: (row["provider_key"], row["raw_post_id"]))

    canonical_output = payload.get("canonical_output") if isinstance(payload.get("canonical_output"), dict) else {}
    providers = canonical_output.get("providers") if isinstance(canonical_output.get("providers"), list) else []
    rows = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        provider_key = _as_text(provider.get("provider_key"))
        first_seen_run_id = _as_text(provider.get("first_seen_run_id") or payload.get("run_id"))
        last_seen_run_id = _as_text(provider.get("last_seen_run_id") or payload.get("run_id"))
        for raw_post_id in _as_text_list(provider.get("evidence_raw_post_ids")):
            rows.append(
                {
                    "provider_key": provider_key,
                    "raw_post_id": raw_post_id,
                    "first_seen_run_id": first_seen_run_id,
                    "last_seen_run_id": last_seen_run_id,
                }
            )
    return _dedupe_rows(rows, lambda row: (row["provider_key"], row["raw_post_id"]))


def _build_offer_raw_post_evidence_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    merge_output = payload.get("merge_output") if isinstance(payload.get("merge_output"), dict) else {}
    edge_rows = merge_output.get("offer_raw_post_evidence") if isinstance(merge_output.get("offer_raw_post_evidence"), list) else []
    if edge_rows:
        rows = []
        for edge in edge_rows:
            if not isinstance(edge, dict):
                continue
            rows.append(
                {
                    "offer_key": _as_text(edge.get("offer_key")),
                    "raw_post_id": _as_text(edge.get("raw_post_id")),
                    "first_seen_run_id": _as_text(edge.get("first_seen_run_id") or payload.get("run_id")),
                    "last_seen_run_id": _as_text(edge.get("last_seen_run_id") or payload.get("run_id")),
                }
            )
        return _dedupe_rows(rows, lambda row: (row["offer_key"], row["raw_post_id"]))

    canonical_output = payload.get("canonical_output") if isinstance(payload.get("canonical_output"), dict) else {}
    offers = canonical_output.get("offers") if isinstance(canonical_output.get("offers"), list) else []
    rows = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        offer_key = _as_text(offer.get("offer_key"))
        first_seen_run_id = _as_text(offer.get("first_seen_run_id") or payload.get("run_id"))
        last_seen_run_id = _as_text(offer.get("last_seen_run_id") or payload.get("run_id"))
        for raw_post_id in _as_text_list(offer.get("evidence_raw_post_ids")):
            rows.append(
                {
                    "offer_key": offer_key,
                    "raw_post_id": raw_post_id,
                    "first_seen_run_id": first_seen_run_id,
                    "last_seen_run_id": last_seen_run_id,
                }
            )
    return _dedupe_rows(rows, lambda row: (row["offer_key"], row["raw_post_id"]))


def _build_audit_enrichment_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    audit_rows = payload.get("audit_enrichment_rows") if isinstance(payload.get("audit_enrichment_rows"), list) else []
    rows = []
    for row in audit_rows:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "audit_row_id": _as_text(row.get("audit_row_id")),
                "run_id": _as_text(row.get("run_id") or payload.get("run_id")),
                "entity_type": _as_text(row.get("entity_type")),
                "entity_id": _as_text(row.get("entity_id")),
                "stage": _as_text(row.get("stage")),
                "processor_type": _as_text(row.get("processor_type")),
                "processor_version": _as_text(row.get("processor_version")),
                "status": _as_text(row.get("status")),
                "decision_code": _as_text(row.get("decision_code")),
                "created_at_utc": _first_text(row.get("created_at_utc"), payload.get("started_at_utc")),
                "input_fingerprint": _as_text(row.get("input_fingerprint")),
                "output_patch_json": _as_json_object(row.get("output_patch_json")),
                "reason_text": _as_text(row.get("reason_text")),
                "latency_ms": _as_nullable_int(row.get("latency_ms")),
                "review_required": _as_bool(row.get("review_required")),
                "attempt_number": _as_int(row.get("attempt_number")),
                "model_name": _as_text(row.get("model_name")),
                "prompt_version": _as_text(row.get("prompt_version")),
                "tokens_input": _as_int(row.get("tokens_input")),
                "tokens_output": _as_int(row.get("tokens_output")),
                "cost_estimate_usd": _as_decimal(row.get("cost_estimate_usd")),
                "confidence": _as_decimal(row.get("confidence")),
                "response_excerpt": _as_text(row.get("response_excerpt")),
                "upstream_audit_row_id": _nullable_text(row.get("upstream_audit_row_id")),
                "superseded_by_audit_row_id": _nullable_text(row.get("superseded_by_audit_row_id")),
            }
        )
    return _dedupe_rows(rows, lambda row: row["audit_row_id"])


def _build_audit_source_raw_post_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    audit_rows = payload.get("audit_enrichment_rows") if isinstance(payload.get("audit_enrichment_rows"), list) else []
    rows = []
    for row in audit_rows:
        if not isinstance(row, dict):
            continue
        audit_row_id = _as_text(row.get("audit_row_id"))
        for raw_post_id in _as_text_list(row.get("source_raw_post_ids")):
            rows.append(
                {
                    "audit_row_id": audit_row_id,
                    "raw_post_id": raw_post_id,
                }
            )
    return _dedupe_rows(rows, lambda row: (row["audit_row_id"], row["raw_post_id"]))


def _offer_keys_from_payload(payload: dict[str, Any]) -> list[str]:
    canonical_output = payload.get("canonical_output") if isinstance(payload.get("canonical_output"), dict) else {}
    offers = canonical_output.get("offers") if isinstance(canonical_output.get("offers"), list) else []
    deduped: list[str] = []
    seen: set[str] = set()
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        offer_key = _as_text(offer.get("offer_key"))
        if not offer_key or offer_key in seen:
            continue
        seen.add(offer_key)
        deduped.append(offer_key)
    return deduped


def _build_service_run_row(payload: dict[str, Any]) -> dict[str, Any]:
    base_row = payload.get("service_run_sheet_row_final") if isinstance(payload.get("service_run_sheet_row_final"), dict) else {}
    service_run_candidate = payload.get("service_run_candidate") if isinstance(payload.get("service_run_candidate"), dict) else {}
    normalized_request = payload.get("normalized_request") if isinstance(payload.get("normalized_request"), dict) else {}
    publication_summary = payload.get("publication_summary") if isinstance(payload.get("publication_summary"), dict) else {}
    merge_output = payload.get("merge_output") if isinstance(payload.get("merge_output"), dict) else {}
    merge_summary = merge_output.get("merge_summary") if isinstance(merge_output.get("merge_summary"), dict) else {}
    unique_offer_keys = _offer_keys_from_payload(payload)
    offers_upserted_total = _as_int(base_row.get("offers_upserted_total") or service_run_candidate.get("offers_upserted_total"))
    if offers_upserted_total <= 0:
        offers_upserted_total = len(unique_offer_keys)

    row = {
        "run_id": _as_text(base_row.get("run_id") or service_run_candidate.get("run_id") or payload.get("run_id")),
        "run_status": _as_text(base_row.get("run_status") or service_run_candidate.get("run_status") or "success"),
        "trigger_type": _as_text(base_row.get("trigger_type") or service_run_candidate.get("trigger_type") or payload.get("trigger_type") or "unknown"),
        "started_at_utc": _as_text(base_row.get("started_at_utc") or service_run_candidate.get("started_at_utc") or payload.get("started_at_utc")),
        "finished_at_utc": _as_text(base_row.get("finished_at_utc") or service_run_candidate.get("finished_at_utc")),
        "duration_ms": _as_int(base_row.get("duration_ms") or service_run_candidate.get("duration_ms")),
        "requested_targets_count": _as_int(base_row.get("requested_targets_count") or service_run_candidate.get("requested_targets_count")),
        "successful_target_count": _as_int(base_row.get("successful_target_count") or service_run_candidate.get("successful_target_count")),
        "failed_target_count": _as_int(base_row.get("failed_target_count") or service_run_candidate.get("failed_target_count")),
        "sync_mode": _as_text(base_row.get("sync_mode") or service_run_candidate.get("sync_mode")),
        "max_messages": _as_int(base_row.get("max_messages") or service_run_candidate.get("max_messages") or normalized_request.get("max_messages")),
        "cutoff_policy_type": _as_text(base_row.get("cutoff_policy_type") or service_run_candidate.get("cutoff_policy_type") or normalized_request.get("cutoff_field")),
        "cutoff_policy_value": _as_text(base_row.get("cutoff_policy_value") or service_run_candidate.get("cutoff_policy_value") or normalized_request.get(normalized_request.get("cutoff_field", ""))),
        "llm_enabled": _as_bool(base_row.get("llm_enabled") if "llm_enabled" in base_row else service_run_candidate.get("llm_enabled", normalized_request.get("llm_enabled"))),
        "raw_posts_total": _as_int(base_row.get("raw_posts_total") or service_run_candidate.get("raw_posts_total") or payload.get("raw_posts_total")),
        "providers_total": _as_int(base_row.get("providers_total") or service_run_candidate.get("providers_total")),
        "offers_total": _as_int(base_row.get("offers_total") or service_run_candidate.get("offers_total")),
        "offers_upserted_total": offers_upserted_total,
        "fetch_messages_seen_total": _as_int(base_row.get("fetch_messages_seen_total") or service_run_candidate.get("fetch_messages_seen_total")),
        "structured_posts_total": _as_int(base_row.get("structured_posts_total") or service_run_candidate.get("structured_posts_total") or merge_output.get("structured_posts_total")),
        "llm_calls_total": _as_int(base_row.get("llm_calls_total") or service_run_candidate.get("llm_calls_total")),
        "llm_tokens_input_total": _as_int(base_row.get("llm_tokens_input_total") or service_run_candidate.get("llm_tokens_input_total")),
        "llm_tokens_output_total": _as_int(base_row.get("llm_tokens_output_total") or service_run_candidate.get("llm_tokens_output_total")),
        "llm_cost_estimate_usd": _as_decimal(base_row.get("llm_cost_estimate_usd") or service_run_candidate.get("llm_cost_estimate_usd")),
        "llm_review_required_count": _as_int(base_row.get("llm_review_required_count") or service_run_candidate.get("llm_review_required_count")),
        "error_type": _as_text(base_row.get("error_type") or service_run_candidate.get("error_type")),
        "error_message": _as_text(base_row.get("error_message") or service_run_candidate.get("error_message")),
        "google_sheet_id": _as_text(base_row.get("google_sheet_id") or normalized_request.get("google_sheet_id")),
        "providers_sheet_name": _as_text(base_row.get("providers_sheet_name") or payload.get("sheets_config", {}).get("providers_sheet_name")),
        "offers_sheet_name": _as_text(base_row.get("offers_sheet_name") or payload.get("sheets_config", {}).get("offers_sheet_name")),
        "requested_targets_json": _as_json_array(base_row.get("requested_targets_json") or service_run_candidate.get("requested_targets_json")),
        "successful_targets_json": _as_json_array(base_row.get("successful_targets_json") or service_run_candidate.get("successful_targets_json")),
        "failed_targets_json": _as_json_array(base_row.get("failed_targets_json") or service_run_candidate.get("failed_targets_json")),
        "warnings_json": _as_json_array(base_row.get("warnings_json") or service_run_candidate.get("warnings_json")),
        "checkpoint_targets_json": _as_json_array(base_row.get("checkpoint_targets_json")),
        "layer_resolution_counts_json": _as_json_object(merge_summary.get("layer_resolution_counts")),
        "field_resolution_counts_json": _as_json_object(merge_summary.get("field_resolution_counts")),
        "response_json": _as_json_object(base_row.get("response_json") or {"publication_summary": publication_summary}),
    }
    if not row["response_json"]:
        row["response_json"] = {"publication_summary": publication_summary}
    return row


def _build_run_target_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    row_sources = payload.get("run_targets_sheet_rows") if isinstance(payload.get("run_targets_sheet_rows"), list) else []
    if row_sources:
        rows = []
        for row in row_sources:
            if not isinstance(row, dict):
                continue
            rows.append(
                {
                    "run_id": _as_text(row.get("run_id")),
                    "target_key": _as_text(row.get("target_key")),
                    "target_input": _as_text(row.get("target_input")),
                    "target_resolved": _as_text(row.get("target_resolved")),
                    "target_status": _as_text(row.get("target_status")),
                    "started_at_utc": _as_text(row.get("started_at_utc")),
                    "finished_at_utc": _as_text(row.get("finished_at_utc")),
                    "checkpoint_message_id": _as_int(row.get("checkpoint_message_id")) or None,
                    "raw_posts_emitted": _as_int(row.get("raw_posts_emitted")),
                    "error_type": _as_text(row.get("error_type")),
                    "error_message": _as_text(row.get("error_message")),
                    "target_stats_json": _as_json_object(row.get("target_stats_json")),
                }
            )
        return _dedupe_rows(rows, lambda row: (row["run_id"], row["target_key"]))

    candidates = payload.get("run_target_candidates") if isinstance(payload.get("run_target_candidates"), list) else []
    rows = []
    for row in candidates:
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "run_id": _as_text(row.get("run_id") or payload.get("run_id")),
                "target_key": _as_text(row.get("target_key")),
                "target_input": _as_text(row.get("target_input")),
                "target_resolved": _as_text(row.get("target_resolved") or row.get("telegram_target_resolved")),
                "target_status": _as_text(row.get("target_status")),
                "started_at_utc": _as_text(row.get("started_at_utc")),
                "finished_at_utc": _as_text(row.get("finished_at_utc")),
                "checkpoint_message_id": _as_int(row.get("checkpoint_message_id")) or None,
                "raw_posts_emitted": _as_int(row.get("raw_posts_emitted")),
                "error_type": _as_text(row.get("error_type")),
                "error_message": _as_text(row.get("error_message")),
                "target_stats_json": _as_json_object(row.get("target_stats_json")),
            }
        )
    return _dedupe_rows(rows, lambda row: (row["run_id"], row["target_key"]))


def _build_provider_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    canonical_output = payload.get("canonical_output") if isinstance(payload.get("canonical_output"), dict) else {}
    providers = canonical_output.get("providers") if isinstance(canonical_output.get("providers"), list) else []
    rows = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        rows.append(
            {
                "provider_key": _as_text(provider.get("provider_key")),
                "provider_state": _as_text(provider.get("provider_state") or "candidate"),
                "identity_strength": _as_text(provider.get("identity_strength") or "provisional"),
                "display_name_best": _as_text(provider.get("display_name_best")),
                "canonical_name": _as_text(provider.get("canonical_name") or provider.get("display_name_best")),
                "provider_type": _as_text(provider.get("provider_type")),
                "provider_summary": _as_text(provider.get("provider_summary")),
                "primary_contact_type": _as_text(provider.get("primary_contact_type")),
                "primary_contact_value": _as_text(provider.get("primary_contact_value")),
                "latest_post_url": _as_text(provider.get("latest_post_url")),
                "first_seen_at_utc": _as_text(provider.get("first_seen_at_utc")),
                "last_seen_at_utc": _as_text(provider.get("last_seen_at_utc")),
                "first_seen_run_id": _as_text(provider.get("first_seen_run_id")),
                "last_seen_run_id": _as_text(provider.get("last_seen_run_id")),
                "times_seen": _as_int(provider.get("times_seen")),
                "offer_count": _as_int(provider.get("offer_count")),
                "dedupe_confidence": _as_text(provider.get("dedupe_confidence")),
                "provider_merge_override_group": _as_text(provider.get("provider_merge_override_group")),
                "provider_suppression_reason": _as_text(provider.get("provider_suppression_reason")),
                "phones": _as_text_list(provider.get("phones")),
                "telegram_handles": _as_text_list(provider.get("telegram_handles")),
                "telegram_links": _as_text_list(provider.get("telegram_links")),
                "instagram_handles": _as_text_list(provider.get("instagram_handles")),
                "instagram_links": _as_text_list(provider.get("instagram_links")),
                "emails": _as_text_list(provider.get("emails")),
                "websites": _as_text_list(provider.get("websites")),
                "facebook_links": _as_text_list(provider.get("facebook_links")),
                "city_codes": _as_text_list(provider.get("city_codes")),
                "service_category_hints": _as_text_list(provider.get("service_category_hints")),
                "source_channel_keys": _as_text_list(provider.get("source_channel_keys")),
                "provider_quality_flags_json": _as_json_array(provider.get("provider_quality_flags")),
            }
        )
    return _dedupe_rows(rows, lambda row: row["provider_key"])


def _build_offer_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    canonical_output = payload.get("canonical_output") if isinstance(payload.get("canonical_output"), dict) else {}
    offers = canonical_output.get("offers") if isinstance(canonical_output.get("offers"), list) else []
    rows = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        quality_flags = offer.get("offer_quality_flags")
        if quality_flags is None:
            quality_flags = offer.get("fact_pack_flags")
        rows.append(
            {
                "offer_key": _as_text(offer.get("offer_key")),
                "provider_key": _as_text(offer.get("provider_key")),
                "offer_state": _as_text(offer.get("offer_state") or "candidate"),
                "service_signature_key": _as_text(offer.get("service_signature_key")),
                "category_primary": _as_text(offer.get("category_primary")),
                "category_secondary": _as_text(offer.get("category_secondary")),
                "title_best": _as_text(offer.get("title_best")),
                "description_best": _as_text(offer.get("description_best")),
                "description_full_best": _as_text(offer.get("description_full_best") or offer.get("description_best")),
                "offer_summary": _as_text(offer.get("offer_summary")),
                "price_text_best": _as_text(offer.get("price_text_best")),
                "price_min": _as_decimal(offer.get("price_min")),
                "price_max": _as_decimal(offer.get("price_max")),
                "currency_code": _as_text(offer.get("currency_code")),
                "latest_post_url": _as_text(offer.get("latest_post_url")),
                "first_seen_at_utc": _as_text(offer.get("first_seen_at_utc")),
                "last_seen_at_utc": _as_text(offer.get("last_seen_at_utc")),
                "first_seen_run_id": _as_text(offer.get("first_seen_run_id")),
                "last_seen_run_id": _as_text(offer.get("last_seen_run_id")),
                "times_seen": _as_int(offer.get("times_seen")),
                "dedupe_confidence": _as_text(offer.get("dedupe_confidence")),
                "serbia_relevance_verdict": _normalize_serbia_relevance_verdict(
                    offer.get("serbia_relevance_verdict")
                ),
                "offer_rejection_reason": _as_text(offer.get("offer_rejection_reason")),
                "offer_merge_override_group": _as_text(offer.get("offer_merge_override_group")),
                "service_tags": _as_text_list(offer.get("service_tags")),
                "city_codes": _as_text_list(offer.get("city_codes")),
                "contact_snapshot_phones": _as_text_list(offer.get("contact_snapshot_phones")),
                "contact_snapshot_telegram_handles": _as_text_list(offer.get("contact_snapshot_telegram_handles")),
                "contact_snapshot_telegram_links": _as_text_list(offer.get("contact_snapshot_telegram_links")),
                "source_channel_keys": _as_text_list(offer.get("source_channel_keys")),
                "offer_quality_flags_json": _as_json_array(quality_flags),
            }
        )
    return _dedupe_rows(rows, lambda row: row["offer_key"])


def _dedupe_rows(rows: Iterable[dict[str, Any]], key_fn: Callable[[dict[str, Any]], Any]) -> list[dict[str, Any]]:
    deduped: dict[Any, dict[str, Any]] = {}
    ordered_keys: list[Any] = []
    for row in rows:
        key = key_fn(row)
        if not key or (isinstance(key, tuple) and any(not part for part in key)):
            continue
        if key not in deduped:
            ordered_keys.append(key)
        deduped[key] = row
    return [deduped[key] for key in ordered_keys]


def build_publication_batch(payload: dict[str, Any]) -> dict[str, Any]:
    service_run_row = _build_service_run_row(payload)
    if not service_run_row["run_id"]:
        raise ValueError("DB publish payload is missing run_id.")

    run_target_rows = _build_run_target_rows(payload)
    raw_post_rows = _build_raw_post_rows(payload)
    provider_rows = _build_provider_rows(payload)
    offer_rows = _build_offer_rows(payload)
    provider_raw_post_evidence_rows = _build_provider_raw_post_evidence_rows(payload)
    offer_raw_post_evidence_rows = _build_offer_raw_post_evidence_rows(payload)
    audit_enrichment_rows = _build_audit_enrichment_rows(payload)
    audit_source_raw_post_rows = _build_audit_source_raw_post_rows(payload)

    return {
        "run_id": service_run_row["run_id"],
        "workflow_stage": WORKFLOW_STAGE,
        "db_publish_contract_version": DB_PUBLISH_CONTRACT_VERSION,
        "service_run_row": service_run_row,
        "run_target_rows": run_target_rows,
        "raw_post_rows": raw_post_rows,
        "provider_rows": provider_rows,
        "offer_rows": offer_rows,
        "provider_raw_post_evidence_rows": provider_raw_post_evidence_rows,
        "offer_raw_post_evidence_rows": offer_raw_post_evidence_rows,
        "audit_enrichment_rows": audit_enrichment_rows,
        "audit_source_raw_post_rows": audit_source_raw_post_rows,
    }


def _with_jsonb(row: dict[str, Any], json_fields: Iterable[str]) -> dict[str, Any]:
    prepared = dict(row)
    for field in json_fields:
        prepared[field] = Jsonb(prepared[field])
    return prepared


def _build_upsert_sql(
    table_name: str,
    columns: list[str],
    conflict_columns: list[str],
    update_columns: list[str],
) -> str:
    insert_columns = ", ".join(columns)
    placeholders = ", ".join(f"%({column})s" for column in columns)
    conflict = ", ".join(conflict_columns)
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
    return (
        f"INSERT INTO {table_name} ({insert_columns}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO UPDATE SET {updates};"
    )


def _build_insert_do_nothing_sql(
    table_name: str,
    columns: list[str],
    conflict_columns: list[str],
) -> str:
    insert_columns = ", ".join(columns)
    placeholders = ", ".join(f"%({column})s" for column in columns)
    conflict = ", ".join(conflict_columns)
    return (
        f"INSERT INTO {table_name} ({insert_columns}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict}) DO NOTHING;"
    )


SERVICE_RUN_UPSERT_SQL = _build_upsert_sql(
    "service_runs",
    SERVICE_RUN_COLUMNS,
    ["run_id"],
    [column for column in SERVICE_RUN_COLUMNS if column != "run_id"],
)

RUN_TARGET_UPSERT_SQL = _build_upsert_sql(
    "run_targets",
    RUN_TARGET_COLUMNS,
    ["run_id", "target_key"],
    [column for column in RUN_TARGET_COLUMNS if column not in {"run_id", "target_key"}],
)

RAW_POST_UPSERT_SQL = _build_upsert_sql(
    "raw_posts",
    RAW_POST_COLUMNS,
    ["raw_post_id"],
    [
        column
        for column in RAW_POST_COLUMNS
        if column in {
            "views",
            "forwards",
            "replies",
            "last_seen_run_id",
            "last_seen_at_utc",
            "last_seen_target_input",
            "last_seen_target_resolved",
            "output_timezone_last",
        }
    ],
)

PROVIDER_UPSERT_SQL = _build_upsert_sql(
    "providers",
    PROVIDER_COLUMNS,
    ["provider_key"],
    [
        column
        for column in PROVIDER_COLUMNS
        if column not in {"provider_key", "first_seen_at_utc", "first_seen_run_id"}
    ],
)

OFFER_UPSERT_SQL = _build_upsert_sql(
    "offers",
    OFFER_COLUMNS,
    ["offer_key"],
    [
        column
        for column in OFFER_COLUMNS
        if column not in {"offer_key", "provider_key", "service_signature_key", "first_seen_at_utc", "first_seen_run_id"}
    ],
)

PROVIDER_RAW_POST_EVIDENCE_UPSERT_SQL = _build_upsert_sql(
    "provider_raw_post_evidence",
    PROVIDER_RAW_POST_EVIDENCE_COLUMNS,
    ["provider_key", "raw_post_id"],
    ["last_seen_run_id"],
)

OFFER_RAW_POST_EVIDENCE_UPSERT_SQL = _build_upsert_sql(
    "offer_raw_post_evidence",
    OFFER_RAW_POST_EVIDENCE_COLUMNS,
    ["offer_key", "raw_post_id"],
    ["last_seen_run_id"],
)

AUDIT_ENRICHMENT_INSERT_SQL = _build_insert_do_nothing_sql(
    "audit_enrichment_rows",
    AUDIT_ENRICHMENT_COLUMNS,
    ["audit_row_id"],
)

AUDIT_SOURCE_RAW_POST_INSERT_SQL = _build_insert_do_nothing_sql(
    "audit_source_raw_posts",
    AUDIT_SOURCE_RAW_POST_COLUMNS,
    ["audit_row_id", "raw_post_id"],
)


def publish_business_rows(payload: dict[str, Any], *, dsn: str, dsn_env: str = DEFAULT_DSN_ENV) -> dict[str, Any]:
    batch = build_publication_batch(payload)
    service_run_response_json = dict(batch["service_run_row"].get("response_json") or {})

    service_run_row = _with_jsonb(
        batch["service_run_row"],
        [
            "requested_targets_json",
            "successful_targets_json",
            "failed_targets_json",
            "warnings_json",
            "checkpoint_targets_json",
            "layer_resolution_counts_json",
            "field_resolution_counts_json",
            "response_json",
        ],
    )
    run_target_rows = [
        _with_jsonb(row, ["target_stats_json"])
        for row in batch["run_target_rows"]
    ]
    raw_post_rows = [
        _with_jsonb(row, ["content_flags_json"])
        for row in batch["raw_post_rows"]
    ]
    provider_rows = [
        _with_jsonb(row, ["provider_quality_flags_json"])
        for row in batch["provider_rows"]
    ]
    offer_rows = [
        _with_jsonb(row, ["offer_quality_flags_json"])
        for row in batch["offer_rows"]
    ]
    provider_raw_post_evidence_rows = batch["provider_raw_post_evidence_rows"]
    offer_raw_post_evidence_rows = batch["offer_raw_post_evidence_rows"]
    audit_enrichment_rows = [
        _with_jsonb(row, ["output_patch_json"])
        for row in batch["audit_enrichment_rows"]
    ]
    audit_source_raw_post_rows = batch["audit_source_raw_post_rows"]

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC';")
            cursor.execute(SERVICE_RUN_UPSERT_SQL, service_run_row)
            if run_target_rows:
                cursor.executemany(RUN_TARGET_UPSERT_SQL, run_target_rows)
            if raw_post_rows:
                cursor.executemany(RAW_POST_UPSERT_SQL, raw_post_rows)
            if provider_rows:
                cursor.executemany(PROVIDER_UPSERT_SQL, provider_rows)
            if offer_rows:
                cursor.executemany(OFFER_UPSERT_SQL, offer_rows)
            if provider_raw_post_evidence_rows:
                cursor.executemany(PROVIDER_RAW_POST_EVIDENCE_UPSERT_SQL, provider_raw_post_evidence_rows)
            if offer_raw_post_evidence_rows:
                cursor.executemany(OFFER_RAW_POST_EVIDENCE_UPSERT_SQL, offer_raw_post_evidence_rows)
            if audit_enrichment_rows:
                cursor.executemany(AUDIT_ENRICHMENT_INSERT_SQL, audit_enrichment_rows)
            if audit_source_raw_post_rows:
                cursor.executemany(AUDIT_SOURCE_RAW_POST_INSERT_SQL, audit_source_raw_post_rows)
            cursor.execute(
                "SELECT current_database() AS db_name, COALESCE(inet_server_addr()::text, '') AS host, inet_server_port() AS port;"
            )
            connection_info = cursor.fetchone()
            db_name, host, port = connection_info if connection_info is not None else ("", "", None)
            db_summary = {
                "status": "success",
                "dsn_env": dsn_env,
                "db_name": _as_text(db_name),
                "host": _as_text(host),
                "port": _as_int(port),
                "service_runs_upserted": 1,
                "run_targets_upserted": len(run_target_rows),
                "raw_posts_upserted": len(raw_post_rows),
                "providers_upserted": len(provider_rows),
                "offers_upserted": len(offer_rows),
                "provider_raw_post_evidence_upserted": len(provider_raw_post_evidence_rows),
                "offer_raw_post_evidence_upserted": len(offer_raw_post_evidence_rows),
                "audit_enrichment_rows_appended": len(audit_enrichment_rows),
                "audit_source_raw_posts_appended": len(audit_source_raw_post_rows),
            }
            service_run_row["response_json"] = Jsonb(
                {
                    **service_run_response_json,
                    "db_publication": db_summary,
                }
            )
            cursor.execute(SERVICE_RUN_UPSERT_SQL, service_run_row)
        connection.commit()

    return {
        "run_id": batch["run_id"],
        "workflow_stage": WORKFLOW_STAGE,
        "db_publish_contract_version": DB_PUBLISH_CONTRACT_VERSION,
        "db_publication": db_summary,
        "service_run_candidate": {
            **(
                payload.get("service_run_candidate")
                if isinstance(payload.get("service_run_candidate"), dict)
                else {}
            ),
            "offers_upserted_total": len(offer_rows),
            "sink_status": "db_published_business_rows",
            "sink_reason": "",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write canonical business rows and provenance surfaces into PostgreSQL."
    )
    parser.add_argument(
        "--input-path",
        help="Path to a JSON file that contains the DB publication payload. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--output-path",
        help="Optional path to write the helper JSON instead of stdout.",
    )
    parser.add_argument(
        "--dsn-env",
        default=DEFAULT_DSN_ENV,
        help="User/process environment variable that contains the PostgreSQL DSN.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print indented UTF-8 JSON instead of ASCII-safe compact JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dsn = os.environ.get(args.dsn_env, "").strip()
    if not dsn:
        raise RuntimeError(f"Environment variable {args.dsn_env} is not set.")

    payload = _load_payload(args.input_path)
    result = publish_business_rows(payload, dsn=dsn, dsn_env=args.dsn_env)
    _write_output(compact_json(result, pretty=args.pretty), args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
