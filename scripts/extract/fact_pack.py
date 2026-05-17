from __future__ import annotations

import re
from typing import Any

from .normalization import normalize_handle, normalize_phone, normalize_text, normalize_url


TITLE_CHAR_LIMIT = 120
DETAILS_CHAR_LIMIT = 280
MAX_DETAIL_LINES = 3

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
TG_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{4,}")
HASHTAG_ONLY_RE = re.compile(r"^(?:#[^\s#]+\s*)+$")
ONLY_SYMBOLS_RE = re.compile(r"^[\W_]+$", re.UNICODE)
LEADING_SYMBOL_RE = re.compile(r"^[^\w@#]+", re.UNICODE)
TRAILING_SYMBOL_RE = re.compile(r"[\s|,:;/-]+$", re.UNICODE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")

CITY_DISPLAY_NAMES = {
    "belgrade": "Belgrade",
    "novi_sad": "Novi Sad",
    "nis": "Nis",
    "subotica": "Subotica",
}

SECTION_LABEL_PREFIXES = (
    "requirements",
    "responsibilities",
    "contact",
    "contacts",
    "our advantages",
    "why choose",
    "\u043e\u0431\u044f\u0437\u0430\u043d\u043d\u043e\u0441\u0442\u0438",
    "\u0442\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f",
    "\u043d\u0430\u0448\u0438 \u043f\u0440\u0435\u0438\u043c\u0443\u0449\u0435\u0441\u0442\u0432\u0430",
    "\u043f\u043e\u0447\u0435\u043c\u0443 \u0441\u0442\u043e\u0438\u0442",
    "\u043e \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u0438",
)

GREETING_PREFIXES = (
    "\u0432\u0441\u0435\u043c \u043f\u0440\u0438\u0432\u0435\u0442",
    "\u043f\u0440\u0438\u0432\u0435\u0442",
    "\u0437\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435",
    "\u0434\u043e\u0431\u0440\u044b\u0439 \u0434\u0435\u043d\u044c",
    "\u0434\u043e\u0431\u0440\u043e\u0433\u043e \u0434\u043d\u044f",
    "hello",
    "hi",
)

CONTACT_LINE_HINTS = (
    "telegram",
    "whatsapp",
    "viber",
    "instagram",
    "contact",
    "contacts",
    "\u043f\u0438\u0448\u0438\u0442\u0435",
    "\u0437\u0432\u043e\u043d\u0438\u0442\u0435",
    "\u043f\u043e \u0432\u043e\u043f\u0440\u043e\u0441\u0430\u043c",
    "\u043a\u043e\u043d\u0442\u0430\u043a\u0442",
)

SOURCE_PROMO_PHRASES = (
    "official portal",
    "official channel",
    "download the app",
    "download the mobile app",
    "marketplace",
    "areasell",
    "\u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u043e\u0440\u0442\u0430\u043b",
    "\u0442\u0433-\u043a\u0430\u043d\u0430\u043b",
    "\u0441\u043a\u0430\u0447\u0430\u0442\u044c \u043c\u043e\u0431\u0438\u043b\u044c\u043d\u043e\u0435 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435",
    "\u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0443 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0439",
    "\u0440\u0430\u0437\u043c\u0435\u0449\u0430\u0439\u0442\u0435 \u0432\u0430\u0448\u0438 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u044f",
)

VACANCY_KEYWORDS = {
    "vacancy",
    "job",
    "hiring",
    "position",
    "salary",
    "employment",
    "company",
    "responsibilities",
    "requirements",
    "resume",
    "fulltime",
    "full-time",
    "\u0432\u0430\u043a\u0430\u043d\u0441\u0438\u044f",
    "\u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438",
    "\u0440\u0430\u0431\u043e\u0442\u0430",
    "\u0438\u0449\u0443",
    "\u0438\u0449\u0435\u043c",
    "\u0437\u0430\u0440\u043f\u043b\u0430\u0442\u0430",
    "\u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f",
    "\u043e\u0431\u044f\u0437\u0430\u043d\u043d\u043e\u0441\u0442\u0438",
    "\u0442\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f",
    "\u0440\u0435\u0437\u044e\u043c\u0435",
}

VACANCY_PHRASES = (
    "looking for",
    "office-based",
    "full-time",
    "what we expect",
    "\u043a\u043e\u0433\u043e \u0438\u0449\u0435\u043c",
    "\u043c\u044b \u043e\u0436\u0438\u0434\u0430\u0435\u043c",
    "\u043e\u0442\u043a\u043b\u0438\u043a\u043d\u0443\u0442\u044c\u0441\u044f \u043d\u0430 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u044e",
    "\u0437\u0430\u0434\u0430\u0447\u0438",
)

RESALE_KEYWORDS = {
    "sell",
    "sale",
    "buy",
    "\u043f\u0440\u043e\u0434\u0430\u043c",
    "\u043f\u0440\u043e\u0434\u0430\u044e",
    "\u043f\u0440\u043e\u0434\u0430\u0435\u0442\u0441\u044f",
    "\u043a\u0443\u043f\u043b\u044e",
    "\u043e\u0431\u043c\u0435\u043d",
}

HARDWARE_KEYWORDS = {
    "iphone",
    "ipad",
    "macbook",
    "samsung",
    "xiaomi",
    "ps5",
    "playstation",
    "nintendo",
    "gpu",
    "cpu",
    "intel",
    "amd",
    "ssd",
    "gb",
    "tb",
    "ram",
    "hz",
    "\u0430\u0439\u0444\u043e\u043d",
    "\u043d\u043e\u0443\u0442\u0431\u0443\u043a",
    "\u0432\u0438\u0434\u0435\u043e\u043a\u0430\u0440\u0442\u0430",
    "\u043f\u0430\u043c\u044f\u0442\u044c",
    "\u043e\u0437\u0443",
}

PLATFORM_AD_PHRASES = (
    "all for life in serbia",
    "platform of listings",
    "download the mobile app",
    "official portal",
    "\u0432\u0441\u0451 \u0434\u043b\u044f \u0436\u0438\u0437\u043d\u0438 \u0432 \u0441\u0435\u0440\u0431\u0438\u0438",
    "\u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0430 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0439",
    "\u0441\u043a\u0430\u0447\u0430\u0442\u044c \u043c\u043e\u0431\u0438\u043b\u044c\u043d\u043e\u0435 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435",
    "\u0440\u0430\u0437\u043c\u0435\u0449\u0430\u0439\u0442\u0435 \u0432\u0430\u0448\u0438 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u044f",
)


def _word_tokens(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text)]


