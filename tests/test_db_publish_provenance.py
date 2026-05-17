from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from scripts.db.publish_business_rows import build_publication_batch, publish_business_rows


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "db" / "migrations"


def _build_payload(*, run_id: str = "run-db-provenance-1") -> dict:
    raw_post_id = "tg:1922228422:5001"
    provider_key = "provider-db-prov-1"
    offer_key = "offer-db-prov-1"
    audit_row_id = f"audit:{run_id}:llm_service_relevance:1"
    return {
        "run_id": run_id,
        "started_at_utc": "2026-04-22T18:12:52.083Z",
        "normalized_request": {
            "google_sheet_id": "sheet-123",
            "llm_enabled": True,
            "cutoff_field": "months_back",
            "months_back": 1,
            "output_timezone": "Europe/Belgrade",
        },
        "service_run_candidate": {
            "run_id": run_id,
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
            "raw_posts_total": 1,
            "providers_total": 1,
            "offers_total": 1,
            "offers_upserted_total": 0,
            "fetch_messages_seen_total": 1,
            "structured_posts_total": 1,
            "llm_calls_total": 1,
            "llm_tokens_input_total": 210,
            "llm_tokens_output_total": 44,
            "llm_cost_estimate_usd": "0.0019",
            "llm_review_required_count": 0,
            "warnings_json": "[]",
            "error_type": "",
            "error_message": "",
        },
        "service_run_sheet_row_final": {
            "run_id": run_id,
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
            "raw_posts_total": 1,
            "providers_total": 1,
            "offers_total": 1,
            "offers_upserted_total": 0,
            "fetch_messages_seen_total": 1,
            "structured_posts_total": 1,
            "llm_calls_total": 1,
            "llm_tokens_input_total": 210,
            "llm_tokens_output_total": 44,
            "llm_cost_estimate_usd": "0.0019",
            "llm_review_required_count": 0,
            "error_type": "",
            "error_message": "",
            "google_sheet_id": "sheet-123",
            "providers_sheet_name": "providers",
            "offers_sheet_name": "offers",
            "requested_targets_json": "[\"@example_source_alpha\"]",
            "successful_targets_json": "[{\"target_key\":\"example_source_alpha\"}]",
            "failed_targets_json": "[]",
            "warnings_json": "[]",
            "checkpoint_targets_json": "[{\"target_key\":\"example_source_alpha\",\"checkpoint_message_id\":\"5001\"}]",
            "response_json": "{\"publication_summary\":{\"status\":\"success\"}}",
        },
        "run_targets_sheet_rows": [
            {
                "run_id": run_id,
                "target_key": "example_source_alpha",
                "target_input": "@example_source_alpha",
                "target_resolved": "https://t.me/example_source_alpha",
                "target_status": "success",
                "started_at_utc": "2026-04-22T18:12:52.083Z",
                "finished_at_utc": "2026-04-22T18:13:22.083Z",
                "checkpoint_message_id": "5001",
                "raw_posts_emitted": 1,
                "error_type": "",
                "error_message": "",
                "target_stats_json": "{\"posts_emitted\":1}",
            }
        ],
        "raw_posts_total": 1,
        "raw_posts": [
            {
                "raw_post_id": raw_post_id,
                "source_platform": "telegram",
                "chat_id": "1922228422",
                "chat_title": "Serbia Specialist",
                "chat_kind": "supergroup",
                "chat_username": "example_source_alpha",
                "message_id": 5001,
                "post_url": "https://t.me/example_source_alpha/5001",
                "posted_at_utc": "2026-04-22T18:12:40.000Z",
                "posted_year_month": "2026-04",
                "posted_iso_week": "2026-W17",
                "text_raw": "Apartment cleaning in Belgrade. Telegram @example_provider_db_one",
                "text_normalized": "Apartment cleaning in Belgrade. Telegram @example_provider_db_one",
                "text_length": 57,
                "has_media": False,
                "media_type": "",
                "views": 120,
                "forwards": 2,
                "replies": 0,
                "grouped_id": None,
                "sender_id": "6001",
                "sender_kind": "user",
                "sender_title": "Provider DB One",
                "sender_username": "example_provider_db_one",
                "sender_profile_url": "https://t.me/example_provider_db_one",
                "post_author": "Provider DB One",
                "_run_id": run_id,
                "_target_key": "example_source_alpha",
                "_telegram_target_input": "@example_source_alpha",
                "_telegram_target_resolved": "https://t.me/example_source_alpha",
            }
        ],
        "canonical_output": {
            "providers": [
                {
                    "provider_key": provider_key,
                    "provider_state": "candidate",
                    "identity_strength": "strong",
                    "display_name_best": "Provider DB One",
                    "canonical_name": "Provider DB One",
                    "provider_summary": "Belgrade apartment cleaning",
                    "primary_contact_type": "telegram_handle",
                    "primary_contact_value": "example_provider_db_one",
                    "phones": ["+381600000004"],
                    "telegram_handles": ["example_provider_db_one"],
                    "telegram_links": ["https://t.me/example_provider_db_one"],
                    "emails": ["hello@example.com"],
                    "city_codes": ["belgrade"],
                    "service_category_hints": ["cleaning"],
                    "first_seen_at_utc": "2026-04-22T18:12:40.000Z",
                    "last_seen_at_utc": "2026-04-22T18:12:40.000Z",
                    "first_seen_run_id": run_id,
                    "last_seen_run_id": run_id,
                    "evidence_raw_post_ids": [raw_post_id],
                    "latest_post_url": "https://t.me/example_source_alpha/5001",
                    "times_seen": 1,
                    "offer_count": 1,
                    "dedupe_confidence": "high",
                    "source_channel_keys": ["example_source_alpha"],
                    "provider_quality_flags": ["has_contact"],
                }
            ],
            "offers": [
                {
                    "offer_key": offer_key,
                    "provider_key": provider_key,
                    "offer_state": "candidate",
                    "service_signature_key": "svc-db-prov-1",
                    "category_primary": "cleaning",
                    "category_secondary": "apartment_cleaning",
                    "title_best": "Apartment Cleaning",
                    "description_best": "Cleaning in Belgrade",
                    "offer_summary": "Apartment cleaning in Belgrade",
                    "price_text_best": "30 EUR",
                    "price_min": 30,
                    "price_max": 30,
                    "currency_code": "EUR",
                    "city_codes": ["belgrade"],
                    "service_tags": ["cleaning"],
                    "contact_snapshot_phones": ["+381600000004"],
                    "contact_snapshot_telegram_handles": ["example_provider_db_one"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_provider_db_one"],
                    "first_seen_at_utc": "2026-04-22T18:12:40.000Z",
                    "last_seen_at_utc": "2026-04-22T18:12:40.000Z",
                    "first_seen_run_id": run_id,
                    "last_seen_run_id": run_id,
                    "evidence_raw_post_ids": [raw_post_id],
                    "latest_post_url": "https://t.me/example_source_alpha/5001",
                    "times_seen": 1,
                    "dedupe_confidence": "high",
                    "serbia_relevance_verdict": "serbia_relevant",
                    "source_channel_keys": ["example_source_alpha"],
                    "offer_quality_flags": ["has_price"],
                }
            ],
        },
        "merge_output": {
            "provider_raw_post_evidence": [
                {
                    "provider_key": provider_key,
                    "raw_post_id": raw_post_id,
                    "first_seen_run_id": run_id,
                    "last_seen_run_id": run_id,
                }
            ],
            "offer_raw_post_evidence": [
                {
                    "offer_key": offer_key,
                    "raw_post_id": raw_post_id,
                    "first_seen_run_id": run_id,
                    "last_seen_run_id": run_id,
                }
            ],
            "merge_summary": {
                "provider_raw_post_evidence_total": 1,
                "offer_raw_post_evidence_total": 1,
                "layer_resolution_counts": {"category_primary": 1},
                "field_resolution_counts": {"category_primary": 1},
            },
        },
        "audit_enrichment_rows": [
            {
                "audit_row_id": audit_row_id,
                "run_id": run_id,
                "entity_type": "offer",
                "entity_id": offer_key,
                "stage": "llm_service_relevance",
                "processor_type": "llm",
                "processor_version": "extr_llm_05_v1",
                "status": "accepted",
                "decision_code": "service_accept",
                "created_at_utc": "2026-04-22T18:13:10.000Z",
                "input_fingerprint": "wf-db-provenance-proof",
                "output_patch_json": {"offer_state": "candidate"},
                "reason_text": "Bounded provenance proof row",
                "source_raw_post_ids": [raw_post_id],
                "attempt_number": 1,
                "review_required": False,
                "model_name": "gpt-5-mini-2025-08-07",
                "prompt_version": "post_merge_llm_v1_service_relevance",
                "confidence": 0.91,
                "latency_ms": 320,
                "tokens_input": 210,
                "tokens_output": 44,
                "cost_estimate_usd": "0.0019",
                "response_excerpt": "accepted",
                "upstream_audit_row_id": "",
                "superseded_by_audit_row_id": "",
            }
        ],
        "sheets_config": {
            "providers_sheet_name": "providers",
            "offers_sheet_name": "offers",
        },
    }


def _schema_dsn(base_dsn: str, schema_name: str) -> str:
    return make_conninfo(base_dsn, options=f"-c search_path={schema_name},public")


def _apply_migrations(base_dsn: str, schema_name: str) -> None:
    migration_paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_paths:
        raise AssertionError("DB migrations were not found for provenance proof.")

    with psycopg.connect(base_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name)))
            for migration_path in migration_paths:
                cursor.execute(migration_path.read_text(encoding="utf-8"))


