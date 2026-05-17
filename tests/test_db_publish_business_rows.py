from __future__ import annotations

import unittest

from scripts.db.publish_business_rows import build_publication_batch


def _build_payload() -> dict:
    return {
        "run_id": "run-db-publish-1",
        "normalized_request": {
            "google_sheet_id": "sheet-123",
            "llm_enabled": True,
            "cutoff_field": "months_back",
            "months_back": 1,
        },
        "service_run_candidate": {
            "run_id": "run-db-publish-1",
            "run_status": "success",
            "trigger_type": "webhook",
            "started_at_utc": "2026-04-22T18:12:52.083Z",
            "finished_at_utc": "2026-04-22T18:13:22.083Z",
            "duration_ms": 30000,
            "requested_targets_count": 1,
            "requested_targets_json": "[\"@example_source_alpha\"]",
            "successful_target_count": 1,
            "successful_targets_json": "[{\"target_key\":\"example_source_alpha\"}]",
            "failed_target_count": 0,
            "failed_targets_json": "[]",
            "sync_mode": "sheet_first_incremental",
            "max_messages": 15,
            "cutoff_policy_type": "months_back",
            "cutoff_policy_value": "1",
            "llm_enabled": True,
            "raw_posts_total": 2,
            "providers_total": 1,
            "offers_total": 2,
            "offers_upserted_total": 0,
            "fetch_messages_seen_total": 2,
            "structured_posts_total": 2,
            "llm_calls_total": 3,
            "llm_tokens_input_total": 111,
            "llm_tokens_output_total": 22,
            "llm_cost_estimate_usd": "0.017",
            "llm_review_required_count": 1,
            "warnings_json": "[\"warn-1\"]",
            "error_type": "",
            "error_message": "",
        },
        "service_run_sheet_row_final": {
            "run_id": "run-db-publish-1",
            "run_status": "success",
            "trigger_type": "webhook",
            "started_at_utc": "2026-04-22T18:12:52.083Z",
            "finished_at_utc": "2026-04-22T18:13:22.083Z",
            "duration_ms": 30000,
            "requested_targets_count": 1,
            "successful_target_count": 1,
            "failed_target_count": 0,
            "sync_mode": "sheet_first_incremental",
            "max_messages": 15,
            "cutoff_policy_type": "months_back",
            "cutoff_policy_value": "1",
            "llm_enabled": True,
            "raw_posts_total": 2,
            "providers_total": 1,
            "offers_total": 2,
            "offers_upserted_total": 0,
            "fetch_messages_seen_total": 2,
            "structured_posts_total": 2,
            "llm_calls_total": 3,
            "llm_tokens_input_total": 111,
            "llm_tokens_output_total": 22,
            "llm_cost_estimate_usd": "0.017",
            "llm_review_required_count": 1,
            "error_type": "",
            "error_message": "",
            "google_sheet_id": "sheet-123",
            "providers_sheet_name": "providers",
            "offers_sheet_name": "offers",
            "requested_targets_json": "[\"@example_source_alpha\"]",
            "successful_targets_json": "[{\"target_key\":\"example_source_alpha\"}]",
            "failed_targets_json": "[]",
            "warnings_json": "[\"warn-1\"]",
            "checkpoint_targets_json": "[{\"target_key\":\"example_source_alpha\",\"checkpoint_message_id\":\"2\"}]",
            "response_json": "{\"publication_summary\":{\"status\":\"success\"}}",
        },
        "run_targets_sheet_rows": [
            {
                "run_id": "run-db-publish-1",
                "target_key": "example_source_alpha",
                "target_input": "@example_source_alpha",
                "target_resolved": "https://t.me/example_source_alpha",
                "target_status": "success",
                "started_at_utc": "2026-04-22T18:12:52.083Z",
                "finished_at_utc": "2026-04-22T18:13:22.083Z",
                "checkpoint_message_id": "2",
                "raw_posts_emitted": 2,
                "error_type": "",
                "error_message": "",
                "target_stats_json": "{\"posts_emitted\":2}",
            }
        ],
        "canonical_output": {
            "providers": [
                {
                    "provider_key": "provider-1",
                    "provider_state": "candidate",
                    "identity_strength": "strong",
                    "display_name_best": "Provider One",
                    "canonical_name": "Provider One",
                    "provider_summary": "Summary",
                    "primary_contact_type": "phone",
                    "primary_contact_value": "+381600000004",
                    "latest_post_url": "https://t.me/example_source_alpha/2",
                    "first_seen_at_utc": "2026-04-22T18:12:52.083Z",
                    "last_seen_at_utc": "2026-04-22T18:13:22.083Z",
                    "first_seen_run_id": "run-db-publish-1",
                    "last_seen_run_id": "run-db-publish-1",
                    "times_seen": 2,
                    "offer_count": 2,
                    "dedupe_confidence": "high",
                    "phones": ["+381600000004"],
                    "telegram_handles": ["example_sample_provider"],
                    "telegram_links": ["https://t.me/example_sample_provider"],
                    "emails": ["hello@example.com"],
                    "city_codes": ["belgrade"],
                    "service_category_hints": ["cleaning"],
                    "source_channel_keys": ["example_source_alpha"],
                    "provider_quality_flags": ["has_contact"],
                }
            ],
            "offers": [
                {
                    "offer_key": "offer-1",
                    "provider_key": "provider-1",
                    "offer_state": "candidate",
                    "service_signature_key": "svc-1",
                    "category_primary": "cleaning",
                    "title_best": "Offer One",
                    "description_best": "Desc One",
                    "price_text_best": "30 EUR",
                    "price_min": 30,
                    "price_max": 30,
                    "currency_code": "EUR",
                    "latest_post_url": "https://t.me/example_source_alpha/1",
                    "first_seen_at_utc": "2026-04-22T18:12:52.083Z",
                    "last_seen_at_utc": "2026-04-22T18:13:22.083Z",
                    "first_seen_run_id": "run-db-publish-1",
                    "last_seen_run_id": "run-db-publish-1",
                    "times_seen": 1,
                    "dedupe_confidence": "high",
                    "serbia_relevance_verdict": "relevant",
                    "service_tags": ["cleaning"],
                    "city_codes": ["belgrade"],
                    "contact_snapshot_phones": ["+381600000004"],
                    "contact_snapshot_telegram_handles": ["example_sample_provider"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_sample_provider"],
                    "source_channel_keys": ["example_source_alpha"],
                    "offer_quality_flags": ["has_price"],
                },
                {
                    "offer_key": "offer-1",
                    "provider_key": "provider-1",
                    "offer_state": "candidate",
                    "service_signature_key": "svc-1",
                    "category_primary": "cleaning",
                    "title_best": "Offer One Updated",
                    "description_best": "Desc Updated",
                    "price_text_best": "30 EUR",
                    "price_min": 30,
                    "price_max": 30,
                    "currency_code": "EUR",
                    "latest_post_url": "https://t.me/example_source_alpha/2",
                    "first_seen_at_utc": "2026-04-22T18:12:52.083Z",
                    "last_seen_at_utc": "2026-04-22T18:13:22.083Z",
                    "first_seen_run_id": "run-db-publish-1",
                    "last_seen_run_id": "run-db-publish-1",
                    "times_seen": 2,
                    "dedupe_confidence": "high",
                    "serbia_relevance_verdict": "relevant",
                    "service_tags": ["cleaning", "repair"],
                    "city_codes": ["belgrade"],
                    "contact_snapshot_phones": ["+381600000004"],
                    "contact_snapshot_telegram_handles": ["example_sample_provider"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_sample_provider"],
                    "source_channel_keys": ["example_source_alpha"],
                    "fact_pack_flags": ["has_price", "has_contact"],
                },
            ],
        },
        "merge_output": {
            "merge_summary": {
                "layer_resolution_counts": {"layer1": 1},
                "field_resolution_counts": {"category_primary": 1},
            }
        },
    }


class DbPublishBusinessRowsTests(unittest.TestCase):
    def test_build_publication_batch_maps_rows_to_db_shape(self) -> None:
        batch = build_publication_batch(_build_payload())

        self.assertEqual(batch["run_id"], "run-db-publish-1")
        self.assertEqual(batch["service_run_row"]["offers_upserted_total"], 1)
        self.assertEqual(batch["service_run_row"]["requested_targets_json"], ["@example_source_alpha"])
        self.assertEqual(batch["service_run_row"]["warnings_json"], ["warn-1"])
        self.assertEqual(batch["service_run_row"]["layer_resolution_counts_json"], {"layer1": 1})
        self.assertEqual(batch["service_run_row"]["field_resolution_counts_json"], {"category_primary": 1})

        self.assertEqual(len(batch["run_target_rows"]), 1)
        self.assertEqual(batch["run_target_rows"][0]["target_stats_json"], {"posts_emitted": 2})
        self.assertEqual(batch["run_target_rows"][0]["checkpoint_message_id"], 2)

        self.assertEqual(len(batch["provider_rows"]), 1)
        provider_row = batch["provider_rows"][0]
        self.assertEqual(provider_row["phones"], ["+381600000004"])
        self.assertEqual(provider_row["telegram_handles"], ["example_sample_provider"])
        self.assertEqual(provider_row["provider_quality_flags_json"], ["has_contact"])

        self.assertEqual(len(batch["offer_rows"]), 1)
        offer_row = batch["offer_rows"][0]
        self.assertEqual(offer_row["offer_key"], "offer-1")
        self.assertEqual(offer_row["title_best"], "Offer One Updated")
        self.assertEqual(offer_row["serbia_relevance_verdict"], "serbia_relevant")
        self.assertEqual(offer_row["service_tags"], ["cleaning", "repair"])
        self.assertEqual(offer_row["offer_quality_flags_json"], ["has_price", "has_contact"])


if __name__ == "__main__":
    unittest.main()