def _count_word_hits(words: list[str], keywords: set[str]) -> int:
    return sum(1 for word in words if word in keywords)


def _count_phrase_hits(text_lower: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for phrase in phrases if phrase in text_lower)


def _format_phone_display(value: str) -> str:
    digits = normalize_phone(value)
    return f"+{digits}" if digits else ""


def _format_contact_display(contact_type: str, contact_value: str) -> str:
    if not contact_value:
        return ""
    if contact_type == "phone":
        return _format_phone_display(contact_value) or contact_value
    if contact_type == "telegram_handle":
        return f"@{normalize_handle(contact_value)}"
    if contact_type == "telegram_link":
        return normalize_url(contact_value)
    return contact_value


def _city_display_names(city_codes: list[str]) -> list[str]:
    return [
        CITY_DISPLAY_NAMES.get(city_code, city_code.replace("_", " ").title())
        for city_code in city_codes
        if city_code
    ]


def _emoji_count(text: str) -> int:
    return len(EMOJI_RE.findall(text))


def _is_greeting_line(line_lower: str) -> bool:
    for greeting in GREETING_PREFIXES:
        if not line_lower.startswith(greeting):
            continue
        suffix = line_lower[len(greeting):len(greeting) + 1]
        if suffix in {"", " ", "!", ",", ".", ":"}:
            return True
    return False


