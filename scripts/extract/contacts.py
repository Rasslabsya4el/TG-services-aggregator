from __future__ import annotations

import re
from dataclasses import dataclass

from .normalization import (
    normalize_handle,
    normalize_phone,
    normalize_text,
    normalize_url,
    normalize_website,
)


PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s\-()]{7,}\d)")
EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
TG_LINK_RE = re.compile(r"https?://t\.me/[A-Za-z0-9_+/]+", re.I)
TG_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{4,}")
SITE_RE = re.compile(r"https?://[^\s<>()]+", re.I)

HEURISTIC_PHONE_MARKERS = (
    "tel",
    "тел",
    "phone",
    "telefon",
    "telefon:",
    "mob",
    "wa",
    "viber",
    "whatsapp",
)
HEURISTIC_TG_MARKERS = ("telegram", "tg", "телеграм", "телега", "t.me")

SUMMARY_KEYS = {
    "phone": "phones",
    "email": "emails",
    "telegram_handle": "telegram_handles",
    "telegram_link": "telegram_links",
    "website": "websites",
}
EXCLUDED_WEBSITE_HINTS = ("t.me/", "instagram.com/", "facebook.com/", "wa.me/")


@dataclass(frozen=True)
class ContactMatch:
    contact_type: str
    value: str
    value_raw: str
    extractor: str

    def as_dict(self) -> dict[str, str]:
        return {
            "contact_type": self.contact_type,
            "value": self.value,
            "value_raw": self.value_raw,
            "extractor": self.extractor,
        }


@dataclass
class ContactExtractionResult:
    matches: list[ContactMatch]

    def summary(self) -> dict[str, list[str]]:
        grouped = {name: [] for name in SUMMARY_KEYS.values()}
        for match in self.matches:
            key = SUMMARY_KEYS[match.contact_type]
            grouped[key].append(match.value)

        return {
            key: sorted(set(values))
            for key, values in grouped.items()
        }


def _add_match(
    index: dict[tuple[str, str], ContactMatch],
    *,
    contact_type: str,
    value: str,
    value_raw: str,
    extractor: str,
) -> None:
    normalized_value = value.strip()
    if not normalized_value:
        return

    key = (contact_type, normalized_value)
    if key not in index:
        index[key] = ContactMatch(
            contact_type=contact_type,
            value=normalized_value,
            value_raw=normalize_text(value_raw),
            extractor=extractor,
        )


def _capture_after_markers(
    text: str,
    markers: tuple[str, ...],
    value_pattern: str,
) -> set[str]:
    matches: set[str] = set()
    text_norm = normalize_text(text)
    for marker in markers:
        pattern = re.compile(rf"{re.escape(marker)}[:\s\-]*({value_pattern})", re.I)
        for match in pattern.finditer(text_norm):
            matches.add(match.group(1).strip())
    return matches


def _extract_regex_contacts(
    text: str,
    *,
    extractor: str,
    index: dict[tuple[str, str], ContactMatch],
) -> None:
    for match in PHONE_RE.finditer(text):
        _add_match(
            index,
            contact_type="phone",
            value=normalize_phone(match.group(0)),
            value_raw=match.group(0),
            extractor=extractor,
        )

    for match in EMAIL_RE.finditer(text):
        _add_match(
            index,
            contact_type="email",
            value=match.group(0).lower(),
            value_raw=match.group(0),
            extractor=extractor,
        )

    for match in TG_LINK_RE.finditer(text):
        _add_match(
            index,
            contact_type="telegram_link",
            value=normalize_url(match.group(0)),
            value_raw=match.group(0),
            extractor=extractor,
        )

    for match in TG_HANDLE_RE.finditer(text):
        _add_match(
            index,
            contact_type="telegram_handle",
            value=normalize_handle(match.group(0)),
            value_raw=match.group(0),
            extractor=extractor,
        )

    for match in SITE_RE.finditer(text):
        raw_value = match.group(0)
        normalized_url = normalize_url(raw_value)
        if any(hint in normalized_url.lower() for hint in EXCLUDED_WEBSITE_HINTS):
            continue
        _add_match(
            index,
            contact_type="website",
            value=normalize_website(raw_value),
            value_raw=raw_value,
            extractor=extractor,
        )


def _extract_marker_contacts(
    text: str,
    *,
    extractor: str,
    index: dict[tuple[str, str], ContactMatch],
) -> None:
    text_norm = normalize_text(text)

    phone_candidates = _capture_after_markers(
        text_norm,
        HEURISTIC_PHONE_MARKERS,
        r"[\d\+\-\s()]{8,}",
    )
    for candidate in phone_candidates:
        _add_match(
            index,
            contact_type="phone",
            value=normalize_phone(candidate),
            value_raw=candidate,
            extractor=extractor,
        )

    telegram_candidates = _capture_after_markers(
        text_norm,
        HEURISTIC_TG_MARKERS,
        r"(?:@[A-Za-z0-9_]{4,}|https?://t\.me/[A-Za-z0-9_+/]+|[A-Za-z0-9_]{4,})",
    )
    for candidate in telegram_candidates:
        if "t.me/" in candidate.lower():
            _add_match(
                index,
                contact_type="telegram_link",
                value=normalize_url(candidate),
                value_raw=candidate,
                extractor=extractor,
            )
            continue

        _add_match(
            index,
            contact_type="telegram_handle",
            value=normalize_handle(candidate),
            value_raw=candidate,
            extractor=extractor,
        )


def extract_contacts(text: str | None) -> ContactExtractionResult:
    raw_text = text or ""
    normalized_text = normalize_text(raw_text)
    index: dict[tuple[str, str], ContactMatch] = {}

    _extract_regex_contacts(raw_text, extractor="regex_base", index=index)
    if normalized_text and normalized_text != raw_text:
        _extract_regex_contacts(normalized_text, extractor="regex_normalized", index=index)
    _extract_marker_contacts(raw_text, extractor="marker_recovery", index=index)

    matches = sorted(
        index.values(),
        key=lambda match: (match.contact_type, match.value),
    )
    return ContactExtractionResult(matches=matches)
