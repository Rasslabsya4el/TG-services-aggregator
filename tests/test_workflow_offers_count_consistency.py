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
const input = JSON.parse(process.argv[2]);
const upstream = JSON.parse(process.argv[3]);
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
    try:
        completed = subprocess.run(
            [
                "node",
                str(harness_path),
                json.dumps(input_payload or {}, ensure_ascii=False),
                json.dumps(upstream_payloads or {}, ensure_ascii=False),
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
            f"node harness failed for {node_name}\n"
            f"returncode={completed.returncode}\n"
            f"stdout={completed.stdout}\n"
            f"stderr={completed.stderr}"
        )
    payload = json.loads(completed.stdout)
    return payload[0]["json"]


def _build_projection_rows_payload() -> dict:
    return {
        "normalized_request": {
            "publication_targets": {"sheets": True, "db": False, "dashboard": False},
            "google_sheet_id": "sheet-123",
            "llm_enabled": True,
        },
        "run_id": "run-duplicate-offers",
        "service_run_candidate": {
            "run_id": "run-duplicate-offers",
            "started_at_utc": "2026-04-22T18:12:52.083Z",
            "warnings_json": "[]",
            "run_status": "success",
            "successful_target_count": 1,
            "successful_targets_json": "[]",
            "failed_target_count": 0,
            "failed_targets_json": "[]",
            "fetch_messages_seen_total": 2,
        },
        "canonical_output": {
            "providers": [],
            "offers": [
                {
                    "offer_key": "offer-duplicate-1",
                    "provider_key": "provider-1",
                    "offer_state": "candidate",
                    "service_signature_key": "svc-1",
                    "category_primary": "food",
                    "title_best": "First version",
                    "description_best": "Old source row",
                    "price_text_best": "",
                    "first_seen_at_utc": "2026-04-22T10:52:35Z",
                    "last_seen_at_utc": "2026-04-22T10:52:35Z",
                    "first_seen_run_id": "run-duplicate-offers",
                    "last_seen_run_id": "run-duplicate-offers",
                    "evidence_raw_post_ids": ["tg:one"],
                    "latest_post_url": "https://t.me/example_source_one/1",
                    "times_seen": 1,
                    "dedupe_confidence": "medium",
                    "source_channel_keys": ["source_one"],
                },
                {
                    "offer_key": "offer-duplicate-1",
                    "provider_key": "provider-1",
                    "offer_state": "candidate",
                    "service_signature_key": "svc-1",
                    "category_primary": "food",
                    "title_best": "Second version",
                    "description_best": "New source row",
                    "price_text_best": "",
                    "first_seen_at_utc": "2026-04-22T16:53:42Z",
                    "last_seen_at_utc": "2026-04-22T16:53:42Z",
                    "first_seen_run_id": "run-duplicate-offers",
                    "last_seen_run_id": "run-duplicate-offers",
                    "evidence_raw_post_ids": ["tg:two"],
                    "latest_post_url": "https://t.me/example_source_two/2",
                    "times_seen": 1,
                    "dedupe_confidence": "medium",
                    "source_channel_keys": ["source_two"],
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


class OffersCountConsistencyWorkflowTests(unittest.TestCase):
    def test_final_summary_counts_unique_offer_keys_for_append_or_update(self) -> None:
        projected = _run_node("WF-SHEETS-04 Build Projection Rows (v1)", input_payload=_build_projection_rows_payload())
        self.assertEqual(projected["offers_sheet_rows_total"], 2)

        upstream = {"WF-SHEETS-04 Build Projection Rows (v1)": projected}
        final_row = _run_node("WF-SHEETS-04 Emit Final Run Row (v1)", upstream_payloads=upstream)
        finalized = _run_node("WF-SHEETS-04 Finalize Publication Output (v1)", upstream_payloads=upstream)

        self.assertEqual(final_row["offers_upserted_total"], 1)
        final_response = json.loads(final_row["response_json"])
        self.assertEqual(final_response["sheets_publication"]["offers_rows_total"], 1)

        self.assertEqual(finalized["publication_summary"]["offers_rows_total"], 1)
        self.assertEqual(finalized["service_run_candidate"]["offers_upserted_total"], 1)
        self.assertEqual(finalized["run_logging"]["sheets_publication"]["offers_rows_total"], 1)

    def test_upsert_offers_node_matches_on_offer_key(self) -> None:
        workflow = _load_workflow()
        node = _node_by_name(workflow, "WF-SHEETS-04 Upsert Offers (v1)")
        self.assertEqual(node["parameters"]["columns"]["matchingColumns"], ["offer_key"])


if __name__ == "__main__":
    unittest.main()