def _rewrite_intro_line(line: str) -> tuple[str, bool]:
    normalized = normalize_text(line)
    lower = normalized.lower()
    changed = False

    if _is_greeting_line(lower):
        normalized = normalize_text(normalized.split(" ", 1)[1] if " " in normalized else "")
        lower = normalized.lower()
        changed = True

    if lower.startswith("\u043c\u0435\u043d\u044f \u0437\u043e\u0432\u0443\u0442 "):
        split_match = re.search(r"[,.:;-]\s*", normalized)
        normalized = normalized[split_match.end():] if split_match else ""
        lower = normalized.lower()
        changed = True

    if lower.startswith("\u044f "):
        normalized = normalize_text(normalized[2:])
        changed = True
    elif lower.startswith("\u043c\u044b "):
        normalized = normalize_text(normalized[3:])
        changed = True

    return normalized, changed


def _looks_like_brand_line(line: str) -> bool:
    words = _word_tokens(line)
    if not words or len(words) > 4:
        return False
    alpha_words = [word for word in words if any(char.isalpha() for char in word)]
    if not alpha_words:
        return False
    return all(word.upper() == word for word in alpha_words if len(word) > 1)


def _looks_like_contact_line(line: str) -> bool:
    line_lower = line.lower()
    contact_hint_hits = sum(1 for hint in CONTACT_LINE_HINTS if hint in line_lower)
    has_contact_value = bool(PHONE_RE.search(line) or URL_RE.search(line) or TG_HANDLE_RE.search(line))
    words = _word_tokens(line)
    return has_contact_value and (contact_hint_hits >= 1 or len(words) <= 6)


def _looks_like_source_promo(line_lower: str) -> bool:
    return any(phrase in line_lower for phrase in SOURCE_PROMO_PHRASES)


def _looks_like_section_label(line_lower: str, words: list[str]) -> bool:
    return len(words) <= 5 and any(line_lower.startswith(prefix) for prefix in SECTION_LABEL_PREFIXES)


def _looks_like_noise_line(line: str) -> bool:
    normalized = normalize_text(line)
    if not normalized:
        return True

    line_lower = normalized.lower()
    words = _word_tokens(normalized)
    if HASHTAG_ONLY_RE.fullmatch(normalized):
        return True
    if ONLY_SYMBOLS_RE.fullmatch(normalized):
        return True
    if _looks_like_section_label(line_lower, words):
        return True
    if _looks_like_contact_line(normalized):
        return True
    if _looks_like_source_promo(line_lower):
        return True
    if _looks_like_brand_line(normalized):
        return True
    return len(words) < 2 and _emoji_count(normalized) > 0


def _clean_line(raw_line: str) -> str:
    normalized = normalize_text(raw_line)
    normalized = LEADING_SYMBOL_RE.sub("", normalized)
    normalized = TRAILING_SYMBOL_RE.sub("", normalized)
    return normalize_text(normalized)


def _split_text_lines(raw_text: str) -> list[str]:
    expanded: list[str] = []
    primary_parts = re.split(r"(?:\r?\n)+", raw_text or "")
    for part in primary_parts:
        for chunk in re.split(r"\s*[•▪▫◦●]\s*", part):
            cleaned = _clean_line(chunk)
            if cleaned:
                expanded.append(cleaned)
    if len(expanded) <= 1:
        expanded = [
            _clean_line(chunk)
            for chunk in re.split(r"(?<=[.!?])\s+", raw_text or "")
            if _clean_line(chunk)
        ]
    return expanded


