from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

try:
    from .openai_responses import ResponseTransportError, TransportResponse, create_response
except ImportError:
    from openai_responses import ResponseTransportError, TransportResponse, create_response  # type: ignore

try:
    from extract.normalization import normalize_handle, normalize_phone, normalize_text, normalize_url  # type: ignore
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from extract.normalization import normalize_handle, normalize_phone, normalize_text, normalize_url  # type: ignore
    except ImportError:
        from scripts.extract.normalization import normalize_handle, normalize_phone, normalize_text, normalize_url  # type: ignore


PROCESSOR_VERSION = "extr_llm_05_v1"
WORKFLOW_STAGE = "llm_post_merge"
DEFAULT_MODEL = "gpt-5-mini-2025-08-07"
RESPONSE_MAX_OUTPUT_TOKENS = 900
PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS = 1800
PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKEN_STAIRCASE = (1800, 3600, 7200, 12000)
CATEGORY_REFINE_RESPONSE_MAX_OUTPUT_TOKENS = 1800
PRODUCT_ROW_LOW_CONFIDENCE_RECOVERY_FLOOR = 0.70
PRODUCT_ROW_STRUCTURED_LOW_CONFIDENCE_RECOVERY_FLOOR = 0.65
MIN_TEXT_SIGNAL_CHARS = 18
MIN_TEXT_SIGNAL_TOKENS = 3

SOFT_WARNING_CALLS = 25
HARD_STOP_CALLS = 50
SOFT_WARNING_COST_USD = 0.25
HARD_STOP_COST_USD = 1.00
DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS = 30 * 60
DEFAULT_PRODUCT_ROW_MAX_CANDIDATES_PER_RUN = 500
PRODUCT_ROW_CHUNK_STATE_VERSION = "llm_product_row_chunk_state_v1"
PRODUCT_ROW_FETCH_FREEZE_VERSION = "product_row_fetch_freeze_v1"
LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON = "llm_product_row_quota_blocked"
PRODUCT_ROW_QUOTA_RETRY_CONTRACT = "wait_for_quota_restoration_then_resume_same_continuation_state_or_start_fresh_state"
PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_FRACTION = 0.10
PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_MIN_SECONDS = 30.0
PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_MAX_SECONDS = 180.0

INPUT_TOKEN_PRICE_USD = 0.25 / 1_000_000
OUTPUT_TOKEN_PRICE_USD = 2.00 / 1_000_000

EVIDENCE_LIMIT = 3
EXCERPT_CHAR_LIMIT = 700
OFFER_SUMMARY_CHAR_LIMIT = 280
PROVIDER_SUMMARY_CHAR_LIMIT = 280
CANONICAL_NAME_CHAR_LIMIT = 120

LLM_STAGES = (
    "llm_service_relevance",
    "llm_serbia_relevance",
    "llm_product_row_shape",
    "llm_category_refine",
    "llm_provider_merge_review",
    "llm_offer_dedupe_review",
)

PROMPT_VERSIONS = {
    "llm_service_relevance": "post_merge_llm_v1_service_relevance",
    "llm_serbia_relevance": "post_merge_llm_v1_serbia_relevance",
    "llm_product_row_shape": "post_merge_llm_v2_product_row_writer",
    "llm_category_refine_offer": "post_merge_llm_v1_category_offer",
    "llm_category_refine_provider": "post_merge_llm_v1_category_provider",
    "llm_provider_merge_review": "post_merge_llm_v1_provider_merge_review",
    "llm_offer_dedupe_review": "post_merge_llm_v1_offer_dedupe_review",
}

