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


def _run_code_node(node_name: str, input_payload: dict) -> list[dict]:
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
    return json.loads(completed.stdout)


def _projection_payload_with_dynamic_source() -> dict:
    return {
        "normalized_request": {
            "publication_targets": {"sheets": True, "db": False, "dashboard": False},
            "google_sheet_id": "sheet-tab-hygiene",
            "llm_enabled": True,
            "resolved_targets": [
                {
                    "source_key": "example_source_alpha",
                    "target_input": "https://t.me/example_source_alpha",
                    "display_name": "Serbia Specialists",
                    "sheet_tab_name": "source_example_source_alpha",
                    "parse_enabled": True,
                }
            ],
        },
        "service_run_candidate": {
            "started_at_utc": "2026-04-22T10:00:00Z",
            "warnings_json": "[]",
            "run_status": "success",
        },
        "canonical_output": {"providers": [], "offers": []},
        "merge_output": {},
        "audit_enrichment_rows": [],
        "run_target_candidates": [],
        "raw_posts": [],
        "raw_posts_total": 0,
        "extraction_ok": True,
        "merge_ok": True,
    }


def _hidden_by_title(specs: list[dict]) -> dict[str, bool]:
    return {spec["sheet_title"]: spec["sheet_hidden"] for spec in specs}


class SheetsTabHygieneWorkflowTests(unittest.TestCase):
    def test_bootstrap_tabs_keep_only_sources_config_visible(self) -> None:
        result = _run_code_node(
            "WF-SHEETS-01 Emit Bootstrap Tabs (v1)",
            {"normalized_request": {"google_sheet_id": "sheet-tab-hygiene"}},
        )
        specs = [item["json"] for item in result]
        hidden_by_title = _hidden_by_title(specs)

        self.assertEqual(
            [title for title, hidden in hidden_by_title.items() if hidden is False],
            ["sources_config"],
        )
        self.assertIs(hidden_by_title["catalog"], True)
        for title in ("providers", "offers", "service_runs", "run_targets", "source_state"):
            self.assertIs(hidden_by_title[title], True)

    def test_projection_specs_keep_public_tabs_visible_and_runtime_tabs_hidden(self) -> None:
        result = _run_code_node("WF-SHEETS-04 Build Projection Rows (v1)", _projection_payload_with_dynamic_source())
        projected = result[0]["json"]
        hidden_by_title = _hidden_by_title(projected["sheet_specs"])

        self.assertCountEqual(
            [title for title, hidden in hidden_by_title.items() if hidden is False],
            ["sources_config", "Услуги"],
        )
        for title in ("catalog", "providers", "offers", "service_runs", "run_targets", "source_state"):
            self.assertIs(hidden_by_title[title], True)

        self.assertEqual(
            projected["source_sheet_specs"],
            [{"sheet_title": "source_example_source_alpha", "sheet_hidden": True}],
        )
        self.assertIs(hidden_by_title["source_example_source_alpha"], True)
        self.assertEqual(projected["sheets_config"]["visible_services_sheet_name"], "Услуги")


if __name__ == "__main__":
    unittest.main()