def _drop_schema(base_dsn: str, schema_name: str) -> None:
    with psycopg.connect(base_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))


class DbPublishProvenanceBatchTests(unittest.TestCase):
    def test_build_publication_batch_materializes_provenance_rows(self) -> None:
        batch = build_publication_batch(_build_payload())

        self.assertEqual(batch["run_id"], "run-db-provenance-1")
        self.assertEqual(len(batch["raw_post_rows"]), 1)
        self.assertEqual(batch["raw_post_rows"][0]["raw_post_id"], "tg:1922228422:5001")
        self.assertEqual(batch["raw_post_rows"][0]["first_seen_target_input"], "@example_source_alpha")
        self.assertEqual(batch["raw_post_rows"][0]["last_seen_target_resolved"], "https://t.me/example_source_alpha")
        self.assertTrue(batch["raw_post_rows"][0]["text_hash_normalized"])

        self.assertEqual(len(batch["provider_raw_post_evidence_rows"]), 1)
        self.assertEqual(batch["provider_raw_post_evidence_rows"][0]["provider_key"], "provider-db-prov-1")
        self.assertEqual(batch["provider_raw_post_evidence_rows"][0]["raw_post_id"], "tg:1922228422:5001")

        self.assertEqual(len(batch["offer_raw_post_evidence_rows"]), 1)
        self.assertEqual(batch["offer_raw_post_evidence_rows"][0]["offer_key"], "offer-db-prov-1")
        self.assertEqual(batch["offer_raw_post_evidence_rows"][0]["raw_post_id"], "tg:1922228422:5001")

        self.assertEqual(len(batch["audit_enrichment_rows"]), 1)
        audit_row = batch["audit_enrichment_rows"][0]
        self.assertEqual(audit_row["audit_row_id"], "audit:run-db-provenance-1:llm_service_relevance:1")
        self.assertEqual(audit_row["entity_id"], "offer-db-prov-1")
        self.assertEqual(audit_row["output_patch_json"], {"offer_state": "candidate"})

        self.assertEqual(len(batch["audit_source_raw_post_rows"]), 1)
        self.assertEqual(
            batch["audit_source_raw_post_rows"][0],
            {
                "audit_row_id": "audit:run-db-provenance-1:llm_service_relevance:1",
                "raw_post_id": "tg:1922228422:5001",
            },
        )


