from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse


EMOJI_DIGIT_MAP = {
    "0\ufe0f\u20e3": "0",
    "1\ufe0f\u20e3": "1",
    "2\ufe0f\u20e3": "2",
    "3\ufe0f\u20e3": "3",
    "4\ufe0f\u20e3": "4",
    "5\ufe0f\u20e3": "5",
    "6\ufe0f\u20e3": "6",
    "7\ufe0f\u20e3": "7",
    "8\ufe0f\u20e3": "8",
    "9\ufe0f\u20e3": "9",
    "\u24ea": "0",
    "\u2460": "1",
    "\u2461": "2",
    "\u2462": "3",
    "\u2463": "4",
    "\u2464": "5",
    "\u2465": "6",
    "\u2466": "7",
    "\u2467": "8",
    "\u2468": "9",
    "\u0660": "0",
    "\u0661": "1",
    "\u0662": "2",
    "\u0663": "3",
    "\u0664": "4",
    "\u0665": "5",
    "\u0666": "6",
    "\u0667": "7",
    "\u0668": "8",
    "\u0669": "9",
}

ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
WHITESPACE_RE = re.compile(r"\s+")


def replace_emoji_digits(text: str) -> str:
    result = text or ""
    for source, target in EMOJI_DIGIT_MAP.items():
        result = result.replace(source, target)
    return result


def normalize_text(text: str | None) -> str:
    result = replace_emoji_digits(text or "")
    result = ZERO_WIDTH_RE.sub("", result)
    result = result.replace("\u00a0", " ")
    result = WHITESPACE_RE.sub(" ", result)
    return result.strip()


def normalize_text_hash(text: str | None) -> str:
    normalized = normalize_text(text).lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def normalize_phone(raw: str | None) -> str:
    digits = re.sub(r"\D+", "", replace_emoji_digits(raw or ""))
    return digits if len(digits) >= 8 else ""


def normalize_handle(raw: str | None) -> str:
    value = normalize_text(raw).lower()
    if not value:
        return ""

    if value.startswith("@"):
        value = value[1:]

    if value.startswith("https://") or value.startswith("http://"):
        parsed = urlparse(value)
        value = parsed.path.strip("/")

    value = value.split("/", 1)[0]
    return value.strip(" .,:;")


def normalize_url(raw: str | None) -> str:
    value = normalize_text(raw).strip(".,);]")
    if not value:
        return ""

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value.lower()

    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def normalize_website(raw: str | None) -> str:
    value = normalize_url(raw)
    if not value:
        return ""

    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}" if host else value.lower()
