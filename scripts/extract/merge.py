from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from .fact_pack import build_offer_fact_pack
from .normalization import (
    normalize_handle,
    normalize_phone,
    normalize_text,
    normalize_url,
    normalize_website,
)


MERGE_CONTRACT_VERSION = "extr_merge_02_v1"
WORKFLOW_STAGE = "merge_deterministic"
INPUT_SHAPE = "extr_layer_01_structured_posts_v1"

STRONG_IDENTITY_PREFIXES = ("phone:", "tg:", "tg_link:", "email:", "site:")
IDENTITY_PRIORITY = {
    "phone:": 0,
    "tg:": 1,
    "tg_link:": 2,
    "email:": 3,
    "site:": 4,
    "weak_text:": 5,
}
CONTACT_ARRAY_KEYS = (
    "phones",
    "telegram_handles",
    "telegram_links",
    "instagram_handles",
    "instagram_links",
    "emails",
    "websites",
    "facebook_links",
)
TOKEN_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF]+")
SERVICE_STOPWORDS = {
    "and",
    "for",
    "from",
    "the",
    "with",
    "your",
    "telegram",
    "phone",
    "email",
    "contact",
    "price",
    "eur",
    "euro",
    "rsd",
    "din",
    "usd",
    "belgrade",
    "beograd",
    "novi",
    "sad",
    "serbia",
    "service",
    "services",
    "\u0443\u0441\u043b\u0443\u0433\u0438",
    "\u0446\u0435\u043d\u0430",
    "\u0431\u0435\u043b\u0433\u0440\u0430\u0434",
    "\u0441\u0435\u0440\u0431\u0438\u044f",
    "\u0442\u0435\u043b\u0435\u0433\u0440\u0430\u043c",
    "\u0442\u0435\u043b\u0435\u0444\u043e\u043d",
}
OFFER_SIMILARITY_THRESHOLD = 0.55
ATTACHMENT_MERGE_WINDOW_SECONDS = 5


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _stable_hash(*parts: str) -> str:
    payload = "\x1f".join(parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _parse_iso_datetime(value: str) -> datetime | None:
    normalized = _as_text(value).strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _is_strong_identity_key(identity_key: str) -> bool:
    return any(identity_key.startswith(prefix) for prefix in STRONG_IDENTITY_PREFIXES)


def _identity_sort_key(identity_key: str) -> tuple[int, str]:
    prefix = identity_key.split(":", 1)[0] + ":"
    return (IDENTITY_PRIORITY.get(prefix, 99), identity_key)


def _normalize_contact_value(contact_type: str, value: str) -> str:
    if contact_type in {"phones", "contact_snapshot_phones"}:
        return normalize_phone(value)
    if contact_type in {"telegram_handles", "instagram_handles"}:
        return normalize_handle(value)
    if contact_type in {"telegram_links", "instagram_links", "facebook_links"}:
        return normalize_url(value)
    if contact_type == "emails":
        return normalize_text(value).lower()
    if contact_type in {"websites", "contact_snapshot_websites"}:
        return normalize_website(value)
    return normalize_text(value)


def _normalize_contact_arrays(raw_contacts: Any, identity_signals: list[str]) -> dict[str, list[str]]:
    grouped = {key: set() for key in CONTACT_ARRAY_KEYS}
    if isinstance(raw_contacts, dict):
        for key in CONTACT_ARRAY_KEYS:
            values = raw_contacts.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                normalized_value = _normalize_contact_value(key, _as_text(value))
                if normalized_value:
                    grouped[key].add(normalized_value)

    for identity_key in identity_signals:
        if identity_key.startswith("phone:"):
            grouped["phones"].add(identity_key.split(":", 1)[1])
        elif identity_key.startswith("tg:"):
            grouped["telegram_handles"].add(identity_key.split(":", 1)[1])
        elif identity_key.startswith("tg_link:"):
            grouped["telegram_links"].add(identity_key.split(":", 1)[1])
        elif identity_key.startswith("email:"):
            grouped["emails"].add(identity_key.split(":", 1)[1])
        elif identity_key.startswith("site:"):
            grouped["websites"].add(identity_key.split(":", 1)[1])

    return {
        key: sorted(values)
        for key, values in grouped.items()
    }


def _normalize_explicit_contact_arrays(raw_contacts: Any) -> dict[str, list[str]]:
    grouped = {key: set() for key in CONTACT_ARRAY_KEYS}
    if not isinstance(raw_contacts, dict):
        return {key: [] for key in CONTACT_ARRAY_KEYS}

    for key in CONTACT_ARRAY_KEYS:
        values = raw_contacts.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            normalized_value = _normalize_contact_value(key, _as_text(value))
            if normalized_value:
                grouped[key].add(normalized_value)

    return {key: sorted(values) for key, values in grouped.items()}


def _normalize_identity_signals(raw_signals: Any) -> list[str]:
    signals = set()
    if not isinstance(raw_signals, list):
        return []

    for raw_signal in raw_signals:
        signal = _as_text(raw_signal).strip()
        if not signal or ":" not in signal:
            continue
        prefix, value = signal.split(":", 1)
        normalized_value = value.strip()
        if not normalized_value:
            continue

        if prefix == "phone":
            normalized_value = normalize_phone(normalized_value)
        elif prefix == "tg":
            normalized_value = normalize_handle(normalized_value)
        elif prefix == "tg_link":
            normalized_value = normalize_url(normalized_value)
        elif prefix == "email":
            normalized_value = normalize_text(normalized_value).lower()
        elif prefix == "site":
            normalized_value = normalize_website(normalized_value)
        elif prefix == "weak_text":
            normalized_value = normalize_text(normalized_value).lower()
        else:
            continue

        if normalized_value:
            signals.add(f"{prefix}:{normalized_value}")

    return sorted(signals, key=_identity_sort_key)


def _extract_category_scores(role_category_hints: Any) -> dict[str, int]:
    scores: dict[str, int] = {}
    if not isinstance(role_category_hints, list):
        return scores

    for item in role_category_hints:
        if not isinstance(item, dict):
            continue
        hint_code = _as_text(item.get("hint_code")).strip()
        if not hint_code:
            continue
        score = item.get("score")
        if not isinstance(score, int):
            score = 1
        scores[hint_code] = max(scores.get(hint_code, 0), score)

    return scores


def _build_excluded_service_tokens(post: dict[str, Any], contacts: dict[str, list[str]]) -> set[str]:
    excluded = set(SERVICE_STOPWORDS)

    for values in contacts.values():
        for value in values:
            excluded.update(TOKEN_RE.findall(normalize_text(value).lower()))

    location_signals = post.get("location_signals")
    if isinstance(location_signals, dict):
        for value in location_signals.get("matched_keywords", []):
            excluded.update(TOKEN_RE.findall(normalize_text(_as_text(value)).lower()))

    price_signals = post.get("price_signals")
    if isinstance(price_signals, dict):
        for value in price_signals.get("price_texts", []):
            excluded.update(TOKEN_RE.findall(normalize_text(_as_text(value)).lower()))

    author_signals = post.get("author_signals")
    if isinstance(author_signals, dict):
        for key in ("sender_title", "sender_username", "post_author"):
            excluded.update(TOKEN_RE.findall(normalize_text(_as_text(author_signals.get(key))).lower()))

    source_ref = post.get("source_ref")
    if isinstance(source_ref, dict):
        for key in ("chat_title", "chat_username"):
            excluded.update(TOKEN_RE.findall(normalize_text(_as_text(source_ref.get(key))).lower()))

    return excluded


def _build_service_tokens(post: dict[str, Any], contacts: dict[str, list[str]]) -> list[str]:
    text_block = post.get("text")
    text_normalized = ""
    if isinstance(text_block, dict):
        text_normalized = _as_text(text_block.get("text_normalized"))

    excluded = _build_excluded_service_tokens(post, contacts)
    tokens = []
    for token in TOKEN_RE.findall(text_normalized.lower()):
        if len(token) < 3:
            continue
        if token.isdigit():
            continue
        if token in excluded:
            continue
        tokens.append(token)

    return sorted(set(tokens))


def _post_seen_sort_key(post_ctx: dict[str, Any]) -> tuple[int, str, str]:
    posted_at_utc = post_ctx["posted_at_utc"]
    return (0 if posted_at_utc else 1, posted_at_utc, post_ctx["raw_post_id"])


def _post_seen_sort_key_desc(post_ctx: dict[str, Any]) -> tuple[int, str, str]:
    posted_at_utc = post_ctx["posted_at_utc"]
    return (1 if posted_at_utc else 0, posted_at_utc, post_ctx["raw_post_id"])


def _unique_in_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _merge_contact_arrays(post_contexts: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped = {key: set() for key in CONTACT_ARRAY_KEYS}
    for post_ctx in post_contexts:
        for key, values in post_ctx["contacts"].items():
            grouped[key].update(values)
    return {key: sorted(values) for key, values in grouped.items()}


def _merge_explicit_contact_arrays(post_contexts: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped = {key: set() for key in CONTACT_ARRAY_KEYS}
    for post_ctx in post_contexts:
        for key, values in post_ctx["explicit_contacts"].items():
            grouped[key].update(values)
    return {key: sorted(values) for key, values in grouped.items()}


def _normalize_source_public_handle(post_ctx: dict[str, Any]) -> str:
    source_ref = post_ctx.get("source_ref")
    if not isinstance(source_ref, dict):
        return ""
    return normalize_handle(source_ref.get("chat_username")) or normalize_handle(post_ctx.get("source_channel_key"))


def _has_distinct_author_identity(
    post_ctx: dict[str, Any],
    *,
    sender_username: str,
    sender_profile_url: str,
) -> bool:
    source_ref = post_ctx.get("source_ref")
    author_signals = post_ctx.get("author_signals")
    if not isinstance(source_ref, dict) or not isinstance(author_signals, dict):
        return False

    sender_id = _as_text(author_signals.get("sender_id")).strip()
    chat_id = _as_text(source_ref.get("chat_id")).strip()
    if sender_id and chat_id and sender_id != chat_id:
        return True

    source_handle = _normalize_source_public_handle(post_ctx)
    if sender_username and sender_username != source_handle:
        return True

    profile_handle = normalize_handle(sender_profile_url)
    if profile_handle and profile_handle != source_handle:
        return True

    return False


def _merge_distinct_author_contacts(post_contexts: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped = {
        "telegram_handles": set(),
        "telegram_links": set(),
        "phones": set(),
    }

    for post_ctx in post_contexts:
        author_signals = post_ctx.get("author_signals")
        if not isinstance(author_signals, dict):
            continue

        source_handle = _normalize_source_public_handle(post_ctx)
        sender_username = normalize_handle(author_signals.get("sender_username"))
        sender_profile_url = normalize_url(_as_text(author_signals.get("sender_profile_url")))
        if not _has_distinct_author_identity(
            post_ctx,
            sender_username=sender_username,
            sender_profile_url=sender_profile_url,
        ):
            continue

        if sender_username and sender_username != source_handle:
            grouped["telegram_handles"].add(sender_username)

        profile_handle = normalize_handle(sender_profile_url)
        if sender_profile_url and (not source_handle or profile_handle != source_handle):
            grouped["telegram_links"].add(sender_profile_url)

        sender_phone = normalize_phone(_as_text(author_signals.get("sender_phone")))
        if sender_phone:
            grouped["phones"].add(sender_phone)

    return {key: sorted(values) for key, values in grouped.items()}


def _aggregate_category_order(post_contexts: list[dict[str, Any]]) -> list[str]:
    score_totals: Counter[str] = Counter()
    occurrence_totals: Counter[str] = Counter()
    for post_ctx in post_contexts:
        for hint_code, score in post_ctx["category_scores"].items():
            score_totals[hint_code] += score
            occurrence_totals[hint_code] += 1

    return sorted(
        score_totals,
        key=lambda hint_code: (-score_totals[hint_code], -occurrence_totals[hint_code], hint_code),
    )


def _pick_display_name(post_contexts: list[dict[str, Any]]) -> str:
    candidates: dict[str, tuple[int, int, int]] = {}
    priority_by_field = {
        "sender_title": 0,
        "post_author": 1,
        "chat_title": 2,
    }
    for post_ctx in post_contexts:
        author_signals = post_ctx.get("author_signals", {})
        source_ref = post_ctx.get("source_ref", {})
        raw_candidates = (
            ("sender_title", _as_text(author_signals.get("sender_title"))),
            ("post_author", _as_text(author_signals.get("post_author"))),
            ("chat_title", _as_text(source_ref.get("chat_title"))),
        )
        for field_name, raw_value in raw_candidates:
            value = normalize_text(raw_value)
            if not value:
                continue
            count, priority, width = candidates.get(value, (0, priority_by_field[field_name], len(value)))
            candidates[value] = (count + 1, min(priority, priority_by_field[field_name]), max(width, len(value)))

    if not candidates:
        return ""

    return sorted(
        candidates,
        key=lambda value: (-candidates[value][0], candidates[value][1], -candidates[value][2], value.lower()),
    )[0]


def _pick_primary_contact(contacts: dict[str, list[str]]) -> tuple[str, str]:
    for contact_type, field_name in (
        ("phone", "phones"),
        ("telegram_handle", "telegram_handles"),
        ("telegram_link", "telegram_links"),
        ("email", "emails"),
        ("website", "websites"),
        ("instagram_handle", "instagram_handles"),
        ("instagram_link", "instagram_links"),
        ("facebook_link", "facebook_links"),
    ):
        values = contacts[field_name]
        if values:
            return contact_type, values[0]
    return "", ""


def _derive_provider_key(anchor_key: str, fallback_raw_post_id: str) -> str:
    if anchor_key:
        anchor_prefix = anchor_key.split(":", 1)[0]
        return f"provider:{anchor_prefix}:{_stable_hash(anchor_key)}"
    return f"provider:raw_post:{_stable_hash(fallback_raw_post_id)}"


def _derive_offer_key(provider_key: str, service_signature_key: str) -> str:
    return f"offer:{_stable_hash(provider_key, service_signature_key)}"


def _pick_provider_confidence(post_contexts: list[dict[str, Any]], identity_keys_primary: list[str]) -> str:
    strong_keys = [identity_key for identity_key in identity_keys_primary if _is_strong_identity_key(identity_key)]
    if strong_keys:
        if any(identity_key.startswith("phone:") for identity_key in strong_keys):
            return "high"
        if len(strong_keys) >= 2 or len(post_contexts) >= 2:
            return "high"
        return "medium"
    if len(post_contexts) >= 2:
        return "medium"
    return "low"


def _derive_title(text_normalized: str) -> str:
    normalized = normalize_text(text_normalized)
    if not normalized:
        return ""
    first_line = re.split(r"[.!?\n]", normalized, maxsplit=1)[0].strip(" -|")
    return first_line[:120] if first_line else normalized[:120]


def _price_sort_key(value: str) -> tuple[int, int, str]:
    digits = re.findall(r"\d+", value)
    return (-len(digits), -len(value), value)


def _pick_price_text(post_contexts: list[dict[str, Any]]) -> str:
    latest_first = sorted(post_contexts, key=_post_seen_sort_key_desc, reverse=True)
    for post_ctx in latest_first:
        price_texts = post_ctx["price_texts"]
        if price_texts:
            return sorted(price_texts, key=_price_sort_key)[0]
    return ""


def _normalize_numeric_price(value: float) -> int | float:
    if value.is_integer():
        return int(value)
    return round(value, 2)


def _parse_price_stats(post_contexts: list[dict[str, Any]]) -> tuple[int | float | None, int | float | None, str]:
    numeric_values: list[float] = []
    currency_codes: Counter[str] = Counter()
    latest_currency_code = ""

    latest_first = sorted(post_contexts, key=_post_seen_sort_key_desc, reverse=True)
    for post_ctx in latest_first:
        for currency_hint in post_ctx["currency_hints"]:
            currency_codes[currency_hint] += 1
        if not latest_currency_code and post_ctx["currency_hints"]:
            latest_currency_code = post_ctx["currency_hints"][0]

        for price_text in post_ctx["price_texts"]:
            for raw_number in re.findall(r"\d[\d\s.,]*", price_text):
                compact = raw_number.replace(" ", "")
                if compact.count(",") == 1 and compact.count(".") == 0:
                    compact = compact.replace(",", ".")
                else:
                    compact = compact.replace(",", "")
                try:
                    numeric_values.append(float(compact))
                except ValueError:
                    continue

    price_min = _normalize_numeric_price(min(numeric_values)) if numeric_values else None
    price_max = _normalize_numeric_price(max(numeric_values)) if numeric_values else None
    currency_code = latest_currency_code
    if currency_codes:
        currency_code = sorted(currency_codes, key=lambda code: (-currency_codes[code], code))[0]

    return price_min, price_max, currency_code


def _jaccard(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _is_attachment_only_post(post_ctx: dict[str, Any]) -> bool:
    return (
        not post_ctx["text_normalized"]
        and not post_ctx["category_codes"]
        and not post_ctx["service_tokens"]
        and not post_ctx["price_texts"]
        and not post_ctx["city_codes"]
    )


def _attachment_pair_score(
    attachment_post: dict[str, Any],
    offer_post: dict[str, Any],
) -> tuple[float, int] | None:
    if not attachment_post["source_channel_key"]:
        return None
    if attachment_post["source_channel_key"] != offer_post["source_channel_key"]:
        return None

    posted_at_a = attachment_post["posted_at_dt"]
    posted_at_b = offer_post["posted_at_dt"]
    if posted_at_a is None or posted_at_b is None:
        if attachment_post["posted_at_utc"] != offer_post["posted_at_utc"]:
            return None
        delta_seconds = 0.0
    else:
        delta_seconds = abs((posted_at_a - posted_at_b).total_seconds())
        if delta_seconds > ATTACHMENT_MERGE_WINDOW_SECONDS:
            return None

    return (delta_seconds, abs(attachment_post["index"] - offer_post["index"]))


def _should_merge_attachment_posts(post_ctx_a: dict[str, Any], post_ctx_b: dict[str, Any]) -> bool:
    attachment_score = _attachment_pair_score(post_ctx_a, post_ctx_b)
    return attachment_score is not None


def _should_merge_offer(post_ctx_a: dict[str, Any], post_ctx_b: dict[str, Any]) -> bool:
    if (
        post_ctx_a["text_hash"]
        and post_ctx_a["text_hash"] == post_ctx_b["text_hash"]
        and (post_ctx_a["text_normalized"] or post_ctx_b["text_normalized"])
    ):
        return True

    if _is_attachment_only_post(post_ctx_a) and _is_attachment_only_post(post_ctx_b):
        return _should_merge_attachment_posts(post_ctx_a, post_ctx_b)

    categories_a = set(post_ctx_a["category_codes"])
    categories_b = set(post_ctx_b["category_codes"])
    if categories_a and categories_b and not categories_a.intersection(categories_b):
        return False

    tokens_a = set(post_ctx_a["service_tokens"])
    tokens_b = set(post_ctx_b["service_tokens"])
    if not tokens_a or not tokens_b:
        return False

    return _jaccard(tokens_a, tokens_b) >= OFFER_SIMILARITY_THRESHOLD


class _DisjointSet:
    def __init__(self, size: int) -> None:
        self.parents = list(range(size))

    def find(self, item: int) -> int:
        parent = self.parents[item]
        if parent != item:
            self.parents[item] = self.find(parent)
        return self.parents[item]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parents[right_root] = left_root


def _build_post_context(post: dict[str, Any], index: int) -> dict[str, Any]:
    identity_signals = _normalize_identity_signals(post.get("identity_signals"))
    contacts = _normalize_contact_arrays(post.get("contacts"), identity_signals)
    explicit_contacts = _normalize_explicit_contact_arrays(post.get("contacts"))
    category_scores = _extract_category_scores(post.get("role_category_hints"))

    text_block = post.get("text")
    text_hash = ""
    text_normalized = ""
    text_raw = ""
    if isinstance(text_block, dict):
        text_hash = normalize_text(_as_text(text_block.get("text_hash_normalized"))).lower()
        text_normalized = _as_text(text_block.get("text_normalized"))
        text_raw = _as_text(text_block.get("text_raw"))

    source_ref = post.get("source_ref") if isinstance(post.get("source_ref"), dict) else {}
    author_signals = post.get("author_signals") if isinstance(post.get("author_signals"), dict) else {}
    location_signals = post.get("location_signals") if isinstance(post.get("location_signals"), dict) else {}
    price_signals = post.get("price_signals") if isinstance(post.get("price_signals"), dict) else {}

    price_texts = sorted(
        {
            normalize_text(_as_text(price_text))
            for price_text in price_signals.get("price_texts", [])
            if normalize_text(_as_text(price_text))
        }
    )
    currency_hints = sorted(
        {
            _as_text(currency_hint).lower()
            for currency_hint in price_signals.get("currency_hints", [])
            if _as_text(currency_hint).strip()
        }
    )
    city_codes = []
    city_code = _as_text(location_signals.get("city")).strip()
    if city_code:
        city_codes.append(city_code)

    strong_identity_keys = [identity_key for identity_key in identity_signals if _is_strong_identity_key(identity_key)]
    weak_identity_keys = [identity_key for identity_key in identity_signals if identity_key.startswith("weak_text:")]

    return {
        "index": index,
        "post": post,
        "raw_post_id": _as_text(post.get("raw_post_id")).strip(),
        "run_id": _as_text(post.get("run_id")).strip(),
        "source_ref": source_ref,
        "author_signals": author_signals,
        "posted_at_utc": _as_text(source_ref.get("posted_at_utc")).strip(),
        "posted_at_dt": _parse_iso_datetime(_as_text(source_ref.get("posted_at_utc")).strip()),
        "post_url": _as_text(source_ref.get("post_url")).strip(),
        "source_channel_key": _as_text(source_ref.get("source_channel_key")).strip(),
        "contacts": contacts,
        "explicit_contacts": explicit_contacts,
        "identity_signals": identity_signals,
        "strong_identity_keys": strong_identity_keys,
        "weak_identity_keys": weak_identity_keys,
        "category_scores": category_scores,
        "category_codes": sorted(category_scores, key=lambda hint_code: (-category_scores[hint_code], hint_code)),
        "city_codes": city_codes,
        "price_texts": price_texts,
        "currency_hints": currency_hints,
        "text_hash": text_hash,
        "raw_text": text_raw,
        "text_normalized": text_normalized,
        "service_tokens": _build_service_tokens(post, contacts),
    }


def _cluster_offer_posts(cluster_posts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not cluster_posts:
        return []
    if len(cluster_posts) <= 1:
        return [cluster_posts]

    disjoint_set = _DisjointSet(len(cluster_posts))
    for left_index in range(len(cluster_posts)):
        for right_index in range(left_index + 1, len(cluster_posts)):
            if _should_merge_offer(cluster_posts[left_index], cluster_posts[right_index]):
                disjoint_set.union(left_index, right_index)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, post_ctx in enumerate(cluster_posts):
        grouped[disjoint_set.find(index)].append(post_ctx)

    return [sorted(group_posts, key=_post_seen_sort_key) for group_posts in grouped.values()]


def _find_attachment_group_target(
    attachment_group: list[dict[str, Any]],
    offer_groups: list[list[dict[str, Any]]],
) -> int | None:
    best_group_index = None
    best_score: tuple[float, int] | None = None

    for group_index, offer_group in enumerate(offer_groups):
        informative_posts = [post_ctx for post_ctx in offer_group if not _is_attachment_only_post(post_ctx)]
        if not informative_posts:
            continue

        group_score: tuple[float, int] | None = None
        for attachment_post in attachment_group:
            for offer_post in informative_posts:
                candidate_score = _attachment_pair_score(attachment_post, offer_post)
                if candidate_score is None:
                    continue
                if group_score is None or candidate_score < group_score:
                    group_score = candidate_score

        if group_score is None:
            continue
        if best_score is None or group_score < best_score:
            best_score = group_score
            best_group_index = group_index

    return best_group_index


def _group_provider_clusters(post_contexts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    strong_posts = [post_ctx for post_ctx in post_contexts if post_ctx["strong_identity_keys"]]
    weak_only_posts = [post_ctx for post_ctx in post_contexts if not post_ctx["strong_identity_keys"]]

    clusters: list[list[dict[str, Any]]] = []
    if strong_posts:
        disjoint_set = _DisjointSet(len(strong_posts))
        identity_index: dict[str, int] = {}
        for index, post_ctx in enumerate(strong_posts):
            for identity_key in post_ctx["strong_identity_keys"]:
                other_index = identity_index.get(identity_key)
                if other_index is None:
                    identity_index[identity_key] = index
                    continue
                disjoint_set.union(index, other_index)

        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for index, post_ctx in enumerate(strong_posts):
            grouped[disjoint_set.find(index)].append(post_ctx)
        clusters.extend(grouped.values())

    weak_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post_ctx in weak_only_posts:
        weak_identity_key = post_ctx["weak_identity_keys"][0] if post_ctx["weak_identity_keys"] else ""
        if weak_identity_key:
            weak_groups[weak_identity_key].append(post_ctx)
            continue
        weak_groups[f"raw_post:{post_ctx['raw_post_id']}"].append(post_ctx)

    clusters.extend(weak_groups.values())
    return sorted(
        (
            sorted(cluster, key=_post_seen_sort_key)
            for cluster in clusters
        ),
        key=lambda cluster: (cluster[0]["posted_at_utc"], cluster[0]["raw_post_id"]),
    )


def _materialize_provider(cluster_posts: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    identity_strength = "strong" if any(post_ctx["strong_identity_keys"] for post_ctx in cluster_posts) else "provisional"
    if identity_strength == "strong":
        identity_keys_primary = sorted(
            {
                identity_key
                for post_ctx in cluster_posts
                for identity_key in post_ctx["strong_identity_keys"]
            },
            key=_identity_sort_key,
        )
    else:
        identity_keys_primary = sorted(
            {
                identity_key
                for post_ctx in cluster_posts
                for identity_key in post_ctx["weak_identity_keys"]
            },
            key=_identity_sort_key,
        )

    anchor_key = identity_keys_primary[0] if identity_keys_primary else ""
    earliest_post = min(cluster_posts, key=_post_seen_sort_key)
    latest_post = max(cluster_posts, key=_post_seen_sort_key_desc)
    provider_key = _derive_provider_key(anchor_key, earliest_post["raw_post_id"])
    merged_contacts = _merge_contact_arrays(cluster_posts)
    primary_contact_type, primary_contact_value = _pick_primary_contact(merged_contacts)
    evidence_raw_post_ids = _unique_in_order(
        [post_ctx["raw_post_id"] for post_ctx in sorted(cluster_posts, key=_post_seen_sort_key)]
    )
    city_codes = sorted({city_code for post_ctx in cluster_posts for city_code in post_ctx["city_codes"]})
    service_category_hints = _aggregate_category_order(cluster_posts)

    provider_candidate = {
        "provider_key": provider_key,
        "provider_state": "candidate",
        "identity_strength": identity_strength,
        "identity_keys_primary": identity_keys_primary,
        "phones": merged_contacts["phones"],
        "telegram_handles": merged_contacts["telegram_handles"],
        "telegram_links": merged_contacts["telegram_links"],
        "instagram_handles": merged_contacts["instagram_handles"],
        "instagram_links": merged_contacts["instagram_links"],
        "emails": merged_contacts["emails"],
        "websites": merged_contacts["websites"],
        "facebook_links": merged_contacts["facebook_links"],
        "first_seen_at_utc": earliest_post["posted_at_utc"],
        "last_seen_at_utc": latest_post["posted_at_utc"],
        "first_seen_run_id": earliest_post["run_id"],
        "last_seen_run_id": latest_post["run_id"],
        "evidence_raw_post_ids": evidence_raw_post_ids,
        "display_name_best": _pick_display_name(cluster_posts),
        "primary_contact_type": primary_contact_type,
        "primary_contact_value": primary_contact_value,
        "city_codes": city_codes,
        "service_category_hints": service_category_hints,
        "latest_post_url": latest_post["post_url"],
        "times_seen": len(evidence_raw_post_ids),
        "offer_count": 0,
        "dedupe_confidence": _pick_provider_confidence(cluster_posts, identity_keys_primary),
        "source_channel_keys": sorted(
            {
                post_ctx["source_channel_key"]
                for post_ctx in cluster_posts
                if post_ctx["source_channel_key"]
            }
        ),
    }

    provider_identity_edges = [
        {
            "provider_key": provider_key,
            "identity_key": identity_key,
            "key_strength": "strong" if _is_strong_identity_key(identity_key) else "weak",
            "first_seen_run_id": provider_candidate["first_seen_run_id"],
            "last_seen_run_id": provider_candidate["last_seen_run_id"],
        }
        for identity_key in identity_keys_primary
    ]

    return provider_candidate, provider_identity_edges


def _group_offer_clusters(cluster_posts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if len(cluster_posts) <= 1:
        return [cluster_posts]

    attachment_posts = [post_ctx for post_ctx in cluster_posts if _is_attachment_only_post(post_ctx)]
    informative_posts = [post_ctx for post_ctx in cluster_posts if not _is_attachment_only_post(post_ctx)]

    offer_groups = _cluster_offer_posts(informative_posts)
    for attachment_group in _cluster_offer_posts(attachment_posts):
        target_group_index = _find_attachment_group_target(attachment_group, offer_groups)
        if target_group_index is None:
            offer_groups.append(attachment_group)
            continue
        offer_groups[target_group_index].extend(attachment_group)
        offer_groups[target_group_index] = sorted(offer_groups[target_group_index], key=_post_seen_sort_key)

    return sorted(
        (
            sorted(group_posts, key=_post_seen_sort_key)
            for group_posts in offer_groups
        ),
        key=lambda group_posts: (group_posts[0]["posted_at_utc"], group_posts[0]["raw_post_id"]),
    )


def _build_service_signature_key(group_posts: list[dict[str, Any]]) -> str:
    category_codes = _aggregate_category_order(group_posts)
    token_frequency: Counter[str] = Counter()
    for post_ctx in group_posts:
        token_frequency.update(post_ctx["service_tokens"])

    common_token_threshold = max(1, len(group_posts) // 2)
    preferred_tokens = [
        token
        for token, frequency in token_frequency.items()
        if frequency >= common_token_threshold
    ]
    if not preferred_tokens:
        preferred_tokens = list(token_frequency)

    ordered_tokens = sorted(
        preferred_tokens,
        key=lambda token: (-token_frequency[token], token),
    )[:10]
    signature_seed = "|".join(category_codes + ordered_tokens)
    if not signature_seed:
        signature_seed = "|".join(post_ctx["text_hash"] for post_ctx in group_posts if post_ctx["text_hash"])
    if not signature_seed:
        signature_seed = "|".join(post_ctx["raw_post_id"] for post_ctx in group_posts)

    return f"svc:{_stable_hash(signature_seed)}"


def _pick_offer_confidence(group_posts: list[dict[str, Any]]) -> str:
    if len(group_posts) >= 2:
        if any(post_ctx["text_hash"] == group_posts[0]["text_hash"] for post_ctx in group_posts[1:]):
            return "high"
        return "medium"
    if group_posts[0]["category_codes"] or group_posts[0]["service_tokens"]:
        return "medium"
    return "low"


def _pick_best_offer_text(group_posts: list[dict[str, Any]]) -> tuple[str, str]:
    best_post = sorted(
        group_posts,
        key=lambda post_ctx: (
            -len(post_ctx["service_tokens"]),
            -len(post_ctx["text_normalized"]),
            _post_seen_sort_key(post_ctx),
        ),
    )[0]
    description_best = normalize_text(best_post["text_normalized"])
    return _derive_title(description_best), description_best


def _materialize_offer(provider_key: str, group_posts: list[dict[str, Any]]) -> dict[str, Any]:
    earliest_post = min(group_posts, key=_post_seen_sort_key)
    latest_post = max(group_posts, key=_post_seen_sort_key_desc)
    evidence_raw_post_ids = _unique_in_order(
        [post_ctx["raw_post_id"] for post_ctx in sorted(group_posts, key=_post_seen_sort_key)]
    )
    category_order = _aggregate_category_order(group_posts)
    service_signature_key = _build_service_signature_key(group_posts)
    price_text_best = _pick_price_text(group_posts)
    price_min, price_max, currency_code = _parse_price_stats(group_posts)
    contact_arrays = _merge_contact_arrays(group_posts)
    explicit_contact_arrays = _merge_explicit_contact_arrays(group_posts)
    author_fallback_contacts = _merge_distinct_author_contacts(group_posts)
    city_codes = sorted({city_code for post_ctx in group_posts for city_code in post_ctx["city_codes"]})
    token_frequency: Counter[str] = Counter()
    for post_ctx in group_posts:
        token_frequency.update(post_ctx["service_tokens"])
    service_tags = category_order + sorted(
        token_frequency,
        key=lambda token: (-token_frequency[token], token),
    )[:6]
    fact_pack = build_offer_fact_pack(
        group_posts=group_posts,
        category_order=category_order,
        merged_contacts=contact_arrays,
        explicit_contacts=explicit_contact_arrays,
        author_fallback_contacts=author_fallback_contacts,
        price_text_best=price_text_best,
        city_codes=city_codes,
        latest_post_url=latest_post["post_url"],
    )
    title_best = _as_text(fact_pack.get("title_best"))
    description_best = _as_text(fact_pack.get("description_best"))
    trimmed_service_tags = fact_pack.get("service_tags_trimmed")
    if isinstance(trimmed_service_tags, list):
        service_tags = trimmed_service_tags

    return {
        "offer_key": _derive_offer_key(provider_key, service_signature_key),
        "provider_key": provider_key,
        "offer_state": _as_text(fact_pack.get("offer_state")) or "candidate",
        "offer_rejection_reason": _as_text(fact_pack.get("offer_rejection_reason")),
        "service_signature_key": service_signature_key,
        "category_primary": _as_text(fact_pack.get("category_primary")),
        "evidence_raw_post_ids": evidence_raw_post_ids,
        "first_seen_at_utc": earliest_post["posted_at_utc"],
        "last_seen_at_utc": latest_post["posted_at_utc"],
        "first_seen_run_id": earliest_post["run_id"],
        "last_seen_run_id": latest_post["run_id"],
        "title_best": title_best,
        "description_best": description_best,
        "service_name_candidate": _as_text(fact_pack.get("service_name_candidate")),
        "details_candidate": _as_text(fact_pack.get("details_candidate")),
        "price_text_best": price_text_best,
        "price_min": price_min,
        "price_max": price_max,
        "currency_code": currency_code,
        "price_candidate_text": _as_text(fact_pack.get("price_candidate_text")),
        "city_codes": city_codes,
        "city_display_names": fact_pack.get("city_display_names") if isinstance(fact_pack.get("city_display_names"), list) else [],
        "service_tags": _unique_in_order(service_tags),
        "contact_snapshot_phones": contact_arrays["phones"],
        "contact_snapshot_telegram_handles": contact_arrays["telegram_handles"],
        "contact_snapshot_telegram_links": contact_arrays["telegram_links"],
        "contact_snapshot_emails": contact_arrays["emails"],
        "contact_snapshot_websites": contact_arrays["websites"],
        "explicit_contact_snapshot_phones": explicit_contact_arrays["phones"],
        "explicit_contact_snapshot_telegram_handles": explicit_contact_arrays["telegram_handles"],
        "explicit_contact_snapshot_telegram_links": explicit_contact_arrays["telegram_links"],
        "author_fallback_telegram_handles": author_fallback_contacts["telegram_handles"],
        "author_fallback_telegram_links": author_fallback_contacts["telegram_links"],
        "author_fallback_phones": author_fallback_contacts["phones"],
        "contact_candidate_type": _as_text(fact_pack.get("contact_candidate_type")),
        "contact_candidate_value": _as_text(fact_pack.get("contact_candidate_value")),
        "contact_candidate_display": _as_text(fact_pack.get("contact_candidate_display")),
        "latest_post_url": latest_post["post_url"],
        "source_anchor_text": _as_text(fact_pack.get("source_anchor_text")),
        "freshness_at_utc": _as_text(fact_pack.get("freshness_at_utc")) or latest_post["posted_at_utc"],
        "fact_pack_quality": _as_text(fact_pack.get("fact_pack_quality")),
        "fact_pack_flags": fact_pack.get("fact_pack_flags") if isinstance(fact_pack.get("fact_pack_flags"), list) else [],
        "times_seen": len(evidence_raw_post_ids),
        "dedupe_confidence": _pick_offer_confidence(group_posts),
        "source_channel_keys": sorted(
            {
                post_ctx["source_channel_key"]
                for post_ctx in group_posts
                if post_ctx["source_channel_key"]
            }
        ),
    }


def merge_structured_posts(extraction_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(extraction_payload, dict):
        raise ValueError("Structured post merge payload must be a JSON object.")

    structured_posts = extraction_payload.get("structured_posts")
    if not isinstance(structured_posts, list):
        raise ValueError("Structured post merge payload must include structured_posts as a list.")

    run_id = _as_text(extraction_payload.get("run_id")).strip()
    post_contexts = []
    for index, post in enumerate(structured_posts):
        if not isinstance(post, dict):
            raise ValueError(f"structured_posts[{index}] must be a JSON object.")
        post_contexts.append(_build_post_context(post, index))

    provider_clusters = _group_provider_clusters(post_contexts)
    providers = []
    offers = []
    provider_identity_keys = []
    provider_raw_post_evidence = []
    offer_raw_post_evidence = []

    for cluster_posts in provider_clusters:
        provider_candidate, provider_identity_edges = _materialize_provider(cluster_posts)
        provider_key = provider_candidate["provider_key"]
        provider_identity_keys.extend(provider_identity_edges)

        for raw_post_id in provider_candidate["evidence_raw_post_ids"]:
            provider_raw_post_evidence.append(
                {
                    "provider_key": provider_key,
                    "raw_post_id": raw_post_id,
                    "first_seen_run_id": provider_candidate["first_seen_run_id"],
                    "last_seen_run_id": provider_candidate["last_seen_run_id"],
                }
            )

        offer_clusters = _group_offer_clusters(cluster_posts)
        provider_offers = []
        for offer_posts in offer_clusters:
            offer_candidate = _materialize_offer(provider_key, offer_posts)
            provider_offers.append(offer_candidate)
            for raw_post_id in offer_candidate["evidence_raw_post_ids"]:
                offer_raw_post_evidence.append(
                    {
                        "offer_key": offer_candidate["offer_key"],
                        "raw_post_id": raw_post_id,
                        "first_seen_run_id": offer_candidate["first_seen_run_id"],
                        "last_seen_run_id": offer_candidate["last_seen_run_id"],
                    }
                )

        provider_candidate["offer_count"] = len(provider_offers)
        providers.append(provider_candidate)
        offers.extend(provider_offers)

    providers = sorted(providers, key=lambda provider: provider["provider_key"])
    offers = sorted(offers, key=lambda offer: (offer["provider_key"], offer["offer_key"]))
    provider_identity_keys = sorted(
        provider_identity_keys,
        key=lambda edge: (edge["provider_key"], edge["identity_key"]),
    )
    provider_raw_post_evidence = sorted(
        provider_raw_post_evidence,
        key=lambda edge: (edge["provider_key"], edge["raw_post_id"]),
    )
    offer_raw_post_evidence = sorted(
        offer_raw_post_evidence,
        key=lambda edge: (edge["offer_key"], edge["raw_post_id"]),
    )

    merge_summary = {
        "input_shape": INPUT_SHAPE,
        "workflow_stage": WORKFLOW_STAGE,
        "provider_identity_keys_total": len(provider_identity_keys),
        "provider_raw_post_evidence_total": len(provider_raw_post_evidence),
        "offer_raw_post_evidence_total": len(offer_raw_post_evidence),
        "strong_providers_total": sum(1 for provider in providers if provider["identity_strength"] == "strong"),
        "provisional_providers_total": sum(
            1 for provider in providers if provider["identity_strength"] == "provisional"
        ),
        "same_provider_merges_total": len(post_contexts) - len(providers),
        "same_offer_merges_total": len(post_contexts) - len(offers),
        "warnings": [],
    }

    effective_run_id = run_id or next(
        (post_ctx["run_id"] for post_ctx in post_contexts if post_ctx["run_id"]),
        "",
    )

    return {
        "run_id": effective_run_id,
        "workflow_stage": WORKFLOW_STAGE,
        "merge_contract_version": MERGE_CONTRACT_VERSION,
        "structured_posts_total": len(structured_posts),
        "providers_total": len(providers),
        "offers_total": len(offers),
        "providers": providers,
        "offers": offers,
        "provider_identity_keys": provider_identity_keys,
        "provider_raw_post_evidence": provider_raw_post_evidence,
        "offer_raw_post_evidence": offer_raw_post_evidence,
        "merge_summary": merge_summary,
    }