@unittest.skipUnless(os.environ.get("TG_SERVICES_DB_DSN"), "TG_SERVICES_DB_DSN is not set")
class DbPublishProvenanceIntegrationTests(unittest.TestCase):
    def test_publish_business_rows_writes_provenance_surfaces_to_postgres(self) -> None:
        base_dsn = os.environ["TG_SERVICES_DB_DSN"]
        schema_name = f"tz_wf_db_provenance_28_{uuid.uuid4().hex[:10]}"
        schema_dsn = _schema_dsn(base_dsn, schema_name)
        run_id = f"run-db-provenance-{uuid.uuid4().hex[:8]}"
        payload = _build_payload(run_id=run_id)

        try:
            _apply_migrations(base_dsn, schema_name)
            result = publish_business_rows(payload, dsn=schema_dsn)

            self.assertEqual(result["run_id"], run_id)
            self.assertEqual(result["db_publication"]["status"], "success")
            self.assertEqual(result["db_publication"]["raw_posts_upserted"], 1)
            self.assertEqual(result["db_publication"]["audit_enrichment_rows_appended"], 1)
            self.assertEqual(result["db_publication"]["provider_raw_post_evidence_upserted"], 1)
            self.assertEqual(result["db_publication"]["offer_raw_post_evidence_upserted"], 1)
            self.assertEqual(result["db_publication"]["audit_source_raw_posts_appended"], 1)

            with psycopg.connect(schema_dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM raw_posts WHERE last_seen_run_id = %s", (run_id,))
                    self.assertEqual(cursor.fetchone()[0], 1)

                    cursor.execute("SELECT COUNT(*) FROM audit_enrichment_rows WHERE run_id = %s", (run_id,))
                    self.assertEqual(cursor.fetchone()[0], 1)

                    cursor.execute(
                        "SELECT COUNT(*) FROM provider_raw_post_evidence WHERE last_seen_run_id = %s",
                        (run_id,),
                    )
                    self.assertEqual(cursor.fetchone()[0], 1)

                    cursor.execute(
                        "SELECT COUNT(*) FROM offer_raw_post_evidence WHERE last_seen_run_id = %s",
                        (run_id,),
                    )
                    self.assertEqual(cursor.fetchone()[0], 1)

                    cursor.execute(
                        """
                        SELECT
                            pre.provider_key,
                            ore.offer_key,
                            asrp.audit_row_id,
                            asrp.raw_post_id
                        FROM audit_source_raw_posts AS asrp
                        JOIN audit_enrichment_rows AS aer ON aer.audit_row_id = asrp.audit_row_id
                        JOIN provider_raw_post_evidence AS pre ON pre.raw_post_id = asrp.raw_post_id
                        JOIN offer_raw_post_evidence AS ore ON ore.raw_post_id = asrp.raw_post_id
                        WHERE aer.run_id = %s
                        """,
                        (run_id,),
                    )
                    self.assertEqual(
                        cursor.fetchone(),
                        (
                            "provider-db-prov-1",
                            "offer-db-prov-1",
                            f"audit:{run_id}:llm_service_relevance:1",
                            "tg:1922228422:5001",
                        ),
                    )

                    cursor.execute(
                        """
                        SELECT response_json -> 'db_publication' ->> 'raw_posts_upserted'
                        FROM service_runs
                        WHERE run_id = %s
                        """,
                        (run_id,),
                    )
                    self.assertEqual(cursor.fetchone()[0], "1")
        finally:
            _drop_schema(base_dsn, schema_name)


if __name__ == "__main__":
    unittest.main()