def _compress_text(value: str, limit: int) -> str:
    text = normalize_text(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rstrip()
    split_index = max(clipped.rfind(marker) for marker in ("; ", ", ", ". ", " "))
    if split_index >= max(24, limit // 3):
        clipped = clipped[:split_index].rstrip(" ,;.")
    return clipped


def _pick_text_source(group_posts: list[dict[str, Any]]) -> str:
    ordered = sorted(
        group_posts,
        key=lambda post_ctx: (
            -len(normalize_text(post_ctx.get("raw_text") or "")),
            -len(normalize_text(post_ctx.get("text_normalized") or "")),
            post_ctx.get("posted_at_utc") or "",
        ),
    )
    for post_ctx in ordered:
        raw_text = normalize_text(post_ctx.get("raw_text") or "")
        if raw_text:
            return post_ctx.get("raw_text") or ""
        text_normalized = normalize_text(post_ctx.get("text_normalized") or "")
        if text_normalized:
            return text_normalized
    return ""


def _build_candidate_lines(raw_text: str) -> tuple[list[str], list[str]]:
    candidate_lines: list[str] = []
    observed_flags: list[str] = []
    seen: set[str] = set()
    had_greeting = False
    had_self_intro = False

    for raw_line in _split_text_lines(raw_text):
        normalized = normalize_text(raw_line)
        if not normalized:
            continue

        line_lower = normalized.lower()
        if _is_greeting_line(line_lower):
            had_greeting = True
            continue

        rewritten, intro_changed = _rewrite_intro_line(normalized)
        if intro_changed and rewritten:
            had_self_intro = True
        normalized = rewritten or normalized
        if not normalized:
            continue
        if _looks_like_noise_line(normalized):
            continue

        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidate_lines.append(normalized)

    if had_greeting:
        observed_flags.append("greeting_filtered")
    if had_self_intro:
        observed_flags.append("self_intro_filtered")
    if _emoji_count(raw_text) >= 8:
        observed_flags.append("emoji_noise_compacted")
    return candidate_lines, observed_flags


def _classify_non_service(
    *,
    raw_text: str,
    source_text: str,
) -> list[str]:
    combined_text = normalize_text(" ".join(part for part in (raw_text, source_text) if part))
    text_lower = combined_text.lower()
    words = _word_tokens(combined_text)
    flags: list[str] = []

    vacancy_score = _count_word_hits(words, VACANCY_KEYWORDS) + _count_phrase_hits(text_lower, VACANCY_PHRASES)
    if vacancy_score >= 4:
        flags.append("vacancy")

    resale_score = _count_word_hits(words, RESALE_KEYWORDS)
    hardware_score = _count_word_hits(words, HARDWARE_KEYWORDS)
    if resale_score >= 1 and hardware_score >= 2:
        flags.append("resale")

    platform_score = _count_phrase_hits(text_lower, PLATFORM_AD_PHRASES)
    if platform_score >= 2:
        flags.append("platform_ad")

    return flags


def _build_source_anchor_text(latest_post: dict[str, Any], latest_post_url: str) -> str:
    source_ref = latest_post.get("source_ref") if isinstance(latest_post.get("source_ref"), dict) else {}
    chat_username = normalize_handle(source_ref.get("chat_username"))
    chat_title = normalize_text(source_ref.get("chat_title"))
    message_id = source_ref.get("message_id")
    url_match = re.search(r"https?://t\.me/([^/?#]+)/(\d+)", latest_post_url or "", re.IGNORECASE)
    if url_match:
        return f"@{normalize_handle(url_match.group(1))}/{url_match.group(2)}"
    if chat_username and message_id:
        return f"@{chat_username}/{message_id}"
    if chat_title and message_id:
        return f"{chat_title} / {message_id}"
    return latest_post_url


def build_offer_fact_pack(
    *,
    group_posts: list[dict[str, Any]],
    category_order: list[str],
    merged_contacts: dict[str, list[str]],
    explicit_contacts: dict[str, list[str]] | None = None,
    author_fallback_contacts: dict[str, list[str]] | None = None,
    price_text_best: str,
    city_codes: list[str],
    latest_post_url: str,
) -> dict[str, Any]:
    latest_post = max(
        group_posts,
        key=lambda post_ctx: (post_ctx.get("posted_at_utc") or "", post_ctx.get("raw_post_id") or ""),
    )
    raw_text = _pick_text_source(group_posts)
    source_text = " ".join(
        normalize_text(value)
        for value in (
            latest_post.get("source_ref", {}).get("chat_title") if isinstance(latest_post.get("source_ref"), dict) else "",
            latest_post.get("author_signals", {}).get("sender_title") if isinstance(latest_post.get("author_signals"), dict) else "",
        )
        if normalize_text(value)
    )
    non_service_flags = _classify_non_service(raw_text=raw_text, source_text=source_text)
    candidate_lines, cleanup_flags = _build_candidate_lines(raw_text)

    contact_type = ""
    contact_value = ""
    explicit_contacts = explicit_contacts or {}
    author_fallback_contacts = author_fallback_contacts or {}
    for candidate_type, field_name in (
        ("phone", "phones"),
        ("telegram_handle", "telegram_handles"),
        ("telegram_link", "telegram_links"),
        ("email", "emails"),
        ("website", "websites"),
    ):
        values = explicit_contacts.get(field_name) or []
        if values:
            contact_type = candidate_type
            contact_value = values[0]
            break
    if not contact_value:
        for candidate_type, field_name in (
            ("telegram_handle", "telegram_handles"),
            ("telegram_link", "telegram_links"),
            ("phone", "phones"),
        ):
            values = author_fallback_contacts.get(field_name) or []
            if values:
                contact_type = candidate_type
                contact_value = values[0]
                break
    title_best = ""
    description_best = ""
    quality_state = "clean"
    offer_state = "candidate"
    offer_rejection_reason = ""
    category_primary = category_order[0] if category_order else ""
    service_tags_trimmed: list[str] | None = None

    if non_service_flags:
        quality_state = "rejected_non_service"
        offer_state = "rejected"
        offer_rejection_reason = f"non_service_{non_service_flags[0]}"
        category_primary = ""
        service_tags_trimmed = []
    else:
        title_best = _compress_text(candidate_lines[0], TITLE_CHAR_LIMIT) if candidate_lines else ""
        detail_lines = [
            line
            for line in candidate_lines[1:]
            if line.lower() != title_best.lower()
        ][:MAX_DETAIL_LINES]
        if detail_lines:
            description_best = _compress_text("; ".join(detail_lines), DETAILS_CHAR_LIMIT)
        elif title_best:
            description_best = title_best

        if raw_text and len(normalize_text(raw_text)) > len(title_best) + len(description_best) + 120:
            cleanup_flags.append("ad_dump_compacted")

        if not title_best and not description_best:
            quality_state = "weak_signal"
            if not price_text_best and not city_codes and not category_order:
                quality_state = "suppressed_empty_offer"
                offer_state = "suppressed"
                offer_rejection_reason = "empty_offer"
                cleanup_flags.append("empty_offer")

    return {
        "title_best": title_best,
        "description_best": description_best,
        "service_name_candidate": title_best,
        "details_candidate": description_best,
        "contact_candidate_type": contact_type,
        "contact_candidate_value": contact_value,
        "contact_candidate_display": _format_contact_display(contact_type, contact_value),
        "price_candidate_text": price_text_best,
        "city_display_names": _city_display_names(city_codes),
        "source_anchor_text": _build_source_anchor_text(latest_post, latest_post_url),
        "freshness_at_utc": latest_post.get("posted_at_utc") or "",
        "fact_pack_quality": quality_state,
        "fact_pack_flags": sorted(set([*non_service_flags, *cleanup_flags])),
        "offer_state": offer_state,
        "offer_rejection_reason": offer_rejection_reason,
        "category_primary": category_primary,
        "service_tags_trimmed": service_tags_trimmed,
    }
