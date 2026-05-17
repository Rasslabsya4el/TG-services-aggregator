from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "n8n" / "workflows" / "tg_services_serbia_greenfield_base.json"
VISIBLE_HEADERS = [
    "Услуга",
    "Детали",
    "Категория",
    "Цена",
    "Город",
    "Telegram",
    "Instagram",
    "WhatsApp",
    "Телефон",
    "Источник",
    "Актуально на",
]
LLM_PRODUCT_ROW_COVERAGE_COMPLETE = {
    "candidate_total": 1,
    "attempts": 1,
    "successful_decisions": 1,
    "failures": 0,
    "skips": 0,
    "max_output_retries": 0,
    "hard_drops": 0,
    "coverage_complete": True,
}


def _load_workflow() -> dict:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise AssertionError(f"Workflow node not found: {name}")


def _run_code_node(node_name: str, input_payload: dict) -> dict:
    workflow = _load_workflow()
    js_code = _node_by_name(workflow, node_name)["parameters"]["jsCode"]
    harness = f"""
const input = JSON.parse(process.argv[2]);
const $input = {{
  first: () => ({{ json: input }}),
}};
const fn = new Function('$input', {json.dumps(js_code)});
const result = fn($input);
process.stdout.write(JSON.stringify(result));
"""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as handle:
        handle.write(harness)
        harness_path = Path(handle.name)
    try:
        completed = subprocess.run(
            ["node", str(harness_path), json.dumps(input_payload, ensure_ascii=False)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    finally:
        harness_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise AssertionError(
            f"node harness failed for {node_name}\n"
            f"returncode={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    payload = json.loads(completed.stdout)
    return payload[0]["json"]


def _run_build_projection_rows(input_payload: dict) -> dict:
    return _run_code_node("WF-SHEETS-04 Build Projection Rows (v1)", input_payload)


def _run_parse_llm_helper_result(
    *,
    base_payload: dict,
    execute_payload: dict,
    read_payload: dict,
    result_text: str = "",
) -> dict:
    workflow = _load_workflow()
    js_code = _node_by_name(workflow, "WF-LLM-05 Parse Helper Result (v1)")["parameters"]["jsCode"]
    harness = f"""
const base = JSON.parse(process.argv[2]);
const executePayload = JSON.parse(process.argv[3]);
const readPayload = JSON.parse(process.argv[4]);
const resultText = process.argv[5] ?? '';
const nodes = {{
  'WF-LLM-05 Prepare Post-Merge Review (v1)': [{{ json: base }}],
  'WF-LLM-05 Execute Helper (v1)': [{{ json: executePayload }}],
}};
const $ = (name) => ({{
  first: () => nodes[name]?.[0] ?? null,
  all: () => nodes[name] ?? [],
}});
const $input = {{
  first: () => ({{ json: readPayload }}),
}};
const helpers = {{
  getBinaryDataBuffer: async () => Buffer.from(resultText, 'utf8'),
}};
const jsCode = {json.dumps(js_code)};
const fn = new Function('$input', '$', 'helpers', `return (async () => {{
${{jsCode}}
}})();`);
fn($input, $, helpers)
  .then((result) => process.stdout.write(JSON.stringify(result)))
  .catch((error) => {{
    console.error(error && error.stack ? error.stack : String(error));
    process.exit(1);
  }});
"""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as handle:
        handle.write(harness)
        harness_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                "node",
                str(harness_path),
                json.dumps(base_payload, ensure_ascii=False),
                json.dumps(execute_payload, ensure_ascii=False),
                json.dumps(read_payload, ensure_ascii=False),
                result_text,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    finally:
        harness_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise AssertionError(
            "node harness failed for WF-LLM-05 Parse Helper Result (v1)\n"
            f"returncode={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    payload = json.loads(completed.stdout)
    return payload[0]["json"]


class VisibleServicesProjectionWorkflowTests(unittest.TestCase):
    def test_llm_prepare_launch_spec_carries_total_and_wrapper_timeouts(self) -> None:
        workflow = _load_workflow()
        prepare_node = _node_by_name(workflow, "WF-LLM-05 Prepare Post-Merge Review (v1)")
        js_code = prepare_node["parameters"]["jsCode"]

        self.assertIn("--total-timeout-seconds", js_code)
        self.assertIn("llmTotalTimeoutSeconds", js_code)
        self.assertIn("llmWrapperTimeoutSeconds", js_code)
        self.assertIn("timeout_artifact: 'post_merge_llm'", js_code)
        self.assertIn("output_path: resultPath", js_code)

    def test_llm_parse_reads_structured_timeout_artifact_after_wrapper_nonzero(self) -> None:
        artifact = {
            "canonical_output": {
                "run_id": "parse-timeout",
                "providers_total": 0,
                "offers_total": 0,
                "providers": [],
                "offers": [],
                "merge_summary": {},
            },
            "audit_enrichment_rows": [],
            "llm_stage": {
                "status": "error",
                "reason": "llm_total_timeout",
                "processor_version": "extr_llm_05_v1",
                "helper_mode": "responses_api",
                "calls_attempted": 7,
                "calls_skipped": 0,
                "accepted_patches_total": 3,
                "audit_only_patches_total": 1,
                "review_required_count": 1,
                "tokens_input_total": 1000,
                "tokens_output_total": 250,
                "cost_estimate_usd": 0.001,
                "budget": {"calls_attempted": 7, "last_outcome": "llm_total_timeout"},
                "stage_breakdown": {"llm_product_row_shape": {"eligible_entities": 4}},
                "product_row_coverage": {
                    "candidate_total": 4,
                    "attempts": 4,
                    "successful_decisions": 3,
                    "failures": 0,
                    "skips": 0,
                    "max_output_retries": 0,
                    "hard_drops": 0,
                    "coverage_complete": False,
                    "fallback_publication_blocked": True,
                    "incomplete_reason": "llm_total_timeout",
                },
                "progress": {
                    "reason": "llm_total_timeout",
                    "current_stage": "llm_product_row_shape",
                    "current_candidate_index": 4,
                    "current_candidate_total": 4,
                    "elapsed_seconds": 1800,
                    "total_timeout_seconds": 1800,
                },
                "accepted_patches": [],
                "audit_only_patches": [],
                "model_name": "gpt-5-mini-2025-08-07",
            },
        }
        parsed = _run_parse_llm_helper_result(
            base_payload={
                "run_id": "parse-timeout",
                "llm_result_path": "__TGSA_N8N_FILES_DIR__/tgss-llm-result-parse-timeout.json",
                "llm_transport_path": "__TGSA_N8N_FILES_DIR__/tgss-llm-parse-timeout.json",
                "llm_payload_bytes": 123,
                "llm_execute_command": "poetry run python execute_helper_wrapper.py --launch-spec-b64url redacted",
                "llm_execute_command_len": 80,
                "llm_helper_path": "__TGSA_REPO_ROOT__/scripts/llm/post_merge_llm.py",
                "service_run_candidate": {},
                "run_logging": {},
            },
            execute_payload={
                "stdout": json.dumps(
                    {
                        "helper_path": "__TGSA_REPO_ROOT__/scripts/llm/post_merge_llm.py",
                        "exit_code": 124,
                        "invocation_error": "llm_total_timeout",
                        "stdout": "",
                        "stderr": "timeout",
                        "payload_bytes": 123,
                    },
                    ensure_ascii=False,
                ),
                "stderr": "",
            },
            read_payload={},
            result_text=json.dumps(artifact, ensure_ascii=False),
        )

        self.assertEqual(parsed["llm_contract_status"], "extr_llm_05_v1_error")
        self.assertEqual(parsed["llm_stage"]["reason"], "llm_total_timeout")
        self.assertEqual(parsed["llm_stage"]["calls_attempted"], 7)
        self.assertEqual(parsed["llm_stage"]["product_row_coverage"]["candidate_total"], 4)
        self.assertFalse(parsed["llm_stage"]["product_row_coverage"]["coverage_complete"])
        self.assertEqual(parsed["llm_stage"]["progress"]["current_stage"], "llm_product_row_shape")

    def test_llm_parse_preserves_process_failed_when_nonzero_wrapper_has_no_result_file(self) -> None:
        parsed = _run_parse_llm_helper_result(
            base_payload={
                "run_id": "parse-missing-timeout",
                "llm_result_path": "__TGSA_N8N_FILES_DIR__/missing-result.json",
                "llm_execute_command": "poetry run python execute_helper_wrapper.py --launch-spec-b64url redacted",
                "llm_execute_command_len": 80,
                "llm_helper_path": "__TGSA_REPO_ROOT__/scripts/llm/post_merge_llm.py",
                "canonical_output": {"providers": [], "offers": []},
                "service_run_candidate": {},
                "run_logging": {},
            },
            execute_payload={
                "stdout": json.dumps(
                    {
                        "helper_path": "__TGSA_REPO_ROOT__/scripts/llm/post_merge_llm.py",
                        "exit_code": 124,
                        "invocation_error": "llm_total_timeout",
                        "stdout": "",
                        "stderr": "timeout",
                    },
                    ensure_ascii=False,
                ),
                "stderr": "",
            },
            read_payload={"error": "No file(s) found for selector"},
        )

        self.assertEqual(parsed["llm_contract_status"], "extr_llm_05_v1_error")
        self.assertEqual(parsed["llm_error_type"], "llm_helper_process_failed")
        self.assertEqual(parsed["llm_stage"]["reason"], "llm_helper_process_failed")

    def test_llm_parse_reports_output_read_failed_when_zero_wrapper_has_no_result_file(self) -> None:
        parsed = _run_parse_llm_helper_result(
            base_payload={
                "run_id": "parse-missing-success",
                "llm_result_path": "__TGSA_N8N_FILES_DIR__/missing-result.json",
                "llm_execute_command": "poetry run python execute_helper_wrapper.py --launch-spec-b64url redacted",
                "llm_execute_command_len": 80,
                "llm_helper_path": "__TGSA_REPO_ROOT__/scripts/llm/post_merge_llm.py",
                "canonical_output": {"providers": [], "offers": []},
                "service_run_candidate": {},
                "run_logging": {},
            },
            execute_payload={
                "stdout": json.dumps(
                    {
                        "helper_path": "__TGSA_REPO_ROOT__/scripts/llm/post_merge_llm.py",
                        "exit_code": 0,
                        "stdout": "",
                        "stderr": "",
                    },
                    ensure_ascii=False,
                ),
                "stderr": "",
            },
            read_payload={"error": "No file(s) found for selector"},
        )

        self.assertEqual(parsed["llm_contract_status"], "extr_llm_05_v1_error")
        self.assertEqual(parsed["llm_error_type"], "llm_output_read_failed")
        self.assertEqual(parsed["llm_stage"]["reason"], "llm_output_read_failed")

    def test_projection_uses_publishable_row_with_exact_visible_contract(self) -> None:
        projected = _run_build_projection_rows(
            {
                "normalized_request": {
                    "publication_targets": {"sheets": True, "db": False, "dashboard": False},
                    "google_sheet_id": "sheet-123",
                    "llm_enabled": True,
                },
                "llm_contract_status": "extr_llm_05_v1_success",
                "llm_stage": {
                    "status": "success",
                    "product_row_coverage": LLM_PRODUCT_ROW_COVERAGE_COMPLETE,
                },
                "service_run_candidate": {
                    "started_at_utc": "2026-04-22T10:00:00Z",
                    "warnings_json": "[]",
                    "run_status": "success",
                },
                "canonical_output": {
                    "providers": [
                        {
                            "provider_key": "provider-visible-1",
                            "instagram_handles": ["example_ac_cleaner"],
                            "instagram_links": [],
                            "phones": [],
                            "telegram_handles": [],
                            "telegram_links": [],
                        }
                    ],
                    "offers": [
                        {
                            "offer_key": "offer-visible-1",
                            "provider_key": "provider-visible-1",
                            "price_text_best": "30 EUR",
                            "city_codes": ["belgrade"],
                            "city_display_names": ["Belgrade"],
                            "contact_snapshot_phones": ["381600000004"],
                            "contact_snapshot_telegram_handles": ["example_cleaner_help"],
                            "contact_snapshot_telegram_links": ["https://t.me/example_cleaner_help"],
                            "title_best": "RAW TITLE SHOULD NOT LEAK",
                            "description_best": "RAW DESCRIPTION SHOULD NOT LEAK",
                            "product_row_service_name": "NOISY PRODUCT ROW",
                            "product_row_details": (
                                "Канал/портфолио в Telegram указан в исходном посте. "
                                "Всем привет, пишите @example_spam | https://t.me/example_spam"
                            ),
                            "product_row_category": "Плохой guess",
                            "product_row_contact": "@example_spam | https://t.me/example_spam",
                            "publishable_row": {
                                "publish_decision": "publish",
                                "service_name": "Чистка кондиционеров",
                                "details": "Чистка и базовое обслуживание кондиционеров.",
                                "category": "Ремонт и монтаж",
                                "contact": "+381600000004",
                                "telegram": "@example_cleaner_help",
                                "instagram": "",
                                "whatsapp": "",
                                "phone": "+381600000004",
                                "source": "https://t.me/example_source_kappa/77",
                                "price": "30 eur",
                                "actual_on": "22.04.2026",
                                "audit_reason": "deterministic_gate_publish",
                            },
                        },
                        {
                            "offer_key": "offer-visible-2",
                            "provider_key": "provider-visible-2",
                            "price_text_best": "99 EUR",
                            "city_codes": ["novi_sad"],
                            "city_display_names": ["Novi Sad"],
                            "title_best": "ALSO SHOULD NOT LEAK",
                            "description_best": "RAW SHOULD NOT LEAK EITHER",
                            "product_row_service_name": "SHOULD NOT FALL BACK",
                            "product_row_details": "Всем привет, это fallback, которого быть не должно.",
                            "product_row_category": "Неправильная категория",
                            "product_row_contact": "@example_fallback_contact",
                            "publishable_row": {
                                "publish_decision": "drop",
                                "service_name": "",
                                "details": "",
                                "category": "",
                                "contact": "",
                                "telegram": "",
                                "instagram": "",
                                "whatsapp": "",
                                "phone": "",
                                "source": "",
                                "actual_on": "",
                                "price": "",
                                "audit_reason": "publishable_missing_contact",
                            },
                        },
                    ],
                },
                "merge_output": {},
                "audit_enrichment_rows": [],
                "run_target_candidates": [],
                "raw_posts": [],
                "raw_posts_total": 0,
                "extraction_ok": True,
                "merge_ok": True,
            }
        )

        self.assertEqual(projected["sheets_config"]["visible_services_sheet_name"], "Услуги")
        self.assertEqual(projected["visible_services_sheet_rows_total"], 1)
        self.assertEqual(projected["publication_summary"]["visible_services_rows_total"], 1)
        self.assertEqual(projected["visible_services_sheet_headers"], VISIBLE_HEADERS)
        self.assertTrue(projected["visible_services_publication_allowed"])
        self.assertEqual(projected["visible_services_publication_status"], "allowed")
        self.assertEqual(projected["publication_summary"]["status"], "ready_to_write")

        row = projected["visible_services_sheet_rows"][0]
        self.assertEqual(list(row.keys()), VISIBLE_HEADERS)
        self.assertEqual(
            row,
            {
                "Услуга": "Чистка кондиционеров",
                "Детали": "Чистка и базовое обслуживание кондиционеров.",
                "Категория": "Ремонт и монтаж",
                "Цена": "30 eur",
                "Город": "Белград",
                "Telegram": "@example_cleaner_help",
                "Instagram": "@example_ac_cleaner",
                "WhatsApp": "",
                "Телефон": "+381600000004",
                "Источник": "https://t.me/example_source_kappa/77",
                "Актуально на": "22.04.2026",
            },
        )
        self.assertEqual(
            projected["visible_services_sheet_write_matrix"],
            [
                VISIBLE_HEADERS,
                [
                    "Чистка кондиционеров",
                    "Чистка и базовое обслуживание кондиционеров.",
                    "Ремонт и монтаж",
                    "30 eur",
                    "Белград",
                    "@example_cleaner_help",
                    "@example_ac_cleaner",
                    "",
                    "+381600000004",
                    "https://t.me/example_source_kappa/77",
                    "22.04.2026",
                ],
            ],
        )
        self.assertEqual(projected["visible_services_sheet_clear_range"], "Услуги!A:K")
        self.assertEqual(projected["visible_services_sheet_write_range"], "Услуги!A1:K2")
        self.assertNotIn("NOISY PRODUCT ROW", json.dumps(row, ensure_ascii=False))
        self.assertNotIn("RAW TITLE SHOULD NOT LEAK", json.dumps(row, ensure_ascii=False))
        self.assertNotIn("портфолио", json.dumps(row, ensure_ascii=False).lower())
        self.assertNotIn("telegram указан", json.dumps(row, ensure_ascii=False).lower())
        self.assertNotIn("@example_fallback_contact", json.dumps(projected["visible_services_sheet_rows"], ensure_ascii=False))

    def test_projection_blocks_visible_sheet_when_llm_product_coverage_is_not_acceptable(self) -> None:
        projected = _run_build_projection_rows(
            {
                "normalized_request": {
                    "publication_targets": {"sheets": True, "db": False, "dashboard": False},
                    "google_sheet_id": "sheet-123",
                    "llm_enabled": False,
                },
                "service_run_candidate": {
                    "started_at_utc": "2026-04-22T10:00:00Z",
                    "warnings_json": "[]",
                    "run_status": "success",
                },
                "canonical_output": {
                    "providers": [],
                    "offers": [
                        {
                            "offer_key": "offer-drop-1",
                            "provider_key": "provider-drop-1",
                            "publishable_row": {
                                "publish_decision": "drop",
                                "service_name": "",
                                "details": "",
                                "category": "",
                                "contact": "",
                                "telegram": "",
                                "instagram": "",
                                "whatsapp": "",
                                "phone": "",
                                "source": "",
                                "actual_on": "",
                                "audit_reason": "publishable_non_service",
                            },
                        }
                    ],
                },
                "merge_output": {},
                "audit_enrichment_rows": [],
                "run_target_candidates": [],
                "raw_posts": [],
                "raw_posts_total": 0,
                "extraction_ok": True,
                "merge_ok": True,
            }
        )

        self.assertEqual(projected["visible_services_sheet_rows_total"], 0)
        self.assertEqual(projected["visible_services_sheet_rows"], [])
        self.assertEqual(projected["visible_services_sheet_headers"], VISIBLE_HEADERS)
        self.assertEqual(projected["visible_services_sheet_write_matrix"], [])
        self.assertEqual(projected["visible_services_sheet_clear_range"], "")
        self.assertEqual(projected["visible_services_sheet_write_range"], "")
        self.assertFalse(projected["visible_services_publication_allowed"])
        self.assertEqual(projected["visible_services_publication_status"], "blocked")
        self.assertEqual(projected["visible_services_publication_blocked_reason"], "blocked_no_llm_product_row_coverage")
        self.assertEqual(projected["visible_services_publication_block_detail"], "llm_disabled")
        self.assertEqual(projected["publication_summary"]["status"], "blocked_visible_publication")
        self.assertEqual(
            projected["run_logging"]["visible_services_publication_blocked_reason"],
            "blocked_no_llm_product_row_coverage",
        )

    def test_projection_blocks_visible_sheet_when_product_coverage_has_failures(self) -> None:
        projected = _run_build_projection_rows(
            {
                "normalized_request": {
                    "publication_targets": {"sheets": True, "db": False, "dashboard": False},
                    "google_sheet_id": "sheet-123",
                    "llm_enabled": True,
                },
                "llm_contract_status": "extr_llm_05_v1_success",
                "llm_stage": {
                    "status": "success",
                    "product_row_coverage": {
                        **LLM_PRODUCT_ROW_COVERAGE_COMPLETE,
                        "failures": 1,
                        "coverage_complete": False,
                    },
                },
                "service_run_candidate": {
                    "started_at_utc": "2026-04-22T10:00:00Z",
                    "warnings_json": "[]",
                    "run_status": "success",
                },
                "canonical_output": {
                    "providers": [],
                    "offers": [
                        {
                            "offer_key": "offer-blocked-coverage",
                            "provider_key": "provider-blocked-coverage",
                            "publishable_row": {
                                "publish_decision": "publish",
                                "service_name": "Сантехник",
                                "details": "Срочный выезд по Белграду.",
                                "category": "Ремонт и монтаж",
                                "contact": "@example_plumber",
                                "telegram": "@example_plumber",
                                "instagram": "",
                                "whatsapp": "",
                                "phone": "",
                                "source": "https://t.me/example_source_kappa/900",
                                "actual_on": "22.04.2026",
                                "price": "",
                                "audit_reason": "deterministic_gate_publish",
                            },
                        }
                    ],
                },
                "merge_output": {},
                "audit_enrichment_rows": [],
                "run_target_candidates": [],
                "raw_posts": [],
                "raw_posts_total": 0,
                "extraction_ok": True,
                "merge_ok": True,
            }
        )

        self.assertEqual(projected["visible_services_sheet_rows_total"], 1)
        self.assertEqual(projected["visible_services_sheet_write_matrix"], [])
        self.assertEqual(projected["visible_services_sheet_clear_range"], "")
        self.assertEqual(projected["visible_services_sheet_write_range"], "")
        self.assertFalse(projected["visible_services_publication_allowed"])
        self.assertEqual(projected["visible_services_publication_block_detail"], "product_row_coverage_failures")
        self.assertNotIn("Услуги!A:K", json.dumps(projected, ensure_ascii=False))
        self.assertNotIn("Услуги!A1:K", json.dumps(projected, ensure_ascii=False))

    def test_projection_blocks_visible_sheet_when_product_row_chunk_continuation_is_required(self) -> None:
        projected = _run_build_projection_rows(
            {
                "normalized_request": {
                    "publication_targets": {"sheets": True, "db": True, "dashboard": True},
                    "google_sheet_id": "sheet-123",
                    "llm_enabled": True,
                },
                "llm_contract_status": "extr_llm_05_v1_error",
                "llm_stage": {
                    "status": "error",
                    "reason": "llm_product_row_continuation_required",
                    "product_row_coverage": {
                        **LLM_PRODUCT_ROW_COVERAGE_COMPLETE,
                        "candidate_total": 5,
                        "attempts": 2,
                        "successful_decisions": 2,
                        "coverage_complete": False,
                        "incomplete_reason": "llm_product_row_continuation_required",
                    },
                    "product_row_chunking": {
                        "enabled": True,
                        "status": "continuation_required",
                        "candidate_total": 5,
                        "chunk_size": 2,
                        "processed_candidate_count": 2,
                        "remaining_candidate_count": 3,
                    },
                },
                "service_run_candidate": {
                    "started_at_utc": "2026-04-22T10:00:00Z",
                    "warnings_json": "[]",
                    "run_status": "success",
                },
                "canonical_output": {
                    "providers": [],
                    "offers": [
                        {
                            "offer_key": "offer-chunk-wait",
                            "provider_key": "provider-chunk-wait",
                            "publishable_row": {
                                "publish_decision": "publish",
                                "service_name": "Клининг квартир",
                                "details": "Поддерживающая уборка квартир.",
                                "category": "Уборка и химчистка",
                                "contact": "@example_cleaning",
                                "telegram": "@example_cleaning",
                                "instagram": "",
                                "whatsapp": "",
                                "phone": "",
                                "source": "https://t.me/example_cleaning/1",
                                "actual_on": "22.04.2026",
                                "price": "",
                                "audit_reason": "deterministic_gate_publish",
                            },
                        }
                    ],
                },
                "merge_output": {},
                "audit_enrichment_rows": [],
                "run_target_candidates": [],
                "raw_posts": [],
                "raw_posts_total": 0,
                "extraction_ok": True,
                "merge_ok": True,
            }
        )

        self.assertEqual(projected["visible_services_sheet_rows_total"], 1)
        self.assertEqual(projected["visible_services_sheet_write_matrix"], [])
        self.assertEqual(projected["visible_services_sheet_clear_range"], "")
        self.assertEqual(projected["visible_services_sheet_write_range"], "")
        self.assertFalse(projected["visible_services_publication_allowed"])
        self.assertEqual(projected["visible_services_publication_blocked_reason"], "blocked_no_llm_product_row_coverage")
        self.assertEqual(projected["visible_services_publication_block_detail"], "llm_product_row_continuation_required")
        self.assertFalse(projected["sheets_publication_allowed"])
        self.assertTrue(projected["sheets_publication_blocked"])
        self.assertEqual(projected["sheets_publication_blocked_reason"], "blocked_incomplete_product_row_coverage")
        self.assertEqual(projected["sheets_publication_block_detail"], "llm_product_row_continuation_required")
        self.assertEqual(projected["publication_summary"]["status"], "blocked_incomplete_product_row_coverage")
        self.assertEqual(projected["publication_summary"]["sheets_publication_allowed"], False)
        self.assertEqual(projected["db_contract_status"], "wf_db_publish_28_v1_blocked_incomplete_product_row_coverage")
        self.assertEqual(projected["db_publication"]["status"], "blocked")

        workflow = _load_workflow()
        gate_node = _node_by_name(workflow, "WF-SHEETS-04 Should Publish To Sheets?")
        gate_condition = gate_node["parameters"]["conditions"]["conditions"][0]["leftValue"]
        self.assertIn("sheets_publication_allowed", gate_condition)
        self.assertNotIn("sheets_config?.enabled", gate_condition)
        gate_connections = workflow["connections"]["WF-SHEETS-04 Should Publish To Sheets?"]["main"]
        self.assertEqual(gate_connections[0][0]["node"], "WF-SHEETS-04 Emit Sheet Specs (v1)")
        self.assertEqual(gate_connections[1][0]["node"], "WF-RESP-01 Webhook Or Manual Output?")

        response = _run_code_node("WF-RESP-01 Build Webhook Response (v1)", projected)
        response_body = response["webhook_response"]["body"]
        self.assertEqual(response_body["publication_summary"]["status"], "blocked_incomplete_product_row_coverage")
        self.assertEqual(response_body["llm_summary"]["reason"], "llm_product_row_continuation_required")
        self.assertEqual(
            response_body["llm_summary"]["product_row_coverage"]["incomplete_reason"],
            "llm_product_row_continuation_required",
        )
        self.assertEqual(response_body["continuation_evidence"]["status"], "continuation_required")
        self.assertEqual(response_body["continuation_evidence"]["product_row_chunking"]["remaining_candidate_count"], 3)

    def test_projection_blocks_publication_when_product_row_candidate_mismatch_requires_repair(self) -> None:
        mismatch_evidence = {
            "saved_candidate_total": 3,
            "current_candidate_total": 2,
            "saved_candidate_order_fingerprint": "saved-fingerprint",
            "current_candidate_order_fingerprint": "current-fingerprint",
            "missing_candidate_ids": ["offer:coverage:002"],
            "unexpected_candidate_ids": [],
            "changed_candidate_ids": [],
            "first_mismatch_index": 2,
            "can_retry_same_continuation_state": False,
            "safe_repair_contract": "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required",
        }
        projected = _run_build_projection_rows(
            {
                "normalized_request": {
                    "publication_targets": {"sheets": True, "db": True, "dashboard": True},
                    "google_sheet_id": "sheet-123",
                    "llm_enabled": True,
                },
                "llm_contract_status": "extr_llm_05_v1_error",
                "llm_stage": {
                    "status": "error",
                    "reason": "llm_product_row_continuation_state_candidate_mismatch",
                    "calls_attempted": 0,
                    "product_row_coverage": {
                        **LLM_PRODUCT_ROW_COVERAGE_COMPLETE,
                        "candidate_total": 2,
                        "attempts": 0,
                        "successful_decisions": 0,
                        "coverage_complete": False,
                        "incomplete_reason": "llm_product_row_continuation_state_candidate_mismatch",
                    },
                    "product_row_chunking": {
                        "enabled": True,
                        "status": "blocked",
                        "error": "llm_product_row_continuation_state_candidate_mismatch",
                        "candidate_total": 2,
                        "processed_candidate_count": 0,
                        "remaining_candidate_count": 2,
                        "candidate_mismatch_evidence": mismatch_evidence,
                    },
                },
                "service_run_candidate": {
                    "started_at_utc": "2026-04-22T10:00:00Z",
                    "warnings_json": "[]",
                    "run_status": "success",
                },
                "canonical_output": {
                    "providers": [],
                    "offers": [
                        {
                            "offer_key": "offer-mismatch-blocked",
                            "provider_key": "provider-mismatch-blocked",
                            "publishable_row": {
                                "publish_decision": "publish",
                                "service_name": "Cleaning",
                                "details": "Apartment cleaning.",
                                "category": "Cleaning",
                                "contact": "@example_cleaning",
                                "telegram": "@example_cleaning",
                                "instagram": "",
                                "whatsapp": "",
                                "phone": "",
                                "source": "https://t.me/example_cleaning/1",
                                "actual_on": "22.04.2026",
                                "price": "",
                                "audit_reason": "deterministic_gate_publish",
                            },
                        }
                    ],
                },
                "merge_output": {},
                "audit_enrichment_rows": [],
                "run_target_candidates": [],
                "raw_posts": [],
                "raw_posts_total": 0,
                "extraction_ok": True,
                "merge_ok": True,
            }
        )

        self.assertEqual(projected["visible_services_sheet_rows_total"], 1)
        self.assertEqual(projected["visible_services_sheet_write_matrix"], [])
        self.assertEqual(projected["visible_services_sheet_clear_range"], "")
        self.assertEqual(projected["visible_services_sheet_write_range"], "")
        self.assertFalse(projected["sheets_publication_allowed"])
        self.assertTrue(projected["sheets_publication_blocked"])
        self.assertEqual(projected["publication_summary"]["status"], "blocked_incomplete_product_row_coverage")
        self.assertEqual(projected["db_contract_status"], "wf_db_publish_28_v1_blocked_incomplete_product_row_coverage")
        self.assertEqual(projected["db_publication"]["status"], "blocked")

        response = _run_code_node("WF-RESP-01 Build Webhook Response (v1)", projected)
        response_body = response["webhook_response"]["body"]
        self.assertEqual(response_body["llm_summary"]["reason"], "llm_product_row_continuation_state_candidate_mismatch")
        self.assertEqual(
            response_body["llm_summary"]["product_row_chunking"]["candidate_mismatch_evidence"],
            mismatch_evidence,
        )
        self.assertIsNone(response_body["continuation_evidence"])

    def test_visible_services_nodes_use_clear_then_raw_write_http_requests(self) -> None:
        workflow = _load_workflow()
        clear_node = _node_by_name(workflow, "WF-SHEETS-04 Clear Visible Services (v1)")
        write_node = _node_by_name(workflow, "WF-SHEETS-04 Upsert Visible Services (v1)")
        gate_node = _node_by_name(workflow, "WF-SHEETS-04 Has Visible Services Rows?")

        self.assertEqual(clear_node["type"], "n8n-nodes-base.httpRequest")
        self.assertEqual(clear_node["parameters"]["method"], "POST")
        self.assertIn(":clear", clear_node["parameters"]["url"])

        self.assertEqual(write_node["type"], "n8n-nodes-base.httpRequest")
        self.assertEqual(write_node["parameters"]["method"], "PUT")
        self.assertIn("valueInputOption=RAW", write_node["parameters"]["url"])
        self.assertEqual(write_node["parameters"]["specifyBody"], "json")

        left_value = gate_node["parameters"]["conditions"]["conditions"][0]["leftValue"]
        self.assertIn("visible_services_publication_allowed", left_value)

    def test_visible_services_upsert_uses_emitted_payload_after_clear_response(self) -> None:
        projected = _run_build_projection_rows(
            {
                "normalized_request": {
                    "publication_targets": {"sheets": True, "db": False, "dashboard": False},
                    "google_sheet_id": "sheet-126",
                    "llm_enabled": True,
                },
                "llm_contract_status": "extr_llm_05_v1_success",
                "llm_stage": {
                    "status": "success",
                    "product_row_coverage": LLM_PRODUCT_ROW_COVERAGE_COMPLETE,
                },
                "service_run_candidate": {
                    "started_at_utc": "2026-04-22T10:00:00Z",
                    "warnings_json": "[]",
                    "run_status": "success",
                },
                "canonical_output": {
                    "providers": [
                        {
                            "provider_key": "provider-clear-regression",
                            "phones": ["+381600000018"],
                            "telegram_handles": ["example_services_writer"],
                            "telegram_links": ["https://t.me/example_services_writer"],
                            "instagram_handles": [],
                            "instagram_links": [],
                        }
                    ],
                    "offers": [
                        {
                            "offer_key": "offer-clear-regression",
                            "provider_key": "provider-clear-regression",
                            "price_text_best": "45 EUR",
                            "city_codes": ["belgrade"],
                            "contact_snapshot_phones": ["+381600000018"],
                            "contact_snapshot_telegram_handles": ["example_services_writer"],
                            "contact_snapshot_telegram_links": ["https://t.me/example_services_writer"],
                            "publishable_row": {
                                "publish_decision": "publish",
                                "service_name": "Ремонт бойлеров",
                                "details": "Выезд по Белграду.",
                                "category": "Ремонт и монтаж",
                                "contact": "+381600000018",
                                "telegram": "@example_services_writer",
                                "instagram": "",
                                "whatsapp": "",
                                "phone": "+381600000018",
                                "source": "https://t.me/example_source_kappa/126",
                                "actual_on": "22.04.2026",
                                "price": "45 eur",
                                "audit_reason": "deterministic_gate_publish",
                            },
                        }
                    ],
                },
                "merge_output": {},
                "audit_enrichment_rows": [],
                "run_target_candidates": [],
                "raw_posts": [],
                "raw_posts_total": 0,
                "extraction_ok": True,
                "merge_ok": True,
            }
        )

        self.assertEqual(projected["visible_services_sheet_write_range"], "Услуги!A1:K2")
        self.assertEqual(len(projected["visible_services_sheet_write_matrix"]), 2)

        workflow = _load_workflow()
        write_node = _node_by_name(workflow, "WF-SHEETS-04 Upsert Visible Services (v1)")
        write_url = write_node["parameters"]["url"]
        write_body = write_node["parameters"]["jsonBody"]
        emitter_ref = "$('WF-SHEETS-04 Emit Visible Services Rows (v1)').first().json"

        self.assertIn(f"{emitter_ref}.visible_services_sheet_write_range", write_url)
        self.assertIn(f"range: {emitter_ref}.visible_services_sheet_write_range ?? ''", write_body)
        self.assertIn(f"values: {emitter_ref}.visible_services_sheet_write_matrix ?? []", write_body)
        self.assertNotIn("$json.visible_services_sheet_write_range", write_url)
        self.assertNotIn("$json.visible_services_sheet_write_range", write_body)
        self.assertNotIn("$json.visible_services_sheet_write_matrix", write_body)


if __name__ == "__main__":
    unittest.main()
