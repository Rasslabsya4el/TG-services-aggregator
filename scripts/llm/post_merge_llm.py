from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from llm.post_merge import (
        DEFAULT_MODEL,
        PROCESSOR_VERSION,
        WORKFLOW_STAGE,
        compact_json,
        process_post_merge_payload,
        validate_stage_schemas,
    )
else:
    from .post_merge import (
        DEFAULT_MODEL,
        PROCESSOR_VERSION,
        WORKFLOW_STAGE,
        compact_json,
        process_post_merge_payload,
        validate_stage_schemas,
    )


def _load_payload(input_path: str | None) -> dict[str, Any]:
    if input_path:
        return json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    return json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))


def _write_output(text: str, output_path: str | None = None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return

    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


def _empty_stage_breakdown() -> dict[str, dict[str, int]]:
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
            "safe_non_visible_drops": 0,
            "recovered_low_confidence_publishes": 0,
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
            "safe_non_visible_drops": 0,
            "recovered_low_confidence_publishes": 0,
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
            "safe_non_visible_drops": 0,
            "recovered_low_confidence_publishes": 0,
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
            "safe_non_visible_drops": 0,
            "recovered_low_confidence_publishes": 0,
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
            "safe_non_visible_drops": 0,
            "recovered_low_confidence_publishes": 0,
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
            "safe_non_visible_drops": 0,
            "recovered_low_confidence_publishes": 0,
        },
    }


def _empty_product_row_coverage() -> dict[str, Any]:
    return {
        "candidate_total": 0,
        "attempts": 0,
        "successful_decisions": 0,
        "failures": 0,
        "skips": 0,
        "max_output_retries": 0,
        "hard_drops": 0,
        "safe_non_visible_drops": 0,
        "recovered_low_confidence_publishes": 0,
        "coverage_complete": True,
        "fallback_publication_blocked": True,
    }


def _empty_budget() -> dict[str, Any]:
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
        "last_outcome": "not_evaluated",
    }


def _build_fallback_canonical_output(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    merge_output = source.get("merge_output") if isinstance(source.get("merge_output"), dict) else {}
    providers = merge_output.get("providers") if isinstance(merge_output.get("providers"), list) else []
    offers = merge_output.get("offers") if isinstance(merge_output.get("offers"), list) else []
    merge_summary = merge_output.get("merge_summary") if isinstance(merge_output.get("merge_summary"), dict) else {}
    run_id = str(source.get("run_id") or "")
    return {
        "run_id": run_id,
        "workflow_stage": WORKFLOW_STAGE,
        "llm_contract_version": PROCESSOR_VERSION,
        "providers_total": len(providers),
        "offers_total": len(offers),
        "providers": providers,
        "offers": offers,
        "merge_summary": merge_summary,
    }


def _build_bootstrap_error_result(
    payload: dict[str, Any] | None,
    *,
    error_type: str,
    error_message: str,
    traceback_excerpt: str,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    run_id = str(source.get("run_id") or "")
    normalized_request = source.get("normalized_request") if isinstance(source.get("normalized_request"), dict) else {}
    canonical_output = _build_fallback_canonical_output(source)
    reason = f"{error_type}: {error_message}".strip()[:240]
    response_excerpt = traceback_excerpt[:4000]
    return {
        "run_id": run_id,
        "workflow_stage": WORKFLOW_STAGE,
        "llm_contract_version": PROCESSOR_VERSION,
        "llm_enabled": bool(normalized_request.get("llm_enabled", False)),
        "helper_mode": "responses_api",
        "canonical_output": canonical_output,
        "audit_enrichment_rows": [
            {
                "audit_row_id": f"audit:{run_id or 'unknown'}:llm_helper_bootstrap:1",
                "run_id": run_id,
                "stage": "llm_helper_bootstrap",
                "entity_type": "workflow",
                "entity_id": "llm_post_merge",
                "processor_type": "llm",
                "processor_version": PROCESSOR_VERSION,
                "status": "error",
                "decision_code": error_type,
                "attempt_number": 1,
                "input_fingerprint": "",
                "output_patch_json": "{}",
                "reason_text": reason,
                "source_raw_post_ids": [],
                "model_name": str(source.get("model_name") or DEFAULT_MODEL),
                "prompt_version": "llm_helper_bootstrap",
                "latency_ms": None,
                "tokens_input": 0,
                "tokens_output": 0,
                "cost_estimate_usd": 0.0,
                "confidence": None,
                "response_excerpt": response_excerpt,
                "review_required": True,
                "upstream_audit_row_id": "",
            }
        ],
        "llm_stage": {
            "status": "error",
            "reason": reason,
            "processor_version": PROCESSOR_VERSION,
            "helper_mode": "responses_api",
            "model_name": str(source.get("model_name") or DEFAULT_MODEL),
            "calls_attempted": 0,
            "calls_skipped": 0,
            "accepted_patches_total": 0,
            "audit_only_patches_total": 1,
            "review_required_count": 1,
            "tokens_input_total": 0,
            "tokens_output_total": 0,
            "cost_estimate_usd": 0,
            "budget": _empty_budget(),
            "stage_breakdown": _empty_stage_breakdown(),
            "product_row_coverage": _empty_product_row_coverage(),
            "accepted_patches": [],
            "audit_only_patches": [
                {
                    "stage": "llm_helper_bootstrap",
                    "entity_type": "workflow",
                    "entity_id": "llm_post_merge",
                    "status": "error",
                    "decision_code": error_type,
                    "patch": {},
                    "reason_text": reason,
                }
            ],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the repo-owned post-merge LLM layer over deterministic provider/offer candidates."
    )
    parser.add_argument(
        "--input-path",
        help="Path to a JSON file that contains the post-merge payload. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--mock-response-path",
        help="Optional local JSON file with mock structured responses for narrow helper repro.",
    )
    parser.add_argument(
        "--output-path",
        help="Optional path to write the helper JSON instead of stdout.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print indented UTF-8 JSON instead of ASCII-safe compact JSON.",
    )
    parser.add_argument(
        "--total-timeout-seconds",
        type=float,
        help="Optional total wall-clock budget for the post-merge LLM helper. Zero aborts before the next candidate.",
    )
    parser.add_argument(
        "--validate-schemas-only",
        action="store_true",
        help="Validate repo-owned strict Structured Outputs schemas and exit without processing a payload.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.validate_schemas_only:
        result = {
            "status": "ok",
            "validated_schemas": validate_stage_schemas(),
        }
        _write_output(compact_json(result, pretty=args.pretty), args.output_path)
        return 0

    payload: dict[str, Any] | None = None
    try:
        payload = _load_payload(args.input_path)
        result = process_post_merge_payload(
            payload,
            mock_response_path=args.mock_response_path,
            pretty=args.pretty,
            total_timeout_seconds=args.total_timeout_seconds,
        )
    except Exception as exc:
        result = _build_bootstrap_error_result(
            payload,
            error_type="llm_helper_process_bootstrap_failed",
            error_message=f"{exc.__class__.__name__}: {exc}",
            traceback_excerpt="".join(traceback.format_exception(exc)).strip(),
        )
    _write_output(compact_json(result, pretty=args.pretty), args.output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
