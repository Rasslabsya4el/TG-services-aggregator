from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.extract.extractor import extract_structured_post
from scripts.extract.merge import merge_structured_posts
from scripts.llm.post_merge import (
    CATEGORY_REFINE_RESPONSE_MAX_OUTPUT_TOKENS,
    DEFAULT_PRODUCT_ROW_MAX_CANDIDATES_PER_RUN,
    HARD_STOP_CALLS,
    PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
    RESPONSE_MAX_OUTPUT_TOKENS,
    _build_product_row_candidates,
    _finalize_product_rows,
    _product_row_continuation_token,
    _response_max_output_token_staircase_for_schema,
    _response_max_output_tokens_for_schema,
    _safe_schema_name,
    _seed_default_product_rows,
    process_post_merge_payload,
)


def _raw_post_from_structured(structured_post: dict[str, Any], *, target_key: str) -> dict[str, Any]:
    source_ref = structured_post.get("source_ref") or {}
    text = structured_post.get("text") or {}
    author = structured_post.get("author_signals") or {}
    content_flags = set(text.get("content_flags") or [])
    return {
        "raw_post_id": structured_post.get("raw_post_id"),
        "post_key": source_ref.get("post_key"),
        "chat_id": source_ref.get("chat_id"),
        "message_id": source_ref.get("message_id"),
        "source_channel_key": source_ref.get("source_channel_key"),
        "chat_title": source_ref.get("chat_title"),
        "chat_kind": source_ref.get("chat_kind"),
        "chat_username": source_ref.get("chat_username"),
        "post_url": source_ref.get("post_url"),
        "posted_at_utc": source_ref.get("posted_at_utc"),
        "text_raw": text.get("text_raw"),
        "has_media": "has_media" in content_flags,
        "sender_id": author.get("sender_id"),
        "sender_kind": author.get("sender_kind"),
        "sender_title": author.get("sender_title"),
        "sender_username": author.get("sender_username"),
        "sender_profile_url": author.get("sender_profile_url"),
        "sender_phone": author.get("sender_phone"),
        "post_author": author.get("post_author"),
        "_run_id": "tz-product-llm",
        "_target_key": target_key,
        "_telegram_target_input": f"@{target_key}",
        "_telegram_target_resolved": f"@{target_key}",
    }


def _build_payload(raw_post: dict[str, Any], *, run_id: str = "tz-product-llm") -> dict[str, Any]:
    structured_post = extract_structured_post(raw_post, run_id)
    merge_output = merge_structured_posts(
        {
            "run_id": run_id,
            "structured_posts": [structured_post],
        }
    )
    return {
        "run_id": run_id,
        "normalized_request": {
            "llm_enabled": True,
        },
        "raw_posts": [raw_post],
        "merge_output": merge_output,
    }


def _stabilize_for_product_stage(
    payload: dict[str, Any],
    *,
    category_primary: str,
    service_tags: list[str],
) -> dict[str, Any]:
    provider = payload["merge_output"]["providers"][0]
    provider["provider_state"] = "accepted"
    provider["identity_strength"] = "strong"
    provider["dedupe_confidence"] = "high"
    provider["service_category_hints"] = [category_primary]
    provider["canonical_name"] = provider.get("canonical_name") or provider.get("display_name_best") or "Provider"
    offer = payload["merge_output"]["offers"][0]
    offer["offer_state"] = "accepted"
    offer["offer_rejection_reason"] = ""
    offer["serbia_relevance_verdict"] = "serbia_relevant"
    offer["category_primary"] = category_primary
    offer["service_tags"] = service_tags
    offer["offer_summary"] = offer.get("details_candidate") or offer.get("description_best") or offer.get("service_name_candidate") or offer.get("title_best")
    return offer


