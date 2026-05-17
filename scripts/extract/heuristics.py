from __future__ import annotations

import re
from typing import Any

from .normalization import normalize_text


PRICE_RE = re.compile(
    r"(?:"
    r"\u20ac\s*\d[\d\s.,]*"
    r"|\$\s*\d[\d\s.,]*"
    r"|\d[\d\s.,]*\s*(?:\u20ac|\$|eur|euro|rsd|din|usd|dinar|\u0434\u0438\u043d|\u0435\u0432\u0440\u043e)"
    r"|\b(?:\u0446\u0435\u043d\u0430|\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c|price)\b[:\s]*\d[\d\s.,]*(?:\s*(?:\u20ac|\$|eur|euro|rsd|din|usd|dinar|\u0434\u0438\u043d|\u0435\u0432\u0440\u043e))?"
    r"|\b(?:from|\u043e\u0442)\b[:\s]*\d[\d\s.,]*\s*(?:\u20ac|\$|eur|euro|rsd|din|usd|dinar|\u0434\u0438\u043d|\u0435\u0432\u0440\u043e)"
    r"|\d{1,3}%"
    r")",
    re.I,
)

PRICE_LINE_MARKERS = (
    "\u0446\u0435\u043d\u0430",
    "\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c",
    "price",
)

ROLE_RULES: dict[str, tuple[str, ...]] = {
    "beauty_hair": (
        "\u0431\u0430\u0440\u0431\u0435\u0440",
        "\u043f\u0430\u0440\u0438\u043a\u043c\u0430\u0445",
        "hair",
        "\u0441\u0442\u0440\u0438\u0436",
        "\u043e\u043a\u0440\u0430\u0448",
        "\u0431\u043e\u0440\u043e\u0434",
    ),
    "beauty_cosmetology": (
        "\u043a\u043e\u0441\u043c\u0435\u0442",
        "\u044d\u043f\u0438\u043b\u044f",
        "\u043c\u0430\u0441\u0441\u0430\u0436",
        "massage",
        "lash",
        "brow",
        "spa",
    ),
    "psychology": (
        "\u043f\u0441\u0438\u0445\u043e\u043b\u043e\u0433",
        "\u043f\u0441\u0438\u0445\u043e\u0442\u0435\u0440\u0430\u043f",
        "therapy",
        "\u0442\u0435\u0440\u0430\u043f\u0435\u0432\u0442",
        "\u043a\u043e\u0443\u0447",
    ),
    "education_tutoring": (
        "\u0440\u0435\u043f\u0435\u0442",
        "\u0443\u0440\u043e\u043a",
        "\u043e\u0431\u0443\u0447",
        "\u043f\u0440\u0435\u043f\u043e\u0434\u0430",
        "teacher",
        "\u043a\u0443\u0440\u0441",
        "\u0430\u043d\u0433\u043b\u0438\u0439",
        "\u0441\u0435\u0440\u0431\u0441\u043a",
    ),
    "construction_repair": (
        "\u0440\u0435\u043c\u043e\u043d\u0442",
        "\u0441\u0442\u0440\u043e\u0438\u0442",
        "\u0441\u0430\u043d\u0442\u0435\u0445",
        "\u044d\u043b\u0435\u043a\u0442\u0440\u0438\u043a",
        "\u043c\u0430\u043b\u044f\u0440",
        "\u043f\u043b\u0438\u0442\u043a",
        "roof",
    ),
    "cleaning": (
        "\u043a\u043b\u0438\u043d\u0438\u043d\u0433",
        "\u0443\u0431\u043e\u0440\u043a",
        "\u0445\u0438\u043c\u0447\u0438\u0441\u0442",
        "\u0447\u0438\u0441\u0442\u043a",
        "cleaning",
    ),
    "moving_delivery": (
        "\u0433\u0440\u0443\u0437\u043e\u043f\u0435\u0440\u0435\u0432",
        "\u043f\u0435\u0440\u0435\u0435\u0437\u0434",
        "\u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0430",
        "\u043a\u0443\u0440\u044c\u0435\u0440",
        "delivery",
        "transport",
        "transfer",
        "\u0432\u043e\u0434\u0438\u0442\u0435\u043b",
    ),
    "auto_service": (
        "\u0430\u0432\u0442\u043e",
        "\u0430\u0432\u0442\u043e\u043c\u043e\u0431",
        "\u0448\u0438\u043d\u043e\u043c\u043e\u043d\u0442\u0430\u0436",
        "car rent",
        "\u0430\u0440\u0435\u043d\u0434\u0430 \u0430\u0432\u0442\u043e",
        "\u043f\u043e\u043b\u0438\u0440\u043e\u0432\u043a",
    ),
    "legal_docs": (
        "\u044e\u0440\u0438\u0441\u0442",
        "\u0430\u0434\u0432\u043e\u043a\u0430\u0442",
        "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442",
        "legal",
        "\u0432\u043d\u0436",
        "\u0431\u0443\u0445\u0433\u0430\u043b\u0442\u0435\u0440",
        "\u043d\u0430\u043b\u043e\u0433",
    ),
    "real_estate": (
        "\u0430\u0440\u0435\u043d\u0434\u0430",
        "\u043a\u0432\u0430\u0440\u0442\u0438\u0440\u0430",
        "\u0441\u0442\u0443\u0434\u0438\u044f",
        "\u0430\u043f\u0430\u0440\u0442\u0430\u043c\u0435\u043d\u0442",
        "rent",
        "\u043d\u0435\u0434\u0432\u0438\u0436",
    ),
    "events_entertainment": (
        "\u0442\u0430\u043d\u0446\u043e\u0432",
        "go-go",
        "\u0432\u0435\u0434\u0443\u0449",
        "\u0430\u043d\u0438\u043c\u0430\u0442\u043e\u0440",
        "event",
        "\u043f\u0440\u0430\u0437\u0434\u043d\u0438\u043a",
    ),
    "food_hospitality": (
        "\u043f\u043e\u0432\u0430\u0440",
        "\u043a\u0443\u0445\u043d",
        "\u0441\u0443\u0448\u0438",
        "\u0440\u0435\u0441\u0442\u043e\u0440\u0430\u043d",
        "\u0431\u0430\u0440",
        "\u043a\u0430\u0444\u0435",
        "bistro",
    ),
    "it_digital": (
        "\u0442\u0430\u0440\u0433\u0435\u0442",
        "smm",
        "\u0434\u0438\u0437\u0430\u0439\u043d",
        "\u0441\u0430\u0439\u0442",
        "\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442",
        "\u043c\u0430\u0440\u043a\u0435\u0442\u0438\u043d\u0433",
        "frontend",
        "backend",
    ),
    "pets": (
        "\u0441\u043e\u0431\u0430\u043a",
        "\u043a\u043e\u0448\u043a",
        "\u0432\u0435\u0442\u0435\u0440\u0438\u043d",
        "\u0433\u0440\u0443\u043c",
        "pet",
    ),
}

