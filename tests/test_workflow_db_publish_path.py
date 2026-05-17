from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "n8n" / "workflows" / "tg_services_serbia_greenfield_base.json"


def _load_workflow() -> dict:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise AssertionError(f"Workflow node not found: {name}")


def _run_node(node_name: str, *, input_payload: dict | None = None, upstream_payloads: dict[str, dict] | None = None) -> dict:
    workflow = _load_workflow()
    js_code = _node_by_name(workflow, node_name)["parameters"]["jsCode"]
    harness = f"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const input = payload.input ?? {{}};
const upstream = payload.upstream ?? {{}};
const $input = {{
  first: () => ({{ json: input }}),
}};
const $ = (name) => {{
  const payload = upstream[name] ?? {{}};
  return {{
    first: () => ({{ json: payload }}),
  }};
}};
const fn = new Function('$', '$input', {json.dumps(js_code)});
const result = fn($, $input);
process.stdout.write(JSON.stringify(result));
"""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as handle:
        handle.write(harness)
        harness_path = Path(handle.name)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(
            {
                "input": input_payload or {},
                "upstream": upstream_payloads or {},
            },
            handle,
            ensure_ascii=False,
        )
        payload_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                "node",
                str(harness_path),
                str(payload_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    finally:
        harness_path.unlink(missing_ok=True)
        payload_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise AssertionError(
            f"node harness failed for {node_name}\n"
            f"returncode={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    payload = json.loads(completed.stdout)
    return payload[0]["json"]


def _run_async_node(
    node_name: str,
    *,
    input_payload: dict | None = None,
    upstream_payloads: dict[str, dict] | None = None,
    binary_text: str = "",
) -> dict:
    workflow = _load_workflow()
    js_code = _node_by_name(workflow, node_name)["parameters"]["jsCode"]
    harness = f"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const input = payload.input ?? {{}};
const upstream = payload.upstream ?? {{}};
const binaryText = payload.binaryText ?? '';
const $input = {{
  first: () => ({{
    json: input,
  }}),
}};
const $ = (name) => {{
  const payload = upstream[name] ?? {{}};
  return {{
    first: () => ({{ json: payload }}),
  }};
}};
const helpers = {{
  getBinaryDataBuffer: async () => Buffer.from(binaryText, 'utf8'),
}};
const AsyncFunction = Object.getPrototypeOf(async function () {{}}).constructor;
const fn = new AsyncFunction('$', '$input', 'helpers', {json.dumps(js_code)});
fn($, $input, helpers)
  .then((result) => process.stdout.write(JSON.stringify(result)))
  .catch((error) => {{
    process.stderr.write(String(error?.stack ?? error));
    process.exit(1);
  }});
"""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as handle:
        handle.write(harness)
        harness_path = Path(handle.name)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(
            {
                "input": input_payload or {},
                "upstream": upstream_payloads or {},
                "binaryText": binary_text,
            },
            handle,
            ensure_ascii=False,
        )
        payload_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                "node",
                str(harness_path),
                str(payload_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    finally:
        harness_path.unlink(missing_ok=True)
        payload_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise AssertionError(
            f"async node harness failed for {node_name}\n"
            f"returncode={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    payload = json.loads(completed.stdout)
    return payload[0]["json"]


def _build_projection_payload(*, db_requested: bool) -> dict:
    return {
        "normalized_request": {
            "publication_targets": {"sheets": True, "db": db_requested, "dashboard": False},
            "google_sheet_id": "sheet-123",
            "llm_enabled": False,
            "requested_targets": ["@example_source_alpha"],
        },
        "run_id": "run-db-publish-workflow",
        "service_run_candidate": {
            "run_id": "run-db-publish-workflow",
            "started_at_utc": "2026-04-22T18:12:52.083Z",
            "warnings_json": "[]",
            "run_status": "success",
            "requested_targets_count": 1,
            "requested_targets_json": "[\"@example_source_alpha\"]",
            "successful_target_count": 1,
            "successful_targets_json": "[{\"target_key\":\"example_source_alpha\"}]",
            "failed_target_count": 0,
            "failed_targets_json": "[]",
            "fetch_messages_seen_total": 2,
            "sync_mode": "sheet_first_incremental",
            "cutoff_policy_type": "months_back",
            "cutoff_policy_value": "1",
            "max_messages": 15,
            "llm_enabled": False,
        },
        "canonical_output": {
            "providers": [
                {
                    "provider_key": "provider-db-1",
                    "provider_state": "candidate",
                    "identity_strength": "strong",
                    "display_name_best": "Provider DB One",
                    "phones": ["+381600000004"],
                    "telegram_handles": ["example_provider_db_one"],
                    "telegram_links": ["https://t.me/example_provider_db_one"],
                    "city_codes": ["belgrade"],
                    "service_category_hints": ["cleaning"],
                    "first_seen_at_utc": "2026-04-22T18:12:52.083Z",
                    "last_seen_at_utc": "2026-04-22T18:13:22.083Z",
                    "first_seen_run_id": "run-db-publish-workflow",
                    "last_seen_run_id": "run-db-publish-workflow",
                    "evidence_raw_post_ids": ["tg:1922228422:5001"],
                    "latest_post_url": "https://t.me/example_source_alpha/1",
                    "times_seen": 1,
                    "offer_count": 1,
                    "dedupe_confidence": "high",
                    "source_channel_keys": ["example_source_alpha"],
                }
            ],
            "offers": [
                {
                    "offer_key": "offer-db-1",
                    "provider_key": "provider-db-1",
                    "offer_state": "candidate",
                    "service_signature_key": "svc-db-1",
                    "category_primary": "cleaning",
                    "title_best": "Apartment Cleaning",
                    "description_best": "Cleaning in Belgrade",
                    "price_text_best": "30 EUR",
                    "price_min": 30,
                    "price_max": 30,
                    "currency_code": "EUR",
                    "city_codes": ["belgrade"],
                    "service_tags": ["cleaning"],
                    "contact_snapshot_phones": ["+381600000004"],
                    "contact_snapshot_telegram_handles": ["example_provider_db_one"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_provider_db_one"],
                    "first_seen_at_utc": "2026-04-22T18:12:52.083Z",
                    "last_seen_at_utc": "2026-04-22T18:13:22.083Z",
                    "first_seen_run_id": "run-db-publish-workflow",
                    "last_seen_run_id": "run-db-publish-workflow",
                    "evidence_raw_post_ids": ["tg:1922228422:5001"],
                    "latest_post_url": "https://t.me/example_source_alpha/1",
                    "times_seen": 1,
                    "dedupe_confidence": "high",
                    "source_channel_keys": ["example_source_alpha"],
                }
            ],
        },
        "merge_output": {
            "provider_raw_post_evidence": [
                {
                    "provider_key": "provider-db-1",
                    "raw_post_id": "tg:1922228422:5001",
                    "first_seen_run_id": "run-db-publish-workflow",
                    "last_seen_run_id": "run-db-publish-workflow",
                }
            ],
            "offer_raw_post_evidence": [
                {
                    "offer_key": "offer-db-1",
                    "raw_post_id": "tg:1922228422:5001",
                    "first_seen_run_id": "run-db-publish-workflow",
                    "last_seen_run_id": "run-db-publish-workflow",
                }
            ],
        },
        "audit_enrichment_rows": [
            {
                "audit_row_id": "audit:run-db-publish-workflow:llm_service_relevance:1",
                "run_id": "run-db-publish-workflow",
                "entity_type": "offer",
                "entity_id": "offer-db-1",
                "stage": "llm_service_relevance",
                "processor_type": "llm",
                "processor_version": "extr_llm_05_v1",
                "status": "accepted",
                "decision_code": "service_accept",
                "created_at_utc": "2026-04-22T18:13:10.000Z",
                "input_fingerprint": "wf-db-publish-proof",
                "output_patch_json": {"offer_state": "candidate"},
                "reason_text": "Workflow DB proof row",
                "source_raw_post_ids": ["tg:1922228422:5001"],
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
            }
        ],
        "run_target_candidates": [],
        "raw_posts": [
            {
                "raw_post_id": "tg:1922228422:5001",
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
                "_run_id": "run-db-publish-workflow",
                "_target_key": "example_source_alpha",
                "_telegram_target_input": "@example_source_alpha",
                "_telegram_target_resolved": "https://t.me/example_source_alpha",
            }
        ],
        "raw_posts_total": 1,
        "extraction_ok": True,
        "merge_ok": True,
    }


class WorkflowDbPublishPathTests(unittest.TestCase):
    def test_build_projection_rows_marks_db_publication_pending(self) -> None:
        projected = _run_node(
            "WF-SHEETS-04 Build Projection Rows (v1)",
            input_payload=_build_projection_payload(db_requested=True),
        )

        self.assertEqual(projected["db_contract_status"], "wf_db_publish_28_v1_pending")
        self.assertEqual(projected["db_publication"]["status"], "pending")
        self.assertEqual(projected["db_publication"]["raw_posts_upserted"], 0)
        self.assertTrue(projected["publication_summary"]["db_requested"])
        self.assertEqual(projected["publication_summary"]["db_status"], "pending")
        self.assertEqual(projected["run_logging"]["sink_status"], "db_publication_pending")
        self.assertEqual(projected["run_logging"]["sink_type"], "postgresql")

    def test_prepare_publish_node_builds_repo_owned_helper_command(self) -> None:
        projected = _run_node(
            "WF-SHEETS-04 Build Projection Rows (v1)",
            input_payload=_build_projection_payload(db_requested=True),
        )
        finalized = _run_node(
            "WF-SHEETS-04 Finalize Publication Output (v1)",
            upstream_payloads={"WF-SHEETS-04 Build Projection Rows (v1)": projected},
        )
        prepared = _run_node(
            "WF-DB-05 Prepare Publish Business Rows (v1)",
            input_payload=finalized,
        )

        self.assertTrue(prepared["db_invoke_helper"])
        self.assertEqual(
            prepared["db_helper_path"],
            "__TGSA_REPO_ROOT__/scripts/db/publish_business_rows.py",
        )
        self.assertIn("execute_helper_wrapper.py", prepared["db_execute_command"])
        self.assertIn("--launch-spec-b64url", prepared["db_execute_command"])
        payload = json.loads(prepared["db_payload_json"])
        self.assertEqual(payload["run_id"], "run-db-publish-workflow")
        self.assertIn("service_run_sheet_row_final", payload)
        self.assertEqual(payload["raw_posts_total"], 1)
        self.assertEqual(payload["raw_posts"][0]["raw_post_id"], "tg:1922228422:5001")
        self.assertEqual(payload["audit_enrichment_rows"][0]["audit_row_id"], "audit:run-db-publish-workflow:llm_service_relevance:1")
        self.assertEqual(payload["merge_output"]["provider_raw_post_evidence"][0]["provider_key"], "provider-db-1")
        self.assertEqual(payload["merge_output"]["offer_raw_post_evidence"][0]["offer_key"], "offer-db-1")

    def test_prepare_publish_node_blocks_db_on_incomplete_product_row_continuation(self) -> None:
        payload = _build_projection_payload(db_requested=True)
        payload["normalized_request"]["llm_enabled"] = True
        payload["normalized_request"]["publication_targets"]["dashboard"] = True
        payload["llm_contract_status"] = "extr_llm_05_v1_error"
        payload["llm_stage"] = {
            "status": "error",
            "reason": "llm_product_row_continuation_required",
            "product_row_coverage": {
                "candidate_total": 5,
                "attempts": 2,
                "successful_decisions": 2,
                "failures": 0,
                "skips": 0,
                "max_output_retries": 0,
                "hard_drops": 0,
                "coverage_complete": False,
                "fallback_publication_blocked": True,
                "incomplete_reason": "llm_product_row_continuation_required",
            },
            "product_row_chunking": {
                "enabled": True,
                "status": "continuation_required",
                "candidate_total": 5,
                "chunk_size": 2,
                "processed_candidate_count": 2,
                "remaining_candidate_count": 3,
                "next_cursor": 2,
                "continuation_token": "test-continuation-token",
                "continuation_state_path": "__TGSA_N8N_FILES_DIR__/test-product-row-state.json",
            },
        }

        projected = _run_node("WF-SHEETS-04 Build Projection Rows (v1)", input_payload=payload)

        self.assertFalse(projected["sheets_publication_allowed"])
        self.assertTrue(projected["product_row_publication_blocked"])
        self.assertEqual(projected["publication_summary"]["status"], "blocked_incomplete_product_row_coverage")
        self.assertEqual(projected["db_contract_status"], "wf_db_publish_28_v1_blocked_incomplete_product_row_coverage")
        self.assertEqual(projected["db_publication"]["status"], "blocked")

        finalized = _run_node(
            "WF-SHEETS-04 Finalize Publication Output (v1)",
            upstream_payloads={"WF-SHEETS-04 Build Projection Rows (v1)": projected},
        )
        prepared = _run_node(
            "WF-DB-05 Prepare Publish Business Rows (v1)",
            input_payload=finalized,
        )

        self.assertFalse(prepared["db_invoke_helper"])
        self.assertEqual(prepared["db_contract_status"], "wf_db_publish_28_v1_blocked_incomplete_product_row_coverage")
        self.assertEqual(prepared["db_publication"]["status"], "blocked")
        self.assertNotIn("db_publication payload prepared", prepared["next_step_note_wf_db_05"].lower())

    def test_bypass_node_marks_db_not_requested(self) -> None:
        projected = _run_node(
            "WF-SHEETS-04 Build Projection Rows (v1)",
            input_payload=_build_projection_payload(db_requested=False),
        )
        finalized = _run_node(
            "WF-SHEETS-04 Finalize Publication Output (v1)",
            upstream_payloads={"WF-SHEETS-04 Build Projection Rows (v1)": projected},
        )
        prepared = _run_node(
            "WF-DB-05 Prepare Publish Business Rows (v1)",
            input_payload=finalized,
        )
        bypassed = _run_node(
            "WF-DB-05 Bypass Not Requested (v1)",
            upstream_payloads={"WF-DB-05 Prepare Publish Business Rows (v1)": prepared},
        )

        self.assertEqual(bypassed["db_contract_status"], "wf_db_publish_28_v1_not_requested")
        self.assertEqual(bypassed["db_publication"]["status"], "not_requested")
        self.assertEqual(bypassed["db_publication"]["raw_posts_upserted"], 0)
        self.assertEqual(bypassed["publication_summary"]["db_status"], "not_requested")
        self.assertEqual(bypassed["run_logging"]["sink_status"], "db_not_requested")
        self.assertEqual(bypassed["run_logging"]["sink_type"], "none")

    def test_parse_publish_result_maps_successful_helper_output(self) -> None:
        projected = _run_node(
            "WF-SHEETS-04 Build Projection Rows (v1)",
            input_payload=_build_projection_payload(db_requested=True),
        )
        finalized = _run_node(
            "WF-SHEETS-04 Finalize Publication Output (v1)",
            upstream_payloads={"WF-SHEETS-04 Build Projection Rows (v1)": projected},
        )
        prepared = _run_node(
            "WF-DB-05 Prepare Publish Business Rows (v1)",
            input_payload=finalized,
        )
        wrapper = {
            "helper_path": prepared["db_helper_path"],
            "input_path": prepared["db_transport_path"],
            "payload_bytes": prepared["db_payload_bytes"],
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "invocation_error": None,
        }
        helper_output = {
            "run_id": prepared["run_id"],
            "db_publication": {
                "status": "success",
                "dsn_env": "TG_SERVICES_DB_DSN",
                "db_name": "tg_services_aggregator",
                "host": "::1/128",
                "port": 5432,
                "service_runs_upserted": 1,
                "run_targets_upserted": 0,
                "raw_posts_upserted": 1,
                "providers_upserted": 1,
                "offers_upserted": 1,
                "provider_raw_post_evidence_upserted": 1,
                "offer_raw_post_evidence_upserted": 1,
                "audit_enrichment_rows_appended": 1,
                "audit_source_raw_posts_appended": 1,
            },
            "service_run_candidate": {
                "offers_upserted_total": 1,
                "sink_status": "db_published_business_rows",
                "sink_reason": "",
            },
        }

        parsed = _run_async_node(
            "WF-DB-05 Parse Publish Result (v1)",
            input_payload={},
            upstream_payloads={
                "WF-DB-05 Prepare Publish Business Rows (v1)": prepared,
                "WF-DB-05 Execute Publish (v1)": {"stdout": json.dumps(wrapper)},
            },
            binary_text=json.dumps(helper_output),
        )

        self.assertEqual(parsed["db_contract_status"], "wf_db_publish_28_v1_success")
        self.assertEqual(parsed["db_publication"]["status"], "success")
        self.assertEqual(parsed["publication_summary"]["db_status"], "success")
        self.assertEqual(parsed["publication_summary"]["db_raw_posts_upserted"], 1)
        self.assertEqual(parsed["publication_summary"]["db_provider_raw_post_evidence_upserted"], 1)
        self.assertEqual(parsed["publication_summary"]["db_offer_raw_post_evidence_upserted"], 1)
        self.assertEqual(parsed["publication_summary"]["db_audit_enrichment_rows_appended"], 1)
        self.assertEqual(parsed["publication_summary"]["db_audit_source_raw_posts_appended"], 1)
        self.assertEqual(parsed["run_logging"]["sink_status"], "db_published_business_rows")
        self.assertEqual(parsed["run_logging"]["sink_type"], "postgresql")

    def test_db_branch_connections_replace_direct_response_jump(self) -> None:
        workflow = _load_workflow()
        finalize_connection = workflow["connections"]["WF-SHEETS-04 Finalize Publication Output (v1)"]["main"][0][0]
        parse_connection = workflow["connections"]["WF-DB-05 Parse Publish Result (v1)"]["main"][0][0]
        bypass_connection = workflow["connections"]["WF-DB-05 Bypass Not Requested (v1)"]["main"][0][0]
        execute_node = _node_by_name(workflow, "WF-DB-05 Execute Publish (v1)")

        self.assertEqual(finalize_connection["node"], "WF-DB-05 Prepare Publish Business Rows (v1)")
        self.assertEqual(parse_connection["node"], "WF-RESP-01 Webhook Or Manual Output?")
        self.assertEqual(bypass_connection["node"], "WF-RESP-01 Webhook Or Manual Output?")
        self.assertEqual(execute_node["parameters"]["command"], "={{ $json.db_execute_command }}")


if __name__ == "__main__":
    unittest.main()
