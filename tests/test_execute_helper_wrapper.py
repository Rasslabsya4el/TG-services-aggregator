from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.common.execute_helper_wrapper import run_launch_spec


class ExecuteHelperWrapperTests(unittest.TestCase):
    def test_post_merge_llm_timeout_materializes_result_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            helper_path = temp_path / "sleeping_helper.py"
            payload_path = temp_path / "payload.json"
            output_path = temp_path / "llm-result.json"

            helper_path.write_text(
                "import time\n"
                "time.sleep(5)\n",
                encoding="utf-8",
            )
            payload = {
                "run_id": "wrapper-timeout",
                "normalized_request": {"llm_enabled": True},
                "merge_output": {
                    "providers": [{"provider_key": "provider:1"}],
                    "offers": [{"offer_key": "offer:1", "provider_key": "provider:1"}],
                    "merge_summary": {},
                },
            }
            payload_text = json.dumps(payload, ensure_ascii=False)
            payload_path.write_text(payload_text, encoding="utf-8")

            wrapper = run_launch_spec(
                {
                    "helper_path": str(helper_path),
                    "helper_args": ["--input-path", str(payload_path), "--output-path", str(output_path)],
                    "payload_path": str(payload_path),
                    "payload_bytes": len(payload_text.encode("utf-8")),
                    "output_path": str(output_path),
                    "timeout_seconds": 0,
                    "timeout_exit_code": 124,
                    "timeout_artifact": "post_merge_llm",
                    "invocation_exit_code": 9004,
                }
            )

            self.assertEqual(wrapper["exit_code"], 124)
            self.assertEqual(wrapper["invocation_error"], "llm_total_timeout")
            self.assertTrue(wrapper["timed_out"])
            self.assertTrue(output_path.exists())
            artifact = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["llm_stage"]["status"], "error")
            self.assertEqual(artifact["llm_stage"]["reason"], "llm_total_timeout")
            self.assertFalse(artifact["llm_stage"]["product_row_coverage"]["coverage_complete"])
            self.assertEqual(
                artifact["llm_stage"]["product_row_coverage"]["incomplete_reason"],
                "llm_total_timeout",
            )
            self.assertTrue(artifact["llm_stage"]["progress"]["wrapper_timeout"])


if __name__ == "__main__":
    unittest.main()
