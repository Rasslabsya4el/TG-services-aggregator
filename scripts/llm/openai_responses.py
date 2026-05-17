from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "https://api.openai.com/v1"
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class TransportResponse:
    payload: dict[str, Any]
    latency_ms: int
    request_id: str


class ResponseTransportError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        response_body: str = "",
        request_id: str = "",
        usage: dict[str, int] | None = None,
        error_type: str = "",
        error_code: str = "",
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.response_body = response_body
        self.request_id = request_id
        self.usage = usage
        self.error_type = error_type
        self.error_code = error_code


def _elapsed_latency_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _normalize_base_url(base_url: str | None) -> str:
    value = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not value.endswith("/v1"):
        value = f"{value}/v1"
    return value


def _extract_error_details(payload_text: str) -> dict[str, str]:
    if not payload_text.strip():
        return {}
    try:
        parsed = json.loads(payload_text)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}
    error = parsed.get("error")
    if not isinstance(error, dict):
        return {}
    details: dict[str, str] = {}
    for key in ("message", "type", "code"):
        value = error.get(key)
        if isinstance(value, str) and value:
            details[key] = value
    return details


def _extract_error_message(payload_text: str) -> str:
    return _extract_error_details(payload_text).get("message", "")


def _build_timeout_message(exc: BaseException) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    return f"OpenAI Responses API transport timeout: {detail}"


def create_response(
    *,
    api_key: str,
    body: dict[str, Any],
    base_url: str | None = None,
    timeout_seconds: float = 60.0,
    organization: str | None = None,
    project: str | None = None,
) -> TransportResponse:
    endpoint = f"{_normalize_base_url(base_url)}/responses"
    payload_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if organization:
        headers["OpenAI-Organization"] = organization
    if project:
        headers["OpenAI-Project"] = project

    request = urllib.request.Request(
        endpoint,
        data=payload_bytes,
        headers=headers,
        method="POST",
    )

    started_at = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            request_id = response.headers.get("x-request-id", "")
            try:
                raw_body = response.read().decode("utf-8")
            except TimeoutError as exc:
                raise ResponseTransportError(
                    _build_timeout_message(exc),
                    retryable=True,
                    request_id=request_id,
                ) from exc
            latency_ms = _elapsed_latency_ms(started_at)
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise ResponseTransportError(
                    "OpenAI Responses API returned invalid JSON.",
                    retryable=True,
                    response_body=raw_body[:4000],
                    request_id=request_id,
                ) from exc
            if not isinstance(payload, dict):
                raise ResponseTransportError(
                    "OpenAI Responses API returned a non-object payload.",
                    retryable=True,
                    response_body=raw_body[:4000],
                    request_id=request_id,
                )
            return TransportResponse(
                payload=payload,
                latency_ms=latency_ms,
                request_id=request_id,
            )
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        status_code = getattr(exc, "code", None)
        request_id = exc.headers.get("x-request-id", "") if getattr(exc, "headers", None) else ""
        error_details = _extract_error_details(raw_body)
        error_message = error_details.get("message", "")
        message = error_message or f"OpenAI Responses API returned HTTP {status_code or 'error'}."
        raise ResponseTransportError(
            message,
            retryable=bool(status_code in RETRYABLE_STATUS_CODES),
            status_code=status_code,
            response_body=raw_body[:4000],
            request_id=request_id,
            error_type=error_details.get("type", ""),
            error_code=error_details.get("code", ""),
        ) from exc
    except TimeoutError as exc:
        raise ResponseTransportError(
            _build_timeout_message(exc),
            retryable=True,
        ) from exc
    except urllib.error.URLError as exc:
        raise ResponseTransportError(
            f"OpenAI Responses API transport error: {exc.reason}",
            retryable=True,
        ) from exc