ROLE_NEGATIVE_RULES: dict[str, tuple[str, ...]] = {
    "beauty_cosmetology": ("\u043a\u043e\u0441\u043c\u0435\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0440\u0435\u043c\u043e\u043d\u0442", "cosmetic repair"),
    "it_digital": ("\u0434\u0438\u0437\u0430\u0439\u043d\u0435\u0440\u0441\u043a\u0438\u0439 \u0440\u0435\u043c\u043e\u043d\u0442",),
    "auto_service": ("\u0430\u0432\u0442\u043e\u043f\u0430\u0440\u043a",),
}

CITY_KEYWORDS = {
    "belgrade": ("\u0431\u0435\u043b\u0433\u0440\u0430\u0434", "belgrade", "beograd"),
    "novi_sad": ("\u043d\u043e\u0432\u0438 \u0441\u0430\u0434", "novi sad"),
    "nis": ("\u043d\u0438\u0448", "ni\u0161", "nis"),
    "subotica": ("\u0441\u0443\u0431\u043e\u0442\u0438\u0446\u0430", "subotica"),
}


def _score_roles(text: str) -> list[dict[str, Any]]:
    text_norm = normalize_text(text).lower()
    scored: list[dict[str, Any]] = []

    for hint_code, keywords in ROLE_RULES.items():
        matched_keywords = sorted({keyword for keyword in keywords if keyword in text_norm})
        if not matched_keywords:
            continue

        negative_keywords = [
            keyword
            for keyword in ROLE_NEGATIVE_RULES.get(hint_code, ())
            if keyword in text_norm
        ]
        score = len(matched_keywords) - len(negative_keywords)
        if score <= 0:
            continue

        if score >= 3:
            confidence = "high"
        elif score == 2:
            confidence = "medium"
        else:
            confidence = "low"

        scored.append(
            {
                "hint_code": hint_code,
                "score": score,
                "matched_keywords": matched_keywords,
                "confidence": confidence,
            }
        )

    return scored


def extract_role_category_hints(text: str | None) -> list[dict[str, Any]]:
    raw_text = text or ""
    scored = _score_roles(raw_text)
    if not scored:
        hashtags = re.findall(r"#([A-Za-z\u0400-\u04FF\u0451\u04010-9_]{3,})", normalize_text(raw_text))
        if hashtags:
            scored = _score_roles(" ".join(sorted({tag.lower() for tag in hashtags})))

    if not scored:
        return []

    max_score = max(item["score"] for item in scored)
    if max_score >= 2:
        scored = [
            item
            for item in scored
            if item["score"] >= max_score - 1 and item["score"] >= 2
        ]

    return sorted(scored, key=lambda item: (-item["score"], item["hint_code"]))


def extract_city_signal(text: str | None) -> dict[str, Any]:
    text_norm = normalize_text(text).lower()
    for city_code, keywords in CITY_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword in text_norm]
        if matched:
            return {
                "city": city_code,
                "matched_keywords": matched,
            }

    return {
        "city": None,
        "matched_keywords": [],
    }


def extract_price_signals(text: str | None) -> dict[str, Any]:
    normalized = normalize_text(text)
    matches = sorted({match.group(0).strip() for match in PRICE_RE.finditer(normalized)})

    if not matches:
        for raw_line in re.split(r"[\r\n|]+", text or ""):
            line = normalize_text(raw_line)
            if not line:
                continue

            line_lower = line.lower()
            if any(marker in line_lower for marker in PRICE_LINE_MARKERS) and re.search(r"\d", line):
                matches.append(line[:80])

    currency_hints = []
    joined = " ".join(matches).lower()
    if "\u20ac" in joined or "eur" in joined or "euro" in joined or "\u0435\u0432\u0440\u043e" in joined:
        currency_hints.append("eur")
    if "rsd" in joined or "din" in joined or "dinar" in joined or "\u0434\u0438\u043d" in joined:
        currency_hints.append("rsd")
    if "$" in joined or "usd" in joined:
        currency_hints.append("usd")

    return {
        "price_texts": sorted(set(matches)),
        "currency_hints": sorted(set(currency_hints)),
        "price_min": None,
        "price_max": None,
    }
