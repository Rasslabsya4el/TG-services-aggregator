from __future__ import annotations

import json
import importlib.util
import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "n8n" / "workflows" / "tg_services_serbia_greenfield_base.json"
FETCH_HELPER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch" / "fetch_telegram_history.py"


def _load_fetch_helper_module():
    spec = importlib.util.spec_from_file_location("fetch_telegram_history", FETCH_HELPER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load fetch helper module spec")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_workflow() -> dict:
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _node_by_name(workflow: dict, name: str) -> dict:
    for node in workflow.get("nodes", []):
        if node.get("name") == name:
            return node
    raise AssertionError(f"Workflow node not found: {name}")


def _run_node(
    node_name: str,
    *,
    input_payload: dict | None = None,
    upstream_payloads: dict[str, dict | list[dict]] | None = None,
) -> list[dict]:
    workflow = _load_workflow()
    js_code = _node_by_name(workflow, node_name)["parameters"]["jsCode"]
    harness = f"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const input = payload.input ?? {{}};
const upstream = payload.upstream ?? {{}};
const $input = {{
  first: () => ({{ json: input }}),
  all: () => [{{ json: input }}],
}};
const $ = (name) => {{
  const payload = upstream[name] ?? {{}};
  const items = Array.isArray(payload) ? payload : [payload];
  return {{
    first: () => ({{ json: items[0] ?? {{}} }}),
    all: () => items.map((item) => ({{ json: item }})),
  }};
}};
const fn = new Function('$', '$input', {json.dumps(js_code)});
const result = fn($, $input);
process.stdout.write(JSON.stringify(result));
"""
    return _run_node_harness(harness, input_payload=input_payload, upstream_payloads=upstream_payloads)


def _run_async_node(
    node_name: str,
    *,
    input_payloads: list[dict] | None = None,
    upstream_payloads: dict[str, dict | list[dict]] | None = None,
    binary_texts: list[str] | None = None,
) -> list[dict]:
    workflow = _load_workflow()
    js_code = _node_by_name(workflow, node_name)["parameters"]["jsCode"]
    harness = f"""
const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const inputs = payload.inputs ?? [{{}}];
const upstream = payload.upstream ?? {{}};
const binaryTexts = payload.binaryTexts ?? [''];
const $input = {{
  first: () => ({{ json: inputs[0] ?? {{}} }}),
  all: () => inputs.map((item) => ({{ json: item }})),
}};
const $ = (name) => {{
  const payload = upstream[name] ?? {{}};
  const items = Array.isArray(payload) ? payload : [payload];
  return {{
    first: () => ({{ json: items[0] ?? {{}} }}),
    all: () => items.map((item) => ({{ json: item }})),
  }};
}};
const helpers = {{
  getBinaryDataBuffer: async (index) => Buffer.from(binaryTexts[index] ?? '', 'utf8'),
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
    return _run_node_harness(
        harness,
        input_payload=None,
        input_payloads=input_payloads,
        upstream_payloads=upstream_payloads,
        binary_texts=binary_texts,
    )


def _run_node_harness(
    harness: str,
    *,
    input_payload: dict | None = None,
    input_payloads: list[dict] | None = None,
    upstream_payloads: dict[str, dict | list[dict]] | None = None,
    binary_texts: list[str] | None = None,
) -> list[dict]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as handle:
        handle.write(harness)
        harness_path = Path(handle.name)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(
            {
                "input": input_payload or {},
                "inputs": input_payloads or ([input_payload] if input_payload is not None else [{}]),
                "upstream": upstream_payloads or {},
                "binaryTexts": binary_texts or [""],
            },
            handle,
            ensure_ascii=False,
        )
        payload_path = Path(handle.name)
    try:
        completed = subprocess.run(
            ["node", str(harness_path), str(payload_path)],
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
            f"node harness failed\nreturncode={completed.returncode}\nstdout={completed.stdout}\nstderr={completed.stderr}"
        )
    return json.loads(completed.stdout)


class FetchTransportTests(unittest.TestCase):
    def test_input_normalization_preserves_product_row_chunk_request_fields(self) -> None:
        result = _run_node(
            "WF-INPUT-02 Normalize & Validate (v1)",
            input_payload={
                "raw_request": {
                    "body": {
                        "target": "https://t.me/example_source_alpha",
                        "llm_enabled": True,
                        "llm_product_row_max_candidates": 500,
                        "llm_product_row_chunking_enabled": True,
                        "llm_product_row_chunk_size": 250,
                        "llm_product_row_continuation_state_path": "__TGSA_N8N_FILES_DIR__/tgss-product-row-state.json",
                        "llm_product_row_continuation_token": "state-token",
                    },
                    "headers": {},
                    "query": {},
                    "params": {},
                },
            },
        )[0]["json"]

        normalized = result["normalized_request"]
        self.assertTrue(result["intake_valid"])
        self.assertTrue(normalized["llm_enabled"])
        self.assertEqual(normalized["llm_product_row_max_candidates"], 500)
        self.assertTrue(normalized["llm_product_row_chunking_enabled"])
        self.assertEqual(normalized["llm_product_row_chunk_size"], 250)
        self.assertEqual(
            normalized["llm_product_row_continuation_state_path"],
            "__TGSA_N8N_FILES_DIR__/tgss-product-row-state.json",
        )
        self.assertEqual(normalized["llm_product_row_continuation_token"], "state-token")

    def test_fetch_cli_file_helpers_round_trip_payload_and_output(self) -> None:
        fetch_helper = _load_fetch_helper_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "payload.json"
            output_path = Path(temp_dir) / "nested" / "result.json"
            payload_path.write_text(json.dumps({"telegram_target": "@example_source_kappa"}), encoding="utf-8")

            self.assertEqual(fetch_helper.load_payload_file(str(payload_path))["telegram_target"], "@example_source_kappa")
            fetch_helper.write_output('{"ok":true}', str(output_path))

            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), {"ok": True})

    def test_exact_tme_post_url_is_fetched_by_message_id_not_history_pagination(self) -> None:
        fetch_helper = _load_fetch_helper_module()

        class FakeMessage:
            id = 29
            date = fetch_helper.datetime(2026, 4, 20, 12, 0, tzinfo=fetch_helper.UTC)
            message = "Точный пост с услугой"
            media = None
            replies = None
            grouped_id = None
            sender_id = 1001
            post_author = ""
            views = 10
            forwards = 1

            async def get_sender(self):
                return SimpleNamespace(
                    id=1001,
                    username="provider_exact",
                    title="",
                    first_name="Provider",
                    last_name="Exact",
                    phone="",
                )

        class FakeTelegramClient:
            iter_messages_called = False
            get_messages_ids = None

            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get_entity(self, target):
                self.target = target
                return SimpleNamespace(
                    id=777,
                    username="example_source_theta",
                    title="Super Subotica",
                    broadcast=True,
                    megagroup=False,
                )

            async def get_messages(self, _entity, *, ids):
                FakeTelegramClient.get_messages_ids = list(ids)
                return [FakeMessage()]

            async def iter_messages(self, *_args, **_kwargs):
                FakeTelegramClient.iter_messages_called = True
                raise AssertionError("exact post URL must not use iter_messages")

        deps = {
            "TelegramClient": FakeTelegramClient,
            "StringSession": lambda value: value,
            "MessageService": type("FakeMessageService", (), {}),
            "ChannelPrivateError": type("ChannelPrivateError", (Exception,), {}),
            "FloodWaitError": type("FloodWaitError", (Exception,), {}),
            "InviteHashExpiredError": type("InviteHashExpiredError", (Exception,), {}),
            "InviteHashInvalidError": type("InviteHashInvalidError", (Exception,), {}),
            "RPCError": type("RPCError", (Exception,), {}),
            "SessionPasswordNeededError": type("SessionPasswordNeededError", (Exception,), {}),
            "UsernameInvalidError": type("UsernameInvalidError", (Exception,), {}),
            "UsernameNotOccupiedError": type("UsernameNotOccupiedError", (Exception,), {}),
        }

        with patch.dict(os.environ, {"TG_API_ID": "1", "TG_API_HASH": "hash", "TG_SESSION_STRING": "session"}):
            fetch_helper.load_telethon_dependencies = lambda: deps
            result = asyncio.run(
                fetch_helper.fetch_history(
                    {
                        "telegram_target": "https://t.me/example_source_theta/29",
                        "run_id": "run-exact-url",
                        "output_timezone": "Europe/Belgrade",
                        "since_date": "2020-01-01",
                        "max_messages": 5000,
                        "max_message_id": 10,
                    }
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(FakeTelegramClient.get_messages_ids, [29])
        self.assertFalse(FakeTelegramClient.iter_messages_called)
        self.assertTrue(result["exact_message_request"])
        self.assertEqual(result["exact_message_ids"], [29])
        self.assertEqual(result["stats"]["stopped_reason"], "exact_messages_fetched")
        self.assertIsNone(result["max_message_id"])
        self.assertEqual(result["posts"][0]["message_id"], 29)
        self.assertEqual(result["posts"][0]["post_url"], "https://t.me/example_source_theta/29")

    def test_full_public_fetch_applies_product_row_freeze_from_state_path(self) -> None:
        fetch_helper = _load_fetch_helper_module()

        class FakeMessage:
            def __init__(self, message_id: int):
                self.id = message_id
                self.date = fetch_helper.datetime(2026, 4, 20, 12, message_id, tzinfo=fetch_helper.UTC)
                self.message = f"Пост услуги {message_id}"
                self.media = None
                self.replies = None
                self.grouped_id = None
                self.sender_id = 1001
                self.post_author = ""
                self.views = 10
                self.forwards = 1

            async def get_sender(self):
                return SimpleNamespace(
                    id=1001,
                    username="provider_public",
                    title="",
                    first_name="Provider",
                    last_name="Public",
                    phone="",
                )

        class FakeTelegramClient:
            iter_messages_kwargs = None

            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get_entity(self, target):
                self.target = target
                return SimpleNamespace(
                    id=777,
                    username="example_source_kappa",
                    title="Serbia Services",
                    broadcast=True,
                    megagroup=False,
                )

            async def get_messages(self, *_args, **_kwargs):
                raise AssertionError("full public fetch must use history pagination")

            async def iter_messages(self, _entity, **kwargs):
                FakeTelegramClient.iter_messages_kwargs = dict(kwargs)
                message_ids = [12, 11, 10, 9, 8]
                if kwargs.get("max_id"):
                    message_ids = [message_id for message_id in message_ids if message_id < int(kwargs["max_id"])]
                if kwargs.get("min_id"):
                    message_ids = [message_id for message_id in message_ids if message_id > int(kwargs["min_id"])]
                if kwargs.get("limit"):
                    message_ids = message_ids[: int(kwargs["limit"])]
                for message_id in message_ids:
                    yield FakeMessage(message_id)

        deps = {
            "TelegramClient": FakeTelegramClient,
            "StringSession": lambda value: value,
            "MessageService": type("FakeMessageService", (), {}),
            "ChannelPrivateError": type("ChannelPrivateError", (Exception,), {}),
            "FloodWaitError": type("FloodWaitError", (Exception,), {}),
            "InviteHashExpiredError": type("InviteHashExpiredError", (Exception,), {}),
            "InviteHashInvalidError": type("InviteHashInvalidError", (Exception,), {}),
            "RPCError": type("RPCError", (Exception,), {}),
            "SessionPasswordNeededError": type("SessionPasswordNeededError", (Exception,), {}),
            "UsernameInvalidError": type("UsernameInvalidError", (Exception,), {}),
            "UsernameNotOccupiedError": type("UsernameNotOccupiedError", (Exception,), {}),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "product-row-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "fetch_freeze": {
                            "version": "product_row_fetch_freeze_v1",
                            "sources": [
                                {
                                    "source_key": "example_source_kappa",
                                    "target_key": "example_source_kappa",
                                    "telegram_public": "example_source_kappa",
                                    "upper_message_id": 10,
                                    "cutoff_utc": "2026-04-20T12:09:00Z",
                                    "oldest_post_utc": "2026-04-20T12:09:00Z",
                                    "lower_message_id": 9,
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"TG_API_ID": "1", "TG_API_HASH": "hash", "TG_SESSION_STRING": "session"}):
                fetch_helper.load_telethon_dependencies = lambda: deps
                result = asyncio.run(
                    fetch_helper.fetch_history(
                        {
                            "telegram_target": "@example_source_kappa",
                            "source_key": "example_source_kappa",
                            "target_key": "example_source_kappa",
                            "run_id": "run-freeze",
                            "output_timezone": "Europe/Belgrade",
                            "since_date": "2026-04-21",
                            "max_messages": 5,
                            "llm_product_row_continuation_state_path": str(state_path),
                        }
                    )
                )

        self.assertTrue(result["ok"])
        self.assertEqual([post["message_id"] for post in result["posts"]], [9, 10])
        self.assertEqual(FakeTelegramClient.iter_messages_kwargs, {"limit": 5, "max_id": 11, "min_id": 8})
        self.assertEqual(result["max_message_id"], 10)
        self.assertEqual(result["cutoff_utc"], "2026-04-20T12:09:00Z")
        self.assertEqual(result["stats"]["max_message_id_used"], 10)
        self.assertEqual(result["stats"]["lower_message_id_used"], 9)
        self.assertEqual(result["stats"]["lower_message_id_observed"], 9)
        self.assertEqual(result["stats"]["upper_message_id_observed"], 10)
        self.assertEqual(result["stats"]["messages_seen"], 2)
        self.assertEqual(result["stats"]["messages_newer_than_max_message_id_skipped"], 0)
        self.assertEqual(result["fetch_freeze"]["upper_message_id"], 10)
        self.assertEqual(result["fetch_freeze"]["max_message_id_applied"], 10)
        self.assertEqual(result["fetch_freeze"]["cutoff_utc"], "2026-04-20T12:09:00Z")
        self.assertEqual(result["fetch_freeze"]["lower_message_id"], 9)

    def test_full_public_fetch_blocks_old_freeze_without_lower_bound_evidence(self) -> None:
        fetch_helper = _load_fetch_helper_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "old-product-row-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "fetch_freeze": {
                            "version": "product_row_fetch_freeze_v1",
                            "sources": [
                                {
                                    "source_key": "example_source_kappa",
                                    "target_key": "example_source_kappa",
                                    "telegram_public": "example_source_kappa",
                                    "upper_message_id": 10,
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"TG_API_ID": "1", "TG_API_HASH": "hash", "TG_SESSION_STRING": "session"}):
                fetch_helper.load_telethon_dependencies = lambda: (_ for _ in ()).throw(
                    AssertionError("missing lower-bound freeze must block before Telegram access")
                )
                result = asyncio.run(
                    fetch_helper.fetch_history(
                        {
                            "telegram_target": "@example_source_kappa",
                            "source_key": "example_source_kappa",
                            "target_key": "example_source_kappa",
                            "run_id": "run-old-freeze",
                            "output_timezone": "Europe/Belgrade",
                            "months_back": 2,
                            "max_messages": 5000,
                            "llm_product_row_continuation_state_path": str(state_path),
                        }
                    )
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["http_status"], 409)
        self.assertEqual(result["error_type"], "product_row_fetch_freeze_missing_lower_bound")
        self.assertEqual(result["max_message_id"], 10)
        self.assertEqual(result["stats"]["stopped_reason"], "product_row_fetch_freeze_missing_lower_bound")
        self.assertEqual(result["posts"], [])
        self.assertEqual(result["product_row_fetch_freeze_error"]["required_lower_bound_fields"], ["cutoff_utc", "oldest_post_utc", "lower_message_id"])

    def test_fetch_build_node_uses_file_transport_not_large_stdout_payload(self) -> None:
        result = _run_node(
            "WF-FETCH-03 Build Target Jobs (v1)",
            input_payload={
                "run_id": "run-fetch-transport",
                "started_at_utc": "2026-04-24T00:00:00Z",
                "normalized_request": {
                    "requested_targets": ["@example_source_kappa"],
                    "max_messages": 125,
                    "months_back": 2,
                    "cutoff_field": "months_back",
                    "output_timezone": "Europe/Belgrade",
                    "llm_enabled": False,
                },
            },
        )
        item = result[0]["json"]

        self.assertEqual(item["fetch_transport_mode"], "n8n_allowed_json_file")
        self.assertEqual(item["fetch_result_transport_mode"], "n8n_allowed_json_file")
        self.assertIn("--input-path", item["helper_command"])
        self.assertIn("--output-path", item["helper_command"])
        self.assertNotIn("--payload-b64url", item["helper_command"])
        self.assertIn("execute_helper_wrapper.py", item["execute_command"])
        self.assertGreater(item["fetch_payload_bytes"], 0)

    def test_fetch_build_node_applies_product_row_freeze_to_full_public_jobs(self) -> None:
        result = _run_node(
            "WF-FETCH-03 Build Target Jobs (v1)",
            input_payload={
                "run_id": "run-fetch-freeze",
                "started_at_utc": "2026-04-24T00:00:00Z",
                "normalized_request": {
                    "source_mode": "payload_targets",
                    "requested_targets": ["@example_source_kappa"],
                    "max_messages": 125,
                    "since_date": "2020-01-01",
                    "cutoff_field": "since_date",
                    "output_timezone": "Europe/Belgrade",
                    "llm_enabled": True,
                    "llm_product_row_continuation_token": "state-token",
                    "llm_product_row_continuation_state": {
                        "fetch_freeze": {
                            "version": "product_row_fetch_freeze_v1",
                            "sources": [
                                {
                                    "source_key": "example_source_kappa",
                                    "target_key": "example_source_kappa",
                                    "telegram_public": "example_source_kappa",
                                    "upper_message_id": 321,
                                    "cutoff_utc": "2026-04-20T00:00:00Z",
                                    "oldest_post_utc": "2026-04-20T00:00:00Z",
                                    "lower_message_id": 123,
                                }
                            ],
                        }
                    },
                },
            },
        )
        item = result[0]["json"]

        self.assertEqual(item["helper_payload"]["max_message_id"], 321)
        self.assertEqual(item["fetch_attempt"]["max_message_id"], 321)
        self.assertEqual(item["helper_payload"]["product_row_fetch_freeze"]["upper_message_id"], 321)
        self.assertEqual(item["helper_payload"]["product_row_fetch_freeze"]["cutoff_utc"], "2026-04-20T00:00:00Z")
        self.assertEqual(item["helper_payload"]["product_row_fetch_freeze"]["lower_message_id"], 123)
        self.assertEqual(item["helper_payload"]["llm_product_row_continuation_token"], "state-token")

    def test_exact_tme_post_urls_resolve_to_distinct_exact_fetch_jobs(self) -> None:
        base_payload = {
            "run_id": "run-exact-targets",
            "started_at_utc": "2026-04-29T12:00:00Z",
            "normalized_request": {
                "source_mode": "payload_targets",
                "requested_targets": [
                    "https://t.me/example_source_alpha",
                    "https://t.me/example_source_theta/29",
                    "https://t.me/example_source_theta/21",
                    "https://t.me/example_source_theta/18",
                    "https://t.me/example_source_theta/27",
                    "https://t.me/example_source_theta/32",
                ],
                "max_messages": 5000,
                "since_date": "2020-01-01",
                "cutoff_field": "since_date",
                "output_timezone": "Europe/Belgrade",
                "llm_enabled": True,
                "llm_product_row_continuation_state": {
                    "fetch_freeze": {
                        "version": "product_row_fetch_freeze_v1",
                        "sources": [
                            {
                                "source_key": "example_source_theta",
                                "target_key": "example_source_theta",
                                "telegram_public": "example_source_theta",
                                "upper_message_id": 30,
                                "cutoff_utc": "2026-04-20T00:00:00Z",
                                "oldest_post_utc": "2026-04-20T00:00:00Z",
                                "lower_message_id": 12,
                            },
                            {
                                "source_key": "example_source_alpha",
                                "target_key": "example_source_alpha",
                                "telegram_public": "example_source_alpha",
                                "upper_message_id": 100,
                                "cutoff_utc": "2026-04-20T00:00:00Z",
                                "oldest_post_utc": "2026-04-20T00:00:00Z",
                                "lower_message_id": 44,
                            },
                        ],
                    }
                },
                "publication_targets": {"sheets": True, "db": False, "dashboard": False},
            },
        }
        resolved = _run_node(
            "WF-SHEETS-01 Resolve Targets From Payload/Sheet (v1)",
            upstream_payloads={
                "WF-SHEETS-01 Continue After Bootstrap (v1)": base_payload,
                "WF-SHEETS-01 Read Sources Config (v1)": [],
                "WF-SHEETS-01 Read Source State (v1)": [],
            },
        )[0]["json"]
        exact_targets = [
            target
            for target in resolved["normalized_request"]["resolved_targets"]
            if target["exact_message_request"]
        ]

        self.assertEqual(resolved["normalized_request"]["requested_targets_count"], 6)
        self.assertEqual([target["exact_message_id"] for target in exact_targets], [29, 21, 18, 27, 32])
        self.assertEqual(
            [target["source_key"] for target in exact_targets],
            [
                "example_source_theta_post_29",
                "example_source_theta_post_21",
                "example_source_theta_post_18",
                "example_source_theta_post_27",
                "example_source_theta_post_32",
            ],
        )

        jobs = _run_node("WF-FETCH-03 Build Target Jobs (v1)", input_payload=resolved)
        exact_jobs = [item["json"] for item in jobs if item["json"]["helper_payload"].get("exact_message_request")]

        self.assertEqual(len(jobs), 6)
        self.assertEqual([job["helper_payload"]["exact_message_ids"] for job in exact_jobs], [[29], [21], [18], [27], [32]])
        self.assertTrue(all(job["helper_payload"]["max_messages"] == 1 for job in exact_jobs))
        self.assertTrue(all("max_message_id" not in job["helper_payload"] for job in exact_jobs))
        self.assertTrue(all("since_date" not in job["helper_payload"] for job in exact_jobs))
        self.assertTrue(all(job["prior_checkpoint_message_id"] is None for job in exact_jobs))
        self.assertEqual(exact_jobs[0]["helper_payload"]["telegram_target"], "https://t.me/example_source_theta/29")

    def test_fetch_parse_node_reads_result_file_when_wrapper_stdout_is_empty(self) -> None:
        base = {
            "run_id": "run-fetch-transport",
            "started_at_utc": "2026-04-24T00:00:00Z",
            "target_input": "@example_source_kappa",
            "target_key": "example_source_kappa",
            "helper_path": "__TGSA_REPO_ROOT__/scripts/fetch/fetch_telegram_history.py",
            "helper_command": "poetry run python fetch --input-path payload.json --output-path result.json",
            "helper_payload_json": json.dumps({"telegram_target": "@example_source_kappa"}),
            "fetch_transport_mode": "n8n_allowed_json_file",
            "fetch_transport_path": "__TGSA_N8N_FILES_DIR__/payload.json",
            "fetch_result_transport_mode": "n8n_allowed_json_file",
            "fetch_result_path": "__TGSA_N8N_FILES_DIR__/result.json",
            "fetch_payload_bytes": 42,
            "execute_command": "poetry run python execute_helper_wrapper.py --launch-spec-b64url redacted",
            "execute_command_len": 72,
        }
        wrapper = {
            "helper_path": base["helper_path"],
            "helper_command": base["helper_command"],
            "input_path": base["fetch_transport_path"],
            "payload_bytes": 42,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "invocation_error": None,
        }
        helper_output = {
            "ok": True,
            "status": "success",
            "run_id": base["run_id"],
            "telegram_target_input": "@example_source_kappa",
            "target_key": "example_source_kappa",
            "output_timezone": "Europe/Belgrade",
            "stats": {"posts_emitted": 1},
            "posts": [{"message_id": 1, "text": "услуги"}],
        }

        result = _run_async_node(
            "WF-FETCH-03 Parse Helper Results (v1)",
            input_payloads=[{}],
            upstream_payloads={
                "WF-FETCH-03 Build Target Jobs (v1)": [base],
                "WF-FETCH-03 Execute Helper (v1)": [{"stdout": json.dumps(wrapper), "stderr": ""}],
            },
            binary_texts=[json.dumps(helper_output)],
        )
        parsed = result[0]["json"]

        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["posts"][0]["text"], "услуги")
        self.assertEqual(parsed["fetch_execution"]["transport_mode"], "n8n_allowed_json_file")
        self.assertEqual(parsed["fetch_execution"]["payload_path"], base["fetch_transport_path"])
        self.assertEqual(parsed["fetch_execution"]["result_path"], base["fetch_result_path"])

    def test_llm_disabled_bypass_has_no_mojibake_bom_and_executes(self) -> None:
        workflow = _load_workflow()
        js_code = _node_by_name(workflow, "WF-LLM-05 Bypass Disabled (v1)")["parameters"]["jsCode"]
        self.assertTrue(js_code.startswith("const base ="))
        self.assertNotIn("Ã¯Â»Â¿", js_code)

        result = _run_node(
            "WF-LLM-05 Bypass Disabled (v1)",
            upstream_payloads={
                "WF-LLM-05 Prepare Post-Merge Review (v1)": {
                    "run_id": "run-llm-disabled",
                    "canonical_output": {"providers": [], "offers": []},
                    "llm_stage": {"status": "pending"},
                    "run_logging": {},
                }
            },
        )
        payload = result[0]["json"]

        self.assertEqual(payload["llm_contract_status"], "extr_llm_05_v1_skipped")
        self.assertFalse(payload["llm_stage"]["helper_invoked"])


if __name__ == "__main__":
    unittest.main()