def _build_mock_path(schema_name: str, decision: dict[str, Any]) -> str:
    payload = {
        "responses": {
            schema_name: {
                "decision": decision,
                "usage": {
                    "input_tokens": 220,
                    "output_tokens": 52,
                },
                "latency_ms": 19,
            }
        }
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        return handle.name


def _run_with_product_mock(payload: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    offer_key = payload["merge_output"]["offers"][0]["offer_key"]
    mock_path = _build_mock_path(_safe_schema_name("tgss_product_row", offer_key), decision)
    try:
        return process_post_merge_payload(payload, mock_response_path=mock_path)
    finally:
        Path(mock_path).unlink(missing_ok=True)


def _build_product_coverage_payload(count: int) -> dict[str, Any]:
    provider_key = "provider:coverage"
    offers: list[dict[str, Any]] = []
    for index in range(count):
        offer_key = f"offer:coverage:{index:03d}"
        raw_post_id = f"raw:coverage:{index:03d}"
        offers.append(
            {
                "offer_key": offer_key,
                "provider_key": provider_key,
                "offer_state": "accepted",
                "offer_rejection_reason": "",
                "serbia_relevance_verdict": "serbia_relevant",
                "category_primary": "cleaning",
                "category_secondary": "",
                "title_best": f"Клининг квартиры {index}",
                "description_best": "Поддерживающая уборка квартиры в Белграде после переезда.",
                "service_name_candidate": f"Клининг квартиры {index}",
                "details_candidate": "Поддерживающая уборка квартиры в Белграде после переезда.",
                "offer_summary": "Поддерживающая уборка квартиры в Белграде.",
                "service_tags": ["cleaning"],
                "city_codes": ["belgrade"],
                "city_display_names": ["Белград"],
                "dedupe_confidence": "high",
                "service_signature_key": f"cleaning-belgrade-{index}",
                "fact_pack_quality": "clean",
                "fact_pack_flags": ["greeting_filtered"],
                "contact_candidate_display": "@example_clean_belgrade",
                "contact_snapshot_phones": [],
                "contact_snapshot_telegram_handles": ["example_clean_belgrade"],
                "contact_snapshot_telegram_links": ["https://t.me/example_clean_belgrade"],
                "contact_snapshot_emails": [],
                "contact_snapshot_websites": [],
                "explicit_contact_snapshot_phones": [],
                "explicit_contact_snapshot_telegram_handles": ["example_clean_belgrade"],
                "explicit_contact_snapshot_telegram_links": ["https://t.me/example_clean_belgrade"],
                "author_fallback_phones": [],
                "author_fallback_telegram_handles": [],
                "author_fallback_telegram_links": [],
                "source_anchor_text": f"@example_source_lambda/{index + 1}",
                "latest_post_url": f"https://t.me/example_source_lambda/{index + 1}",
                "freshness_at_utc": "2026-04-25T09:00:00Z",
                "last_seen_at_utc": "2026-04-25T09:00:00Z",
                "evidence_raw_post_ids": [raw_post_id],
            }
        )
    return {
        "run_id": "tz-product-coverage",
        "normalized_request": {
            "llm_enabled": True,
        },
        "raw_posts": [],
        "merge_output": {
            "providers": [
                {
                    "provider_key": provider_key,
                    "provider_state": "accepted",
                    "identity_strength": "strong",
                    "dedupe_confidence": "high",
                    "display_name_best": "Clean Belgrade",
                    "canonical_name": "Clean Belgrade",
                    "provider_summary": "Клининг в Белграде.",
                    "service_category_hints": ["cleaning"],
                    "city_codes": ["belgrade"],
                    "evidence_raw_post_ids": [offer["evidence_raw_post_ids"][0] for offer in offers],
                }
            ],
            "offers": offers,
            "merge_summary": {},
        },
    }


def _attach_product_row_fetch_freeze(
    payload: dict[str, Any],
    *,
    source_key: str = "coverage_source",
    upper_message_id: int = 3,
) -> dict[str, Any]:
    payload["fetch_summary"] = {
        "product_row_fetch_freeze": {
            "version": "product_row_fetch_freeze_v1",
            "sources": [
                {
                    "version": "product_row_fetch_freeze_v1",
                    "source_key": source_key,
                    "target_key": source_key,
                    "target_lookup_key": source_key,
                    "telegram_public": "example_source_lambda",
                    "telegram_target": "@example_source_lambda",
                    "exact_message_request": False,
                    "upper_message_id": upper_message_id,
                    "max_message_id_applied": None,
                    "newer_posts_skipped": 0,
                    "posts_emitted": min(len(payload["merge_output"]["offers"]), upper_message_id),
                    "cutoff_utc": "2026-04-25T09:01:00Z",
                    "cutoff_utc_source": "request",
                    "oldest_post_utc": "2026-04-25T09:01:00Z",
                    "lower_message_id": 1,
                    "lower_message_id_applied": None,
                    "newest_post_utc": "2026-04-25T09:00:00Z",
                    "stopped_reason": "cutoff_reached",
                }
            ],
        }
    }
    return payload


def _attach_product_row_raw_post_evidence(
    payload: dict[str, Any],
    *,
    source_key: str = "coverage_source",
) -> dict[str, Any]:
    raw_posts: list[dict[str, Any]] = []
    for index, offer in enumerate(payload["merge_output"]["offers"], start=1):
        raw_post_id = offer["evidence_raw_post_ids"][0]
        raw_posts.append(
            {
                "raw_post_id": raw_post_id,
                "message_id": index,
                "post_url": f"https://t.me/example_source_lambda/{index}",
                "posted_at_utc": f"2026-04-25T09:{index:02d}:00Z",
                "text_raw": offer["description_best"],
                "text_normalized": offer["description_best"],
                "chat_username": "example_source_lambda",
                "_source_key": source_key,
                "_target_key": source_key,
                "_telegram_target_input": "@example_source_lambda",
                "_exact_message_request": False,
            }
        )
    payload["raw_posts"] = raw_posts
    return payload


def _build_direct_product_payload(
    *,
    offer_key: str,
    provider_key: str,
    raw_post: dict[str, Any],
    category_primary: str,
    service_tags: list[str],
    service_name_candidate: str,
    details_candidate: str,
    contact_handle: str,
) -> dict[str, Any]:
    raw_post_id = raw_post["raw_post_id"]
    return {
        "run_id": "tz-product-writer",
        "normalized_request": {
            "llm_enabled": True,
        },
        "raw_posts": [raw_post],
        "merge_output": {
            "providers": [
                {
                    "provider_key": provider_key,
                    "provider_state": "accepted",
                    "identity_strength": "strong",
                    "dedupe_confidence": "high",
                    "display_name_best": "Provider",
                    "canonical_name": "Provider",
                    "provider_summary": details_candidate,
                    "service_category_hints": [category_primary] if category_primary else [],
                    "city_codes": ["belgrade"],
                    "evidence_raw_post_ids": [raw_post_id],
                }
            ],
            "offers": [
                {
                    "offer_key": offer_key,
                    "provider_key": provider_key,
                    "offer_state": "accepted",
                    "offer_rejection_reason": "",
                    "serbia_relevance_verdict": "serbia_relevant",
                    "category_primary": category_primary,
                    "category_secondary": "",
                    "title_best": service_name_candidate,
                    "description_best": details_candidate,
                    "service_name_candidate": service_name_candidate,
                    "details_candidate": details_candidate,
                    "offer_summary": details_candidate,
                    "service_tags": service_tags,
                    "city_codes": ["belgrade"],
                    "city_display_names": ["Белград"],
                    "dedupe_confidence": "high",
                    "service_signature_key": offer_key,
                    "fact_pack_quality": "clean",
                    "fact_pack_flags": [],
                    "contact_candidate_display": f"@{contact_handle}",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": [contact_handle],
                    "contact_snapshot_telegram_links": [f"https://t.me/{contact_handle}"],
                    "contact_snapshot_emails": [],
                    "contact_snapshot_websites": [],
                    "explicit_contact_snapshot_phones": [],
                    "explicit_contact_snapshot_telegram_handles": [contact_handle],
                    "explicit_contact_snapshot_telegram_links": [f"https://t.me/{contact_handle}"],
                    "author_fallback_phones": [],
                    "author_fallback_telegram_handles": [],
                    "author_fallback_telegram_links": [],
                    "source_anchor_text": f"@{raw_post['chat_username']}/{raw_post['message_id']}",
                    "latest_post_url": raw_post["post_url"],
                    "freshness_at_utc": raw_post["posted_at_utc"],
                    "last_seen_at_utc": raw_post["posted_at_utc"],
                    "evidence_raw_post_ids": [raw_post_id],
                }
            ],
            "merge_summary": {},
        },
    }


def _build_product_coverage_mock(payload: dict[str, Any]) -> str:
    responses: dict[str, Any] = {}
    for offer in payload["merge_output"]["offers"]:
        offer_key = offer["offer_key"]
        responses[_safe_schema_name("tgss_product_row", offer_key)] = {
            "expected_max_output_tokens": PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
            "decision": {
                "decision_code": "publish",
                "confidence": 0.93,
                "patch": {
                    "product_row_service_name": offer["service_name_candidate"],
                    "product_row_details": offer["details_candidate"],
                    "product_row_category": "Уборка и химчистка",
                    "product_row_contact": "@example_clean_belgrade",
                },
                "reason_text": "Clear cleaning service from deterministic fact pack.",
            },
            "usage": {
                "input_tokens": 180,
                "output_tokens": 40,
            },
        }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump({"responses": responses}, handle, ensure_ascii=False)
        return handle.name


def _product_row_success_entry(offer: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_max_output_tokens": PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
        "decision": {
            "decision_code": "publish",
            "confidence": 0.93,
            "patch": {
                "product_row_service_name": offer["service_name_candidate"],
                "product_row_details": offer["details_candidate"],
                "product_row_category": "Уборка и химчистка",
                "product_row_contact": "@example_clean_belgrade",
            },
            "reason_text": "Clear cleaning service from deterministic fact pack.",
        },
        "usage": {
            "input_tokens": 180,
            "output_tokens": 40,
        },
    }


def _product_row_quota_entry(*, request_id: str = "req_product_quota_mock") -> dict[str, Any]:
    return {
        "expected_max_output_tokens": PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
        "error_message": "You exceeded your current quota, please check your plan and billing details.",
        "retryable": True,
        "status_code": 429,
        "error_type": "insufficient_quota",
        "error_code": "insufficient_quota",
        "request_id": request_id,
        "response_body": (
            '{"error":{"message":"You exceeded your current quota, please check your plan and billing details.",'
            '"type":"insufficient_quota","code":"insufficient_quota"}}'
        ),
    }


def _make_payload_post_product_clean(payload: dict[str, Any]) -> dict[str, Any]:
    variants = [
        (
            "Генеральная уборка квартиры после ремонта",
            "Генеральная уборка квартиры после ремонта в Белграде.",
            ["cleaning", "deep_cleaning"],
        ),
        (
            "Профессиональное мытье окон и витрин",
            "Мытье окон и стеклянных витрин в Белграде.",
            ["cleaning", "windows"],
        ),
        (
            "Химчистка мягкой мебели на дому",
            "Химчистка диванов и кресел с выездом по Белграду.",
            ["cleaning", "upholstery"],
        ),
    ]
    for index, offer in enumerate(payload["merge_output"]["offers"]):
        service_name, details, tags = variants[index % len(variants)]
        offer["title_best"] = service_name
        offer["description_best"] = details
        offer["service_name_candidate"] = service_name
        offer["details_candidate"] = details
        offer["offer_summary"] = details
        offer["service_tags"] = tags
        offer["service_signature_key"] = f"post-product-clean-{index}"
    return payload


def _product_row_candidates_for_payload(payload: dict[str, Any]) -> list[Any]:
    providers_by_key = {
        provider["provider_key"]: provider
        for provider in payload["merge_output"]["providers"]
    }
    offers_by_key = {
        offer["offer_key"]: offer
        for offer in payload["merge_output"]["offers"]
    }
    deterministic_offers_by_key = copy.deepcopy(offers_by_key)
    _seed_default_product_rows(payload["merge_output"]["offers"], deterministic_offers_by_key)
    raw_post_map = {
        raw_post["raw_post_id"]: raw_post
        for raw_post in payload.get("raw_posts", [])
    }
    return _build_product_row_candidates(
        deterministic_providers_by_key=providers_by_key,
        deterministic_offers_by_key=deterministic_offers_by_key,
        offers_by_key=offers_by_key,
        raw_post_map=raw_post_map,
    )


class ProductRowLlmTests(unittest.TestCase):
    def test_product_row_stage_uses_expanded_output_cap_after_live_max_output_errors(self) -> None:
        self.assertGreater(PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS, RESPONSE_MAX_OUTPUT_TOKENS)
        self.assertGreater(CATEGORY_REFINE_RESPONSE_MAX_OUTPUT_TOKENS, RESPONSE_MAX_OUTPUT_TOKENS)
        self.assertEqual(
            _response_max_output_tokens_for_schema("tgss_product_row_offer_safe"),
            PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(
            _response_max_output_tokens_for_schema("tgss_category_offer_safe"),
            CATEGORY_REFINE_RESPONSE_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(
            _response_max_output_tokens_for_schema("tgss_category_provider_safe"),
            CATEGORY_REFINE_RESPONSE_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(
            _response_max_output_tokens_for_schema("tgss_service_relevance_offer_safe"),
            RESPONSE_MAX_OUTPUT_TOKENS,
        )

    def test_product_row_max_output_staircase_is_coarse_and_bounded(self) -> None:
        staircase = _response_max_output_token_staircase_for_schema("tgss_product_row_offer_safe")

        self.assertEqual(staircase[0], PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS)
        self.assertLessEqual(len(staircase), 4)
        self.assertEqual(tuple(sorted(set(staircase))), staircase)
        for previous, current in zip(staircase, staircase[1:]):
            self.assertGreaterEqual(current, previous * 1.5)

    def test_product_row_coverage_is_not_skipped_by_global_hard_stop(self) -> None:
        payload = _build_product_coverage_payload(HARD_STOP_CALLS + 1)
        mock_path = _build_product_coverage_mock(payload)
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        product_breakdown = result["llm_stage"]["stage_breakdown"]["llm_product_row_shape"]
        self.assertEqual(product_breakdown["eligible_entities"], HARD_STOP_CALLS + 1)
        self.assertEqual(product_breakdown["vendor_attempts"], HARD_STOP_CALLS + 1)
        self.assertEqual(product_breakdown["skipped"], 0)
        self.assertEqual(product_breakdown["accepted_patches"], HARD_STOP_CALLS + 1)
        self.assertEqual(product_breakdown["coverage_failures"], 0)
        coverage = result["llm_stage"]["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], HARD_STOP_CALLS + 1)
        self.assertEqual(coverage["attempts"], HARD_STOP_CALLS + 1)
        self.assertEqual(coverage["successful_decisions"], HARD_STOP_CALLS + 1)
        self.assertEqual(coverage["failures"], 0)
        self.assertTrue(coverage["coverage_complete"])
        self.assertTrue(result["llm_stage"]["budget"]["hard_stop_triggered"])
        self.assertTrue(
            all(
                offer["publishable_row"]["publish_decision"] == "publish"
                for offer in result["canonical_output"]["offers"]
            )
        )

    def test_product_row_priority_spends_hard_stop_on_visible_coverage_before_relevance_review(self) -> None:
        payload = _build_product_coverage_payload(HARD_STOP_CALLS + 1)
        for index, offer in enumerate(payload["merge_output"]["offers"]):
            offer["title_best"] = f"Ищу клининг квартиры {index}"
            offer["description_best"] = "Ищу клининг квартиры после переезда в Белграде."
            offer["offer_summary"] = "Ищу клининг квартиры после переезда в Белграде."
        mock_path = _build_product_coverage_mock(payload)
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "success")
        product_breakdown = result["llm_stage"]["stage_breakdown"]["llm_product_row_shape"]
        service_breakdown = result["llm_stage"]["stage_breakdown"]["llm_service_relevance"]
        self.assertEqual(product_breakdown["vendor_attempts"], HARD_STOP_CALLS + 1)
        self.assertEqual(product_breakdown["accepted_patches"], HARD_STOP_CALLS + 1)
        self.assertGreater(service_breakdown["eligible_entities"], 0)
        self.assertEqual(service_breakdown["vendor_attempts"], 0)
        self.assertEqual(service_breakdown["skipped"], HARD_STOP_CALLS + 1)
        coverage = result["llm_stage"]["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], HARD_STOP_CALLS + 1)
        self.assertEqual(coverage["successful_decisions"], HARD_STOP_CALLS + 1)
        self.assertTrue(coverage["coverage_complete"])

    def test_product_row_quota_exhaustion_blocks_publication_without_row_failure(self) -> None:
        payload = _build_product_coverage_payload(1)
        offer = payload["merge_output"]["offers"][0]
        schema_name = _safe_schema_name("tgss_product_row", offer["offer_key"])
        quota_entry = _product_row_quota_entry()
        quota_entry.pop("error_type")
        quota_entry.pop("error_code")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump({"responses": {schema_name: quota_entry}}, handle, ensure_ascii=False)
            mock_path = handle.name
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "error")
        self.assertEqual(llm_stage["reason"], "llm_product_row_quota_blocked")
        self.assertEqual(llm_stage["calls_attempted"], 1)
        self.assertEqual(llm_stage["audit_only_patches_total"], 0)
        self.assertEqual(llm_stage["budget"]["last_outcome"], "llm_product_row_quota_blocked")
        product_breakdown = llm_stage["stage_breakdown"]["llm_product_row_shape"]
        self.assertEqual(product_breakdown["vendor_attempts"], 1)
        self.assertEqual(product_breakdown["quota_blockers"], 1)
        self.assertEqual(product_breakdown["errors"], 0)
        self.assertEqual(product_breakdown["coverage_failures"], 0)

        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], 1)
        self.assertEqual(coverage["attempts"], 1)
        self.assertEqual(coverage["successful_decisions"], 0)
        self.assertEqual(coverage["failures"], 0)
        self.assertEqual(coverage["hard_drops"], 0)
        self.assertEqual(coverage["quota_blockers"], 1)
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(coverage["incomplete_reason"], "llm_product_row_quota_blocked")
        self.assertTrue(coverage["fallback_publication_blocked"])

        audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertEqual(len(audit_rows), 1)
        self.assertEqual(audit_rows[0]["status"], "blocked")
        self.assertEqual(audit_rows[0]["decision_code"], "llm_product_row_quota_blocked")
        self.assertIn("request_id=req_product_quota_mock", audit_rows[0]["response_excerpt"])
        self.assertNotEqual(audit_rows[0]["decision_code"], "call_failed")
        self.assertEqual(llm_stage["quota_blocker"]["status_code"], 429)

    def test_chunked_product_row_quota_exhaustion_preserves_retryable_state(self) -> None:
        payload = _make_payload_post_product_clean(_build_product_coverage_payload(3))
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 2,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 2,
            }
        )
        offers = payload["merge_output"]["offers"]
        responses = {
            _safe_schema_name("tgss_product_row", offers[0]["offer_key"]): _product_row_success_entry(offers[0]),
            _safe_schema_name("tgss_product_row", offers[1]["offer_key"]): _product_row_quota_entry(
                request_id="req_product_quota_chunk_mock"
            ),
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump({"responses": responses}, handle, ensure_ascii=False)
            mock_path = handle.name
        try:
            first = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        first_stage = first["llm_stage"]
        self.assertEqual(first_stage["status"], "error")
        self.assertEqual(first_stage["reason"], "llm_product_row_quota_blocked")
        self.assertEqual(first_stage["calls_attempted"], 2)
        first_coverage = first_stage["product_row_coverage"]
        self.assertEqual(first_coverage["successful_decisions"], 1)
        self.assertEqual(first_coverage["failures"], 0)
        self.assertEqual(first_coverage["hard_drops"], 0)
        self.assertFalse(first_coverage["coverage_complete"])
        self.assertEqual(first_coverage["incomplete_reason"], "llm_product_row_quota_blocked")

        chunking = first_stage["product_row_chunking"]
        self.assertEqual(chunking["status"], "blocked")
        self.assertEqual(chunking["next_cursor"], 1)
        self.assertEqual(chunking["remaining_candidate_count"], 2)
        self.assertEqual(chunking["quota_blocker"]["request_id"], "req_product_quota_chunk_mock")
        self.assertTrue(chunking["can_retry_same_continuation_state"])
        state = chunking["continuation_state"]
        self.assertEqual(state["coverage_status"], "blocked")
        self.assertEqual(state["processed_candidate_ids"], ["offer:coverage:000"])
        self.assertEqual(state["successful_candidate_ids"], ["offer:coverage:000"])
        self.assertEqual(state["failed_candidate_ids"], [])
        self.assertTrue(state["can_retry_same_continuation_state"])

        resumed_payload = _make_payload_post_product_clean(_build_product_coverage_payload(3))
        resumed_payload["normalized_request"].update(payload["normalized_request"])
        resumed_payload["normalized_request"]["llm_product_row_continuation_state"] = state
        resumed_payload["normalized_request"]["llm_product_row_continuation_token"] = state["continuation_token"]
        resumed_responses = {
            _safe_schema_name("tgss_product_row", offers[1]["offer_key"]): _product_row_success_entry(offers[1]),
            _safe_schema_name("tgss_product_row", offers[2]["offer_key"]): _product_row_success_entry(offers[2]),
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump({"responses": resumed_responses}, handle, ensure_ascii=False)
            resumed_mock_path = handle.name
        try:
            resumed = process_post_merge_payload(resumed_payload, mock_response_path=resumed_mock_path)
        finally:
            Path(resumed_mock_path).unlink(missing_ok=True)

        resumed_stage = resumed["llm_stage"]
        self.assertEqual(resumed_stage["status"], "success")
        self.assertEqual(resumed_stage["reason"], "llm_stage_completed")
        resumed_coverage = resumed_stage["product_row_coverage"]
        self.assertEqual(resumed_coverage["candidate_total"], 3)
        self.assertEqual(resumed_coverage["successful_decisions"], 3)
        self.assertEqual(resumed_coverage["failures"], 0)
        self.assertTrue(resumed_coverage["coverage_complete"])
        resumed_state = resumed_stage["product_row_chunking"]["continuation_state"]
        self.assertEqual(resumed_state["coverage_status"], "complete")
        self.assertNotIn("quota_blocker", resumed_state)

    def test_product_row_non_quota_retryable_transport_error_still_retries_once(self) -> None:
        payload = _build_product_coverage_payload(HARD_STOP_CALLS + 1)
        offers = payload["merge_output"]["offers"]
        responses: dict[str, Any] = {}
        for index, offer in enumerate(offers):
            schema_name = _safe_schema_name("tgss_product_row", offer["offer_key"])
            responses[schema_name] = (
                [
                    {
                        "expected_max_output_tokens": PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
                        "error_message": "OpenAI Responses API transport timeout: The read operation timed out",
                        "retryable": True,
                        "status_code": 503,
                        "request_id": "req_product_timeout_retry_mock",
                    },
                    _product_row_success_entry(offer),
                ]
                if index == 0
                else _product_row_success_entry(offer)
            )
        mock_payload = {"responses": responses}
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(mock_payload, handle, ensure_ascii=False)
            mock_path = handle.name
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "success")
        self.assertEqual(llm_stage["reason"], "llm_stage_completed")
        product_breakdown = llm_stage["stage_breakdown"]["llm_product_row_shape"]
        self.assertEqual(product_breakdown["vendor_attempts"], HARD_STOP_CALLS + 2)
        self.assertEqual(product_breakdown["quota_blockers"], 0)
        self.assertEqual(product_breakdown["errors"], 0)
        self.assertEqual(product_breakdown["accepted_patches"], HARD_STOP_CALLS + 1)
        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], HARD_STOP_CALLS + 1)
        self.assertEqual(coverage["successful_decisions"], HARD_STOP_CALLS + 1)
        self.assertEqual(coverage["failures"], 0)
        self.assertTrue(coverage["coverage_complete"])
        audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertEqual([row["status"] for row in audit_rows[:2]], ["error", "accepted"])
        self.assertEqual(audit_rows[0]["decision_code"], "call_failed")

    def test_total_timeout_returns_structured_progress_error_without_wait(self) -> None:
        payload = _build_product_coverage_payload(2)
        mock_path = _build_product_coverage_mock(payload)
        try:
            result = process_post_merge_payload(
                payload,
                mock_response_path=mock_path,
                total_timeout_seconds=0,
            )
        finally:
            Path(mock_path).unlink(missing_ok=True)

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "error")
        self.assertEqual(llm_stage["reason"], "llm_total_timeout")
        self.assertEqual(llm_stage["budget"]["last_outcome"], "llm_total_timeout")
        self.assertEqual(llm_stage["progress"]["reason"], "llm_total_timeout")
        self.assertEqual(llm_stage["progress"]["total_timeout_seconds"], 0)
        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], 2)
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(coverage["incomplete_reason"], "llm_total_timeout")
        self.assertEqual(result["canonical_output"]["offers_total"], 2)
        self.assertTrue(
            any(row["decision_code"] == "llm_total_timeout" for row in result["audit_enrichment_rows"])
        )

    def test_product_row_scale_guard_blocks_before_large_public_llm_wave(self) -> None:
        payload = _build_product_coverage_payload(3)
        payload["normalized_request"]["llm_product_row_max_candidates"] = 2

        result = process_post_merge_payload(payload)

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "error")
        self.assertEqual(llm_stage["reason"], "llm_product_row_scale_blocked")
        self.assertEqual(llm_stage["budget"]["last_outcome"], "llm_product_row_scale_blocked")
        self.assertEqual(llm_stage["calls_attempted"], 0)
        self.assertEqual(llm_stage["progress"]["candidate_limit"], 2)
        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], 3)
        self.assertEqual(coverage["attempts"], 0)
        self.assertEqual(coverage["skips"], 3)
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(coverage["incomplete_reason"], "llm_product_row_scale_blocked")
        self.assertTrue(
            any(row["decision_code"] == "llm_product_row_scale_blocked" for row in result["audit_enrichment_rows"])
        )
        self.assertGreater(DEFAULT_PRODUCT_ROW_MAX_CANDIDATES_PER_RUN, HARD_STOP_CALLS + 1)

    def test_chunked_product_row_first_chunk_requires_continuation_without_public_completion(self) -> None:
        payload = _build_product_coverage_payload(5)
        _attach_product_row_fetch_freeze(payload, upper_message_id=5)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 2,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 2,
            }
        )
        mock_path = _build_product_coverage_mock(payload)
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "error")
        self.assertEqual(llm_stage["reason"], "llm_product_row_continuation_required")
        self.assertEqual(llm_stage["calls_attempted"], 2)
        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], 5)
        self.assertEqual(coverage["attempts"], 2)
        self.assertEqual(coverage["successful_decisions"], 2)
        self.assertEqual(coverage["failures"], 0)
        self.assertEqual(coverage["skips"], 0)
        self.assertFalse(coverage["coverage_complete"])
        self.assertEqual(coverage["incomplete_reason"], "llm_product_row_continuation_required")

        chunking = llm_stage["product_row_chunking"]
        self.assertEqual(chunking["status"], "continuation_required")
        self.assertEqual(chunking["chunk_start_index"], 0)
        self.assertEqual(chunking["chunk_end_index"], 2)
        self.assertEqual(chunking["processed_candidate_count"], 2)
        self.assertEqual(chunking["remaining_candidate_count"], 3)
        self.assertEqual(chunking["chunk_candidate_ids"], ["offer:coverage:000", "offer:coverage:001"])
        state = chunking["continuation_state"]
        self.assertEqual(state["processed_candidate_ids"], ["offer:coverage:000", "offer:coverage:001"])
        self.assertEqual(state["candidate_ids"], sorted(state["candidate_ids"]))
        self.assertEqual(state["fetch_freeze"]["source_count"], 1)
        self.assertEqual(state["fetch_freeze"]["sources"][0]["upper_message_id"], 5)
        self.assertEqual(chunking["fetch_freeze"]["sources"][0]["telegram_public"], "example_source_lambda")

    def test_chunked_product_row_near_total_timeout_returns_clean_continuation(self) -> None:
        payload = _build_product_coverage_payload(5)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 4,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 4,
            }
        )
        mock_path = _build_product_coverage_mock(payload)
        monotonic_values = iter([0, 10, 20, 30, 40, 80])

        def fake_monotonic() -> float:
            return next(monotonic_values, 80)

        try:
            result = process_post_merge_payload(
                payload,
                mock_response_path=mock_path,
                total_timeout_seconds=100,
                monotonic=fake_monotonic,
            )
        finally:
            Path(mock_path).unlink(missing_ok=True)

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "error")
        self.assertEqual(llm_stage["reason"], "llm_product_row_continuation_required")
        self.assertEqual(llm_stage["budget"]["last_outcome"], "llm_product_row_continuation_required")
        self.assertEqual(llm_stage["calls_attempted"], 1)
        self.assertEqual(llm_stage["product_row_coverage"]["incomplete_reason"], "llm_product_row_continuation_required")
        self.assertNotEqual(llm_stage["reason"], "llm_total_timeout")
        chunking = llm_stage["product_row_chunking"]
        self.assertEqual(chunking["status"], "continuation_required")
        self.assertEqual(chunking["processed_candidate_count"], 1)
        self.assertEqual(chunking["remaining_candidate_count"], 4)
        self.assertEqual(chunking["next_cursor"], 1)
        self.assertEqual(chunking["continuation_state"]["coverage_status"], "continuation_required")
        self.assertEqual(chunking["continuation_state"]["successful_candidate_ids"], ["offer:coverage:000"])

    def test_chunked_product_row_safe_drops_unusable_row_outputs_without_failed_coverage(self) -> None:
        payload = _build_product_coverage_payload(3)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 2,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 2,
            }
        )
        responses: dict[str, Any] = {}
        offers = payload["merge_output"]["offers"]
        responses[_safe_schema_name("tgss_product_row", offers[0]["offer_key"])] = {
            "expected_max_output_tokens": PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
            "decision": {
                "decision_code": "drop",
                "confidence": 0.62,
                "patch": {
                    "product_row_service_name": "",
                    "product_row_details": "",
                    "product_row_category": "",
                    "product_row_contact": "",
                },
                "reason_text": "Not enough evidence for a public product row.",
            },
        }
        responses[_safe_schema_name("tgss_product_row", offers[1]["offer_key"])] = {
            "expected_max_output_tokens": PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS,
            "decision": {
                "decision_code": "publish",
                "confidence": 0.91,
                "patch": {
                    "product_row_service_name": "",
                    "product_row_details": "Incomplete product-row output without a service name.",
                    "product_row_category": "",
                    "product_row_contact": "@example_clean_belgrade",
                },
                "reason_text": "Unsafe publish output should not publish or fail the whole chunk.",
            },
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump({"responses": responses}, handle, ensure_ascii=False)
            mock_path = handle.name
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "error")
        self.assertEqual(llm_stage["reason"], "llm_product_row_continuation_required")
        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(coverage["attempts"], 2)
        self.assertEqual(coverage["successful_decisions"], 2)
        self.assertEqual(coverage["failures"], 0)
        self.assertEqual(coverage["hard_drops"], 0)
        self.assertEqual(coverage["safe_non_visible_drops"], 2)
        chunking = llm_stage["product_row_chunking"]
        self.assertEqual(chunking["status"], "continuation_required")
        self.assertEqual(chunking["failures"], 0)
        self.assertEqual(chunking["continuation_state"]["coverage_status"], "continuation_required")
        self.assertEqual(chunking["continuation_state"]["successful_candidate_ids"], ["offer:coverage:000", "offer:coverage:001"])
        self.assertTrue(
            all(
                offer["product_row_publish_decision"] == "drop"
                for offer in result["canonical_output"]["offers"][:2]
            )
        )
        product_audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertTrue(all(row["status"] == "accepted" for row in product_audit_rows))
        self.assertTrue(all(row["review_required"] for row in product_audit_rows))

    def test_chunked_product_row_resume_completes_aggregate_coverage_without_duplicates(self) -> None:
        candidate_total = HARD_STOP_CALLS + 1
        payload = _build_product_coverage_payload(candidate_total)
        payload["merge_output"]["offers"] = [
            *payload["merge_output"]["offers"][2:],
            *payload["merge_output"]["offers"][:2],
        ]
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": HARD_STOP_CALLS // 2,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": HARD_STOP_CALLS // 2,
            }
        )
        mock_path = _build_product_coverage_mock(payload)
        try:
            first = process_post_merge_payload(payload, mock_response_path=mock_path)
            first_state = first["llm_stage"]["product_row_chunking"]["continuation_state"]
            second_payload = copy.deepcopy(payload)
            second_payload["normalized_request"]["llm_product_row_continuation_state"] = first_state
            second_payload["normalized_request"]["llm_product_row_continuation_token"] = first_state["continuation_token"]
            second = process_post_merge_payload(second_payload, mock_response_path=mock_path)
            second_state = second["llm_stage"]["product_row_chunking"]["continuation_state"]
            third_payload = copy.deepcopy(payload)
            third_payload["normalized_request"]["llm_product_row_continuation_state"] = second_state
            third_payload["normalized_request"]["llm_product_row_continuation_token"] = second_state["continuation_token"]
            final = process_post_merge_payload(third_payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        self.assertEqual(first["llm_stage"]["product_row_chunking"]["chunk_candidate_ids"][0], "offer:coverage:000")
        self.assertEqual(first["llm_stage"]["product_row_chunking"]["chunk_candidate_ids"][-1], "offer:coverage:024")
        self.assertEqual(second["llm_stage"]["product_row_chunking"]["chunk_candidate_ids"][0], "offer:coverage:025")
        self.assertEqual(second["llm_stage"]["product_row_chunking"]["chunk_candidate_ids"][-1], "offer:coverage:049")
        self.assertEqual(final["llm_stage"]["product_row_chunking"]["chunk_candidate_ids"], ["offer:coverage:050"])

        llm_stage = final["llm_stage"]
        self.assertEqual(llm_stage["status"], "success")
        self.assertEqual(llm_stage["reason"], "llm_stage_completed")
        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], candidate_total)
        self.assertEqual(coverage["attempts"], candidate_total)
        self.assertEqual(coverage["successful_decisions"], candidate_total)
        self.assertEqual(coverage["failures"], 0)
        self.assertEqual(coverage["skips"], 0)
        self.assertTrue(coverage["coverage_complete"])
        chunking = llm_stage["product_row_chunking"]
        self.assertTrue(chunking["aggregate_coverage_complete"])
        self.assertEqual(chunking["processed_candidate_count"], candidate_total)
        self.assertEqual(chunking["remaining_candidate_count"], 0)
        self.assertEqual(
            len(set(chunking["continuation_state"]["processed_candidate_ids"])),
            candidate_total,
        )
        self.assertTrue(
            all(
                offer["publishable_row"]["publish_decision"] == "publish"
                for offer in final["canonical_output"]["offers"]
            )
        )

    def test_chunked_product_row_state_path_can_resume_without_inline_thread_memory(self) -> None:
        payload = _build_product_coverage_payload(3)
        mock_path = _build_product_coverage_mock(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = str(Path(temp_dir) / "product-row-state.json")
            payload["normalized_request"].update(
                {
                    "llm_product_row_max_candidates": 1,
                    "llm_product_row_chunking_enabled": True,
                    "llm_product_row_chunk_size": 1,
                    "llm_product_row_continuation_state_path": state_path,
                }
            )
            try:
                first = process_post_merge_payload(payload, mock_response_path=mock_path)
                state_after_first = json.loads(Path(state_path).read_text(encoding="utf-8"))
                second_payload = copy.deepcopy(payload)
                second_payload["normalized_request"]["llm_product_row_continuation_token"] = state_after_first["continuation_token"]
                second = process_post_merge_payload(second_payload, mock_response_path=mock_path)
            finally:
                Path(mock_path).unlink(missing_ok=True)

            self.assertNotIn("continuation_state", first["llm_stage"]["product_row_chunking"])
            self.assertEqual(first["llm_stage"]["product_row_chunking"]["continuation_state_path"], state_path)
            self.assertEqual(state_after_first["processed_candidate_ids"], ["offer:coverage:000"])
            self.assertEqual(second["llm_stage"]["product_row_chunking"]["chunk_candidate_ids"], ["offer:coverage:001"])
            state_after_second = json.loads(Path(state_path).read_text(encoding="utf-8"))
            self.assertEqual(state_after_second["processed_candidate_ids"], ["offer:coverage:000", "offer:coverage:001"])

    def test_chunked_product_row_resume_ignores_newer_candidates_explained_by_fetch_freeze(self) -> None:
        payload = _build_product_coverage_payload(3)
        _attach_product_row_raw_post_evidence(payload)
        _attach_product_row_fetch_freeze(payload, upper_message_id=3)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 1,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 1,
            }
        )
        first_mock_path = _build_product_coverage_mock(payload)
        resumed_payload = _build_product_coverage_payload(4)
        _attach_product_row_raw_post_evidence(resumed_payload)
        _attach_product_row_fetch_freeze(resumed_payload, upper_message_id=3)
        resumed_payload["normalized_request"].update(payload["normalized_request"])
        resumed_mock_path = _build_product_coverage_mock(resumed_payload)
        try:
            first = process_post_merge_payload(payload, mock_response_path=first_mock_path)
            state = first["llm_stage"]["product_row_chunking"]["continuation_state"]
            resumed_payload["normalized_request"]["llm_product_row_continuation_state"] = state
            resumed_payload["normalized_request"]["llm_product_row_continuation_token"] = state["continuation_token"]

            result = process_post_merge_payload(resumed_payload, mock_response_path=resumed_mock_path)
        finally:
            Path(first_mock_path).unlink(missing_ok=True)
            Path(resumed_mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "error")
        self.assertEqual(result["llm_stage"]["reason"], "llm_product_row_continuation_required")
        self.assertNotEqual(
            result["llm_stage"]["reason"],
            "llm_product_row_continuation_state_candidate_mismatch",
        )
        chunking = result["llm_stage"]["product_row_chunking"]
        self.assertEqual(chunking["chunk_candidate_ids"], ["offer:coverage:001"])
        self.assertEqual(chunking["candidate_total"], 3)
        self.assertEqual(chunking["fetch_freeze_excluded_candidate_ids"], ["offer:coverage:003"])
        self.assertEqual(
            chunking["continuation_state"]["fetch_freeze_excluded_candidate_ids"],
            ["offer:coverage:003"],
        )

    def test_chunked_product_row_resume_accepts_missing_non_candidate_raw_post_when_candidates_match(self) -> None:
        payload = _build_product_coverage_payload(3)
        _attach_product_row_raw_post_evidence(payload)
        payload["raw_posts"].append(
            {
                "raw_post_id": "raw:coverage:non_candidate",
                "message_id": 4,
                "post_url": "https://t.me/example_source_lambda/4",
                "posted_at_utc": "2026-04-25T09:04:00Z",
                "text_raw": "Informational channel post without a service offer.",
                "text_normalized": "Informational channel post without a service offer.",
                "chat_username": "example_source_lambda",
                "_source_key": "coverage_source",
                "_target_key": "coverage_source",
                "_telegram_target_input": "@example_source_lambda",
                "_exact_message_request": False,
            }
        )
        _attach_product_row_fetch_freeze(payload, upper_message_id=4)
        payload["fetch_summary"]["product_row_fetch_freeze"]["sources"][0]["posts_emitted"] = 4
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 1,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 1,
            }
        )
        first_mock_path = _build_product_coverage_mock(payload)

        resumed_payload = _build_product_coverage_payload(3)
        _attach_product_row_raw_post_evidence(resumed_payload)
        _attach_product_row_fetch_freeze(resumed_payload, upper_message_id=4)
        resumed_payload["fetch_summary"]["product_row_fetch_freeze"]["sources"][0]["posts_emitted"] = 3
        resumed_payload["normalized_request"].update(payload["normalized_request"])
        resumed_mock_path = _build_product_coverage_mock(resumed_payload)
        try:
            first = process_post_merge_payload(payload, mock_response_path=first_mock_path)
            state = first["llm_stage"]["product_row_chunking"]["continuation_state"]
            resumed_payload["normalized_request"]["llm_product_row_continuation_state"] = state
            resumed_payload["normalized_request"]["llm_product_row_continuation_token"] = state["continuation_token"]

            result = process_post_merge_payload(resumed_payload, mock_response_path=resumed_mock_path)
        finally:
            Path(first_mock_path).unlink(missing_ok=True)
            Path(resumed_mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "error")
        self.assertEqual(result["llm_stage"]["reason"], "llm_product_row_continuation_required")
        chunking = result["llm_stage"]["product_row_chunking"]
        self.assertEqual(chunking["chunk_candidate_ids"], ["offer:coverage:001"])
        self.assertEqual(chunking["candidate_total"], 3)
        self.assertNotIn("candidate_mismatch_evidence", chunking)
        self.assertEqual(chunking["fetch_freeze"]["sources"][0]["posts_emitted"], 4)
        self.assertEqual(chunking["continuation_state"]["fetch_freeze"]["sources"][0]["posts_emitted"], 4)

    def test_chunked_product_row_resume_rejects_missing_saved_candidate_under_fetch_freeze(self) -> None:
        payload = _build_product_coverage_payload(3)
        _attach_product_row_raw_post_evidence(payload)
        _attach_product_row_fetch_freeze(payload, upper_message_id=3)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 1,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 1,
            }
        )
        first_mock_path = _build_product_coverage_mock(payload)
        resumed_payload = _build_product_coverage_payload(2)
        _attach_product_row_raw_post_evidence(resumed_payload)
        _attach_product_row_fetch_freeze(resumed_payload, upper_message_id=3)
        resumed_payload["normalized_request"].update(payload["normalized_request"])
        resumed_mock_path = _build_product_coverage_mock(resumed_payload)
        try:
            first = process_post_merge_payload(payload, mock_response_path=first_mock_path)
            state = first["llm_stage"]["product_row_chunking"]["continuation_state"]
            resumed_payload["normalized_request"]["llm_product_row_continuation_state"] = state
            resumed_payload["normalized_request"]["llm_product_row_continuation_token"] = state["continuation_token"]

            result = process_post_merge_payload(resumed_payload, mock_response_path=resumed_mock_path)
        finally:
            Path(first_mock_path).unlink(missing_ok=True)
            Path(resumed_mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "error")
        self.assertEqual(
            result["llm_stage"]["reason"],
            "llm_product_row_continuation_state_candidate_mismatch",
        )
        self.assertEqual(result["llm_stage"]["calls_attempted"], 0)
        self.assertEqual(
            result["llm_stage"]["product_row_chunking"]["error"],
            "llm_product_row_continuation_state_candidate_mismatch",
        )
        self.assertFalse(result["llm_stage"]["product_row_coverage"]["coverage_complete"])
        self.assertEqual(
            result["llm_stage"]["product_row_coverage"]["incomplete_reason"],
            "llm_product_row_continuation_state_candidate_mismatch",
        )
        mismatch = result["llm_stage"]["product_row_chunking"]["candidate_mismatch_evidence"]
        self.assertEqual(mismatch["saved_candidate_total"], 3)
        self.assertEqual(mismatch["current_candidate_total"], 2)
        self.assertEqual(mismatch["missing_candidate_ids"], ["offer:coverage:002"])
        self.assertEqual(mismatch["unexpected_candidate_ids"], [])
        self.assertEqual(mismatch["changed_candidate_ids"], [])
        self.assertFalse(mismatch["can_retry_same_continuation_state"])
        self.assertEqual(
            mismatch["safe_repair_contract"],
            "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required",
        )

    def test_chunked_product_row_resume_blocks_old_fetch_freeze_without_lower_bound(self) -> None:
        payload = _build_product_coverage_payload(3)
        _attach_product_row_raw_post_evidence(payload)
        _attach_product_row_fetch_freeze(payload, upper_message_id=3)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 1,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 1,
            }
        )
        mock_path = _build_product_coverage_mock(payload)
        try:
            first = process_post_merge_payload(payload, mock_response_path=mock_path)
            old_state = copy.deepcopy(first["llm_stage"]["product_row_chunking"]["continuation_state"])
            for source in old_state["fetch_freeze"]["sources"]:
                source.pop("cutoff_utc", None)
                source.pop("oldest_post_utc", None)
                source.pop("lower_message_id", None)
            old_state["continuation_token"] = _product_row_continuation_token(old_state)
            resumed_payload = copy.deepcopy(payload)
            resumed_payload["normalized_request"]["llm_product_row_continuation_state"] = old_state
            resumed_payload["normalized_request"]["llm_product_row_continuation_token"] = old_state["continuation_token"]

            result = process_post_merge_payload(resumed_payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "error")
        self.assertEqual(
            result["llm_stage"]["reason"],
            "llm_product_row_continuation_state_missing_fetch_lower_bound",
        )
        self.assertEqual(result["llm_stage"]["calls_attempted"], 0)
        chunking = result["llm_stage"]["product_row_chunking"]
        self.assertEqual(chunking["status"], "blocked")
        self.assertEqual(
            chunking["error"],
            "llm_product_row_continuation_state_missing_fetch_lower_bound",
        )
        self.assertEqual(
            chunking["safe_repair_contract"],
            "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required",
        )
        self.assertEqual(chunking["fetch_freeze_missing_lower_bound_sources"][0]["upper_message_id"], 3)
        self.assertEqual(
            result["llm_stage"]["product_row_coverage"]["incomplete_reason"],
            "llm_product_row_continuation_state_missing_fetch_lower_bound",
        )

    def test_chunked_product_row_resume_rejects_same_ids_with_changed_candidate_facts(self) -> None:
        payload = _build_product_coverage_payload(3)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 1,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 1,
            }
        )
        mock_path = _build_product_coverage_mock(payload)
        try:
            first = process_post_merge_payload(payload, mock_response_path=mock_path)
            state = first["llm_stage"]["product_row_chunking"]["continuation_state"]
            resumed_payload = copy.deepcopy(payload)
            resumed_payload["merge_output"]["offers"][1]["details_candidate"] = "Измененный факт кандидата."
            resumed_payload["normalized_request"]["llm_product_row_continuation_state"] = state
            resumed_payload["normalized_request"]["llm_product_row_continuation_token"] = state["continuation_token"]

            result = process_post_merge_payload(resumed_payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "error")
        self.assertEqual(
            result["llm_stage"]["reason"],
            "llm_product_row_continuation_state_candidate_mismatch",
        )
        self.assertEqual(result["llm_stage"]["calls_attempted"], 0)
        self.assertEqual(
            result["llm_stage"]["product_row_chunking"]["error"],
            "llm_product_row_continuation_state_candidate_mismatch",
        )
        mismatch = result["llm_stage"]["product_row_chunking"]["candidate_mismatch_evidence"]
        self.assertEqual(mismatch["missing_candidate_ids"], [])
        self.assertEqual(mismatch["unexpected_candidate_ids"], [])
        self.assertEqual(mismatch["changed_candidate_ids"], ["offer:coverage:001"])

    def test_chunked_product_row_resume_rejects_failed_state(self) -> None:
        payload = _build_product_coverage_payload(3)
        payload["normalized_request"].update(
            {
                "llm_product_row_max_candidates": 1,
                "llm_product_row_chunking_enabled": True,
                "llm_product_row_chunk_size": 1,
            }
        )
        mock_path = _build_product_coverage_mock(payload)
        try:
            first = process_post_merge_payload(payload, mock_response_path=mock_path)
            failed_state = copy.deepcopy(first["llm_stage"]["product_row_chunking"]["continuation_state"])
            failed_state["coverage_status"] = "failed"
            failed_state["failed_candidate_ids"] = [failed_state["processed_candidate_ids"][0]]
            failed_state["continuation_token"] = ""
            resumed_payload = copy.deepcopy(payload)
            resumed_payload["normalized_request"]["llm_product_row_continuation_state"] = failed_state

            result = process_post_merge_payload(resumed_payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "error")
        self.assertEqual(result["llm_stage"]["reason"], "llm_product_row_continuation_state_failed")
        self.assertEqual(result["llm_stage"]["calls_attempted"], 0)
        self.assertEqual(
            result["llm_stage"]["product_row_chunking"]["error"],
            "llm_product_row_continuation_state_failed",
        )

    def test_clean_deterministic_publish_row_still_gets_product_llm_coverage(self) -> None:
        payload = _build_product_coverage_payload(1)
        payload["merge_output"]["offers"][0]["fact_pack_flags"] = []
        mock_path = _build_product_coverage_mock(payload)
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        product_breakdown = result["llm_stage"]["stage_breakdown"]["llm_product_row_shape"]
        self.assertEqual(product_breakdown["eligible_entities"], 1)
        self.assertEqual(product_breakdown["vendor_attempts"], 1)
        self.assertEqual(product_breakdown["accepted_patches"], 1)
        coverage = result["llm_stage"]["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], 1)
        self.assertEqual(coverage["successful_decisions"], 1)
        self.assertTrue(coverage["coverage_complete"])

    def test_policy_drop_rows_are_excluded_from_product_row_llm_candidates(self) -> None:
        cases = [
            (
                {
                    "raw_post_id": "raw:model-search-3362",
                    "post_key": "raw:model-search-3362",
                    "chat_id": "1001",
                    "message_id": 3362,
                    "source_channel_key": "example_source_zeta",
                    "chat_title": "Model Beograd",
                    "chat_kind": "channel",
                    "chat_username": "example_source_zeta",
                    "post_url": "https://t.me/example_source_zeta/3362",
                    "posted_at_utc": "2026-04-24T10:00:00Z",
                    "text_raw": "Нужна модель на макияж для пополнения портфолио, оплата только за материалы. Писать @example_makeup_studio",
                },
                {
                    "offer_key": "offer:model-search-3362",
                    "provider_key": "provider:model-search-3362",
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["makeup", "model"],
                    "service_name_candidate": "Модель на макияж",
                    "details_candidate": "Нужна модель на макияж для пополнения портфолио, оплата только за материалы.",
                    "contact_handle": "example_makeup_studio",
                },
                "deterministic_model_search_drop",
            ),
            (
                {
                    "raw_post_id": "raw:model-search-3395",
                    "post_key": "raw:model-search-3395",
                    "chat_id": "1001",
                    "message_id": 3395,
                    "source_channel_key": "example_source_zeta",
                    "chat_title": "Model Beograd",
                    "chat_kind": "channel",
                    "chat_username": "example_source_zeta",
                    "post_url": "https://t.me/example_source_zeta/3395",
                    "posted_at_utc": "2026-04-24T12:47:20Z",
                    "text_raw": (
                        "Ищу моделей на укладку феном, брашинг и локоны для отработки скорости. "
                        "Бесплатно на дому или 500 rsd в салоне. Писать @example_contact_beta"
                    ),
                },
                {
                    "offer_key": "offer:model-search-3395",
                    "provider_key": "provider:model-search-3395",
                    "category_primary": "",
                    "service_tags": ["grad", "stari", "бесплатно", "брашинг", "локоны"],
                    "service_name_candidate": "По стоимости: бесплатно (на дому) либо 500 rsd (в салоне)",
                    "details_candidate": "По стоимости: бесплатно (на дому) либо 500 rsd (в салоне)",
                    "contact_handle": "example_contact_beta",
                },
                "deterministic_model_search_drop",
            ),
            (
                {
                    "raw_post_id": "raw:real-estate-platform-2042",
                    "post_key": "raw:real-estate-platform-2042",
                    "chat_id": "1003",
                    "message_id": 2042,
                    "source_channel_key": "example_source_delta",
                    "chat_title": "Serbia Works",
                    "chat_kind": "channel",
                    "chat_username": "example_source_delta",
                    "post_url": "https://t.me/example_source_delta/2042",
                    "posted_at_utc": "2026-04-24T13:30:00Z",
                    "text_raw": (
                        "Покупайте и продавайте правильно и бесплатно! Лучшее место для вашей недвижимости. "
                        "Умный поиск на карте, безлимитные бесплатные объявления, встроенный чат и отзывы. "
                        "Пишите @example_contact_gamma"
                    ),
                },
                {
                    "offer_key": "offer:real-estate-platform-2042",
                    "provider_key": "provider:real-estate-platform-2042",
                    "category_primary": "food_hospitality",
                    "service_tags": ["it_digital", "real_estate", "marketplace"],
                    "service_name_candidate": "Покупайте и продавайте правильно и бесплатно!",
                    "details_candidate": (
                        "Лучшее место для вашей недвижимости; умный поиск на карте; "
                        "безлимитные бесплатные объявления; встроенный чат и отзывы."
                    ),
                    "contact_handle": "example_contact_gamma",
                },
                "deterministic_platform_promo_drop",
            ),
            (
                {
                    "raw_post_id": "raw:remote-platform-2027",
                    "post_key": "raw:remote-platform-2027",
                    "chat_id": "1003",
                    "message_id": 2027,
                    "source_channel_key": "example_source_delta",
                    "chat_title": "Serbia Works",
                    "chat_kind": "channel",
                    "chat_username": "example_source_delta",
                    "post_url": "https://t.me/example_source_delta/2027",
                    "posted_at_utc": "2026-04-24T13:00:00Z",
                    "text_raw": (
                        "Покрећемо платформу за запошљавање за рад на даљину. "
                        "Погледајте TG канал и веб-сајт, придружите се каналу."
                    ),
                },
                {
                    "offer_key": "offer:remote-platform-2027",
                    "provider_key": "provider:remote-platform-2027",
                    "category_primary": "it_digital",
                    "service_tags": ["platform", "remote work", "hiring"],
                    "service_name_candidate": "Платформа для удалённой работы",
                    "details_candidate": "TG канал и веб-сайт с материалами для remote work и найма.",
                    "contact_handle": "remote_jobs_platform",
                },
                "deterministic_remote_work_platform_drop",
            ),
            (
                {
                    "raw_post_id": "raw:service-channel-hiring-70799",
                    "post_key": "raw:service-channel-hiring-70799",
                    "chat_id": "1004",
                    "message_id": 70799,
                    "source_channel_key": "example_source_beta",
                    "chat_title": "Специалисты Сербия",
                    "chat_kind": "channel",
                    "chat_username": "example_source_beta",
                    "post_url": "https://t.me/example_source_beta/70799",
                    "posted_at_utc": "2026-04-28T10:00:00Z",
                    "text_raw": (
                        "Бьюти студия в Новом Белграде открывает набор мастеров. "
                        "Ищем мастера в нашу дружную команду: подолог, мастер маникюра и педикюра, "
                        "мастер по наращиванию ресниц. Требования: опыт от 2 лет, аккуратность. "
                        "Условия: оплата 40-50% от чека, выплата 2 раза в месяц. Писать @example_contact_delta"
                    ),
                },
                {
                    "offer_key": "offer:service-channel-hiring-70799",
                    "provider_key": "provider:service-channel-hiring-70799",
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["beauty_cosmetology", "manicure", "pedicure", "lashes"],
                    "service_name_candidate": "Бьюти студия в Новом Белграде открывает набор мастеров",
                    "details_candidate": (
                        "Ищем мастера в нашу дружную команду. Требования: опыт от 2 лет. "
                        "Условия: оплата 40-50% от чека, выплата 2 раза в месяц."
                    ),
                    "contact_handle": "example_contact_delta",
                },
                "deterministic_vacancy_drop",
            ),
            (
                {
                    "raw_post_id": "raw:auto-rental-hiring-41000",
                    "post_key": "raw:auto-rental-hiring-41000",
                    "chat_id": "1005",
                    "message_id": 41000,
                    "source_channel_key": "example_source_gamma",
                    "chat_title": "Сербия услуги",
                    "chat_kind": "channel",
                    "chat_username": "example_source_gamma",
                    "post_url": "https://t.me/example_source_gamma/41000",
                    "posted_at_utc": "2026-04-28T12:00:00Z",
                    "text_raw": (
                        "Требуется менеджер в rent-a-car. Ищем в команду сотрудника, "
                        "обязанности: оформление договоров, депозит и страховка клиентов, зарплата. "
                        "Писать @example_contact_epsilon"
                    ),
                },
                {
                    "offer_key": "offer:auto-rental-hiring-41000",
                    "provider_key": "provider:auto-rental-hiring-41000",
                    "category_primary": "auto_service",
                    "service_tags": ["auto_service", "car rental", "hiring"],
                    "service_name_candidate": "Требуется менеджер в rent-a-car",
                    "details_candidate": (
                        "Ищем в команду сотрудника; обязанности: оформление договоров, "
                        "депозит и страховка клиентов, зарплата."
                    ),
                    "contact_handle": "example_contact_epsilon",
                },
                "deterministic_vacancy_drop",
            ),
            (
                {
                    "raw_post_id": "raw:rental-listing-234683",
                    "post_key": "raw:rental-listing-234683",
                    "chat_id": "1002",
                    "message_id": 234683,
                    "source_channel_key": "example_source_eta",
                    "chat_title": "Flats to rent Belgrade",
                    "chat_kind": "channel",
                    "chat_username": "example_source_eta",
                    "post_url": "https://t.me/example_source_eta/234683",
                    "posted_at_utc": "2026-04-24T11:00:00Z",
                    "text_raw": "Аренда квартиры в Белграде. Для записи на просмотр укажите дату заезда, срок и кто будет жить.",
                },
                {
                    "offer_key": "offer:rental-listing-234683",
                    "provider_key": "provider:rental-listing-234683",
                    "category_primary": "",
                    "service_tags": ["rent", "real estate"],
                    "service_name_candidate": "Аренда квартиры в Белграде",
                    "details_candidate": "Для записи на просмотр укажите дату заезда, срок и кто будет жить в квартире.",
                    "contact_handle": "example_source_eta",
                },
                "deterministic_real_estate_listing_drop",
            ),
        ]

        for raw_post, offer_overrides, expected_reason in cases:
            with self.subTest(anchor=raw_post["post_url"]):
                payload = _build_direct_product_payload(raw_post=raw_post, **offer_overrides)

                candidates = _product_row_candidates_for_payload(payload)

                offer = payload["merge_output"]["offers"][0]
                self.assertEqual(candidates, [])
                self.assertEqual(offer["product_row_publish_decision"], "drop")
                self.assertEqual(offer["product_row_service_name"], "")
                self.assertEqual(offer["product_row_details"], "")
                self.assertEqual(offer["product_row_audit_reason"], expected_reason)

    def test_auto_rental_deposit_insurance_terms_still_reach_product_row_llm(self) -> None:
        raw_post = {
            "raw_post_id": "raw:auto-rental-40904",
            "post_key": "raw:auto-rental-40904",
            "chat_id": "1005",
            "message_id": 40904,
            "source_channel_key": "example_source_gamma",
            "chat_title": "Сербия услуги",
            "chat_kind": "channel",
            "chat_username": "example_source_gamma",
            "post_url": "https://t.me/example_source_gamma/40904",
            "posted_at_utc": "2026-04-28T09:00:00Z",
            "text_raw": (
                "Аренда Citroen C3 (акпп, дизель). Белград. 18-40 EUR/сутки. "
                "Минимум 3 суток или помесячно. Депозит и страховка требуются. "
                "Предоставим с полным баком. Писать @example_contact_zeta"
            ),
        }
        payload = _build_direct_product_payload(
            raw_post=raw_post,
            offer_key="offer:auto-rental-40904",
            provider_key="provider:auto-rental-40904",
            category_primary="auto_service",
            service_tags=["auto_service", "car rental", "citroen", "акпп", "дизель"],
            service_name_candidate="Аренда Citroen C3 (акпп, дизель)",
            details_candidate=(
                "Минимум 3 суток или помесячно. Депозит и страховка требуются. "
                "Предоставим с полным баком."
            ),
            contact_handle="example_contact_zeta",
        )

        candidates = _product_row_candidates_for_payload(payload)

        offer = payload["merge_output"]["offers"][0]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(offer["product_row_publish_decision"], "publish")
        self.assertNotEqual(offer["product_row_audit_reason"], "deterministic_vacancy_drop")

    def test_product_row_max_output_retries_same_candidate_with_larger_cap(self) -> None:
        payload = _build_product_coverage_payload(1)
        offer_key = payload["merge_output"]["offers"][0]["offer_key"]
        schema_name = _safe_schema_name("tgss_product_row", offer_key)
        staircase = _response_max_output_token_staircase_for_schema(schema_name)
        mock_payload = {
            "responses": {
                schema_name: [
                    {
                        "expected_max_output_tokens": staircase[0],
                        "request_id": "req_product_cutoff_1",
                        "payload": {
                            "id": "mock-product-cutoff-1",
                            "status": "incomplete",
                            "incomplete_details": {
                                "reason": "max_output_tokens",
                            },
                            "usage": {
                                "input_tokens": 500,
                                "output_tokens": staircase[0],
                            },
                        },
                        "latency_ms": 22,
                    },
                    {
                        "expected_max_output_tokens": staircase[1],
                        "decision": {
                            "decision_code": "publish",
                            "confidence": 0.94,
                            "patch": {
                                "product_row_service_name": "Клининг квартиры",
                                "product_row_details": "Поддерживающая уборка квартиры в Белграде после переезда.",
                                "product_row_category": "Уборка и химчистка",
                                "product_row_contact": "@example_clean_belgrade",
                            },
                            "reason_text": "Retry with larger output cap completed the product row.",
                        },
                        "usage": {
                            "input_tokens": 510,
                            "output_tokens": 44,
                        },
                    },
                ],
            }
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(mock_payload, handle, ensure_ascii=False)
            mock_path = handle.name
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        product_breakdown = result["llm_stage"]["stage_breakdown"]["llm_product_row_shape"]
        self.assertEqual(product_breakdown["eligible_entities"], 1)
        self.assertEqual(product_breakdown["vendor_attempts"], 2)
        self.assertEqual(product_breakdown["max_output_retries"], 1)
        self.assertEqual(product_breakdown["accepted_patches"], 1)
        self.assertEqual(product_breakdown["coverage_failures"], 0)
        coverage = result["llm_stage"]["product_row_coverage"]
        self.assertEqual(coverage["attempts"], 2)
        self.assertEqual(coverage["max_output_retries"], 1)
        self.assertEqual(coverage["successful_decisions"], 1)
        self.assertTrue(coverage["coverage_complete"])
        audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertEqual([row["status"] for row in audit_rows], ["error", "accepted"])
        self.assertIn("request_id=req_product_cutoff_1", audit_rows[0]["response_excerpt"])

    def test_product_row_max_output_ceiling_hard_drops_instead_of_fallback_publish(self) -> None:
        payload = _build_product_coverage_payload(1)
        offer_key = payload["merge_output"]["offers"][0]["offer_key"]
        schema_name = _safe_schema_name("tgss_product_row", offer_key)
        staircase = _response_max_output_token_staircase_for_schema(schema_name)
        mock_payload = {
            "responses": {
                schema_name: [
                    {
                        "expected_max_output_tokens": cap,
                        "request_id": f"req_product_cutoff_{index}",
                        "payload": {
                            "id": f"mock-product-cutoff-{index}",
                            "status": "incomplete",
                            "incomplete_details": {
                                "reason": "max_output_tokens",
                            },
                            "usage": {
                                "input_tokens": 500 + index,
                                "output_tokens": cap,
                            },
                        },
                        "latency_ms": 22,
                    }
                    for index, cap in enumerate(staircase, start=1)
                ],
            }
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(mock_payload, handle, ensure_ascii=False)
            mock_path = handle.name
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        product_breakdown = result["llm_stage"]["stage_breakdown"]["llm_product_row_shape"]
        self.assertEqual(product_breakdown["vendor_attempts"], len(staircase))
        self.assertEqual(product_breakdown["max_output_retries"], len(staircase) - 1)
        self.assertEqual(product_breakdown["errors"], 1)
        self.assertEqual(product_breakdown["coverage_failures"], 1)
        self.assertEqual(product_breakdown["coverage_hard_drops"], 1)
        coverage = result["llm_stage"]["product_row_coverage"]
        self.assertEqual(coverage["candidate_total"], 1)
        self.assertEqual(coverage["failures"], 1)
        self.assertEqual(coverage["hard_drops"], 1)
        self.assertTrue(coverage["coverage_complete"])
        self.assertEqual(result["llm_stage"]["status"], "error")
        self.assertEqual(result["llm_stage"]["reason"], "product_row_coverage_failed")
        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "drop")
        self.assertEqual(shaped_offer["publishable_row"]["publish_decision"], "drop")
        self.assertIn("max_output_tokens ceiling", shaped_offer["product_row_audit_reason"])

    def test_category_refine_max_output_cutoff_falls_back_without_contract_error(self) -> None:
        offer_key = "offer:category-cutoff"
        provider_key = "provider:category-cutoff"
        raw_post_id = "tg:test:category-cutoff"
        schema_name = _safe_schema_name("tgss_category_offer", offer_key)
        product_schema_name = _safe_schema_name("tgss_product_row", offer_key)
        payload = {
            "run_id": "tz-category-cutoff",
            "normalized_request": {
                "llm_enabled": True,
            },
            "raw_posts": [
                {
                    "raw_post_id": raw_post_id,
                    "post_url": "https://t.me/example_services/123",
                    "posted_at_utc": "2026-04-25T09:00:00Z",
                    "source_channel_key": "example_services",
                    "text_raw": "Клининг квартир и офисов в Белграде. Поддерживающая уборка по договоренности.",
                }
            ],
            "merge_output": {
                "providers": [
                    {
                        "provider_key": provider_key,
                        "provider_state": "accepted",
                        "identity_strength": "strong",
                        "dedupe_confidence": "high",
                        "display_name_best": "Fam Cleaning Belgrade",
                        "canonical_name": "Fam Cleaning Belgrade",
                        "provider_summary": "Клининг в Белграде.",
                        "service_category_hints": ["cleaning"],
                        "city_codes": ["belgrade"],
                        "evidence_raw_post_ids": [raw_post_id],
                    }
                ],
                "offers": [
                    {
                        "offer_key": offer_key,
                        "provider_key": provider_key,
                        "offer_state": "accepted",
                        "offer_rejection_reason": "",
                        "serbia_relevance_verdict": "serbia_relevant",
                        "category_primary": "cleaning",
                        "category_secondary": "",
                        "title_best": "Клининг",
                        "description_best": "Поддерживающая уборка квартир и офисов в Белграде.",
                        "service_name_candidate": "Клининг",
                        "details_candidate": "Поддерживающая уборка квартир и офисов в Белграде.",
                        "offer_summary": "",
                        "service_tags": ["cleaning"],
                        "city_codes": ["belgrade"],
                        "city_display_names": ["Белград"],
                        "dedupe_confidence": "high",
                        "service_signature_key": "cleaning-belgrade",
                        "fact_pack_quality": "clean",
                        "fact_pack_flags": [],
                        "contact_candidate_display": "@example_clean_belgrade",
                        "contact_snapshot_phones": [],
                        "contact_snapshot_telegram_handles": ["example_clean_belgrade"],
                        "contact_snapshot_telegram_links": [],
                        "contact_snapshot_emails": [],
                        "contact_snapshot_websites": [],
                        "explicit_contact_snapshot_phones": [],
                        "explicit_contact_snapshot_telegram_handles": ["example_clean_belgrade"],
                        "explicit_contact_snapshot_telegram_links": [],
                        "author_fallback_phones": [],
                        "author_fallback_telegram_handles": [],
                        "author_fallback_telegram_links": [],
                        "source_anchor_text": "@example_services/123",
                        "latest_post_url": "https://t.me/example_services/123",
                        "freshness_at_utc": "2026-04-25T09:00:00Z",
                        "last_seen_at_utc": "2026-04-25T09:00:00Z",
                        "evidence_raw_post_ids": [raw_post_id],
                    }
                ],
                "merge_summary": {},
            },
        }
        mock_payload = {
            "responses": {
                product_schema_name: {
                    "decision": {
                        "decision_code": "publish",
                        "confidence": 0.93,
                        "patch": {
                            "product_row_service_name": "Клининг",
                            "product_row_details": "Поддерживающая уборка квартир и офисов в Белграде.",
                            "product_row_category": "Уборка и химчистка",
                            "product_row_contact": "@example_clean_belgrade",
                        },
                        "reason_text": "Clear cleaning service from deterministic fact pack.",
                    },
                    "usage": {
                        "input_tokens": 300,
                        "output_tokens": 45,
                    },
                    "latency_ms": 24,
                },
                schema_name: {
                    "request_id": "req_category_cutoff_mock",
                    "payload": {
                        "id": "mock-category-cutoff",
                        "status": "incomplete",
                        "incomplete_details": {
                            "reason": "max_output_tokens",
                        },
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": (
                                            "{\"decision_code\":\"category_refined\",\"confidence\":0.81,"
                                            "\"patch\":{\"category_primary\":\"cleaning\",\"category_secondary\":null,"
                                            "\"service_tags\":[\"cleaning\"],\"offer_summary\":\""
                                        ),
                                    }
                                ],
                            }
                        ],
                        "usage": {
                            "input_tokens": 740,
                            "output_tokens": RESPONSE_MAX_OUTPUT_TOKENS,
                        },
                    },
                    "latency_ms": 31,
                }
            }
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(mock_payload, handle, ensure_ascii=False)
            mock_path = handle.name
        try:
            result = process_post_merge_payload(payload, mock_response_path=mock_path)
        finally:
            Path(mock_path).unlink(missing_ok=True)

        self.assertEqual(result["llm_stage"]["status"], "success")
        self.assertEqual(result["llm_stage"]["reason"], "llm_stage_completed")
        category_breakdown = result["llm_stage"]["stage_breakdown"]["llm_category_refine"]
        self.assertEqual(category_breakdown["eligible_entities"], 1)
        self.assertEqual(category_breakdown["vendor_attempts"], 1)
        self.assertEqual(category_breakdown["errors"], 0)
        self.assertEqual(category_breakdown["audit_only_patches"], 1)
        self.assertEqual(result["llm_stage"]["budget"]["last_outcome"], "category_refine_cutoff_fallback")
        audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_category_refine"
        ]
        self.assertEqual(len(audit_rows), 1)
        self.assertEqual(audit_rows[0]["status"], "skipped")
        self.assertEqual(audit_rows[0]["decision_code"], "category_refine_cutoff_fallback_no_change")
        self.assertIn("request_id=req_category_cutoff_mock", audit_rows[0]["response_excerpt"])
        self.assertNotEqual(audit_rows[0]["decision_code"], "call_failed")

    def test_exact_logistics_anchor_uses_fact_pack_only_and_corrects_category(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:40483",
            "post_key": "tg:test:40483",
            "chat_id": "1922228422",
            "message_id": 40483,
            "source_channel_key": "example_source_gamma",
            "chat_title": "Сербия Услуги",
            "chat_kind": "channel",
            "chat_username": "example_source_gamma",
            "post_url": "https://t.me/example_source_gamma/40483",
            "posted_at_utc": "2026-04-20T11:00:00Z",
            "text_raw": (
                "✅ Грузоперевозки №1 в Белграде \n\n"
                "🇷🇸 𝑹𝑼𝑺 𝑳𝑶𝑮𝑰𝑺𝑻𝑰𝑪𝑺 🇷🇸\n\n"
                "🚚 Квартирные и Офисные переезды \"под ключ\", доставка мебели из IKEA \n"
                "🚛 Перевозка любых грузов весом до 1500кг, объём кузова 10 м³\n"
                "💪 Проф. Грузчики\n"
                "🛠️ Разборка & Сборка мебели\n"
                "📦 Защитная упаковка \n"
                "✅ Предузетник\n"
                "💰 Различные способы оплаты (дин/евро/руб) \n"
                "🌍 Работаем по Белграду и всей Сербии, Европе & России \n\n"
                "☎️ +381600000002\n"
                "📲 WhatsApp, Viber, Telegram"
            ),
            "sender_title": "Example Provider",
            "_run_id": "tz-product-llm",
            "_target_key": "example_source_gamma",
            "_telegram_target_input": "@example_source_gamma",
            "_telegram_target_resolved": "@example_source_gamma",
        }
        payload = _build_payload(raw_post)
        offer = _stabilize_for_product_stage(
            payload,
            category_primary="beauty_cosmetology",
            service_tags=["cargo", "moving", "delivery"],
        )
        offer["price_candidate_text"] = "4000 RSD"
        offer["price_text_best"] = "4000 RSD"
        offer["price_min"] = 4000
        offer["price_max"] = 4000
        offer["currency_code"] = "rsd"

        deterministic_offers_by_key = {
            offer["offer_key"]: copy.deepcopy(offer),
        }
        current_offers_by_key = {
            offer["offer_key"]: copy.deepcopy(offer),
        }
        _seed_default_product_rows(list(current_offers_by_key.values()), deterministic_offers_by_key)
        candidates = _build_product_row_candidates(
            deterministic_providers_by_key={
                payload["merge_output"]["providers"][0]["provider_key"]: copy.deepcopy(payload["merge_output"]["providers"][0]),
            },
            deterministic_offers_by_key=deterministic_offers_by_key,
            offers_by_key=current_offers_by_key,
            raw_post_map={raw_post["raw_post_id"]: raw_post},
        )
        self.assertEqual(len(candidates), 1)
        candidate_payload = candidates[0].input_payload
        self.assertNotIn("draft_row", candidate_payload)
        self.assertTrue(candidate_payload["writer_contract"]["deterministic_default_is_not_final_writer"])
        self.assertIn("supporting_raw_post_excerpts", candidate_payload)
        self.assertEqual(candidate_payload["supporting_raw_post_excerpts"][0]["raw_post_id"], "tg:test:40483")
        self.assertEqual(candidate_payload["supporting_raw_post_excerpts"][0]["post_url"], "https://t.me/example_source_gamma/40483")
        self.assertIn("Грузоперевозки", candidate_payload["supporting_raw_post_excerpts"][0]["excerpt"])
        fact_pack = candidate_payload["deterministic_fact_pack"]
        self.assertIn("service_name_candidate", fact_pack)
        self.assertIn("details_candidate", fact_pack)
        self.assertIn("contact_candidates", fact_pack)
        self.assertEqual(fact_pack["price_candidate_text"], "4000 RSD")
        self.assertEqual(fact_pack["price_text_best"], "4000 RSD")
        self.assertEqual(fact_pack["price_min"], 4000)
        self.assertEqual(fact_pack["price_max"], 4000)
        self.assertEqual(fact_pack["currency_code"], "rsd")
        self.assertIn("source_anchor_text", fact_pack)
        self.assertIn("ad_dump_compacted", candidate_payload["deterministic_fact_pack"]["fact_pack_flags"])
        self.assertNotIn("+381600000002", candidate_payload["deterministic_fact_pack"]["details_candidate"])

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.94,
                "patch": {
                    "product_row_service_name": "Грузоперевозки и переезды",
                    "product_row_details": "Квартирные и офисные переезды, доставка мебели, грузчики и сборка.",
                    "product_row_category": "Переезды и доставка",
                    "product_row_contact": "+381600000002",
                },
                "reason_text": "Compact moving service summary from deterministic fact pack; wrong beauty category corrected.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["product_row_service_name"], "Грузоперевозки и переезды")
        self.assertEqual(
            shaped_offer["product_row_details"],
            "Квартирные и офисные переезды, доставка мебели, грузчики и сборка.",
        )
        self.assertEqual(shaped_offer["product_row_category"], "Переезды и доставка")
        self.assertEqual(shaped_offer["product_row_contact"], "+381600000002")
        self.assertEqual(
            result["llm_stage"]["stage_breakdown"]["llm_product_row_shape"]["accepted_patches"],
            1,
        )

    def test_product_row_promo_rank_service_label_is_normalized_without_coverage_failure(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:70777",
            "post_key": "tg:test:70777",
            "chat_id": "1004",
            "message_id": 70777,
            "source_channel_key": "example_source_beta",
            "chat_title": "Специалисты Сербия",
            "chat_kind": "channel",
            "chat_username": "example_source_beta",
            "post_url": "https://t.me/example_source_beta/70777",
            "posted_at_utc": "2026-04-28T09:00:00Z",
            "text_raw": (
                "Грузоперевозки №1 в Белграде\n"
                "Квартирные и офисные переезды под ключ, доставка мебели и бытовой техники. "
                "Перевозка любых грузов весом до 1500кг, объем кузова 10 м3. "
                "Работаем по Белграду и всей Сербии. WhatsApp, Viber, Telegram +381600000002"
            ),
            "sender_title": "Example Provider",
            "_run_id": "tz-product-llm",
            "_target_key": "example_source_beta",
            "_telegram_target_input": "@example_source_beta",
            "_telegram_target_resolved": "@example_source_beta",
        }
        payload = _build_payload(raw_post)
        _stabilize_for_product_stage(
            payload,
            category_primary="moving_delivery",
            service_tags=["moving_delivery", "cargo", "moving", "delivery"],
        )

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.86,
                "patch": {
                    "product_row_service_name": "Грузоперевозки №1 в Белграде",
                    "product_row_details": (
                        "Квартирные и офисные переезды под ключ; доставка мебели и бытовой техники; "
                        "перевозка грузов до 1500 кг. Работа по Белграду и Сербии."
                    ),
                    "product_row_category": "Переезды и доставка",
                    "product_row_contact": "+381600000002",
                },
                "reason_text": "Moving and cargo service is supported by the raw post; label contains rank-style promo noise.",
            },
        )

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "success")
        self.assertEqual(llm_stage["reason"], "llm_stage_completed")
        self.assertEqual(llm_stage["product_row_coverage"]["failures"], 0)
        self.assertEqual(llm_stage["product_row_coverage"]["hard_drops"], 0)
        self.assertTrue(llm_stage["product_row_coverage"]["coverage_complete"])
        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["product_row_service_name"], "Грузоперевозки")
        self.assertEqual(shaped_offer["publishable_row"]["publish_decision"], "publish")
        self.assertEqual(shaped_offer["publishable_row"]["service_name"], "Грузоперевозки")
        product_audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertEqual(product_audit_rows[0]["status"], "accepted")
        self.assertIn("field_normalized:product_row_service_name", product_audit_rows[0]["reason_text"])
        self.assertNotIn("field_invalid:product_row_service_name", product_audit_rows[0]["reason_text"])

    def test_product_row_trailing_price_service_label_is_normalized_without_coverage_failure(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:70840",
            "post_key": "tg:test:70840",
            "chat_id": "1004",
            "message_id": 70840,
            "source_channel_key": "example_source_beta",
            "chat_title": "Специалисты Сербия",
            "chat_kind": "channel",
            "chat_username": "example_source_beta",
            "post_url": "https://t.me/example_source_beta/70840",
            "posted_at_utc": "2026-04-28T20:19:54Z",
            "text_raw": (
                "Переезд по Белграду и Сербии. Грузоперевозки, квартирные и офисные переезды, "
                "доставка и сборка мебели. Стоимость от 4000 дин. Запись @example_contact_eta"
            ),
        }
        payload = _build_direct_product_payload(
            offer_key="offer:price-tail-moving",
            provider_key="provider:price-tail-moving",
            raw_post=raw_post,
            category_primary="moving_delivery",
            service_tags=["moving_delivery", "cargo", "moving", "delivery"],
            service_name_candidate="Переезд по Белграду",
            details_candidate="Квартирные и офисные переезды, доставка и сборка мебели.",
            contact_handle="example_contact_eta",
        )
        offer = payload["merge_output"]["offers"][0]
        offer["price_candidate_text"] = "от 4000 дин"
        offer["price_text_best"] = "4000 дин"
        offer["price_min"] = 4000
        offer["price_max"] = 4000
        offer["currency_code"] = "rsd"

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.82,
                "patch": {
                    "product_row_service_name": "Грузоперевозки и переезды от 4000 дин",
                    "product_row_details": "Квартирные и офисные переезды, доставка мебели, грузчики и упаковка.",
                    "product_row_category": "Переезды и доставка",
                    "product_row_contact": "@example_contact_eta",
                },
                "reason_text": "Moving service is concrete; service label included a trailing price clause.",
            },
        )

        llm_stage = result["llm_stage"]
        self.assertNotEqual(llm_stage["reason"], "product_row_coverage_failed")
        self.assertEqual(llm_stage["product_row_coverage"]["failures"], 0)
        self.assertEqual(llm_stage["product_row_coverage"]["hard_drops"], 0)
        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["product_row_service_name"], "Грузоперевозки и переезды")
        row = shaped_offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Грузоперевозки и переезды")
        self.assertEqual(row["price"], "4000 rsd")
        self.assertNotIn("4000", row["service_name"])
        self.assertNotIn("дин", row["service_name"].lower())
        product_audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertEqual(product_audit_rows[0]["status"], "accepted")
        self.assertIn("field_normalized:product_row_service_name", product_audit_rows[0]["reason_text"])
        self.assertNotIn("field_invalid:product_row_service_name", product_audit_rows[0]["reason_text"])

    def test_product_row_writer_keeps_photo_video_digital_category_and_cleans_portfolio_detail(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:70843",
            "post_key": "tg:test:70843",
            "chat_id": "1004",
            "message_id": 70843,
            "source_channel_key": "example_source_beta",
            "chat_title": "Специалисты Сербия",
            "chat_kind": "channel",
            "chat_username": "example_source_beta",
            "post_url": "https://t.me/example_source_beta/70843",
            "posted_at_utc": "2026-04-28T20:35:51Z",
            "text_raw": (
                "Снимаю видео и фото, монтирую качественные ролики. "
                "Имею опыт более 3 лет, пришлю портфолио. Писать @example_contact_alpha"
            ),
        }
        payload = _build_direct_product_payload(
            offer_key="offer:photo-video-production",
            provider_key="provider:photo-video-production",
            raw_post=raw_post,
            category_primary="",
            service_tags=["video", "photo", "editing"],
            service_name_candidate="Снимаю видео и фото, монтирую качественные ролики.",
            details_candidate="Имею опыт более 3 лет; пришлю портфолио.",
            contact_handle="example_contact_alpha",
        )

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.87,
                "patch": {
                    "product_row_service_name": "Видео- и фотосъёмка, монтаж роликов",
                    "product_row_details": "Видео- и фотосъёмка; монтаж качественных роликов; портфолио доступно.",
                    "product_row_category": "Digital и дизайн",
                    "product_row_contact": "@example_contact_alpha",
                },
                "reason_text": "Concrete photo/video shooting and video-editing service with provider portfolio wording.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        row = shaped_offer["publishable_row"]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["product_row_category"], "Digital и дизайн")
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Видео- и фотосъёмка, монтаж роликов")
        self.assertEqual(row["details"], "Видео- и фотосъёмка; Монтаж качественных роликов")
        self.assertEqual(row["category"], "Digital и дизайн")
        self.assertEqual(row["telegram"], "@example_contact_alpha")
        self.assertNotIn("портфолио", row["details"].lower())

    def test_product_row_writer_cleans_graphic_design_portfolio_channel_availability_detail(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:graphic-design",
            "post_key": "tg:test:graphic-design",
            "chat_id": "1004",
            "message_id": 70001,
            "source_channel_key": "example_source_beta",
            "chat_title": "Специалисты Сербия",
            "chat_kind": "channel",
            "chat_username": "example_source_beta",
            "post_url": "https://t.me/example_source_beta/70001",
            "posted_at_utc": "2026-04-28T20:35:51Z",
            "text_raw": (
                "Графический дизайн: логотипы, рекламные материалы, баннеры и инфографика. "
                "Канал/портфолио в Telegram указан в исходном посте. Писать @example_designer_contact"
            ),
        }
        payload = _build_direct_product_payload(
            offer_key="offer:graphic-design",
            provider_key="provider:graphic-design",
            raw_post=raw_post,
            category_primary="it_digital",
            service_tags=["graphic design", "logo", "advertising materials"],
            service_name_candidate="Графический дизайн — логотипы и рекламные материалы",
            details_candidate=(
                "Дизайн для соцсетей и рекламы, инфографика, баннеры, афиши, визитки; "
                "Канал/портфолио в Telegram указан в исходном посте."
            ),
            contact_handle="example_designer_contact",
        )

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.88,
                "patch": {
                    "product_row_service_name": "Графический дизайн — логотипы и рекламные материалы",
                    "product_row_details": (
                        "Дизайн для соцсетей и рекламы, инфографика, баннеры, афиши, визитки; "
                        "Канал/портфолио в Telegram указан в исходном посте."
                    ),
                    "product_row_category": "Digital и дизайн",
                    "product_row_contact": "@example_designer_contact",
                },
                "reason_text": "Concrete graphic-design service with provider portfolio/channel availability wording.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        row = shaped_offer["publishable_row"]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["product_row_category"], "Digital и дизайн")
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Графический дизайн — логотипы и рекламные материалы")
        self.assertEqual(row["details"], "Дизайн для соцсетей и рекламы, инфографика, баннеры, афиши, визитки")
        self.assertEqual(row["category"], "Digital и дизайн")
        self.assertEqual(row["telegram"], "@example_designer_contact")
        self.assertNotIn("портфолио", row["details"].lower())
        self.assertNotIn("telegram", row["details"].lower())

    def test_product_row_price_only_and_vague_price_tail_labels_stay_rejected(self) -> None:
        cases = ("от 4000 дин", "Доступно от 4000 дин", "Акция от 4000 дин")
        for label in cases:
            with self.subTest(label=label):
                raw_post = {
                    "raw_post_id": f"raw:price-tail-negative:{label}",
                    "post_key": f"raw:price-tail-negative:{label}",
                    "chat_id": "1004",
                    "message_id": 70841,
                    "source_channel_key": "example_source_beta",
                    "chat_title": "Специалисты Сербия",
                    "chat_kind": "channel",
                    "chat_username": "example_source_beta",
                    "post_url": f"https://t.me/example_source_beta/price-tail-negative-{len(label)}",
                    "posted_at_utc": "2026-04-28T20:20:54Z",
                    "text_raw": "Переезды и грузоперевозки по Белграду. Запись @example_contact_eta",
                }
                payload = _build_direct_product_payload(
                    offer_key=f"offer:price-tail-negative:{len(label)}",
                    provider_key=f"provider:price-tail-negative:{len(label)}",
                    raw_post=raw_post,
                    category_primary="moving_delivery",
                    service_tags=["moving_delivery", "cargo", "moving", "delivery"],
                    service_name_candidate="Грузоперевозки и переезды",
                    details_candidate="Квартирные и офисные переезды, доставка мебели.",
                    contact_handle="example_contact_eta",
                )

                result = _run_with_product_mock(
                    payload,
                    {
                        "decision_code": "publish",
                        "confidence": 0.86,
                        "patch": {
                            "product_row_service_name": label,
                            "product_row_details": "Квартирные и офисные переезды, доставка мебели.",
                            "product_row_category": "Переезды и доставка",
                            "product_row_contact": "@example_contact_eta",
                        },
                        "reason_text": "Unsafe product-row service label must not publish.",
                    },
                )

                llm_stage = result["llm_stage"]
                self.assertEqual(llm_stage["status"], "error")
                self.assertEqual(llm_stage["reason"], "product_row_coverage_failed")
                self.assertEqual(llm_stage["product_row_coverage"]["failures"], 1)
                self.assertEqual(llm_stage["product_row_coverage"]["hard_drops"], 1)
                shaped_offer = result["canonical_output"]["offers"][0]
                self.assertEqual(shaped_offer["product_row_publish_decision"], "drop")
                self.assertEqual(shaped_offer["product_row_service_name"], "")
                product_audit_rows = [
                    row for row in result["audit_enrichment_rows"]
                    if row["stage"] == "llm_product_row_shape"
                ]
                self.assertEqual(product_audit_rows[0]["status"], "rejected")
                self.assertIn("field_invalid:product_row_service_name", product_audit_rows[0]["reason_text"])

    def test_greeting_and_self_intro_anchor_becomes_clean_publish_row(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:intro",
            "post_key": "tg:test:intro",
            "chat_id": "5000",
            "message_id": 42,
            "source_channel_key": "example_source_mu",
            "chat_title": "Маникюр Белград",
            "chat_kind": "channel",
            "chat_username": "example_source_mu",
            "post_url": "https://t.me/example_source_mu/42",
            "posted_at_utc": "2026-04-21T12:00:00Z",
            "text_raw": (
                "Всем привет!\n"
                "Меня зовут Нина, я мастер маникюра и педикюра в Нови Саде\n"
                "Делаю маникюр, педикюр и укрепление гелем\n"
                "Пишите @example_nina_nails"
            ),
            "sender_title": "Example Provider",
            "_run_id": "tz-product-llm",
            "_target_key": "example_source_mu",
            "_telegram_target_input": "@example_source_mu",
            "_telegram_target_resolved": "@example_source_mu",
        }
        payload = _build_payload(raw_post)
        offer = _stabilize_for_product_stage(
            payload,
            category_primary="beauty_cosmetology",
            service_tags=["manicure", "pedicure"],
        )
        self.assertIn("greeting_filtered", offer["fact_pack_flags"])
        self.assertIn("self_intro_filtered", offer["fact_pack_flags"])

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.93,
                "patch": {
                    "product_row_service_name": "Маникюр и педикюр",
                    "product_row_details": "Маникюр, педикюр и укрепление гелем в Нови-Саде.",
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "@example_nina_nails",
                },
                "reason_text": "Greeting and self-intro removed; deterministic fact pack still shows a clear nail service.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["product_row_service_name"], "Маникюр и педикюр")
        self.assertEqual(shaped_offer["product_row_category"], "Красота и здоровье")
        self.assertEqual(shaped_offer["product_row_contact"], "@example_nina_nails")
        self.assertNotIn("Всем привет", shaped_offer["product_row_service_name"])
        self.assertNotIn("Меня зовут", shaped_offer["product_row_details"])

    def test_product_row_publish_without_llm_service_label_hard_drops_instead_of_fallback(self) -> None:
        payload = _build_product_coverage_payload(1)

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.91,
                "patch": {
                    "product_row_service_name": None,
                    "product_row_details": "Поддерживающая уборка квартиры в Белграде после переезда.",
                    "product_row_category": "Уборка и химчистка",
                    "product_row_contact": "@example_clean_belgrade",
                },
                "reason_text": "The row should not fall back to deterministic service labels when LLM output is incomplete.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "drop")
        self.assertEqual(shaped_offer["product_row_service_name"], "")
        self.assertEqual(shaped_offer["publishable_row"]["publish_decision"], "drop")
        self.assertEqual(result["llm_stage"]["product_row_coverage"]["hard_drops"], 1)
        self.assertEqual(result["llm_stage"]["reason"], "product_row_coverage_failed")

    def test_near_threshold_product_row_publish_is_accepted_after_safety_validation(self) -> None:
        raw_post = {
            "raw_post_id": "raw:sugaring-5159",
            "post_key": "raw:sugaring-5159",
            "chat_id": "2143000733",
            "message_id": 5159,
            "source_channel_key": "example_source_alpha",
            "chat_title": "Сербия - Специалисты, услуги, работа",
            "chat_kind": "supergroup",
            "chat_username": "example_source_alpha",
            "post_url": "https://t.me/example_source_alpha/5159",
            "posted_at_utc": "2026-04-24T14:00:00Z",
            "text_raw": (
                "Сертифицированный мастер депиляции приглашает на шугаринг и восковую депиляцию. "
                "Подбираю технику индивидуально, работаю аккуратно и спокойно. Запись @example_contact_theta"
            ),
        }
        payload = _build_direct_product_payload(
            offer_key="offer:sugaring-5159",
            provider_key="provider:sugaring-5159",
            raw_post=raw_post,
            category_primary="beauty_cosmetology",
            service_tags=["depilation", "sugaring", "waxing"],
            service_name_candidate="Сертифицированный мастер депиляции",
            details_candidate="Шугаринг и восковая депиляция, индивидуальный подбор техники.",
            contact_handle="example_contact_theta",
        )
        payload["merge_output"]["providers"][0]["display_name_best"] = "Sugar Master Belgrade"
        payload["merge_output"]["providers"][0]["canonical_name"] = "Sugar Master Belgrade"

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.73,
                "patch": {
                    "product_row_service_name": "Шугаринг и восковая депиляция",
                    "product_row_details": "Шугаринг и восковая депиляция с индивидуальным подбором техники.",
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "@example_contact_theta",
                },
                "reason_text": "Near-threshold but structurally safe depilation service row.",
            },
        )

        llm_stage = result["llm_stage"]
        self.assertEqual(llm_stage["status"], "success")
        self.assertEqual(llm_stage["reason"], "llm_stage_completed")
        self.assertEqual(llm_stage["product_row_coverage"]["failures"], 0)
        self.assertEqual(llm_stage["product_row_coverage"]["hard_drops"], 0)
        self.assertTrue(llm_stage["product_row_coverage"]["coverage_complete"])
        self.assertEqual(llm_stage["stage_breakdown"]["llm_product_row_shape"]["accepted_patches"], 1)
        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["publishable_row"]["publish_decision"], "publish")
        self.assertEqual(shaped_offer["publishable_row"]["service_name"], "Шугаринг и восковая депиляция")
        product_audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertEqual(product_audit_rows[0]["status"], "accepted")
        self.assertIn("near_threshold_safe_publish", product_audit_rows[0]["reason_text"])

    def test_structured_low_confidence_product_row_publish_is_recovered_after_publishable_validation(self) -> None:
        raw_post = {
            "raw_post_id": "tg:1922228422:5195",
            "post_key": "tg:1922228422:5195",
            "chat_id": "1922228422",
            "message_id": 5195,
            "source_channel_key": "example_source_alpha",
            "chat_title": "Сербия - Специалисты, услуги, работа",
            "chat_kind": "supergroup",
            "chat_username": "example_source_alpha",
            "post_url": "https://t.me/example_source_alpha/5195",
            "posted_at_utc": "2026-04-28T09:00:00Z",
            "text_raw": (
                "Маркетолог с 5 лет практики помогает с упаковкой Instagram и запуском "
                "таргетированной рекламы для русскоязычной, англоязычной и азиатской аудиторий. "
                "Кейсы в США, ОАЭ, Бали, Таиланде, Аргентине, Израиле, Канаде, Сербии. "
                "Писать @example_contact_iota"
            ),
        }
        payload = _build_direct_product_payload(
            offer_key="offer:870324da29d9ef3f0d4caba1e377f17ed9310885",
            provider_key="provider:marr-marketing",
            raw_post=raw_post,
            category_primary="marketing_promotion",
            service_tags=["smm", "targeting", "instagram"],
            service_name_candidate="SMM и таргетинг Instagram",
            details_candidate="Упаковка Instagram и запуск таргетированной рекламы.",
            contact_handle="example_contact_iota",
        )
        payload["merge_output"]["providers"][0]["display_name_best"] = "Marr Marketing"
        payload["merge_output"]["providers"][0]["canonical_name"] = "Marr Marketing"

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.67,
                "patch": {
                    "product_row_service_name": "Комплексное СММ и таргетинг (Instagram)",
                    "product_row_details": (
                        "5 лет практики; упаковка Instagram и запуск таргетированной рекламы "
                        "для русскоязычной, англоязычной и азиатской аудиторий. Город: Nis."
                    ),
                    "product_row_category": "Digital и дизайн",
                    "product_row_contact": "@example_contact_iota",
                },
                "reason_text": "Low-confidence but structurally concrete SMM and targeting service row.",
            },
        )

        llm_stage = result["llm_stage"]
        coverage = llm_stage["product_row_coverage"]
        self.assertEqual(llm_stage["status"], "success")
        self.assertEqual(llm_stage["reason"], "llm_stage_completed")
        self.assertEqual(coverage["failures"], 0)
        self.assertEqual(coverage["hard_drops"], 0)
        self.assertEqual(coverage["recovered_low_confidence_publishes"], 1)
        self.assertTrue(coverage["coverage_complete"])

        shaped_offer = result["canonical_output"]["offers"][0]
        row = shaped_offer["publishable_row"]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Комплексное СММ и таргетинг (Instagram)")
        self.assertEqual(row["category"], "Digital и дизайн")
        self.assertEqual(row["telegram"], "@example_contact_iota")
        product_audit_rows = [
            row for row in result["audit_enrichment_rows"]
            if row["stage"] == "llm_product_row_shape"
        ]
        self.assertEqual(product_audit_rows[0]["status"], "accepted")
        self.assertIn("structured_low_confidence_safe_publish", product_audit_rows[0]["reason_text"])

    def test_structured_low_confidence_recovery_blocks_unsafe_publish_patches(self) -> None:
        cases = [
            (
                "incomplete_short_row",
                {
                    "product_row_service_name": "Клининг",
                    "product_row_details": "",
                    "product_row_category": "Уборка и химчистка",
                    "product_row_contact": "@example_clean_belgrade",
                },
                "structured_low_confidence_weak_details",
            ),
            (
                "promotional_label",
                {
                    "product_row_service_name": "Акция на уборку квартиры",
                    "product_row_details": "Сезонное спецпредложение на поддерживающую уборку квартиры в Белграде.",
                    "product_row_category": "Уборка и химчистка",
                    "product_row_contact": "@example_clean_belgrade",
                },
                "structured_low_confidence_weak_service_name",
            ),
            (
                "non_service_giveaway",
                {
                    "product_row_service_name": "Розыгрыш автосервиса",
                    "product_row_details": "Призовые места и подарки за участие в розыгрыше.",
                    "product_row_category": "Автоуслуги",
                    "product_row_contact": "@example_clean_belgrade",
                },
                "publishable_non_service",
            ),
        ]

        for case_name, patch, expected_warning in cases:
            with self.subTest(case=case_name):
                raw_post = {
                    "raw_post_id": f"raw:low-confidence-negative:{case_name}",
                    "post_key": f"raw:low-confidence-negative:{case_name}",
                    "chat_id": "1001",
                    "message_id": 9001,
                    "source_channel_key": "example_source_lambda",
                    "chat_title": "Cleaning Services",
                    "chat_kind": "channel",
                    "chat_username": "example_source_lambda",
                    "post_url": f"https://t.me/example_source_lambda/{case_name}",
                    "posted_at_utc": "2026-04-28T10:00:00Z",
                    "text_raw": (
                        "Поддерживающая уборка квартиры в Белграде после переезда. "
                        "Работаем аккуратно, запись @example_clean_belgrade"
                    ),
                }
                payload = _build_direct_product_payload(
                    offer_key=f"offer:low-confidence-negative:{case_name}",
                    provider_key=f"provider:low-confidence-negative:{case_name}",
                    raw_post=raw_post,
                    category_primary="cleaning",
                    service_tags=["cleaning"],
                    service_name_candidate="Клининг квартиры",
                    details_candidate="Поддерживающая уборка квартиры в Белграде после переезда.",
                    contact_handle="example_clean_belgrade",
                )

                result = _run_with_product_mock(
                    payload,
                    {
                        "decision_code": "publish",
                        "confidence": 0.67,
                        "patch": patch,
                        "reason_text": "Low-confidence unsafe product-row patch must not publish.",
                    },
                )

                llm_stage = result["llm_stage"]
                coverage = llm_stage["product_row_coverage"]
                self.assertEqual(llm_stage["status"], "error")
                self.assertEqual(llm_stage["reason"], "product_row_coverage_failed")
                self.assertEqual(coverage["failures"], 1)
                self.assertEqual(coverage["hard_drops"], 1)
                self.assertEqual(coverage["recovered_low_confidence_publishes"], 0)
                shaped_offer = result["canonical_output"]["offers"][0]
                self.assertEqual(shaped_offer["product_row_publish_decision"], "drop")
                self.assertEqual(shaped_offer["publishable_row"]["publish_decision"], "drop")
                product_audit_rows = [
                    row for row in result["audit_enrichment_rows"]
                    if row["stage"] == "llm_product_row_shape"
                ]
                self.assertEqual(product_audit_rows[0]["status"], "rejected")
                self.assertIn(expected_warning, product_audit_rows[0]["reason_text"])

    def test_product_row_writer_shapes_specific_training_row_from_raw_evidence(self) -> None:
        raw_post = {
            "raw_post_id": "raw:training",
            "post_key": "raw:training",
            "chat_id": "7000",
            "message_id": 77,
            "source_channel_key": "example_source_nu",
            "chat_title": "Тренировки Белград",
            "chat_kind": "channel",
            "chat_username": "example_source_nu",
            "post_url": "https://t.me/example_source_nu/77",
            "posted_at_utc": "2026-04-24T09:00:00Z",
            "text_raw": (
                "Направления групповых и индивидуальных занятий:\n"
                "Тайский бокс, бокс, растяжка, утренние и вечерние группы.\n"
                "Запись @example_coach_bg"
            ),
        }
        payload = _build_direct_product_payload(
            offer_key="offer:training",
            provider_key="provider:training",
            raw_post=raw_post,
            category_primary="education_tutoring",
            service_tags=["sports", "training", "boxing"],
            service_name_candidate="Направления групповых и индивидуальных занятий",
            details_candidate="Тайский бокс, бокс, растяжка, утренние и вечерние группы.",
            contact_handle="example_coach_bg",
        )

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.93,
                "patch": {
                    "product_row_service_name": "Тайский бокс, бокс и растяжка",
                    "product_row_details": "Групповые и индивидуальные занятия утром и вечером.",
                    "product_row_category": "Обучение",
                    "product_row_contact": "@example_coach_bg",
                },
                "reason_text": "Training service meaning is supported by the raw post excerpt.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        row = shaped_offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Тайский бокс, бокс и растяжка")
        self.assertEqual(row["details"], "Групповые и индивидуальные занятия утром и вечером.")
        self.assertEqual(row["category"], "Обучение")
        self.assertNotEqual(row["service_name"], "Направления групповых и индивидуальных занятий")

    def test_product_row_writer_replaces_slogan_label_with_service_meaning(self) -> None:
        raw_post = {
            "raw_post_id": "raw:cleaning-slogan",
            "post_key": "raw:cleaning-slogan",
            "chat_id": "8000",
            "message_id": 35,
            "source_channel_key": "example_source_xi",
            "chat_title": "Клининг Белград",
            "chat_kind": "channel",
            "chat_username": "example_source_xi",
            "post_url": "https://t.me/example_source_xi/35",
            "posted_at_utc": "2026-04-25T10:00:00Z",
            "text_raw": (
                "Сезон охоты на пыль открыт!\n"
                "Уборка квартир, генеральная уборка и поддерживающий клининг в Белграде.\n"
                "Пишите @example_clean_bg"
            ),
        }
        payload = _build_direct_product_payload(
            offer_key="offer:cleaning-slogan",
            provider_key="provider:cleaning-slogan",
            raw_post=raw_post,
            category_primary="cleaning",
            service_tags=["cleaning", "housekeeping"],
            service_name_candidate="Сезон охоты на пыль открыт",
            details_candidate="Уборка квартир, генеральная уборка и поддерживающий клининг в Белграде.",
            contact_handle="example_clean_bg",
        )

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.94,
                "patch": {
                    "product_row_service_name": "Клининг квартир",
                    "product_row_details": "Генеральная и поддерживающая уборка квартир в Белграде.",
                    "product_row_category": "Уборка и химчистка",
                    "product_row_contact": "@example_clean_bg",
                },
                "reason_text": "Slogan was replaced with normalized cleaning service meaning.",
            },
        )

        row = result["canonical_output"]["offers"][0]["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Клининг квартир")
        self.assertNotIn("сезон охоты", row["service_name"].lower())

    def test_resale_row_stays_dropped(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:resale",
            "post_key": "tg:test:resale",
            "chat_id": "6000",
            "message_id": 7,
            "source_channel_key": "example_source_omicron",
            "chat_title": "Продажа в Сербии",
            "chat_kind": "channel",
            "chat_username": "example_source_omicron",
            "post_url": "https://t.me/example_source_omicron/7",
            "posted_at_utc": "2026-04-21T13:00:00Z",
            "text_raw": (
                "Продам iPhone 15 Pro Max 256GB, 8GB RAM, состояние 10/10\n"
                "Цена 950 eur\n"
                "Пишите @seller"
            ),
            "_run_id": "tz-product-llm",
            "_target_key": "example_source_omicron",
            "_telegram_target_input": "@example_source_omicron",
            "_telegram_target_resolved": "@example_source_omicron",
        }
        payload = _build_payload(raw_post)

        result = process_post_merge_payload(payload)
        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "drop")
        self.assertEqual(shaped_offer["product_row_service_name"], "")
        self.assertEqual(shaped_offer["product_row_details"], "")
        self.assertEqual(shaped_offer["product_row_contact"], "")
        self.assertEqual(shaped_offer["product_row_audit_reason"], "non_service_resale")

    def test_weak_signal_row_honestly_abstains(self) -> None:
        payload = {
            "run_id": "tz-product-weak",
            "normalized_request": {
                "llm_enabled": True,
            },
            "merge_output": {
                "providers": [
                    {
                        "provider_key": "prov-weak",
                        "provider_state": "accepted",
                        "identity_strength": "strong",
                        "display_name_best": "Household Helper Belgrade",
                        "canonical_name": "Household Helper Belgrade",
                        "provider_summary": "",
                        "service_category_hints": ["cleaning"],
                        "city_codes": ["belgrade"],
                        "dedupe_confidence": "high",
                        "offer_count": 1,
                        "evidence_raw_post_ids": ["raw-weak"],
                    }
                ],
                "offers": [
                    {
                        "offer_key": "offer-weak",
                        "provider_key": "prov-weak",
                        "offer_state": "accepted",
                        "offer_rejection_reason": "",
                        "service_signature_key": "sig-weak",
                        "category_primary": "cleaning",
                        "evidence_raw_post_ids": ["raw-weak"],
                        "first_seen_at_utc": "2026-04-21T14:00:00Z",
                        "last_seen_at_utc": "2026-04-21T14:00:00Z",
                        "title_best": "Помогу с бытовыми вопросами в Белграде",
                        "description_best": "Разные бытовые задачи и помощь по договоренности, уточняйте в личке.",
                        "service_name_candidate": "Помогу с бытовыми вопросами в Белграде",
                        "details_candidate": "Разные бытовые задачи и помощь по договоренности, уточняйте в личке.",
                        "price_text_best": "",
                        "price_candidate_text": "",
                        "city_codes": ["belgrade"],
                        "city_display_names": ["Belgrade"],
                        "service_tags": ["help", "support"],
                        "contact_snapshot_phones": [],
                        "contact_snapshot_telegram_handles": [],
                        "contact_snapshot_telegram_links": [],
                        "contact_snapshot_emails": [],
                        "contact_snapshot_websites": [],
                        "contact_candidate_display": "",
                        "latest_post_url": "https://t.me/example_helper/1",
                        "source_anchor_text": "@example_helper/1",
                        "freshness_at_utc": "2026-04-21T14:00:00Z",
                        "fact_pack_quality": "weak_signal",
                        "fact_pack_flags": [],
                        "serbia_relevance_verdict": "serbia_relevant",
                        "offer_summary": "Разные бытовые задачи и помощь по договоренности.",
                    }
                ],
                "merge_summary": {},
            },
        }

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "drop",
                "confidence": 0.91,
                "patch": {
                    "product_row_service_name": None,
                    "product_row_details": None,
                    "product_row_category": None,
                    "product_row_contact": None,
                },
                "reason_text": "Weak and generic signal; deterministic fact pack does not support a publishable service row.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "drop")
        self.assertEqual(shaped_offer["product_row_service_name"], "")
        self.assertEqual(shaped_offer["product_row_details"], "")
        self.assertEqual(shaped_offer["product_row_category"], "")
        self.assertEqual(shaped_offer["product_row_contact"], "")

    def test_contact_outside_deterministic_candidates_is_not_applied(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:pedicure",
            "post_key": "tg:test:pedicure",
            "chat_id": "2143000733",
            "message_id": 5062,
            "source_channel_key": "example_source_alpha",
            "chat_title": "Сербия - Специалисты, услуги, работа",
            "chat_kind": "supergroup",
            "chat_username": "example_source_alpha",
            "post_url": "https://t.me/example_source_alpha/5062",
            "posted_at_utc": "2026-04-20T10:00:00Z",
            "text_raw": (
                "Medicinski pedikir na kućnoj adresi (Beograd / Novi Sad)\n"
                "Ako vaši roditelji imaju problem sa stopalima, tu sam da pomognem.\n"
                "Medicinska sestra po struci.\n"
                "+381600000001 Example Provider"
            ),
            "sender_title": "Example Provider",
            "_run_id": "tz-product-llm",
            "_target_key": "example_source_alpha",
            "_telegram_target_input": "@example_source_alpha",
            "_telegram_target_resolved": "@example_source_alpha",
        }
        payload = _build_payload(raw_post)
        offer = _stabilize_for_product_stage(
            payload,
            category_primary="beauty_cosmetology",
            service_tags=["pedicure", "medical"],
        )
        offer["fact_pack_quality"] = "weak_signal"

        result = _run_with_product_mock(
            payload,
            {
                "decision_code": "publish",
                "confidence": 0.92,
                "patch": {
                    "product_row_service_name": "Медицинский педикюр",
                    "product_row_details": "Выездной медицинский педикюр для пожилых и людей с проблемами стоп.",
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "@invented_contact",
                },
                "reason_text": "Service meaning is clear, but the chosen contact must stay within deterministic candidates.",
            },
        )

        shaped_offer = result["canonical_output"]["offers"][0]
        self.assertEqual(shaped_offer["product_row_publish_decision"], "publish")
        self.assertEqual(shaped_offer["product_row_service_name"], "Медицинский педикюр")
        self.assertEqual(shaped_offer["product_row_contact"], "+381600000001")
        self.assertNotEqual(shaped_offer["product_row_contact"], "@invented_contact")

    def test_distinct_author_telegram_fallback_is_used_when_post_has_no_explicit_contact(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:author-telegram",
            "post_key": "tg:test:author-telegram",
            "chat_id": "9000",
            "message_id": 91,
            "source_channel_key": "example_source_kappa",
            "chat_title": "Serbia services",
            "chat_kind": "channel",
            "chat_username": "example_source_kappa",
            "post_url": "https://t.me/example_source_kappa/91",
            "posted_at_utc": "2026-04-23T09:00:00Z",
            "text_raw": "Ремонт бойлеров с выездом по Белграду в день обращения.",
            "sender_id": "700001",
            "sender_title": "Example Provider",
            "sender_username": "example_boiler_master",
            "sender_profile_url": "https://t.me/example_boiler_master",
            "_run_id": "tz-product-llm",
            "_target_key": "example_source_kappa",
            "_telegram_target_input": "@example_source_kappa",
            "_telegram_target_resolved": "@example_source_kappa",
        }
        payload = _build_payload(raw_post, run_id="tz-author-telegram")
        result = process_post_merge_payload(
            {
                **payload,
                "normalized_request": {
                    "llm_enabled": False,
                },
            }
        )

        row = result["canonical_output"]["offers"][0]["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["telegram"], "@example_boiler_master")
        self.assertEqual(row["phone"], "")
        self.assertEqual(row["source"], "https://t.me/example_source_kappa/91")
        self.assertEqual(row["actual_on"], "23.04.2026")

    def test_distinct_author_phone_fallback_is_used_only_when_sender_phone_is_present(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:author-phone",
            "post_key": "tg:test:author-phone",
            "chat_id": "9001",
            "message_id": 92,
            "source_channel_key": "example_source_kappa",
            "chat_title": "Serbia services",
            "chat_kind": "channel",
            "chat_username": "example_source_kappa",
            "post_url": "https://t.me/example_source_kappa/92",
            "posted_at_utc": "2026-04-23T10:00:00Z",
            "text_raw": "Ремонт бойлеров с выездом по Белграду в день обращения.",
            "sender_id": "700002",
            "sender_title": "Example Provider",
            "sender_username": "example_boiler_master",
            "sender_profile_url": "https://t.me/example_boiler_master",
            "sender_phone": "+381600000003",
            "_run_id": "tz-product-llm",
            "_target_key": "example_source_kappa",
            "_telegram_target_input": "@example_source_kappa",
            "_telegram_target_resolved": "@example_source_kappa",
        }
        payload = _build_payload(raw_post, run_id="tz-author-phone")
        result = process_post_merge_payload(
            {
                **payload,
                "normalized_request": {
                    "llm_enabled": False,
                },
            }
        )

        row = result["canonical_output"]["offers"][0]["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["telegram"], "@example_boiler_master")
        self.assertEqual(row["phone"], "+381600000003")


if __name__ == "__main__":
    unittest.main()