TOKEN_RE = re.compile(r"[0-9A-Za-z\u0400-\u04FF]+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
HANDLE_RE = re.compile(r"(?<![\w/])@[A-Za-z0-9_]{3,}")
URL_EXTRACT_RE = re.compile(r"(?:https?://|www\.)[^\s|;]+", re.IGNORECASE)
TELEGRAM_MESSAGE_URL_RE = re.compile(r"^https?://t\.me/(?P<handle>[A-Za-z0-9_]{3,})/(?P<message_id>\d+)$", re.IGNORECASE)
TELEGRAM_CONTACT_URL_RE = re.compile(r"^https?://t\.me/(?P<handle>[A-Za-z0-9_]{3,})(?:/\d+)?$", re.IGNORECASE)
SOURCE_ANCHOR_RE = re.compile(r"^@[A-Za-z0-9_]{3,}/\d+$")
SOURCE_TITLE_ANCHOR_RE = re.compile(r"^.+\s/\s\d+$")
CONTACT_SPLIT_RE = re.compile(r"[|\n;]+")
EMOJI_CHAR_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
SERVICE_LABEL_PROMO_RANK_RE = re.compile(
    r"\s*(?:[№#]\s*1|number\s*1|no\.?\s*1)\b(?:\s+(?:в|у|на|по)\s+[^,.;!?]{2,48})?",
    re.IGNORECASE,
)
ONE_OFF_TRIP_DATE_RE = re.compile(
    r"^\d{1,2}\s+(?:январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"\b\d[\d\s.,]{0,12}\s?(?:eur|euro|rsd|usd|din(?:ar)?|дин|динар|динара|евро)\b", re.IGNORECASE)
PRICE_FROM_RE = re.compile(r"\b(?:от|from)\s+\d[\d\s.,]{0,12}\s?(?:eur|euro|rsd|usd|din(?:ar)?|дин|динар|динара|евро)\b", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
DETAIL_SPLIT_RE = re.compile(r"\s*(?:;|•)\s*")
LOCATION_TAIL_RE = re.compile(r"(?P<head>.+?)\s+(?P<preposition>в|по|из)\s+(?P<tail>[^,.;!?]+)$", re.IGNORECASE)
DETAILS_LEGAL_ARTICLE_PREFIX_RE = re.compile(r"^статья\s+\d+\s*:\s*", re.IGNORECASE)
DETAILS_MARKET_TENURE_RE = re.compile(r"^уже\s+\d+(?:[.,]\d+)?\s+года?\s+на рынке$", re.IGNORECASE)
DETAILS_LIST_INTRO_PREFIX_RE = re.compile(
    r"^(?:что мы делаем|запросы, с которыми я работаю|зоны для работы|результат|дополнительно)\s*:\s*",
    re.IGNORECASE,
)
SERVICE_ACTION_HEAD_RE = re.compile(r"^[A-Za-zА-Яа-яЁё-]+(?:ть|ться)$", re.IGNORECASE)

JSON_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
NON_RETRYABLE_INCOMPLETE_REASONS = {"max_output_tokens"}
QUOTA_OR_BILLING_ERROR_CODES = {
    "billing_hard_limit_reached",
    "billing_not_active",
    "credits_exhausted",
    "insufficient_quota",
    "quota_exceeded",
}
QUOTA_OR_BILLING_MESSAGE_PHRASES = (
    "billing hard limit",
    "billing details",
    "check your plan and billing",
    "credit balance",
    "credits exhausted",
    "exceeded your current quota",
    "insufficient_quota",
    "not enough credits",
    "quota exceeded",
)

SERBIA_CITY_CODES = {
    "belgrade",
    "beograd",
    "novi_sad",
    "nis",
    "subotica",
    "kragujevac",
    "cacak",
    "kraljevo",
    "novi_pazar",
    "smederevo",
    "zrenjanin",
    "pancevo",
}
SERBIA_KEYWORDS = {
    "serbia",
    "srbija",
    "serbian",
    "сербия",
    "сербии",
    "белград",
    "belgrade",
    "beograd",
    "нови",
    "сад",
    "novi sad",
    "ниш",
    "nis",
    "суботица",
    "subotica",
}
FOREIGN_GEOGRAPHY_HINTS = {
    "montenegro",
    "черногория",
    "croatia",
    "хорватия",
    "bosnia",
    "босния",
    "slovenia",
    "словения",
    "germany",
    "германия",
    "austria",
    "австрия",
    "hungary",
    "венгрия",
}
NON_SERVICE_HINTS = {
    "вакансия",
    "вакансии",
    "работа",
    "ищу",
    "ищем",
    "куплю",
    "продам",
    "сдам",
    "сниму",
    "job",
    "vacancy",
    "wanted",
    "looking",
    "rent",
    "sell",
    "buy",
}
GENERIC_PROVIDER_TOKENS = {
    "service",
    "services",
    "услуги",
    "master",
    "мастер",
    "serbia",
    "serbian",
}
GENERIC_CATEGORY_CODES = {
    "other",
    "misc",
    "services_general",
    "service_general",
    "unknown",
}

PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY = {
    "construction_repair": "\u0420\u0435\u043c\u043e\u043d\u0442 \u0438 \u043c\u043e\u043d\u0442\u0430\u0436",
    "cleaning": "\u0423\u0431\u043e\u0440\u043a\u0430 \u0438 \u0445\u0438\u043c\u0447\u0438\u0441\u0442\u043a\u0430",
    "moving_delivery": "\u041f\u0435\u0440\u0435\u0435\u0437\u0434\u044b \u0438 \u0434\u043e\u0441\u0442\u0430\u0432\u043a\u0430",
    "auto_service": "\u0410\u0432\u0442\u043e\u0443\u0441\u043b\u0443\u0433\u0438",
    "education_tutoring": "\u041e\u0431\u0443\u0447\u0435\u043d\u0438\u0435",
    "marketing_promotion": "Digital \u0438 \u0434\u0438\u0437\u0430\u0439\u043d",
    "it_digital": "Digital \u0438 \u0434\u0438\u0437\u0430\u0439\u043d",
    "beauty_cosmetology": "\u041a\u0440\u0430\u0441\u043e\u0442\u0430 \u0438 \u0437\u0434\u043e\u0440\u043e\u0432\u044c\u0435",
    "psychology": "\u041f\u0441\u0438\u0445\u043e\u043b\u043e\u0433\u0438\u044f",
    "legal_docs": "\u0414\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u044b \u0438 \u043f\u0440\u0430\u0432\u043e",
    "food_hospitality": "\u0415\u0434\u0430 \u0438 \u0433\u043e\u0441\u0442\u0435\u043f\u0440\u0438\u0438\u043c\u0441\u0442\u0432\u043e",
}
PRODUCT_CATEGORY_DISPLAY_SET = set(PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY.values())
PRODUCT_CATEGORY_PRIMARY_BY_DISPLAY = {
    normalize_text(label).lower(): primary
    for primary, label in PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY.items()
}
PRODUCT_DROP_FACT_PACK_FLAGS = {
    "empty_offer",
    "platform_ad",
    "resale",
    "vacancy",
}
PRODUCT_REVIEW_FACT_PACK_FLAGS = {
    "ad_dump_compacted",
    "greeting_filtered",
    "self_intro_filtered",
}
PRODUCT_GREETING_PREFIXES = (
    "\u0432\u0441\u0435\u043c \u043f\u0440\u0438\u0432\u0435\u0442",
    "\u043f\u0440\u0438\u0432\u0435\u0442",
    "\u0437\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435",
    "\u0434\u043e\u0431\u0440\u044b\u0439 \u0434\u0435\u043d\u044c",
    "добрый вечер",
    "доброе утро",
    "доброго времени суток",
    "времени суток",
    "уважаемые соседи",
    "уважаемые",
    "\u0434\u043e\u0431\u0440\u043e \u043f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c",
    "hello",
    "hi",
)
PRODUCT_HOLIDAY_GREETING_PREFIXES = (
    "с новым годом",
    "с 8 марта",
    "с восьмым марта",
    "с международным женским днем",
    "с международным женским днём",
    "с праздником",
    "поздравляем",
    "поздравляю",
)
PRODUCT_SELF_INTRO_PREFIXES = (
    "\u043c\u0435\u043d\u044f \u0437\u043e\u0432\u0443\u0442",
    "\u044f \u043c\u0430\u0441\u0442\u0435\u0440",
    "\u044f \u0441\u043f\u0435\u0446\u0438\u0430\u043b\u0438\u0441\u0442",
    "\u044f \u043f\u0441\u0438\u0445\u043e\u043b\u043e\u0433",
    "\u044f \u0440\u0435\u043f\u0435\u0442\u0438\u0442\u043e\u0440",
    "\u043c\u044b \u043a\u043e\u043c\u0430\u043d\u0434\u0430",
    "\u043c\u044b \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f",
)
PRODUCT_PROMO_PHRASES = (
    "\u21161 \u0432",
    "number 1",
    "official portal",
    "official channel",
    "download the app",
    "download the mobile app",
)
PRODUCT_HARDWARE_HINTS = {
    "iphone",
    "ipad",
    "macbook",
    "samsung",
    "xiaomi",
    "ram",
    "gb",
    "tb",
    "ssd",
    "cpu",
    "gpu",
    "\u0430\u0439\u0444\u043e\u043d",
    "\u043d\u043e\u0443\u0442\u0431\u0443\u043a",
    "\u043e\u0437\u0443",
}
PRODUCT_GENERIC_SERVICE_NAMES = {
    "service",
    "services",
    "услуги",
    "предлагаю услуги",
    "специалист",
    "консультация",
    "master",
    "мастер",
    "помогу",
}
PRODUCT_GENERIC_SERVICE_PHRASES = (
    "помогу с бытовыми вопросами",
    "разные бытовые задачи",
    "help with household issues",
    "help with daily tasks",
)
PRODUCT_NON_SERVICE_PHRASES = (
    "розыгрыш",
    "giveaway",
    "чат по",
    "news",
    "новости",
    "дайджест",
    "digest",
    "не забываем",
    "переход на летнее время",
)
PRODUCT_CHAT_DIRECTORY_HINTS = (
    "авточат",
    "вступайте в чат",
    "группа для обсуждения",
    "обсуждаем",
    "присоединяйтесь к чату",
    "чат сербии",
    "чат о",
    "чат по",
    "чат про",
)
PRODUCT_CHAT_DIRECTORY_SERVICE_ALLOW_HINTS = (
    "занятия",
    "консультац",
    "настройка",
    "обучение",
    "продвижение",
    "разработка",
    "уроки",
    "services",
)
PRODUCT_EVENT_SOCIAL_NOISE_HINTS = (
    "знакомств",
    "новые друзья",
    "вечер ",
    "вечерин",
    "коктейл",
    "бар",
    "stand-up",
    "стендап",
    "концерт",
    "шоу",
    "выступлен",
    "билет",
    "афиша",
    "шутк",
)
PRODUCT_NEWS_MARKETING_HEADLINE_HINTS = (
    "в 2025 году",
    "в 2026 году",
    "почему ",
    "стал ",
    "стала ",
    "стало ",
    "выдал",
    "получил",
    "получила",
    "маршрут легализации",
    "популярн",
    "без крупных инвестиций",
)
PRODUCT_MODERATION_BOT_NOISE_HINTS = (
    "недостаточно прав",
    "блокировк",
    "удаление сообщений",
    "техническ",
    "настройках бота",
    "тихий режим",
    "spam",
    "спам",
    "moderation",
)
PRODUCT_MODEL_SEARCH_PHRASES = (
    "ищу моделей",
    "ищу модель",
    "ищем моделей",
    "ищем модель",
    "ищет моделей",
    "ищет модель",
    "нужны модели",
    "нужна модель",
    "в качестве модели",
    "для отработки скорости",
    "для съемки контента",
    "для съёмки контента",
    "для пополнения портфолио",
    "оплата только за материалы",
    "оплата только за украшение",
    "приглашаю моделей",
)
PRODUCT_MODEL_SEARCH_CONTEXT_HINTS = (
    "бесплатно",
    "за материалы",
    "для отработки",
    "отработк",
    "портфолио",
    "практик",
    "учебн",
    "трениров",
    "брашинг",
    "локон",
    "уклад",
    "макияж",
    "маникюр",
    "педикюр",
    "окрашив",
    "стриж",
)
PRODUCT_PHOTO_VIDEO_PRODUCTION_MEDIA_HINTS = (
    "видео",
    "видеосъ",
    "video",
    "фото",
    "фотосъ",
    "фотосес",
    "photo",
    "ролик",
    "роликов",
    "reels",
)
PRODUCT_PHOTO_VIDEO_PRODUCTION_WORK_HINTS = (
    "снима",
    "сниму",
    "поснимаю",
    "съёмк",
    "съемк",
    "shoot",
    "filming",
    "монтаж",
    "монтир",
    "editing",
    "production",
)
PRODUCT_REAL_ESTATE_LISTING_PHRASES = (
    "#сдача",
    "#аренда",
    "аренда квартир",
    "сдаётся квартира",
    "сдается квартира",
    "сдам квартиру",
    "сдаю квартиру",
    "аренда квартиры",
    "аренда дома",
    "продажа квартиры",
    "продам квартиру",
    "куплю квартиру",
    "flat for rent",
    "apartment for rent",
    "rent apartment",
)
PRODUCT_REAL_ESTATE_SERVICE_MARKERS = (
    "риелтор",
    "риэлтор",
    "агент",
    "подбор квартиры",
    "поможем найти квартиру",
    "сопровождение сделки",
    "юридическое сопровождение",
    "переезд",
    "moving",
)
PRODUCT_REAL_ESTATE_LISTING_DETAIL_HINTS = (
    "м2",
    "м²",
    "спальн",
    "комнат",
    "депозит",
    "заезд",
    "этаж",
    "площадь",
    "просмотр",
    "на срок",
    "помесячно",
    "viewing",
)
PRODUCT_REAL_ESTATE_SERVICE_CONTEXT_HINTS = (
    "уборк",
    "клининг",
    "химчист",
    "технический аудит",
    "техническ",
    "приёмк",
    "приемк",
    "осмотр",
    "инспекц",
    "дефект",
    "переезд",
    "перевоз",
    "груз",
    "доставк",
    "строитель",
    "строительные работы",
    "отделк",
    "монтаж",
    "сантех",
    "электрик",
    "массаж",
    "реабилитац",
    "therapy",
    "massage",
)
PRODUCT_PROPERTY_TECHNICAL_INSPECTION_HINTS = (
    "технический аудит",
    "техническ",
    "приёмк",
    "приемк",
    "осмотр",
    "инспекц",
    "дефект",
    "застройщик",
    "вентиляц",
    "плесен",
    "заключен",
    "бюджет ремонта",
)
PRODUCT_PROPERTY_TECHNICAL_INSPECTION_OBJECT_HINTS = (
    "квартир",
    "апартамент",
    "дом",
    "дома",
    "house",
    "офис",
    "office",
    "помещен",
    "premise",
)
PRODUCT_REAL_ESTATE_PLATFORM_HINTS = (
    "платформа",
    "площадка",
    "marketplace",
    "platform",
    "приложение",
    "app",
)
PRODUCT_REAL_ESTATE_PLATFORM_ACTION_HINTS = (
    "объявлен",
    "недвижим",
    "real estate",
    "покуп",
    "продаж",
    "аренд",
    "листинг",
    "listing",
    "на карте",
    "map",
)
PRODUCT_REAL_ESTATE_PLATFORM_MECHANIC_HINTS = (
    "бесплатн",
    "безлимит",
    "публик",
    "размест",
    "объявлен",
    "поиск на карте",
    "на карте",
    "радиус",
    "чат",
    "отзыв",
)
PRODUCT_ESOTERIC_PHRASES = (
    "таро",
    "taro",
    "гадание",
    "гадаю",
    "натальная карта",
    "астролог",
    "астрология",
    "нумеролог",
    "нумерология",
    "эзотер",
    "предсказан",
    "fortune telling",
)
PRODUCT_AUDIENCE_PREFIXES = (
    "девочки",
    "девушки",
    "друзья",
)
PRODUCT_SERVICE_OFFER_PREFIXES = (
    "произвожу ",
    "выполняю ",
    "выполняем ",
    "делаю ",
    "делаем ",
    "предлагаю ",
    "предлагаем ",
    "предоставляю ",
    "предоставляем ",
    "оказываю ",
    "оказываем ",
    "провожу ",
    "проводим ",
    "могу ",
    "можем ",
)
PRODUCT_PROVIDER_INTRO_PHRASES = (
    "сертифицированный мастер",
    "дипломированный психолог",
    "начинающий мастер",
    "я мастер",
    "я репетитор",
    "я психолог",
)
PRODUCT_BRAND_LABEL_TOKENS = {
    "cleaning",
    "studio",
    "studios",
    "clinic",
    "salon",
    "company",
}
PRODUCT_SHORT_SERVICE_LABEL_REWRITES = {
    "клининг": "Клининг",
    "cleaning": "Клининг",
    "электроэпиляция": "Электроэпиляция",
    "маникюр": "Маникюр",
    "педикюр": "Педикюр",
    "маникюр педикюр": "Маникюр и педикюр",
    "психолог": "Консультация психолога",
    "психология": "Консультация психолога",
    "репетитор": "Репетитор",
    "соленая карамель": "Соленая карамель",
    "солёная карамель": "Соленая карамель",
    "кондиционер": "Обслуживание кондиционеров",
    "кондиционеров": "Обслуживание кондиционеров",
    "муж на час": "Мастер" + " на час",
    "мастер на час": "Мастер" + " на час",
}
PRODUCT_SERVICE_TAIL_PHRASES = (
    "также работаю",
    "работаю по",
    "запись в",
    "запись по",
    "пишите",
    "напишите",
    "пришлите",
    "звоните",
    "с любовью",
    "с удовольствием помогу",
    "спокойно жить",
    "планировать будущее",
    "по договоренности",
    "по договорённости",
    "в короткие сроки",
    "в нашем арсенале",
)
PRODUCT_SERVICE_CONDITION_PHRASES = (
    "без кредитной карты",
    "без кредитных карт",
    "без депозита",
    "без залога",
)
PRODUCT_MARKETING_TAIL_PHRASES = (
    "просто и надежно",
    "просто и надёжно",
    "легко и с любовью",
    "комфортно и быстро",
    "как вы любите",
)
PRODUCT_SENTENCE_LIKE_START_PHRASES = (
    "говорите ",
    "как ",
    "готов ",
    "готова ",
    "готовы ",
    "требуются ",
    "требуется ",
)
PRODUCT_SENTENCE_LIKE_INLINE_PHRASES = (
    " я предлагаю ",
    " я выполняю ",
    " я оказываю ",
    " я провожу ",
)
PRODUCT_SLOGAN_OR_PROMO_LABEL_PHRASES = (
    "самое время",
    "время ",
    "сезон ",
    "сезон охоты",
    "устали от",
    "ищете ",
    "хотите ",
    "пора ",
    "сезонн",
    "акция",
    "спецпредложение",
    "позаботьтесь",
)
PRODUCT_ADDRESS_LABEL_PREFIXES = (
    "address",
    "location",
    "адрес",
    "локация",
)
PRODUCT_PRICE_CLAUSE_LABEL_PREFIXES = (
    "price",
    "cost",
    "fee",
    "по стоимости",
    "стоимость",
    "цена",
    "оплата",
    "прайс",
)
PRODUCT_INSTRUCTION_LABEL_PREFIXES = (
    "how to ",
    "instruction",
    "instructions",
    "как ",
    "инструкция",
    "что нужно",
    "для участия",
    "условия участия",
    "заполните",
    "скачайте",
    "перейдите",
    "подпишитесь",
)
PRODUCT_AVAILABILITY_LABEL_NEGATIVE_PREFIXES = (
    "нет нужн",
    "нет подходящ",
    "нет требуем",
    "нет необходим",
)
PRODUCT_AVAILABILITY_LABEL_INVENTORY_HINTS = (
    "комплектац",
    "версии",
    "модели",
    "размера",
    "цвета",
    "варианта",
)
PRODUCT_DETAILS_NOISE_PHRASES = (
    "мои преимущества",
    "могу помочь вам",
    "могу помочь и вам",
    "реальные отзывы клиентов",
    "места ограничены",
    "собираю портфолио",
    "приглашаю моделей",
    "по отличным ценам",
    "скидка",
    "подарок",
    "в честь запуска",
    "только до",
    "ваш надежный",
    "ваш надёжный",
    "подписывайтесь",
    "рассчитать стоимость",
    "пишите в личку",
    "пишите в личные сообщения",
    "пишите сюда",
    "напишите нам",
    "пришлите фото",
    "давайте подарим",
    "буду рада",
    "это значит",
    "работаю офлайн",
    "по всему миру",
    "сессия-знакомство бесплатно",
    "сессия-знакомство бесплатна",
    "таланты, способности и профессии",
    "талантов способностей и профессий",
    "для женщин и их детей",
    "в нашем арсенале",
    "много лет работал",
    "работал в сфере",
    "теперь живу",
    "продолжаю своё дело",
    "продолжаю свое дело",
    "при повторных заказах",
    "приближается летний период",
    "рекомендуется заблаговременно",
    "необходимые мероприятия включают",
    "когда мы работаем",
    "почему массаж",
    "потому что",
    "здесь у вас есть возможность",
)
PRODUCT_RESALE_DETAIL_PHRASES = (
    "в наличии",
    "ассортимент",
    "для покупки",
    "новую технику",
    "новая техника",
    "дешевле чем",
    "с доставкой на дом",
)
PRODUCT_PURCHASE_REQUEST_PHRASES = (
    "где купить",
    "где можно купить",
    "где найти",
    "кто знает где",
    "подскажите где",
    "ищу где купить",
)
PRODUCT_RENTAL_REQUEST_PHRASES = (
    "аренда мастерской",
    "снять мастерскую",
    "ищу мастерскую",
    "где арендовать",
    "нужна мастерская",
    "нужен плиткорез",
    "аренда плиткореза",
    "сдать плиткорез",
    "взять в аренду",
    "самостоятельной работы",
)
PRODUCT_OFFERING_RENTAL_PHRASES = (
    "предоставляю в аренду",
    "предоставляем в аренду",
    "сдаю в аренду",
    "сдаем в аренду",
    "сдаём в аренду",
    "прокат",
    "аренда авто",
)
PRODUCT_GOODS_INFO_PHRASES = (
    "информация о ценах",
    "цены и скидки",
    "скидки на инструмент",
    "отзыв о",
    "обзор ",
    "где купить",
)
PRODUCT_COMPLAINT_PROBLEM_PHRASES = (
    "некачественный монтаж",
    "некачественная установка",
    "плохо сделали",
    "плохо сделали монтаж",
    "кто может исправить",
    "как исправить",
)
PRODUCT_DETAILS_LEGAL_NOISE_PHRASES = (
    "работаем официально",
    "по закону о туризме",
    "компания официально зарегистрирована",
    "официально зарегистрирована",
)
PRODUCT_DETAILS_BENEFIT_PREFIXES = (
    "жить ",
    "работать ",
    "планировать ",
    "открыть ",
    "оформить ",
    "получить ",
)
PRODUCT_CLEANING_SERVICE_HINTS = (
    "клининг",
    "уборк",
    "генеральн",
    "поддерживающ",
    "после ремонта",
    "химчист",
    "обработка паром",
)
PRODUCT_AIRCON_CLEANING_HINTS = (
    "кондиционер",
    "кондиционеров",
    "фильтр",
    "турбин",
    "хлор",
    "мойк",
    "чистк",
)
PRODUCT_TUTORING_HINTS = (
    "репетитор",
    "уроки",
    "ielts",
    "tefl",
    "гете",
    "goethe",
)
PRODUCT_MARKETING_SERVICE_HINTS = (
    "маркетолог",
    "маркетинг",
    "продвиж",
    "личный бренд",
    "таргет",
    "рилс",
    "продажи",
    "клиентов",
    "smm",
    "реклама",
)
PRODUCT_PROFORIENTATION_HINTS = (
    "професси",
    "талант",
    "способност",
    "ребёнок",
    "ребенок",
    "подрост",
    "профориентац",
)
PRODUCT_FOOD_SALE_ITEM_HINTS = (
    "карамел",
    "торт",
    "десерт",
    "печенье",
    "капкейк",
    "пирог",
)
PRODUCT_ORDER_PICKUP_HINTS = (
    "заказ",
    "самовывоз",
    "из банки",
    "доставка",
)
PRODUCT_AUTO_HEADLINE_BRAND_HINTS = {
    "audi",
    "benz",
    "bmw",
    "chevrolet",
    "citroen",
    "cls",
    "ford",
    "honda",
    "hyundai",
    "kia",
    "lexus",
    "mazda",
    "mercedes",
    "mitsubishi",
    "nissan",
    "opel",
    "peugeot",
    "renault",
    "skoda",
    "subaru",
    "suzuki",
    "tesla",
    "toyota",
    "volkswagen",
    "volvo",
    "vw",
    "мерседес",
}
PRODUCT_AUTO_SERVICE_CORE_HINTS = (
    "аренда авто",
    "аренда автомобиля",
    "аренда машины",
    "прокат авто",
    "прокат автомобиля",
    "rent a car",
    "car rental",
    "подбор авто",
    "автоподбор",
    "ремонт авто",
    "диагностика авто",
    "осмотр и диагностика авто",
    "осмотр авто перед покупкой",
    "автосервис",
    "детейлинг",
    "эвакуатор",
    "авто под ключ",
    "автомобиль под ключ",
    "пригнать авто",
    "пригон авто",
    "из европы",
)
PRODUCT_AUTO_INSPECTION_DETAIL_HINTS = (
    "осмотр кузова",
    "лкп",
    "компьютерная диагностика",
    "тест-драйв",
    "фото/видео отчет",
    "фото/видео отчёт",
    "осмотр авто",
    "проверили",
)
PRODUCT_VEHICLE_RENTAL_CONDITION_TERMS = (
    "депозит",
    "залог",
    "страхов",
    "каско",
    "осаго",
)
PRODUCT_VACANCY_KEYWORDS = {
    "company",
    "cv",
    "employment",
    "hiring",
    "job",
    "position",
    "requirements",
    "responsibilities",
    "resume",
    "salary",
    "\u0430\u043d\u043a\u0435\u0442\u0443",
    "\u0432\u0430\u043a\u0430\u043d\u0441\u0438\u044f",
    "\u0432\u0430\u043a\u0430\u043d\u0441\u0438\u0438",
    "\u0438\u0449\u0435\u043c",
    "\u0438\u0449\u0443",
    "\u0437\u0430\u0440\u043f\u043b\u0430\u0442\u0430",
    "\u043a\u043e\u043c\u0430\u043d\u0434\u0443",
    "\u043e\u0431\u044f\u0437\u0430\u043d\u043d\u043e\u0441\u0442\u0438",
    "\u043e\u0442\u043a\u043b\u0438\u043a\u0430\u0439\u0441\u044f",
    "\u0440\u0430\u0431\u043e\u0442\u0430",
    "\u0440\u0435\u0437\u044e\u043c\u0435",
    "\u0442\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f",
    "\u0442\u0440\u0435\u0431\u0443\u044e\u0442\u0441\u044f",
    "\u0442\u0440\u0435\u0431\u043e\u0432\u0430\u043d\u0438\u044f",
}
PRODUCT_VACANCY_PHRASES = (
    "#cv",
    "full-time",
    "looking for",
    "office-based",
    "what we expect",
    "\u0432 \u043f\u043e\u0438\u0441\u043a\u0435 \u0440\u0430\u0431\u043e\u0442\u044b",
    "\u0438\u0449\u0435\u043c \u0432 \u043a\u043e\u043c\u0430\u043d\u0434\u0443",
    "\u0438\u0449\u0443 \u0440\u0430\u0431\u043e\u0442\u0443",
    "\u0438\u0449\u0443\u0440\u0430\u0431\u043e\u0442\u0443",
    "\u043a\u043e\u0433\u043e \u043c\u044b \u0438\u0449\u0435\u043c",
    "\u043e\u0442\u043a\u043b\u0438\u043a\u043d\u0443\u0442\u044c\u0441\u044f \u043d\u0430 \u0432\u0430\u043a\u0430\u043d\u0441\u0438\u044e",
    "\u043c\u044b \u0430\u043a\u0442\u0438\u0432\u043d\u043e \u0440\u0430\u0441\u0442\u0435\u043c \u0438 \u0438\u0449\u0435\u043c",
    "\u0437\u0430\u043f\u043e\u043b\u043d\u0438\u0442\u044c \u0430\u043d\u043a\u0435\u0442\u0443",
    "\u0447\u0442\u043e \u043f\u0440\u0435\u0434\u043b\u0430\u0433\u0430\u0435\u0442 \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u044f",
    "требуются ",
    "требуется ",
)
PRODUCT_SERVICE_CHANNEL_HIRING_INTRO_HINTS = (
    "ищут ",
    "ищем ",
    "ищет ",
    "набор ",
    "открывает набор",
    "в команду",
    "требуются ",
    "требуется ",
)
PRODUCT_SERVICE_CHANNEL_HIRING_ROLE_HINTS = (
    "мастер",
    "специалист",
    "подолог",
    "маникюр",
    "педикюр",
    "ресниц",
    "парикмах",
    "барбер",
    "косметолог",
)
PRODUCT_SERVICE_CHANNEL_HIRING_CONDITION_HINTS = (
    "требован",
    "услови",
    "опыт от",
    "оплата",
    "% от",
    "процент",
    "выплата",
    "график",
    "зарплат",
)
PRODUCT_PLATFORM_PROMO_PHRASES = (
    "download the app",
    "download the mobile app",
    "google play",
    "marketplace",
    "official channel",
    "official portal",
    "\u0432 \u043d\u0430\u0448\u0435\u043c \u043a\u0430\u043d\u0430\u043b\u0435",
    "\u043d\u0430\u0448 \u043a\u0430\u043d\u0430\u043b",
    "\u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439 \u043a\u0430\u043d\u0430\u043b",
    "\u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u043e\u0440\u0442\u0430\u043b",
    "\u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0430 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0439",
    "\u043f\u043b\u043e\u0449\u0430\u0434\u043a\u0438 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0439",
    "\u043f\u043e\u0434\u043f\u0438\u0441\u044b\u0432\u0430\u0439\u0442\u0435\u0441\u044c",
    "\u043f\u0443\u0431\u043b\u0438\u043a\u0443\u0435\u043c \u0432\u0430\u0448\u0438 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u044f",
    "\u043d\u0430\u0439\u0434\u0438\u0442\u0435 \u0432\u0441\u0451 \u0447\u0442\u043e \u043d\u0443\u0436\u043d\u043e",
    "\u043e\u043f\u0443\u0431\u043b\u0438\u043a\u0443\u0439\u0442\u0435 \u0441\u0432\u043e\u0451",
    "\u043f\u0440\u0438\u0432\u043b\u0435\u0447\u044c \u043d\u043e\u0432\u0443\u044e \u0430\u0443\u0434\u0438\u0442\u043e\u0440\u0438\u044e",
    "\u043f\u0440\u0438\u0432\u043b\u0435\u0447\u044c \u0430\u0443\u0434\u0438\u0442\u043e\u0440\u0438\u044e",
    "\u0440\u0430\u0437\u043c\u0435\u0441\u0442\u0438\u0442\u0435 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0435",
    "\u0440\u0430\u0437\u043c\u0435\u0441\u0442\u0438\u0442\u044c \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0435",
    "\u0440\u0430\u0437\u043c\u0435\u0449\u0430\u0439\u0442\u0435 \u0432\u0430\u0448\u0438 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u044f",
    "\u0441\u043a\u0430\u0447\u0430\u0442\u044c \u043c\u043e\u0431\u0438\u043b\u044c\u043d\u043e\u0435 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435",
)
PRODUCT_PLATFORM_REPOST_PROMO_PHRASES = (
    "\u0441\u0434\u0435\u043b\u0430\u0442\u044c \u0440\u0435\u043f\u043e\u0441\u0442",
    "\u0440\u0435\u043f\u043e\u0441\u0442 \u0437\u0430\u043f\u0438\u0441\u0438",
    "\u043a \u0441\u0435\u0431\u0435 \u0432 \u0433\u0440\u0443\u043f\u043f\u0443",
    "\u043d\u0430 \u043b\u0438\u0447\u043d\u0443\u044e \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0443",
    "\u0432 \u043b\u044e\u0431\u043e\u0439 \u0441\u043e\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0439 \u0441\u0435\u0442\u0438",
)
PRODUCT_REMOTE_WORK_EMPLOYMENT_HINTS = (
    "employment",
    "hiring",
    "job",
    "vacancy",
    "запошљ",
    "послов",
    "посао",
    "ваканс",
)
PRODUCT_REMOTE_WORK_MODE_HINTS = (
    "remote",
    "на даљину",
    "удален",
    "дистанц",
)
PRODUCT_REMOTE_WORK_PLATFORM_HINTS = (
    "platform",
    "платформ",
    "channel",
    "канал",
    "website",
    "web-site",
    "веб",
    "сайт",
    "tg ",
    "telegram",
)
PRODUCT_RESALE_PREFIXES = (
    "for sale",
    "selling",
    "\u0432 \u043f\u0440\u043e\u0434\u0430\u0436\u0435",
    "\u043d\u0430 \u043f\u0440\u043e\u0434\u0430\u0436\u0435",
    "\u043f\u0440\u043e\u0434\u0430\u0435\u0442\u0441\u044f",
    "\u043f\u0440\u043e\u0434\u0430\u044e",
    "\u043f\u0440\u043e\u0434\u0430\u044e\u0442\u0441\u044f",
    "\u043f\u0440\u043e\u0434\u0430\u043c",
)
PRODUCT_JOB_PROFILE_ROLE_HINTS = {
    "backend",
    "developer",
    "devops",
    "engineer",
    "frontend",
    "fullstack",
    "qa",
    "\u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a",
}
PRODUCT_JOB_PROFILE_SENIORITY_HINTS = {
    "junior",
    "middle",
    "senior",
}
PRODUCT_JOB_PROFILE_EXPERIENCE_HINTS = {
    "experience",
    "years",
    "\u0433\u043e\u0434",
    "\u0433\u043e\u0434\u0430",
    "\u0433\u043e\u0434\u0430\u043c\u0438",
    "\u043b\u0435\u0442",
    "\u043e\u043f\u044b\u0442",
    "\u043e\u043f\u044b\u0442\u0430",
}
PRODUCT_CATEGORY_SIGNAL_HINTS = {
    "construction_repair": (
        "ремонт",
        "монтаж",
        "сантех",
        "электрик",
        "мастер на час",
        "мастер",
        "кондиционер",
        "кондиционеров",
        "электроинструмент",
        "инструмент",
        "дрель",
        "шуруповерт",
        "шуруповёрт",
        "изготовление мебели",
        "мебел",
        "кухни на заказ",
        "шкаф",
        "paint",
        "plaster",
        "plumber",
        "electric",
    ),
    "cleaning": ("уборк", "клининг", "химчист", "дезинфекц", "пыль", "поверхност", "cleaning", "clean", "housekeeping"),
    "moving_delivery": ("переезд", "доставк", "груз", "cargo", "moving", "delivery", "truck", "furniture"),
    "auto_service": ("авто", "трансфер", "пассажир", "car", "detailing", "шин", "эвакуатор", "mechanic", "tow", "transfer"),
    "education_tutoring": ("обуч", "репет", "урок", "заняти", "трениров", "бокс", "растяж", "tutor", "course", "class", "training", "language lesson"),
    "marketing_promotion": ("маркетинг", "продвижен", "реклам", "smm", "seo", "targeting", "marketing"),
    "it_digital": ("smm", "seo", "design", "designer", "web", "website", "targeting", "marketing", "logo", "digital"),
    "beauty_cosmetology": ("маникюр", "педикюр", "pedikir", "pedicure", "груминг", "grooming", "бров", "ресниц", "космет", "beauty", "nails", "lash", "brow", "hair"),
    "psychology": ("психолог", "терап", "psycholog", "therapy", "counselling"),
    "legal_docs": ("документ", "нотари", "внж", "перевод", "visa", "legal", "lawyer"),
    "food_hospitality": ("еда", "food", "cake", "catering", "chef", "cook", "baker", "торт", "ресторан", "кафе"),
}
PRODUCT_AUTO_DETAILING_HINTS = (
    "детейлинг",
    "полировк",
    "керамик",
    "автодетейлинг",
)
PRODUCT_AUTO_INSPECTION_IMPORT_HINTS = (
    "подбор авто",
    "автоподбор",
    "осмотр авто",
    "осмотр и подбор авто",
    "техпровер",
    "проверка авто",
    "пригон авто",
    "пригнать авто",
    "авто под ключ",
    "автомобиль под ключ",
    "доставка авто",
    "из германии",
    "из европы",
    "из словении",
)
PRODUCT_AUTO_AC_HINTS = (
    "автокондиционер",
    "авто кондиционер",
    "кондиционер в авто",
    "фреон в авто",
    "утечке фреона в авто",
)
PRODUCT_HVAC_REPAIR_HINTS = (
    "обслуживание кондиционер",
    "обслуживание и ремонт кондиционер",
    "ремонт кондиционер",
    "монтаж кондиционер",
    "установка кондиционер",
    "запуск кондиционер",
    "настройка кондиционер",
    "заправка кондиционер",
    "фреон",
    "хладагент",
)
PRODUCT_TRANSPORT_SERVICE_HINTS = (
    "трансфер",
    "пассажир",
    "перевозки людей",
    "перевозка людей",
    "перевозки пассажиров",
    "перевозка пассажиров",
    "перевозки людей и грузов",
    "перевозка людей и грузов",
    "грузоперевоз",
    "перевозка вещей",
    "перевозки вещей",
    "поездки по сербии",
)
PRODUCT_VISARUN_TRANSPORT_HINTS = (
    "отправление",
    "маршрут",
    "поездк",
    "трансфер",
    "выезд",
    "из белграда",
    "сава центра",
)
PRODUCT_LANGUAGE_TUTORING_HINTS = (
    "репетитор",
    "преподаватель",
    "уроки",
    "занятия",
    "язык",
    "английск",
    "немецк",
    "сербск",
    "математик",
    "огэ",
    "егэ",
    "ielts",
    "goethe",
    "гете",
)
PRODUCT_MEDICAL_REHAB_HINTS = (
    "реабилитолог",
    "реабилитац",
    "лфк",
    "лечебная физкультура",
    "физиотерап",
    "мануальная",
    "мобилизац",
    "врач",
    "массаж",
    "терапевтический массаж",
    "подолог",
)
PRODUCT_REPAIR_CONTEXT_HINTS = (
    "ремонт",
    "обслуживан",
    "диагност",
    "замена",
    "аккумулятор",
    "клавиатур",
    "комплектующ",
    "термопаст",
    "экран",
    "ноутбук",
    "windows",
    "apple",
    "кондиционер",
    "кондиционеров",
)
PRODUCT_HOUSEHOLD_CLEANING_CONTEXT_HINTS = (
    "квартира",
    "дом",
    "офис",
    "генеральн",
    "после ремонта",
    "диван",
    "матрас",
    "ковер",
    "окна",
    "мебель",
    "клининг",
    "химчист",
    "housekeeping",
)
PRODUCT_HOUSEHOLD_REPAIR_MASTER_HINTS = (
    "ремонт",
    "монтаж",
    "сантех",
    "электрик",
    "маляр",
    "мебел",
    "бытов",
    "бойлер",
    "ролет",
    "окон",
    "двер",
    "засор",
    "полок",
    "шкаф",
)
SERBIA_TZ = ZoneInfo("Europe/Belgrade")

def _strict_object_schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    required_keys = list(properties.keys()) if required is None else required
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required_keys,
    }


def _nullable_schema(base_schema: dict[str, Any]) -> dict[str, Any]:
    schema = copy.deepcopy(base_schema)
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        schema["type"] = [schema_type, "null"]
    elif isinstance(schema_type, list):
        if "null" not in schema_type:
            schema["type"] = [*schema_type, "null"]
    else:
        raise ValueError("Nullable schema wrapper expects a typed schema.")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and None not in enum_values:
        schema["enum"] = [*enum_values, None]
    return schema


SERVICE_RELEVANCE_SCHEMA = _strict_object_schema(
    {
        "decision_code": {
            "type": "string",
            "enum": ["service_accept", "service_reject_non_service", "service_ambiguous"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "patch": _strict_object_schema(
            {
                "offer_state": _nullable_schema(
                    {
                        "type": "string",
                        "enum": ["candidate", "accepted", "rejected", "suppressed"],
                    }
                ),
                "offer_rejection_reason": _nullable_schema({"type": "string", "maxLength": 160}),
            }
        ),
        "reason_text": {"type": "string", "maxLength": 240},
    }
)

SERBIA_RELEVANCE_SCHEMA = _strict_object_schema(
    {
        "decision_code": {
            "type": "string",
            "enum": ["serbia_accept", "serbia_reject", "serbia_ambiguous"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "patch": _strict_object_schema(
            {
                "serbia_relevance_verdict": _nullable_schema(
                    {
                        "type": "string",
                        "enum": ["serbia_relevant", "outside_serbia", "uncertain"],
                    }
                ),
                "offer_state": _nullable_schema(
                    {
                        "type": "string",
                        "enum": ["candidate", "accepted", "rejected", "suppressed"],
                    }
                ),
                "offer_rejection_reason": _nullable_schema({"type": "string", "maxLength": 160}),
            }
        ),
        "reason_text": {"type": "string", "maxLength": 240},
    }
)

PRODUCT_ROW_SHAPE_SCHEMA = _strict_object_schema(
    {
        "decision_code": {
            "type": "string",
            "enum": ["publish", "drop"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "patch": _strict_object_schema(
            {
                "product_row_service_name": _nullable_schema({"type": "string", "maxLength": 120}),
                "product_row_details": _nullable_schema({"type": "string", "maxLength": 280}),
                "product_row_category": _nullable_schema(
                    {
                        "type": "string",
                        "enum": sorted(PRODUCT_CATEGORY_DISPLAY_SET),
                    }
                ),
                "product_row_contact": _nullable_schema({"type": "string", "maxLength": 160}),
            }
        ),
        "reason_text": {"type": "string", "maxLength": 240},
    }
)

CATEGORY_REFINE_OFFER_SCHEMA = _strict_object_schema(
    {
        "decision_code": {
            "type": "string",
            "enum": ["category_refined", "summary_refined", "no_change"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "patch": _strict_object_schema(
            {
                "category_primary": _nullable_schema({"type": "string", "maxLength": 80}),
                "category_secondary": _nullable_schema({"type": "string", "maxLength": 80}),
                "service_tags": _nullable_schema(
                    {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 40},
                        "maxItems": 8,
                    }
                ),
                "offer_summary": _nullable_schema({"type": "string", "maxLength": OFFER_SUMMARY_CHAR_LIMIT}),
            }
        ),
        "reason_text": {"type": "string", "maxLength": 240},
    }
)

CATEGORY_REFINE_PROVIDER_SCHEMA = _strict_object_schema(
    {
        "decision_code": {
            "type": "string",
            "enum": ["provider_named", "provider_summarized", "no_change"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "patch": _strict_object_schema(
            {
                "canonical_name": _nullable_schema({"type": "string", "maxLength": CANONICAL_NAME_CHAR_LIMIT}),
                "provider_summary": _nullable_schema({"type": "string", "maxLength": PROVIDER_SUMMARY_CHAR_LIMIT}),
            }
        ),
        "reason_text": {"type": "string", "maxLength": 240},
    }
)

PROVIDER_MERGE_REVIEW_SCHEMA = _strict_object_schema(
    {
        "decision_code": {
            "type": "string",
            "enum": ["same_provider", "different_provider", "uncertain"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "patch": _strict_object_schema({}),
        "reason_text": {"type": "string", "maxLength": 240},
    }
)

OFFER_DEDUPE_REVIEW_SCHEMA = _strict_object_schema(
    {
        "decision_code": {
            "type": "string",
            "enum": ["same_offer", "different_offer", "uncertain"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "patch": _strict_object_schema({}),
        "reason_text": {"type": "string", "maxLength": 240},
    }
)

STRICT_STAGE_SCHEMAS = {
    "service relevance": SERVICE_RELEVANCE_SCHEMA,
    "Serbia relevance": SERBIA_RELEVANCE_SCHEMA,
    "product row shape": PRODUCT_ROW_SHAPE_SCHEMA,
    "category refine offer": CATEGORY_REFINE_OFFER_SCHEMA,
    "category refine provider": CATEGORY_REFINE_PROVIDER_SCHEMA,
    "provider merge review": PROVIDER_MERGE_REVIEW_SCHEMA,
    "offer dedupe review": OFFER_DEDUPE_REVIEW_SCHEMA,
}


def _schema_allows_type(schema: dict[str, Any], expected_type: str) -> bool:
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type == expected_type
    if isinstance(schema_type, list):
        return expected_type in schema_type
    return False


def _collect_strict_schema_violations(schema: Any, *, path: str = "$") -> list[str]:
    if not isinstance(schema, dict):
        return [f"{path}: schema node must be an object."]

    violations: list[str] = []
    if _schema_allows_type(schema, "object"):
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            violations.append(f"{path}: object schema properties must be an object.")
            properties = {}
        if schema.get("additionalProperties") is not False:
            violations.append(f"{path}: object schema must set additionalProperties to false.")
        required = schema.get("required")
        if not isinstance(required, list):
            violations.append(f"{path}: object schema must define required as an array.")
        else:
            property_keys = list(properties.keys())
            missing = [key for key in property_keys if key not in required]
            unexpected = [key for key in required if key not in properties]
            if missing:
                violations.append(
                    f"{path}: required must include every property key; missing {', '.join(missing)}."
                )
            if unexpected:
                violations.append(
                    f"{path}: required includes unknown keys {', '.join(unexpected)}."
                )
        for key, child_schema in properties.items():
            violations.extend(_collect_strict_schema_violations(child_schema, path=f"{path}.{key}"))

    items_schema = schema.get("items")
    if isinstance(items_schema, dict):
        violations.extend(_collect_strict_schema_violations(items_schema, path=f"{path}[]"))

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        for index, child_schema in enumerate(any_of):
            violations.extend(_collect_strict_schema_violations(child_schema, path=f"{path}.anyOf[{index}]"))

    defs = schema.get("$defs")
    if isinstance(defs, dict):
        for key, child_schema in defs.items():
            violations.extend(_collect_strict_schema_violations(child_schema, path=f"{path}.$defs.{key}"))

    return violations


def validate_stage_schemas() -> list[str]:
    validated: list[str] = []
    violations: list[str] = []
    for schema_name, schema in STRICT_STAGE_SCHEMAS.items():
        schema_violations = _collect_strict_schema_violations(schema)
        if schema_violations:
            violations.extend(f"{schema_name}: {entry}" for entry in schema_violations)
            continue
        validated.append(schema_name)
    if violations:
        detail = "\n".join(f"- {entry}" for entry in violations)
        raise ValueError(f"Strict Structured Outputs schema validation failed.\n{detail}")
    return validated


@dataclass(slots=True)
class Candidate:
    stage: str
    entity_type: str
    entity_id: str
    entity_ref: str
    prompt_version: str
    schema_name: str
    schema: dict[str, Any]
    threshold: float
    input_payload: dict[str, Any]
    source_raw_post_ids: list[str]
    estimated_next_cost_usd: float


@dataclass(slots=True)
class LlmProgress:
    started_monotonic: float
    total_timeout_seconds: float | None
    current_stage: str = ""
    current_candidate_index: int = 0
    current_candidate_total: int = 0
    current_entity_type: str = ""
    current_entity_id: str = ""
    completed_candidates_total: int = 0


class LlmTotalTimeout(RuntimeError):
    pass


def _configured_total_timeout_seconds() -> float | None:
    raw_value = os.environ.get("TGSA_LLM_TOTAL_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return None
    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise ValueError("TGSA_LLM_TOTAL_TIMEOUT_SECONDS must be numeric.") from exc
    if parsed < 0:
        raise ValueError("TGSA_LLM_TOTAL_TIMEOUT_SECONDS must be non-negative.")
    return parsed


def _configured_product_row_chunk_timeout_reserve_seconds() -> float | None:
    raw_value = os.environ.get("TGSA_LLM_PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_SECONDS", "").strip()
    if not raw_value:
        return None
    try:
        parsed = float(raw_value)
    except ValueError as exc:
        raise ValueError("TGSA_LLM_PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_SECONDS must be numeric.") from exc
    if parsed < 0:
        raise ValueError("TGSA_LLM_PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_SECONDS must be non-negative.")
    return parsed


def _product_row_chunk_timeout_reserve_seconds(total_timeout_seconds: float | None) -> float:
    configured = _configured_product_row_chunk_timeout_reserve_seconds()
    if configured is not None:
        return configured
    if total_timeout_seconds is None:
        return 0.0
    proportional = total_timeout_seconds * PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_FRACTION
    return min(
        PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_MAX_SECONDS,
        max(PRODUCT_ROW_CHUNK_TIMEOUT_RESERVE_MIN_SECONDS, proportional),
    )


def _parse_non_negative_int(raw_value: Any, *, field_name: str) -> int:
    try:
        parsed = int(str(raw_value).strip())
    except Exception as exc:
        raise ValueError(f"{field_name} must be a non-negative integer.") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")
    return parsed


def _resolve_product_row_candidate_limit(normalized_request: dict[str, Any]) -> int:
    request_value = normalized_request.get("llm_product_row_max_candidates")
    if request_value not in (None, ""):
        return _parse_non_negative_int(
            request_value,
            field_name="llm_product_row_max_candidates",
        )

    env_value = os.environ.get("TGSA_LLM_PRODUCT_ROW_MAX_CANDIDATES", "").strip()
    if env_value:
        return _parse_non_negative_int(
            env_value,
            field_name="TGSA_LLM_PRODUCT_ROW_MAX_CANDIDATES",
        )

    return DEFAULT_PRODUCT_ROW_MAX_CANDIDATES_PER_RUN


def _parse_positive_int(raw_value: Any, *, field_name: str) -> int:
    parsed = _parse_non_negative_int(raw_value, field_name=field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return parsed


def _request_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _product_row_chunking_enabled(normalized_request: dict[str, Any]) -> bool:
    return _request_bool(
        normalized_request.get("llm_product_row_chunking_enabled")
        or normalized_request.get("llm_product_row_chunked")
    )


def _resolve_product_row_chunk_size(normalized_request: dict[str, Any], *, candidate_limit: int) -> int:
    request_value = normalized_request.get("llm_product_row_chunk_size")
    if request_value in (None, ""):
        return max(1, candidate_limit)
    return _parse_positive_int(request_value, field_name="llm_product_row_chunk_size")


def _candidate_order_fingerprint(candidate_identities: list[dict[str, str]]) -> str:
    return _compact_hash(
        {
            "version": PRODUCT_ROW_CHUNK_STATE_VERSION,
            "candidate_identities": candidate_identities,
        }
    )


def _candidate_identity_by_id(candidate_identities: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for identity in candidate_identities:
        if not isinstance(identity, dict):
            continue
        candidate_id = _as_text(identity.get("candidate_id"))
        if not candidate_id:
            continue
        by_id[candidate_id] = {
            "candidate_id": candidate_id,
            "schema_name": _as_text(identity.get("schema_name")),
            "input_fingerprint": _as_text(identity.get("input_fingerprint")),
        }
    return by_id


def _product_row_candidate_mismatch_evidence(
    *,
    saved_candidate_ids: list[str],
    current_candidate_ids: list[str],
    saved_candidate_identities: list[dict[str, str]],
    current_candidate_identities: list[dict[str, str]],
    saved_candidate_order_fingerprint: str,
    current_candidate_order_fingerprint: str,
) -> dict[str, Any]:
    saved_id_set = set(saved_candidate_ids)
    current_id_set = set(current_candidate_ids)
    saved_by_id = _candidate_identity_by_id(saved_candidate_identities)
    current_by_id = _candidate_identity_by_id(current_candidate_identities)
    changed_candidate_ids = [
        candidate_id
        for candidate_id in saved_candidate_ids
        if candidate_id in current_id_set and saved_by_id.get(candidate_id) != current_by_id.get(candidate_id)
    ]
    first_mismatch_index: int | None = None
    for index in range(max(len(saved_candidate_ids), len(current_candidate_ids))):
        saved_id = saved_candidate_ids[index] if index < len(saved_candidate_ids) else ""
        current_id = current_candidate_ids[index] if index < len(current_candidate_ids) else ""
        if saved_id != current_id:
            first_mismatch_index = index
            break
    return {
        "saved_candidate_total": len(saved_candidate_ids),
        "current_candidate_total": len(current_candidate_ids),
        "saved_candidate_order_fingerprint": saved_candidate_order_fingerprint,
        "current_candidate_order_fingerprint": current_candidate_order_fingerprint,
        "missing_candidate_ids": [candidate_id for candidate_id in saved_candidate_ids if candidate_id not in current_id_set],
        "unexpected_candidate_ids": [candidate_id for candidate_id in current_candidate_ids if candidate_id not in saved_id_set],
        "changed_candidate_ids": changed_candidate_ids,
        "first_mismatch_index": first_mismatch_index,
        "can_retry_same_continuation_state": False,
        "safe_repair_contract": "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required",
    }


def _product_row_candidate_ids(candidates: list["Candidate"]) -> list[str]:
    return [candidate.entity_id for candidate in candidates]


def _product_row_candidate_identities(candidates: list["Candidate"]) -> list[dict[str, str]]:
    return [
        {
            "candidate_id": candidate.entity_id,
            "schema_name": candidate.schema_name,
            "input_fingerprint": _compact_hash(candidate.input_payload),
        }
        for candidate in candidates
    ]


def _normalize_fetch_freeze_key(raw_value: Any) -> str:
    value = _as_text(raw_value).strip().lower()
    if not value:
        return ""
    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    value = re.sub(r"^https?://t\.me/", "", value, flags=re.IGNORECASE)
    if value.startswith("s/"):
        value = value[2:]
    if value.startswith("@"):
        value = value[1:]
    parts = [part for part in value.split("/") if part]
    return parts[0] if parts else value


def _positive_int_or_none(raw_value: Any) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        value = int(str(raw_value).strip())
    except Exception:
        return None
    return value if value > 0 else None


def _raw_fetch_freeze_sources(raw_freeze: Any) -> list[dict[str, Any]]:
    if isinstance(raw_freeze, dict):
        raw_sources = raw_freeze.get("sources")
        if isinstance(raw_sources, list):
            return [source for source in raw_sources if isinstance(source, dict)]
        if isinstance(raw_sources, dict):
            return [source for source in raw_sources.values() if isinstance(source, dict)]
    if isinstance(raw_freeze, list):
        return [source for source in raw_freeze if isinstance(source, dict)]
    return []


def _product_row_fetch_freeze_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized_request = payload.get("normalized_request") if isinstance(payload.get("normalized_request"), dict) else {}
    fetch_summary = payload.get("fetch_summary") if isinstance(payload.get("fetch_summary"), dict) else {}
    raw_freeze_candidates = [
        normalized_request.get("llm_product_row_fetch_freeze"),
        payload.get("product_row_fetch_freeze"),
        fetch_summary.get("product_row_fetch_freeze"),
    ]
    sources: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, int]] = set()
    for raw_freeze in raw_freeze_candidates:
        for raw_source in _raw_fetch_freeze_sources(raw_freeze):
            if raw_source.get("exact_message_request") is True:
                continue
            upper_message_id = _positive_int_or_none(
                raw_source.get("upper_message_id")
                if raw_source.get("upper_message_id") not in (None, "")
                else raw_source.get("max_message_id")
            )
            if upper_message_id is None:
                continue
            source_key = _as_text(raw_source.get("source_key"))
            target_key = _as_text(raw_source.get("target_key"))
            telegram_public = _normalize_fetch_freeze_key(raw_source.get("telegram_public") or raw_source.get("telegram_target"))
            identity = (source_key, target_key, upper_message_id)
            if identity in seen_keys:
                continue
            seen_keys.add(identity)
            sources.append(
                {
                    "version": PRODUCT_ROW_FETCH_FREEZE_VERSION,
                    "source_key": source_key,
                    "target_key": target_key,
                    "target_lookup_key": _as_text(raw_source.get("target_lookup_key")),
                    "telegram_public": telegram_public,
                    "telegram_target": _as_text(raw_source.get("telegram_target")),
                    "exact_message_request": False,
                    "upper_message_id": upper_message_id,
                    "max_message_id_applied": _positive_int_or_none(raw_source.get("max_message_id_applied")),
                    "newer_posts_skipped": int(_positive_int_or_none(raw_source.get("newer_posts_skipped")) or 0),
                    "posts_emitted": int(_positive_int_or_none(raw_source.get("posts_emitted")) or 0),
                    "cutoff_utc": _as_text(raw_source.get("cutoff_utc")),
                    "cutoff_utc_source": _as_text(raw_source.get("cutoff_utc_source")),
                    "oldest_post_utc": _as_text(raw_source.get("oldest_post_utc")),
                    "lower_message_id": _positive_int_or_none(raw_source.get("lower_message_id")),
                    "lower_message_id_applied": _positive_int_or_none(raw_source.get("lower_message_id_applied")),
                    "newest_post_utc": _as_text(raw_source.get("newest_post_utc")),
                    "stopped_reason": _as_text(raw_source.get("stopped_reason")),
                }
            )
    sources.sort(key=lambda source: (source.get("source_key") or "", source.get("target_key") or "", source["upper_message_id"]))
    return {
        "version": PRODUCT_ROW_FETCH_FREEZE_VERSION,
        "sources": sources,
        "source_count": len(sources),
    }


def _fetch_freeze_lookup_sources(fetch_freeze: dict[str, Any]) -> list[dict[str, Any]]:
    return _raw_fetch_freeze_sources(fetch_freeze)


def _fetch_freeze_missing_lower_bound_sources(fetch_freeze: dict[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for source in _fetch_freeze_lookup_sources(fetch_freeze):
        if source.get("exact_message_request") is True:
            continue
        upper_message_id = _positive_int_or_none(source.get("upper_message_id"))
        if upper_message_id is None:
            continue
        if (
            _as_text(source.get("cutoff_utc"))
            or _as_text(source.get("oldest_post_utc"))
            or _positive_int_or_none(source.get("lower_message_id")) is not None
        ):
            continue
        missing.append(
            {
                "source_key": _as_text(source.get("source_key")),
                "target_key": _as_text(source.get("target_key")),
                "target_lookup_key": _as_text(source.get("target_lookup_key")),
                "telegram_public": _as_text(source.get("telegram_public")),
                "upper_message_id": upper_message_id,
                "required_lower_bound_fields": ["cutoff_utc", "oldest_post_utc", "lower_message_id"],
            }
        )
    return missing


def _extract_telegram_message_ref(raw_value: Any) -> tuple[str, int | None]:
    value = _as_text(raw_value).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not value:
        return "", None
    url_match = re.match(r"^https?://t\.me/(?:s/)?([^/?#]+)/(\d+)$", value, flags=re.IGNORECASE)
    handle_match = re.match(r"^@([^/?#]+)/(\d+)$", value)
    match = url_match or handle_match
    if not match:
        return "", None
    return _normalize_fetch_freeze_key(match.group(1)), _positive_int_or_none(match.group(2))


def _offer_evidence_message_refs(
    offer: dict[str, Any],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[tuple[set[str], int, bool]]:
    refs: list[tuple[set[str], int, bool]] = []
    for raw_post_id in _uniq_str_list(offer.get("evidence_raw_post_ids")):
        raw_post = raw_post_map.get(raw_post_id)
        if not isinstance(raw_post, dict):
            continue
        message_id = _positive_int_or_none(raw_post.get("message_id"))
        if message_id is None:
            continue
        keys = {
            _normalize_fetch_freeze_key(raw_post.get("_source_key")),
            _normalize_fetch_freeze_key(raw_post.get("_target_key")),
            _normalize_fetch_freeze_key(raw_post.get("_telegram_target_input")),
            _normalize_fetch_freeze_key(raw_post.get("chat_username")),
            _normalize_fetch_freeze_key(raw_post.get("telegram_public")),
        }
        keys.discard("")
        refs.append((keys, message_id, bool(raw_post.get("_exact_message_request"))))
    for field_name in ("latest_post_url", "source_anchor_text"):
        public_key, message_id = _extract_telegram_message_ref(offer.get(field_name))
        if public_key and message_id is not None:
            refs.append(({public_key}, message_id, False))
    return refs


def _offer_exceeds_fetch_freeze(
    offer: dict[str, Any],
    raw_post_map: dict[str, dict[str, Any]],
    fetch_freeze: dict[str, Any],
) -> bool:
    refs = _offer_evidence_message_refs(offer, raw_post_map)
    if not refs:
        return False
    for source in _fetch_freeze_lookup_sources(fetch_freeze):
        upper_message_id = _positive_int_or_none(source.get("upper_message_id"))
        if upper_message_id is None or source.get("exact_message_request") is True:
            continue
        source_keys = {
            _normalize_fetch_freeze_key(source.get("source_key")),
            _normalize_fetch_freeze_key(source.get("target_key")),
            _normalize_fetch_freeze_key(source.get("target_lookup_key")),
            _normalize_fetch_freeze_key(source.get("telegram_public")),
            _normalize_fetch_freeze_key(source.get("telegram_target")),
        }
        source_keys.discard("")
        if not source_keys:
            continue
        for ref_keys, message_id, exact_message_request in refs:
            if exact_message_request:
                continue
            if ref_keys.intersection(source_keys) and message_id > upper_message_id:
                return True
    return False


def _filter_product_row_candidates_for_fetch_freeze(
    *,
    candidates: list["Candidate"],
    offers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
    fetch_freeze: dict[str, Any],
    state_candidate_ids: list[str],
) -> tuple[list["Candidate"], list[str]]:
    if not state_candidate_ids or not _fetch_freeze_lookup_sources(fetch_freeze):
        return candidates, []
    state_candidate_id_set = set(state_candidate_ids)
    kept: list[Candidate] = []
    excluded_ids: list[str] = []
    for candidate in candidates:
        if candidate.entity_id in state_candidate_id_set:
            kept.append(candidate)
            continue
        offer = offers_by_key.get(candidate.entity_id)
        if offer is not None and _offer_exceeds_fetch_freeze(offer, raw_post_map, fetch_freeze):
            excluded_ids.append(candidate.entity_id)
            _apply_product_row_policy_drop(offer, "product_row_fetch_freeze_excluded_newer_post")
            continue
        kept.append(candidate)
    return kept, excluded_ids


def _stable_token_value(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _product_row_continuation_token(state: dict[str, Any]) -> str:
    return _compact_hash(
        {
            "version": state.get("version"),
            "candidate_order_fingerprint": state.get("candidate_order_fingerprint"),
            "fetch_freeze": _stable_token_value(state.get("fetch_freeze") or {}),
            "processed_candidate_ids": state.get("processed_candidate_ids") or [],
            "successful_candidate_ids": state.get("successful_candidate_ids") or [],
            "failed_candidate_ids": state.get("failed_candidate_ids") or [],
            "skipped_candidate_ids": state.get("skipped_candidate_ids") or [],
            "next_cursor": state.get("next_cursor"),
            "coverage_status": state.get("coverage_status"),
        }
    )


def _product_row_state_path(normalized_request: dict[str, Any]) -> str:
    return normalize_text(_as_text(normalized_request.get("llm_product_row_continuation_state_path")))


def _load_product_row_chunk_state(normalized_request: dict[str, Any]) -> dict[str, Any]:
    inline_state = normalized_request.get("llm_product_row_continuation_state")
    if isinstance(inline_state, dict):
        return copy.deepcopy(inline_state)

    state_path = _product_row_state_path(normalized_request)
    if not state_path:
        return {}
    path = Path(state_path)
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    return loaded if isinstance(loaded, dict) else {}


def _write_product_row_chunk_state(state: dict[str, Any], state_path: str) -> None:
    if not state_path:
        return
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compact_json(state, pretty=True) + "\n", encoding="utf-8")


def _empty_product_row_chunk_state(
    *,
    run_id: str,
    candidate_ids: list[str],
    candidate_identities: list[dict[str, str]],
    candidate_limit: int,
    chunk_size: int,
    state_path: str,
    fetch_freeze: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": PRODUCT_ROW_CHUNK_STATE_VERSION,
        "run_id": run_id,
        "processor_version": PROCESSOR_VERSION,
        "candidate_total": len(candidate_ids),
        "candidate_limit": candidate_limit,
        "chunk_size": chunk_size,
        "candidate_order_fingerprint": _candidate_order_fingerprint(candidate_identities),
        "fetch_freeze": copy.deepcopy(fetch_freeze),
        "fetch_freeze_excluded_candidate_ids": [],
        "candidate_ids": candidate_ids,
        "candidate_identities": candidate_identities,
        "processed_candidate_ids": [],
        "successful_candidate_ids": [],
        "failed_candidate_ids": [],
        "skipped_candidate_ids": [],
        "next_cursor": 0,
        "coverage_status": "not_started",
        "continuation_state_path": state_path,
        "accepted_patches": [],
        "audit_only_patches": [],
        "audit_enrichment_rows": [],
        "stage_breakdown": _empty_stage_breakdown(),
        "budget": _empty_budget_state(),
    }


def _validated_product_row_chunk_state(
    *,
    raw_state: dict[str, Any],
    run_id: str,
    candidate_ids: list[str],
    candidate_identities: list[dict[str, str]],
    candidate_limit: int,
    chunk_size: int,
    state_path: str,
    fetch_freeze: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if not raw_state:
        state = _empty_product_row_chunk_state(
            run_id=run_id,
            candidate_ids=candidate_ids,
            candidate_identities=candidate_identities,
            candidate_limit=candidate_limit,
            chunk_size=chunk_size,
            state_path=state_path,
            fetch_freeze=fetch_freeze,
        )
        state["continuation_token"] = _product_row_continuation_token(state)
        return state, ""

    expected_fingerprint = _candidate_order_fingerprint(candidate_identities)
    if raw_state.get("version") != PRODUCT_ROW_CHUNK_STATE_VERSION:
        return raw_state, "llm_product_row_continuation_state_version_mismatch"
    missing_lower_bound_sources = _fetch_freeze_missing_lower_bound_sources(
        raw_state.get("fetch_freeze") if isinstance(raw_state.get("fetch_freeze"), dict) else {}
    )
    if missing_lower_bound_sources:
        state = copy.deepcopy(raw_state)
        state["fetch_freeze_missing_lower_bound_sources"] = missing_lower_bound_sources
        return state, "llm_product_row_continuation_state_missing_fetch_lower_bound"
    saved_candidate_ids = [_as_text(candidate_id) for candidate_id in raw_state.get("candidate_ids", []) or []]
    saved_candidate_identities = [
        identity
        for identity in raw_state.get("candidate_identities", []) or []
        if isinstance(identity, dict)
    ]
    candidate_mismatch_evidence = _product_row_candidate_mismatch_evidence(
        saved_candidate_ids=saved_candidate_ids,
        current_candidate_ids=candidate_ids,
        saved_candidate_identities=saved_candidate_identities,
        current_candidate_identities=candidate_identities,
        saved_candidate_order_fingerprint=_as_text(raw_state.get("candidate_order_fingerprint")),
        current_candidate_order_fingerprint=expected_fingerprint,
    )
    if raw_state.get("candidate_order_fingerprint") != expected_fingerprint:
        state = copy.deepcopy(raw_state)
        state["candidate_mismatch_evidence"] = candidate_mismatch_evidence
        return state, "llm_product_row_continuation_state_candidate_mismatch"
    if saved_candidate_ids != candidate_ids:
        state = copy.deepcopy(raw_state)
        state["candidate_mismatch_evidence"] = candidate_mismatch_evidence
        return state, "llm_product_row_continuation_state_candidate_mismatch"
    if saved_candidate_identities != candidate_identities:
        state = copy.deepcopy(raw_state)
        state["candidate_mismatch_evidence"] = candidate_mismatch_evidence
        return state, "llm_product_row_continuation_state_candidate_mismatch"
    requested_token = normalize_text(_as_text(raw_state.get("continuation_token")))
    if requested_token and requested_token != _product_row_continuation_token(raw_state):
        return raw_state, "llm_product_row_continuation_state_token_mismatch"
    if normalize_text(_as_text(raw_state.get("coverage_status"))) == "failed":
        return raw_state, "llm_product_row_continuation_state_failed"
    if raw_state.get("failed_candidate_ids"):
        return raw_state, "llm_product_row_continuation_state_failed"

    processed_ids = list(raw_state.get("processed_candidate_ids") or [])
    if len(processed_ids) != len(set(processed_ids)):
        return raw_state, "llm_product_row_continuation_state_duplicate_processed_ids"
    if processed_ids != candidate_ids[: len(processed_ids)]:
        return raw_state, "llm_product_row_continuation_state_non_contiguous_cursor"

    state = copy.deepcopy(raw_state)
    state["run_id"] = state.get("run_id") or run_id
    state["processor_version"] = PROCESSOR_VERSION
    state["candidate_total"] = len(candidate_ids)
    state["candidate_limit"] = candidate_limit
    state["chunk_size"] = chunk_size
    state["fetch_freeze"] = copy.deepcopy(raw_state.get("fetch_freeze") or fetch_freeze)
    state["fetch_freeze_excluded_candidate_ids"] = list(raw_state.get("fetch_freeze_excluded_candidate_ids") or [])
    state["candidate_ids"] = candidate_ids
    state["candidate_identities"] = candidate_identities
    state["next_cursor"] = len(processed_ids)
    state["continuation_state_path"] = state_path or normalize_text(_as_text(state.get("continuation_state_path")))
    return state, ""


def _apply_product_row_chunk_state_to_runtime(
    *,
    state: dict[str, Any],
    offers_by_key: dict[str, dict[str, Any]],
    stage_breakdown: dict[str, dict[str, Any]],
    budget: dict[str, Any],
    audit_rows: list[dict[str, Any]],
    accepted_patches: list[dict[str, Any]],
    audit_only_patches: list[dict[str, Any]],
) -> None:
    product_breakdown = state.get("stage_breakdown", {}).get("llm_product_row_shape")
    if isinstance(product_breakdown, dict):
        for key, value in product_breakdown.items():
            if key in stage_breakdown["llm_product_row_shape"]:
                stage_breakdown["llm_product_row_shape"][key] = int(value or 0)

    prior_budget = state.get("budget") if isinstance(state.get("budget"), dict) else {}
    for key, value in prior_budget.items():
        if key not in budget:
            continue
        if isinstance(budget[key], bool):
            budget[key] = bool(value)
        elif isinstance(budget[key], (int, float)):
            budget[key] = value
        else:
            budget[key] = value

    for row in state.get("audit_enrichment_rows") or []:
        if isinstance(row, dict):
            audit_rows.append(copy.deepcopy(row))
    for patch_record in state.get("accepted_patches") or []:
        if not isinstance(patch_record, dict):
            continue
        accepted_patches.append(copy.deepcopy(patch_record))
        if patch_record.get("stage") != "llm_product_row_shape":
            continue
        offer = offers_by_key.get(_as_text(patch_record.get("entity_id")))
        patch = patch_record.get("patch") if isinstance(patch_record.get("patch"), dict) else {}
        if offer is not None and patch:
            _apply_offer_patch(offer, patch)
    for patch_record in state.get("audit_only_patches") or []:
        if isinstance(patch_record, dict):
            audit_only_patches.append(copy.deepcopy(patch_record))


def _refresh_product_row_chunk_state(
    *,
    state: dict[str, Any],
    candidate_ids: list[str],
    candidate_identities: list[dict[str, str]],
    chunk_size: int,
    candidate_limit: int,
    state_path: str,
    fetch_freeze: dict[str, Any],
    fetch_freeze_excluded_candidate_ids: list[str],
    stage_breakdown: dict[str, dict[str, Any]],
    budget: dict[str, Any],
    audit_rows: list[dict[str, Any]],
    accepted_patches: list[dict[str, Any]],
    audit_only_patches: list[dict[str, Any]],
    quota_blocker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    successful_ids = [
        _as_text(patch.get("entity_id"))
        for patch in accepted_patches
        if isinstance(patch, dict) and patch.get("stage") == "llm_product_row_shape" and _as_text(patch.get("entity_id"))
    ]
    failed_ids = [
        _as_text(patch.get("entity_id"))
        for patch in audit_only_patches
        if isinstance(patch, dict) and patch.get("stage") == "llm_product_row_shape" and _as_text(patch.get("entity_id"))
    ]
    processed_ids = [candidate_id for candidate_id in candidate_ids if candidate_id in set(successful_ids + failed_ids)]
    quota_blocker_payload = copy.deepcopy(quota_blocker) if isinstance(quota_blocker, dict) else {}
    coverage_status = (
        "failed"
        if failed_ids or int(stage_breakdown["llm_product_row_shape"].get("coverage_failures") or 0) > 0
        else "blocked" if quota_blocker_payload
        else "complete" if len(processed_ids) == len(candidate_ids) else "continuation_required"
    )
    refreshed = {
        **copy.deepcopy(state),
        "version": PRODUCT_ROW_CHUNK_STATE_VERSION,
        "candidate_total": len(candidate_ids),
        "candidate_limit": candidate_limit,
        "chunk_size": chunk_size,
        "candidate_order_fingerprint": _candidate_order_fingerprint(candidate_identities),
        "fetch_freeze": copy.deepcopy(state.get("fetch_freeze") or fetch_freeze),
        "fetch_freeze_excluded_candidate_ids": sorted(set(fetch_freeze_excluded_candidate_ids)),
        "candidate_ids": candidate_ids,
        "candidate_identities": candidate_identities,
        "processed_candidate_ids": processed_ids,
        "successful_candidate_ids": successful_ids,
        "failed_candidate_ids": failed_ids,
        "skipped_candidate_ids": [],
        "next_cursor": len(processed_ids),
        "coverage_status": coverage_status,
        "continuation_state_path": state_path,
        "accepted_patches": copy.deepcopy(accepted_patches),
        "audit_only_patches": copy.deepcopy(audit_only_patches),
        "audit_enrichment_rows": copy.deepcopy(audit_rows),
        "stage_breakdown": copy.deepcopy(stage_breakdown),
        "budget": copy.deepcopy(budget),
    }
    if quota_blocker_payload:
        refreshed["quota_blocker"] = quota_blocker_payload
        refreshed["can_retry_same_continuation_state"] = True
        refreshed["safe_retry_contract"] = PRODUCT_ROW_QUOTA_RETRY_CONTRACT
    else:
        refreshed.pop("quota_blocker", None)
        refreshed.pop("can_retry_same_continuation_state", None)
        refreshed.pop("safe_retry_contract", None)
    refreshed["continuation_token"] = _product_row_continuation_token(refreshed)
    return refreshed


def _product_row_chunk_summary(
    *,
    state: dict[str, Any],
    candidate_ids: list[str],
    chunk_start_index: int,
    chunk_end_index: int,
    chunk_size: int,
    candidate_limit: int,
    state_path: str,
    include_inline_state: bool,
) -> dict[str, Any]:
    processed_count = int(state.get("next_cursor") or 0)
    remaining_count = max(0, len(candidate_ids) - processed_count)
    summary: dict[str, Any] = {
        "enabled": True,
        "state_version": PRODUCT_ROW_CHUNK_STATE_VERSION,
        "status": state.get("coverage_status") or "continuation_required",
        "candidate_total": len(candidate_ids),
        "candidate_limit": candidate_limit,
        "chunk_size": chunk_size,
        "candidate_order_fingerprint": state.get("candidate_order_fingerprint") or "",
        "fetch_freeze": copy.deepcopy(state.get("fetch_freeze") or {}),
        "fetch_freeze_excluded_candidate_ids": list(state.get("fetch_freeze_excluded_candidate_ids") or []),
        "chunk_start_index": chunk_start_index,
        "chunk_end_index": chunk_end_index,
        "chunk_candidate_ids": candidate_ids[chunk_start_index:chunk_end_index],
        "processed_candidate_count": processed_count,
        "remaining_candidate_count": remaining_count,
        "successful_decisions": len(state.get("successful_candidate_ids") or []),
        "failures": len(state.get("failed_candidate_ids") or []),
        "skips": len(state.get("skipped_candidate_ids") or []),
        "next_cursor": processed_count,
        "next_candidate_id": candidate_ids[processed_count] if processed_count < len(candidate_ids) else "",
        "continuation_token": state.get("continuation_token") or _product_row_continuation_token(state),
        "continuation_state_path": state_path,
        "aggregate_coverage_complete": processed_count == len(candidate_ids)
        and not state.get("failed_candidate_ids")
        and not state.get("skipped_candidate_ids"),
    }
    missing_lower_bound_sources = list(state.get("fetch_freeze_missing_lower_bound_sources") or [])
    if missing_lower_bound_sources:
        summary["fetch_freeze_missing_lower_bound_sources"] = copy.deepcopy(missing_lower_bound_sources)
        summary["safe_repair_contract"] = (
            "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required"
        )
    candidate_mismatch_evidence = state.get("candidate_mismatch_evidence")
    if isinstance(candidate_mismatch_evidence, dict) and candidate_mismatch_evidence:
        summary["candidate_mismatch_evidence"] = copy.deepcopy(candidate_mismatch_evidence)
        summary["safe_repair_contract"] = candidate_mismatch_evidence.get(
            "safe_repair_contract",
            "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required",
        )
    quota_blocker = state.get("quota_blocker")
    if isinstance(quota_blocker, dict) and quota_blocker:
        summary["quota_blocker"] = copy.deepcopy(quota_blocker)
        summary["can_retry_same_continuation_state"] = bool(
            state.get("can_retry_same_continuation_state", True)
        )
        summary["safe_retry_contract"] = _as_text(state.get("safe_retry_contract")) or PRODUCT_ROW_QUOTA_RETRY_CONTRACT
    if include_inline_state:
        summary["continuation_state"] = copy.deepcopy(state)
    return summary


def _progress_snapshot(progress: LlmProgress, monotonic: Callable[[], float]) -> dict[str, Any]:
    elapsed_seconds = max(0.0, monotonic() - progress.started_monotonic)
    return {
        "status": "timeout",
        "reason": "llm_total_timeout",
        "current_stage": progress.current_stage,
        "current_candidate_index": progress.current_candidate_index,
        "current_candidate_total": progress.current_candidate_total,
        "current_entity_type": progress.current_entity_type,
        "current_entity_id": progress.current_entity_id,
        "completed_candidates_total": progress.completed_candidates_total,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "total_timeout_seconds": progress.total_timeout_seconds,
    }


def _raise_if_total_timeout(progress: LlmProgress, monotonic: Callable[[], float]) -> None:
    if progress.total_timeout_seconds is None:
        return
    elapsed_seconds = monotonic() - progress.started_monotonic
    if elapsed_seconds >= progress.total_timeout_seconds:
        raise LlmTotalTimeout("llm_total_timeout")


def _product_row_chunk_should_stop_before_timeout(
    *,
    progress: LlmProgress,
    monotonic: Callable[[], float],
    chunk_start_completed_total: int,
) -> bool:
    if progress.total_timeout_seconds is None:
        return False
    processed_in_this_chunk = max(0, progress.completed_candidates_total - chunk_start_completed_total)
    if processed_in_this_chunk <= 0:
        return False
    elapsed_seconds = max(0.0, monotonic() - progress.started_monotonic)
    remaining_seconds = progress.total_timeout_seconds - elapsed_seconds
    reserve_seconds = _product_row_chunk_timeout_reserve_seconds(progress.total_timeout_seconds)
    average_seconds_per_processed_candidate = elapsed_seconds / max(1, progress.completed_candidates_total)
    return remaining_seconds <= reserve_seconds + average_seconds_per_processed_candidate


def _build_timeout_audit_row(
    *,
    run_id: str,
    model_name: str,
    progress: dict[str, Any],
) -> dict[str, Any]:
    current_stage = _as_text(progress.get("current_stage")) or "llm_total_timeout"
    current_entity_type = _as_text(progress.get("current_entity_type")) or "workflow"
    current_entity_id = _as_text(progress.get("current_entity_id")) or "llm_post_merge"
    reason_text = (
        "Post-merge LLM helper reached total wall-clock timeout "
        f"at stage={current_stage}, entity={current_entity_id}."
    )
    return {
        "audit_row_id": f"audit:{run_id or 'unknown'}:llm_total_timeout:{_compact_hash(progress)[:16]}",
        "run_id": run_id,
        "entity_type": current_entity_type,
        "entity_id": current_entity_id,
        "stage": current_stage,
        "processor_type": "deterministic",
        "processor_version": PROCESSOR_VERSION,
        "status": "error",
        "decision_code": "llm_total_timeout",
        "created_at_utc": os.environ.get("TGSA_FIXED_NOW_UTC") or _iso_now_utc(),
        "input_fingerprint": "",
        "output_patch_json": "{}",
        "reason_text": reason_text[:240],
        "source_raw_post_ids": [],
        "attempt_number": 0,
        "review_required": True,
        "model_name": model_name,
        "prompt_version": "llm_total_timeout",
        "confidence": None,
        "latency_ms": None,
        "tokens_input": 0,
        "tokens_output": 0,
        "cost_estimate_usd": 0.0,
        "response_excerpt": compact_json(progress)[:240],
        "upstream_audit_row_id": "",
    }


def _build_product_row_scale_block_audit_row(
    *,
    run_id: str,
    model_name: str,
    candidate_total: int,
    candidate_limit: int,
) -> dict[str, Any]:
    reason_text = (
        "Product-row LLM candidate pool exceeds the per-run guard "
        f"({candidate_total}>{candidate_limit}); public publication requires chunk/resume."
    )
    evidence = {
        "reason": "llm_product_row_scale_blocked",
        "candidate_total": candidate_total,
        "candidate_limit": candidate_limit,
    }
    return {
        "audit_row_id": f"audit:{run_id or 'unknown'}:llm_product_row_scale_blocked:{_compact_hash(evidence)[:16]}",
        "run_id": run_id,
        "entity_type": "workflow",
        "entity_id": "llm_post_merge",
        "stage": "llm_product_row_shape",
        "processor_type": "deterministic",
        "processor_version": PROCESSOR_VERSION,
        "status": "blocked",
        "decision_code": "llm_product_row_scale_blocked",
        "created_at_utc": os.environ.get("TGSA_FIXED_NOW_UTC") or _iso_now_utc(),
        "input_fingerprint": "",
        "output_patch_json": "{}",
        "reason_text": reason_text[:240],
        "source_raw_post_ids": [],
        "attempt_number": 0,
        "review_required": True,
        "model_name": model_name,
        "prompt_version": "llm_product_row_scale_guard",
        "confidence": None,
        "latency_ms": None,
        "tokens_input": 0,
        "tokens_output": 0,
        "cost_estimate_usd": 0.0,
        "response_excerpt": compact_json(evidence)[:240],
        "upstream_audit_row_id": "",
    }


def _response_max_output_tokens_for_schema(schema_name: str) -> int:
    normalized = normalize_text(schema_name).lower()
    if normalized.startswith("tgss_product_row"):
        return PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKENS
    if normalized.startswith("tgss_category_"):
        return CATEGORY_REFINE_RESPONSE_MAX_OUTPUT_TOKENS
    return RESPONSE_MAX_OUTPUT_TOKENS


def _response_max_output_token_staircase_for_schema(schema_name: str) -> tuple[int, ...]:
    normalized = normalize_text(schema_name).lower()
    if normalized.startswith("tgss_product_row"):
        return PRODUCT_ROW_RESPONSE_MAX_OUTPUT_TOKEN_STAIRCASE
    return (_response_max_output_tokens_for_schema(schema_name),)


class _LiveResponsesTransport:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        organization: str | None,
        project: str | None,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.organization = organization
        self.project = project
        self.timeout_seconds = timeout_seconds

    def create(
        self,
        *,
        model: str,
        input_messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int | None = None,
    ) -> TransportResponse:
        body = {
            "model": model,
            "store": False,
            "input": input_messages,
            "max_output_tokens": max_output_tokens or _response_max_output_tokens_for_schema(schema_name),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        return create_response(
            api_key=self.api_key,
            body=body,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            organization=self.organization,
            project=self.project,
        )


class _MockResponsesTransport:
    def __init__(self, mock_payload: dict[str, Any]) -> None:
        responses = mock_payload.get("responses")
        if not isinstance(responses, dict):
            raise ValueError("Mock response payload must include an object at responses.")
        self.responses = responses
        self.response_positions: dict[str, int] = {}

    def create(
        self,
        *,
        model: str,
        input_messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        max_output_tokens: int | None = None,
    ) -> TransportResponse:
        _ = input_messages
        _ = schema
        _ = model
        entry = self.responses.get(schema_name)
        if entry is None:
            raise ResponseTransportError(
                f"Mock response not found for schema_name={schema_name}.",
                retryable=False,
            )
        if isinstance(entry, list):
            position = self.response_positions.get(schema_name, 0)
            if position >= len(entry):
                raise ResponseTransportError(
                    f"Mock response list exhausted for schema_name={schema_name}.",
                    retryable=False,
                )
            self.response_positions[schema_name] = position + 1
            entry = entry[position]
        if not isinstance(entry, dict):
            raise ResponseTransportError(
                f"Mock response entry for schema_name={schema_name} must be an object.",
                retryable=False,
            )
        expected_max_output_tokens = entry.get("expected_max_output_tokens")
        if expected_max_output_tokens is not None and int(expected_max_output_tokens) != int(max_output_tokens or 0):
            raise ResponseTransportError(
                (
                    f"Mock response for schema_name={schema_name} expected "
                    f"max_output_tokens={expected_max_output_tokens}, got {max_output_tokens}."
                ),
                retryable=False,
            )
        if "error_message" in entry:
            raise ResponseTransportError(
                str(entry.get("error_message") or "Mock transport error."),
                retryable=bool(entry.get("retryable", False)),
                status_code=int(entry.get("status_code")) if entry.get("status_code") else None,
                response_body=_as_text(entry.get("response_body"))[:4000],
                request_id=_as_text(entry.get("request_id")),
                usage=entry.get("usage") if isinstance(entry.get("usage"), dict) else None,
                error_type=_as_text(entry.get("error_type")),
                error_code=_as_text(entry.get("error_code")),
            )
        raw_payload = entry.get("payload")
        if raw_payload is not None:
            if not isinstance(raw_payload, dict):
                raise ResponseTransportError(
                    f"Mock response payload for schema_name={schema_name} must be an object.",
                    retryable=False,
                )
            return TransportResponse(
                payload=copy.deepcopy(raw_payload),
                latency_ms=int(entry.get("latency_ms") or 42),
                request_id=_as_text(entry.get("request_id")) or f"mock-req-{schema_name}",
            )
        decision = entry.get("decision")
        if not isinstance(decision, dict):
            raise ResponseTransportError(
                f"Mock response entry for schema_name={schema_name} is missing decision.",
                retryable=False,
            )
        usage = entry.get("usage")
        if not isinstance(usage, dict):
            usage = {
                "input_tokens": 650,
                "output_tokens": 130,
            }
        payload = {
            "id": f"mock-{schema_name}",
            "model": entry.get("model") or DEFAULT_MODEL,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(decision, ensure_ascii=False),
                        }
                    ],
                }
            ],
            "usage": usage,
        }
        return TransportResponse(
            payload=payload,
            latency_ms=int(entry.get("latency_ms") or 42),
            request_id=f"mock-req-{schema_name}",
        )


def compact_json(payload: dict[str, Any], *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _compact_hash(payload: Any) -> str:
    return hashlib.sha1(compact_json(payload).encode("utf-8")).hexdigest()


def _safe_schema_name(prefix: str, entity_id: str) -> str:
    return f"{prefix}__{_compact_hash(entity_id)[:16]}"


def _tokenize(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(normalize_text(text))
        if len(token) >= 3 and not token.isdigit()
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _uniq_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = normalize_text(_as_text(item))
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _category_display_label(category_primary: Any) -> str:
    normalized = normalize_text(_as_text(category_primary)).lower()
    return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY.get(normalized, "")


def _normalize_category_display_label(value: Any) -> str:
    normalized = normalize_text(_as_text(value))
    if not normalized:
        return ""
    lowered = normalized.lower()
    if lowered in PRODUCT_CATEGORY_PRIMARY_BY_DISPLAY:
        category_primary = PRODUCT_CATEGORY_PRIMARY_BY_DISPLAY[lowered]
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY.get(category_primary, "")
    if lowered in PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY:
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY[lowered]
    return normalized if normalized in PRODUCT_CATEGORY_DISPLAY_SET else ""


def _format_contact_candidate_display(contact_type: str, value: str) -> str:
    normalized = normalize_text(value)
    if not normalized:
        return ""
    if contact_type == "phone":
        digits = normalize_phone(normalized)
        return f"+{digits}" if digits else ""
    if contact_type == "telegram_handle":
        handle = normalize_handle(normalized)
        return f"@{handle}" if handle else ""
    if contact_type in {"telegram_link", "website"}:
        return normalize_url(normalized)
    if contact_type == "email":
        return normalized.lower()
    return normalized


def _normalize_contact_candidate_display(value: Any) -> str:
    normalized = normalize_text(_as_text(value))
    if not normalized:
        return ""
    if URL_RE.search(normalized):
        return normalize_url(normalized)
    if PHONE_RE.search(normalized):
        digits = normalize_phone(normalized)
        return f"+{digits}" if digits else ""
    if normalized.startswith("@"):
        handle = normalize_handle(normalized)
        return f"@{handle}" if handle else ""
    if "@" in normalized and "." in normalized:
        return normalized.lower()
    return normalized


def _build_offer_contact_candidates(offer: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for candidate in (
        *(_format_contact_candidate_display("phone", value) for value in _uniq_str_list(offer.get("explicit_contact_snapshot_phones"))),
        *(_format_contact_candidate_display("telegram_handle", value) for value in _uniq_str_list(offer.get("explicit_contact_snapshot_telegram_handles"))),
        *(_format_contact_candidate_display("telegram_link", value) for value in _uniq_str_list(offer.get("explicit_contact_snapshot_telegram_links"))),
        _as_text(offer.get("contact_candidate_display")),
        *(_format_contact_candidate_display("email", value) for value in _uniq_str_list(offer.get("contact_snapshot_emails"))),
        *(_format_contact_candidate_display("website", value) for value in _uniq_str_list(offer.get("contact_snapshot_websites"))),
        *(_format_contact_candidate_display("telegram_handle", value) for value in _uniq_str_list(offer.get("author_fallback_telegram_handles"))),
        *(_format_contact_candidate_display("telegram_link", value) for value in _uniq_str_list(offer.get("author_fallback_telegram_links"))),
        *(_format_contact_candidate_display("phone", value) for value in _uniq_str_list(offer.get("author_fallback_phones"))),
    ):
        normalized = _normalize_contact_candidate_display(candidate)
        if normalized:
            candidates.append(normalized)
    return _uniq_str_list(candidates)


def _contains_any_phrase(text_lower: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text_lower for phrase in phrases)


def _count_phrase_hits(text_lower: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for phrase in phrases if phrase in text_lower)


def _starts_with_any(text_lower: str, prefixes: tuple[str, ...]) -> bool:
    return any(text_lower.startswith(prefix) for prefix in prefixes)


def _label_prefix_remainder(text: str, prefixes: tuple[str, ...]) -> str | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    lowered = normalized.lower()
    for prefix in prefixes:
        if lowered == prefix:
            return ""
        for separator in (":", " - ", " — ", " – "):
            marker = f"{prefix}{separator}"
            if lowered.startswith(marker):
                return normalize_text(normalized[len(marker) :]).strip(" ,;:—–-")
        marker = f"{prefix} "
        if lowered.startswith(marker):
            return normalize_text(normalized[len(marker) :]).strip(" ,;:—–-")
    return None


def _looks_like_address_only_label(text: Any) -> bool:
    remainder = _label_prefix_remainder(_as_text(text), PRODUCT_ADDRESS_LABEL_PREFIXES)
    return remainder is not None and bool(remainder)


def _looks_like_price_clause_label(text: Any) -> bool:
    remainder = _label_prefix_remainder(_as_text(text), PRODUCT_PRICE_CLAUSE_LABEL_PREFIXES)
    if remainder is None:
        return False
    if not remainder:
        return True
    lowered = remainder.lower()
    return (
        bool(PRICE_RE.search(remainder) or PRICE_FROM_RE.search(remainder))
        or "бесплат" in lowered
        or "free" in lowered
    )


def _looks_like_instruction_or_onboarding_label(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    if _starts_with_any(lowered, PRODUCT_INSTRUCTION_LABEL_PREFIXES):
        return True
    return (
        "testflight" in lowered
        or "beta" in lowered
        or "бета" in lowered
        or "app store" in lowered
    ) and ("пользовател" in lowered or "доступ" in lowered or "установ" in lowered)


def _looks_like_availability_or_inventory_label(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    return _starts_with_any(lowered, PRODUCT_AVAILABILITY_LABEL_NEGATIVE_PREFIXES) and any(
        hint in lowered for hint in PRODUCT_AVAILABILITY_LABEL_INVENTORY_HINTS
    )


def _looks_like_non_service_visible_label(text: Any) -> bool:
    return (
        _looks_like_address_only_label(text)
        or _looks_like_price_clause_label(text)
        or _looks_like_instruction_or_onboarding_label(text)
        or _looks_like_availability_or_inventory_label(text)
    )


def _service_label_signal_text(
    offer: dict[str, Any],
    candidate: str,
    salvaged_fragments: list[str] | None = None,
) -> str:
    product_details = _as_text(offer.get("product_row_details"))
    parts = [
        candidate,
        *(salvaged_fragments or []),
        product_details,
        " ".join(_uniq_str_list(offer.get("service_tags"))),
    ]
    return normalize_text(" ".join(part for part in parts if part)).lower()


def _label_looks_like_provider_or_brand_intro(candidate: str) -> bool:
    normalized = normalize_text(candidate)
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(phrase in lowered for phrase in PRODUCT_PROVIDER_INTRO_PHRASES):
        return True
    if lowered.startswith(
        (
            "надежный мастер",
            "надёжный мастер",
            "универсальный мастер",
            "сертифицированный ",
            "дипломированный ",
            "грязный ",
            "репетитор по",
            "консультация ",
            "я ",
            "меня зовут",
        )
    ):
        return True
    if " это " in lowered:
        return True
    head, separator, tail = normalized.partition(",")
    if separator and len(_tokenize(head)) <= 2:
        tail_lower = normalize_text(tail).lower()
        if any(
            marker in tail_lower
            for marker in ("мастер", "психолог", "репетитор", "маркетолог", "наставник", "консультац", "водител")
        ):
            return True
    tokens = _tokenize(normalized)
    return len(tokens) <= 3 and any(token in PRODUCT_BRAND_LABEL_TOKENS for token in tokens)


def _rewrite_short_service_label(label: str) -> str:
    normalized = normalize_text(label)
    if not normalized:
        return ""
    collapsed = normalize_text(normalized.replace("/", " "))
    rewritten = PRODUCT_SHORT_SERVICE_LABEL_REWRITES.get(collapsed.lower())
    return rewritten or _normalize_service_label_case(normalized)


def _label_looks_like_action_or_experience_statement(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered.startswith(("мой опыт", "моя практика", "мой путь")):
        return True
    head = lowered.split(maxsplit=1)[0]
    return bool(SERVICE_ACTION_HEAD_RE.fullmatch(head))


def _label_looks_like_slogan_or_promo(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _contains_any_phrase(lowered, PRODUCT_SLOGAN_OR_PROMO_LABEL_PHRASES):
        return True
    if any(marker in lowered for marker in ("всего за", "каждый день", "ежедневно")) and _looks_like_visa_run_context(lowered):
        return True
    return len(_tokenize(normalized)) >= 5 and any(marker in normalized for marker in "!?…")


def _looks_like_tool_rental_context(signal_text: str) -> bool:
    if "аренд" not in signal_text:
        return False
    return any(
        hint in signal_text
        for hint in ("электроинструмент", "инструмент", "дрел", "шуруповерт", "шуруповёрт", "перфоратор")
    )


def _looks_like_purchase_request_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if not any(phrase in lowered for phrase in PRODUCT_PURCHASE_REQUEST_PHRASES):
        return False
    return any(
        hint in lowered
        for hint in (
            "баллон",
            "co2",
            "инструмент",
            "bosch",
            "насадк",
            "плиткорез",
            "запчаст",
            "материал",
        )
    )


def _looks_like_tool_or_workspace_rental_request(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered or "аренд" not in lowered:
        return False
    if any(phrase in lowered for phrase in PRODUCT_OFFERING_RENTAL_PHRASES):
        return False
    if not any(phrase in lowered for phrase in PRODUCT_RENTAL_REQUEST_PHRASES):
        return False
    request_markers = (
        "где",
        "ищу",
        "нужн",
        "подскаж",
        "кто",
        "самостоятельн",
        "любитель",
        "запрос",
        "пользователь ищет",
    )
    return any(marker in lowered for marker in request_markers)


def _looks_like_goods_price_info_or_review(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if not any(phrase in lowered for phrase in PRODUCT_GOODS_INFO_PHRASES):
        return False
    goods_hit = any(
        hint in lowered
        for hint in (
            "инструмент",
            "bosch",
            "насадк",
            "баллон",
            "co2",
            "товар",
            "магазин",
            "цены",
            "скидк",
        )
    )
    service_hit = any(marker in lowered for marker in ("ремонт", "монтаж", "мастер", "услуг", "сервис"))
    return goods_hit and not service_hit


def _looks_like_complaint_or_problem_report(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if not any(phrase in lowered for phrase in PRODUCT_COMPLAINT_PROBLEM_PHRASES):
        return False
    provider_markers = ("предлага", "оказыва", "выполня", "мастер", "бригада", "услуг")
    return not any(marker in lowered for marker in provider_markers)


def _looks_like_furniture_made_to_order_context(signal_text: str) -> bool:
    return any(hint in signal_text for hint in ("изготовление мебели", "мебель на заказ", "кухни на заказ", "шкаф"))


def _looks_like_massage_context(signal_text: str) -> bool:
    return "массаж" in signal_text or "massage" in signal_text


def _looks_like_restaurant_context(signal_text: str) -> bool:
    return "ресторан" in signal_text or "restaurant" in signal_text


def _looks_like_visa_run_context(signal_text: str) -> bool:
    return any(marker in signal_text for marker in ("визаран", "виза ран", "visa run", "visaran"))


def _looks_like_auto_service_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if any(hint in lowered for hint in PRODUCT_AUTO_DETAILING_HINTS):
        return True
    if any(hint in lowered for hint in PRODUCT_AUTO_AC_HINTS):
        return True
    if any(hint in lowered for hint in PRODUCT_AUTO_INSPECTION_IMPORT_HINTS):
        return "авто" in lowered or "автомоб" in lowered or "машин" in lowered
    return False


def _looks_like_hvac_repair_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered or not any(marker in lowered for marker in ("кондиционер", "кондиционеров", "фреон", "хладагент")):
        return False
    if _looks_like_auto_service_context(lowered):
        return False
    return any(hint in lowered for hint in PRODUCT_HVAC_REPAIR_HINTS)


def _looks_like_aircon_cleaning_only_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered or not any(marker in lowered for marker in ("кондиционер", "кондиционеров")):
        return False
    if _looks_like_household_repair_master_context(lowered):
        return False
    cleaning_hit = any(marker in lowered for marker in ("чистк", "мойк", "фильтр", "турбин", "дезинфекц"))
    repair_hit = any(
        marker in lowered
        for marker in (
            "ремонт",
            "монтаж",
            "установ",
            "запуск",
            "настрой",
            "фреон",
            "хладагент",
            "заправ",
        )
    )
    return cleaning_hit and not repair_hit


def _looks_like_transport_delivery_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if _looks_like_auto_service_context(lowered):
        return False
    if any(hint in lowered for hint in PRODUCT_TRANSPORT_SERVICE_HINTS):
        return True
    if _looks_like_visa_run_context(lowered):
        return any(hint in lowered for hint in PRODUCT_VISARUN_TRANSPORT_HINTS)
    return False


def _looks_like_language_tutoring_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if not any(hint in lowered for hint in PRODUCT_LANGUAGE_TUTORING_HINTS):
        return False
    return any(marker in lowered for marker in ("репет", "преподав", "урок", "заняти", "подготов", "обуч"))


def _looks_like_medical_rehab_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if not any(hint in lowered for hint in PRODUCT_MEDICAL_REHAB_HINTS):
        return False
    training_markers = ("курс", "обучение", "учебн", "преподав", "тренинг")
    if any(marker in lowered for marker in training_markers) and not any(
        marker in lowered for marker in ("врач", "реабилитолог", "лфк", "физиотерап", "лечеб")
    ):
        return False
    return True


def _infer_service_meaning_label(
    offer: dict[str, Any],
    candidate: str,
    salvaged_fragments: list[str] | None = None,
) -> str:
    signal_text = _service_label_signal_text(offer, candidate, salvaged_fragments)
    if not signal_text:
        return ""

    if _looks_like_auto_service_context(signal_text):
        if any(hint in signal_text for hint in PRODUCT_AUTO_DETAILING_HINTS):
            return "Детейлинг и полировка автомобилей"
        if any(hint in signal_text for hint in PRODUCT_AUTO_AC_HINTS):
            return "Обслуживание автокондиционеров"
        if any(hint in signal_text for hint in ("пригон", "из европы", "из германии", "из словении", "доставка авто")):
            return "Подбор и доставка авто"
        if any(hint in signal_text for hint in ("осмотр авто", "подбор авто", "техпровер")):
            return "Осмотр и подбор авто"
        return "Автоуслуги"
    if _looks_like_hvac_repair_context(signal_text):
        return "Обслуживание кондиционеров"
    if _looks_like_transport_delivery_context(signal_text):
        if _looks_like_visa_run_context(signal_text):
            if "трансфер" in signal_text:
                return "Визаран и трансфер"
            if "белград" in signal_text or "belgrade" in signal_text:
                return "Визаран из Белграда"
            return "Визаран"
        if "груз" in signal_text:
            return "Перевозки и доставка"
        return "Трансфер и поездки"
    if _looks_like_language_tutoring_context(signal_text):
        if "англий" in signal_text and "немец" in signal_text:
            return "Уроки английского и немецкого"
        if "англий" in signal_text:
            return "Уроки английского языка"
        if "сербск" in signal_text:
            return "Уроки сербского языка"
        if "математ" in signal_text:
            return "Репетитор по математике"
        return "Репетитор"
    if _looks_like_medical_rehab_context(signal_text):
        if "массаж" in signal_text and "реабилитац" in signal_text:
            return "Массаж и реабилитация"
        if "реабилитац" in signal_text or "лфк" in signal_text:
            return "Реабилитация"
        if "подолог" in signal_text:
            return "Подология"
        return "Массаж"

    if _looks_like_visa_run_context(signal_text):
        if "белград" in signal_text or "belgrade" in signal_text:
            return "Визаран из Белграда"
        return "Визаран"
    if _looks_like_restaurant_context(signal_text):
        if "итальян" in signal_text or "italian" in signal_text:
            return "Итальянский ресторан"
        return "Ресторан"
    if _looks_like_tool_rental_context(signal_text):
        return "Аренда электроинструментов"
    if _looks_like_massage_context(signal_text):
        return "Массаж"
    if "электроэпиляц" in signal_text:
        return "Электроэпиляция"
    if "маникюр" in signal_text and "педикюр" in signal_text:
        return "Маникюр и педикюр"
    if "психолог" in signal_text or _as_text(offer.get("category_primary")) == "psychology":
        return "Консультация психолога"
    if "муж на час" in signal_text or "мастер на час" in signal_text:
        return "Мастер" + " на час"
    if "стиральн" in signal_text and "ремонт" in signal_text:
        return "Ремонт стиральных машин"
    if _looks_like_household_repair_master_context(signal_text):
        return "Мастер по бытовому ремонту"
    if "москит" in signal_text and ("окн" in signal_text or "сетк" in signal_text):
        return "Окна и москитные сетки"
    if "окн" in signal_text and any(hint in signal_text for hint in ("ремонт", "монтаж", "установ", "сетк")):
        return "Окна и монтаж"
    if any(hint in signal_text for hint in ("трансфер", "аэропорт", "пассажир", "водител", "поездк")):
        return "Трансфер и поездки"
    if (
        any(hint in signal_text for hint in PRODUCT_AIRCON_CLEANING_HINTS)
        and "кондиционер" in signal_text
        and any(marker in signal_text for marker in ("чист", "мойк", "фильтр", "турбин"))
    ):
        return PRODUCT_SHORT_SERVICE_LABEL_REWRITES["кондиционер"]
    if sum(1 for hint in PRODUCT_CLEANING_SERVICE_HINTS if hint in signal_text) >= 2:
        return "Клининг"
    if _as_text(offer.get("category_primary")) == "cleaning" and "пыль" in signal_text:
        return "Клининг"
    if (
        any(hint in signal_text for hint in PRODUCT_TUTORING_HINTS)
        and "англий" in signal_text
        and "немец" in signal_text
    ):
        return "Уроки английского и немецкого"
    if any(hint in signal_text for hint in PRODUCT_TUTORING_HINTS) and "сербск" in signal_text:
        return "Уроки сербского языка"
    if sum(1 for hint in PRODUCT_MARKETING_SERVICE_HINTS if hint in signal_text) >= 2:
        return "\u041c\u0430\u0440\u043a\u0435\u0442\u0438\u043d\u0433 \u0438 \u043f\u0440\u043e\u0434\u0432\u0438\u0436\u0435\u043d\u0438\u0435"
    if "консультац" in signal_text and sum(1 for hint in PRODUCT_PROFORIENTATION_HINTS if hint in signal_text) >= 2:
        return "Профориентационная" + " консультация"

    candidate_tokens = _tokenize(candidate)
    if len(candidate_tokens) <= 3:
        return _rewrite_short_service_label(candidate)
    return ""


def _looks_like_food_or_goods_sale_offer(
    service_name: str,
    details: str,
) -> bool:
    signal_text = normalize_text(" ".join(part for part in (service_name, details) if part)).lower()
    if not signal_text:
        return False
    if not any(hint in signal_text for hint in PRODUCT_FOOD_SALE_ITEM_HINTS):
        return False
    if len(_tokenize(service_name)) <= 3 and any(hint in normalize_text(service_name).lower() for hint in ("\u0447\u0438\u0437\u043a\u0435\u0439\u043a", "cake")):
        return False
    if not any(hint in signal_text for hint in PRODUCT_ORDER_PICKUP_HINTS):
        return False
    return "кейтер" not in signal_text and "catering" not in signal_text


def _looks_like_event_or_social_noise(service_name: str, details: str) -> bool:
    signal_text = normalize_text(" ".join(part for part in (service_name, details) if part)).lower()
    if not signal_text:
        return False
    hint_hits = _count_phrase_hits(signal_text, PRODUCT_EVENT_SOCIAL_NOISE_HINTS)
    if hint_hits < 2:
        return False
    service_markers = (
        "организац",
        "ведущ",
        "ивент",
        "event",
        "кейтер",
        "catering",
        "фотограф",
        "аренд",
    )
    return not any(marker in signal_text for marker in service_markers)


def _looks_like_one_off_trip_availability(service_name: str, details: str) -> bool:
    signal_text = normalize_text(" ".join(part for part in (service_name, details) if part)).lower()
    if not signal_text:
        return False
    if not ONE_OFF_TRIP_DATE_RE.search(signal_text):
        return False
    if not any(marker in signal_text for marker in ("поеду", "еду ", "выезжаю", "буду ехать")):
        return False
    if any(marker in signal_text for marker in ("регулярн", "ежедневн", "каждый день", "трансфер по заказу")):
        return False
    route_outside_serbia = any(
        marker in signal_text
        for marker in ("москв", "росси", "венгр", "чех", "словац", "польш", "беларус", "герман", "австри")
    )
    return route_outside_serbia


def _looks_like_holiday_greeting_noise(service_name: str, details: str) -> bool:
    signal_text = normalize_text(" ".join(part for part in (service_name, details) if part)).lower()
    if not signal_text:
        return False
    if _starts_with_any(signal_text, PRODUCT_HOLIDAY_GREETING_PREFIXES):
        return True
    return _count_phrase_hits(signal_text, PRODUCT_HOLIDAY_GREETING_PREFIXES) >= 1 and any(
        marker in signal_text for marker in ("поздрав", "желаем", "желаю", "пусть", "праздник")
    )


def _looks_like_news_marketing_headline_noise(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if not any(marker in lowered for marker in ("внж", "легализац", "вид на жительство", "резидент")):
        return False
    if any(marker in lowered for marker in ("оформ", "помог", "консультац", "сопровожд", "запис", "услуг")):
        return False
    return _count_phrase_hits(lowered, PRODUCT_NEWS_MARKETING_HEADLINE_HINTS) >= 2


def _looks_like_moderation_bot_noise(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _count_phrase_hits(lowered, PRODUCT_MODERATION_BOT_NOISE_HINTS) < 2:
        return False
    return any(marker in lowered for marker in ("бот", "bot", "сообщен", "прав", "блокиров", "спам", "spam"))


def _looks_like_resale_or_inventory_detail(fragment: str) -> bool:
    normalized = normalize_text(fragment)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _starts_with_any(lowered, PRODUCT_RESALE_PREFIXES):
        return True
    if _count_phrase_hits(lowered, PRODUCT_RESALE_DETAIL_PHRASES) >= 1 and any(
        marker in lowered for marker in ("ноутбук", "техник", "покупк", "продаж")
    ):
        return True
    hardware_hits = _tokenize(normalized).intersection(PRODUCT_HARDWARE_HINTS)
    return bool(hardware_hits) and any(marker in lowered for marker in ("продаж", "продам", "покупк", "в наличии"))


def _looks_like_product_noise(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    if _looks_like_non_service_visible_label(normalized):
        return True
    lowered = normalized.lower()
    tokens = _tokenize(normalized)
    if _starts_with_any(lowered, PRODUCT_GREETING_PREFIXES):
        return True
    if _starts_with_any(lowered, PRODUCT_SELF_INTRO_PREFIXES):
        return True
    if _contains_any_phrase(lowered, PRODUCT_PROMO_PHRASES):
        return True
    if normalized.count("#") >= 2:
        return True
    if len(tokens) >= 28 and len(normalized) >= 180:
        return True
    if len(tokens.intersection(PRODUCT_HARDWARE_HINTS)) >= 2 and any(
        hint in lowered for hint in ("sell", "sale", "\u043f\u0440\u043e\u0434\u0430\u043c", "\u043f\u0440\u043e\u0434\u0430\u0436\u0430")
    ):
        return True
    return False


def _product_text_signal_text(offer: dict[str, Any], extra_text: str = "") -> str:
    parts = [
        _as_text(offer.get("service_name_candidate")),
        _as_text(offer.get("details_candidate")),
        _as_text(offer.get("title_best")),
        _as_text(offer.get("description_best")),
        " ".join(_uniq_str_list(offer.get("service_tags"))),
        " ".join(_uniq_str_list(offer.get("city_display_names"))),
        extra_text,
    ]
    return normalize_text(" ".join(part for part in parts if part))


def _product_row_default_reason(offer: dict[str, Any]) -> str:
    offer_state = _as_text(offer.get("offer_state"))
    rejection_reason = _as_text(offer.get("offer_rejection_reason"))
    quality = _as_text(offer.get("fact_pack_quality"))
    if offer_state in {"rejected", "suppressed"}:
        return rejection_reason or "deterministic_non_publishable_offer"
    if quality == "weak_signal":
        return "deterministic_weak_signal_review"
    return "deterministic_fact_pack_draft"


def _product_row_policy_drop_reason(offer: dict[str, Any], extra_text: str = "") -> str:
    if _as_text(offer.get("offer_rejection_reason")):
        return ""
    signal_text = _product_text_signal_text(offer, extra_text)
    if _looks_like_model_search(signal_text):
        return "deterministic_model_search_drop"
    if _looks_like_vacancy_or_cv(signal_text):
        return "deterministic_vacancy_drop"
    if _looks_like_remote_work_hiring_platform(signal_text):
        return "deterministic_remote_work_platform_drop"
    if _looks_like_real_estate_listing(signal_text):
        return "deterministic_real_estate_listing_drop"
    if _looks_like_real_estate_platform_promo(signal_text) or _looks_like_platform_promo(signal_text):
        return "deterministic_platform_promo_drop"
    return ""


def _build_default_product_row(offer: dict[str, Any]) -> dict[str, Any]:
    service_name = normalize_text(_as_text(offer.get("service_name_candidate")) or _as_text(offer.get("title_best")))
    details = normalize_text(_as_text(offer.get("details_candidate")) or _as_text(offer.get("description_best")))
    contact_candidates = _build_offer_contact_candidates(offer)
    flags = set(_uniq_str_list(offer.get("fact_pack_flags")))
    quality = _as_text(offer.get("fact_pack_quality"))
    category = _category_display_label(offer.get("category_primary"))
    policy_drop_reason = _product_row_policy_drop_reason(offer)
    drop_row = (
        _as_text(offer.get("offer_state")) in {"rejected", "suppressed"}
        or quality in {"rejected_non_service", "suppressed_empty_offer"}
        or bool(flags.intersection(PRODUCT_DROP_FACT_PACK_FLAGS))
        or bool(policy_drop_reason)
        or (not service_name and not details)
    )

    if not details and service_name:
        details = service_name

    if drop_row:
        return {
            "product_row_publish_decision": "drop",
            "product_row_service_name": "",
            "product_row_details": "",
            "product_row_category": "",
            "product_row_contact": "",
            "product_row_audit_reason": policy_drop_reason or _product_row_default_reason(offer),
        }

    return {
        "product_row_publish_decision": "publish",
        "product_row_service_name": service_name[:120],
        "product_row_details": details[:280],
        "product_row_category": category,
        "product_row_contact": contact_candidates[0] if contact_candidates else "",
        "product_row_audit_reason": _product_row_default_reason(offer),
    }


def _offer_needs_product_row_llm(offer: dict[str, Any]) -> bool:
    if _as_text(offer.get("offer_state")) in {"rejected", "suppressed"}:
        return False

    quality = _as_text(offer.get("fact_pack_quality"))
    flags = set(_uniq_str_list(offer.get("fact_pack_flags")))
    contact_candidates = _build_offer_contact_candidates(offer)
    service_name = normalize_text(_as_text(offer.get("service_name_candidate")) or _as_text(offer.get("title_best")))
    details = normalize_text(_as_text(offer.get("details_candidate")) or _as_text(offer.get("description_best")))
    text_signal = _product_text_signal_text(offer)

    if quality == "weak_signal":
        return True
    if flags.intersection(PRODUCT_REVIEW_FACT_PACK_FLAGS):
        return True
    if not service_name or len(service_name) > 70:
        return True
    if len(details) > 160:
        return True
    if _looks_like_product_noise(service_name) or _looks_like_product_noise(details):
        return True
    if not _category_display_label(offer.get("category_primary")):
        return True
    if len(contact_candidates) != 1:
        return True
    return len(text_signal) < MIN_TEXT_SIGNAL_CHARS and len(_tokenize(text_signal)) < MIN_TEXT_SIGNAL_TOKENS


def _offer_can_become_visible_product_row(offer: dict[str, Any]) -> bool:
    if _as_text(offer.get("offer_state")) in {"rejected", "suppressed"}:
        return False
    if _as_text(offer.get("serbia_relevance_verdict")) == "outside_serbia":
        return False
    return _as_text(_build_default_product_row(offer).get("product_row_publish_decision")) == "publish"


def _derive_raw_post_id(raw_post: dict[str, Any]) -> str:
    explicit = normalize_text(_as_text(raw_post.get("raw_post_id")))
    if explicit:
        return explicit
    post_key = normalize_text(_as_text(raw_post.get("post_key")))
    if post_key:
        return post_key
    chat_id = normalize_text(str(raw_post.get("chat_id") or ""))
    message_id = normalize_text(str(raw_post.get("message_id") or ""))
    if chat_id and message_id:
        return f"tg:{chat_id}:{message_id}"
    return ""


def _build_raw_post_map(raw_posts: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_posts, list):
        return result
    for item in raw_posts:
        if not isinstance(item, dict):
            continue
        raw_post_id = _derive_raw_post_id(item)
        if raw_post_id:
            result[raw_post_id] = item
    return result


def _truncate_excerpt(text: str, limit: int = EXCERPT_CHAR_LIMIT) -> str:
    normalized = normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _build_evidence_excerpts(entity: dict[str, Any], raw_post_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_ids = _uniq_str_list(entity.get("evidence_raw_post_ids"))
    excerpts: list[dict[str, Any]] = []
    for raw_post_id in evidence_ids[:EVIDENCE_LIMIT]:
        raw_post = raw_post_map.get(raw_post_id)
        if not raw_post:
            excerpts.append(
                {
                    "raw_post_id": raw_post_id,
                    "post_url": "",
                    "posted_at_utc": "",
                    "source_channel_key": "",
                    "excerpt": "",
                }
            )
            continue
        text = _as_text(raw_post.get("text_raw")) or _as_text(raw_post.get("text"))
        excerpts.append(
            {
                "raw_post_id": raw_post_id,
                "post_url": _as_text(raw_post.get("post_url")),
                "posted_at_utc": _as_text(raw_post.get("posted_at_utc")),
                "source_channel_key": _as_text(raw_post.get("source_channel_key"))
                or _as_text(raw_post.get("chat_username"))
                or normalize_text(str(raw_post.get("chat_id") or "")),
                "excerpt": _truncate_excerpt(text),
            }
        )
    return excerpts


def _build_pair_evidence(
    first: dict[str, Any],
    second: dict[str, Any],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    combined_ids = _uniq_str_list(
        _uniq_str_list(first.get("evidence_raw_post_ids")) + _uniq_str_list(second.get("evidence_raw_post_ids"))
    )
    excerpts: list[dict[str, Any]] = []
    for raw_post_id in combined_ids[:EVIDENCE_LIMIT]:
        raw_post = raw_post_map.get(raw_post_id)
        if not raw_post:
            continue
        text = _as_text(raw_post.get("text_raw")) or _as_text(raw_post.get("text"))
        excerpts.append(
            {
                "raw_post_id": raw_post_id,
                "post_url": _as_text(raw_post.get("post_url")),
                "posted_at_utc": _as_text(raw_post.get("posted_at_utc")),
                "source_channel_key": _as_text(raw_post.get("source_channel_key"))
                or _as_text(raw_post.get("chat_username"))
                or normalize_text(str(raw_post.get("chat_id") or "")),
                "excerpt": _truncate_excerpt(text),
            }
        )
    return excerpts


def _compact_prompt_value(value: Any) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, nested in value.items():
            compacted_value = _compact_prompt_value(nested)
            if compacted_value in ("", None, [], {}):
                continue
            compacted[key] = compacted_value
        return compacted
    if isinstance(value, list):
        compacted_list = [_compact_prompt_value(item) for item in value]
        return [item for item in compacted_list if item not in ("", None, [], {})]
    if isinstance(value, str):
        return value.strip()
    return value


def _compact_prompt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = _compact_prompt_value(payload)
    return compacted if isinstance(compacted, dict) else payload


def _offer_text_signal_text(
    offer: dict[str, Any],
    raw_post_map: dict[str, dict[str, Any]],
) -> str:
    parts = [
        _as_text(offer.get("title_best")),
        _as_text(offer.get("description_best")),
        *(_as_text(excerpt.get("excerpt")) for excerpt in _build_evidence_excerpts(offer, raw_post_map)),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def _offer_has_minimum_text_signal(
    offer: dict[str, Any],
    raw_post_map: dict[str, dict[str, Any]],
) -> bool:
    text_signal = _offer_text_signal_text(offer, raw_post_map)
    return len(text_signal) >= MIN_TEXT_SIGNAL_CHARS or len(_tokenize(text_signal)) >= MIN_TEXT_SIGNAL_TOKENS


def _offer_has_llm_review_basis(
    offer: dict[str, Any],
    raw_post_map: dict[str, dict[str, Any]],
) -> bool:
    category_primary = _as_text(offer.get("category_primary")).strip().lower()
    return bool(
        (category_primary and category_primary not in GENERIC_CATEGORY_CODES)
        or _uniq_str_list(offer.get("service_tags"))
        or _as_text(offer.get("price_text_best"))
        or _offer_has_minimum_text_signal(offer, raw_post_map)
    )


def _estimate_next_call_cost_usd(stage_input: dict[str, Any]) -> float:
    input_tokens = max(220, math.ceil(len(compact_json(stage_input)) / 4) + 200)
    output_tokens = 180
    return round(
        (input_tokens * INPUT_TOKEN_PRICE_USD) + (output_tokens * OUTPUT_TOKEN_PRICE_USD),
        6,
    )


def _compute_cost_estimate(usage: dict[str, Any]) -> float:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return round(
        (input_tokens * INPUT_TOKEN_PRICE_USD) + (output_tokens * OUTPUT_TOKEN_PRICE_USD),
        6,
    )


def _apply_usage_to_budget(budget: dict[str, Any], usage: dict[str, Any] | None) -> None:
    usage_payload = usage or {}
    budget["tokens_input_total"] += int(usage_payload.get("input_tokens") or 0)
    budget["tokens_output_total"] += int(usage_payload.get("output_tokens") or 0)
    budget["cost_estimate_usd"] = round(
        budget["cost_estimate_usd"] + _compute_cost_estimate(usage_payload),
        6,
    )


def _empty_stage_breakdown() -> dict[str, dict[str, Any]]:
    return {
        stage: {
            "eligible_entities": 0,
            "vendor_attempts": 0,
            "skipped": 0,
            "accepted_patches": 0,
            "audit_only_patches": 0,
            "errors": 0,
            "max_output_retries": 0,
            "quota_blockers": 0,
            "coverage_failures": 0,
            "coverage_hard_drops": 0,
            "safe_non_visible_drops": 0,
            "recovered_low_confidence_publishes": 0,
        }
        for stage in LLM_STAGES
    }


def _empty_budget_state() -> dict[str, Any]:
    return {
        "soft_warning_calls": SOFT_WARNING_CALLS,
        "hard_stop_calls": HARD_STOP_CALLS,
        "soft_warning_cost_usd": SOFT_WARNING_COST_USD,
        "hard_stop_cost_usd": HARD_STOP_COST_USD,
        "calls_attempted": 0,
        "calls_skipped": 0,
        "tokens_input_total": 0,
        "tokens_output_total": 0,
        "cost_estimate_usd": 0.0,
        "soft_warning_triggered": False,
        "hard_stop_triggered": False,
        "last_outcome": "not_evaluated",
    }


def _ensure_budget_flags(budget: dict[str, Any]) -> None:
    budget["soft_warning_triggered"] = bool(
        budget["calls_attempted"] >= SOFT_WARNING_CALLS or budget["cost_estimate_usd"] >= SOFT_WARNING_COST_USD
    )
    budget["hard_stop_triggered"] = bool(
        budget["calls_attempted"] >= HARD_STOP_CALLS or budget["cost_estimate_usd"] >= HARD_STOP_COST_USD
    )


def _build_messages(stage: str, stage_input: dict[str, Any]) -> list[dict[str, Any]]:
    base_guardrails = (
        "You review bounded, post-merge Telegram service candidates for Serbia. "
        "Use only the supplied canonical fields and supporting raw-post excerpts. "
        "Never invent contacts, URLs, prices, or locations. "
        "Keep reason_text brief and concrete. "
        "Return strict JSON only."
    )
    stage_instruction_map = {
        "llm_service_relevance": (
            "Decide whether the offer is a real service offer. "
            "Only change offer_state or offer_rejection_reason when evidence is strong."
        ),
        "llm_serbia_relevance": (
            "Decide whether the offer is relevant to Serbia. "
            "Only change serbia_relevance_verdict, offer_state, or offer_rejection_reason when evidence is strong."
        ),
        "llm_product_row_shape": (
            "Shape one bounded user-facing row from deterministic facts plus supporting raw-post excerpts. "
            "You are the primary writer of product_row_service_name, product_row_details, and product_row_category for publish decisions. "
            "Either publish or drop. Do not pull raw-post dumps, greetings, self-intros, resale text, vacancy text, or hardware-spec noise into the visible meaning. "
            "Choose category only from the supplied allowed labels. "
            "Choose contact only from contact_candidates or leave it blank."
        ),
        "llm_category_refine_offer": (
            "Refine offer category and summary only when deterministic fields are blank, generic, or weak."
        ),
        "llm_category_refine_provider": (
            "Refine provider naming and summary only when deterministic identity display is weak or generic."
        ),
        "llm_provider_merge_review": (
            "Review one ambiguous provider pair. Do not invent replacement keys; only decide same or different provider."
        ),
        "llm_offer_dedupe_review": (
            "Review one ambiguous offer pair inside one provider. Do not invent replacement keys; only decide same or different offer."
        ),
    }
    system_message = f"{base_guardrails} {stage_instruction_map[stage]}"
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": compact_json(stage_input, pretty=True)},
    ]


def _coerce_output_text_fragment(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("value", "text"):
            fragment = _coerce_output_text_fragment(value.get(key))
            if fragment:
                return fragment
        return ""
    if isinstance(value, list):
        return "".join(fragment for fragment in (_coerce_output_text_fragment(item) for item in value) if fragment)
    return ""


def _extract_usage(payload: dict[str, Any]) -> dict[str, int]:
    usage_payload = payload.get("usage")
    return {
        "input_tokens": int(usage_payload.get("input_tokens") or 0) if isinstance(usage_payload, dict) else 0,
        "output_tokens": int(usage_payload.get("output_tokens") or 0) if isinstance(usage_payload, dict) else 0,
    }


def _response_incomplete_is_retryable(reason: str) -> bool:
    normalized = normalize_text(reason).lower()
    if normalized in NON_RETRYABLE_INCOMPLETE_REASONS:
        return False
    return normalized in {"response_format_error", "response_incomplete"}


def _response_incomplete_error_message(
    reason: str,
    *,
    structured_output: bool,
    truncated_json: bool = False,
) -> str:
    normalized = normalize_text(reason).lower() or "response_incomplete"
    if normalized == "max_output_tokens":
        if truncated_json:
            return "Structured output hit the repo max_output_tokens limit before a complete object was emitted."
        if structured_output:
            return "Structured output hit the repo max_output_tokens limit before completion."
        return "Responses API output hit the repo max_output_tokens limit before completion."
    if truncated_json:
        return f"Structured output JSON ended before a complete object was emitted ({normalized})."
    if structured_output:
        return f"Responses API returned incomplete structured output: {normalized}."
    return f"Responses API returned incomplete output: {normalized}."


def _build_response_error_excerpt(payload: dict[str, Any], *, usage: dict[str, int]) -> str:
    excerpt_payload: dict[str, Any] = {}
    status = _as_text(payload.get("status"))
    if status:
        excerpt_payload["status"] = status
    incomplete_details = payload.get("incomplete_details")
    if isinstance(incomplete_details, dict) and incomplete_details:
        excerpt_payload["incomplete_details"] = incomplete_details
    error_payload = payload.get("error")
    if isinstance(error_payload, dict) and error_payload:
        excerpt_payload["error"] = error_payload
    if usage["input_tokens"] or usage["output_tokens"]:
        excerpt_payload["usage"] = usage
    if not excerpt_payload:
        excerpt_payload["payload_type"] = type(payload).__name__
    return compact_json(excerpt_payload)[:4000]


def _extract_output_text(payload: dict[str, Any], *, request_id: str = "") -> str:
    output = payload.get("output")
    fragments: list[str] = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text":
                    text = _coerce_output_text_fragment(part.get("text"))
                    if text:
                        fragments.append(text)
                if part.get("type") == "refusal":
                    refusal = _as_text(part.get("refusal")).strip() or "Model refusal."
                    raise ResponseTransportError(refusal, retryable=False, request_id=request_id)
    combined = "".join(fragments).strip()
    if combined:
        return combined
    status = _as_text(payload.get("status")).strip().lower()
    incomplete_details = payload.get("incomplete_details")
    if status == "incomplete" and isinstance(incomplete_details, dict):
        reason = _as_text(incomplete_details.get("reason")).strip() or "response_incomplete"
        raise ResponseTransportError(
            _response_incomplete_error_message(reason, structured_output=False),
            retryable=_response_incomplete_is_retryable(reason),
            request_id=request_id,
        )
    raise ResponseTransportError(
        "Responses API payload did not include structured output text.",
        retryable=True,
        request_id=request_id,
    )


def _normalize_structured_output_text(output_text: str) -> str:
    normalized = output_text.lstrip("\ufeff").strip()
    if not normalized:
        return normalized
    fence_match = JSON_CODE_FENCE_RE.match(normalized)
    if not fence_match:
        return normalized
    fenced_body = fence_match.group("body").strip()
    return fenced_body or normalized


def _response_incomplete_reason(payload: dict[str, Any]) -> str:
    status = _as_text(payload.get("status")).strip().lower()
    incomplete_details = payload.get("incomplete_details")
    if status != "incomplete" or not isinstance(incomplete_details, dict):
        return ""
    return _as_text(incomplete_details.get("reason")).strip() or "response_incomplete"


def _looks_like_truncated_json(text: str, exc: json.JSONDecodeError) -> bool:
    stripped = text.rstrip()
    if not stripped or stripped[0] not in "{[":
        return False
    if exc.pos < max(0, len(stripped) - 24):
        return False
    lower_message = exc.msg.lower()
    if any(
        token in lower_message
        for token in (
            "unterminated string",
            "expecting value",
            "expecting property name",
            "expecting ',' delimiter",
            "expecting ':' delimiter",
        )
    ):
        return True
    if stripped.endswith(("{", "[", ",", ":", "\"")):
        return True
    if stripped.count("{") > stripped.count("}") or stripped.count("[") > stripped.count("]"):
        return True
    return False


def _classify_structured_output_parse_error(
    payload: dict[str, Any],
    output_text: str,
    exc: json.JSONDecodeError,
) -> tuple[str, bool]:
    incomplete_reason = _response_incomplete_reason(payload)
    if _looks_like_truncated_json(output_text, exc):
        if incomplete_reason:
            return (
                _response_incomplete_error_message(
                    incomplete_reason,
                    structured_output=True,
                    truncated_json=True,
                ),
                _response_incomplete_is_retryable(incomplete_reason),
            )
        return ("Structured output JSON ended before a complete object was emitted.", True)
    if incomplete_reason:
        return (
            _response_incomplete_error_message(incomplete_reason, structured_output=True),
            _response_incomplete_is_retryable(incomplete_reason),
        )
    return ("Structured output text was not valid JSON.", True)


def _parse_response_decision(payload: dict[str, Any], *, request_id: str = "") -> tuple[dict[str, Any], dict[str, int], str]:
    usage = _extract_usage(payload)
    try:
        output_text = _extract_output_text(payload, request_id=request_id)
    except ResponseTransportError as exc:
        if not getattr(exc, "response_body", ""):
            exc.response_body = _build_response_error_excerpt(payload, usage=usage)
        if not getattr(exc, "request_id", ""):
            exc.request_id = request_id
        if getattr(exc, "usage", None) is None:
            exc.usage = usage
        raise
    raw_excerpt = output_text[:4000]
    decision_text = _normalize_structured_output_text(output_text)
    try:
        parsed = json.loads(decision_text)
    except json.JSONDecodeError as exc:
        error_message, retryable = _classify_structured_output_parse_error(payload, decision_text, exc)
        raise ResponseTransportError(
            error_message,
            retryable=retryable,
            response_body=raw_excerpt,
            request_id=request_id,
            usage=usage,
        ) from exc
    if not isinstance(parsed, dict):
        raise ResponseTransportError(
            "Structured output JSON must be an object.",
            retryable=True,
            response_body=raw_excerpt,
            request_id=request_id,
            usage=usage,
        )
    return parsed, usage, output_text


def _validate_required_decision(raw: dict[str, Any]) -> dict[str, Any]:
    decision_code = _as_text(raw.get("decision_code")).strip()
    confidence = raw.get("confidence")
    patch = raw.get("patch")
    reason_text = normalize_text(_as_text(raw.get("reason_text")))
    if not decision_code:
        raise ResponseTransportError("Structured output is missing decision_code.", retryable=True)
    if not isinstance(confidence, (int, float)):
        raise ResponseTransportError("Structured output is missing numeric confidence.", retryable=True)
    if not isinstance(patch, dict):
        raise ResponseTransportError("Structured output patch must be an object.", retryable=True)
    return {
        "decision_code": decision_code,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "patch": patch,
        "reason_text": reason_text[:240],
    }


def _contains_disallowed_generated_content(text: str) -> bool:
    if not text:
        return False
    normalized = normalize_text(text)
    return bool(PHONE_RE.search(normalized) or URL_RE.search(normalized) or PRICE_RE.search(normalized))


def _sanitize_offer_patch(stage: str, patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    allowed_fields = {
        "llm_service_relevance": {"offer_state", "offer_rejection_reason"},
        "llm_serbia_relevance": {"serbia_relevance_verdict", "offer_state", "offer_rejection_reason"},
        "llm_category_refine": {"category_primary", "category_secondary", "service_tags", "offer_summary"},
    }[stage]
    sanitized: dict[str, Any] = {}
    warnings: list[str] = []

    for key, value in patch.items():
        if key not in allowed_fields:
            warnings.append(f"field_not_allowed:{key}")
            continue

        if key == "service_tags":
            tags = []
            for item in _uniq_str_list(value):
                if len(item) > 40 or _contains_disallowed_generated_content(item):
                    warnings.append(f"field_invalid:{key}")
                    continue
                tags.append(item)
            if tags:
                sanitized[key] = tags[:8]
            continue

        normalized = normalize_text(_as_text(value))
        if not normalized:
            continue

        if key == "offer_state" and normalized not in {"candidate", "accepted", "rejected", "suppressed"}:
            warnings.append(f"field_invalid:{key}")
            continue
        if key == "serbia_relevance_verdict" and normalized not in {
            "serbia_relevant",
            "outside_serbia",
            "uncertain",
        }:
            warnings.append(f"field_invalid:{key}")
            continue
        if key == "offer_summary":
            if len(normalized) > OFFER_SUMMARY_CHAR_LIMIT or _contains_disallowed_generated_content(normalized):
                warnings.append(f"field_invalid:{key}")
                continue
        if key in {"category_primary", "category_secondary"}:
            if len(normalized) > 80 or _contains_disallowed_generated_content(normalized):
                warnings.append(f"field_invalid:{key}")
                continue
        if key == "offer_rejection_reason" and len(normalized) > 160:
            warnings.append(f"field_invalid:{key}")
            continue
        sanitized[key] = normalized

    return sanitized, warnings


def _sanitize_provider_patch(patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    sanitized: dict[str, Any] = {}
    warnings: list[str] = []
    for key, value in patch.items():
        if key not in {"canonical_name", "provider_summary"}:
            warnings.append(f"field_not_allowed:{key}")
            continue
        normalized = normalize_text(_as_text(value))
        if not normalized:
            continue
        limit = CANONICAL_NAME_CHAR_LIMIT if key == "canonical_name" else PROVIDER_SUMMARY_CHAR_LIMIT
        if len(normalized) > limit or _contains_disallowed_generated_content(normalized):
            warnings.append(f"field_invalid:{key}")
            continue
        sanitized[key] = normalized
    return sanitized, warnings


def _service_label_has_price_tail_service_signal(text: str) -> bool:
    lowered = normalize_text(text).lower()
    if not lowered or lowered in PRODUCT_GENERIC_SERVICE_NAMES:
        return False
    category_hints = (
        hint
        for hints in PRODUCT_CATEGORY_SIGNAL_HINTS.values()
        for hint in hints
    )
    extra_hints = (
        "аренд",
        "депиляц",
        "запись",
        "консультац",
        "массаж",
        "перевоз",
        "переезд",
        "прокат",
        "съемк",
        "съёмк",
        "шугаринг",
    )
    return any(hint in lowered for hint in (*category_hints, *extra_hints))


def _strip_product_row_service_label_price_tail(text: str) -> tuple[str, bool]:
    normalized = normalize_text(text)
    if not normalized:
        return "", False

    searchable = normalized.rstrip(" .,!?:;")
    for price_pattern in (PRICE_FROM_RE, PRICE_RE):
        matches = list(price_pattern.finditer(searchable))
        if not matches:
            continue
        price_match = matches[-1]
        if price_match.end() != len(searchable):
            continue
        candidate = normalize_text(searchable[: price_match.start()]).strip(" ,;:—–-")
        if (
            candidate
            and _service_label_has_price_tail_service_signal(candidate)
            and not _looks_like_non_service_visible_label(candidate)
            and not _label_looks_like_action_or_experience_statement(candidate)
            and not _label_looks_like_provider_or_brand_intro(candidate)
            and not _label_looks_like_slogan_or_promo(candidate)
            and not _service_label_looks_sentence_like(candidate)
        ):
            return candidate, True
    return normalized, False


def _normalize_product_row_service_label_patch(text: str) -> tuple[str, bool]:
    normalized = normalize_text(text)
    if not normalized:
        return "", False
    compacted = normalize_text(SERVICE_LABEL_PROMO_RANK_RE.sub(" ", normalized)).strip(" ,;:—–-")
    if compacted:
        price_stripped, price_normalized = _strip_product_row_service_label_price_tail(compacted)
        if price_normalized:
            return price_stripped, True
    if compacted and compacted != normalized:
        return compacted, True
    return normalized, False


def _sanitize_product_row_patch(
    candidate: Candidate,
    patch: dict[str, Any],
) -> tuple[dict[str, str], list[str]]:
    sanitized: dict[str, str] = {}
    warnings: list[str] = []
    allowed_contacts = {
        _normalize_contact_candidate_display(value)
        for value in _uniq_str_list(
            ((candidate.input_payload.get("deterministic_fact_pack") or {}).get("contact_candidates"))
        )
    }

    for key, value in patch.items():
        if key not in {
            "product_row_service_name",
            "product_row_details",
            "product_row_category",
            "product_row_contact",
        }:
            warnings.append(f"field_not_allowed:{key}")
            continue

        if value is None:
            sanitized[key] = ""
            continue

        normalized = normalize_text(_as_text(value))
        if not normalized:
            sanitized[key] = ""
            continue

        if key == "product_row_service_name":
            normalized, label_normalized = _normalize_product_row_service_label_patch(normalized)
            if label_normalized:
                warnings.append("field_normalized:product_row_service_name")
            if not normalized:
                sanitized[key] = ""
                continue
            if len(normalized) > 120 or _contains_disallowed_generated_content(normalized) or _looks_like_product_noise(normalized):
                warnings.append(f"field_invalid:{key}")
                continue
        elif key == "product_row_details":
            limit = 280
            if len(normalized) > limit or _contains_disallowed_generated_content(normalized) or _looks_like_product_noise(normalized):
                warnings.append(f"field_invalid:{key}")
                continue
        elif key == "product_row_category":
            category_label = _normalize_category_display_label(normalized)
            if not category_label:
                warnings.append(f"field_invalid:{key}")
                continue
            normalized = category_label
        elif key == "product_row_contact":
            contact_value = _normalize_contact_candidate_display(normalized)
            if not contact_value:
                sanitized[key] = ""
                continue
            if allowed_contacts and contact_value not in allowed_contacts:
                warnings.append(f"field_invalid:{key}")
                continue
            normalized = contact_value

        sanitized[key] = normalized

    return sanitized, warnings


def _apply_offer_patch(offer: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    changed: dict[str, Any] = {}
    for key, value in patch.items():
        current = offer.get(key)
        if current == value:
            continue
        offer[key] = value
        changed[key] = value
    return offer, changed


def _apply_provider_patch(provider: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    changed: dict[str, Any] = {}
    for key, value in patch.items():
        current = provider.get(key)
        if current == value:
            continue
        provider[key] = value
        changed[key] = value
    return provider, changed


def _apply_product_row_patch(
    *,
    offer: dict[str, Any],
    decision_code: str,
    patch: dict[str, str],
    reason_text: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    if decision_code == "drop":
        patch_to_apply = {
            "product_row_publish_decision": "drop",
            "product_row_service_name": "",
            "product_row_details": "",
            "product_row_category": "",
            "product_row_contact": "",
            "product_row_audit_reason": reason_text[:240],
        }
        _, changed = _apply_offer_patch(offer, patch_to_apply)
        return offer, changed, warnings

    final_service_name = patch.get("product_row_service_name", "")
    final_details = patch.get("product_row_details", "")
    final_category = patch.get("product_row_category", "")
    final_contact = patch.get("product_row_contact", _as_text(offer.get("product_row_contact")))

    if not final_service_name:
        warnings.append("missing_service_name")
    if not final_category:
        warnings.append("missing_category")
    if _looks_like_product_noise(final_service_name):
        warnings.append("service_name_invalid")
    if final_details and _looks_like_product_noise(final_details):
        warnings.append("details_invalid")
    if final_category and final_category not in PRODUCT_CATEGORY_DISPLAY_SET:
        warnings.append("category_invalid")
    if warnings:
        return offer, {}, warnings

    if not final_details:
        final_details = final_service_name

    patch_to_apply = {
        "product_row_publish_decision": "publish",
        "product_row_service_name": final_service_name[:120],
        "product_row_details": final_details[:280],
        "product_row_category": final_category,
        "product_row_contact": final_contact,
        "product_row_audit_reason": reason_text[:240],
    }
    _, changed = _apply_offer_patch(offer, patch_to_apply)
    return offer, changed, warnings


def _build_override_group(prefix: str, entity_ids: list[str]) -> str:
    ordered = sorted(entity_ids)
    return f"{prefix}:{_compact_hash(ordered)[:16]}"


def _copy_canonical_output(run_id: str, merge_output: dict[str, Any]) -> dict[str, Any]:
    providers = copy.deepcopy(merge_output.get("providers") if isinstance(merge_output.get("providers"), list) else [])
    offers = copy.deepcopy(merge_output.get("offers") if isinstance(merge_output.get("offers"), list) else [])
    return {
        "run_id": run_id,
        "workflow_stage": WORKFLOW_STAGE,
        "llm_contract_version": PROCESSOR_VERSION,
        "providers_total": len(providers),
        "offers_total": len(offers),
        "providers": providers,
        "offers": offers,
        "merge_summary": copy.deepcopy(merge_output.get("merge_summary") if isinstance(merge_output.get("merge_summary"), dict) else {}),
    }


def _count_emoji_chars(text: Any) -> int:
    return len(EMOJI_CHAR_RE.findall(_as_text(text)))


def _looks_like_model_search(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(phrase in lowered for phrase in PRODUCT_MODEL_SEARCH_PHRASES):
        return True
    tokens = _tokenize(normalized)
    model_hit = bool(tokens.intersection({"model", "models", "модель", "модели", "моделей", "моделям"}))
    if model_hit and any(marker in lowered for marker in PRODUCT_MODEL_SEARCH_CONTEXT_HINTS):
        return True
    return "модель" in lowered and (
        "ищу" in tokens
        or "нужны" in tokens
        or "нужна" in tokens
        or "отработки" in tokens
    )


def _looks_like_photo_video_production_context(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    if _looks_like_model_search(lowered):
        return False
    media_hit = any(hint in lowered for hint in PRODUCT_PHOTO_VIDEO_PRODUCTION_MEDIA_HINTS)
    work_hit = any(hint in lowered for hint in PRODUCT_PHOTO_VIDEO_PRODUCTION_WORK_HINTS)
    return media_hit and work_hit


def _looks_like_real_estate_listing(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    service_context = _looks_like_real_estate_service_context(lowered)
    if _count_phrase_hits(lowered, PRODUCT_REAL_ESTATE_LISTING_PHRASES) >= 1:
        return True
    tokens = _tokenize(normalized)
    listing_tokens = {"сдача", "сдаётся", "сдается", "аренда", "продажа", "просмотр", "rent", "sale"}
    property_tokens = {
        "квартира",
        "квартиры",
        "квартир",
        "квартире",
        "квартиру",
        "дом",
        "дома",
        "апартамент",
        "apartment",
        "flat",
        "house",
    }
    if tokens.intersection(listing_tokens) and tokens.intersection(property_tokens):
        return True
    if not tokens.intersection(property_tokens) or service_context:
        return False
    return any(marker in lowered for marker in PRODUCT_REAL_ESTATE_LISTING_DETAIL_HINTS)


def _looks_like_real_estate_service_context(lowered_text: str) -> bool:
    if _looks_like_property_technical_inspection_context(lowered_text):
        return True
    if any(marker in lowered_text for marker in PRODUCT_REAL_ESTATE_SERVICE_MARKERS):
        return True
    if any(marker in lowered_text for marker in PRODUCT_REAL_ESTATE_SERVICE_CONTEXT_HINTS):
        return True
    if "ремонт" in lowered_text and any(
        marker in lowered_text for marker in ("услуг", "мастер", "бригада", "сантех", "электрик", "отделк", "монтаж")
    ):
        return True
    return False


def _looks_like_property_technical_inspection_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    has_property_object = any(marker in lowered for marker in PRODUCT_PROPERTY_TECHNICAL_INSPECTION_OBJECT_HINTS)
    if not has_property_object:
        return False
    inspection_hits = _count_phrase_hits(lowered, PRODUCT_PROPERTY_TECHNICAL_INSPECTION_HINTS)
    if inspection_hits >= 2:
        return True
    return (
        any(marker in lowered for marker in ("технический аудит", "техническая инспекц", "technical inspection"))
        and any(marker in lowered for marker in ("дефект", "заключен", "ремонт", "застройщик", "вентиляц", "плесен"))
    )


def _looks_like_real_estate_platform_promo(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    has_real_estate_subject = any(marker in lowered for marker in ("недвиж", "квартир", "real estate", "property", "apartment"))
    if (
        has_real_estate_subject
        and any(marker in lowered for marker in PRODUCT_REAL_ESTATE_PLATFORM_MECHANIC_HINTS)
        and (
            any(marker in lowered for marker in PRODUCT_REAL_ESTATE_PLATFORM_ACTION_HINTS)
            or _count_phrase_hits(lowered, PRODUCT_REAL_ESTATE_PLATFORM_MECHANIC_HINTS) >= 2
        )
    ):
        return True
    return (
        any(marker in lowered for marker in PRODUCT_REAL_ESTATE_PLATFORM_HINTS)
        and any(marker in lowered for marker in PRODUCT_REAL_ESTATE_PLATFORM_ACTION_HINTS)
        and has_real_estate_subject
    )


def _looks_like_esoteric_offer(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    return _count_phrase_hits(lowered, PRODUCT_ESOTERIC_PHRASES) >= 1


def _strip_leading_text_prefix(text: str, prefixes: tuple[str, ...]) -> tuple[str, str]:
    lowered = normalize_text(text).lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            remainder = normalize_text(text[len(prefix) :].lstrip(" ,:;.!?-—–"))
            return remainder, prefix
    return normalize_text(text), ""


def _normalize_service_label_case(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return ""
    lowercase_short_words = {"БЕЗ", "ДЛЯ", "ПОД", "ПРИ", "ПО", "НА", "В", "И", "С", "ОТ", "ДО"}

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in lowercase_short_words:
            return token.lower()
        if len(token) > 3 or len(token) == 1:
            return token.lower()
        return token

    lowered_shouting = re.sub(r"\b[A-ZА-ЯЁ]{1,}\b", _replace, normalized)
    lowered_shouting = normalize_text(lowered_shouting)
    return lowered_shouting[:1].upper() + lowered_shouting[1:] if lowered_shouting else ""


def _service_tail_looks_like_noise(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _looks_like_non_service_visible_label(normalized):
        return True
    if _looks_like_product_noise(normalized) or _looks_like_model_search(normalized):
        return True
    if any(phrase in lowered for phrase in PRODUCT_MARKETING_TAIL_PHRASES):
        return True
    if any(phrase in lowered for phrase in PRODUCT_SERVICE_TAIL_PHRASES):
        return True
    if PRICE_RE.search(normalized) or PRICE_FROM_RE.search(normalized):
        return True
    return len(_tokenize(normalized)) >= 5 and any(marker in normalized for marker in ",.!?")


def _offer_location_tokens(offer: dict[str, Any]) -> set[str]:
    tokens = {
        "belgrade",
        "serbia",
        "белград",
        "белграда",
        "белграду",
        "белграде",
        "нови",
        "сад",
        "саду",
        "сада",
        "сербия",
        "сербии",
        "сербии.",
    }
    for value in _uniq_str_list(offer.get("city_display_names")):
        tokens.update(_tokenize(value))
    return tokens


def _fragment_meaning_tokens(fragment: str) -> set[str]:
    return _tokenize(fragment).difference({"в", "во", "по", "из", "на", "и", "and"})


def _fragment_is_location_only(fragment: str, offer: dict[str, Any]) -> bool:
    tokens = _fragment_meaning_tokens(fragment)
    return bool(tokens) and tokens.issubset(_offer_location_tokens(offer))


def _fragment_is_geography_only(fragment: str, offer: dict[str, Any]) -> bool:
    tokens = _fragment_meaning_tokens(fragment)
    if not tokens:
        return False
    geography_tokens = set(_offer_location_tokens(offer))
    for hint in FOREIGN_GEOGRAPHY_HINTS:
        geography_tokens.update(_tokenize(hint))
    geography_tokens.update({"и", "and", "европы", "europe", "германии", "словении", "австрии", "венгрии"})
    return tokens.issubset(geography_tokens)


def _offer_has_visible_service_context(offer: dict[str, Any]) -> bool:
    signal_text = normalize_text(
        " ".join(
            part
            for part in (
                _as_text(offer.get("product_row_service_name")),
                _as_text(offer.get("service_name_candidate")),
                " ".join(_uniq_str_list(offer.get("service_tags"))),
                _as_text(offer.get("category_primary")),
            )
            if part
        )
    ).lower()
    return bool(signal_text) and not _looks_like_vacancy_or_cv(signal_text)


def _looks_like_vehicle_rental_context(signal_text: str) -> bool:
    lowered = normalize_text(signal_text).lower()
    if not lowered:
        return False
    if not any(hint in lowered for hint in ("аренд", "прокат", "rent", "rental")):
        return False
    if any(
        hint in lowered
        for hint in (
            "авто",
            "автомоб",
            "машин",
            "vehicle",
            "car",
            "rentacar",
            "rent-a-car",
            "акпп",
            "мкпп",
            "дизель",
            "бензин",
            "полный бак",
        )
    ):
        return True
    return bool(_tokenize(lowered).intersection(PRODUCT_AUTO_HEADLINE_BRAND_HINTS))


def _strip_vehicle_rental_requirement_vacancy_noise(text: str) -> str:
    normalized = normalize_text(text)
    if not _looks_like_vehicle_rental_context(normalized):
        return normalized

    terms = r"(?:депозит|залог|страховк[а-яё]*|каско|осаго)"
    joiner = r"(?:\s*(?:и|или|/)\s*)"
    requirement = r"требу(?:етс[яь]|ются)"

    def _remove_requirement_word(match: re.Match[str]) -> str:
        return normalize_text(re.sub(rf"\b{requirement}\b", " ", match.group(0), flags=re.IGNORECASE))

    updated = re.sub(
        rf"\b{terms}(?:{joiner}{terms})*\s+{requirement}\b",
        _remove_requirement_word,
        normalized,
        flags=re.IGNORECASE,
    )
    updated = re.sub(
        rf"\b{requirement}\s+{terms}(?:{joiner}{terms})*\b",
        _remove_requirement_word,
        updated,
        flags=re.IGNORECASE,
    )
    return normalize_text(updated)


def _strip_service_label_price(text: str) -> tuple[str, list[str]]:
    fragments: list[str] = []
    updated = normalize_text(text)

    from_match = PRICE_FROM_RE.search(updated)
    if from_match:
        fragments.append(normalize_text(from_match.group(0)))
        updated = normalize_text(updated[: from_match.start()] + " " + updated[from_match.end() :])

    inline_match = PRICE_RE.search(updated)
    if inline_match:
        fragments.append(normalize_text(inline_match.group(0)))
        updated = normalize_text(updated[: inline_match.start()] + " " + updated[inline_match.end() :])

    return updated.strip(" ,;:—–-"), fragments


def _strip_service_label_condition_tail(text: str) -> tuple[str, str]:
    normalized = normalize_text(text)
    lowered = normalized.lower()
    best_index: int | None = None
    best_fragment = ""
    for phrase in PRODUCT_SERVICE_CONDITION_PHRASES:
        index = lowered.find(phrase)
        if index <= 0:
            continue
        if best_index is None or index < best_index:
            best_index = index
            best_fragment = normalize_text(normalized[index:])
    if best_index is None:
        return normalized, ""
    return normalize_text(normalized[:best_index]).strip(" ,;:—–-"), best_fragment


def _strip_service_label_location_tail(offer: dict[str, Any], text: str) -> tuple[str, str]:
    normalized = normalize_text(text)
    if not normalized:
        return "", ""
    lowered = normalized.lower()
    if any(hint in lowered for hint in PRODUCT_CATEGORY_SIGNAL_HINTS.get("legal_docs", ())):
        return normalized, ""

    match = LOCATION_TAIL_RE.match(normalized)
    if not match:
        return normalized, ""

    tail = normalize_text(match.group("tail"))
    if not _fragment_is_location_only(tail, offer) and not _fragment_is_geography_only(tail, offer):
        return normalized, ""

    fragment = normalize_text(f"{match.group('preposition')} {tail}")
    return normalize_text(match.group("head")).strip(" ,;:—–-"), fragment


def _service_label_tail_should_move_to_details(offer: dict[str, Any], head: str, tail: str) -> bool:
    normalized_head = normalize_text(head)
    normalized_tail = normalize_text(tail).strip(" ,;:—–-")
    if not normalized_head or not normalized_tail:
        return False
    head_tokens = _tokenize(normalized_head)
    tail_tokens = _tokenize(normalized_tail)
    if not head_tokens or len(head_tokens) > 8 or not tail_tokens or len(tail_tokens) > 12:
        return False
    if _fragment_is_location_only(normalized_tail, offer):
        return True
    if _looks_like_vehicle_rental_context(f"{normalized_head} {normalized_tail}") and any(
        marker in normalized_tail.lower() for marker in ("акпп", "мкпп", "дизель", "бензин")
    ):
        return False
    tail_lower = normalized_tail.lower()
    detail_markers = (
        "аудитор",
        "аудит",
        "бойлер",
        "взросл",
        "детей",
        "дети",
        "диагност",
        "доставка",
        "класс",
        "ковр",
        "консультац",
        "лфк",
        "мебел",
        "мобилизац",
        "нови",
        "огэ",
        "егэ",
        "окрестност",
        "онлайн",
        "очно",
        "отчет",
        "отчёт",
        "подготов",
        "провер",
        "салон",
        "салоны",
        "сантех",
        "сопровожд",
        "реабилитац",
        "ресниц",
        "лечеб",
        "спецификац",
        "студия",
        "техпровер",
        "центр",
    )
    if any(marker in tail_lower for marker in detail_markers):
        return True
    return False


def _strip_service_label_parenthetical_tail(offer: dict[str, Any], text: str) -> tuple[str, str]:
    normalized = normalize_text(text)
    if not normalized or not normalized.endswith(")"):
        return normalized, ""
    match = re.match(r"^(?P<head>.+?)\s*\((?P<tail>[^()]*)\)$", normalized)
    if not match:
        return normalized, ""
    head = normalize_text(match.group("head")).strip(" ,;:—–-")
    tail = normalize_text(match.group("tail")).strip(" ,;:—–-")
    if not head or not tail:
        return normalized, ""
    if _service_label_tail_should_move_to_details(offer, head, tail):
        return head, tail
    return normalized, ""


def _looks_like_vehicle_result_headline(offer: dict[str, Any], service_name: str) -> bool:
    normalized = normalize_text(service_name)
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(hint in lowered for hint in PRODUCT_AUTO_SERVICE_CORE_HINTS):
        return False

    tokens = _tokenize(normalized)
    has_brand_signal = bool(tokens.intersection(PRODUCT_AUTO_HEADLINE_BRAND_HINTS)) or bool(
        re.search(r"\b[a-zа-яё]{1,5}\s?-?\d{2,4}\b", lowered)
    )
    if not has_brand_signal:
        return False

    detail_signal = normalize_text(
        " ".join(
            part
            for part in (
                normalized,
                _as_text(offer.get("details_candidate")),
                _as_text(offer.get("description_best")),
                " ".join(_uniq_str_list(offer.get("service_tags"))),
            )
            if part
        )
    ).lower()
    inspection_hits = _count_phrase_hits(detail_signal, PRODUCT_AUTO_INSPECTION_DETAIL_HINTS)
    result_like = bool(re.search(r"\bза\s+\d+\s+(?:дн|дня|дней|час|часа|часов)\b", detail_signal)) or "реально" in lowered
    return inspection_hits >= 2 or result_like


def _service_label_looks_sentence_like(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _label_looks_like_action_or_experience_statement(normalized):
        return True
    if _looks_like_non_service_visible_label(normalized):
        return True
    if _looks_like_model_search(normalized):
        return True
    if PRICE_RE.search(normalized) or PRICE_FROM_RE.search(normalized):
        return True
    if any(phrase in lowered for phrase in PRODUCT_SERVICE_TAIL_PHRASES):
        return True
    if any(lowered.startswith(phrase) for phrase in PRODUCT_SENTENCE_LIKE_START_PHRASES):
        return True
    if any(phrase in lowered for phrase in PRODUCT_SENTENCE_LIKE_INLINE_PHRASES):
        return True
    if any(phrase in lowered for phrase in ("помогу", "работаю", "приглашаю", "ищу ", "нужны ", "если вы")):
        return True
    return len(_tokenize(normalized)) >= 9 and any(marker in normalized for marker in ",.;:?")


def _singularize_service_label_fragment(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return ""
    tokens: list[str] = []
    for token in normalized.split():
        lowered = token.lower()
        if len(lowered) > 6 and lowered.endswith("аний"):
            token = token[:-4] + "ание"
        elif len(lowered) > 6 and lowered.endswith("ений"):
            token = token[:-4] + "ение"
        elif len(lowered) > 5 and lowered.endswith("ек"):
            token = token[:-2] + "ка"
        tokens.append(token)
    return normalize_text(" ".join(tokens))


def _extract_service_label_from_list_intro(text: str) -> tuple[str, list[str]]:
    normalized = normalize_text(text)
    lowered = normalized.lower()
    body = ""
    for prefix in ("все виды ", "любые виды "):
        if lowered.startswith(prefix):
            body = normalize_text(normalized[len(prefix) :])
            break
    if not body:
        return "", []

    head, separator, tail = body.partition(":")
    head = _normalize_service_label_case(_singularize_service_label_fragment(head).strip(" ,;:—–-"))
    if not head or len(_tokenize(head)) > 4 or _service_label_looks_sentence_like(head):
        return "", []

    label = head
    salvaged: list[str] = []
    if separator:
        for fragment in re.split(r"\s*,\s*", tail):
            cleaned = normalize_text(fragment).strip(" ,;:—–-")
            if not cleaned:
                continue
            lowered_fragment = cleaned.lower()
            if (
                len(_tokenize(cleaned)) <= 3
                and not lowered_fragment.startswith(("от ", "до ", "для ", "без ", "по "))
                and not _service_label_looks_sentence_like(cleaned)
            ):
                extra = _singularize_service_label_fragment(cleaned).lower()
                if extra and extra.lower() != label.lower():
                    label = normalize_text(f"{label} и {extra}")[:120]
                    continue
            salvaged.append(cleaned)
    return label, salvaged


def _clean_publishable_service_label(offer: dict[str, Any], service_name: str) -> tuple[str, list[str]]:
    normalized = normalize_text(service_name)
    if not normalized or _looks_like_model_search(normalized):
        return "", []
    if "мастер на все руки" in normalized.lower():
        return "", []
    if _looks_like_non_service_visible_label(normalized):
        return "", []

    salvaged_fragments: list[str] = []
    candidate = normalize_text(EMOJI_CHAR_RE.sub(" ", normalized))
    had_question_mark = "?" in candidate

    candidate, stripped_prefix = _strip_leading_text_prefix(
        candidate,
        PRODUCT_GREETING_PREFIXES + PRODUCT_AUDIENCE_PREFIXES + PRODUCT_SELF_INTRO_PREFIXES,
    )
    if stripped_prefix:
        salvaged_fragments.append(stripped_prefix)
    candidate, stripped_offer_prefix = _strip_leading_text_prefix(candidate, PRODUCT_SERVICE_OFFER_PREFIXES)
    if stripped_offer_prefix:
        salvaged_fragments.append(stripped_offer_prefix)

    list_label, list_fragments = _extract_service_label_from_list_intro(candidate)
    if list_label:
        candidate = list_label
        salvaged_fragments.extend(list_fragments)
        had_question_mark = False

    for separator in (" — ", " – ", " - "):
        if separator not in candidate:
            continue
        head, tail = candidate.split(separator, 1)
        if _service_tail_looks_like_noise(tail) or _service_label_tail_should_move_to_details(offer, head, tail):
            candidate = normalize_text(head)
            salvaged_fragments.append(normalize_text(tail))
        break

    sentence_parts = SENTENCE_SPLIT_RE.split(candidate, maxsplit=1)
    if len(sentence_parts) == 2:
        candidate = normalize_text(sentence_parts[0].rstrip(".!?"))
        salvaged_fragments.append(normalize_text(sentence_parts[1]))
    else:
        candidate = candidate.rstrip(".!?")

    lowered = candidate.lower()
    phrase_hits = [lowered.find(phrase) for phrase in PRODUCT_SERVICE_TAIL_PHRASES if lowered.find(phrase) > 0]
    if phrase_hits:
        cut_index = min(phrase_hits)
        salvaged_fragments.append(normalize_text(candidate[cut_index:]))
        candidate = normalize_text(candidate[:cut_index])

    candidate, condition_fragment = _strip_service_label_condition_tail(candidate)
    if condition_fragment:
        salvaged_fragments.append(condition_fragment)

    candidate, price_fragments = _strip_service_label_price(candidate)
    salvaged_fragments.extend(price_fragments)

    candidate, parenthetical_fragment = _strip_service_label_parenthetical_tail(offer, candidate)
    if parenthetical_fragment:
        salvaged_fragments.append(parenthetical_fragment)

    candidate, location_fragment = _strip_service_label_location_tail(offer, candidate)
    if location_fragment:
        salvaged_fragments.append(location_fragment)

    candidate = _normalize_service_label_case(candidate).strip(" ,;:—–-")
    if had_question_mark and len(_tokenize(candidate)) >= 6:
        return "", [fragment for fragment in salvaged_fragments if fragment]
    inferred_label = _infer_service_meaning_label(offer, candidate, salvaged_fragments)
    if inferred_label and (
        not candidate
        or normalize_text(candidate).lower() in PRODUCT_GENERIC_SERVICE_NAMES
        or _fragment_is_location_only(candidate, offer)
        or _label_looks_like_action_or_experience_statement(candidate)
        or _label_looks_like_provider_or_brand_intro(candidate)
        or _label_looks_like_slogan_or_promo(candidate)
        or normalize_text(candidate).lower() in {"боль", "усталость", "напряжение"}
        or (len(_tokenize(candidate)) > 4 and _service_label_looks_sentence_like(candidate))
    ):
        candidate = inferred_label
    if _looks_like_vehicle_result_headline(offer, candidate):
        return "", [fragment for fragment in salvaged_fragments if fragment]
    if not candidate or _service_label_looks_sentence_like(candidate):
        return "", [fragment for fragment in salvaged_fragments if fragment]
    return candidate[:120], [fragment for fragment in salvaged_fragments if fragment]


def _looks_like_service_area_detail_fragment(offer: dict[str, Any], fragment: str) -> bool:
    normalized = normalize_text(fragment)
    if not normalized:
        return False
    lowered = normalized.lower()
    if not lowered.startswith(("работа в ", "работа по ", "работа на ")):
        return False
    if any(marker in lowered for marker in ("ваканс", "резюме", "зарплат", "требует", "ищу работу", "ищем в команду")):
        return False
    has_service_context = _offer_has_visible_service_context(offer)
    has_area_context = bool(_tokenize(normalized).intersection(_offer_location_tokens(offer))) or any(
        marker in lowered
        for marker in ("белград", "район", "районе", "окрестност", "без выходных", "ежедневно", "по записи")
    )
    return has_service_context and has_area_context


def _looks_like_service_experience_detail_fragment(offer: dict[str, Any], fragment: str) -> bool:
    normalized = normalize_text(fragment).strip(" .")
    if not normalized or not _offer_has_visible_service_context(offer):
        return False
    lowered = normalized.lower()
    if not lowered.startswith(("опыт ", "опыт работы ", "стаж ")):
        return False
    return bool(re.search(r"\b\d+\s+(?:год|года|лет)\b", lowered))


def _looks_like_provider_portfolio_detail_fragment(offer: dict[str, Any], fragment: str) -> bool:
    normalized = normalize_text(fragment)
    if not normalized or not _offer_has_visible_service_context(offer):
        return False
    lowered = normalized.lower()
    if "портфолио" not in lowered and "portfolio" not in lowered:
        return False
    if _looks_like_model_search(normalized):
        return False
    token_count = len(_tokenize(normalized))
    if token_count <= 5:
        return True
    return token_count <= 8 and any(
        marker in lowered
        for marker in ("пример", "работ", "кейс", "запрос", "канал", "telegram", "телеграм", "указан", "доступ")
    )


def _looks_like_music_software_training_context(offer: dict[str, Any], fragment: str) -> bool:
    signal_text = normalize_text(
        " ".join(
            part
            for part in (
                fragment,
                _as_text(offer.get("product_row_service_name")),
                _as_text(offer.get("product_row_details")),
                _as_text(offer.get("service_name_candidate")),
                _as_text(offer.get("details_candidate")),
                _as_text(offer.get("title_best")),
                _as_text(offer.get("description_best")),
                " ".join(_uniq_str_list(offer.get("service_tags"))),
                _as_text(offer.get("category_primary")),
            )
            if part
        )
    ).lower()
    if not signal_text:
        return False
    training_hit = _as_text(offer.get("category_primary")) == "education_tutoring" or any(
        hint in signal_text
        for hint in ("обуч", "урок", "заняти", "репет", "course", "class", "lesson", "training")
    )
    music_or_software_hit = any(
        hint in signal_text
        for hint in ("daw", "software", "гитар", "звукозап", "музык", "нотн", "программ", "редактор", "сведен")
    )
    return training_hit and music_or_software_hit


def _normalize_training_program_work_detail_fragment(offer: dict[str, Any], fragment: str) -> str:
    normalized = normalize_text(fragment)
    lowered = normalized.lower()
    if not lowered.startswith(("работа в программ", "работа с программ", "работа в daw", "работа с daw")):
        return normalized
    if not _looks_like_music_software_training_context(offer, normalized):
        return normalized

    tail = re.sub(r"^работа\s+(?:в|с)\s+", "", normalized, flags=re.IGNORECASE)
    tail = normalize_text(tail).strip(" ,;:—–-!?")
    if not tail:
        return ""

    lowered_tail = tail.lower()
    for prefix in ("программах", "программами", "программам"):
        if lowered_tail == prefix:
            return "Программы для обучения"
        if lowered_tail.startswith(f"{prefix} "):
            return _normalize_service_label_case(f"Программы {tail[len(prefix):].strip()}")
    return _normalize_service_label_case(tail)


def _normalize_vehicle_rental_condition_detail_fragment(offer: dict[str, Any], fragment: str) -> str:
    normalized = normalize_text(fragment)
    if not normalized:
        return ""
    lowered = normalized.lower()
    if "требу" not in lowered:
        return normalized
    if not any(term in lowered for term in PRODUCT_VEHICLE_RENTAL_CONDITION_TERMS):
        return normalized

    signal_text = normalize_text(
        " ".join(
            part
            for part in (
                normalized,
                _as_text(offer.get("product_row_service_name")),
                _as_text(offer.get("service_name_candidate")),
                _as_text(offer.get("title_best")),
                _as_text(offer.get("product_row_category")),
                _as_text(offer.get("category_primary")),
                " ".join(_uniq_str_list(offer.get("service_tags"))),
            )
            if part
        )
    )
    if not _looks_like_vehicle_rental_context(signal_text):
        return normalized

    cleaned = re.sub(r"\bтребу(?:етс[яь]|ются)\b", " ", normalized, flags=re.IGNORECASE)
    cleaned = normalize_text(cleaned).strip(" ,;:—–-!?")
    if not cleaned or cleaned == normalized:
        return normalized
    return _normalize_service_label_case(f"Условия аренды: {cleaned.lower()}")


def _split_publishable_detail_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    normalized = normalize_text(text)
    if not normalized:
        return fragments
    for part in DETAIL_SPLIT_RE.split(normalized):
        candidate = normalize_text(part)
        if not candidate:
            continue
        for sentence in SENTENCE_SPLIT_RE.split(candidate):
            cleaned = normalize_text(sentence).strip(" ,;")
            if cleaned:
                fragments.append(cleaned)
    return fragments


def _clean_publishable_detail_fragment(offer: dict[str, Any], fragment: str) -> str:
    normalized = normalize_text(EMOJI_CHAR_RE.sub(" ", fragment)).strip(" ,;:—–-!?")
    if not normalized:
        return ""
    original_lowered = normalized.lower()

    normalized = normalize_text(DETAILS_LIST_INTRO_PREFIX_RE.sub("", normalized)).strip(" ,;:—–-!?")
    if not normalized:
        return ""

    normalized = normalize_text(DETAILS_LEGAL_ARTICLE_PREFIX_RE.sub("", normalized)).strip(" ,;:—–-!?")
    if not normalized:
        return ""

    lowered = normalized.lower()
    normalized, _ = _strip_leading_text_prefix(normalized, PRODUCT_GREETING_PREFIXES + PRODUCT_AUDIENCE_PREFIXES)
    if _starts_with_any(original_lowered, PRODUCT_SELF_INTRO_PREFIXES):
        return ""
    normalized, _ = _strip_leading_text_prefix(normalized, PRODUCT_SELF_INTRO_PREFIXES)
    normalized, _ = _strip_leading_text_prefix(normalized, PRODUCT_SERVICE_OFFER_PREFIXES)
    normalized = normalize_text(normalized).strip(" ,;:—–-!?")
    lowered = normalized.lower()
    if not normalized:
        return ""
    normalized_training = _normalize_training_program_work_detail_fragment(offer, normalized)
    if normalized_training != normalized:
        normalized = normalized_training
        lowered = normalized.lower()
        if not normalized:
            return ""
    normalized_rental_condition = _normalize_vehicle_rental_condition_detail_fragment(offer, normalized)
    if normalized_rental_condition != normalized:
        normalized = normalized_rental_condition
        lowered = normalized.lower()
        if not normalized:
            return ""
    if lowered.startswith(("спешите ", "успейте ", "торопитесь ")):
        return ""
    if re.match(
        r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\s.-]{0,40},\s*(?:могу|можем|предлагаю|предлагаем|приглашаю|приглашаем)\b",
        normalized,
        re.IGNORECASE,
    ):
        return ""
    if lowered.startswith(("чувствуете ", "когда мы ", "почему ", "потому что ", "здесь у вас ")):
        return ""
    if lowered.startswith(("заберу, отвезу", "всё, как", "все, как")):
        return ""
    if _looks_like_service_area_detail_fragment(offer, normalized):
        return ""
    if _looks_like_service_experience_detail_fragment(offer, normalized):
        return ""
    if _looks_like_provider_portfolio_detail_fragment(offer, normalized):
        return ""
    if lowered.startswith("в аренду ") and "электроинструмент" in lowered:
        tail = re.sub(r"^в аренду\s+электроинструменты?\s*", "", normalized, flags=re.IGNORECASE)
        normalized = normalize_text(f"Аренда электроинструментов {tail}")
        lowered = normalized.lower()
    if _looks_like_non_service_visible_label(normalized):
        return ""
    if _looks_like_model_search(normalized):
        return ""
    if _looks_like_resale_or_inventory_detail(normalized):
        return ""
    if _contains_contact_fragment(normalized):
        return ""
    if any(phrase in lowered for phrase in PRODUCT_SERVICE_TAIL_PHRASES):
        return ""
    if any(phrase in lowered for phrase in PRODUCT_DETAILS_NOISE_PHRASES):
        return ""
    if any(phrase in lowered for phrase in PRODUCT_MARKETING_TAIL_PHRASES):
        return ""
    if any(phrase in lowered for phrase in PRODUCT_DETAILS_LEGAL_NOISE_PHRASES):
        return ""
    if DETAILS_MARKET_TENURE_RE.match(lowered):
        return ""
    if re.search(r"\bс\s+20\d{2}\s+года\s+работ", lowered):
        return ""
    if "слот" in lowered and any(marker in lowered for marker in ("огранич", "остал", "заполн")):
        return ""
    if "помните" in lowered and "спрашивал" in lowered:
        return ""
    if lowered.startswith("если вы ") or lowered.startswith("с внж вы "):
        return ""
    if lowered.startswith(PRODUCT_DETAILS_BENEFIT_PREFIXES):
        return ""
    if "с удовольствием помогу" in lowered:
        return ""
    if PRICE_FROM_RE.search(normalized):
        return ""
    if len(_tokenize(normalized)) < 2 and not _fragment_is_location_only(normalized, offer):
        return ""
    return _normalize_service_label_case(normalized)[:280]


def _details_duplicate_service_name(service_name: str, details: str) -> bool:
    def _key(value: str) -> str:
        normalized = normalize_text(EMOJI_CHAR_RE.sub(" ", value).replace("\ufe0f", " ")).lower()
        return re.sub(r"[^0-9a-zа-яё]+", "", normalized)

    normalized_service = _key(service_name)
    normalized_details = _key(details)
    return bool(normalized_service and normalized_details and normalized_service == normalized_details)


def _merge_publishable_details(
    offer: dict[str, Any],
    details: str,
    service_name: str,
    salvaged_fragments: list[str],
) -> str:
    fragments: list[str] = []
    seen: set[str] = set()
    for fragment in [*_split_publishable_detail_fragments(details), *salvaged_fragments]:
        cleaned = _clean_publishable_detail_fragment(offer, fragment)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key == service_name.lower() or _details_duplicate_service_name(service_name, cleaned) or key in seen:
            continue
        seen.add(key)
        fragments.append(cleaned)
    if not fragments:
        return ""

    trimmed_fragments: list[str] = []
    for fragment in fragments:
        candidate_details = normalize_text("; ".join([*trimmed_fragments, fragment]))
        if trimmed_fragments and len(_tokenize(candidate_details)) >= 28 and len(candidate_details) >= 180:
            break
        if not trimmed_fragments and len(_tokenize(candidate_details)) >= 28 and len(candidate_details) >= 180:
            continue
        trimmed_fragments.append(fragment)

    final_fragments = trimmed_fragments or fragments[:1]
    return normalize_text("; ".join(final_fragments))[:280]


def _telegram_handle_from_url(url: str) -> str:
    normalized_url = normalize_url(url)
    match = TELEGRAM_CONTACT_URL_RE.match(normalized_url)
    if not match:
        return ""
    return normalize_handle(match.group("handle"))


def _contact_endpoint_signature(value: Any) -> tuple[str, str]:
    normalized = normalize_text(_as_text(value))
    if not normalized:
        return "", ""

    lowered = normalized.lower()
    email_match = EMAIL_RE.fullmatch(lowered)
    if email_match:
        email = email_match.group(0)
        return f"email:{email}", email

    if normalized.startswith("@"):
        handle = normalize_handle(normalized)
        return (f"telegram:{handle}", f"@{handle}") if handle else ("", "")

    if URL_RE.search(normalized) or (" " not in normalized and "." in normalized):
        normalized_url = normalize_url(normalized)
        handle = _telegram_handle_from_url(normalized_url)
        if handle:
            return f"telegram:{handle}", f"@{handle}"
        return f"url:{normalized_url}", normalized_url

    if PHONE_RE.search(normalized):
        digits = normalize_phone(normalized)
        return (f"phone:{digits}", f"+{digits}") if digits else ("", "")

    return "", ""


def _append_contact_endpoint(
    result: list[tuple[str, str]],
    seen: set[str],
    value: Any,
) -> None:
    endpoint_key, display_value = _contact_endpoint_signature(value)
    if not endpoint_key or endpoint_key in seen:
        return
    seen.add(endpoint_key)
    result.append((endpoint_key, display_value))


def _build_offer_contact_endpoints(offer: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in (
        *(_format_contact_candidate_display("phone", value) for value in _uniq_str_list(offer.get("explicit_contact_snapshot_phones"))),
        *(_format_contact_candidate_display("telegram_handle", value) for value in _uniq_str_list(offer.get("explicit_contact_snapshot_telegram_handles"))),
        *(_format_contact_candidate_display("telegram_link", value) for value in _uniq_str_list(offer.get("explicit_contact_snapshot_telegram_links"))),
        *(_format_contact_candidate_display("email", value) for value in _uniq_str_list(offer.get("contact_snapshot_emails"))),
        *(_format_contact_candidate_display("website", value) for value in _uniq_str_list(offer.get("contact_snapshot_websites"))),
        _as_text(offer.get("contact_candidate_display")),
        *(_format_contact_candidate_display("telegram_handle", value) for value in _uniq_str_list(offer.get("author_fallback_telegram_handles"))),
        *(_format_contact_candidate_display("telegram_link", value) for value in _uniq_str_list(offer.get("author_fallback_telegram_links"))),
        *(_format_contact_candidate_display("phone", value) for value in _uniq_str_list(offer.get("author_fallback_phones"))),
    ):
        _append_contact_endpoint(result, seen, value)
    return result


def _extract_contact_endpoints_from_text(text: Any) -> list[tuple[str, str]]:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return []

    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in CONTACT_SPLIT_RE.split(normalized):
        candidate = part.strip(" ,")
        if not candidate:
            continue

        matched = False
        for match in EMAIL_RE.finditer(candidate):
            _append_contact_endpoint(result, seen, match.group(0))
            matched = True
        for match in URL_EXTRACT_RE.finditer(candidate):
            _append_contact_endpoint(result, seen, match.group(0))
            matched = True
        for match in HANDLE_RE.finditer(candidate):
            _append_contact_endpoint(result, seen, match.group(0))
            matched = True
        for match in PHONE_RE.finditer(candidate):
            _append_contact_endpoint(result, seen, match.group(0))
            matched = True

        if not matched:
            _append_contact_endpoint(result, seen, candidate)
    return result


def _resolve_publishable_contact(offer: dict[str, Any]) -> tuple[str, str]:
    supported_endpoints = dict(_build_offer_contact_endpoints(offer))
    if not supported_endpoints:
        return "", "publishable_contact_missing"

    row_endpoints = _extract_contact_endpoints_from_text(offer.get("product_row_contact"))
    supported_row_keys = [endpoint_key for endpoint_key, _ in row_endpoints if endpoint_key in supported_endpoints]
    unique_row_keys = list(dict.fromkeys(supported_row_keys))
    preferred_key, _ = _contact_endpoint_signature(offer.get("contact_candidate_display"))

    if unique_row_keys:
        if preferred_key and preferred_key in supported_endpoints:
            return supported_endpoints[preferred_key], ""
        if len(unique_row_keys) == 1:
            return supported_endpoints[unique_row_keys[0]], ""
        return "", "publishable_contact_ambiguous"

    if preferred_key and preferred_key in supported_endpoints:
        return supported_endpoints[preferred_key], ""
    if len(supported_endpoints) == 1:
        return next(iter(supported_endpoints.values())), ""
    return "", "publishable_contact_ambiguous"


def _contains_contact_fragment(text: Any) -> bool:
    return bool(_extract_contact_endpoints_from_text(text))


def _canonical_telegram_message_url(value: Any) -> str:
    normalized = normalize_text(_as_text(value))
    if not normalized:
        return ""
    url_match = TELEGRAM_MESSAGE_URL_RE.match(normalize_url(normalized))
    if url_match:
        return f"https://t.me/{normalize_handle(url_match.group('handle'))}/{url_match.group('message_id')}"
    if SOURCE_ANCHOR_RE.fullmatch(normalized):
        handle, message_id = normalized[1:].split("/", 1)
        normalized_handle = normalize_handle(handle)
        return f"https://t.me/{normalized_handle}/{message_id}" if normalized_handle and message_id.isdigit() else ""
    return ""


def _build_publishable_source(offer: dict[str, Any]) -> str:
    for candidate in (
        offer.get("latest_post_url"),
        offer.get("source_anchor_text"),
    ):
        resolved = _canonical_telegram_message_url(candidate)
        if resolved:
            return resolved
    return ""


def _format_serbia_actual_on(value: Any) -> str:
    raw_value = _as_text(value).strip()
    if not raw_value:
        return ""
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SERBIA_TZ).strftime("%d.%m.%Y")


def _coerce_price_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    text = _as_text(value).strip()
    if not text:
        return None
    compact = text.replace(" ", "")
    if compact.count(".") >= 1 and compact.count(",") == 0:
        parts = compact.split(".")
        if all(part.isdigit() for part in parts) and all(len(part) == 3 for part in parts[1:]):
            compact = "".join(parts)
    if compact.count(",") == 1 and compact.count(".") == 0:
        compact = compact.replace(",", ".")
    else:
        compact = compact.replace(",", "")
    try:
        parsed = float(compact)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize_price_currency_token(value: Any) -> str:
    lowered = normalize_text(_as_text(value)).lower()
    if not lowered:
        return ""
    if any(token in lowered for token in ("eur", "euro", "€", "евро")):
        return "eur"
    if any(token in lowered for token in ("rsd", "din", "dinar", "дин")):
        return "rsd"
    if any(token in lowered for token in ("usd", "$")):
        return "usd"
    return ""


def _format_price_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _extract_price_numbers_from_text(text: str) -> list[float]:
    numbers: list[float] = []
    for raw_number in re.findall(r"\d[\d\s.,]*", normalize_text(text)):
        parsed = _coerce_price_number(raw_number)
        if parsed is not None:
            numbers.append(parsed)
    return numbers


def _correct_collapsed_rsd_thousands_price(
    price_min: float,
    price_max: float,
    currency: str,
    raw_price_text: str,
) -> tuple[float, float]:
    if currency != "rsd" or price_min > 99 or price_max > 99:
        return price_min, price_max
    extracted_numbers = sorted({number for number in _extract_price_numbers_from_text(raw_price_text) if number >= 1000})
    if len(extracted_numbers) != 1:
        return price_min, price_max
    corrected = extracted_numbers[0]
    return corrected, corrected


def _format_publishable_price(offer: dict[str, Any]) -> str:
    price_min = _coerce_price_number(offer.get("price_min"))
    price_max = _coerce_price_number(offer.get("price_max"))
    currency = _normalize_price_currency_token(offer.get("currency_code"))
    raw_price_text = normalize_text(
        " ".join(
            part
            for part in (
                _as_text(offer.get("price_candidate_text")),
                _as_text(offer.get("price_text_best")),
                _as_text(offer.get("product_row_details")),
                _as_text(offer.get("details_candidate")),
            )
            if part
        )
    )

    if price_min is None and price_max is None:
        extracted_numbers = sorted(set(_extract_price_numbers_from_text(raw_price_text)))
        if len(extracted_numbers) == 1:
            price_min = price_max = extracted_numbers[0]
        elif len(extracted_numbers) == 2:
            price_min, price_max = sorted(extracted_numbers)
        else:
            return ""
        currency = currency or _normalize_price_currency_token(raw_price_text)

    if price_min is None and price_max is not None:
        price_min = price_max
    if price_max is None and price_min is not None:
        price_max = price_min

    if price_min is None or price_max is None or not currency:
        return ""

    if price_max < price_min:
        price_min, price_max = price_max, price_min

    price_min, price_max = _correct_collapsed_rsd_thousands_price(price_min, price_max, currency, raw_price_text)

    if math.isclose(price_min, price_max):
        return f"{_format_price_number(price_min)} {currency}"
    return f"{_format_price_number(price_min)}-{_format_price_number(price_max)} {currency}"


def _first_publishable_contact_value(
    supported_endpoints: dict[str, str],
    *,
    prefix: str,
) -> str:
    for endpoint_key, display_value in supported_endpoints.items():
        if endpoint_key.startswith(prefix):
            return display_value
    return ""


def _resolve_publishable_contact_channels(offer: dict[str, Any]) -> tuple[dict[str, str], str]:
    supported_endpoints = dict(_build_offer_contact_endpoints(offer))
    telegram_value = _first_publishable_contact_value(supported_endpoints, prefix="telegram:")
    phone_value = _first_publishable_contact_value(supported_endpoints, prefix="phone:")
    instagram_value = ""
    whatsapp_value = ""

    preferred_key, _ = _contact_endpoint_signature(offer.get("contact_candidate_display"))
    preferred_contact = ""
    if preferred_key.startswith("telegram:"):
        preferred_contact = telegram_value
    elif preferred_key.startswith("phone:"):
        preferred_contact = phone_value

    fallback_contact = next(
        (
            value
            for value in (
                telegram_value,
                instagram_value,
                whatsapp_value,
                phone_value,
            )
            if value
        ),
        "",
    )
    if not fallback_contact:
        return {
            "contact": "",
            "telegram": "",
            "instagram": "",
            "whatsapp": "",
            "phone": "",
        }, "publishable_contact_missing"

    return {
        "contact": preferred_contact or fallback_contact,
        "telegram": telegram_value,
        "instagram": instagram_value,
        "whatsapp": whatsapp_value,
        "phone": phone_value,
    }, ""


def _category_has_publishable_signal(
    category_label: str,
    offer: dict[str, Any],
    service_name: str,
    details: str,
) -> bool:
    normalized_label = _normalize_category_display_label(category_label)
    if not normalized_label:
        return False
    category_primary = PRODUCT_CATEGORY_PRIMARY_BY_DISPLAY.get(normalize_text(normalized_label).lower(), "")
    if not category_primary:
        return False

    signal_text = normalize_text(
        " ".join(
            part
            for part in (
                service_name,
                details,
                _as_text(offer.get("service_name_candidate")),
                _as_text(offer.get("details_candidate")),
                " ".join(_uniq_str_list(offer.get("service_tags"))),
                _as_text(offer.get("title_best")),
                _as_text(offer.get("description_best")),
            )
            if part
        )
    ).lower()
    if category_primary == "cleaning" and _looks_like_device_repair_context(signal_text) and not _looks_like_aircon_cleaning_only_context(signal_text):
        return False
    inferred_label = _infer_publishable_category_from_product_text(offer, service_name, details)
    inferred_primary = PRODUCT_CATEGORY_PRIMARY_BY_DISPLAY.get(normalize_text(inferred_label).lower(), "")
    if inferred_primary and inferred_primary != category_primary:
        return False
    if category_primary == "it_digital" and _looks_like_photo_video_production_context(signal_text):
        return True
    hints = PRODUCT_CATEGORY_SIGNAL_HINTS.get(category_primary, ())
    return any(normalize_text(hint).lower() in signal_text for hint in hints)


def _looks_like_service_channel_hiring_post(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if not any(marker in lowered for marker in PRODUCT_SERVICE_CHANNEL_HIRING_INTRO_HINTS):
        return False
    if not any(marker in lowered for marker in PRODUCT_SERVICE_CHANNEL_HIRING_ROLE_HINTS):
        return False
    condition_hits = _count_phrase_hits(lowered, PRODUCT_SERVICE_CHANNEL_HIRING_CONDITION_HINTS)
    if condition_hits >= 2:
        return True
    return condition_hits >= 1 and bool(re.search(r"\b\d{1,2}\s*[-–]\s*\d{1,2}\s*%", lowered))


def _looks_like_vacancy_or_cv(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    normalized = _strip_vehicle_rental_requirement_vacancy_noise(normalized)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _looks_like_service_channel_hiring_post(normalized):
        return True
    if lowered.startswith(("требуются ", "требуется ")):
        return True
    tokens = _tokenize(normalized)
    keyword_hits = tokens.intersection(PRODUCT_VACANCY_KEYWORDS)
    phrase_hits = _count_phrase_hits(lowered, PRODUCT_VACANCY_PHRASES)
    if phrase_hits >= 2:
        return True
    if phrase_hits >= 1 and keyword_hits:
        return True
    if len(keyword_hits) >= 3:
        return True
    if (
        tokens.intersection(PRODUCT_JOB_PROFILE_ROLE_HINTS)
        and tokens.intersection(PRODUCT_JOB_PROFILE_SENIORITY_HINTS)
        and tokens.intersection(PRODUCT_JOB_PROFILE_EXPERIENCE_HINTS)
    ):
        return True
    return "cv" in keyword_hits and ("\u0438\u0449\u0443\u0440\u0430\u0431\u043e\u0442\u0443" in lowered or "\u0438\u0449\u0443 \u0440\u0430\u0431\u043e\u0442\u0443" in lowered)


def _looks_like_platform_promo(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    lowered = normalized.lower()
    if _looks_like_real_estate_platform_promo(lowered):
        return True
    phrase_hits = _count_phrase_hits(lowered, PRODUCT_PLATFORM_PROMO_PHRASES)
    if phrase_hits >= 2:
        return True
    repost_hits = _count_phrase_hits(lowered, PRODUCT_PLATFORM_REPOST_PROMO_PHRASES)
    if repost_hits >= 2:
        return True
    if repost_hits >= 1 and phrase_hits >= 1:
        return True
    if (
        ("\u043f\u0440\u0438\u0432\u043b\u0435\u0447\u044c \u043d\u043e\u0432\u0443\u044e \u0430\u0443\u0434\u0438\u0442\u043e\u0440\u0438\u044e" in lowered or "\u043f\u0440\u0438\u0432\u043b\u0435\u0447\u044c \u0430\u0443\u0434\u0438\u0442\u043e\u0440\u0438\u044e" in lowered)
        and any(marker in lowered for marker in ("\u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d", "\u043a\u0430\u043d\u0430\u043b", "\u0440\u0430\u0437\u043c\u0435\u0441\u0442"))
    ):
        return True
    return False


def _looks_like_remote_work_hiring_platform(text: Any) -> bool:
    normalized = normalize_text(_as_text(text))
    if not normalized:
        return False
    lowered = normalized.lower()
    employment_hit = any(marker in lowered for marker in PRODUCT_REMOTE_WORK_EMPLOYMENT_HINTS)
    platform_hit = any(marker in lowered for marker in PRODUCT_REMOTE_WORK_PLATFORM_HINTS)
    if not employment_hit or not platform_hit:
        return False
    remote_hit = any(marker in lowered for marker in PRODUCT_REMOTE_WORK_MODE_HINTS)
    return remote_hit or _looks_like_platform_promo(lowered)


def _looks_like_chat_directory_row(service_name: str, details: str) -> bool:
    combined = normalize_text(" ".join(part for part in (service_name, details) if part)).lower()
    if not combined:
        return False
    if not _contains_any_phrase(combined, PRODUCT_CHAT_DIRECTORY_HINTS):
        return False
    if _contains_any_phrase(combined, PRODUCT_CHAT_DIRECTORY_SERVICE_ALLOW_HINTS):
        return False
    return True


def _looks_like_device_repair_context(signal_text: str) -> bool:
    if not signal_text:
        return False
    repair_hits = _count_phrase_hits(signal_text, PRODUCT_REPAIR_CONTEXT_HINTS)
    hardware_hits = _tokenize(signal_text).intersection(PRODUCT_HARDWARE_HINTS)
    if hardware_hits and repair_hits >= 2:
        return True
    if repair_hits >= 4:
        return True
    if _contains_any_phrase(signal_text, PRODUCT_HOUSEHOLD_CLEANING_CONTEXT_HINTS):
        return False
    return repair_hits >= 2 and bool(hardware_hits)


def _looks_like_household_repair_master_context(signal_text: str) -> bool:
    if not signal_text:
        return False
    master_hit = any(hint in signal_text for hint in ("мастер", "муж на час", "master", "мужская помощь"))
    repair_hits = _count_phrase_hits(signal_text, PRODUCT_HOUSEHOLD_REPAIR_MASTER_HINTS)
    if not master_hit:
        return False
    if "мастер на час" in signal_text or "муж на час" in signal_text:
        return True
    if "мужская помощь" in signal_text and any(marker in signal_text for marker in ("сломал", "сломалось", "почин", "ремонт")):
        return True
    return repair_hits >= 2


def _looks_like_window_repair_or_install_context(signal_text: str) -> bool:
    if not signal_text:
        return False
    window_hit = any(hint in signal_text for hint in ("окно", "окна", "окон", "window"))
    screen_hit = any(hint in signal_text for hint in ("москит", "сетка", "сетк", "screen"))
    work_hit = any(hint in signal_text for hint in ("ремонт", "монтаж", "установ", "замена", "изготов", "мастер"))
    return window_hit and (screen_hit or work_hit)


def _looks_like_earthworks_or_materials_context(signal_text: str) -> bool:
    if not signal_text:
        return False
    earthworks_hit = any(hint in signal_text for hint in ("землян", "земляные", "копка", "котлован", "экскаватор"))
    materials_hit = any(hint in signal_text for hint in ("инертн", "щеб", "песок", "грав", "материал", "черноз"))
    work_hit = any(hint in signal_text for hint in ("работ", "поставк", "доставк", "техник", "строит"))
    return (earthworks_hit and work_hit) or (earthworks_hit and materials_hit) or (materials_hit and "поставк" in signal_text)


def _category_priority_score(category_primary: str, signal_text: str) -> int:
    hints = PRODUCT_CATEGORY_SIGNAL_HINTS.get(category_primary, ())
    score = sum(1 for hint in hints if normalize_text(hint).lower() in signal_text)
    if category_primary == "food_hospitality" and any(
        hint in signal_text for hint in ("чизкейк", "кейк", "десерт", "торт", "cake")
    ):
        score += 3
    if category_primary == "legal_docs" and any(
        hint in signal_text for hint in ("визаран", "visa run", "виза ран", "внж", "документ", "легализац")
    ):
        score += 3
    if category_primary == "beauty_cosmetology" and any(
        hint in signal_text for hint in ("косметолог", "кожа", "лицо", "массаж", "самомассаж", "метод")
    ):
        score += 2
    if category_primary == "beauty_cosmetology" and _looks_like_medical_rehab_context(signal_text):
        score += 4
    if category_primary == "auto_service" and any(
        hint in signal_text for hint in ("авто под ключ", "автомобиль под ключ", "пригон авто", "пригнать авто", "из европы")
    ):
        score += 3
    if category_primary == "auto_service" and _looks_like_auto_service_context(signal_text):
        score += 4
    if category_primary == "moving_delivery" and _looks_like_transport_delivery_context(signal_text):
        score += 4
    if category_primary == "education_tutoring" and _looks_like_language_tutoring_context(signal_text):
        score += 4
    if category_primary == "construction_repair" and (
        _looks_like_device_repair_context(signal_text)
        or _looks_like_household_repair_master_context(signal_text)
        or _looks_like_earthworks_or_materials_context(signal_text)
        or _looks_like_property_technical_inspection_context(signal_text)
        or _looks_like_hvac_repair_context(signal_text)
    ):
        score += 3
    if category_primary == "construction_repair" and any(
        hint in signal_text for hint in ("мастер на час", "муж на час", "русский мастер", "единая служба")
    ):
        score += 3
    if category_primary == "auto_service" and any(hint in signal_text for hint in ("трансфер", "пассажир")):
        score += 1
    if category_primary == "cleaning" and any(hint in signal_text for hint in ("клинин", "химчист", "уборк", "дезинфекц")):
        score += 2
    if category_primary == "psychology" and any(hint in signal_text for hint in PRODUCT_PROFORIENTATION_HINTS):
        score += 3
    if category_primary == "beauty_cosmetology" and any(hint in signal_text for hint in ("педикюр", "pedikir", "маникюр")):
        score += 2
    if category_primary == "legal_docs" and any(hint in signal_text for hint in ("внж", "документ", "legal")):
        score += 2
    if category_primary == "marketing_promotion" and any(hint in signal_text for hint in ("маркетинг", "продвижен", "реклам")):
        score += 2
    if category_primary == "it_digital" and any(hint in signal_text for hint in ("smm", "seo", "website", "digital")):
        score += 1
    if category_primary == "it_digital" and any(
        hint in signal_text for hint in ("маркетинг", "продвижен", "реклам", "таргет", "личный бренд")
    ):
        score += 2
    return score


def _infer_publishable_category_from_product_text(
    offer: dict[str, Any],
    service_name: str,
    details: str,
) -> str:
    signal_text = normalize_text(
        " ".join(
            part
            for part in (
                service_name,
                details,
                _as_text(offer.get("product_row_service_name")),
                _as_text(offer.get("product_row_details")),
                _as_text(offer.get("service_name_candidate")),
                _as_text(offer.get("details_candidate")),
                " ".join(_uniq_str_list(offer.get("service_tags"))),
                _as_text(offer.get("title_best")),
                _as_text(offer.get("description_best")),
            )
            if part
        )
    ).lower()
    if not signal_text:
        return ""
    if _looks_like_photo_video_production_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["it_digital"]
    if _looks_like_auto_service_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["auto_service"]
    if _looks_like_aircon_cleaning_only_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["cleaning"]
    if _looks_like_hvac_repair_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["construction_repair"]
    if _looks_like_transport_delivery_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["moving_delivery"]
    if _looks_like_language_tutoring_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["education_tutoring"]
    if _looks_like_medical_rehab_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["beauty_cosmetology"]
    if (
        _looks_like_tool_rental_context(signal_text)
        or _looks_like_furniture_made_to_order_context(signal_text)
        or ("стиральн" in signal_text and "ремонт" in signal_text)
        or _looks_like_earthworks_or_materials_context(signal_text)
        or _looks_like_property_technical_inspection_context(signal_text)
    ):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["construction_repair"]
    if _looks_like_massage_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["beauty_cosmetology"]
    if _looks_like_household_repair_master_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["construction_repair"]
    if _looks_like_window_repair_or_install_context(signal_text):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["construction_repair"]
    if any(hint in signal_text for hint in ("кондиционер", "кондиционеров")) and any(
        hint in signal_text for hint in ("чистк", "мойк", "фильтр", "турбин", "дезинфекц")
    ):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["cleaning"]
    if (
        _looks_like_device_repair_context(signal_text)
        or _looks_like_household_repair_master_context(signal_text)
        or _looks_like_window_repair_or_install_context(signal_text)
    ):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["construction_repair"]
    if any(hint in signal_text for hint in PRODUCT_PROFORIENTATION_HINTS) and any(
        marker in signal_text for marker in ("консультац", "психолог", "терап")
    ):
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY["psychology"]

    scored_categories = [
        (category_primary, _category_priority_score(category_primary, signal_text))
        for category_primary in PRODUCT_CATEGORY_SIGNAL_HINTS
    ]
    scored_categories = [(category_primary, score) for category_primary, score in scored_categories if score > 0]
    if not scored_categories:
        return ""
    scored_categories.sort(key=lambda item: item[1], reverse=True)
    if len(scored_categories) == 1 or scored_categories[0][1] > scored_categories[1][1]:
        return PRODUCT_CATEGORY_DISPLAY_BY_PRIMARY.get(scored_categories[0][0], "")
    return ""


def _resolve_publishable_category(
    offer: dict[str, Any],
    category_label: str,
    service_name: str,
    details: str,
) -> str:
    normalized_label = _normalize_category_display_label(category_label)
    if not normalize_text(category_label):
        return _infer_publishable_category_from_product_text(offer, service_name, details)
    if not normalized_label:
        return ""
    if _category_has_publishable_signal(normalized_label, offer, service_name, details):
        return normalized_label
    return _infer_publishable_category_from_product_text(offer, service_name, details)


def _classify_publishable_row_issue(
    offer: dict[str, Any],
    service_name: str,
    details: str,
) -> str:
    if not service_name:
        return "publishable_missing_service_name"

    normalized_service = normalize_text(service_name)
    normalized_details = normalize_text(details)
    combined_text = normalize_text(" ".join(part for part in (normalized_service, normalized_details) if part))
    signal_text = normalize_text(
        " ".join(
            part
            for part in (
                normalized_service,
                normalized_details,
                _as_text(offer.get("product_row_service_name")),
                _as_text(offer.get("product_row_details")),
                _as_text(offer.get("service_name_candidate")),
                _as_text(offer.get("details_candidate")),
                _as_text(offer.get("title_best")),
                _as_text(offer.get("description_best")),
            )
            if part
        )
    )
    if not combined_text:
        return "publishable_empty_offer"

    service_lower = normalized_service.lower()
    details_lower = normalized_details.lower()
    combined_lower = combined_text.lower()
    hardware_hits = _tokenize(combined_text).intersection(PRODUCT_HARDWARE_HINTS)

    if _starts_with_any(service_lower, PRODUCT_GREETING_PREFIXES) or _starts_with_any(details_lower, PRODUCT_GREETING_PREFIXES):
        return "publishable_greeting_block"
    if _starts_with_any(service_lower, PRODUCT_SELF_INTRO_PREFIXES) or _starts_with_any(details_lower, PRODUCT_SELF_INTRO_PREFIXES):
        return "publishable_self_intro_block"
    if _count_emoji_chars(normalized_service) + _count_emoji_chars(normalized_details) >= 4:
        return "publishable_emoji_storm"
    if _looks_like_non_service_visible_label(normalized_service):
        return "publishable_non_service"
    if _contains_contact_fragment(normalized_service) or _contains_contact_fragment(normalized_details):
        return "publishable_raw_dump"
    if _looks_like_model_search(signal_text):
        return "publishable_non_service"
    if _looks_like_real_estate_listing(signal_text):
        return "publishable_non_service"
    if _looks_like_esoteric_offer(signal_text):
        return "publishable_non_service"
    if _looks_like_remote_work_hiring_platform(signal_text):
        return "publishable_non_service"
    if _looks_like_vacancy_or_cv(combined_text):
        return "publishable_non_service"
    if _looks_like_platform_promo(combined_text):
        return "publishable_non_service"
    if _looks_like_chat_directory_row(normalized_service, normalized_details):
        return "publishable_non_service"
    if _looks_like_purchase_request_context(signal_text):
        return "publishable_non_service"
    if _looks_like_tool_or_workspace_rental_request(signal_text):
        return "publishable_non_service"
    if _looks_like_goods_price_info_or_review(signal_text):
        return "publishable_non_service"
    if _looks_like_complaint_or_problem_report(signal_text):
        return "publishable_non_service"
    if _looks_like_holiday_greeting_noise(normalized_service, normalized_details):
        return "publishable_non_service"
    if _looks_like_news_marketing_headline_noise(signal_text):
        return "publishable_non_service"
    if _looks_like_moderation_bot_noise(signal_text):
        return "publishable_non_service"
    if _looks_like_food_or_goods_sale_offer(normalized_service, normalized_details):
        return "publishable_non_service"
    if _looks_like_event_or_social_noise(normalized_service, normalized_details):
        return "publishable_non_service"
    if _starts_with_any(service_lower, PRODUCT_RESALE_PREFIXES) or _starts_with_any(details_lower, PRODUCT_RESALE_PREFIXES):
        return "publishable_resale_dump"
    if len(hardware_hits) >= 2 and any(hint in combined_lower for hint in ("sell", "sale", "продам", "продажа")):
        return "publishable_resale_dump"
    if _looks_like_product_noise(normalized_service) or _looks_like_product_noise(normalized_details):
        return "publishable_raw_dump"
    if _service_label_looks_sentence_like(normalized_service):
        return "publishable_raw_dump"
    if normalize_text(normalized_service).lower() in PRODUCT_GENERIC_SERVICE_NAMES:
        return "publishable_non_service"
    if _contains_any_phrase(combined_lower, PRODUCT_NON_SERVICE_PHRASES):
        return "publishable_non_service"
    if _as_text(offer.get("fact_pack_quality")) == "weak_signal":
        if len(_tokenize(combined_text)) < MIN_TEXT_SIGNAL_TOKENS:
            return "publishable_empty_offer"
        if any(phrase in combined_lower for phrase in PRODUCT_GENERIC_SERVICE_PHRASES):
            return "publishable_non_service"
    return ""


def _empty_publishable_row(reason_text: str) -> dict[str, str]:
    return {
        "publish_decision": "drop",
        "service_name": "",
        "details": "",
        "category": "",
        "price": "",
        "contact": "",
        "telegram": "",
        "instagram": "",
        "whatsapp": "",
        "phone": "",
        "source": "",
        "actual_on": "",
        "audit_reason": normalize_text(reason_text)[:240],
    }


def _build_publishable_row(offer: dict[str, Any]) -> dict[str, str]:
    if _as_text(offer.get("product_row_publish_decision")) != "publish":
        return _empty_publishable_row(_as_text(offer.get("product_row_audit_reason")) or "product_row_not_publishable")

    raw_service_name = normalize_text(_as_text(offer.get("product_row_service_name")))
    raw_details = normalize_text(_as_text(offer.get("product_row_details")))
    if _count_emoji_chars(raw_service_name) + _count_emoji_chars(raw_details) >= 4:
        return _empty_publishable_row("publishable_emoji_storm")
    if _looks_like_one_off_trip_availability(raw_service_name, raw_details):
        return _empty_publishable_row("publishable_one_off_trip")
    service_name, salvaged_fragments = _clean_publishable_service_label(offer, raw_service_name)
    details = _merge_publishable_details(offer, raw_details, service_name, salvaged_fragments) if service_name else ""
    issue = _classify_publishable_row_issue(offer, service_name, details)
    if issue:
        return _empty_publishable_row(issue)

    contact_channels, contact_issue = _resolve_publishable_contact_channels(offer)
    if contact_issue:
        return _empty_publishable_row(contact_issue)

    source_value = _build_publishable_source(offer)
    if not source_value:
        return _empty_publishable_row("publishable_source_missing")

    actual_on_value = _format_serbia_actual_on(_as_text(offer.get("freshness_at_utc")) or _as_text(offer.get("last_seen_at_utc")))
    if not actual_on_value:
        return _empty_publishable_row("publishable_actual_on_missing")

    resolved_category = _resolve_publishable_category(offer, _as_text(offer.get("product_row_category")), service_name, details)
    if not resolved_category:
        return _empty_publishable_row("publishable_category_missing")

    return {
        "publish_decision": "publish",
        "service_name": service_name,
        "details": details,
        "category": resolved_category,
        "price": _format_publishable_price(offer),
        "contact": contact_channels["contact"],
        "telegram": contact_channels["telegram"],
        "instagram": contact_channels["instagram"],
        "whatsapp": contact_channels["whatsapp"],
        "phone": contact_channels["phone"],
        "source": source_value,
        "actual_on": actual_on_value,
        "audit_reason": _as_text(offer.get("product_row_audit_reason"))[:240],
    }


def _finalize_product_rows(offers: list[dict[str, Any]]) -> None:
    for offer in offers:
        if _as_text(offer.get("offer_state")) not in {"rejected", "suppressed"} and _as_text(
            offer.get("serbia_relevance_verdict")
        ) != "outside_serbia":
            offer["publishable_row"] = _build_publishable_row(offer)
            continue
        reason = (
            _as_text(offer.get("offer_rejection_reason"))
            or (
                "outside_serbia"
                if _as_text(offer.get("serbia_relevance_verdict")) == "outside_serbia"
                else "offer_state_not_publishable"
            )
        )
        _apply_offer_patch(
            offer,
            {
                "product_row_publish_decision": "drop",
                "product_row_service_name": "",
                "product_row_details": "",
                "product_row_category": "",
                "product_row_contact": "",
                "product_row_audit_reason": reason[:240],
            },
        )
        offer["publishable_row"] = _build_publishable_row(offer)


def _offer_signal_text(offer: dict[str, Any]) -> str:
    parts = [
        _as_text(offer.get("title_best")),
        _as_text(offer.get("description_best")),
        " ".join(_uniq_str_list(offer.get("service_tags"))),
        " ".join(_uniq_str_list(offer.get("city_codes"))),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def _provider_signal_text(provider: dict[str, Any]) -> str:
    parts = [
        _as_text(provider.get("canonical_name")),
        _as_text(provider.get("display_name_best")),
        " ".join(_uniq_str_list(provider.get("service_category_hints"))),
        " ".join(_uniq_str_list(provider.get("city_codes"))),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def _build_offer_snapshot(offer: dict[str, Any]) -> dict[str, Any]:
    return {
        "offer_key": _as_text(offer.get("offer_key")),
        "provider_key": _as_text(offer.get("provider_key")),
        "offer_state": _as_text(offer.get("offer_state")),
        "service_signature_key": _as_text(offer.get("service_signature_key")),
        "category_primary": _as_text(offer.get("category_primary")),
        "category_secondary": _as_text(offer.get("category_secondary")),
        "title_best": _as_text(offer.get("title_best")),
        "description_best": _as_text(offer.get("description_best")),
        "price_text_best": _as_text(offer.get("price_text_best")),
        "city_codes": _uniq_str_list(offer.get("city_codes")),
        "service_tags": _uniq_str_list(offer.get("service_tags")),
        "dedupe_confidence": _as_text(offer.get("dedupe_confidence")),
        "serbia_relevance_verdict": _as_text(offer.get("serbia_relevance_verdict")),
    }


def _build_provider_snapshot(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_key": _as_text(provider.get("provider_key")),
        "provider_state": _as_text(provider.get("provider_state")),
        "identity_strength": _as_text(provider.get("identity_strength")),
        "display_name_best": _as_text(provider.get("display_name_best")),
        "canonical_name": _as_text(provider.get("canonical_name")),
        "provider_summary": _as_text(provider.get("provider_summary")),
        "service_category_hints": _uniq_str_list(provider.get("service_category_hints")),
        "city_codes": _uniq_str_list(provider.get("city_codes")),
        "dedupe_confidence": _as_text(provider.get("dedupe_confidence")),
        "offer_count": int(provider.get("offer_count") or 0),
    }


def _seed_default_product_rows(
    offers: list[dict[str, Any]],
    deterministic_offers_by_key: dict[str, dict[str, Any]],
) -> None:
    for offer in offers:
        offer_key = _as_text(offer.get("offer_key"))
        source_offer = deterministic_offers_by_key.get(offer_key, offer)
        _apply_offer_patch(offer, _build_default_product_row(source_offer))


def _offer_has_contacts(offer: dict[str, Any]) -> bool:
    return bool(
        _uniq_str_list(offer.get("contact_snapshot_phones"))
        or _uniq_str_list(offer.get("contact_snapshot_telegram_handles"))
        or _uniq_str_list(offer.get("contact_snapshot_telegram_links"))
    )


def _product_raw_evidence_signal_text(offer: dict[str, Any], raw_post_map: dict[str, dict[str, Any]]) -> str:
    fragments: list[str] = []
    for raw_post_id in _uniq_str_list(offer.get("evidence_raw_post_ids")):
        raw_post = raw_post_map.get(raw_post_id)
        if not isinstance(raw_post, dict):
            continue
        fragments.append(_as_text(raw_post.get("text_raw")))
        fragments.append(_as_text(raw_post.get("text_normalized")))
    return normalize_text(" ".join(fragment for fragment in fragments if fragment))


def _apply_product_row_policy_drop(offer: dict[str, Any], reason_text: str) -> None:
    _apply_offer_patch(
        offer,
        {
            "product_row_publish_decision": "drop",
            "product_row_service_name": "",
            "product_row_details": "",
            "product_row_category": "",
            "product_row_contact": "",
            "product_row_audit_reason": reason_text[:240],
        },
    )


def _build_product_row_candidates(
    *,
    deterministic_providers_by_key: dict[str, dict[str, Any]],
    deterministic_offers_by_key: dict[str, dict[str, Any]],
    offers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for offer_key, offer in offers_by_key.items():
        if _as_text(offer.get("offer_state")) in {"rejected", "suppressed"}:
            continue
        if _as_text(offer.get("serbia_relevance_verdict")) == "outside_serbia":
            continue
        deterministic_offer = deterministic_offers_by_key.get(offer_key, offer)
        if not _offer_can_become_visible_product_row(deterministic_offer):
            continue
        raw_evidence_text = _product_raw_evidence_signal_text(deterministic_offer, raw_post_map)
        policy_drop_reason = _product_row_policy_drop_reason(deterministic_offer, raw_evidence_text)
        if policy_drop_reason:
            _apply_product_row_policy_drop(offer, policy_drop_reason)
            continue
        provider = deterministic_providers_by_key.get(_as_text(deterministic_offer.get("provider_key")), {})
        contact_candidates = _build_offer_contact_candidates(deterministic_offer)
        input_payload = _compact_prompt_payload(
            {
                "stage": "product_row_shape",
                "offer_anchor": {
                    "offer_key": _as_text(deterministic_offer.get("offer_key")),
                    "provider_key": _as_text(deterministic_offer.get("provider_key")),
                    "source_anchor_text": _as_text(deterministic_offer.get("source_anchor_text")),
                    "freshness_at_utc": _as_text(deterministic_offer.get("freshness_at_utc")),
                },
                "deterministic_fact_pack": {
                    "service_name_candidate": _as_text(deterministic_offer.get("service_name_candidate")),
                    "details_candidate": _as_text(deterministic_offer.get("details_candidate")),
                    "contact_candidate_display": _as_text(deterministic_offer.get("contact_candidate_display")),
                    "contact_candidates": contact_candidates,
                    "price_candidate_text": _as_text(deterministic_offer.get("price_candidate_text")),
                    "price_text_best": _as_text(deterministic_offer.get("price_text_best")),
                    "price_min": deterministic_offer.get("price_min"),
                    "price_max": deterministic_offer.get("price_max"),
                    "currency_code": _as_text(deterministic_offer.get("currency_code")),
                    "city_display_names": _uniq_str_list(deterministic_offer.get("city_display_names")),
                    "source_anchor_text": _as_text(deterministic_offer.get("source_anchor_text")),
                    "freshness_at_utc": _as_text(deterministic_offer.get("freshness_at_utc")),
                    "fact_pack_quality": _as_text(deterministic_offer.get("fact_pack_quality")),
                    "fact_pack_flags": _uniq_str_list(deterministic_offer.get("fact_pack_flags")),
                },
                "canonical_offer_facts": {
                    "offer_state": _as_text(deterministic_offer.get("offer_state")),
                    "offer_rejection_reason": _as_text(deterministic_offer.get("offer_rejection_reason")),
                    "category_primary": _as_text(deterministic_offer.get("category_primary")),
                    "category_display_candidate": _category_display_label(deterministic_offer.get("category_primary")),
                    "service_tags": _uniq_str_list(deterministic_offer.get("service_tags")),
                    "serbia_relevance_verdict": _as_text(deterministic_offer.get("serbia_relevance_verdict")),
                    "provider_display_name": _as_text(provider.get("display_name_best")),
                },
                "writer_contract": {
                    "llm_owned_visible_fields": [
                        "product_row_service_name",
                        "product_row_details",
                        "product_row_category",
                    ],
                    "deterministic_default_is_not_final_writer": True,
                    "drop_when_publishable_meaning_is_not_supported": True,
                },
                "supporting_raw_post_excerpts": _build_evidence_excerpts(deterministic_offer, raw_post_map),
                "allowed_category_labels": sorted(PRODUCT_CATEGORY_DISPLAY_SET),
            }
        )
        candidates.append(
            Candidate(
                stage="llm_product_row_shape",
                entity_type="offer",
                entity_id=_as_text(deterministic_offer.get("offer_key")),
                entity_ref=_as_text(deterministic_offer.get("offer_key")),
                prompt_version=PROMPT_VERSIONS["llm_product_row_shape"],
                schema_name=_safe_schema_name("tgss_product_row", _as_text(deterministic_offer.get("offer_key"))),
                schema=PRODUCT_ROW_SHAPE_SCHEMA,
                threshold=0.75,
                input_payload=input_payload,
                source_raw_post_ids=_uniq_str_list(deterministic_offer.get("evidence_raw_post_ids")),
                estimated_next_cost_usd=_estimate_next_call_cost_usd(input_payload),
            )
        )
    candidates.sort(key=lambda candidate: (candidate.entity_id, candidate.schema_name))
    return candidates


def _build_service_relevance_candidates(
    *,
    providers_by_key: dict[str, dict[str, Any]],
    offers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for offer in offers_by_key.values():
        if _as_text(offer.get("offer_state")) in {"rejected", "suppressed"}:
            continue
        if not _offer_has_llm_review_basis(offer, raw_post_map):
            continue
        provider = providers_by_key.get(_as_text(offer.get("provider_key")), {})
        category_primary = _as_text(offer.get("category_primary")).strip().lower()
        text = _offer_signal_text(offer)
        negative_hits = sorted(token for token in NON_SERVICE_HINTS if token in text.lower())
        strong_accept = bool(
            category_primary
            and category_primary not in GENERIC_CATEGORY_CODES
            and (bool(_uniq_str_list(offer.get("service_tags"))) or _offer_has_contacts(offer) or _as_text(offer.get("price_text_best")))
        )
        if strong_accept and not negative_hits:
            continue
        has_structured_signal = bool(
            category_primary
            or _uniq_str_list(offer.get("service_tags"))
            or _offer_has_contacts(offer)
            or _as_text(offer.get("price_text_best"))
            or _uniq_str_list(offer.get("city_codes"))
        )
        if has_structured_signal and len(text) >= 48 and not negative_hits:
            continue
        input_payload = _compact_prompt_payload({
            "stage": "service_relevance",
            "canonical_offer": _build_offer_snapshot(offer),
            "provider_context": _build_provider_snapshot(provider),
            "deterministic_hints": {
                "negative_keywords": negative_hits,
                "has_contacts": _offer_has_contacts(offer),
                "has_price": bool(_as_text(offer.get("price_text_best"))),
                "has_city_codes": bool(_uniq_str_list(offer.get("city_codes"))),
                "dedupe_confidence": _as_text(offer.get("dedupe_confidence")),
            },
            "supporting_raw_post_excerpts": _build_evidence_excerpts(offer, raw_post_map),
        })
        candidates.append(
            Candidate(
                stage="llm_service_relevance",
                entity_type="offer",
                entity_id=_as_text(offer.get("offer_key")),
                entity_ref=_as_text(offer.get("offer_key")),
                prompt_version=PROMPT_VERSIONS["llm_service_relevance"],
                schema_name=_safe_schema_name("tgss_service_relevance", _as_text(offer.get("offer_key"))),
                schema=SERVICE_RELEVANCE_SCHEMA,
                threshold=0.85,
                input_payload=input_payload,
                source_raw_post_ids=_uniq_str_list(offer.get("evidence_raw_post_ids")),
                estimated_next_cost_usd=_estimate_next_call_cost_usd(input_payload),
            )
        )
    return candidates


def _build_serbia_relevance_candidates(
    *,
    providers_by_key: dict[str, dict[str, Any]],
    offers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for offer in offers_by_key.values():
        if _as_text(offer.get("offer_state")) in {"rejected", "suppressed"}:
            continue
        provider = providers_by_key.get(_as_text(offer.get("provider_key")), {})
        text = " ".join(
            [
                _offer_signal_text(offer).lower(),
                " ".join(excerpt["excerpt"].lower() for excerpt in _build_evidence_excerpts(offer, raw_post_map)),
            ]
        )
        city_codes = {city.lower() for city in _uniq_str_list(offer.get("city_codes"))}
        serbia_hits = sorted(keyword for keyword in SERBIA_KEYWORDS if keyword in text)
        foreign_hits = sorted(keyword for keyword in FOREIGN_GEOGRAPHY_HINTS if keyword in text)
        if city_codes.intersection(SERBIA_CITY_CODES) or serbia_hits:
            continue
        input_payload = _compact_prompt_payload({
            "stage": "serbia_relevance",
            "canonical_offer": _build_offer_snapshot(offer),
            "provider_context": _build_provider_snapshot(provider),
            "deterministic_hints": {
                "city_codes": sorted(city_codes),
                "serbia_keyword_hits": serbia_hits,
                "foreign_keyword_hits": foreign_hits,
            },
            "supporting_raw_post_excerpts": _build_evidence_excerpts(offer, raw_post_map),
        })
        candidates.append(
            Candidate(
                stage="llm_serbia_relevance",
                entity_type="offer",
                entity_id=_as_text(offer.get("offer_key")),
                entity_ref=_as_text(offer.get("offer_key")),
                prompt_version=PROMPT_VERSIONS["llm_serbia_relevance"],
                schema_name=_safe_schema_name("tgss_serbia_relevance", _as_text(offer.get("offer_key"))),
                schema=SERBIA_RELEVANCE_SCHEMA,
                threshold=0.85,
                input_payload=input_payload,
                source_raw_post_ids=_uniq_str_list(offer.get("evidence_raw_post_ids")),
                estimated_next_cost_usd=_estimate_next_call_cost_usd(input_payload),
            )
        )
    return candidates


def _build_category_offer_candidates(
    *,
    providers_by_key: dict[str, dict[str, Any]],
    offers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for offer in offers_by_key.values():
        if _as_text(offer.get("offer_state")) in {"rejected", "suppressed"}:
            continue
        if not _offer_has_minimum_text_signal(offer, raw_post_map):
            continue
        provider = providers_by_key.get(_as_text(offer.get("provider_key")), {})
        category_primary = _as_text(offer.get("category_primary")).strip().lower()
        weak_title = len(normalize_text(_as_text(offer.get("title_best")))) < 24
        weak_tags = len(_uniq_str_list(offer.get("service_tags"))) < 2
        missing_summary = not _as_text(offer.get("offer_summary")) and len(normalize_text(_as_text(offer.get("description_best")))) > 80
        if not (not category_primary or category_primary in GENERIC_CATEGORY_CODES or weak_title or weak_tags or missing_summary):
            continue
        input_payload = _compact_prompt_payload({
            "stage": "category_refine_offer",
            "canonical_offer": _build_offer_snapshot(offer),
            "provider_context": _build_provider_snapshot(provider),
            "deterministic_hints": {
                "weak_title": weak_title,
                "weak_tags": weak_tags,
                "missing_summary": missing_summary,
            },
            "supporting_raw_post_excerpts": _build_evidence_excerpts(offer, raw_post_map),
        })
        candidates.append(
            Candidate(
                stage="llm_category_refine",
                entity_type="offer",
                entity_id=_as_text(offer.get("offer_key")),
                entity_ref=_as_text(offer.get("offer_key")),
                prompt_version=PROMPT_VERSIONS["llm_category_refine_offer"],
                schema_name=_safe_schema_name("tgss_category_offer", _as_text(offer.get("offer_key"))),
                schema=CATEGORY_REFINE_OFFER_SCHEMA,
                threshold=0.75,
                input_payload=input_payload,
                source_raw_post_ids=_uniq_str_list(offer.get("evidence_raw_post_ids")),
                estimated_next_cost_usd=_estimate_next_call_cost_usd(input_payload),
            )
        )
    return candidates


def _build_category_provider_candidates(
    *,
    providers_by_key: dict[str, dict[str, Any]],
    offers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[Candidate]:
    offers_by_provider: dict[str, list[dict[str, Any]]] = {}
    for offer in offers_by_key.values():
        offers_by_provider.setdefault(_as_text(offer.get("provider_key")), []).append(offer)

    candidates: list[Candidate] = []
    for provider in providers_by_key.values():
        if _as_text(provider.get("provider_state")) in {"rejected", "suppressed"}:
            continue
        display_name = normalize_text(_as_text(provider.get("display_name_best"))).lower()
        display_tokens = _tokenize(display_name)
        generic_display = not display_name or display_tokens.issubset(GENERIC_PROVIDER_TOKENS) or len(display_tokens) < 2
        if not (
            generic_display
            or _as_text(provider.get("identity_strength")) == "provisional"
            or _as_text(provider.get("dedupe_confidence")) == "low"
        ):
            continue
        provider_offers = offers_by_provider.get(_as_text(provider.get("provider_key")), [])
        input_payload = _compact_prompt_payload({
            "stage": "category_refine_provider",
            "canonical_provider": _build_provider_snapshot(provider),
            "offer_examples": [_build_offer_snapshot(offer) for offer in provider_offers[:3]],
            "deterministic_hints": {
                "generic_display_name": generic_display,
                "identity_strength": _as_text(provider.get("identity_strength")),
                "dedupe_confidence": _as_text(provider.get("dedupe_confidence")),
            },
            "supporting_raw_post_excerpts": _build_evidence_excerpts(provider, raw_post_map),
        })
        candidates.append(
            Candidate(
                stage="llm_category_refine",
                entity_type="provider",
                entity_id=_as_text(provider.get("provider_key")),
                entity_ref=_as_text(provider.get("provider_key")),
                prompt_version=PROMPT_VERSIONS["llm_category_refine_provider"],
                schema_name=_safe_schema_name("tgss_category_provider", _as_text(provider.get("provider_key"))),
                schema=CATEGORY_REFINE_PROVIDER_SCHEMA,
                threshold=0.75,
                input_payload=input_payload,
                source_raw_post_ids=_uniq_str_list(provider.get("evidence_raw_post_ids")),
                estimated_next_cost_usd=_estimate_next_call_cost_usd(input_payload),
            )
        )
    return candidates


def _build_provider_merge_review_candidates(
    *,
    providers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[Candidate]:
    providers = list(providers_by_key.values())
    scored_pairs: list[tuple[float, Candidate]] = []
    for left_index in range(len(providers)):
        left = providers[left_index]
        left_key = _as_text(left.get("provider_key"))
        left_tokens = _tokenize(_provider_signal_text(left))
        for right_index in range(left_index + 1, len(providers)):
            right = providers[right_index]
            right_key = _as_text(right.get("provider_key"))
            if not left_key or not right_key:
                continue
            if _as_text(left.get("identity_strength")) == "strong" and _as_text(right.get("identity_strength")) == "strong":
                continue
            right_tokens = _tokenize(_provider_signal_text(right))
            similarity = _jaccard(left_tokens, right_tokens)
            city_overlap = sorted(set(_uniq_str_list(left.get("city_codes"))).intersection(_uniq_str_list(right.get("city_codes"))))
            category_overlap = sorted(
                set(_uniq_str_list(left.get("service_category_hints"))).intersection(
                    _uniq_str_list(right.get("service_category_hints"))
                )
            )
            if similarity < 0.70 or (not city_overlap and not category_overlap):
                continue
            entity_id = f"{left_key}|{right_key}"
            input_payload = _compact_prompt_payload({
                "stage": "provider_merge_review",
                "provider_a": _build_provider_snapshot(left),
                "provider_b": _build_provider_snapshot(right),
                "deterministic_hints": {
                    "signal_similarity_jaccard": round(similarity, 3),
                    "city_overlap": city_overlap,
                    "service_category_overlap": category_overlap,
                },
                "supporting_raw_post_excerpts": _build_pair_evidence(left, right, raw_post_map),
            })
            scored_pairs.append(
                (
                    similarity,
                    Candidate(
                        stage="llm_provider_merge_review",
                        entity_type="provider",
                        entity_id=entity_id,
                        entity_ref=entity_id,
                        prompt_version=PROMPT_VERSIONS["llm_provider_merge_review"],
                        schema_name=_safe_schema_name("tgss_provider_merge", entity_id),
                        schema=PROVIDER_MERGE_REVIEW_SCHEMA,
                        threshold=0.85,
                        input_payload=input_payload,
                        source_raw_post_ids=_uniq_str_list(left.get("evidence_raw_post_ids"))
                        + _uniq_str_list(right.get("evidence_raw_post_ids")),
                        estimated_next_cost_usd=_estimate_next_call_cost_usd(input_payload),
                    ),
                )
            )
    scored_pairs.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in scored_pairs[:10]]


def _build_offer_dedupe_review_candidates(
    *,
    offers_by_key: dict[str, dict[str, Any]],
    raw_post_map: dict[str, dict[str, Any]],
) -> list[Candidate]:
    offers_by_provider: dict[str, list[dict[str, Any]]] = {}
    for offer in offers_by_key.values():
        provider_key = _as_text(offer.get("provider_key"))
        if provider_key:
            offers_by_provider.setdefault(provider_key, []).append(offer)

    scored_pairs: list[tuple[float, Candidate]] = []
    for provider_offers in offers_by_provider.values():
        for left_index in range(len(provider_offers)):
            left = provider_offers[left_index]
            if _as_text(left.get("offer_state")) in {"rejected", "suppressed"}:
                continue
            left_key = _as_text(left.get("offer_key"))
            left_tokens = _tokenize(_offer_signal_text(left))
            for right_index in range(left_index + 1, len(provider_offers)):
                right = provider_offers[right_index]
                if _as_text(right.get("offer_state")) in {"rejected", "suppressed"}:
                    continue
                right_key = _as_text(right.get("offer_key"))
                if _as_text(left.get("service_signature_key")) == _as_text(right.get("service_signature_key")):
                    continue
                right_tokens = _tokenize(_offer_signal_text(right))
                similarity = _jaccard(left_tokens, right_tokens)
                category_match = _as_text(left.get("category_primary")) == _as_text(right.get("category_primary"))
                if similarity < 0.75 or (not category_match and similarity < 0.82):
                    continue
                entity_id = f"{left_key}|{right_key}"
                input_payload = _compact_prompt_payload({
                    "stage": "offer_dedupe_review",
                    "offer_a": _build_offer_snapshot(left),
                    "offer_b": _build_offer_snapshot(right),
                    "deterministic_hints": {
                        "signal_similarity_jaccard": round(similarity, 3),
                        "same_category_primary": category_match,
                    },
                    "supporting_raw_post_excerpts": _build_pair_evidence(left, right, raw_post_map),
                })
                scored_pairs.append(
                    (
                        similarity,
                        Candidate(
                            stage="llm_offer_dedupe_review",
                            entity_type="offer",
                            entity_id=entity_id,
                            entity_ref=entity_id,
                            prompt_version=PROMPT_VERSIONS["llm_offer_dedupe_review"],
                            schema_name=_safe_schema_name("tgss_offer_dedupe", entity_id),
                            schema=OFFER_DEDUPE_REVIEW_SCHEMA,
                            threshold=0.85,
                            input_payload=input_payload,
                            source_raw_post_ids=_uniq_str_list(left.get("evidence_raw_post_ids"))
                            + _uniq_str_list(right.get("evidence_raw_post_ids")),
                            estimated_next_cost_usd=_estimate_next_call_cost_usd(input_payload),
                        ),
                    )
                )
    scored_pairs.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in scored_pairs[:15]]


def _build_audit_row(
    *,
    run_id: str,
    candidate: Candidate,
    processor_type: str,
    status: str,
    decision_code: str,
    attempt_number: int,
    input_fingerprint: str,
    output_patch_json: dict[str, Any],
    reason_text: str,
    source_raw_post_ids: list[str],
    model_name: str,
    prompt_version: str,
    confidence: float | None = None,
    latency_ms: int | None = None,
    usage: dict[str, int] | None = None,
    response_excerpt: str = "",
    request_id: str = "",
    review_required: bool = False,
    upstream_audit_row_id: str = "",
) -> dict[str, Any]:
    tokens_input = int((usage or {}).get("input_tokens") or 0)
    tokens_output = int((usage or {}).get("output_tokens") or 0)
    cost_estimate_usd = _compute_cost_estimate(usage or {})
    audit_row_id = f"audit:{run_id}:{candidate.stage}:{_compact_hash([candidate.entity_id, attempt_number, input_fingerprint])[:16]}"
    excerpt_value = _prepend_request_id_evidence(response_excerpt, request_id) if status == "error" else response_excerpt
    return {
        "audit_row_id": audit_row_id,
        "run_id": run_id,
        "entity_type": candidate.entity_type,
        "entity_id": candidate.entity_id,
        "stage": candidate.stage,
        "processor_type": processor_type,
        "processor_version": PROCESSOR_VERSION,
        "status": status,
        "decision_code": decision_code,
        "created_at_utc": os.environ.get("TGSA_FIXED_NOW_UTC") or _iso_now_utc(),
        "input_fingerprint": input_fingerprint,
        "output_patch_json": compact_json(output_patch_json),
        "reason_text": reason_text[:240],
        "source_raw_post_ids": source_raw_post_ids[:],
        "attempt_number": attempt_number,
        "review_required": review_required,
        "model_name": model_name,
        "prompt_version": prompt_version,
        "confidence": None if confidence is None else round(confidence, 4),
        "latency_ms": latency_ms if latency_ms is not None else None,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "cost_estimate_usd": cost_estimate_usd,
        "response_excerpt": _truncate_excerpt(excerpt_value, 240),
        "upstream_audit_row_id": upstream_audit_row_id,
    }


def _prepend_request_id_evidence(text: str, request_id: str) -> str:
    normalized_request_id = _as_text(request_id).strip()
    if not normalized_request_id:
        return text
    if normalized_request_id in text:
        return text
    if text:
        return f"request_id={normalized_request_id}\n{text}"
    return f"request_id={normalized_request_id}"


def _iso_now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _budget_would_hard_stop(
    budget: dict[str, Any],
    candidate: Candidate,
    *,
    protect_product_row_coverage: bool = False,
) -> bool:
    if protect_product_row_coverage and candidate.stage == "llm_product_row_shape":
        return False
    return bool(
        budget["calls_attempted"] >= HARD_STOP_CALLS
        or budget["cost_estimate_usd"] + candidate.estimated_next_cost_usd > HARD_STOP_COST_USD
    )


def _response_error_is_max_output(exc: ResponseTransportError) -> bool:
    evidence = normalize_text(
        " ".join(
            part
            for part in (
                str(exc),
                getattr(exc, "response_body", ""),
            )
            if part
        )
    ).lower()
    return "max_output_tokens" in evidence


def _response_error_is_quota_or_billing(exc: ResponseTransportError) -> bool:
    error_code = normalize_text(_as_text(getattr(exc, "error_code", ""))).lower()
    error_type = normalize_text(_as_text(getattr(exc, "error_type", ""))).lower()
    if error_code in QUOTA_OR_BILLING_ERROR_CODES or error_type in QUOTA_OR_BILLING_ERROR_CODES:
        return True

    evidence = normalize_text(
        " ".join(
            part
            for part in (
                str(exc),
                getattr(exc, "response_body", ""),
                error_code,
                error_type,
            )
            if part
        )
    ).lower()
    if any(phrase in evidence for phrase in QUOTA_OR_BILLING_MESSAGE_PHRASES):
        return True
    if "quota" in evidence and any(term in evidence for term in ("billing", "plan", "credit")):
        return True
    return False


def _build_product_row_quota_blocker(
    *,
    candidate: Candidate,
    exc: ResponseTransportError,
    attempt_number: int,
) -> dict[str, Any]:
    evidence = {
        "status": "blocked",
        "reason": LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
        "stage": candidate.stage,
        "entity_type": candidate.entity_type,
        "entity_id": candidate.entity_id,
        "attempt_number": attempt_number,
        "provider": "openai",
        "status_code": getattr(exc, "status_code", None),
        "error_type": _as_text(getattr(exc, "error_type", "")),
        "error_code": _as_text(getattr(exc, "error_code", "")),
        "request_id": _as_text(getattr(exc, "request_id", "")),
        "message": str(exc)[:240],
        "retry_after_quota_restoration": True,
        "safe_retry_contract": PRODUCT_ROW_QUOTA_RETRY_CONTRACT,
    }
    return {key: value for key, value in evidence.items() if value not in ("", None)}


def _category_refine_max_output_cutoff_fallback_allowed(candidate: Candidate, exc: ResponseTransportError) -> bool:
    if candidate.stage != "llm_category_refine":
        return False
    return _response_error_is_max_output(exc)


def _category_refine_cutoff_fallback_reason(candidate: Candidate) -> str:
    target = "provider" if candidate.entity_type == "provider" else "offer"
    return f"Category-refine {target} hit max_output_tokens; deterministic fields were preserved."


def _near_threshold_product_row_publish_is_safe(
    *,
    offer: dict[str, Any],
    decision_code: str,
    patch: dict[str, str],
    reason_text: str,
) -> tuple[bool, list[str]]:
    if decision_code != "publish":
        return False, ["near_threshold_not_publish"]

    candidate_offer = copy.deepcopy(offer)
    _, changed, apply_warnings = _apply_product_row_patch(
        offer=candidate_offer,
        decision_code=decision_code,
        patch=patch,
        reason_text=reason_text,
    )
    if apply_warnings:
        return False, apply_warnings
    if not changed and _as_text(candidate_offer.get("product_row_publish_decision")) != "publish":
        return False, ["near_threshold_no_publish_patch"]

    publishable_row = _build_publishable_row(candidate_offer)
    if _as_text(publishable_row.get("publish_decision")) != "publish":
        issue = _as_text(publishable_row.get("audit_reason")) or "near_threshold_not_publishable"
        return False, [issue]
    return True, []


def _product_row_patch_has_structural_publish_signal(patch: dict[str, str]) -> tuple[bool, list[str]]:
    service_name = normalize_text(_as_text(patch.get("product_row_service_name")))
    details = normalize_text(_as_text(patch.get("product_row_details")))
    category = normalize_text(_as_text(patch.get("product_row_category")))
    contact = normalize_text(_as_text(patch.get("product_row_contact")))
    warnings: list[str] = []

    if not service_name:
        warnings.append("structured_low_confidence_missing_service_name")
    elif (
        service_name.lower() in PRODUCT_GENERIC_SERVICE_NAMES
        or _looks_like_non_service_visible_label(service_name)
        or _service_label_looks_sentence_like(service_name)
        or _label_looks_like_slogan_or_promo(service_name)
    ):
        warnings.append("structured_low_confidence_weak_service_name")

    service_tokens = _tokenize(service_name)
    detail_tokens = _tokenize(details)
    if len(service_tokens) < 2:
        warnings.append("structured_low_confidence_short_service_name")
    if len(detail_tokens) < MIN_TEXT_SIGNAL_TOKENS:
        warnings.append("structured_low_confidence_weak_details")
    if len(_tokenize(" ".join(part for part in (service_name, details) if part))) < MIN_TEXT_SIGNAL_TOKENS + 1:
        warnings.append("structured_low_confidence_weak_text_signal")
    if len(normalize_text(" ".join(part for part in (service_name, details) if part))) < MIN_TEXT_SIGNAL_CHARS:
        warnings.append("structured_low_confidence_short_text_signal")
    if not category or category not in PRODUCT_CATEGORY_DISPLAY_SET:
        warnings.append("structured_low_confidence_missing_category")
    if not contact:
        warnings.append("structured_low_confidence_missing_contact")

    return not warnings, warnings


def _apply_decision(
    *,
    candidate: Candidate,
    decision: dict[str, Any],
    providers_by_key: dict[str, dict[str, Any]],
    offers_by_key: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], bool, list[str]]:
    warnings: list[str] = []
    confidence = float(decision["confidence"])

    if candidate.stage == "llm_service_relevance":
        if confidence < candidate.threshold:
            warnings.append("low_confidence")
            return {}, False, warnings
        offer = offers_by_key[candidate.entity_ref]
        patch, sanitize_warnings = _sanitize_offer_patch(candidate.stage, decision["patch"])
        warnings.extend(sanitize_warnings)
        _, changed = _apply_offer_patch(offer, patch)
        return changed, bool(changed), warnings

    if candidate.stage == "llm_serbia_relevance":
        if confidence < candidate.threshold:
            warnings.append("low_confidence")
            return {}, False, warnings
        offer = offers_by_key[candidate.entity_ref]
        patch, sanitize_warnings = _sanitize_offer_patch(candidate.stage, decision["patch"])
        warnings.extend(sanitize_warnings)
        _, changed = _apply_offer_patch(offer, patch)
        return changed, bool(changed), warnings

    if candidate.stage == "llm_product_row_shape":
        offer = offers_by_key[candidate.entity_ref]
        patch, sanitize_warnings = _sanitize_product_row_patch(candidate, decision["patch"])
        warnings.extend(sanitize_warnings)
        blocking_sanitize_warnings = [
            warning for warning in sanitize_warnings
            if not warning.startswith("field_normalized:")
        ]
        if confidence < candidate.threshold:
            warnings.append("low_confidence")
            if not blocking_sanitize_warnings:
                publish_is_safe, safety_warnings = _near_threshold_product_row_publish_is_safe(
                    offer=offer,
                    decision_code=decision["decision_code"],
                    patch=patch,
                    reason_text=decision["reason_text"],
                )
                if publish_is_safe and confidence >= PRODUCT_ROW_LOW_CONFIDENCE_RECOVERY_FLOOR:
                    _, changed, apply_warnings = _apply_product_row_patch(
                        offer=offer,
                        decision_code=decision["decision_code"],
                        patch=patch,
                        reason_text=decision["reason_text"],
                    )
                    warnings.extend(apply_warnings)
                    warnings.append("near_threshold_safe_publish")
                    return changed, True, warnings
                if publish_is_safe and confidence >= PRODUCT_ROW_STRUCTURED_LOW_CONFIDENCE_RECOVERY_FLOOR:
                    structurally_concrete, structural_warnings = _product_row_patch_has_structural_publish_signal(patch)
                    if structurally_concrete:
                        _, changed, apply_warnings = _apply_product_row_patch(
                            offer=offer,
                            decision_code=decision["decision_code"],
                            patch=patch,
                            reason_text=decision["reason_text"],
                        )
                        warnings.extend(apply_warnings)
                        warnings.append("structured_low_confidence_safe_publish")
                        return changed, True, warnings
                    warnings.extend(structural_warnings)
                elif confidence >= PRODUCT_ROW_STRUCTURED_LOW_CONFIDENCE_RECOVERY_FLOOR:
                    warnings.extend(safety_warnings)
            return {}, False, warnings
        _, changed, apply_warnings = _apply_product_row_patch(
            offer=offer,
            decision_code=decision["decision_code"],
            patch=patch,
            reason_text=decision["reason_text"],
        )
        warnings.extend(apply_warnings)
        return changed, bool(changed), warnings

    if candidate.stage == "llm_category_refine" and candidate.entity_type == "offer":
        if confidence < candidate.threshold:
            warnings.append("low_confidence")
            return {}, False, warnings
        offer = offers_by_key[candidate.entity_ref]
        patch, sanitize_warnings = _sanitize_offer_patch(candidate.stage, decision["patch"])
        warnings.extend(sanitize_warnings)
        _, changed = _apply_offer_patch(offer, patch)
        return changed, bool(changed), warnings

    if candidate.stage == "llm_category_refine" and candidate.entity_type == "provider":
        if confidence < candidate.threshold:
            warnings.append("low_confidence")
            return {}, False, warnings
        provider = providers_by_key[candidate.entity_ref]
        patch, sanitize_warnings = _sanitize_provider_patch(decision["patch"])
        warnings.extend(sanitize_warnings)
        _, changed = _apply_provider_patch(provider, patch)
        return changed, bool(changed), warnings

    if candidate.stage == "llm_provider_merge_review":
        if confidence < candidate.threshold:
            warnings.append("low_confidence")
            return {}, False, warnings
        left_key, right_key = candidate.entity_ref.split("|", 1)
        if decision["decision_code"] != "same_provider":
            return {}, False, warnings
        group_id = _build_override_group("provider_merge_override_group", [left_key, right_key])
        changed: dict[str, Any] = {}
        for provider_key in (left_key, right_key):
            provider = providers_by_key[provider_key]
            if provider.get("provider_merge_override_group") == group_id:
                continue
            provider["provider_merge_override_group"] = group_id
            changed[provider_key] = {"provider_merge_override_group": group_id}
        return changed, bool(changed), warnings

    if candidate.stage == "llm_offer_dedupe_review":
        if confidence < candidate.threshold:
            warnings.append("low_confidence")
            return {}, False, warnings
        left_key, right_key = candidate.entity_ref.split("|", 1)
        if decision["decision_code"] != "same_offer":
            return {}, False, warnings
        group_id = _build_override_group("offer_merge_override_group", [left_key, right_key])
        changed = {}
        for offer_key in (left_key, right_key):
            offer = offers_by_key[offer_key]
            if offer.get("offer_merge_override_group") == group_id:
                continue
            offer["offer_merge_override_group"] = group_id
            changed[offer_key] = {"offer_merge_override_group": group_id}
        return changed, bool(changed), warnings

    return {}, False, warnings


def _stage_error_reason(base_reason: str, warnings: list[str]) -> str:
    if not warnings:
        return base_reason
    return f"{base_reason}; {', '.join(warnings)}"


def _hard_drop_product_row_candidate(
    *,
    candidate: Candidate,
    offers_by_key: dict[str, dict[str, Any]],
    stage_breakdown: dict[str, dict[str, Any]],
    reason_text: str,
) -> dict[str, Any]:
    if candidate.stage != "llm_product_row_shape":
        return {}
    offer = offers_by_key.get(candidate.entity_ref)
    if not isinstance(offer, dict):
        stage_breakdown[candidate.stage]["coverage_failures"] += 1
        return {}

    patch = {
        "product_row_publish_decision": "drop",
        "product_row_service_name": "",
        "product_row_details": "",
        "product_row_category": "",
        "product_row_contact": "",
        "product_row_audit_reason": reason_text[:240],
    }
    _, changed = _apply_offer_patch(offer, patch)
    stage_breakdown[candidate.stage]["coverage_failures"] += 1
    stage_breakdown[candidate.stage]["coverage_hard_drops"] += 1
    return changed or patch


def _build_product_row_coverage_summary(
    stage_breakdown: dict[str, dict[str, Any]],
    *,
    planned_candidate_total: int | None = None,
    incomplete_reason: str = "",
) -> dict[str, Any]:
    breakdown = stage_breakdown.get("llm_product_row_shape", {})
    candidate_total = int(breakdown.get("eligible_entities") or 0)
    if planned_candidate_total is not None:
        candidate_total = int(planned_candidate_total)
    successful_decisions = int(breakdown.get("accepted_patches") or 0)
    hard_drops = int(breakdown.get("coverage_hard_drops") or 0)
    coverage_complete = candidate_total == successful_decisions + hard_drops and not incomplete_reason
    summary = {
        "candidate_total": candidate_total,
        "attempts": int(breakdown.get("vendor_attempts") or 0),
        "successful_decisions": successful_decisions,
        "failures": int(breakdown.get("coverage_failures") or 0),
        "skips": int(breakdown.get("skipped") or 0),
        "max_output_retries": int(breakdown.get("max_output_retries") or 0),
        "quota_blockers": int(breakdown.get("quota_blockers") or 0),
        "hard_drops": hard_drops,
        "safe_non_visible_drops": int(breakdown.get("safe_non_visible_drops") or 0),
        "recovered_low_confidence_publishes": int(breakdown.get("recovered_low_confidence_publishes") or 0),
        "coverage_complete": coverage_complete,
        "fallback_publication_blocked": hard_drops > 0 or candidate_total == successful_decisions,
    }
    if incomplete_reason:
        summary["fallback_publication_blocked"] = True
        summary["incomplete_reason"] = incomplete_reason
    return summary


def _execute_candidate(
    *,
    run_id: str,
    candidate: Candidate,
    transport: _LiveResponsesTransport | _MockResponsesTransport | None,
    model_name: str,
    budget: dict[str, Any],
    providers_by_key: dict[str, dict[str, Any]],
    offers_by_key: dict[str, dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    accepted_patches: list[dict[str, Any]],
    audit_only_patches: list[dict[str, Any]],
    stage_breakdown: dict[str, dict[str, Any]],
    missing_credentials: bool,
    timeout_guard: Callable[[], None] | None = None,
    safe_product_row_rejection_drop: bool = False,
) -> dict[str, Any] | None:
    stage_breakdown[candidate.stage]["eligible_entities"] += 1
    if timeout_guard is not None:
        timeout_guard()
    input_fingerprint = _compact_hash(candidate.input_payload)

    if _budget_would_hard_stop(budget, candidate, protect_product_row_coverage=True):
        budget["calls_skipped"] += 1
        budget["last_outcome"] = "budget_exhausted"
        _ensure_budget_flags(budget)
        stage_breakdown[candidate.stage]["skipped"] += 1
        coverage_drop_patch = _hard_drop_product_row_candidate(
            candidate=candidate,
            offers_by_key=offers_by_key,
            stage_breakdown=stage_breakdown,
            reason_text="Product-row LLM budget guard blocked processing; deterministic fallback publication was blocked.",
        )
        audit_rows.append(
            _build_audit_row(
                run_id=run_id,
                candidate=candidate,
                processor_type="deterministic",
                status="skipped",
                decision_code="budget_exhausted",
                attempt_number=0,
                input_fingerprint=input_fingerprint,
                output_patch_json={},
                reason_text="Budget guard skipped this candidate before the next call.",
                source_raw_post_ids=candidate.source_raw_post_ids,
                model_name=model_name,
                prompt_version=candidate.prompt_version,
                review_required=True,
            )
        )
        audit_only_patches.append(
            {
                "stage": candidate.stage,
                "entity_type": candidate.entity_type,
                "entity_id": candidate.entity_id,
                "status": "skipped",
                "decision_code": "budget_exhausted",
                "patch": coverage_drop_patch,
            }
        )
        return

    if missing_credentials or transport is None:
        budget["calls_skipped"] += 1
        budget["last_outcome"] = "missing_credentials"
        _ensure_budget_flags(budget)
        stage_breakdown[candidate.stage]["skipped"] += 1
        coverage_drop_patch = _hard_drop_product_row_candidate(
            candidate=candidate,
            offers_by_key=offers_by_key,
            stage_breakdown=stage_breakdown,
            reason_text="Product-row LLM credentials were unavailable; deterministic fallback publication was blocked.",
        )
        audit_rows.append(
            _build_audit_row(
                run_id=run_id,
                candidate=candidate,
                processor_type="deterministic",
                status="skipped",
                decision_code="missing_credentials",
                attempt_number=0,
                input_fingerprint=input_fingerprint,
                output_patch_json={},
                reason_text="LLM credentials were not available for this eligible candidate.",
                source_raw_post_ids=candidate.source_raw_post_ids,
                model_name=model_name,
                prompt_version=candidate.prompt_version,
                review_required=True,
            )
        )
        audit_only_patches.append(
            {
                "stage": candidate.stage,
                "entity_type": candidate.entity_type,
                "entity_id": candidate.entity_id,
                "status": "skipped",
                "decision_code": "missing_credentials",
                "patch": coverage_drop_patch,
            }
        )
        return

    upstream_audit_row_id = ""
    max_output_staircase = _response_max_output_token_staircase_for_schema(candidate.schema_name)
    max_output_index = 0
    retryable_transport_retries = 0
    attempt_number = 0
    while True:
        if timeout_guard is not None:
            timeout_guard()
        attempt_number += 1
        max_output_tokens = max_output_staircase[max_output_index]
        messages = _build_messages(
            "llm_category_refine_provider" if candidate.stage == "llm_category_refine" and candidate.entity_type == "provider" else
            "llm_category_refine_offer" if candidate.stage == "llm_category_refine" else
            candidate.stage,
            candidate.input_payload,
        )
        stage_breakdown[candidate.stage]["vendor_attempts"] += 1
        budget["calls_attempted"] += 1
        try:
            transport_response = transport.create(
                model=model_name,
                input_messages=messages,
                schema_name=candidate.schema_name,
                schema=candidate.schema,
                max_output_tokens=max_output_tokens,
            )
            decision_raw, usage, response_excerpt = _parse_response_decision(
                transport_response.payload,
                request_id=transport_response.request_id,
            )
            _apply_usage_to_budget(budget, usage)
            budget["last_outcome"] = "call_executed"
            _ensure_budget_flags(budget)

            decision = _validate_required_decision(decision_raw)
            changed_patch, applied, warnings = _apply_decision(
                candidate=candidate,
                decision=decision,
                providers_by_key=providers_by_key,
                offers_by_key=offers_by_key,
            )
            safe_drop_from_rejection = False
            decision_code = decision["decision_code"]
            if (
                not applied
                and safe_product_row_rejection_drop
                and candidate.stage == "llm_product_row_shape"
                and candidate.entity_ref in offers_by_key
            ):
                safe_drop_from_rejection = True
                decision_code = "drop"
                warnings.append("safe_non_visible_drop_after_unusable_product_row_output")
                safe_drop_reason = _stage_error_reason(
                    "Product-row LLM output could not be safely published; safe non-visible drop applied.",
                    warnings,
                )
                safe_drop_patch = {
                    "product_row_publish_decision": "drop",
                    "product_row_service_name": "",
                    "product_row_details": "",
                    "product_row_category": "",
                    "product_row_contact": "",
                    "product_row_audit_reason": safe_drop_reason[:240],
                }
                _, safe_drop_changed = _apply_offer_patch(offers_by_key[candidate.entity_ref], safe_drop_patch)
                changed_patch = safe_drop_changed or safe_drop_patch
                applied = True
            status = "accepted" if applied else "rejected"
            reason_text = _stage_error_reason(decision["reason_text"], warnings)
            review_required = safe_drop_from_rejection or not applied
            coverage_drop_patch: dict[str, Any] = {}
            if candidate.stage == "llm_product_row_shape" and not applied:
                coverage_drop_patch = _hard_drop_product_row_candidate(
                    candidate=candidate,
                    offers_by_key=offers_by_key,
                    stage_breakdown=stage_breakdown,
                    reason_text=(
                        "Product-row LLM decision was not safely applied; "
                        "deterministic fallback publication was blocked."
                    ),
                )
            audit_row = _build_audit_row(
                run_id=run_id,
                candidate=candidate,
                processor_type="llm",
                status=status,
                decision_code=decision_code,
                attempt_number=attempt_number,
                input_fingerprint=input_fingerprint,
                output_patch_json=changed_patch if applied else decision["patch"],
                reason_text=reason_text,
                source_raw_post_ids=candidate.source_raw_post_ids,
                model_name=model_name,
                prompt_version=candidate.prompt_version,
                confidence=decision["confidence"],
                latency_ms=transport_response.latency_ms,
                usage=usage,
                response_excerpt=response_excerpt,
                request_id=transport_response.request_id,
                review_required=review_required,
                upstream_audit_row_id=upstream_audit_row_id,
            )
            audit_rows.append(audit_row)
            upstream_audit_row_id = audit_row["audit_row_id"]
            if applied:
                stage_breakdown[candidate.stage]["accepted_patches"] += 1
                if candidate.stage == "llm_product_row_shape":
                    if decision_code == "drop":
                        stage_breakdown[candidate.stage]["safe_non_visible_drops"] += 1
                    if (
                        "near_threshold_safe_publish" in warnings
                        or "structured_low_confidence_safe_publish" in warnings
                    ):
                        stage_breakdown[candidate.stage]["recovered_low_confidence_publishes"] += 1
                accepted_patches.append(
                    {
                        "stage": candidate.stage,
                        "entity_type": candidate.entity_type,
                        "entity_id": candidate.entity_id,
                        "status": status,
                        "decision_code": decision_code,
                        "patch": changed_patch,
                        "confidence": round(decision["confidence"], 4),
                    }
                )
            else:
                stage_breakdown[candidate.stage]["audit_only_patches"] += 1
                audit_only_patches.append(
                    {
                        "stage": candidate.stage,
                        "entity_type": candidate.entity_type,
                        "entity_id": candidate.entity_id,
                        "status": status,
                        "decision_code": decision_code,
                        "patch": coverage_drop_patch or decision["patch"],
                        "confidence": round(decision["confidence"], 4),
                        "reason_text": reason_text,
                    }
                )
            return
        except ResponseTransportError as exc:
            error_usage = exc.usage if isinstance(getattr(exc, "usage", None), dict) else None
            _apply_usage_to_budget(budget, error_usage)
            budget["last_outcome"] = "call_error"
            _ensure_budget_flags(budget)
            if _category_refine_max_output_cutoff_fallback_allowed(candidate, exc):
                fallback_reason = _category_refine_cutoff_fallback_reason(candidate)
                response_excerpt = _prepend_request_id_evidence(
                    getattr(exc, "response_body", ""),
                    getattr(exc, "request_id", ""),
                )
                audit_rows.append(
                    _build_audit_row(
                        run_id=run_id,
                        candidate=candidate,
                        processor_type="deterministic",
                        status="skipped",
                        decision_code="category_refine_cutoff_fallback_no_change",
                        attempt_number=attempt_number,
                        input_fingerprint=input_fingerprint,
                        output_patch_json={},
                        reason_text=fallback_reason,
                        source_raw_post_ids=candidate.source_raw_post_ids,
                        model_name=model_name,
                        prompt_version=candidate.prompt_version,
                        latency_ms=None,
                        usage=error_usage,
                        response_excerpt=response_excerpt,
                        review_required=True,
                        upstream_audit_row_id=upstream_audit_row_id,
                    )
                )
                stage_breakdown[candidate.stage]["audit_only_patches"] += 1
                audit_only_patches.append(
                    {
                        "stage": candidate.stage,
                        "entity_type": candidate.entity_type,
                        "entity_id": candidate.entity_id,
                        "status": "skipped",
                        "decision_code": "category_refine_cutoff_fallback_no_change",
                        "patch": {},
                        "reason_text": fallback_reason,
                    }
                )
                budget["last_outcome"] = "category_refine_cutoff_fallback"
                _ensure_budget_flags(budget)
                return
            if candidate.stage == "llm_product_row_shape" and _response_error_is_quota_or_billing(exc):
                quota_blocker = _build_product_row_quota_blocker(
                    candidate=candidate,
                    exc=exc,
                    attempt_number=attempt_number,
                )
                budget["last_outcome"] = LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON
                _ensure_budget_flags(budget)
                stage_breakdown[candidate.stage]["quota_blockers"] += 1
                response_excerpt = _prepend_request_id_evidence(
                    getattr(exc, "response_body", ""),
                    getattr(exc, "request_id", ""),
                )
                audit_rows.append(
                    _build_audit_row(
                        run_id=run_id,
                        candidate=candidate,
                        processor_type="llm",
                        status="blocked",
                        decision_code=LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
                        attempt_number=attempt_number,
                        input_fingerprint=input_fingerprint,
                        output_patch_json={},
                        reason_text=str(exc),
                        source_raw_post_ids=candidate.source_raw_post_ids,
                        model_name=model_name,
                        prompt_version=candidate.prompt_version,
                        latency_ms=None,
                        usage=error_usage,
                        response_excerpt=response_excerpt,
                        request_id=getattr(exc, "request_id", ""),
                        review_required=True,
                        upstream_audit_row_id=upstream_audit_row_id,
                    )
                )
                return quota_blocker
            audit_row = _build_audit_row(
                run_id=run_id,
                candidate=candidate,
                processor_type="llm",
                status="error",
                decision_code="call_failed",
                attempt_number=attempt_number,
                input_fingerprint=input_fingerprint,
                output_patch_json={},
                reason_text=str(exc),
                source_raw_post_ids=candidate.source_raw_post_ids,
                model_name=model_name,
                prompt_version=candidate.prompt_version,
                latency_ms=None,
                usage=error_usage,
                response_excerpt=getattr(exc, "response_body", ""),
                request_id=getattr(exc, "request_id", ""),
                review_required=True,
                upstream_audit_row_id=upstream_audit_row_id,
            )
            audit_rows.append(audit_row)
            upstream_audit_row_id = audit_row["audit_row_id"]
            is_product_max_output = candidate.stage == "llm_product_row_shape" and _response_error_is_max_output(exc)
            if is_product_max_output and max_output_index + 1 < len(max_output_staircase):
                stage_breakdown[candidate.stage]["max_output_retries"] += 1
                budget["last_outcome"] = "product_row_max_output_retry"
                _ensure_budget_flags(budget)
                max_output_index += 1
                continue
            if (
                exc.retryable
                and not is_product_max_output
                and retryable_transport_retries < 1
                and not _budget_would_hard_stop(budget, candidate, protect_product_row_coverage=True)
            ):
                retryable_transport_retries += 1
                continue
            stage_breakdown[candidate.stage]["errors"] += 1
            coverage_drop_patch = _hard_drop_product_row_candidate(
                candidate=candidate,
                offers_by_key=offers_by_key,
                stage_breakdown=stage_breakdown,
                reason_text=(
                    "Product-row LLM max_output_tokens ceiling was exhausted; "
                    "deterministic fallback publication was blocked."
                    if is_product_max_output
                    else "Product-row LLM call failed; deterministic fallback publication was blocked."
                ),
            )
            audit_only_patches.append(
                {
                    "stage": candidate.stage,
                    "entity_type": candidate.entity_type,
                    "entity_id": candidate.entity_id,
                    "status": "error",
                    "decision_code": "call_failed",
                    "patch": coverage_drop_patch,
                    "reason_text": str(exc),
                }
            )
            return


def process_post_merge_payload(
    payload: dict[str, Any],
    *,
    mock_response_path: str | None = None,
    pretty: bool = False,
    total_timeout_seconds: float | None = None,
    monotonic: Callable[[], float] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Post-merge LLM payload must be a JSON object.")

    run_id = normalize_text(_as_text(payload.get("run_id")))
    normalized_request = payload.get("normalized_request") if isinstance(payload.get("normalized_request"), dict) else {}
    llm_enabled = bool(normalized_request.get("llm_enabled", False))
    merge_output = payload.get("merge_output") if isinstance(payload.get("merge_output"), dict) else {}
    if not isinstance(merge_output.get("providers"), list) or not isinstance(merge_output.get("offers"), list):
        raise ValueError("Post-merge LLM payload must include merge_output.providers and merge_output.offers arrays.")
    if llm_enabled:
        validate_stage_schemas()
    if total_timeout_seconds is None:
        configured_total_timeout = _configured_total_timeout_seconds()
        total_timeout_seconds = (
            configured_total_timeout
            if configured_total_timeout is not None
            else DEFAULT_LLM_TOTAL_TIMEOUT_SECONDS
        )
    if total_timeout_seconds is not None and total_timeout_seconds < 0:
        raise ValueError("total_timeout_seconds must be non-negative.")
    monotonic_clock = monotonic or time.monotonic

    raw_post_map = _build_raw_post_map(payload.get("raw_posts"))
    canonical_output = _copy_canonical_output(run_id, merge_output)
    deterministic_providers_by_key = {
        _as_text(provider.get("provider_key")): copy.deepcopy(provider)
        for provider in (merge_output.get("providers") if isinstance(merge_output.get("providers"), list) else [])
        if _as_text(provider.get("provider_key"))
    }
    deterministic_offers_by_key = {
        _as_text(offer.get("offer_key")): copy.deepcopy(offer)
        for offer in (merge_output.get("offers") if isinstance(merge_output.get("offers"), list) else [])
        if _as_text(offer.get("offer_key"))
    }
    providers_by_key = {
        _as_text(provider.get("provider_key")): provider
        for provider in canonical_output["providers"]
        if _as_text(provider.get("provider_key"))
    }
    offers_by_key = {
        _as_text(offer.get("offer_key")): offer
        for offer in canonical_output["offers"]
        if _as_text(offer.get("offer_key"))
    }
    _seed_default_product_rows(canonical_output["offers"], deterministic_offers_by_key)

    budget = _empty_budget_state()
    stage_breakdown = _empty_stage_breakdown()
    audit_rows: list[dict[str, Any]] = []
    accepted_patches: list[dict[str, Any]] = []
    audit_only_patches: list[dict[str, Any]] = []
    progress = LlmProgress(
        started_monotonic=monotonic_clock(),
        total_timeout_seconds=total_timeout_seconds if llm_enabled else None,
    )

    model_name = normalize_text(os.environ.get("TGSA_OPENAI_MODEL") or "") or DEFAULT_MODEL
    missing_credentials = False
    helper_mode = "responses_api"
    transport: _LiveResponsesTransport | _MockResponsesTransport | None = None

    if mock_response_path:
        helper_mode = "mock"
        transport = _MockResponsesTransport(
            json.loads(Path(mock_response_path).read_text(encoding="utf-8"))
        )
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if api_key:
            transport = _LiveResponsesTransport(
                api_key=api_key,
                base_url=os.environ.get("OPENAI_BASE_URL", "").strip() or None,
                organization=os.environ.get("OPENAI_ORGANIZATION", "").strip() or None,
                project=os.environ.get("OPENAI_PROJECT", "").strip() or None,
                timeout_seconds=float(os.environ.get("TGSA_OPENAI_TIMEOUT_SECONDS", "60")),
            )
        else:
            missing_credentials = True

    if not llm_enabled:
        _finalize_product_rows(canonical_output["offers"])
        canonical_output["providers_total"] = len(canonical_output["providers"])
        canonical_output["offers_total"] = len(canonical_output["offers"])
        _ensure_budget_flags(budget)
        llm_stage = {
            "status": "skipped",
            "reason": "llm_disabled",
            "processor_version": PROCESSOR_VERSION,
            "helper_mode": helper_mode,
            "model_name": model_name,
            "calls_attempted": 0,
            "calls_skipped": 0,
            "accepted_patches_total": 0,
            "audit_only_patches_total": 0,
            "review_required_count": 0,
            "tokens_input_total": 0,
            "tokens_output_total": 0,
            "cost_estimate_usd": 0.0,
            "budget": budget,
            "stage_breakdown": stage_breakdown,
            "product_row_coverage": _build_product_row_coverage_summary(stage_breakdown),
            "accepted_patches": [],
            "audit_only_patches": [],
        }
        result = {
            "run_id": run_id,
            "workflow_stage": WORKFLOW_STAGE,
            "llm_contract_version": PROCESSOR_VERSION,
            "llm_enabled": False,
            "helper_mode": helper_mode,
            "canonical_output": canonical_output,
            "audit_enrichment_rows": [],
            "llm_stage": llm_stage,
        }
        return json.loads(compact_json(result, pretty=pretty))

    def build_result(
        *,
        llm_status: str | None = None,
        llm_reason: str | None = None,
        progress_snapshot: dict[str, Any] | None = None,
        planned_product_candidate_total: int | None = None,
        product_row_incomplete_reason: str = "",
        product_row_chunking: dict[str, Any] | None = None,
        quota_blocker: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _finalize_product_rows(canonical_output["offers"])
        canonical_output["providers_total"] = len(canonical_output["providers"])
        canonical_output["offers_total"] = len(canonical_output["offers"])
        _ensure_budget_flags(budget)
        product_row_coverage = _build_product_row_coverage_summary(
            stage_breakdown,
            planned_candidate_total=planned_product_candidate_total,
            incomplete_reason=product_row_incomplete_reason
            or ("llm_total_timeout" if progress_snapshot else ""),
        )

        status = llm_status or "success"
        reason = llm_reason or "llm_stage_completed"
        if llm_status is None or llm_reason is None:
            if product_row_coverage["failures"] > 0:
                status = "error"
                reason = "product_row_coverage_failed"
            elif any(stage_breakdown[stage]["errors"] > 0 for stage in stage_breakdown):
                status = "error"
                reason = "llm_call_error"
            elif missing_credentials and any(stage_breakdown[stage]["eligible_entities"] > 0 for stage in stage_breakdown):
                status = "skipped"
                reason = "missing_credentials"
            elif budget["calls_skipped"] > 0 and budget["calls_attempted"] == 0:
                status = "skipped"
                reason = "budget_exhausted"
            elif not any(stage_breakdown[stage]["eligible_entities"] > 0 for stage in stage_breakdown):
                status = "skipped"
                reason = "no_eligible_entities"

        llm_stage = {
            "status": status,
            "reason": reason,
            "processor_version": PROCESSOR_VERSION,
            "helper_mode": helper_mode,
            "model_name": model_name,
            "calls_attempted": budget["calls_attempted"],
            "calls_skipped": budget["calls_skipped"],
            "accepted_patches_total": len(accepted_patches),
            "audit_only_patches_total": len(audit_only_patches),
            "review_required_count": sum(1 for row in audit_rows if row.get("review_required")),
            "tokens_input_total": budget["tokens_input_total"],
            "tokens_output_total": budget["tokens_output_total"],
            "cost_estimate_usd": round(float(budget["cost_estimate_usd"]), 6),
            "budget": budget,
            "stage_breakdown": stage_breakdown,
            "product_row_coverage": product_row_coverage,
            "accepted_patches": accepted_patches,
            "audit_only_patches": audit_only_patches,
        }
        if progress_snapshot is not None:
            llm_stage["progress"] = progress_snapshot
        if product_row_chunking is not None:
            llm_stage["product_row_chunking"] = product_row_chunking
        if quota_blocker is not None:
            llm_stage["quota_blocker"] = copy.deepcopy(quota_blocker)

        result = {
            "run_id": run_id,
            "workflow_stage": WORKFLOW_STAGE,
            "llm_contract_version": PROCESSOR_VERSION,
            "llm_enabled": True,
            "helper_mode": helper_mode,
            "canonical_output": canonical_output,
            "audit_enrichment_rows": audit_rows,
            "llm_stage": llm_stage,
        }
        return json.loads(compact_json(result, pretty=pretty))

    llm_quota_blocker: dict[str, Any] | None = None

    def execute_stage(
        stage_name: str,
        candidates: list[Candidate],
        *,
        index_offset: int = 0,
        planned_total: int | None = None,
        should_stop_before_candidate: Callable[[], bool] | None = None,
        safe_product_row_rejection_drop: bool = False,
    ) -> None:
        nonlocal llm_quota_blocker
        progress.current_stage = stage_name
        progress.current_candidate_total = planned_total if planned_total is not None else len(candidates)
        progress.current_candidate_index = index_offset
        progress.current_entity_type = ""
        progress.current_entity_id = ""
        _raise_if_total_timeout(progress, monotonic_clock)
        for index, candidate in enumerate(candidates, start=1):
            progress.current_stage = candidate.stage
            progress.current_candidate_index = index_offset + index
            progress.current_candidate_total = planned_total if planned_total is not None else len(candidates)
            progress.current_entity_type = candidate.entity_type
            progress.current_entity_id = candidate.entity_id
            if should_stop_before_candidate is not None and should_stop_before_candidate():
                break
            candidate_outcome = _execute_candidate(
                run_id=run_id,
                candidate=candidate,
                transport=transport,
                model_name=model_name,
                budget=budget,
                providers_by_key=providers_by_key,
                offers_by_key=offers_by_key,
                audit_rows=audit_rows,
                accepted_patches=accepted_patches,
                audit_only_patches=audit_only_patches,
                stage_breakdown=stage_breakdown,
                missing_credentials=missing_credentials,
                timeout_guard=lambda: _raise_if_total_timeout(progress, monotonic_clock),
                safe_product_row_rejection_drop=safe_product_row_rejection_drop,
            )
            if (
                isinstance(candidate_outcome, dict)
                and candidate_outcome.get("reason") == LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON
            ):
                llm_quota_blocker = copy.deepcopy(candidate_outcome)
                return
            progress.completed_candidates_total += 1

    product_row_fetch_freeze = _product_row_fetch_freeze_from_payload(payload)
    product_row_loaded_chunk_state: dict[str, Any] = {}
    product_row_fetch_freeze_excluded_candidate_ids: list[str] = []
    product_row_candidates = _build_product_row_candidates(
        deterministic_providers_by_key=deterministic_providers_by_key,
        deterministic_offers_by_key=deterministic_offers_by_key,
        offers_by_key=offers_by_key,
        raw_post_map=raw_post_map,
    )
    product_row_candidate_limit = _resolve_product_row_candidate_limit(normalized_request)
    product_row_chunking_active = False
    product_row_chunking_summary: dict[str, Any] | None = None
    product_row_chunk_state: dict[str, Any] = {}
    product_row_chunk_state_path = ""
    product_row_chunk_size = 0
    product_row_chunk_start_index = 0
    product_row_chunk_end_index = 0
    if _product_row_chunking_enabled(normalized_request):
        product_row_chunk_state_path = _product_row_state_path(normalized_request)
        product_row_loaded_chunk_state = _load_product_row_chunk_state(normalized_request)
        state_fetch_freeze = (
            product_row_loaded_chunk_state.get("fetch_freeze")
            if isinstance(product_row_loaded_chunk_state.get("fetch_freeze"), dict)
            else {}
        )
        effective_fetch_freeze = state_fetch_freeze or product_row_fetch_freeze
        state_candidate_ids = [
            _as_text(candidate_id)
            for candidate_id in product_row_loaded_chunk_state.get("candidate_ids", [])
            if _as_text(candidate_id)
        ]
        product_row_candidates, product_row_fetch_freeze_excluded_candidate_ids = (
            _filter_product_row_candidates_for_fetch_freeze(
                candidates=product_row_candidates,
                offers_by_key=offers_by_key,
                raw_post_map=raw_post_map,
                fetch_freeze=effective_fetch_freeze,
                state_candidate_ids=state_candidate_ids,
            )
        )
        product_row_fetch_freeze = effective_fetch_freeze
    product_row_candidate_ids = _product_row_candidate_ids(product_row_candidates)
    product_row_candidate_identities = _product_row_candidate_identities(product_row_candidates)
    if len(product_row_candidates) > product_row_candidate_limit:
        if _product_row_chunking_enabled(normalized_request):
            product_row_chunking_active = True
            product_row_chunk_size = _resolve_product_row_chunk_size(
                normalized_request,
                candidate_limit=product_row_candidate_limit,
            )
            if product_row_candidate_limit > 0:
                product_row_chunk_size = min(product_row_chunk_size, product_row_candidate_limit)
            product_row_chunk_state, state_error = _validated_product_row_chunk_state(
                raw_state=product_row_loaded_chunk_state,
                run_id=run_id,
                candidate_ids=product_row_candidate_ids,
                candidate_identities=product_row_candidate_identities,
                candidate_limit=product_row_candidate_limit,
                chunk_size=product_row_chunk_size,
                state_path=product_row_chunk_state_path,
                fetch_freeze=product_row_fetch_freeze,
            )
            requested_token = normalize_text(_as_text(normalized_request.get("llm_product_row_continuation_token")))
            if not state_error and requested_token:
                current_token = normalize_text(_as_text(product_row_chunk_state.get("continuation_token")))
                if requested_token != current_token:
                    state_error = "llm_product_row_continuation_state_token_mismatch"
            if state_error:
                progress.current_stage = "llm_product_row_shape"
                progress.current_candidate_index = int(product_row_chunk_state.get("next_cursor") or 0)
                progress.current_candidate_total = len(product_row_candidates)
                stage_breakdown["llm_product_row_shape"]["eligible_entities"] = len(product_row_candidates)
                budget["last_outcome"] = state_error
                _ensure_budget_flags(budget)
                state_progress = {
                    "status": "blocked",
                    "reason": state_error,
                    "current_stage": "llm_product_row_shape",
                    "current_candidate_index": progress.current_candidate_index,
                    "current_candidate_total": len(product_row_candidates),
                    "completed_candidates_total": progress.completed_candidates_total,
                    "candidate_limit": product_row_candidate_limit,
                    "chunk_size": product_row_chunk_size,
                    "continuation_state_path": product_row_chunk_state_path,
                }
                missing_lower_bound_sources = list(
                    product_row_chunk_state.get("fetch_freeze_missing_lower_bound_sources") or []
                )
                if missing_lower_bound_sources:
                    state_progress["fetch_freeze_missing_lower_bound_sources"] = copy.deepcopy(
                        missing_lower_bound_sources
                    )
                    state_progress["safe_repair_contract"] = (
                        "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required"
                    )
                candidate_mismatch_evidence = product_row_chunk_state.get("candidate_mismatch_evidence")
                if isinstance(candidate_mismatch_evidence, dict) and candidate_mismatch_evidence:
                    state_progress["candidate_mismatch_evidence"] = copy.deepcopy(candidate_mismatch_evidence)
                    state_progress["safe_repair_contract"] = candidate_mismatch_evidence.get(
                        "safe_repair_contract",
                        "fresh_product_row_chunk_state_or_orchestrator_approved_state_repair_required",
                    )
                audit_only_patches.append(
                    {
                        "stage": "llm_product_row_shape",
                        "entity_type": "workflow",
                        "entity_id": "llm_post_merge",
                        "status": "blocked",
                        "decision_code": state_error,
                        "patch": {},
                        "reason_text": "Product-row continuation state could not be safely resumed.",
                    }
                )
                product_row_chunking_summary = _product_row_chunk_summary(
                    state=product_row_chunk_state,
                    candidate_ids=product_row_candidate_ids,
                    chunk_start_index=progress.current_candidate_index,
                    chunk_end_index=progress.current_candidate_index,
                    chunk_size=product_row_chunk_size,
                    candidate_limit=product_row_candidate_limit,
                    state_path=product_row_chunk_state_path,
                    include_inline_state=not product_row_chunk_state_path,
                )
                product_row_chunking_summary["status"] = "blocked"
                product_row_chunking_summary["error"] = state_error
                return build_result(
                    llm_status="error",
                    llm_reason=state_error,
                    progress_snapshot=state_progress,
                    planned_product_candidate_total=len(product_row_candidates),
                    product_row_incomplete_reason=state_error,
                    product_row_chunking=product_row_chunking_summary,
                )

            _apply_product_row_chunk_state_to_runtime(
                state=product_row_chunk_state,
                offers_by_key=offers_by_key,
                stage_breakdown=stage_breakdown,
                budget=budget,
                audit_rows=audit_rows,
                accepted_patches=accepted_patches,
                audit_only_patches=audit_only_patches,
            )
            progress.completed_candidates_total = int(product_row_chunk_state.get("next_cursor") or 0)
            product_row_chunk_start_index = int(product_row_chunk_state.get("next_cursor") or 0)
            product_row_chunk_start_completed_total = progress.completed_candidates_total
            product_row_chunk_end_index = min(
                len(product_row_candidates),
                product_row_chunk_start_index + product_row_chunk_size,
            )
        else:
            progress.current_stage = "llm_product_row_shape"
            progress.current_candidate_index = 0
            progress.current_candidate_total = len(product_row_candidates)
            stage_breakdown["llm_product_row_shape"]["eligible_entities"] = len(product_row_candidates)
            stage_breakdown["llm_product_row_shape"]["skipped"] = len(product_row_candidates)
            budget["calls_skipped"] += len(product_row_candidates)
            budget["last_outcome"] = "llm_product_row_scale_blocked"
            _ensure_budget_flags(budget)
            scale_progress = {
                "status": "blocked",
                "reason": "llm_product_row_scale_blocked",
                "current_stage": "llm_product_row_shape",
                "current_candidate_index": 0,
                "current_candidate_total": len(product_row_candidates),
                "completed_candidates_total": progress.completed_candidates_total,
                "candidate_limit": product_row_candidate_limit,
                "required_strategy": "chunk_or_resume_before_public_publication",
            }
            audit_rows.append(
                _build_product_row_scale_block_audit_row(
                    run_id=run_id,
                    model_name=model_name,
                    candidate_total=len(product_row_candidates),
                    candidate_limit=product_row_candidate_limit,
                )
            )
            audit_only_patches.append(
                {
                    "stage": "llm_product_row_shape",
                    "entity_type": "workflow",
                    "entity_id": "llm_post_merge",
                    "status": "blocked",
                    "decision_code": "llm_product_row_scale_blocked",
                    "patch": {},
                    "reason_text": (
                        "Product-row LLM candidate pool exceeds the per-run guard; "
                        "public publication requires chunk/resume."
                    ),
                }
            )
            return build_result(
                llm_status="error",
                llm_reason="llm_product_row_scale_blocked",
                progress_snapshot=scale_progress,
                planned_product_candidate_total=len(product_row_candidates),
                product_row_incomplete_reason="llm_product_row_scale_blocked",
            )

    if not product_row_chunking_active:
        product_row_chunk_end_index = len(product_row_candidates)

    try:
        if product_row_chunking_active:
            execute_stage(
                "llm_product_row_shape",
                product_row_candidates[product_row_chunk_start_index:product_row_chunk_end_index],
                index_offset=product_row_chunk_start_index,
                planned_total=len(product_row_candidates),
                should_stop_before_candidate=lambda: _product_row_chunk_should_stop_before_timeout(
                    progress=progress,
                    monotonic=monotonic_clock,
                    chunk_start_completed_total=product_row_chunk_start_completed_total,
                ),
                safe_product_row_rejection_drop=True,
            )
            product_row_chunk_state = _refresh_product_row_chunk_state(
                state=product_row_chunk_state,
                candidate_ids=product_row_candidate_ids,
                candidate_identities=product_row_candidate_identities,
                chunk_size=product_row_chunk_size,
                candidate_limit=product_row_candidate_limit,
                state_path=product_row_chunk_state_path,
                fetch_freeze=product_row_fetch_freeze,
                fetch_freeze_excluded_candidate_ids=product_row_fetch_freeze_excluded_candidate_ids,
                stage_breakdown=stage_breakdown,
                budget=budget,
                audit_rows=audit_rows,
                accepted_patches=accepted_patches,
                audit_only_patches=audit_only_patches,
                quota_blocker=llm_quota_blocker,
            )
            _write_product_row_chunk_state(product_row_chunk_state, product_row_chunk_state_path)
            product_row_chunking_summary = _product_row_chunk_summary(
                state=product_row_chunk_state,
                candidate_ids=product_row_candidate_ids,
                chunk_start_index=product_row_chunk_start_index,
                chunk_end_index=product_row_chunk_end_index,
                chunk_size=product_row_chunk_size,
                candidate_limit=product_row_candidate_limit,
                state_path=product_row_chunk_state_path,
                include_inline_state=not product_row_chunk_state_path,
            )
            if llm_quota_blocker is not None:
                retry_cursor = int(product_row_chunking_summary["next_cursor"])
                progress.current_stage = "llm_product_row_shape"
                progress.current_candidate_index = retry_cursor
                progress.current_candidate_total = len(product_row_candidates)
                budget["last_outcome"] = LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON
                return build_result(
                    llm_status="error",
                    llm_reason=LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
                    progress_snapshot={
                        "status": "blocked",
                        "reason": LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
                        "current_stage": "llm_product_row_shape",
                        "current_candidate_index": retry_cursor,
                        "current_candidate_total": len(product_row_candidates),
                        "completed_candidates_total": progress.completed_candidates_total,
                        "candidate_limit": product_row_candidate_limit,
                        "chunk_size": product_row_chunk_size,
                        "continuation_token": product_row_chunking_summary["continuation_token"],
                        "continuation_state_path": product_row_chunk_state_path,
                        "can_retry_same_continuation_state": True,
                        "safe_retry_contract": PRODUCT_ROW_QUOTA_RETRY_CONTRACT,
                    },
                    planned_product_candidate_total=len(product_row_candidates),
                    product_row_incomplete_reason=LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
                    product_row_chunking=product_row_chunking_summary,
                    quota_blocker=llm_quota_blocker,
                )
            if product_row_chunking_summary["failures"] > 0:
                progress.current_stage = "llm_product_row_shape"
                progress.current_candidate_index = product_row_chunk_end_index
                progress.current_candidate_total = len(product_row_candidates)
                budget["last_outcome"] = "product_row_coverage_failed"
                return build_result(
                    llm_status="error",
                    llm_reason="product_row_coverage_failed",
                    progress_snapshot={
                        "status": "error",
                        "reason": "product_row_coverage_failed",
                        "current_stage": "llm_product_row_shape",
                        "current_candidate_index": product_row_chunk_end_index,
                        "current_candidate_total": len(product_row_candidates),
                        "completed_candidates_total": progress.completed_candidates_total,
                        "chunk_size": product_row_chunk_size,
                        "continuation_state_path": product_row_chunk_state_path,
                    },
                    planned_product_candidate_total=len(product_row_candidates),
                    product_row_chunking=product_row_chunking_summary,
                )
            if product_row_chunking_summary["remaining_candidate_count"] > 0:
                budget["last_outcome"] = "llm_product_row_continuation_required"
                return build_result(
                    llm_status="error",
                    llm_reason="llm_product_row_continuation_required",
                    progress_snapshot={
                        "status": "continuation_required",
                        "reason": "llm_product_row_continuation_required",
                        "current_stage": "llm_product_row_shape",
                        "current_candidate_index": product_row_chunking_summary["next_cursor"],
                        "current_candidate_total": len(product_row_candidates),
                        "completed_candidates_total": progress.completed_candidates_total,
                        "candidate_limit": product_row_candidate_limit,
                        "chunk_size": product_row_chunk_size,
                        "continuation_token": product_row_chunking_summary["continuation_token"],
                        "continuation_state_path": product_row_chunk_state_path,
                    },
                    planned_product_candidate_total=len(product_row_candidates),
                    product_row_incomplete_reason="llm_product_row_continuation_required",
                    product_row_chunking=product_row_chunking_summary,
                )
        else:
            execute_stage(
                "llm_product_row_shape",
                product_row_candidates,
            )
            if llm_quota_blocker is not None:
                retry_index = max(0, progress.current_candidate_index - 1)
                return build_result(
                    llm_status="error",
                    llm_reason=LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
                    progress_snapshot={
                        "status": "blocked",
                        "reason": LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
                        "current_stage": "llm_product_row_shape",
                        "current_candidate_index": retry_index,
                        "current_candidate_total": len(product_row_candidates),
                        "completed_candidates_total": progress.completed_candidates_total,
                        "can_retry_same_continuation_state": False,
                        "safe_retry_contract": PRODUCT_ROW_QUOTA_RETRY_CONTRACT,
                    },
                    planned_product_candidate_total=len(product_row_candidates),
                    product_row_incomplete_reason=LLM_PRODUCT_ROW_QUOTA_BLOCKED_REASON,
                    quota_blocker=llm_quota_blocker,
                )
        execute_stage(
            "llm_service_relevance",
            _build_service_relevance_candidates(
                providers_by_key=providers_by_key,
                offers_by_key=offers_by_key,
                raw_post_map=raw_post_map,
            ),
        )
        execute_stage(
            "llm_serbia_relevance",
            _build_serbia_relevance_candidates(
                providers_by_key=providers_by_key,
                offers_by_key=offers_by_key,
                raw_post_map=raw_post_map,
            ),
        )
        execute_stage(
            "llm_category_refine",
            _build_category_offer_candidates(
                providers_by_key=providers_by_key,
                offers_by_key=offers_by_key,
                raw_post_map=raw_post_map,
            ),
        )
        execute_stage(
            "llm_category_refine",
            _build_category_provider_candidates(
                providers_by_key=providers_by_key,
                offers_by_key=offers_by_key,
                raw_post_map=raw_post_map,
            ),
        )
        execute_stage(
            "llm_provider_merge_review",
            _build_provider_merge_review_candidates(
                providers_by_key=providers_by_key,
                raw_post_map=raw_post_map,
            ),
        )
        execute_stage(
            "llm_offer_dedupe_review",
            _build_offer_dedupe_review_candidates(
                offers_by_key=offers_by_key,
                raw_post_map=raw_post_map,
            ),
        )
    except LlmTotalTimeout:
        timeout_progress = _progress_snapshot(progress, monotonic_clock)
        budget["last_outcome"] = "llm_total_timeout"
        _ensure_budget_flags(budget)
        audit_rows.append(
            _build_timeout_audit_row(
                run_id=run_id,
                model_name=model_name,
                progress=timeout_progress,
            )
        )
        audit_only_patches.append(
            {
                "stage": timeout_progress["current_stage"] or "llm_total_timeout",
                "entity_type": timeout_progress["current_entity_type"] or "workflow",
                "entity_id": timeout_progress["current_entity_id"] or "llm_post_merge",
                "status": "error",
                "decision_code": "llm_total_timeout",
                "patch": {},
                "reason_text": "Post-merge LLM helper reached total wall-clock timeout.",
            }
        )
        if product_row_chunking_active:
            product_row_chunk_state = _refresh_product_row_chunk_state(
                state=product_row_chunk_state,
                candidate_ids=product_row_candidate_ids,
                candidate_identities=product_row_candidate_identities,
                chunk_size=product_row_chunk_size,
                candidate_limit=product_row_candidate_limit,
                state_path=product_row_chunk_state_path,
                fetch_freeze=product_row_fetch_freeze,
                fetch_freeze_excluded_candidate_ids=product_row_fetch_freeze_excluded_candidate_ids,
                stage_breakdown=stage_breakdown,
                budget=budget,
                audit_rows=audit_rows,
                accepted_patches=accepted_patches,
                audit_only_patches=audit_only_patches,
            )
            _write_product_row_chunk_state(product_row_chunk_state, product_row_chunk_state_path)
            product_row_chunking_summary = _product_row_chunk_summary(
                state=product_row_chunk_state,
                candidate_ids=product_row_candidate_ids,
                chunk_start_index=product_row_chunk_start_index,
                chunk_end_index=product_row_chunk_end_index,
                chunk_size=product_row_chunk_size,
                candidate_limit=product_row_candidate_limit,
                state_path=product_row_chunk_state_path,
                include_inline_state=not product_row_chunk_state_path,
            )
        return build_result(
            llm_status="error",
            llm_reason="llm_total_timeout",
            progress_snapshot=timeout_progress,
            planned_product_candidate_total=len(product_row_candidates),
            product_row_chunking=product_row_chunking_summary,
        )

    return build_result(
        planned_product_candidate_total=len(product_row_candidates) if product_row_chunking_active else None,
        product_row_chunking=product_row_chunking_summary,
    )
