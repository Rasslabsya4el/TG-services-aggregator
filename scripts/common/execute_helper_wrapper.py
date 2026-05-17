import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def compact_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, separators=(",", ":"))


def decode_b64url_json(value: str) -> dict[str, Any]:
    padding = "=" * (-len(value) % 4)
    raw = base64.urlsafe_b64decode(value + padding)
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Launch spec must decode to a JSON object.")
    return parsed


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_args(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Launch spec helper_args must be an array.")
    return [str(entry) for entry in value]


def normalize_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Launch spec metadata must be an object.")
    return value


def resolve_repo_root(value: Any) -> Path | None:
    repo_root = normalize_text(value)
    if not repo_root:
        return None

    path = Path(repo_root)
    if not path.exists():
        raise FileNotFoundError(f"Repo root was not found: {repo_root}")
    if not path.is_dir():
        raise NotADirectoryError(f"Repo root is not a directory: {repo_root}")
    return path


def payload_bytes_for(spec: dict[str, Any]) -> int | None:
    raw_value = spec.get("payload_bytes")
    if raw_value is not None:
        try:
            return int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Launch spec payload_bytes must be numeric.") from exc

    payload_path = normalize_text(spec.get("payload_path"))
    if not payload_path:
        return None
    return Path(payload_path).stat().st_size


def normalize_timeout_seconds(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Launch spec timeout_seconds must be numeric.") from exc
    if timeout_seconds < 0:
        raise ValueError("Launch spec timeout_seconds must be non-negative.")
    return timeout_seconds


def extract_output_path(spec: dict[str, Any], helper_args: list[str]) -> str:
    explicit_path = normalize_text(spec.get("output_path") or spec.get("result_path"))
    if explicit_path:
        return explicit_path
    for index, arg in enumerate(helper_args):
        if arg == "--output-path" and index + 1 < len(helper_args):
            return helper_args[index + 1]
    return ""


def read_payload_object(path_text: str) -> dict[str, Any]:
    if not path_text:
        return {}
    try:
        parsed = json.loads(Path(path_text).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def empty_stage_breakdown() -> dict[str, dict[str, int]]:
    return {
        "llm_service_relevance": {
            "eligible_entities": 0,
            "vendor_attempts": 0,
            "skipped": 0,
            "accepted_patches": 0,
            "audit_only_patches": 0,
            "errors": 0,
            "max_output_retries": 0,
            "coverage_failures": 0,
            "coverage_hard_drops": 0,
        },
        "llm_serbia_relevance": {
            "eligible_entities": 0,
            "vendor_attempts": 0,
            "skipped": 0,
            "accepted_patches": 0,
            "audit_only_patches": 0,
            "errors": 0,
            "max_output_retries": 0,
            "coverage_failures": 0,
            "coverage_hard_drops": 0,
        },
        "llm_product_row_shape": {
            "eligible_entities": 0,
            "vendor_attempts": 0,
            "skipped": 0,
            "accepted_patches": 0,
            "audit_only_patches": 0,
            "errors": 0,
            "max_output_retries": 0,
            "coverage_failures": 0,
            "coverage_hard_drops": 0,
        },
        "llm_category_refine": {
            "eligible_entities": 0,
            "vendor_attempts": 0,
            "skipped": 0,
            "accepted_patches": 0,
            "audit_only_patches": 0,
            "errors": 0,
            "max_output_retries": 0,
            "coverage_failures": 0,
            "coverage_hard_drops": 0,
        },
        "llm_provider_merge_review": {
            "eligible_entities": 0,
            "vendor_attempts": 0,
            "skipped": 0,
            "accepted_patches": 0,
            "audit_only_patches": 0,
            "errors": 0,
            "max_output_retries": 0,
            "coverage_failures": 0,
            "coverage_hard_drops": 0,
        },
        "llm_offer_dedupe_review": {
            "eligible_entities": 0,
            "vendor_attempts": 0,
            "skipped": 0,
            "accepted_patches": 0,
            "audit_only_patches": 0,
            "errors": 0,
            "max_output_retries": 0,
            "coverage_failures": 0,
            "coverage_hard_drops": 0,
        },
    }


def empty_budget() -> dict[str, Any]:
    return {
        "soft_warning_calls": 25,
        "hard_stop_calls": 50,
        "soft_warning_cost_usd": 0.25,
        "hard_stop_cost_usd": 1.0,
        "calls_attempted": 0,
        "calls_skipped": 0,
        "tokens_input_total": 0,
        "tokens_output_total": 0,
        "cost_estimate_usd": 0,
        "soft_warning_triggered": False,
        "hard_stop_triggered": False,
        "last_outcome": "llm_total_timeout",
    }


def fallback_canonical_output(payload: dict[str, Any]) -> dict[str, Any]:
    merge_output = payload.get("merge_output") if isinstance(payload.get("merge_output"), dict) else {}
    providers = merge_output.get("providers") if isinstance(merge_output.get("providers"), list) else []
    offers = merge_output.get("offers") if isinstance(merge_output.get("offers"), list) else []
    return {
        "run_id": normalize_text(payload.get("run_id")),
        "workflow_stage": "llm_post_merge",
        "llm_contract_version": "extr_llm_05_v1",
        "providers_total": len(providers),
        "offers_total": len(offers),
        "providers": providers,
        "offers": offers,
        "merge_summary": merge_output.get("merge_summary") if isinstance(merge_output.get("merge_summary"), dict) else {},
    }


def build_post_merge_llm_timeout_artifact(
    *,
    spec: dict[str, Any],
    wrapper: dict[str, Any],
    timeout_seconds: float,
    elapsed_seconds: float,
    output_path: str,
    payload_path: str,
) -> dict[str, Any]:
    payload = read_payload_object(payload_path)
    run_id = normalize_text(payload.get("run_id"))
    canonical_output = fallback_canonical_output(payload)
    progress = {
        "status": "timeout",
        "reason": "llm_total_timeout",
        "current_stage": "wrapper_wait",
        "current_candidate_index": 0,
        "current_candidate_total": 0,
        "current_entity_type": "",
        "current_entity_id": "",
        "completed_candidates_total": 0,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "total_timeout_seconds": timeout_seconds,
        "wrapper_timeout": True,
    }
    product_row_coverage = {
        "candidate_total": 0,
        "attempts": 0,
        "successful_decisions": 0,
        "failures": 0,
        "skips": 0,
        "max_output_retries": 0,
        "hard_drops": 0,
        "coverage_complete": False,
        "fallback_publication_blocked": True,
        "incomplete_reason": "llm_total_timeout",
    }
    timeout_message = (
        f"LLM helper exceeded total timeout after {round(elapsed_seconds, 3)}s "
        f"(budget {timeout_seconds}s)."
    )
    return {
        "run_id": run_id,
        "workflow_stage": "llm_post_merge",
        "llm_contract_version": "extr_llm_05_v1",
        "llm_enabled": True,
        "helper_mode": "responses_api",
        "canonical_output": canonical_output,
        "audit_enrichment_rows": [
            {
                "audit_row_id": f"audit:{run_id or 'unknown'}:llm_total_timeout:wrapper",
                "run_id": run_id,
                "stage": "llm_total_timeout",
                "entity_type": "workflow",
                "entity_id": "llm_post_merge",
                "processor_type": "deterministic",
                "processor_version": "extr_llm_05_v1",
                "status": "error",
                "decision_code": "llm_total_timeout",
                "attempt_number": 0,
                "input_fingerprint": "",
                "output_patch_json": "{}",
                "reason_text": timeout_message[:240],
                "source_raw_post_ids": [],
                "model_name": "gpt-5-mini-2025-08-07",
                "prompt_version": "llm_total_timeout",
                "latency_ms": None,
                "tokens_input": 0,
                "tokens_output": 0,
                "cost_estimate_usd": 0.0,
                "confidence": None,
                "response_excerpt": normalize_text(wrapper.get("stderr"))[:240],
                "review_required": True,
                "upstream_audit_row_id": "",
            }
        ],
        "llm_stage": {
            "status": "error",
            "reason": "llm_total_timeout",
            "processor_version": "extr_llm_05_v1",
            "helper_mode": "responses_api",
            "helper_path": normalize_text(wrapper.get("helper_path")),
            "helper_invoked": True,
            "calls_attempted": 0,
            "calls_skipped": 0,
            "accepted_patches_total": 0,
            "audit_only_patches_total": 1,
            "review_required_count": 1,
            "tokens_input_total": 0,
            "tokens_output_total": 0,
            "cost_estimate_usd": 0,
            "budget": empty_budget(),
            "stage_breakdown": empty_stage_breakdown(),
            "product_row_coverage": product_row_coverage,
            "progress": progress,
            "accepted_patches": [],
            "audit_only_patches": [
                {
                    "stage": "llm_total_timeout",
                    "entity_type": "workflow",
                    "entity_id": "llm_post_merge",
                    "status": "error",
                    "decision_code": "llm_total_timeout",
                    "patch": {},
                    "reason_text": timeout_message[:240],
                }
            ],
            "model_name": normalize_text(spec.get("model_name")) or "gpt-5-mini-2025-08-07",
            "timeout_seconds": timeout_seconds,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "result_path": output_path,
        },
    }


def materialize_timeout_artifact(
    *,
    spec: dict[str, Any],
    wrapper: dict[str, Any],
    timeout_seconds: float,
    elapsed_seconds: float,
    output_path: str,
    payload_path: str,
) -> None:
    if normalize_text(spec.get("timeout_artifact")) != "post_merge_llm":
        return
    if not output_path:
        return
    artifact = build_post_merge_llm_timeout_artifact(
        spec=spec,
        wrapper=wrapper,
        timeout_seconds=timeout_seconds,
        elapsed_seconds=elapsed_seconds,
        output_path=output_path,
        payload_path=payload_path,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compact_json(artifact) + "\n", encoding="utf-8")


def build_command_display(
    helper_path: str,
    helper_args: list[str],
    helper_command: str,
    repo_root: Path | None,
) -> str:
    if helper_command:
        return helper_command
    quoted_args = " ".join(json.dumps(arg) for arg in helper_args)
    if repo_root is not None:
        quoted_repo_root = json.dumps(str(repo_root))
        return (
            f"poetry --directory {quoted_repo_root} run python {json.dumps(helper_path)}"
            f'{(" " + quoted_args) if quoted_args else ""}'
        )
    return f'python "{helper_path}"{(" " + quoted_args) if quoted_args else ""}'


def cleanup_path(path_text: str) -> None:
    if not path_text:
        return

    path = Path(path_text)
    if not path.exists():
        return

    if path.is_dir():
        return

    path.unlink(missing_ok=True)


def run_launch_spec(spec: dict[str, Any]) -> dict[str, Any]:
    helper_path = normalize_text(spec.get("helper_path"))
    helper_args = normalize_args(spec.get("helper_args"))
    metadata = normalize_metadata(spec.get("metadata"))
    repo_root = resolve_repo_root(spec.get("repo_root"))
    cleanup_target = normalize_text(spec.get("cleanup_path"))
    payload_path = normalize_text(spec.get("payload_path"))
    output_path = extract_output_path(spec, helper_args)
    timeout_seconds = normalize_timeout_seconds(spec.get("timeout_seconds"))
    helper_command = normalize_text(spec.get("helper_command"))
    invocation_exit_code = spec.get("invocation_exit_code", 9000)
    timeout_exit_code = spec.get("timeout_exit_code", 124)

    try:
        invocation_exit_code = int(invocation_exit_code)
    except (TypeError, ValueError) as exc:
        raise ValueError("Launch spec invocation_exit_code must be numeric.") from exc
    try:
        timeout_exit_code = int(timeout_exit_code)
    except (TypeError, ValueError) as exc:
        raise ValueError("Launch spec timeout_exit_code must be numeric.") from exc

    if not helper_path:
        raise ValueError("Launch spec is missing helper_path.")

    wrapper: dict[str, Any] = {
        **metadata,
        "helper_path": helper_path,
        "helper_command": build_command_display(helper_path, helper_args, helper_command, repo_root),
        "exit_code": 0,
        "invocation_error": None,
        "stdout": "",
        "stderr": "",
    }

    if payload_path:
        wrapper["input_path"] = payload_path
    if output_path:
        wrapper["output_path"] = output_path
    if timeout_seconds is not None:
        wrapper["timeout_seconds"] = timeout_seconds
    if repo_root is not None:
        wrapper["repo_root"] = str(repo_root)
        wrapper["working_directory"] = str(repo_root)

    payload_bytes = payload_bytes_for(spec)
    if payload_bytes is not None:
        wrapper["payload_bytes"] = int(payload_bytes)

    try:
        helper_file = Path(helper_path)
        if not helper_file.exists():
            raise FileNotFoundError(f"Helper path was not found: {helper_path}")

        if payload_path and not Path(payload_path).exists():
            raise FileNotFoundError("Input payload file was not found.")

        started = time.monotonic()
        try:
            completed = subprocess.run(
                [sys.executable, helper_path, *helper_args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                cwd=str(repo_root) if repo_root is not None else None,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_seconds = time.monotonic() - started
            wrapper["exit_code"] = timeout_exit_code
            wrapper["invocation_error"] = "llm_total_timeout"
            wrapper["timed_out"] = True
            wrapper["elapsed_seconds"] = round(elapsed_seconds, 3)
            wrapper["stdout"] = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
            wrapper["stderr"] = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
            materialize_timeout_artifact(
                spec=spec,
                wrapper=wrapper,
                timeout_seconds=float(timeout_seconds or 0),
                elapsed_seconds=elapsed_seconds,
                output_path=output_path,
                payload_path=payload_path,
            )
            return wrapper
        wrapper["exit_code"] = int(completed.returncode)
        wrapper["stdout"] = completed.stdout.strip()
        wrapper["stderr"] = completed.stderr.strip()
    except Exception as exc:
        wrapper["exit_code"] = invocation_exit_code
        wrapper["invocation_error"] = str(exc)
    finally:
        cleanup_path(cleanup_target)

    return wrapper


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a repo-owned helper and emit one stable JSON wrapper for n8n Execute Command."
    )
    parser.add_argument("--launch-spec-b64url", required=True, help="Base64url-encoded helper launch spec JSON")
    args = parser.parse_args()

    try:
        launch_spec = decode_b64url_json(args.launch_spec_b64url)
        wrapper = run_launch_spec(launch_spec)
    except Exception as exc:
        wrapper = {
            "helper_path": normalize_text(None),
            "helper_command": "",
            "exit_code": 9099,
            "invocation_error": str(exc),
            "stdout": "",
            "stderr": "",
        }

    print(compact_json(wrapper))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
