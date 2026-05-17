from __future__ import annotations

import json
import unittest
from typing import Any

from scripts.llm.post_merge import _finalize_product_rows, _looks_like_real_estate_listing, _looks_like_vacancy_or_cv


def _build_offer(**overrides: Any) -> dict[str, Any]:
    offer = {
        "offer_key": "offer:test:gate",
        "provider_key": "provider:test:gate",
        "offer_state": "accepted",
        "offer_rejection_reason": "",
        "serbia_relevance_verdict": "serbia_relevant",
        "category_primary": "beauty_cosmetology",
        "title_best": "Маникюр и педикюр",
        "description_best": "Маникюр, педикюр и укрепление гелем в Нови-Саде.",
        "service_name_candidate": "Маникюр и педикюр",
        "details_candidate": "Маникюр, педикюр и укрепление гелем в Нови-Саде.",
        "service_tags": ["manicure", "pedicure"],
        "fact_pack_quality": "clean",
        "fact_pack_flags": [],
        "price_text_best": "20 EUR",
        "price_min": 20,
        "price_max": 20,
        "currency_code": "eur",
        "product_row_publish_decision": "publish",
        "product_row_service_name": "Маникюр и педикюр",
        "product_row_details": "Маникюр, педикюр и укрепление гелем в Нови-Саде.",
        "product_row_category": "Красота и здоровье",
        "product_row_contact": "@example_nina_nails",
        "product_row_audit_reason": "deterministic_fact_pack_draft",
        "contact_candidate_display": "@example_nina_nails",
        "contact_snapshot_phones": [],
        "contact_snapshot_telegram_handles": ["example_nina_nails"],
        "contact_snapshot_telegram_links": ["https://t.me/example_nina_nails"],
        "contact_snapshot_emails": [],
        "contact_snapshot_websites": [],
        "explicit_contact_snapshot_phones": [],
        "explicit_contact_snapshot_telegram_handles": ["example_nina_nails"],
        "explicit_contact_snapshot_telegram_links": ["https://t.me/example_nina_nails"],
        "author_fallback_phones": [],
        "author_fallback_telegram_handles": [],
        "author_fallback_telegram_links": [],
        "source_anchor_text": "@example_source_mu/42",
        "latest_post_url": "https://t.me/example_source_mu/42",
        "freshness_at_utc": "2026-04-21T12:00:00Z",
        "last_seen_at_utc": "2026-04-21T12:00:00Z",
    }
    offer.update(overrides)
    if "explicit_contact_snapshot_phones" not in overrides:
        offer["explicit_contact_snapshot_phones"] = list(offer.get("contact_snapshot_phones", []))
    if "explicit_contact_snapshot_telegram_handles" not in overrides:
        offer["explicit_contact_snapshot_telegram_handles"] = list(offer.get("contact_snapshot_telegram_handles", []))
    if "explicit_contact_snapshot_telegram_links" not in overrides:
        offer["explicit_contact_snapshot_telegram_links"] = list(offer.get("contact_snapshot_telegram_links", []))
    if "author_fallback_phones" not in overrides:
        offer["author_fallback_phones"] = []
    if "author_fallback_telegram_handles" not in overrides:
        offer["author_fallback_telegram_handles"] = []
    if "author_fallback_telegram_links" not in overrides:
        offer["author_fallback_telegram_links"] = []
    return offer


class PublishableRowGateTests(unittest.TestCase):
    def test_publishable_row_contract_uses_split_visible_channels_and_exact_post_url(self) -> None:
        offer = _build_offer(
            product_row_contact="@example_nina_nails | +381600000001",
            contact_candidate_display="+381600000001",
            contact_snapshot_phones=["381600000001"],
            latest_post_url="",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Маникюр и педикюр")
        self.assertEqual(row["details"], "Маникюр, педикюр и укрепление гелем в Нови-Саде.")
        self.assertEqual(row["category"], "Красота и здоровье")
        self.assertEqual(row["price"], "20 eur")
        self.assertEqual(row["contact"], "+381600000001")
        self.assertEqual(row["telegram"], "@example_nina_nails")
        self.assertEqual(row["instagram"], "")
        self.assertEqual(row["whatsapp"], "")
        self.assertEqual(row["phone"], "+381600000001")
        self.assertEqual(row["source"], "https://t.me/example_source_mu/42")
        self.assertEqual(row["actual_on"], "21.04.2026")

    def test_publishable_row_corrects_unsupported_category_guess_from_visible_meaning(self) -> None:
        offer = _build_offer(
            product_row_category="Автоуслуги",
            contact_candidate_display="+381600000001",
            contact_snapshot_phones=["381600000001"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["category"], "Красота и здоровье")
        self.assertEqual(row["telegram"], "@example_nina_nails")
        self.assertEqual(row["phone"], "+381600000001")

    def test_publishable_row_drops_noisy_emoji_row(self) -> None:
        offer = _build_offer(
            product_row_service_name="Маникюр 😍😍😍😍",
            product_row_details="Маникюр, педикюр и укрепление гелем в Нови-Саде.",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_emoji_storm")
        self.assertEqual(row["telegram"], "")
        self.assertEqual(row["phone"], "")
        self.assertEqual(row["source"], "")

    def test_publishable_row_drops_without_exact_source_anchor(self) -> None:
        offer = _build_offer(
            source_anchor_text="",
            latest_post_url="https://example.com/post/42",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_source_missing")
        self.assertEqual(row["actual_on"], "")

    def test_publishable_row_ignores_hallucinated_row_contact_and_uses_canonical_channels(self) -> None:
        offer = _build_offer(
            product_row_contact="@invented_contact",
            contact_candidate_display="+381600000001",
            contact_snapshot_phones=["381600000001"],
            contact_snapshot_telegram_handles=[],
            contact_snapshot_telegram_links=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["telegram"], "")
        self.assertEqual(row["phone"], "+381600000001")
        self.assertEqual(row["contact"], "+381600000001")
        self.assertNotIn("@invented_contact", json.dumps(row, ensure_ascii=False))

    def test_publishable_row_uses_distinct_author_telegram_fallback_and_keeps_phone_blank_without_sender_phone(self) -> None:
        offer = _build_offer(
            contact_candidate_display="@example_boiler_master",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=[],
            contact_snapshot_telegram_links=[],
            explicit_contact_snapshot_phones=[],
            explicit_contact_snapshot_telegram_handles=[],
            explicit_contact_snapshot_telegram_links=[],
            author_fallback_phones=[],
            author_fallback_telegram_handles=["example_boiler_master"],
            author_fallback_telegram_links=["https://t.me/example_boiler_master"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["telegram"], "@example_boiler_master")
        self.assertEqual(row["phone"], "")
        self.assertEqual(row["contact"], "@example_boiler_master")

    def test_publishable_row_uses_deterministic_sender_phone_fallback_when_available(self) -> None:
        offer = _build_offer(
            contact_candidate_display="+381600000003",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=[],
            contact_snapshot_telegram_links=[],
            explicit_contact_snapshot_phones=[],
            explicit_contact_snapshot_telegram_handles=[],
            explicit_contact_snapshot_telegram_links=[],
            author_fallback_phones=["381600000003"],
            author_fallback_telegram_handles=["example_boiler_master"],
            author_fallback_telegram_links=["https://t.me/example_boiler_master"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["telegram"], "@example_boiler_master")
        self.assertEqual(row["phone"], "+381600000003")

    def test_publishable_row_drops_without_publishable_visible_contact_channel(self) -> None:
        offer = _build_offer(
            product_row_contact="https://example.com",
            contact_candidate_display="https://example.com",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=[],
            contact_snapshot_telegram_links=[],
            contact_snapshot_emails=[],
            contact_snapshot_websites=["https://example.com"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_contact_missing")
        self.assertEqual(row["service_name"], "")

    def test_publishable_row_drops_news_chat_giveaway_noise(self) -> None:
        offer = _build_offer(
            product_row_service_name="Сделали для вас розыгрыш!",
            product_row_details="Не забываем: переход на летнее время в Сербии — сегодня.",
            contact_candidate_display="+381600000001",
            contact_snapshot_phones=["381600000001"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_non_service")
        self.assertEqual(row["phone"], "")

    def test_publishable_row_drops_question_like_live_service_label_family(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_gamma/40531",
            source_anchor_text="@example_source_gamma/40531",
            category_primary="education_tutoring",
            service_tags=["education_tutoring", "ielts", "английский"],
            product_row_service_name="Говорите по-английски, но трудно воспринимаете речь на слух и беспокоит произношение? 🇬🇧",
            product_row_details=(
                "Меня зовут Данила; Я специализируюсь не просто на грамматике, а на том, чтобы вы звучали как носитель "
                "и понимали английскую речь на слух; Учился и закончил среднюю школу в Англии (4 года); "
                "Уровень - IELTS C2; Более 5 лет преподавания"
            ),
            product_row_category="Обучение",
            product_row_contact="@example_contact_delta",
            contact_candidate_display="@example_contact_delta",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_contact_delta"],
            contact_snapshot_telegram_links=["https://t.me/example_contact_delta"],
            freshness_at_utc="2026-04-22T14:57:32Z",
            last_seen_at_utc="2026-04-22T14:57:32Z",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["service_name"], "")
        self.assertEqual(row["source"], "")
        self.assertEqual(row["audit_reason"], "publishable_missing_service_name")

    def test_publishable_row_drops_current_live_address_price_and_instruction_label_family(self) -> None:
        cases = [
            (
                "3394",
                {
                    "latest_post_url": "https://t.me/example_source_zeta/3394",
                    "source_anchor_text": "@example_source_zeta/3394",
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["beauty_hair", "styling", "haircut"],
                    "product_row_service_name": "Адрес: Кнеза Милоша 95",
                    "product_row_details": "Студия по волосам, укладки и стрижка.",
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "@example_editor_contact",
                    "contact_candidate_display": "@example_editor_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_editor_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_editor_contact"],
                    "freshness_at_utc": "2026-04-22T08:49:04Z",
                    "last_seen_at_utc": "2026-04-22T08:49:04Z",
                },
            ),
            (
                "3395",
                {
                    "latest_post_url": "https://t.me/example_source_zeta/3395",
                    "source_anchor_text": "@example_source_zeta/3395",
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["beauty_hair", "styling"],
                    "product_row_service_name": "По стоимости: бесплатно (на дому) либо (в салоне)",
                    "product_row_details": "Укладка феном на брашинг и локоны.",
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "@example_contact_beta",
                    "contact_candidate_display": "@example_contact_beta",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_contact_beta"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_contact_beta"],
                    "freshness_at_utc": "2026-04-22T12:47:20Z",
                    "last_seen_at_utc": "2026-04-22T12:47:20Z",
                },
            ),
            (
                "1780",
                {
                    "latest_post_url": "https://t.me/example_source_delta/1780",
                    "source_anchor_text": "@example_source_delta/1780",
                    "category_primary": "it_digital",
                    "service_tags": ["it_digital", "ios", "app"],
                    "product_row_service_name": "Как попасть в число первых пользователей ios",
                    "product_row_details": "Установите TestFlight; Перейдите на сайт; Получите доступ.",
                    "product_row_category": "Digital и дизайн",
                    "product_row_contact": "@example_contact_gamma",
                    "contact_candidate_display": "@example_contact_gamma",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_contact_gamma"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_contact_gamma"],
                    "freshness_at_utc": "2026-03-19T01:23:36Z",
                    "last_seen_at_utc": "2026-03-19T01:23:36Z",
                },
            ),
        ]

        for anchor, overrides in cases:
            with self.subTest(anchor=anchor):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["service_name"], "")
                self.assertEqual(row["details"], "")
                self.assertEqual(row["source"], "")
                self.assertEqual(row["audit_reason"], "publishable_missing_service_name")

    def test_publishable_row_removes_address_price_and_instruction_detail_fragments(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_zeta/3400",
            source_anchor_text="@example_source_zeta/3400",
            category_primary="beauty_cosmetology",
            service_tags=["beauty_hair", "styling"],
            product_row_service_name="Укладка волос",
            product_row_details=(
                "Адрес: Кнеза Милоша 95; "
                "По стоимости: бесплатно; "
                "Как записаться: напишите в личные сообщения; "
                "Укладка феном и локоны"
            ),
            product_row_category="Красота и здоровье",
            product_row_contact="@example_hair_stylist",
            contact_candidate_display="@example_hair_stylist",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_hair_stylist"],
            contact_snapshot_telegram_links=["https://t.me/example_hair_stylist"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Укладка волос")
        self.assertEqual(row["details"], "Укладка феном и локоны")
        self.assertNotIn("адрес", row["details"].lower())
        self.assertNotIn("стоимости", row["details"].lower())
        self.assertNotIn("как записаться", row["details"].lower())

    def test_publishable_row_normalizes_provider_intro_brand_promo_and_sentence_live_family(self) -> None:
        cases = [
            (
                "3381",
                {
                    "latest_post_url": "https://t.me/example_source_zeta/3381",
                    "source_anchor_text": "@example_source_zeta/3381",
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["beauty_cosmetology", "электроэпиляция", "модели"],
                    "title_best": "Ника, сертифицированный мастер по электроэпиляции 🌿",
                    "description_best": "Сейчас активно собираю портфолио и приглашаю моделей на процедуры.; Зоны для работы; подмышки",
                    "service_name_candidate": "Ника, сертифицированный мастер по электроэпиляции 🌿",
                    "details_candidate": "Сейчас активно собираю портфолио и приглашаю моделей на процедуры.; Зоны для работы; подмышки",
                    "product_row_service_name": "Ника, сертифицированный мастер по электроэпиляции 🌿",
                    "product_row_details": "Сейчас активно собираю портфолио и приглашаю моделей на процедуры.; Зоны для работы; подмышки",
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "@example_epilation_contact",
                    "contact_candidate_display": "@example_epilation_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_epilation_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_epilation_contact"],
                    "freshness_at_utc": "2026-04-15T13:52:03Z",
                    "last_seen_at_utc": "2026-04-15T13:52:03Z",
                },
                "drop",
                "",
            ),
            (
                "70213",
                {
                    "latest_post_url": "https://t.me/example_source_beta/70213",
                    "source_anchor_text": "@example_source_beta/70213",
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["manicure", "pedicure", "nails"],
                    "title_best": "сертифицированный мастер маникюра/педикюра.",
                    "description_best": "Приглашаю в нейл студию на маникюр и педикюр по отличным ценам!; Маникюр гигиена 2000rsd, Маникюр с покрытием от 2500rsd, Педикюр от 3000rsd.; Центр Белграда.",
                    "service_name_candidate": "сертифицированный мастер маникюра/педикюра.",
                    "details_candidate": "Приглашаю в нейл студию на маникюр и педикюр по отличным ценам!; Маникюр гигиена 2000rsd, Маникюр с покрытием от 2500rsd, Педикюр от 3000rsd.; Центр Белграда.",
                    "product_row_service_name": "сертифицированный мастер маникюра/педикюра.",
                    "product_row_details": "Приглашаю в нейл студию на маникюр и педикюр по отличным ценам!; Маникюр гигиена 2000rsd, Маникюр с покрытием от 2500rsd, Педикюр от 3000rsd.; Центр Белграда.",
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "@example_nails_maria",
                    "contact_candidate_display": "@example_nails_maria",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_nails_maria"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_nails_maria"],
                    "freshness_at_utc": "2026-04-23T10:00:00Z",
                    "last_seen_at_utc": "2026-04-23T10:00:00Z",
                },
                "publish",
                "Маникюр и педикюр",
            ),
            (
                "70178",
                {
                    "latest_post_url": "https://t.me/example_source_beta/70178",
                    "source_anchor_text": "@example_source_beta/70178",
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning", "уборка", "химчистка"],
                    "title_best": "Breeze Cleaning — ваш надежный клининг в Белграде и Нови-Саде!",
                    "description_best": "СКИДКА 15% + ПОДАРОК В ЧЕСТЬ ЗАПУСКА!; Что мы делаем: поддерживающая уборка, генеральная уборка, уборка после ремонта, химчистка мягкой мебели, обработка паром.",
                    "service_name_candidate": "Breeze Cleaning — ваш надежный клининг в Белграде и Нови-Саде!",
                    "details_candidate": "СКИДКА 15% + ПОДАРОК В ЧЕСТЬ ЗАПУСКА!; Что мы делаем: поддерживающая уборка, генеральная уборка, уборка после ремонта, химчистка мягкой мебели, обработка паром.",
                    "product_row_service_name": "Breeze Cleaning — ваш надежный клининг в Белграде и Нови-Саде!",
                    "product_row_details": "СКИДКА 15% + ПОДАРОК В ЧЕСТЬ ЗАПУСКА!; Что мы делаем: поддерживающая уборка, генеральная уборка, уборка после ремонта, химчистка мягкой мебели, обработка паром.",
                    "product_row_category": "Уборка и химчистка",
                    "product_row_contact": "@example_cleaning_manager",
                    "contact_candidate_display": "@example_cleaning_manager",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_cleaning_manager"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_cleaning_manager"],
                    "freshness_at_utc": "2026-04-23T10:00:00Z",
                    "last_seen_at_utc": "2026-04-23T10:00:00Z",
                },
                "publish",
                "Клининг",
            ),
            (
                "70226",
                {
                    "latest_post_url": "https://t.me/example_source_beta/70226",
                    "source_anchor_text": "@example_source_beta/70226",
                    "category_primary": "education_tutoring",
                    "service_tags": ["consultation", "children", "professions"],
                    "title_best": "КОНСУЛЬТАЦИЯ ТАЛАНТОВ СПОСОБНОСТЕЙ И ПРОФЕССИЙ!",
                    "description_best": (
                        "Для женщин и их детей.; Помните, нас с детства спрашивали: КЕМ ТЫ БУДЕШЬ КОГДА ВЫРАСТЕШЬ?; "
                        "Способности ребёнка, его сильные стороны, предрасположенность к профессиям — всё это можно определить заранее.; "
                        "Практически с 4 лет.; Запишитесь на встречу со специалистом."
                    ),
                    "service_name_candidate": "КОНСУЛЬТАЦИЯ ТАЛАНТОВ СПОСОБНОСТЕЙ И ПРОФЕССИЙ!",
                    "details_candidate": (
                        "Для женщин и их детей.; Способности ребёнка, его сильные стороны, предрасположенность к профессиям — всё это можно определить заранее.; "
                        "Практически с 4 лет.; Запишитесь на встречу со специалистом."
                    ),
                    "product_row_service_name": "Консультация",
                    "product_row_details": (
                        "Талантов способностей и профессий.; Для женщин и их детей.; "
                        "Способности ребёнка, его сильные стороны, предрасположенность к профессиям — всё это можно определить заранее.; "
                        "Практически с 4 лет.; Запишитесь на встречу со специалистом."
                    ),
                    "product_row_category": "Обучение",
                    "product_row_contact": "@example_painting_contact",
                    "contact_candidate_display": "@example_painting_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_painting_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_painting_contact"],
                    "freshness_at_utc": "2026-04-23T10:00:00Z",
                    "last_seen_at_utc": "2026-04-23T10:00:00Z",
                },
                "publish",
                "Профориентационная консультация",
            ),
            (
                "70207",
                {
                    "latest_post_url": "https://t.me/example_source_beta/70207",
                    "source_anchor_text": "@example_source_beta/70207",
                    "category_primary": "education_tutoring",
                    "service_tags": ["tutor", "english", "german", "ielts"],
                    "title_best": "Здравствуйте! Я репетитор по английскому и немецкому языку.",
                    "description_best": (
                        "Проживаю в Сербии.; Беру учеников онлайн, также возможны встречи вживую.; Дети и взрослые.; "
                        "Мой опыт работы в различных языковых школах и репетиторства — 5 лет.; "
                        "Высшее образование по специальности перевод и переводоведение.; Прошла курсы TEFL.; "
                        "Сдала IELTS и Гете с результатом C1."
                    ),
                    "service_name_candidate": "репетитор по английскому и немецкому языку.",
                    "details_candidate": (
                        "Беру учеников онлайн, также возможны встречи вживую.; Дети и взрослые.; "
                        "IELTS и Гете.; Мой опыт работы в различных языковых школах и репетиторства — 5 лет."
                    ),
                    "product_row_service_name": "Мой опыт работы в различных языковых школах и репетиторства",
                    "product_row_details": (
                        "Здравствуйте! Я репетитор по английскому и немецкому языку.; Проживаю в Сербии.; "
                        "Беру учеников онлайн, также возможны встречи вживую.; Дети и взрослые.; "
                        "Высшее образование по специальности перевод и переводоведение.; Прошла TEFL.; "
                        "Сдала IELTS и Гете с результатом C1, поэтому также готовлю к этим экзаменам."
                    ),
                    "product_row_category": "Обучение",
                    "product_row_contact": "@example_language_tutor",
                    "contact_candidate_display": "@example_language_tutor",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_language_tutor"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_language_tutor"],
                    "freshness_at_utc": "2026-04-23T10:00:00Z",
                    "last_seen_at_utc": "2026-04-23T10:00:00Z",
                },
                "publish",
                "Уроки английского и немецкого",
            ),
            (
                "70203",
                {
                    "latest_post_url": "https://t.me/example_source_beta/70203",
                    "source_anchor_text": "@example_source_beta/70203",
                    "category_primary": "it_digital",
                    "service_tags": ["marketing", "smm", "sales"],
                    "title_best": "Привет! Меня зовут Максим и я помогаю специалистам и предпринимателям экономить время и:",
                    "description_best": (
                        "Находить платежеспособных клиентов по разным странам.; Делать продажи на новых рынках.; "
                        "Эффективно запускать проекты с нуля.; Создавать личный бренд через рилсы и телеграм.; "
                        "Запускать таргет в мете и гугле.; Получать реальный результат, а не просто красивые цифры.; "
                        "Я маркетолог и наставник с 5-и летним международным опытом в Европе и США в продвижении, смм и рекламе."
                    ),
                    "product_row_service_name": "Находить платежеспособных клиентов по разным странам",
                    "product_row_details": (
                        "Делать продажи на новых рынках.; Эффективно запускать проекты с нуля.; "
                        "Создавать личный бренд через рилсы и телеграм.; Запускать таргет в мете и гугле.; "
                        "Получать реальный результат, а не просто красивые цифры.; "
                        "Я маркетолог и наставник с 5-и летним международным опытом в Европе и США в продвижении, смм и рекламе.; "
                        "Работаю без предоплат, но только с теми проектами, где вижу потенциал."
                    ),
                    "product_row_category": "Digital и дизайн",
                    "product_row_contact": "@example_question_contact",
                    "contact_candidate_display": "@example_question_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_question_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_question_contact"],
                    "freshness_at_utc": "2026-04-23T10:00:00Z",
                    "last_seen_at_utc": "2026-04-23T10:00:00Z",
                },
                "publish",
                "Маркетинг и продвижение",
            ),
            (
                "5042",
                {
                    "latest_post_url": "https://t.me/example_source_alpha/5042",
                    "source_anchor_text": "@example_source_alpha/5042",
                    "category_primary": "psychology",
                    "service_tags": ["psychology", "therapy", "consultation"],
                    "title_best": "дипломированный психолог с опытом работы более двух лет.",
                    "description_best": "Работаю в интегративном подходе.; Работаю офлайн в Белграде и онлайн по всему миру.; Первая 30-минутная сессия-знакомство бесплатно.",
                    "service_name_candidate": "дипломированный психолог с опытом работы более двух лет.",
                    "details_candidate": "Работаю в интегративном подходе.; Работаю офлайн в Белграде и онлайн по всему миру.; Первая 30-минутная сессия-знакомство бесплатно.",
                    "product_row_service_name": "дипломированный психолог с опытом работы более двух лет.",
                    "product_row_details": "Работаю в интегративном подходе.; Работаю офлайн в Белграде и онлайн по всему миру.; Первая 30-минутная сессия-знакомство бесплатно.",
                    "product_row_category": "Психология",
                    "product_row_contact": "@example_psychologist_contact",
                    "contact_candidate_display": "@example_psychologist_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_psychologist_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_psychologist_contact"],
                    "freshness_at_utc": "2026-04-18T10:00:00Z",
                    "last_seen_at_utc": "2026-04-18T10:00:00Z",
                },
                "publish",
                "Консультация психолога",
            ),
            (
                "5045",
                {
                    "latest_post_url": "https://t.me/example_source_alpha/5045",
                    "source_anchor_text": "@example_source_alpha/5045",
                    "category_primary": "construction_repair",
                    "service_tags": ["cleaning", "air_conditioner", "master"],
                    "title_best": "Грязный кондиционер — это бактерии.",
                    "description_best": "Разберем до основания: снимем кожух, турбину и фильтры.; Тотально очистим.; Удалим заразу на 100%.",
                    "service_name_candidate": "Грязный кондиционер — это бактерии.",
                    "details_candidate": "Разберем до основания: снимем кожух, турбину и фильтры.; Тотально очистим.; Удалим заразу на 100%.",
                    "product_row_service_name": "Грязный кондиционер — это бактерии.",
                    "product_row_details": "Разберем до основания: снимем кожух, турбину и фильтры.; Тотально очистим.; Удалим заразу на 100%.",
                    "product_row_category": "Ремонт и монтаж",
                    "product_row_contact": "@example_handyman_contact",
                    "contact_candidate_display": "@example_handyman_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_handyman_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_handyman_contact"],
                    "freshness_at_utc": "2026-04-19T10:00:00Z",
                    "last_seen_at_utc": "2026-04-19T10:00:00Z",
                },
                "publish",
                "Обслуживание кондиционеров",
            ),
            (
                "5091",
                {
                    "latest_post_url": "https://t.me/example_source_alpha/5091",
                    "source_anchor_text": "@example_source_alpha/5091",
                    "category_primary": "construction_repair",
                    "service_tags": ["master", "repair", "cleaning"],
                    "title_best": "Надежный мастер в Белграде.",
                    "description_best": "Услуги муж на час.; Мойка кондиционера.; Универсальный мастер.",
                    "service_name_candidate": "Надежный мастер в Белграде.",
                    "details_candidate": "Услуги муж на час.; Мойка кондиционера.; Универсальный мастер.",
                    "product_row_service_name": "Надежный мастер в Белграде.",
                    "product_row_details": "Услуги муж на час.; Мойка кондиционера.; Универсальный мастер.",
                    "product_row_category": "Ремонт и монтаж",
                    "product_row_contact": "@example_belgrade_master",
                    "contact_candidate_display": "@example_belgrade_master",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_belgrade_master"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_belgrade_master"],
                    "freshness_at_utc": "2026-04-23T10:00:00Z",
                    "last_seen_at_utc": "2026-04-23T10:00:00Z",
                },
                "publish",
                "Мастер на час",
            ),
        ]

        for anchor, overrides, expected_decision, expected_service_name in cases:
            with self.subTest(anchor=anchor):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], expected_decision)
                self.assertEqual(row["service_name"], expected_service_name)
                if expected_decision == "drop":
                    self.assertEqual(row["details"], "")
                    self.assertEqual(row["source"], "")
                self.assertNotIn("сертифицированный мастер", row["service_name"].lower())
                self.assertNotIn("надежный мастер", row["service_name"].lower())
                self.assertNotIn("breeze", row["service_name"].lower())
                self.assertNotIn("грязный кондиционер", row["service_name"].lower())
                self.assertNotIn("делать продажи", row["service_name"].lower())
                self.assertNotIn("личный бренд", row["service_name"].lower())
                self.assertNotIn("могу помочь", row["details"].lower())
                self.assertNotIn("скидка", row["details"].lower())
                self.assertNotIn("подарок", row["details"].lower())

    def test_publishable_row_drops_new_live_goods_sale_family(self) -> None:
        cases = [
            (
                "5092",
                {
                    "latest_post_url": "https://t.me/example_source_alpha/5092",
                    "source_anchor_text": "@example_source_alpha/5092",
                    "category_primary": "food_hospitality",
                    "service_tags": ["food", "dessert", "caramel"],
                    "product_row_service_name": "Варю ту самую соленую карамель по которой вы соскучились.",
                    "product_row_details": "Она идеальна к блинам, тостам или просто ложкой из банки.; Пишите для заказа.; Нови Сад и Нови Белград самовывоз.",
                    "product_row_category": "Еда и гостеприимство",
                    "product_row_contact": "@example_bakery_contact",
                    "contact_candidate_display": "@example_bakery_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_bakery_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_bakery_contact"],
                    "freshness_at_utc": "2026-04-23T10:00:00Z",
                    "last_seen_at_utc": "2026-04-23T10:00:00Z",
                },
            ),
        ]

        for anchor, overrides in cases:
            with self.subTest(anchor=anchor):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["service_name"], "")
                self.assertEqual(row["source"], "")

    def test_publishable_row_cleans_list_intro_live_service_label_family(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_gamma/40544",
            source_anchor_text="@example_source_gamma/40544",
            category_primary="beauty_hair",
            service_tags=["beauty_hair", "биозавивка", "окрашивание"],
            product_row_service_name="Выполняю все виды окрашиваний: от глубоких натуральных тонов до сложных блондов , биозавивка",
            product_row_details=(
                "все виды стрижек: мужские, женские и детские; "
                "Добро пожаловать — буду рада создать для вас образ, в котором вы почувствуете себя ещё прекраснее; "
                "консультация бесплатно"
            ),
            product_row_category="Красота и здоровье",
            product_row_contact="@example_hair_contact",
            contact_candidate_display="@example_hair_contact",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_hair_contact"],
            contact_snapshot_telegram_links=["https://t.me/example_hair_contact"],
            freshness_at_utc="2026-04-22T20:26:07Z",
            last_seen_at_utc="2026-04-22T20:26:07Z",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Окрашивание и биозавивка")
        self.assertEqual(
            row["details"],
            "Все виды стрижек: мужские, женские и детские; Консультация бесплатно; От глубоких натуральных тонов до сложных блондов",
        )
        self.assertEqual(row["source"], "https://t.me/example_source_gamma/40544")
        self.assertEqual(row["actual_on"], "22.04.2026")
        self.assertNotIn("все виды окрашиваний", row["service_name"].lower())
        self.assertNotIn("добро пожаловать", row["details"].lower())
        self.assertNotIn("буду рада", row["details"].lower())

    def test_publishable_row_drops_new_live_non_service_family(self) -> None:
        cases = [
            (
                "40561",
                {
                    "latest_post_url": "https://t.me/example_source_gamma/40561",
                    "source_anchor_text": "@example_source_gamma/40561",
                    "category_primary": "construction_repair",
                    "service_tags": ["repair", "electrician", "plumber"],
                    "product_row_service_name": "Мастер на все руки, я предлагаю свои услуги по бытовому ремонту и прочим мелким работам.",
                    "product_row_details": (
                        "Ремонт бойлеров; Чистка бойлера; Любой вопрос с ремонтом помогу решить быстро; "
                        "Услуги электрика — ремонт и установка выключателей и розеток, замена автоматов и пускателей; "
                        "Услуги сантехника — устраню засоры и протечки труб; "
                        "Услуги домашнего мастера — любые перфораторные работы, установка полок и шкафов, сборка мебели"
                    ),
                    "product_row_category": "Ремонт и монтаж",
                    "product_row_contact": "@example_repair_belgrade",
                    "contact_candidate_display": "@example_repair_belgrade",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_repair_belgrade"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_repair_belgrade"],
                    "freshness_at_utc": "2026-04-22T22:08:14Z",
                    "last_seen_at_utc": "2026-04-22T22:08:14Z",
                },
            ),
            (
                "70168",
                {
                    "latest_post_url": "https://t.me/example_source_beta/70168",
                    "source_anchor_text": "@example_source_beta/70168",
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["haircut", "barbershop"],
                    "product_row_service_name": "Барбершоп на Ватерфронте ищет моделей для пополнения портфолио мастеров",
                    "product_row_details": (
                        "Делаем стильные стрижки и оформляем бороду; Крутой результат бесплатно, за наш счёт; "
                        "От тебя — прийти вовремя и быть готовым к съёмке"
                    ),
                    "product_row_category": "Красота и здоровье",
                    "product_row_contact": "+381600000005",
                    "contact_candidate_display": "+381600000005",
                    "contact_snapshot_phones": ["381600000005"],
                    "contact_snapshot_telegram_handles": [],
                    "contact_snapshot_telegram_links": [],
                    "freshness_at_utc": "2026-04-22T10:00:00Z",
                    "last_seen_at_utc": "2026-04-22T10:00:00Z",
                },
            ),
            (
                "3358",
                {
                    "latest_post_url": "https://t.me/example_source_zeta/3358",
                    "source_anchor_text": "@example_source_zeta/3358",
                    "category_primary": "",
                    "service_tags": ["middle"],
                    "product_row_service_name": "Ищем моделей на маникюр с покрытием гель-лак для портфолио для мастера маникюра (уровень middle) 10 апреля (пятница) и",
                    "product_row_details": "Подберем удобное время.; Оплата 1500 за расходные материалы 🙌; Занятость 3 часа 🙏",
                    "product_row_category": "",
                    "product_row_contact": "@example_beauty_contact",
                    "contact_candidate_display": "@example_beauty_contact",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_beauty_contact", "example_source_zeta"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_beauty_contact", "https://t.me/example_source_zeta"],
                    "freshness_at_utc": "2026-04-08T09:15:40Z",
                    "last_seen_at_utc": "2026-04-08T09:15:40Z",
                },
            ),
            (
                "2015",
                {
                    "latest_post_url": "https://t.me/example_source_delta/2015",
                    "source_anchor_text": "@example_source_delta/2015",
                    "category_primary": "it_digital",
                    "service_tags": ["marketplace"],
                    "product_row_service_name": "Приветствуем в группах самой высокотехнологичной площадки объявлений в Сербии и на всём Балканском полуострове",
                    "product_row_details": "Сайт: AreaSell.example.invalid; Найдите всё что нужно или опубликуйте своё; Сербия все группы: https://t.me/example_serbia_global",
                    "product_row_category": "Digital и дизайн",
                    "product_row_contact": "https://t.me/example_serbia_global",
                    "contact_candidate_display": "https://t.me/example_serbia_global",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": [],
                    "contact_snapshot_telegram_links": [],
                    "contact_snapshot_websites": ["https://example.invalid/areasell"],
                    "freshness_at_utc": "2026-04-17T10:00:00Z",
                    "last_seen_at_utc": "2026-04-17T10:00:00Z",
                },
            ),
            (
                "1978",
                {
                    "latest_post_url": "https://t.me/example_source_delta/1978",
                    "source_anchor_text": "@example_source_delta/1978",
                    "category_primary": "construction_repair",
                    "service_tags": ["construction_repair"],
                    "product_row_service_name": "Требуются мастера: арматурщики, бетонщики (опалубщики) и кузнецы (металлисты).",
                    "product_row_details": "Для арматурщиков: 10 евро за квадратный метр; Для бетонщиков и опалубщиков: 70 евро в день; Писать только тем, кто умеет работать и имеет опыт.",
                    "product_row_category": "Ремонт и монтаж",
                    "product_row_contact": "@example_contact_theta",
                    "contact_candidate_display": "@example_contact_theta",
                    "contact_snapshot_phones": [],
                    "contact_snapshot_telegram_handles": ["example_contact_theta"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_contact_theta"],
                    "freshness_at_utc": "2026-04-17T15:19:06Z",
                    "last_seen_at_utc": "2026-04-17T15:19:06Z",
                },
            ),
        ]

        for anchor, overrides in cases:
            with self.subTest(anchor=anchor):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["service_name"], "")
                self.assertEqual(row["source"], "")
                self.assertNotEqual(row["audit_reason"], "deterministic_fact_pack_draft")


    def test_publishable_row_drops_live_cv_anchor_without_source_specific_hardcode(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_delta/2003",
            source_anchor_text="@example_source_delta/2003",
            category_primary="it_digital",
            service_tags=["backend", "go", "nextjs"],
            product_row_service_name="Junior+/Middle Backend разработчик с 2 годами опыта на Go и 1 годом на Js/React/NextJs.",
            product_row_details="Junior+/Middle Backend разработчик с 2 годами опыта на Go и 1 годом на Js/React/NextJs. #CV #ищуработу",
            product_row_category="Digital и дизайн",
            product_row_contact="@example_contact_burkov",
            contact_candidate_display="@example_contact_burkov",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_contact_burkov"],
            contact_snapshot_telegram_links=["https://t.me/example_contact_burkov"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_non_service")
        self.assertEqual(row["source"], "")

    def test_publishable_row_drops_live_resale_anchor_without_goods_leakage(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_beta/70136",
            source_anchor_text="@example_source_beta/70136",
            category_primary="construction_repair",
            service_tags=[],
            product_row_service_name="Продаются светильники",
            product_row_details="Продаются светильники для дома и офиса, новые, пишите в личку.",
            product_row_category="Ремонт и монтаж",
            product_row_contact="@example_seller_lights",
            contact_candidate_display="@example_seller_lights",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_seller_lights"],
            contact_snapshot_telegram_links=["https://t.me/example_seller_lights"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_resale_dump")
        self.assertEqual(row["category"], "")

    def test_publishable_row_drops_live_platform_promo_anchor(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_delta/1867",
            source_anchor_text="@example_source_delta/1867",
            category_primary="it_digital",
            service_tags=["it_digital", "1ctwdrifkg", "1cufh4zuh9", "com", "facebook", "share", "www"],
            product_row_service_name="Хотите привлечь новую аудиторию без вложений в бюджет? У нас есть отличное предложение для взаимовыгодного",
            product_row_details="Что мы предлагаем; Что требуется от вас; Всего одно простое действие — сделать репост записи с информацией о нашем проекте к себе в группу или на личную страницу в любой социальной сети.",
            product_row_category="Digital и дизайн",
            product_row_contact="@example_contact_gamma",
            contact_candidate_display="@example_contact_gamma",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_contact_gamma"],
            contact_snapshot_telegram_links=["https://t.me/example_contact_gamma"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertIn(row["audit_reason"], {"publishable_non_service", "publishable_missing_service_name"})
        self.assertEqual(row["contact"], "")

    def test_publishable_row_corrects_live_gross_category_mismatch_even_when_deterministic_primary_matches(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_gamma/40538",
            source_anchor_text="@example_source_gamma/40538",
            category_primary="cleaning",
            service_tags=["cleaning", "construction_repair", "moving_delivery", "apple", "macbook", "macos", "ram", "ssd", "windows"],
            product_row_service_name="Произвожу ремонт и обслуживание техники Apple и Windows ноутбуков в короткие сроки, также работаю по выходным.",
            product_row_details="1. Первичная диагностика бесплатно; 2. Замена экранов, аккумуляторов, клавиатур и других комплектующих; 3. Полная чистка внутри и снаружи, замена термопасты, устранение шума",
            product_row_category="Уборка и химчистка",
            product_row_contact="+381600000006",
            contact_candidate_display="+381600000006",
            contact_snapshot_phones=["381600000006"],
            contact_snapshot_telegram_handles=["example_dima_serbia", "laptopserbia"],
            contact_snapshot_telegram_links=[],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Ремонт и обслуживание техники Apple и Windows ноутбуков")
        self.assertEqual(
            row["details"],
            "Первичная диагностика бесплатно; Замена экранов, аккумуляторов, клавиатур и других комплектующих; Полная чистка внутри и снаружи, замена термопасты, устранение шума",
        )
        self.assertEqual(row["category"], "Ремонт и монтаж")
        self.assertEqual(row["source"], "https://t.me/example_source_gamma/40538")
        self.assertEqual(row["phone"], "+381600000006")
        self.assertEqual(row["telegram"], "@example_dima_serbia")
        self.assertNotIn("короткие сроки", row["service_name"].lower())
        self.assertNotIn("работаю по выходным", row["details"].lower())

    def test_publishable_row_keeps_previous_cleaning_structure_anchors_publishable(self) -> None:
        cases = [
            (
                "5060",
                {
                    "latest_post_url": "https://t.me/example_source_alpha/5060",
                    "source_anchor_text": "@example_source_alpha/5060",
                    "category_primary": "auto_service",
                    "service_tags": ["auto_service", "cleaning", "авто"],
                    "title_best": "Химчистка мебели, ковров, КЛИНИНГ и химчистка авто! 🚗🛋️",
                    "description_best": "Верну вашей мебели, коврам и салону автомобиля былую чистоту!; Мои преимущества; Приезжаю с чистым оборудованием !!!",
                    "service_name_candidate": "Химчистка мебели, ковров, КЛИНИНГ и химчистка авто! 🚗🛋️",
                    "details_candidate": "Верну вашей мебели, коврам и салону автомобиля былую чистоту!; Мои преимущества; Приезжаю с чистым оборудованием !!!",
                    "product_row_service_name": "Химчистка мебели, ковров, КЛИНИНГ и химчистка авто! 🚗🛋️",
                    "product_row_details": "Верну вашей мебели, коврам и салону автомобиля былую чистоту!; Мои преимущества; Приезжаю с чистым оборудованием !!!",
                    "product_row_category": "Автоуслуги",
                    "product_row_contact": "+0621503290",
                    "contact_candidate_display": "+0621503290",
                    "contact_snapshot_phones": ["0621503290", "0628471849"],
                    "contact_snapshot_telegram_handles": ["example_auto_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_auto_contact"],
                    "freshness_at_utc": "2026-04-20T10:00:00Z",
                    "last_seen_at_utc": "2026-04-20T10:00:00Z",
                },
                "Химчистка мебели, ковров, клининг и химчистка авто",
                "Верну вашей мебели, коврам и салону автомобиля былую чистоту; Приезжаю с чистым оборудованием",
            ),
            (
                "5081",
                {
                    "latest_post_url": "https://t.me/example_source_alpha/5081",
                    "source_anchor_text": "@example_source_alpha/5081",
                    "category_primary": "auto_service",
                    "service_tags": ["auto_service", "cleaning", "авто"],
                    "city_display_names": ["Novi Sad"],
                    "title_best": "ЧИСТКА И ДЕЗИНФЕКЦИЯ – ЛЕГКО И С ЛЮБОВЬЮ!",
                    "description_best": (
                        "Алексей из Нови-Сада и с удовольствием помогу сделать ваш дом и авто снова свежими; "
                        "Химчистка мягкой мебели, кресел, стульев, штор и матрасов; "
                        "Чистка и дезинфекция салонов автомобилей"
                    ),
                    "service_name_candidate": "ЧИСТКА И ДЕЗИНФЕКЦИЯ – ЛЕГКО И С ЛЮБОВЬЮ!",
                    "details_candidate": (
                        "Алексей из Нови-Сада и с удовольствием помогу сделать ваш дом и авто снова свежими; "
                        "Химчистка мягкой мебели, кресел, стульев, штор и матрасов; "
                        "Чистка и дезинфекция салонов автомобилей"
                    ),
                    "product_row_service_name": "ЧИСТКА И ДЕЗИНФЕКЦИЯ – ЛЕГКО И С ЛЮБОВЬЮ!",
                    "product_row_details": (
                        "Алексей из Нови-Сада и с удовольствием помогу сделать ваш дом и авто снова свежими; "
                        "Химчистка мягкой мебели, кресел, стульев, штор и матрасов; "
                        "Чистка и дезинфекция салонов автомобилей"
                    ),
                    "product_row_category": "Автоуслуги",
                    "product_row_contact": "+381600000007",
                    "contact_candidate_display": "+381600000007",
                    "contact_snapshot_phones": ["381600000007"],
                    "contact_snapshot_telegram_handles": ["example_auto_mats_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_auto_mats_contact"],
                    "freshness_at_utc": "2026-04-22T10:00:00Z",
                    "last_seen_at_utc": "2026-04-22T10:00:00Z",
                },
                "Чистка и дезинфекция",
                "Химчистка мягкой мебели, кресел, стульев, штор и матрасов; Чистка и дезинфекция салонов автомобилей",
            ),
        ]

        for anchor, overrides, expected_service, expected_details in cases:
            with self.subTest(anchor=anchor):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["service_name"], expected_service)
                self.assertEqual(row["details"], expected_details)
                self.assertEqual(row["source"], overrides["latest_post_url"])
                self.assertNotIn("легко и с любовью", row["service_name"].lower())
                self.assertNotIn("мои преимущества", row["details"].lower())

    def test_publishable_row_cleans_live_anchor_with_price_and_location_tail(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_beta/70193",
            source_anchor_text="@example_source_beta/70193",
            category_primary="moving_delivery",
            service_tags=["moving", "delivery", "cargo"],
            city_display_names=["Belgrade"],
            title_best="Грузоперевозки по Белграду и Сербии от 4000 динар.",
            description_best="",
            service_name_candidate="Грузоперевозки по Белграду и Сербии от 4000 динар.",
            details_candidate="",
            price_text_best="4000 динар",
            price_min=4000,
            price_max=4000,
            currency_code="rsd",
            product_row_service_name="Грузоперевозки по Белграду и Сербии от 4000 динар.",
            product_row_details="",
            product_row_category="Переезды и доставка",
            product_row_contact="@example_cargo_move",
            contact_candidate_display="@example_cargo_move",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_cargo_move"],
            contact_snapshot_telegram_links=["https://t.me/example_cargo_move"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Грузоперевозки")
        self.assertEqual(row["details"], "По Белграду и Сербии")
        self.assertEqual(row["price"], "4000 rsd")
        self.assertEqual(row["source"], "https://t.me/example_source_beta/70193")
        self.assertEqual(row["telegram"], "@example_cargo_move")
        self.assertNotIn("белграду", row["service_name"].lower())
        self.assertNotIn("динар", row["service_name"].lower())

    def test_publishable_row_infers_device_repair_category_when_product_category_blank(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_services/901",
            source_anchor_text="@example_services/901",
            category_primary="",
            service_tags=["repair", "laptop", "computer"],
            title_best="Ремонт ноутбуков и компьютеров",
            description_best="Диагностика, замена клавиатур, экранов и комплектующих, установка Windows.",
            service_name_candidate="Ремонт ноутбуков и компьютеров",
            details_candidate="Диагностика, замена клавиатур, экранов и комплектующих, установка Windows.",
            product_row_service_name="Ремонт ноутбуков и компьютеров",
            product_row_details="Диагностика, замена клавиатур, экранов и комплектующих, установка Windows.",
            product_row_category="",
            product_row_contact="@example_computer_master",
            contact_candidate_display="@example_computer_master",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_computer_master"],
            contact_snapshot_telegram_links=["https://t.me/example_computer_master"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["category"], "Ремонт и монтаж")

    def test_publishable_row_preserves_serbian_thousands_price_from_text(self) -> None:
        offer = _build_offer(
            category_primary="moving_delivery",
            service_tags=["moving", "delivery"],
            title_best="Доставка и перевозка вещей",
            description_best="Помогу перевезти вещи по Белграду. Цена 3.000 rsd.",
            service_name_candidate="Доставка и перевозка вещей",
            details_candidate="Помогу перевезти вещи по Белграду. Цена 3.000 rsd.",
            price_text_best="3.000 rsd",
            price_min=None,
            price_max=None,
            currency_code="",
            price_candidate_text="3.000 rsd",
            product_row_service_name="Доставка и перевозка вещей",
            product_row_details="Помогу перевезти вещи по Белграду.",
            product_row_category="Переезды и доставка",
            product_row_contact="@example_cargo_move",
            contact_candidate_display="@example_cargo_move",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_cargo_move"],
            contact_snapshot_telegram_links=["https://t.me/example_cargo_move"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["price"], "3000 rsd")

    def test_publishable_row_repairs_collapsed_serbian_thousands_price_from_raw_text(self) -> None:
        offer = _build_offer(
            category_primary="moving_delivery",
            service_tags=["moving", "delivery"],
            title_best="Доставка и перевозка вещей",
            description_best="Помогу перевезти вещи по Белграду. Цена 3.000 rsd.",
            service_name_candidate="Доставка и перевозка вещей",
            details_candidate="Помогу перевезти вещи по Белграду. Цена 3.000 rsd.",
            price_text_best="3.000 rsd",
            price_min=3,
            price_max=3,
            currency_code="rsd",
            price_candidate_text="",
            product_row_service_name="Доставка и перевозка вещей",
            product_row_details="Помогу перевезти вещи по Белграду. Цена 3.000 rsd.",
            product_row_category="Переезды и доставка",
            product_row_contact="@example_cargo_move",
            contact_candidate_display="@example_cargo_move",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_cargo_move"],
            contact_snapshot_telegram_links=["https://t.me/example_cargo_move"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["price"], "3000 rsd")

    def test_publishable_row_corrects_current_full_cell_audit_category_families(self) -> None:
        cases = [
            (
                "dessert_blank",
                {
                    "category_primary": "",
                    "service_tags": ["dessert", "cake"],
                    "title_best": "Cheesecake",
                    "description_best": "Домашний cheesecake, десерты и торты на заказ.",
                    "service_name_candidate": "Cheesecake",
                    "details_candidate": "Домашний cheesecake, десерты и торты на заказ.",
                    "product_row_service_name": "Cheesecake",
                    "product_row_details": "Домашний cheesecake, десерты и торты на заказ.",
                    "product_row_category": "",
                },
                "Еда и гостеприимство",
            ),
            (
                "cleaning_over_auto",
                {
                    "category_primary": "auto_service",
                    "service_tags": ["auto_service", "cleaning"],
                    "title_best": "Химчистка мебели, ковров, клининг и химчистка авто",
                    "description_best": "Химчистка мягкой мебели и салонов автомобилей, чистое оборудование.",
                    "service_name_candidate": "Химчистка мебели, ковров, клининг и химчистка авто",
                    "details_candidate": "Химчистка мягкой мебели и салонов автомобилей, чистое оборудование.",
                    "product_row_service_name": "Химчистка мебели, ковров, клининг и химчистка авто",
                    "product_row_details": "Химчистка мягкой мебели и салонов автомобилей, чистое оборудование.",
                    "product_row_category": "Автоуслуги",
                },
                "Уборка и химчистка",
            ),
            (
                "pedicure_blank",
                {
                    "category_primary": "",
                    "service_tags": ["pedicure", "beauty"],
                    "title_best": "Medicinski pedikir na kućnoj adresi",
                    "description_best": "Medicinski pedikir na kućnoj adresi za Beograd i Novi Sad.",
                    "service_name_candidate": "Medicinski pedikir na kućnoj adresi",
                    "details_candidate": "Medicinski pedikir na kućnoj adresi za Beograd i Novi Sad.",
                    "product_row_service_name": "Medicinski pedikir na kućnoj adresi",
                    "product_row_details": "Medicinski pedikir na kućnoj adresi za Beograd i Novi Sad.",
                    "product_row_category": "",
                },
                "Красота и здоровье",
            ),
            (
                "docs_over_auto",
                {
                    "category_primary": "auto_service",
                    "service_tags": ["auto_service", "legal_docs"],
                    "title_best": "ВНЖ в Сербии",
                    "description_best": "Помощь с документами, подача на ВНЖ, консультации по легализации.",
                    "service_name_candidate": "ВНЖ в Сербии",
                    "details_candidate": "Помощь с документами, подача на ВНЖ, консультации по легализации.",
                    "product_row_service_name": "ВНЖ в Сербии",
                    "product_row_details": "Помощь с документами, подача на ВНЖ, консультации по легализации.",
                    "product_row_category": "Автоуслуги",
                },
                "Документы и право",
            ),
            (
                "visa_run_over_auto",
                {
                    "category_primary": "auto_service",
                    "service_tags": ["visa", "documents"],
                    "title_best": "Быстрый визаран",
                    "description_best": "Помощь с визараном, документами и легальным въездом.",
                    "service_name_candidate": "Быстрый визаран",
                    "details_candidate": "Помощь с визараном, документами и легальным въездом.",
                    "product_row_service_name": "Быстрый визаран",
                    "product_row_details": "Помощь с визараном, документами и легальным въездом.",
                    "product_row_category": "Автоуслуги",
                },
                "Документы и право",
            ),
            (
                "self_care_method_over_psychology",
                {
                    "category_primary": "psychology",
                    "service_tags": ["beauty", "self-care"],
                    "title_best": "Метод ухода за лицом",
                    "description_best": "Самомассаж, уход за кожей и мягкая работа с лицом.",
                    "service_name_candidate": "Метод ухода за лицом",
                    "details_candidate": "Самомассаж, уход за кожей и мягкая работа с лицом.",
                    "product_row_service_name": "Метод ухода за лицом",
                    "product_row_details": "Самомассаж, уход за кожей и мягкая работа с лицом.",
                    "product_row_category": "Психология",
                },
                "Красота и здоровье",
            ),
            (
                "passenger_transfer",
                {
                    "category_primary": "moving_delivery",
                    "service_tags": ["moving", "transfer"],
                    "title_best": "Перевозка пассажиров и багажа по всей Сербии",
                    "description_best": "Трансфер, пассажирские перевозки и багаж по всей Сербии.",
                    "service_name_candidate": "Перевозка пассажиров и багажа по всей Сербии",
                    "details_candidate": "Трансфер, пассажирские перевозки и багаж по всей Сербии.",
                    "product_row_service_name": "Перевозка пассажиров и багажа по всей Сербии",
                    "product_row_details": "Трансфер, пассажирские перевозки и багаж по всей Сербии.",
                    "product_row_category": "Переезды и доставка",
                },
                "Переезды и доставка",
            ),
            (
                "marketing_over_education",
                {
                    "category_primary": "education_tutoring",
                    "service_tags": ["marketing", "promotion"],
                    "title_best": "Маркетинг и продвижение",
                    "description_best": "Маркетинг, реклама и продвижение проектов в социальных сетях.",
                    "service_name_candidate": "Маркетинг и продвижение",
                    "details_candidate": "Маркетинг, реклама и продвижение проектов в социальных сетях.",
                    "product_row_service_name": "Маркетинг и продвижение",
                    "product_row_details": "Маркетинг, реклама и продвижение проектов в социальных сетях.",
                    "product_row_category": "Обучение",
                },
                "Digital и дизайн",
            ),
            (
                "master_over_cleaning",
                {
                    "category_primary": "cleaning",
                    "service_tags": ["construction_repair", "master"],
                    "title_best": "Мастер на час в Белграде",
                    "description_best": "Мелкий ремонт, монтаж, сантехника и электрика по дому.",
                    "service_name_candidate": "Мастер на час в Белграде",
                    "details_candidate": "Мелкий ремонт, монтаж, сантехника и электрика по дому.",
                    "product_row_service_name": "Мастер на час в Белграде",
                    "product_row_details": "Мелкий ремонт, монтаж, сантехника и электрика по дому.",
                    "product_row_category": "Уборка и химчистка",
                },
                "Ремонт и монтаж",
            ),
            (
                "computer_master_over_cleaning",
                {
                    "category_primary": "cleaning",
                    "service_tags": ["computer", "repair", "master"],
                    "title_best": "Компьютерный мастер",
                    "description_best": "Ремонт ноутбуков, диагностика, замена клавиатур и установка Windows.",
                    "service_name_candidate": "Компьютерный мастер",
                    "details_candidate": "Ремонт ноутбуков, диагностика, замена клавиатур и установка Windows.",
                    "product_row_service_name": "Компьютерный мастер",
                    "product_row_details": "Ремонт ноутбуков, диагностика, замена клавиатур и установка Windows.",
                    "product_row_category": "Уборка и химчистка",
                },
                "Ремонт и монтаж",
            ),
            (
                "aircon_cleaning_over_repair",
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["cleaning", "air_conditioner"],
                    "title_best": "Чистка кондиционеров",
                    "description_best": "Чистка фильтров, мойка турбин и дезинфекция кондиционеров.",
                    "service_name_candidate": "Чистка кондиционеров",
                    "details_candidate": "Чистка фильтров, мойка турбин и дезинфекция кондиционеров.",
                    "product_row_service_name": "Чистка кондиционеров",
                    "product_row_details": "Чистка фильтров, мойка турбин и дезинфекция кондиционеров.",
                    "product_row_category": "Ремонт и монтаж",
                },
                "Уборка и химчистка",
            ),
            (
                "auto_import_over_delivery",
                {
                    "category_primary": "moving_delivery",
                    "service_tags": ["auto", "import"],
                    "title_best": "Пригон авто под ключ из Европы",
                    "description_best": "Подбор, покупка и пригон автомобиля под ключ из Европы.",
                    "service_name_candidate": "Пригон авто под ключ из Европы",
                    "details_candidate": "Подбор, покупка и пригон автомобиля под ключ из Европы.",
                    "product_row_service_name": "Пригон авто под ключ из Европы",
                    "product_row_details": "Подбор, покупка и пригон автомобиля под ключ из Европы.",
                    "product_row_category": "Переезды и доставка",
                },
                "Автоуслуги",
            ),
        ]

        for anchor, overrides, expected_category in cases:
            with self.subTest(anchor=anchor):
                offer = _build_offer(
                    **overrides,
                    product_row_contact="@example_service_contact",
                    contact_candidate_display="@example_service_contact",
                    contact_snapshot_phones=[],
                    contact_snapshot_telegram_handles=["example_service_contact"],
                    contact_snapshot_telegram_links=["https://t.me/example_service_contact"],
                    contact_snapshot_emails=[],
                    contact_snapshot_websites=[],
                )

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], expected_category)

    def test_publishable_row_drops_laptop_resale_without_repair_service_signal(self) -> None:
        offer = _build_offer(
            category_primary="moving_delivery",
            service_tags=["laptop", "macbook", "ssd", "ram"],
            title_best="В продаже ноутбук",
            description_best="В продаже ноутбук MacBook Pro, 16 gb ram, 512 gb ssd, отличное состояние.",
            service_name_candidate="В продаже ноутбук",
            details_candidate="MacBook Pro, 16 gb ram, 512 gb ssd, отличное состояние.",
            product_row_service_name="В продаже ноутбук",
            product_row_details="MacBook Pro, 16 gb ram, 512 gb ssd, отличное состояние.",
            product_row_category="Переезды и доставка",
            product_row_contact="@example_seller_contact",
            contact_candidate_display="@example_seller_contact",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_seller_contact"],
            contact_snapshot_telegram_links=["https://t.me/example_seller_contact"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_resale_dump")

    def test_publishable_row_cleans_psychology_details_ad_dump_contact_family(self) -> None:
        offer = _build_offer(
            category_primary="psychology",
            service_tags=["psychology", "consultation"],
            title_best="Консультация психолога",
            description_best=(
                "Работаю в интегративном подходе (гуманистический, КПТ и др.).; "
                "Это значит, что мы подберём самые эффективные инструменты.; "
                "Работаю офлайн в Белграде и онлайн по всему миру.; "
                "Первая 30-минутная сессия-знакомство бесплатно.; "
                "Запись @example_psy_contact"
            ),
            service_name_candidate="Консультация психолога",
            details_candidate=(
                "Работаю в интегративном подходе (гуманистический, КПТ и др.).; "
                "Это значит, что мы подберём самые эффективные инструменты.; "
                "Работаю офлайн в Белграде и онлайн по всему миру.; "
                "Первая 30-минутная сессия-знакомство бесплатно.; "
                "Запись @example_psy_contact"
            ),
            product_row_service_name="Консультация психолога",
            product_row_details=(
                "Работаю в интегративном подходе (гуманистический, КПТ и др.).; "
                "Это значит, что мы подберём самые эффективные инструменты.; "
                "Работаю офлайн в Белграде и онлайн по всему миру.; "
                "Первая 30-минутная сессия-знакомство бесплатно.; "
                "Запись @example_psy_contact"
            ),
            product_row_category="Психология",
            product_row_contact="@example_psy_contact",
            contact_candidate_display="@example_psy_contact",
            contact_snapshot_phones=[],
            contact_snapshot_telegram_handles=["example_psy_contact"],
            contact_snapshot_telegram_links=["https://t.me/example_psy_contact"],
            contact_snapshot_emails=[],
            contact_snapshot_websites=[],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["category"], "Психология")
        self.assertEqual(row["details"], "Работаю в интегративном подходе (гуманистический, КПТ и др.).")
        self.assertNotIn("@example_psy_contact", row["details"])
        self.assertNotIn("сессия-знакомство", row["details"].lower())

    def test_publishable_row_drops_vehicle_result_headline_without_service_meaning(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_alpha/5040",
            source_anchor_text="@example_source_alpha/5040",
            category_primary="auto_service",
            service_tags=["auto_service", "2019г", "benz", "cls", "mercedes", "viber", "whatsapp"],
            title_best="Mercedes-Benz CLS 450 за 14 дней. Реально.",
            description_best=(
                "Проверили в Германии; комплексный осмотр кузова и ЛКП. Компьютерная диагностика. "
                "Тест-драйв. Фото/видео отчет с рекомендациями.; не передаю работу третьим лицам. "
                "Осмотр авто делаю сам. Именно поэтому я лично отвечаю за качество проверки перед вами."
            ),
            service_name_candidate="Mercedes-Benz CLS 450 за 14 дней. Реально.",
            details_candidate=(
                "Проверили в Германии; комплексный осмотр кузова и ЛКП. Компьютерная диагностика. "
                "Тест-драйв. Фото/видео отчет с рекомендациями.; не передаю работу третьим лицам. "
                "Осмотр авто делаю сам. Именно поэтому я лично отвечаю за качество проверки перед вами."
            ),
            product_row_service_name="Mercedes-Benz CLS 450 за 14 дней. Реально.",
            product_row_details=(
                "Проверили в Германии; комплексный осмотр кузова и ЛКП. Компьютерная диагностика. "
                "Тест-драйв. Фото/видео отчет с рекомендациями.; не передаю работу третьим лицам. "
                "Осмотр авто делаю сам. Именно поэтому я лично отвечаю за качество проверки перед вами."
            ),
            product_row_category="Автоуслуги",
            product_row_contact="+381600000008",
            price_text_best="29 400€",
            price_min=800,
            price_max=29400,
            currency_code="eur",
            contact_candidate_display="+381600000008",
            contact_snapshot_phones=["381600000008", "79510395888"],
            contact_snapshot_telegram_handles=["example_contact_omega"],
            contact_snapshot_telegram_links=["https://t.me/example_contact_omega"],
            explicit_contact_snapshot_phones=["381600000008", "79510395888"],
            explicit_contact_snapshot_telegram_handles=["example_contact_omega"],
            explicit_contact_snapshot_telegram_links=[],
            author_fallback_phones=["79510395888"],
            author_fallback_telegram_handles=["example_contact_omega"],
            author_fallback_telegram_links=["https://t.me/example_contact_omega"],
            freshness_at_utc="2026-04-17T13:23:38Z",
            last_seen_at_utc="2026-04-17T13:23:38Z",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["service_name"], "")
        self.assertEqual(row["details"], "")
        self.assertEqual(row["price"], "")
        self.assertEqual(row["source"], "")
        self.assertEqual(row["contact"], "")
        self.assertEqual(row["audit_reason"], "publishable_missing_service_name")

    def test_publishable_row_drops_inventory_availability_label_family(self) -> None:
        offer = _build_offer(
            category_primary="auto_service",
            service_tags=["auto", "sale", "inventory"],
            title_best="Автомобиль под заказ",
            description_best="Подбор вариантов и консультация по доступным комплектациям.",
            service_name_candidate="Автомобиль под заказ",
            details_candidate="Подбор вариантов и консультация по доступным комплектациям.",
            product_row_service_name="Нет нужной комплектации",
            product_row_details="Подбор вариантов и консультация по доступным комплектациям.",
            product_row_category="Автоуслуги",
            product_row_contact="@example_auto_helper",
            contact_candidate_display="@example_auto_helper",
            contact_snapshot_telegram_handles=["example_auto_helper"],
            contact_snapshot_telegram_links=["https://t.me/example_auto_helper"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["service_name"], "")
        self.assertEqual(row["details"], "")
        self.assertEqual(row["source"], "")
        self.assertEqual(row["audit_reason"], "publishable_missing_service_name")

    def test_publishable_row_cleans_live_auto_rental_promo_tail_family(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_source_beta/70201",
            source_anchor_text="@example_source_beta/70201",
            category_primary="auto_service",
            service_tags=["auto_service", "whatsapp", "автомобили", "автопарке", "акпп", "без", "бесплатно"],
            city_display_names=["Belgrade"],
            title_best="АРЕНДА АВТО В СЕРБИИ БЕЗ КРЕДИТНОЙ КАРТЫ — ПРОСТО И НАДЁЖНО",
            description_best=(
                "Работаем официально по Закону о туризме Сербии; "
                "Статья 106: только автомобили не старше 5 лет (сейчас — от 2021 года), в автопарке — более 5 новых авто; "
                "Компания официально зарегистрирована. Уже 3,5 года на рынке"
            ),
            service_name_candidate="АРЕНДА АВТО В СЕРБИИ БЕЗ КРЕДИТНОЙ КАРТЫ — ПРОСТО И НАДЁЖНО",
            details_candidate=(
                "Работаем официально по Закону о туризме Сербии; "
                "Статья 106: только автомобили не старше 5 лет (сейчас — от 2021 года), в автопарке — более 5 новых авто; "
                "Компания официально зарегистрирована. Уже 3,5 года на рынке"
            ),
            product_row_service_name="АРЕНДА АВТО В СЕРБИИ БЕЗ КРЕДИТНОЙ КАРТЫ — ПРОСТО И НАДЁЖНО",
            product_row_details=(
                "Работаем официально по Закону о туризме Сербии; "
                "Статья 106: только автомобили не старше 5 лет (сейчас — от 2021 года), в автопарке — более 5 новых авто; "
                "Компания официально зарегистрирована. Уже 3,5 года на рынке"
            ),
            product_row_category="Автоуслуги",
            product_row_contact="+381600000009",
            price_text_best="",
            price_min=None,
            price_max=None,
            currency_code="",
            price_candidate_text="",
            contact_candidate_display="+381600000009",
            contact_snapshot_phones=["381600000009"],
            contact_snapshot_telegram_handles=["example_novi_sad_rent", "example_rentacar_belgrade_novisad"],
            contact_snapshot_telegram_links=["https://t.me/example_rentacar_belgrade_novisad"],
            explicit_contact_snapshot_phones=["381600000009"],
            explicit_contact_snapshot_telegram_handles=["example_novi_sad_rent"],
            explicit_contact_snapshot_telegram_links=[],
            author_fallback_phones=[],
            author_fallback_telegram_handles=["example_rentacar_belgrade_novisad"],
            author_fallback_telegram_links=["https://t.me/example_rentacar_belgrade_novisad"],
            freshness_at_utc="2026-04-23T11:35:40Z",
            last_seen_at_utc="2026-04-23T11:35:40Z",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Аренда авто")
        self.assertEqual(
            row["details"],
            "Только автомобили не старше 5 лет (сейчас — от 2021 года), в автопарке — более 5 новых авто; Без кредитной карты; В сербии",
        )
        self.assertEqual(row["category"], "Автоуслуги")
        self.assertEqual(row["price"], "")
        self.assertEqual(row["phone"], "+381600000009")
        self.assertEqual(row["telegram"], "@example_novi_sad_rent")
        self.assertEqual(row["source"], "https://t.me/example_source_beta/70201")
        self.assertEqual(row["actual_on"], "23.04.2026")
        self.assertNotIn("кредитной карты", row["service_name"].lower())
        self.assertNotIn("просто", row["service_name"].lower())
        self.assertNotIn("надёжно", row["details"].lower())

    def test_vehicle_rental_deposit_insurance_requirement_terms_are_visible_service_context(self) -> None:
        offer = _build_offer(
            latest_post_url="https://t.me/example_rental_service/904",
            source_anchor_text="@example_rental_service/904",
            category_primary="auto_service",
            service_tags=["auto_service", "car rental", "citroen", "акпп", "дизель"],
            city_display_names=["Belgrade"],
            title_best="Аренда Citroen C3 (акпп, дизель)",
            description_best=(
                "Минимум 3 суток или помесячно.; "
                "Депозит и страховка требуются; "
                "Предоставим с полным баком."
            ),
            service_name_candidate="Аренда Citroen C3 (акпп, дизель)",
            details_candidate=(
                "Минимум 3 суток или помесячно.; "
                "Депозит и страховка требуются; "
                "Предоставим с полным баком."
            ),
            product_row_service_name="Аренда Citroen C3 (АКПП, дизель)",
            product_row_details=(
                "Минимум 3 суток или помесячно.; "
                "Депозит и страховка требуются; "
                "Предоставим с полным баком."
            ),
            product_row_category="Автоуслуги",
            product_row_contact="@example_rentacar",
            price_text_best="40 EUR",
            price_min=40,
            price_max=40,
            currency_code="eur",
            contact_candidate_display="@example_rentacar",
            contact_snapshot_telegram_handles=["example_rentacar"],
            contact_snapshot_telegram_links=["https://t.me/example_rentacar"],
            explicit_contact_snapshot_telegram_handles=["example_rentacar"],
            freshness_at_utc="2026-04-28T09:00:00Z",
            last_seen_at_utc="2026-04-28T09:00:00Z",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Аренда Citroen C3 (акпп, дизель)")
        self.assertEqual(row["category"], "Автоуслуги")
        self.assertEqual(row["price"], "40 eur")
        self.assertIn("Условия аренды: депозит и страховка", row["details"])
        self.assertNotIn("требуются", row["details"].lower())
        self.assertFalse(_looks_like_vacancy_or_cv(f"{row['service_name']} {row['details']}"))

    def test_vehicle_rental_hiring_context_stays_blocked_with_deposit_insurance_terms(self) -> None:
        offer = _build_offer(
            category_primary="auto_service",
            service_tags=["auto_service", "car rental", "hiring"],
            title_best="Требуется менеджер в rent-a-car",
            description_best=(
                "Ищем в команду менеджера по аренде авто; требования, обязанности, зарплата. "
                "Депозит и страховка требуются для оформления договоров клиентов."
            ),
            service_name_candidate="Требуется менеджер в rent-a-car",
            details_candidate=(
                "Ищем в команду менеджера по аренде авто; требования, обязанности, зарплата. "
                "Депозит и страховка требуются для оформления договоров клиентов."
            ),
            product_row_service_name="Менеджер в rent-a-car",
            product_row_details=(
                "Ищем в команду менеджера по аренде авто; требования, обязанности, зарплата. "
                "Депозит и страховка требуются для оформления договоров клиентов."
            ),
            product_row_category="Автоуслуги",
            product_row_contact="@example_contact_epsilon",
            contact_candidate_display="@example_contact_epsilon",
            contact_snapshot_telegram_handles=["example_contact_epsilon"],
            contact_snapshot_telegram_links=["https://t.me/example_contact_epsilon"],
            explicit_contact_snapshot_telegram_handles=["example_contact_epsilon"],
        )

        self.assertTrue(_looks_like_vacancy_or_cv(f"{offer['title_best']} {offer['details_candidate']}"))

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_non_service")

    def test_execution141_event_like_social_row_is_dropped_as_non_service(self) -> None:
        offer = _build_offer(
            category_primary="food_hospitality",
            service_tags=["bar", "event", "networking"],
            service_name_candidate="Неформальные знакомства",
            details_candidate="Вечер, где разговоры начинаются сами, а новые друзья появляются за коктейлем в баре.",
            product_row_service_name="Неформальные знакомства",
            product_row_details="Вечер, где разговоры начинаются сами; новые друзья появляются быстрее, чем вы успеваете допить коктейль; бар в центре.",
            product_row_category="",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_non_service")

    def test_broad_quality_drops_remaining_non_service_leakage_families(self) -> None:
        cases = [
            {
                "category_primary": "food_hospitality",
                "service_tags": ["event", "tickets"],
                "title_best": "Stand-up концерт комика в Белграде",
                "description_best": "Воскресенье, новый материал, истории и шутки, билеты по фиксированной цене.",
                "service_name_candidate": "Stand-up концерт комика в Белграде",
                "details_candidate": "Воскресенье; новый материал; много историй и шуток.",
                "product_row_service_name": "Stand-up концерт комика в Белграде",
                "product_row_details": "Воскресенье; новый материал; много историй и шуток.",
                "product_row_category": "Еда и гостеприимство",
            },
            {
                "category_primary": "legal_docs",
                "service_tags": ["residence", "legalization"],
                "title_best": "В 2026 году страна выдала россиянам больше ВНЖ и стала стабильным маршрутом легализации",
                "description_best": "Почему ВНЖ стал популярнее: решение быстро, без крупных инвестиций.",
                "service_name_candidate": "В 2026 году страна выдала россиянам больше ВНЖ и стала стабильным маршрутом легализации",
                "details_candidate": "Почему ВНЖ так популярен; без крупных инвестиций; решение быстро.",
                "product_row_service_name": "В 2026 году страна выдала россиянам больше ВНЖ и стала стабильным маршрутом легализации",
                "product_row_details": "Почему ВНЖ так популярен; без крупных инвестиций; решение быстро.",
                "product_row_category": "Документы и право",
            },
            {
                "category_primary": "",
                "service_tags": [],
                "title_best": "С Новым годом",
                "description_best": "Поздравляем, желаем радости и новых возможностей.",
                "service_name_candidate": "С Новым годом",
                "details_candidate": "Поздравляем, желаем радости и новых возможностей.",
                "product_row_service_name": "С Новым годом",
                "product_row_details": "Поздравляем, желаем радости и новых возможностей.",
                "product_row_category": "",
            },
            {
                "category_primary": "",
                "service_tags": [],
                "title_best": "С 8 Марта",
                "description_best": "Пусть каждый день приносит счастье, вдохновение и улыбки.",
                "service_name_candidate": "С 8 Марта",
                "details_candidate": "Пусть каждый день приносит счастье, вдохновение и улыбки.",
                "product_row_service_name": "С 8 Марта",
                "product_row_details": "Пусть каждый день приносит счастье, вдохновение и улыбки.",
                "product_row_category": "",
            },
            {
                "category_primary": "it_digital",
                "service_tags": ["moderation", "bot"],
                "title_best": "Недостаточно прав для блокировки пользователя за spam",
                "description_best": "Удаление сообщений может работать некорректно из-за технических настроек бота.",
                "service_name_candidate": "Недостаточно прав для блокировки пользователя за spam",
                "details_candidate": "Скрыть сообщения можно включив тихий режим в настройках бота.",
                "product_row_service_name": "Недостаточно прав для блокировки пользователя за spam",
                "product_row_details": "Скрыть сообщения можно включив тихий режим в настройках бота.",
                "product_row_category": "Digital и дизайн",
            },
        ]
        for overrides in cases:
            with self.subTest(service_name=overrides["product_row_service_name"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["audit_reason"], "publishable_non_service")

    def test_execution141_proforientation_consultation_gets_psychology_category_and_clean_details(self) -> None:
        offer = _build_offer(
            category_primary="",
            service_tags=["consultation", "career", "children"],
            service_name_candidate="Профориентационная консультация",
            details_candidate="Таланты, способности и профессии; Для женщин и их детей; Помогаю выбрать направление обучения.",
            product_row_service_name="Профориентационная консультация",
            product_row_details="Таланты, способности и профессии; Для женщин и их детей; Помогаю выбрать направление обучения.",
            product_row_category="",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["category"], "Психология")
        self.assertEqual(row["details"], "Помогаю выбрать направление обучения.")
        self.assertNotIn("таланты", row["details"].lower())
        self.assertNotIn("для женщин", row["details"].lower())

    def test_execution142_proforientation_rhetorical_intro_detail_is_blanked(self) -> None:
        offer = _build_offer(
            category_primary="psychology",
            service_tags=["consultation", "career", "children"],
            service_name_candidate="Профориентационная консультация",
            details_candidate="Помните, нас с детства спрашивали",
            product_row_service_name="Профориентационная консультация",
            product_row_details="Помните, нас с детства спрашивали",
            product_row_category="Психология",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["category"], "Психология")
        self.assertEqual(row["details"], "")
        self.assertNotIn("помните", row["details"].lower())

    def test_execution141_master_and_repair_rows_do_not_regress_to_cleaning(self) -> None:
        cases = [
            {
                "service_name_candidate": "Русский мастер",
                "details_candidate": "Ремонт, сборка мебели, мелкие бытовые работы и монтаж.",
                "product_row_service_name": "Русский мастер",
                "product_row_details": "Ремонт, сборка мебели, мелкие бытовые работы и монтаж.",
            },
            {
                "service_name_candidate": "Единая служба мастеров",
                "details_candidate": "Сантехник, электрик, ремонт и монтаж по дому.",
                "product_row_service_name": "Единая служба мастеров",
                "product_row_details": "Сантехник, электрик, ремонт и монтаж по дому.",
            },
            {
                "service_name_candidate": "Мастер на час",
                "details_candidate": "Мелкий ремонт, сборка мебели, установка полок и бытовой монтаж.",
                "product_row_service_name": "Мастер на час",
                "product_row_details": "Мелкий ремонт, сборка мебели, установка полок и бытовой монтаж.",
            },
        ]
        for overrides in cases:
            with self.subTest(service=overrides["product_row_service_name"]):
                offer = _build_offer(
                    category_primary="cleaning",
                    service_tags=["cleaning", "repair", "master"],
                    product_row_category="Уборка и химчистка",
                    **overrides,
                )

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], "Ремонт и монтаж")

    def test_execution142_mixed_master_rows_publish_as_repair_not_cleaning(self) -> None:
        cases = [
            {
                "service_name_candidate": "Русский мастер",
                "details_candidate": (
                    "Белград; Электрика, сантехника, отделка, ремонт бытовой техники, "
                    "чистка и дозаправка кондиционеров, чистка и ремонт бойлеров, сборка мебели."
                ),
                "product_row_service_name": "Русский мастер",
                "product_row_details": (
                    "Белград; Электрика, сантехника, отделка, ремонт бытовой техники, "
                    "чистка и дозаправка кондиционеров, чистка и ремонт бойлеров, сборка мебели."
                ),
            },
            {
                "service_name_candidate": "Единая служба мастеров",
                "details_candidate": (
                    "Химчистка мебели, ремонт бытовой техники, клининг, мастер на час, "
                    "устранение засоров, услуги маляров, мойка кондиционеров, ремонт ролет, окон и дверей."
                ),
                "product_row_service_name": "Единая служба мастеров",
                "product_row_details": (
                    "Химчистка мебели, ремонт бытовой техники, клининг, мастер на час, "
                    "устранение засоров, услуги маляров, мойка кондиционеров, ремонт ролет, окон и дверей."
                ),
            },
            {
                "service_name_candidate": "Мастер на час",
                "details_candidate": "Услуги муж на час; Мойка кондиционера; Универсальный мастер",
                "product_row_service_name": "Мастер на час",
                "product_row_details": "Услуги муж на час; Мойка кондиционера; Универсальный мастер",
            },
        ]
        for overrides in cases:
            with self.subTest(service=overrides["product_row_service_name"]):
                offer = _build_offer(
                    category_primary="cleaning",
                    service_tags=["cleaning", "master", "repair"],
                    product_row_category="Уборка и химчистка",
                    **overrides,
                )

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], "Ремонт и монтаж")

    def test_execution141_computer_master_keeps_repair_and_strips_laptop_resale_details(self) -> None:
        offer = _build_offer(
            category_primary="cleaning",
            service_tags=["cleaning", "computer", "laptop", "repair"],
            title_best="Компьютерный мастер",
            description_best=(
                "Диагностика и ремонт ноутбуков; Замена комплектующих и установка Windows; "
                "В наличии большой ассортимент проверенных б/у ноутбуков для покупки; "
                "Привожу новую технику дешевле чем в Сербии с доставкой на дом."
            ),
            service_name_candidate="Компьютерный мастер",
            details_candidate=(
                "Диагностика и ремонт ноутбуков; Замена комплектующих и установка Windows; "
                "В наличии большой ассортимент проверенных б/у ноутбуков для покупки; "
                "Привожу новую технику дешевле чем в Сербии с доставкой на дом."
            ),
            product_row_service_name="Компьютерный мастер",
            product_row_details=(
                "Диагностика и ремонт ноутбуков; Замена комплектующих и установка Windows; "
                "В наличии большой ассортимент проверенных б/у ноутбуков для покупки; "
                "Привожу новую технику дешевле чем в Сербии с доставкой на дом."
            ),
            product_row_category="Уборка и химчистка",
            product_row_contact="@example_computer_master",
            contact_candidate_display="@example_computer_master",
            contact_snapshot_telegram_handles=["example_computer_master"],
            contact_snapshot_telegram_links=["https://t.me/example_computer_master"],
            explicit_contact_snapshot_telegram_handles=["example_computer_master"],
            explicit_contact_snapshot_telegram_links=["https://t.me/example_computer_master"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["category"], "Ремонт и монтаж")
        self.assertEqual(row["details"], "Диагностика и ремонт ноутбуков; Замена комплектующих и установка Windows")
        self.assertNotIn("в наличии", row["details"].lower())
        self.assertNotIn("новую технику", row["details"].lower())

    def test_full_cell_fix74_normalizes_live_label_issue_families_without_anchor_hardcode(self) -> None:
        cases = [
            (
                {
                    "category_primary": "food_hospitality",
                    "service_tags": ["restaurant", "food"],
                    "title_best": "Белград",
                    "description_best": "Итальянский ресторан Emma; центральная улица",
                    "service_name_candidate": "Белград",
                    "details_candidate": "Итальянский ресторан Emma; центральная улица",
                    "product_row_service_name": "Белград",
                    "product_row_details": "Итальянский ресторан Emma; центральная улица",
                    "product_row_category": "Еда и гостеприимство",
                },
                "Итальянский ресторан",
                "Еда и гостеприимство",
            ),
            (
                {
                    "category_primary": "",
                    "service_tags": ["tool rental", "repair"],
                    "title_best": "Доброго времени суток",
                    "description_best": (
                        "Предоставляем в аренду электроинструменты для малых домашних и строительных работ.; "
                        "В нашем арсенале дрели и шуруповерты."
                    ),
                    "service_name_candidate": "Времени суток",
                    "details_candidate": (
                        "Предоставляем в аренду электроинструменты для малых домашних и строительных работ.; "
                        "В нашем арсенале дрели и шуруповерты."
                    ),
                    "product_row_service_name": "Времени суток",
                    "product_row_details": (
                        "Предоставляем в аренду электроинструменты для малых домашних и строительных работ.; "
                        "В нашем арсенале дрели и шуруповерты."
                    ),
                    "product_row_category": "",
                },
                "Аренда электроинструментов",
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "auto_service",
                    "service_tags": ["repair", "appliance"],
                    "title_best": "Готов оперативно приехать и помочь в ремонте по дому практически в любой сфере",
                    "description_best": "Ремонт стиральной машины: замена помпы, щеток; опыт ремонта бытовой техники.",
                    "service_name_candidate": "Готов оперативно приехать и помочь в ремонте по дому практически в любой сфере",
                    "details_candidate": "Ремонт стиральной машины: замена помпы, щеток; опыт ремонта бытовой техники.",
                    "product_row_service_name": "Готов оперативно приехать и помочь в ремонте по дому практически в любой сфере",
                    "product_row_details": (
                        "Много лет работал в сфере ремонта стиральных машин.; "
                        "Теперь живу в Белграде и продолжаю своё дело; "
                        "При повторных заказах сделаю скидку; "
                        "Ремонт стиральной машины: замена помпы, щеток"
                    ),
                    "product_row_category": "Автоуслуги",
                },
                "Ремонт стиральных машин",
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning", "housekeeping"],
                    "title_best": "Сезон охоты на пыль открыт",
                    "description_best": "Уборка пыли, шерсти животных, налета в душевой и окон.",
                    "service_name_candidate": "Сезон охоты на пыль открыт",
                    "details_candidate": "Уборка пыли, шерсти животных, налета в душевой и окон.",
                    "product_row_service_name": "Сезон охоты на пыль открыт",
                    "product_row_details": (
                        "Дарья, могу найти и уничтожить пыль в труднодоступных местах, "
                        "шерсть животных, волосы людей, убрать налет в душевой, вымыть окна."
                    ),
                    "product_row_category": "Уборка и химчистка",
                },
                "Клининг",
                "Уборка и химчистка",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["air_conditioner", "cleaning"],
                    "title_best": "Уважаемые соседи",
                    "description_best": "Чистка фильтров, мойка турбины и подготовка кондиционеров к лету.",
                    "service_name_candidate": "Уважаемые соседи",
                    "details_candidate": "Чистка фильтров, мойка турбины и подготовка кондиционеров к лету.",
                    "product_row_service_name": "Уважаемые соседи",
                    "product_row_details": (
                        "Приближается летний период.; "
                        "Рекомендуется заблаговременно подготовить кондиционеры к эксплуатации.; "
                        "Необходимые мероприятия включают чистку фильтров и мойку турбины."
                    ),
                    "product_row_category": "Уборка и химчистка",
                },
                "Обслуживание кондиционеров",
                "Уборка и химчистка",
            ),
            (
                {
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["massage", "health"],
                    "title_best": "Боль",
                    "description_best": "Профессиональный массаж при боли и напряжении в спине.",
                    "service_name_candidate": "Боль",
                    "details_candidate": "Профессиональный массаж при боли и напряжении в спине.",
                    "product_row_service_name": "Боль",
                    "product_row_details": (
                        "Когда мы работаем с такими запросами, задача - не просто погладить, а вернуть вашей спине свободу; "
                        "Почему массаж в нашей студии - это безопасно и эффективно; Потому что мы не работаем вслепую."
                    ),
                    "product_row_category": "Красота и здоровье",
                },
                "Массаж",
                "Красота и здоровье",
            ),
        ]

        for overrides, expected_service_name, expected_category in cases:
            with self.subTest(expected_service_name=expected_service_name):
                offer = _build_offer(
                    **overrides,
                    product_row_contact="@example_direct_service",
                    contact_candidate_display="@example_direct_service",
                    contact_snapshot_telegram_handles=["example_direct_service"],
                    contact_snapshot_telegram_links=["https://t.me/example_direct_service"],
                    latest_post_url="https://t.me/example_generic_services/100",
                    source_anchor_text="@example_generic_services/100",
                )

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["service_name"], expected_service_name)
                self.assertEqual(row["category"], expected_category)
                row_text = json.dumps(row, ensure_ascii=False).lower()
                self.assertNotIn("времени суток", row_text)
                self.assertNotIn("готов оперативно", row_text)
                self.assertNotIn("сезон охоты", row_text)
                self.assertNotIn("уважаемые соседи", row_text)
                self.assertNotIn("когда мы работаем", row_text)
                self.assertNotIn("много лет работал", row_text)

    def test_full_cell_fix74_applies_trip_duplicate_transfer_and_furniture_policies(self) -> None:
        trip_offer = _build_offer(
            category_primary="auto_service",
            service_tags=["trip", "delivery"],
            title_best="27 апреля поеду из Белграда в Москву",
            description_best="Могу взять документы или небольшую посылку по пути.",
            service_name_candidate="27 апреля поеду из Белграда в Москву",
            details_candidate="Могу взять документы или небольшую посылку по пути.",
            product_row_service_name="27 апреля поеду из Белграда в Москву",
            product_row_details="Могу взять документы или небольшую посылку по пути.",
            product_row_category="Автоуслуги",
        )
        _finalize_product_rows([trip_offer])
        self.assertEqual(trip_offer["publishable_row"]["publish_decision"], "drop")
        self.assertEqual(trip_offer["publishable_row"]["audit_reason"], "publishable_one_off_trip")

        duplicate_offer = _build_offer(
            category_primary="psychology",
            service_tags=["psychology", "therapy"],
            title_best="Психолог - Психотерапевт",
            description_best="Психолог - Психотерапевт",
            service_name_candidate="Психолог - Психотерапевт",
            details_candidate="Психолог - Психотерапевт",
            product_row_service_name="Психолог - Психотерапевт",
            product_row_details="Психолог - Психотерапевт ️",
            product_row_category="Психология",
        )
        _finalize_product_rows([duplicate_offer])
        self.assertEqual(duplicate_offer["publishable_row"]["publish_decision"], "publish")
        self.assertEqual(duplicate_offer["publishable_row"]["details"], "")

        transfer_offer = _build_offer(
            category_primary="auto_service",
            service_tags=["transfer", "driver"],
            title_best="Трансфер в Белграде - комфортно и быстро",
            description_best="Заберу, отвезу, подожду; Всё, как вы любите; Аэропорт, ж/д вокзал",
            service_name_candidate="Трансфер в Белграде - комфортно и быстро",
            details_candidate="Заберу, отвезу, подожду; Всё, как вы любите; Аэропорт, ж/д вокзал",
            product_row_service_name="Трансфер в Белграде - комфортно и быстро",
            product_row_details="Заберу, отвезу, подожду; Всё, как вы любите; Аэропорт, ж/д вокзал",
            product_row_category="Автоуслуги",
        )
        _finalize_product_rows([transfer_offer])
        self.assertEqual(transfer_offer["publishable_row"]["publish_decision"], "publish")
        self.assertEqual(transfer_offer["publishable_row"]["service_name"], "Трансфер")
        self.assertEqual(transfer_offer["publishable_row"]["details"], "Аэропорт, ж/д вокзал; В Белграде")

        furniture_offer = _build_offer(
            category_primary="it_digital",
            service_tags=["furniture", "custom"],
            title_best="Изготовление мебели на заказ: кухни и шкафы",
            description_best="Корпусная мебель по индивидуальным проектам; кухни на заказ; шкафы-купе.",
            service_name_candidate="Изготовление мебели на заказ: кухни и шкафы",
            details_candidate="Корпусная мебель по индивидуальным проектам; кухни на заказ; шкафы-купе.",
            product_row_service_name="Изготовление мебели на заказ: кухни и шкафы",
            product_row_details="Предлагаем услуги по изготовлению качественной корпусной мебели по индивидуальным проектам.; Кухни на заказ; Шкафы-купе.",
            product_row_category="Digital и дизайн",
        )
        _finalize_product_rows([furniture_offer])
        self.assertEqual(furniture_offer["publishable_row"]["publish_decision"], "publish")
        self.assertEqual(furniture_offer["publishable_row"]["category"], "Ремонт и монтаж")

    def test_broad_quality_normalizes_slogan_and_intro_service_labels(self) -> None:
        cases = [
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning", "housekeeping"],
                    "title_best": "Самое время привести дом в порядок перед сезоном!",
                    "description_best": "Генеральная уборка, поддерживающая уборка и химчистка мебели.",
                    "service_name_candidate": "Самое время привести дом в порядок перед сезоном!",
                    "details_candidate": "Генеральная уборка, поддерживающая уборка и химчистка мебели.",
                    "product_row_service_name": "Самое время привести дом в порядок перед сезоном!",
                    "product_row_details": "Генеральная уборка, поддерживающая уборка и химчистка мебели.",
                    "product_row_category": "Уборка и химчистка",
                },
                "Клининг",
                "Уборка и химчистка",
            ),
            (
                {
                    "category_primary": "auto_service",
                    "service_tags": ["transfer", "driver"],
                    "title_best": "Привет, меня зовут Алексей, я водитель в Белграде.",
                    "description_best": "Трансфер из аэропорта, поездки по Сербии и пассажирские перевозки.",
                    "service_name_candidate": "Привет, меня зовут Алексей, я водитель в Белграде.",
                    "details_candidate": "Трансфер из аэропорта, поездки по Сербии и пассажирские перевозки.",
                    "product_row_service_name": "Привет, меня зовут Алексей, я водитель в Белграде.",
                    "product_row_details": "Трансфер из аэропорта, поездки по Сербии и пассажирские перевозки.",
                    "product_row_category": "Автоуслуги",
                },
                "Трансфер и поездки",
                "Переезды и доставка",
            ),
            (
                {
                    "category_primary": "legal_docs",
                    "service_tags": ["visa", "documents", "transport"],
                    "title_best": "Надежный визаран из Белграда каждый день всего за",
                    "description_best": "Регулярный визаран из Белграда, отправление утром и вечером.",
                    "service_name_candidate": "Надежный визаран из Белграда каждый день всего за",
                    "details_candidate": "Регулярный визаран из Белграда, отправление утром и вечером.",
                    "product_row_service_name": "Надежный визаран ИЗ белграда каждый день всего ЗА",
                    "product_row_details": "Отправление каждый день с центра города и от Сава центра.",
                    "product_row_category": "Документы и право",
                },
                "Визаран из Белграда",
                "Переезды и доставка",
            ),
        ]
        for overrides, expected_service_name, expected_category in cases:
            with self.subTest(expected_service_name=expected_service_name):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["service_name"], expected_service_name)
                self.assertEqual(row["category"], expected_category)
                self.assertNotIn("самое время", row["service_name"].lower())
                self.assertNotIn("меня зовут", row["service_name"].lower())
                self.assertNotIn("всего за", row["service_name"].lower())

    def test_broad_quality_cleans_raw_intro_details_and_normalizes_categories(self) -> None:
        cases = [
            (
                {
                    "category_primary": "auto_service",
                    "service_tags": ["transfer", "driver"],
                    "title_best": "Трансфер и поездки",
                    "description_best": "Меня зовут Алексей, я водитель; Трансфер из аэропорта; Поездки по Сербии",
                    "service_name_candidate": "Трансфер и поездки",
                    "details_candidate": "Меня зовут Алексей, я водитель; Трансфер из аэропорта; Поездки по Сербии",
                    "product_row_service_name": "Трансфер и поездки",
                    "product_row_details": "Меня зовут Алексей, я водитель; Трансфер из аэропорта; Поездки по Сербии",
                    "product_row_category": "Автоуслуги",
                },
                "Трансфер из аэропорта; Поездки по Сербии",
                "Переезды и доставка",
            ),
            (
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["repair", "master"],
                    "title_best": "Мастер на час",
                    "description_best": "Мелкий ремонт, сантехника, электрика и сборка мебели.",
                    "service_name_candidate": "Мастер на час",
                    "details_candidate": "Мелкий ремонт, сантехника, электрика и сборка мебели.",
                    "product_row_service_name": "Мастер на час",
                    "product_row_details": "Мелкий ремонт, сантехника, электрика и сборка мебели.",
                    "product_row_category": "construction_repair",
                },
                "Мелкий ремонт, сантехника, электрика и сборка мебели.",
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "",
                    "service_tags": ["tutor", "language lesson"],
                    "title_best": "Уроки сербского языка",
                    "description_best": "Репетитор, разговорный сербский, грамматика и подготовка к жизни в Сербии.",
                    "service_name_candidate": "Уроки сербского языка",
                    "details_candidate": "Репетитор, разговорный сербский, грамматика и подготовка к жизни в Сербии.",
                    "product_row_service_name": "Уроки сербского языка",
                    "product_row_details": "Репетитор, разговорный сербский, грамматика и подготовка к жизни в Сербии.",
                    "product_row_category": "",
                },
                "Репетитор, разговорный сербский, грамматика и подготовка к жизни в Сербии.",
                "Обучение",
            ),
            (
                {
                    "category_primary": "",
                    "service_tags": ["sports", "training", "group classes"],
                    "title_best": "Направления групповых и индивидуальных занятий",
                    "description_best": "Тайский бокс, бокс, растяжка, утренние и вечерние группы.",
                    "service_name_candidate": "Направления групповых и индивидуальных занятий",
                    "details_candidate": "Тайский бокс, бокс, растяжка, утренние и вечерние группы.",
                    "product_row_service_name": "Направления групповых и индивидуальных занятий",
                    "product_row_details": "Тайский бокс, бокс, растяжка, утренние и вечерние группы.",
                    "product_row_category": "",
                },
                "Тайский бокс, бокс, растяжка, утренние и вечерние группы.",
                "Обучение",
            ),
            (
                {
                    "category_primary": "",
                    "service_tags": ["cleaning", "housekeeping"],
                    "title_best": "Сезон борьбы с пылью дома",
                    "description_best": "Убираем пыль с видимых поверхностей и из труднодоступных углов.",
                    "service_name_candidate": "Сезон борьбы с пылью дома",
                    "details_candidate": "Убираем пыль с видимых поверхностей и из труднодоступных углов.",
                    "product_row_service_name": "Сезон борьбы с пылью дома",
                    "product_row_details": "Убираем пыль с видимых поверхностей и из труднодоступных углов.",
                    "product_row_category": "",
                },
                "Убираем пыль с видимых поверхностей и из труднодоступных углов.",
                "Уборка и химчистка",
            ),
            (
                {
                    "category_primary": "",
                    "service_tags": ["master", "home repair"],
                    "title_best": "Скорая мужская помощь",
                    "description_best": "Белград; сломалось что-то дома; постараюсь помочь уже сегодня.",
                    "service_name_candidate": "Скорая мужская помощь",
                    "details_candidate": "Белград; сломалось что-то дома; постараюсь помочь уже сегодня.",
                    "product_row_service_name": "Скорая мужская помощь",
                    "product_row_details": "Белград; сломалось что-то дома; постараюсь помочь уже сегодня.",
                    "product_row_category": "",
                },
                "Белград; Сломалось что-то дома; Постараюсь помочь уже сегодня.",
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "",
                    "service_tags": ["windows", "mosquito screens"],
                    "title_best": "Окна",
                    "description_best": "Москитные сетки, установка и ремонт оконных решений.",
                    "service_name_candidate": "Окна",
                    "details_candidate": "Москитные сетки, установка и ремонт оконных решений.",
                    "product_row_service_name": "Окна",
                    "product_row_details": "Москитные сетки, установка и ремонт оконных решений.",
                    "product_row_category": "",
                },
                "Москитные сетки, установка и ремонт оконных решений.",
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning", "housekeeping"],
                    "title_best": "Клининг в Белграде",
                    "description_best": "Уборка квартир, офисов и помещений.",
                    "service_name_candidate": "Клининг в Белграде",
                    "details_candidate": "Уборка квартир, офисов и помещений.",
                    "product_row_service_name": "Клининг в Белграде",
                    "product_row_details": (
                        "Спешите заказать уборку квартиры, офиса, помещения; "
                        "Не забывайте, слоты имеют ограничение; "
                        "С 2023 года работаем в клининге Белграда."
                    ),
                    "product_row_category": "Уборка и химчистка",
                },
                "В Белграде",
                "Уборка и химчистка",
            ),
        ]
        for overrides, expected_details, expected_category in cases:
            with self.subTest(expected_category=expected_category):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["details"], expected_details)
                self.assertEqual(row["category"], expected_category)
                self.assertNotIn("меня зовут", row["details"].lower())
                self.assertNotIn("спешите", row["details"].lower())
                self.assertNotIn("слоты", row["details"].lower())

    def test_audit121_high_confidence_non_service_families_are_dropped(self) -> None:
        cases = [
            {
                "category_primary": "it_digital",
                "service_tags": ["tool", "discount", "bosch"],
                "title_best": "Информация о ценах и скидках на инструмент (Bosch)",
                "description_best": "Цены и скидки на инструмент Bosch, обзор магазинов и доступных моделей.",
                "service_name_candidate": "Информация о ценах и скидках на инструмент (Bosch)",
                "details_candidate": "Цены и скидки на инструмент Bosch, обзор магазинов и доступных моделей.",
                "product_row_service_name": "Информация о ценах и скидках на инструмент (Bosch)",
                "product_row_details": "Цены и скидки на инструмент Bosch, обзор магазинов и доступных моделей.",
                "product_row_category": "Digital и дизайн",
            },
            {
                "category_primary": "auto_service",
                "service_tags": ["goods", "co2"],
                "title_best": "Где купить маленький баллон CO2 по вменяемой цене",
                "description_best": "Подскажите, где купить маленький баллон CO2 по нормальной цене.",
                "service_name_candidate": "Где купить маленький баллон CO2 по вменяемой цене",
                "details_candidate": "Подскажите, где купить маленький баллон CO2 по нормальной цене.",
                "product_row_service_name": "Где купить маленький баллон CO2 по вменяемой цене",
                "product_row_details": "Подскажите, где купить маленький баллон CO2 по нормальной цене.",
                "product_row_category": "Автоуслуги",
            },
            {
                "category_primary": "construction_repair",
                "service_tags": ["tool", "rental"],
                "title_best": "Аренда мастерской и инструментов",
                "description_best": "Ищу мастерскую с инструментами для самостоятельной работы, кто знает где арендовать.",
                "service_name_candidate": "Аренда мастерской и инструментов",
                "details_candidate": "Ищу мастерскую с инструментами для самостоятельной работы, кто знает где арендовать.",
                "product_row_service_name": "Аренда мастерской и инструментов",
                "product_row_details": "Ищу мастерскую с инструментами для самостоятельной работы, кто знает где арендовать.",
                "product_row_category": "Ремонт и монтаж",
            },
            {
                "category_primary": "construction_repair",
                "service_tags": ["tool", "rental"],
                "title_best": "Аренда плиткореза",
                "description_best": "Нужен плиткорез на один день, пользователь ищет у кого взять в аренду.",
                "service_name_candidate": "Аренда плиткореза",
                "details_candidate": "Нужен плиткорез на один день, пользователь ищет у кого взять в аренду.",
                "product_row_service_name": "Аренда плиткореза",
                "product_row_details": "Нужен плиткорез на один день, пользователь ищет у кого взять в аренду.",
                "product_row_category": "Ремонт и монтаж",
            },
            {
                "category_primary": "construction_repair",
                "service_tags": ["repair"],
                "title_best": "Некачественный монтаж кабель-канала",
                "description_best": "Плохо сделали монтаж кабель-канала, вопрос как исправить результат.",
                "service_name_candidate": "Некачественный монтаж кабель-канала",
                "details_candidate": "Плохо сделали монтаж кабель-канала, вопрос как исправить результат.",
                "product_row_service_name": "Некачественный монтаж кабель-канала",
                "product_row_details": "Плохо сделали монтаж кабель-канала, вопрос как исправить результат.",
                "product_row_category": "Ремонт и монтаж",
            },
        ]

        for overrides in cases:
            with self.subTest(service=overrides["product_row_service_name"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["audit_reason"], "publishable_non_service")
                self.assertEqual(row["service_name"], "")
                self.assertEqual(row["category"], "")

    def test_audit121_category_families_are_generalized_without_source_hardcode(self) -> None:
        cases = [
            (
                {
                    "category_primary": "auto_service",
                    "service_tags": ["visa", "transfer", "passenger"],
                    "title_best": "Визаран и трансфер",
                    "description_best": "Регулярный визаран, отправление из Белграда, поездки и трансфер.",
                    "service_name_candidate": "Визаран и трансфер",
                    "details_candidate": "Регулярный визаран, отправление из Белграда, поездки и трансфер.",
                    "product_row_service_name": "Визаран и трансфер",
                    "product_row_details": "Регулярный визаран, отправление из Белграда, поездки и трансфер.",
                    "product_row_category": "Автоуслуги",
                },
                "Переезды и доставка",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["detailing", "auto", "polishing"],
                    "title_best": "Детейлинг и полировка автомобилей",
                    "description_best": "Детейлинг, полировка кузова и уход за салоном автомобилей.",
                    "service_name_candidate": "Детейлинг и полировка автомобилей",
                    "details_candidate": "Детейлинг, полировка кузова и уход за салоном автомобилей.",
                    "product_row_service_name": "Детейлинг и полировка автомобилей",
                    "product_row_details": "Детейлинг, полировка кузова и уход за салоном автомобилей.",
                    "product_row_category": "Уборка и химчистка",
                },
                "Автоуслуги",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["air_conditioner", "repair"],
                    "title_best": "Обслуживание и ремонт кондиционеров",
                    "description_best": "Обслуживание и ремонт кондиционеров, диагностика фреона и настройка.",
                    "service_name_candidate": "Обслуживание и ремонт кондиционеров",
                    "details_candidate": "Обслуживание и ремонт кондиционеров, диагностика фреона и настройка.",
                    "product_row_service_name": "Обслуживание и ремонт кондиционеров",
                    "product_row_details": "Обслуживание и ремонт кондиционеров, диагностика фреона и настройка.",
                    "product_row_category": "Уборка и химчистка",
                },
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "psychology",
                    "service_tags": ["teacher", "english", "exam"],
                    "title_best": "Преподаватель английского",
                    "description_best": "Репетитор: подготовка к ОГЭ/ЕГЭ и профессиональный английский.",
                    "service_name_candidate": "Преподаватель английского",
                    "details_candidate": "Репетитор: подготовка к ОГЭ/ЕГЭ и профессиональный английский.",
                    "product_row_service_name": "Преподаватель английского",
                    "product_row_details": "Репетитор: подготовка к ОГЭ/ЕГЭ и профессиональный английский.",
                    "product_row_category": "Психология",
                },
                "Обучение",
            ),
            (
                {
                    "category_primary": "education_tutoring",
                    "service_tags": ["rehabilitation", "medical", "lfk"],
                    "title_best": "Врач-реабилитолог",
                    "description_best": "Индивидуальная лечебная физкультура, ЛФК и программы реабилитации.",
                    "service_name_candidate": "Врач-реабилитолог",
                    "details_candidate": "Индивидуальная лечебная физкультура, ЛФК и программы реабилитации.",
                    "product_row_service_name": "Врач-реабилитолог",
                    "product_row_details": "Индивидуальная лечебная физкультура, ЛФК и программы реабилитации.",
                    "product_row_category": "Обучение",
                },
                "Красота и здоровье",
            ),
        ]

        for overrides, expected_category in cases:
            with self.subTest(expected_category=expected_category):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], expected_category)

    def test_audit121_overlong_service_labels_move_detail_clauses_to_details(self) -> None:
        cases = [
            (
                {
                    "category_primary": "moving_delivery",
                    "service_tags": ["auto", "import", "inspection"],
                    "title_best": "Подбор и доставка авто из Германии и Словении — техпроверка и сопровождение",
                    "description_best": "Подбор, доставка авто из Германии и Словении, техпроверка и сопровождение сделки.",
                    "service_name_candidate": "Подбор и доставка авто из Германии и Словении — техпроверка и сопровождение",
                    "details_candidate": "Подбор, доставка авто из Германии и Словении, техпроверка и сопровождение сделки.",
                    "product_row_service_name": "Подбор и доставка авто из Германии и Словении — техпроверка и сопровождение",
                    "product_row_details": "Подбор, доставка авто из Германии и Словении, техпроверка и сопровождение сделки.",
                    "product_row_category": "Психология",
                },
                "Подбор и доставка авто",
                "техпроверка",
                "Автоуслуги",
            ),
            (
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["carpenter", "furniture", "installation"],
                    "title_best": "Столяр/плотник — изготовление мебели и монтаж деревянных конструкций (Нови Сад)",
                    "description_best": "Изготовление мебели и монтаж деревянных конструкций в Нови Сад.",
                    "service_name_candidate": "Столяр/плотник — изготовление мебели и монтаж деревянных конструкций (Нови Сад)",
                    "details_candidate": "Изготовление мебели и монтаж деревянных конструкций в Нови Сад.",
                    "product_row_service_name": "Столяр/плотник — изготовление мебели и монтаж деревянных конструкций (Нови Сад)",
                    "product_row_details": "Изготовление мебели и монтаж деревянных конструкций в Нови Сад.",
                    "product_row_category": "Ремонт и монтаж",
                },
                "Столяр/плотник",
                "изготовление мебели",
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["plumber", "master", "boiler"],
                    "city_display_names": ["Belgrade"],
                    "title_best": "Сантехник и мастер на час в Белграде — бойлеры и сантехнические работы",
                    "description_best": "Сантехник, мастер на час, бойлеры и сантехнические работы.",
                    "service_name_candidate": "Сантехник и мастер на час в Белграде — бойлеры и сантехнические работы",
                    "details_candidate": "Сантехник, мастер на час, бойлеры и сантехнические работы.",
                    "product_row_service_name": "Сантехник и мастер на час в Белграде — бойлеры и сантехнические работы",
                    "product_row_details": "Сантехник, мастер на час, бойлеры и сантехнические работы.",
                    "product_row_category": "Ремонт и монтаж",
                },
                "Сантехник и мастер на час",
                "бойлеры",
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "psychology",
                    "service_tags": ["teacher", "english", "exam"],
                    "title_best": "Преподаватель английского — репетитор: подготовка к ОГЭ/ЕГЭ и профессиональный английский",
                    "description_best": "Репетитор, подготовка к ОГЭ/ЕГЭ и профессиональный английский.",
                    "service_name_candidate": "Преподаватель английского — репетитор: подготовка к ОГЭ/ЕГЭ и профессиональный английский",
                    "details_candidate": "Репетитор, подготовка к ОГЭ/ЕГЭ и профессиональный английский.",
                    "product_row_service_name": "Преподаватель английского — репетитор: подготовка к ОГЭ/ЕГЭ и профессиональный английский",
                    "product_row_details": "Репетитор, подготовка к ОГЭ/ЕГЭ и профессиональный английский.",
                    "product_row_category": "Психология",
                },
                "Преподаватель английского",
                "подготовка",
                "Обучение",
            ),
        ]

        for overrides, expected_service, detail_fragment, expected_category in cases:
            with self.subTest(expected_service=expected_service):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["service_name"], expected_service)
                self.assertEqual(row["category"], expected_category)
                self.assertNotIn(" — ", row["service_name"])
                self.assertNotIn("Нови Сад", row["service_name"])
                self.assertIn(detail_fragment.lower(), row["details"].lower())

    def test_broad_quality_drops_chat_directory_rows_but_keeps_direct_services(self) -> None:
        drop_cases = [
            {
                "category_primary": "food_hospitality",
                "service_tags": ["food", "community"],
                "title_best": "Чат о еде и продуктах",
                "description_best": "Обсуждаем кафе, магазины и доставки еды в общем чате.",
                "service_name_candidate": "Чат о еде и продуктах",
                "details_candidate": "Обсуждаем кафе, магазины и доставки еды в общем чате.",
                "product_row_service_name": "Чат о еде и продуктах",
                "product_row_details": "Обсуждаем кафе, магазины и доставки еды в общем чате.",
                "product_row_category": "Еда и гостеприимство",
                "product_row_contact": "@example_food_chat",
                "contact_candidate_display": "@example_food_chat",
                "contact_snapshot_telegram_handles": ["example_food_chat"],
                "contact_snapshot_telegram_links": ["https://t.me/example_food_chat"],
            },
            {
                "category_primary": "auto_service",
                "service_tags": ["auto", "community"],
                "title_best": "Самый крупный авточат",
                "description_best": "Авточат для общения владельцев машин в Сербии.",
                "service_name_candidate": "Самый крупный авточат",
                "details_candidate": "Авточат для общения владельцев машин в Сербии.",
                "product_row_service_name": "Самый крупный авточат",
                "product_row_details": "Авточат для общения владельцев машин в Сербии.",
                "product_row_category": "Автоуслуги",
                "product_row_contact": "@example_auto_chat",
                "contact_candidate_display": "@example_auto_chat",
                "contact_snapshot_telegram_handles": ["example_auto_chat"],
                "contact_snapshot_telegram_links": ["https://t.me/example_auto_chat"],
            },
            {
                "category_primary": "construction_repair",
                "service_tags": ["construction", "community"],
                "title_best": "Строительство и ремонт",
                "description_best": "Присоединяйтесь к чату: обсуждаем строителей, материалы и цены.",
                "service_name_candidate": "Строительство и ремонт",
                "details_candidate": "Присоединяйтесь к чату: обсуждаем строителей, материалы и цены.",
                "product_row_service_name": "Строительство и ремонт",
                "product_row_details": "Присоединяйтесь к чату: обсуждаем строителей, материалы и цены.",
                "product_row_category": "Ремонт и монтаж",
                "product_row_contact": "@example_build_chat",
                "contact_candidate_display": "@example_build_chat",
                "contact_snapshot_telegram_handles": ["example_build_chat"],
                "contact_snapshot_telegram_links": ["https://t.me/example_build_chat"],
            },
        ]
        for overrides in drop_cases:
            with self.subTest(title=overrides["title_best"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["audit_reason"], "publishable_non_service")

        keep_cases = [
            (
                {
                    "category_primary": "it_digital",
                    "service_tags": ["product design", "ux", "digital"],
                    "title_best": "UX/UI design for digital products",
                    "description_best": "Design complex digital products for fintech, enterprise and B2B SaaS.",
                    "service_name_candidate": "UX/UI design for digital products",
                    "details_candidate": "Design complex digital products for fintech, enterprise and B2B SaaS.",
                    "product_row_service_name": "UX/UI design for digital products",
                    "product_row_details": "Design complex digital products for fintech, enterprise and B2B SaaS.",
                    "product_row_category": "Digital и дизайн",
                },
                "Digital и дизайн",
            ),
            (
                {
                    "category_primary": "it_digital",
                    "service_tags": ["website", "seo", "ads"],
                    "title_best": "Разработка и продвижение продающих веб-сайтов",
                    "description_best": "SEO, настройка рекламных кампаний и создание лендингов.",
                    "service_name_candidate": "Разработка и продвижение продающих веб-сайтов",
                    "details_candidate": "SEO, настройка рекламных кампаний и создание лендингов.",
                    "product_row_service_name": "Разработка и продвижение продающих веб-сайтов",
                    "product_row_details": "SEO, настройка рекламных кампаний и создание лендингов.",
                    "product_row_category": "Digital и дизайн",
                },
                "Digital и дизайн",
            ),
            (
                {
                    "category_primary": "education_tutoring",
                    "service_tags": ["music lessons", "guitar"],
                    "title_best": "Уроки гитары",
                    "description_best": "Электрогитара и акустика для взрослых и детей от 7 лет.",
                    "service_name_candidate": "Уроки гитары",
                    "details_candidate": "Электрогитара и акустика для взрослых и детей от 7 лет.",
                    "product_row_service_name": "Уроки гитары",
                    "product_row_details": "Электрогитара и акустика для взрослых и детей от 7 лет.",
                    "product_row_category": "Обучение",
                },
                "Обучение",
            ),
        ]
        for overrides, expected_category in keep_cases:
            with self.subTest(title=overrides["title_best"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], expected_category)
                if overrides["title_best"] == "Мастер на час":
                    self.assertEqual(row["details"], "Электрика, сантехника, ремонт бытовой техники")
                    self.assertNotIn("Работа в", row["details"])
                    self.assertNotIn("без выходных", row["details"])

    def test_proof83_visible_audit_families_are_generalized_without_source_hardcode(self) -> None:
        publish_cases = [
            (
                {
                    "category_primary": "",
                    "service_tags": ["driver", "transfer", "passenger"],
                    "title_best": "Индивидуальные междугородние поездки",
                    "description_best": (
                        "Маршруты: Нови-Сад, Суботица, Сомбор, Златибор, Голубац, "
                        "Фрушка Гора. По Сербии."
                    ),
                    "service_name_candidate": "Индивидуальные междугородние поездки",
                    "details_candidate": "Маршруты: Нови-Сад, Суботица, Сомбор, Златибор. По Сербии.",
                    "product_row_service_name": "Индивидуальные междугородние поездки",
                    "product_row_details": "Маршруты: Нови-Сад, Суботица, Сомбор, Златибор. По Сербии.",
                    "product_row_category": "",
                    "product_row_contact": "+381600000010",
                    "contact_candidate_display": "+381600000010",
                    "contact_snapshot_phones": ["381600000010"],
                    "explicit_contact_snapshot_phones": ["381600000010"],
                },
                "Автоуслуги",
            ),
            (
                {
                    "category_primary": "",
                    "service_tags": ["earthworks", "construction materials"],
                    "title_best": "Земляные работы и поставка инертных материалов",
                    "description_best": (
                        "Земляные работы, техника, доставка песка, щебня и других "
                        "инертных материалов в Сербии."
                    ),
                    "service_name_candidate": "Земляные работы и поставка инертных материалов",
                    "details_candidate": "Земляные работы, техника, доставка песка и щебня.",
                    "product_row_service_name": "Земляные работы и поставка инертных материалов",
                    "product_row_details": "Земляные работы и поставка инертных материалов в Сербии.",
                    "product_row_category": "",
                    "product_row_contact": "@example_building_contact",
                    "contact_candidate_display": "@example_building_contact",
                    "contact_snapshot_telegram_handles": ["example_building_contact"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_building_contact"],
                },
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["master", "repair"],
                    "title_best": "Мастер на час",
                    "description_best": (
                        "Электрика, сантехника, ремонт бытовой техники. "
                        "Работа в Belgrade, без выходных (07:00-23:00)."
                    ),
                    "service_name_candidate": "Мастер на час (Belgrade)",
                    "details_candidate": (
                        "Электрика, сантехника, ремонт бытовой техники; "
                        "Работа в Belgrade, без выходных (07:00-23:00)."
                    ),
                    "product_row_service_name": "Мастер на час (Belgrade)",
                    "product_row_details": (
                        "Электрика, сантехника, ремонт бытовой техники; "
                        "Работа в Belgrade, без выходных (07:00-23:00)."
                    ),
                    "product_row_category": "Ремонт и монтаж",
                    "product_row_contact": "@example_belgrade_repair",
                    "contact_candidate_display": "@example_belgrade_repair",
                    "contact_snapshot_telegram_handles": ["example_belgrade_repair"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_belgrade_repair"],
                },
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning"],
                    "title_best": "Уборка квартир и офисов в Белграде",
                    "description_best": (
                        "Генеральная и регулярная уборка, уборка после ремонта, "
                        "химчистка диванов и мебели на дому."
                    ),
                    "service_name_candidate": "Уборка квартир и офисов в Белграде",
                    "details_candidate": (
                        "Генеральная и регулярная уборка, уборка после ремонта, "
                        "химчистка диванов и мебели на дому."
                    ),
                    "product_row_service_name": "Уборка квартир и офисов в Белграде",
                    "product_row_details": (
                        "Генеральная и регулярная уборка, уборка после ремонта, "
                        "химчистка диванов и мебели на дому."
                    ),
                    "product_row_category": "Ремонт и монтаж",
                    "product_row_contact": "+381600000011",
                    "contact_candidate_display": "+381600000011",
                    "contact_snapshot_phones": ["381600000011"],
                    "explicit_contact_snapshot_phones": ["381600000011"],
                },
                "Уборка и химчистка",
            ),
        ]

        for overrides, expected_category in publish_cases:
            with self.subTest(expected_category=expected_category):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], expected_category)

        drop_cases = [
            {
                "category_primary": "beauty_cosmetology",
                "service_tags": ["hair", "model"],
                "title_best": "Нужна модель для укладки феном",
                "description_best": (
                    "Ищу модель на брашинг и локоны, бесплатно дома или 500 rsd "
                    "в салоне, для отработки скорости и пополнения портфолио."
                ),
                "service_name_candidate": "Модель для укладки феном (брашинг, локоны)",
                "details_candidate": "Ищу модель на брашинг и локоны, бесплатно дома или 500 rsd в салоне.",
                "product_row_service_name": "Модель для укладки феном (брашинг, локоны)",
                "product_row_details": "",
                "product_row_category": "Автоуслуги",
                "product_row_contact": "@example_contact_beta",
                "contact_candidate_display": "@example_contact_beta",
                "contact_snapshot_telegram_handles": ["example_contact_beta"],
                "contact_snapshot_telegram_links": ["https://t.me/example_contact_beta"],
            },
            {
                "category_primary": "",
                "service_tags": ["rent", "real estate"],
                "title_best": "Аренда квартир в Белграде — запись на просмотр",
                "description_best": (
                    "Для записи на просмотр укажите: кто будет жить в квартире, "
                    "предполагаемая дата заезда, срок и когда удобно посмотреть квартиру."
                ),
                "service_name_candidate": "Аренда квартир в Белграде — запись на просмотр",
                "details_candidate": (
                    "Для записи на просмотр укажите: кто будет жить в квартире, "
                    "предполагаемая дата заезда, на какой срок и когда вам удобно посмотреть квартиру."
                ),
                "product_row_service_name": "Аренда квартир в Белграде — запись на просмотр",
                "product_row_details": (
                    "Для записи на просмотр укажите: кто будет жить в квартире, "
                    "предполагаемая дата заезда, на какой срок и когда вам удобно посмотреть квартиру."
                ),
                "product_row_category": "",
                "product_row_contact": "@example_source_eta",
                "contact_candidate_display": "@example_source_eta",
                "contact_snapshot_telegram_handles": ["example_source_eta"],
                "contact_snapshot_telegram_links": ["https://t.me/example_source_eta"],
            },
            {
                "category_primary": "",
                "service_tags": [],
                "title_best": "Разная помощь",
                "description_best": "Помогу с разными бытовыми вопросами по договоренности.",
                "service_name_candidate": "Разная помощь",
                "details_candidate": "Помогу с разными бытовыми вопросами по договоренности.",
                "product_row_service_name": "Разная помощь",
                "product_row_details": "Помогу с разными бытовыми вопросами по договоренности.",
                "product_row_category": "",
                "product_row_contact": "@example_generic_helper",
                "contact_candidate_display": "@example_generic_helper",
                "contact_snapshot_telegram_handles": ["example_generic_helper"],
                "contact_snapshot_telegram_links": ["https://t.me/example_generic_helper"],
            },
        ]
        for overrides in drop_cases:
            with self.subTest(title=overrides["title_best"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["category"], "")

    def test_photo_video_portfolio_service_keeps_digital_category_and_cleans_details(self) -> None:
        offer = _build_offer(
            category_primary="",
            service_tags=["video", "photo", "editing"],
            title_best="Снимаю видео и фото, монтирую качественные ролики.",
            description_best="Имею опыт более 3 лет; пришлю портфолио.",
            service_name_candidate="Снимаю видео и фото, монтирую качественные ролики.",
            details_candidate="Имею опыт более 3 лет; пришлю портфолио.",
            product_row_service_name="Видео- и фотосъёмка, монтаж роликов",
            product_row_details="Видео- и фотосъёмка; монтаж качественных роликов; портфолио доступно.",
            product_row_category="Digital и дизайн",
            product_row_contact="@example_contact_alpha",
            contact_candidate_display="@example_contact_alpha",
            contact_snapshot_telegram_handles=["example_contact_alpha"],
            contact_snapshot_telegram_links=["https://t.me/example_contact_alpha"],
            source_anchor_text="@example_source_beta/70843",
            latest_post_url="https://t.me/example_source_beta/70843",
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Видео- и фотосъёмка, монтаж роликов")
        self.assertEqual(row["details"], "Видео- и фотосъёмка; Монтаж качественных роликов")
        self.assertEqual(row["category"], "Digital и дизайн")
        self.assertNotIn("портфолио", row["details"].lower())

    def test_graphic_design_portfolio_channel_availability_is_removed_from_visible_details(self) -> None:
        offer = _build_offer(
            category_primary="it_digital",
            service_tags=["graphic design", "logo", "advertising materials"],
            title_best="Графический дизайн — логотипы и рекламные материалы",
            description_best=(
                "Дизайн для соцсетей и рекламы, инфографика, баннеры, афиши, визитки. "
                "Канал/портфолио в Telegram указан в исходном посте."
            ),
            service_name_candidate="Графический дизайн — логотипы и рекламные материалы",
            details_candidate=(
                "Дизайн для соцсетей и рекламы, инфографика, баннеры, афиши, визитки; "
                "Канал/портфолио в Telegram указан в исходном посте."
            ),
            product_row_service_name="Графический дизайн — логотипы и рекламные материалы",
            product_row_details=(
                "Дизайн для соцсетей и рекламы, инфографика, баннеры, афиши, визитки; "
                "Канал/портфолио в Telegram указан в исходном посте."
            ),
            product_row_category="Digital и дизайн",
            product_row_contact="@example_designer_contact",
            contact_candidate_display="@example_designer_contact",
            contact_snapshot_telegram_handles=["example_designer_contact"],
            contact_snapshot_telegram_links=["https://t.me/example_designer_contact"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["service_name"], "Графический дизайн — логотипы и рекламные материалы")
        self.assertEqual(row["details"], "Дизайн для соцсетей и рекламы, инфографика, баннеры, афиши, визитки")
        self.assertEqual(row["category"], "Digital и дизайн")
        self.assertNotIn("портфолио", row["details"].lower())
        self.assertNotIn("telegram", row["details"].lower())

    def test_service_area_work_wording_is_removed_from_visible_details(self) -> None:
        cases = [
            (
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["hvac", "repair", "heating"],
                    "title_best": "Ремонт и чистка кондиционеров",
                    "description_best": "Диагностика и ремонт отопления; Работа в Нови Сад.",
                    "service_name_candidate": "Ремонт и чистка кондиционеров",
                    "details_candidate": "Диагностика и ремонт отопления; Работа в Нови Сад.",
                    "product_row_service_name": "Ремонт и чистка кондиционеров",
                    "product_row_details": "Диагностика и ремонт отопления; Работа в Нови Сад.",
                    "product_row_category": "Ремонт и монтаж",
                },
                "Диагностика и ремонт отопления",
            ),
            (
                {
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["hair", "beauty"],
                    "title_best": "Парикмахерские услуги",
                    "description_best": "Стрижки, окрашивание и укладки; Работа в районе Futoška pijaca, Novi Sad.",
                    "service_name_candidate": "Парикмахерские услуги",
                    "details_candidate": "Стрижки, окрашивание и укладки; Работа в районе Futoška pijaca, Novi Sad.",
                    "product_row_service_name": "Парикмахерские услуги",
                    "product_row_details": "Стрижки, окрашивание и укладки; Работа в районе Futoška pijaca, Novi Sad.",
                    "product_row_category": "Красота и здоровье",
                },
                "Стрижки, окрашивание и укладки",
            ),
            (
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["repair", "installation", "plumbing", "electrical"],
                    "title_best": "Мастер по ремонту и монтажу бытовой техники",
                    "description_best": (
                        "Ремонт бытовой техники, чистка кондиционеров, электромонтаж, "
                        "сантехнические работы. Работа в Белграде и окрестностях. Опыт 8 лет."
                    ),
                    "service_name_candidate": "Мастер по ремонту и монтажу бытовой техники",
                    "details_candidate": (
                        "Ремонт бытовой техники, чистка кондиционеров, электромонтаж, "
                        "сантехнические работы; Работа в Белграде и окрестностях; Опыт 8 лет."
                    ),
                    "product_row_service_name": "Мастер по ремонту и монтажу бытовой техники",
                    "product_row_details": (
                        "Ремонт бытовой техники, чистка кондиционеров, электромонтаж, "
                        "сантехнические работы; Работа в Белграде и окрестностях; Опыт 8 лет."
                    ),
                    "product_row_category": "Ремонт и монтаж",
                },
                "Ремонт бытовой техники, чистка кондиционеров, электромонтаж, сантехнические работы",
            ),
        ]

        for overrides, expected_details in cases:
            with self.subTest(title=overrides["title_best"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["details"], expected_details)
                self.assertNotIn("Работа", row["details"])
                self.assertNotIn("Опыт", row["details"])
                self.assertFalse(_looks_like_vacancy_or_cv(f"{row['service_name']} {row['details']}"))

    def test_music_software_training_work_wording_is_not_visible_job_leakage(self) -> None:
        offer = _build_offer(
            category_primary="education_tutoring",
            service_tags=["music lessons", "guitar", "sound recording", "software training"],
            title_best="Обучение игре на гитаре, звукозаписи и написанию музыки",
            description_best=(
                "Индивидуальные занятия по акустической и электрогитаре; Обучение звукозаписи и сведению; "
                "Работа в программах для звукозаписи, гитарных и нотных редакторах."
            ),
            service_name_candidate="Обучение игре на гитаре, звукозаписи и написанию музыки",
            details_candidate=(
                "Индивидуальные занятия по акустической и электрогитаре; Обучение звукозаписи и сведению; "
                "Работа в программах для звукозаписи, гитарных и нотных редакторах."
            ),
            product_row_service_name="Обучение игре на гитаре, звукозаписи и написанию музыки",
            product_row_details=(
                "Индивидуальные занятия по акустической и электрогитаре; Обучение звукозаписи и сведению; "
                "Написанию и выпуску музыки; Музыкальная теория и нотная грамота; "
                "Работа в программах для звукозаписи, гитарных и нотных редакторах; "
                "Помощь с выбором и настройкой оборудования."
            ),
            product_row_category="Обучение",
            product_row_contact="@example_contact_kappa",
            contact_candidate_display="@example_contact_kappa",
            contact_snapshot_telegram_handles=["example_contact_kappa"],
            contact_snapshot_telegram_links=["https://t.me/example_contact_kappa"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "publish")
        self.assertEqual(row["category"], "Обучение")
        self.assertIn("Программы для звукозаписи", row["details"])
        self.assertNotIn("Работа в программах", row["details"])
        self.assertFalse(_looks_like_vacancy_or_cv(f"{row['service_name']} {row['details']}"))

    def test_real_training_vacancy_stays_blocked_before_visibility(self) -> None:
        offer = _build_offer(
            category_primary="education_tutoring",
            service_tags=["music lessons", "guitar"],
            title_best="Требуется преподаватель гитары",
            description_best="Ищем в команду преподавателя гитары; требования, обязанности, зарплата.",
            service_name_candidate="Уроки гитары",
            details_candidate="Ищем в команду преподавателя гитары; требования, обязанности, зарплата.",
            product_row_service_name="Уроки гитары",
            product_row_details="Ищем в команду преподавателя гитары; требования, обязанности, зарплата.",
            product_row_category="Обучение",
            product_row_contact="@example_music_school",
            contact_candidate_display="@example_music_school",
            contact_snapshot_telegram_handles=["example_music_school"],
            contact_snapshot_telegram_links=["https://t.me/example_music_school"],
        )

        _finalize_product_rows([offer])

        row = offer["publishable_row"]
        self.assertEqual(row["publish_decision"], "drop")
        self.assertEqual(row["audit_reason"], "publishable_non_service")


    def test_broad_mvp_policy_families_are_dropped_from_visible_services(self) -> None:
        cases = [
            {
                "title_best": "Ищу моделей на окрашивание и стрижку",
                "description_best": "Нужны модели для пополнения портфолио и отработки скорости, оплата только за материалы.",
                "service_name_candidate": "Ищу моделей на окрашивание и стрижку",
                "details_candidate": "Нужны модели для пополнения портфолио и отработки скорости, оплата только за материалы.",
                "product_row_service_name": "Окрашивание и стрижка",
                "product_row_details": "Нужны модели для пополнения портфолио и отработки скорости, оплата только за материалы.",
                "product_row_category": "Красота и здоровье",
            },
            {
                "category_primary": "beauty_cosmetology",
                "service_tags": ["makeup", "model"],
                "title_best": "Нужна модель на макияж",
                "description_best": "Ищу модель для макияжа и пополнения портфолио, оплата только за материалы.",
                "service_name_candidate": "Модель на макияж",
                "details_candidate": "Ищу модель для макияжа и пополнения портфолио, оплата только за материалы.",
                "product_row_service_name": "Макияж",
                "product_row_details": "Ищу модель для макияжа и пополнения портфолио, оплата только за материалы.",
                "product_row_category": "Красота и здоровье",
            },
            {
                "category_primary": "moving_delivery",
                "service_tags": ["real estate", "rent"],
                "title_best": "Сдаётся квартира в Белграде",
                "description_best": "Две спальни, 60м2, 1000 евро, квартира актуальна сейчас.",
                "service_name_candidate": "Сдаётся квартира в Белграде",
                "details_candidate": "Две спальни, 60м2, 1000 евро, квартира актуальна сейчас.",
                "product_row_service_name": "Сдаётся квартира в Белграде",
                "product_row_details": "Две спальни, 60м2, 1000 евро, квартира актуальна сейчас.",
                "product_row_category": "Переезды и доставка",
            },
            {
                "category_primary": "",
                "service_tags": ["real estate", "rent"],
                "title_best": "Аренда квартиры в Белграде",
                "description_best": "Для записи на просмотр укажите дату заезда, срок и кто будет жить в квартире.",
                "service_name_candidate": "Аренда квартиры в Белграде",
                "details_candidate": "Для записи на просмотр укажите дату заезда, срок и кто будет жить в квартире.",
                "product_row_service_name": "Аренда квартиры в Белграде",
                "product_row_details": "Для записи на просмотр укажите дату заезда, срок и кто будет жить в квартире.",
                "product_row_category": "",
            },
            {
                "category_primary": "it_digital",
                "service_tags": ["real estate", "platform"],
                "title_best": "AreaSell — платформа объявлений недвижимости",
                "description_best": "Платформа для покупки и продажи недвижимости на карте, можно бесплатно разместить объявление.",
                "service_name_candidate": "AreaSell — платформа объявлений недвижимости",
                "details_candidate": "Покупка и продажа недвижимости на карте, бесплатные объявления и чат.",
                "product_row_service_name": "AreaSell — платформа объявлений недвижимости",
                "product_row_details": "Покупка и продажа недвижимости на карте, бесплатные объявления и чат.",
                "product_row_category": "Digital и дизайн",
            },
            {
                "category_primary": "psychology",
                "service_tags": ["tarot", "consultation"],
                "title_best": "Таро консультация онлайн",
                "description_best": "Гадание на отношения, расклад на будущее и нумерология.",
                "service_name_candidate": "Таро консультация онлайн",
                "details_candidate": "Гадание на отношения, расклад на будущее и нумерология.",
                "product_row_service_name": "Таро консультация онлайн",
                "product_row_details": "Гадание на отношения, расклад на будущее и нумерология.",
                "product_row_category": "Психология",
            },
        ]
        for overrides in cases:
            with self.subTest(title=overrides["title_best"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "drop")
                self.assertEqual(row["category"], "")
                self.assertEqual(row["service_name"], "")
                self.assertEqual(row["details"], "")
                self.assertEqual(row["source"], "")

    def test_clear_medical_pedicure_and_pet_grooming_get_visible_category(self) -> None:
        cases = [
            {
                "service_tags": ["medical pedicure", "home visit"],
                "title_best": "Medicinski pedikir na kuÄnoj adresi",
                "description_best": "Medicinska sestra radi neÅ¾no, strpljivo i sa razumevanjem u Beogradu i Novom Sadu.",
                "service_name_candidate": "Medicinski pedikir na kuÄnoj adresi",
                "details_candidate": "Medicinska sestra radi neÅ¾no, strpljivo i sa razumevanjem u Beogradu i Novom Sadu.",
                "product_row_service_name": "Medicinski pedikir na kuÄnoj adresi",
                "product_row_details": "Medicinska sestra radi neÅ¾no, strpljivo i sa razumevanjem u Beogradu i Novom Sadu.",
            },
            {
                "service_tags": ["pet grooming", "dogs"],
                "title_best": "Grooming pasa u Beogradu",
                "description_best": "Kupanje, Å¡iÅ¡anje i higijenska nega pasa po dogovoru.",
                "service_name_candidate": "Grooming pasa u Beogradu",
                "details_candidate": "Kupanje, Å¡iÅ¡anje i higijenska nega pasa po dogovoru.",
                "product_row_service_name": "Grooming pasa u Beogradu",
                "product_row_details": "Kupanje, Å¡iÅ¡anje i higijenska nega pasa po dogovoru.",
            },
        ]
        for overrides in cases:
            with self.subTest(title=overrides["title_best"]):
                offer = _build_offer(category_primary="", product_row_category="", **overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], "Красота и здоровье")

    def test_real_estate_service_provider_offer_stays_publishable(self) -> None:
        cases = [
            (
                {
                    "category_primary": "legal_docs",
                    "service_tags": ["relocation", "legal", "real estate"],
                    "title_best": "Переезд в Сербию под ключ",
                    "description_best": "Оформление ВНЖ, открытие ИП, помощь с подбором квартиры и сопровождение сделки.",
                    "service_name_candidate": "Переезд в Сербию под ключ",
                    "details_candidate": "Оформление ВНЖ, открытие ИП, помощь с подбором квартиры и сопровождение сделки.",
                    "product_row_service_name": "Переезд в Сербию под ключ",
                    "product_row_details": "Оформление ВНЖ, открытие ИП, помощь с подбором квартиры и сопровождение сделки.",
                    "product_row_category": "Документы и право",
                },
                "Документы и право",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning", "apartment cleaning"],
                    "title_best": "Уборка квартир, офисов и помещений",
                    "description_best": "Генеральная уборка квартиры после ремонта, 50 евро за выезд.",
                    "service_name_candidate": "Уборка квартир, офисов и помещений",
                    "details_candidate": "Генеральная уборка квартиры после ремонта, 50 евро за выезд.",
                    "product_row_service_name": "Уборка квартир, офисов и помещений",
                    "product_row_details": "Генеральная уборка квартиры после ремонта, 50 евро за выезд.",
                    "product_row_category": "Уборка и химчистка",
                },
                "Уборка и химчистка",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning", "chemical cleaning", "apartment cleaning"],
                    "title_best": "BroCleaning",
                    "description_best": (
                        "Химчистка мебели, матрасов и штор; чистка кондиционеров; "
                        "аккуратная уборка квартир экологичными средствами."
                    ),
                    "service_name_candidate": "BroCleaning",
                    "details_candidate": "Химчистка мебели, авто и квартир в Нови-Саде.",
                    "product_row_service_name": "BroCleaning",
                    "product_row_details": (
                        "Химчистка мебели, матрасов и штор; Чистка и дезинфекция салонов автомобилей; "
                        "Чистка кондиционеров; Озонирование и обработка сухим дымом; "
                        "Аккуратная уборка квартир; Используются экологичные и безопасные средства."
                    ),
                    "product_row_category": "Уборка и химчистка",
                },
                "Уборка и химчистка",
            ),
            (
                {
                    "category_primary": "cleaning",
                    "service_tags": ["cleaning", "apartment cleaning"],
                    "title_best": "Уборка квартир — a&k Cleaning",
                    "description_best": "Обычная и генеральная уборка, уборка для Airbnb и Booking.",
                    "service_name_candidate": "Уборка квартир — a&k Cleaning",
                    "details_candidate": "Обычная и генеральная уборка квартир.",
                    "product_row_service_name": "Уборка квартир — a&k Cleaning",
                    "product_row_details": "",
                    "product_row_category": "Уборка и химчистка",
                    "product_row_contact": "@example_contact_mu",
                    "contact_candidate_display": "@example_contact_mu",
                    "contact_snapshot_telegram_handles": ["example_contact_mu"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_contact_mu"],
                },
                "Уборка и химчистка",
            ),
            (
                {
                    "category_primary": "moving_delivery",
                    "service_tags": ["moving", "cargo"],
                    "title_best": "Переезды квартир и офисов",
                    "description_best": "Перевозка вещей из квартир, домов, складов и коммерческих помещений.",
                    "service_name_candidate": "Переезды квартир и офисов",
                    "details_candidate": "Перевозка вещей из квартир, домов, складов и коммерческих помещений.",
                    "product_row_service_name": "Переезды квартир и офисов",
                    "product_row_details": "Перевозка вещей из квартир, домов, складов и коммерческих помещений.",
                    "product_row_category": "Переезды и доставка",
                },
                "Переезды и доставка",
            ),
            (
                {
                    "category_primary": "construction_repair",
                    "service_tags": ["construction", "renovation"],
                    "title_best": "Ремонт квартир и коммерческих помещений",
                    "description_best": "Строительные и отделочные работы в квартирах, домах и помещениях.",
                    "service_name_candidate": "Ремонт квартир и коммерческих помещений",
                    "details_candidate": "Строительные и отделочные работы в квартирах, домах и помещениях.",
                    "product_row_service_name": "Ремонт квартир и коммерческих помещений",
                    "product_row_details": "Строительные и отделочные работы в квартирах, домах и помещениях.",
                    "product_row_category": "Ремонт и монтаж",
                },
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "psychology",
                    "service_tags": ["technical inspection", "acceptance", "defect inspection"],
                    "title_best": "Профессиональный осмотр и приёмка квартир",
                    "description_best": (
                        "Независимый технический аудит домов, квартир и офисов в Сербии "
                        "перед покупкой или арендой."
                    ),
                    "service_name_candidate": "Профессиональный осмотр и приёмка квартир",
                    "details_candidate": (
                        "Независимый технический аудит домов, квартир и офисов в Сербии "
                        "перед покупкой или арендой."
                    ),
                    "product_row_service_name": "Профессиональный осмотр и приёмка квартир",
                    "product_row_details": (
                        "Независимый технический аудит домов, квартир и офисов в Сербии "
                        "перед покупкой или арендой.; Выявление скрытых дефектов и подготовка заключения."
                    ),
                    "product_row_category": "Психология",
                    "product_row_contact": "@example_contact_lambda",
                    "contact_candidate_display": "@example_contact_lambda",
                    "contact_snapshot_telegram_handles": ["example_contact_lambda"],
                    "contact_snapshot_telegram_links": ["https://t.me/example_contact_lambda"],
                },
                "Ремонт и монтаж",
            ),
            (
                {
                    "category_primary": "beauty_cosmetology",
                    "service_tags": ["massage", "rehabilitation"],
                    "title_best": "Массаж и реабилитация",
                    "description_best": "Массаж и реабилитация в оборудованном помещении студии.",
                    "service_name_candidate": "Массаж и реабилитация",
                    "details_candidate": "Массаж и реабилитация в оборудованном помещении студии.",
                    "product_row_service_name": "Массаж и реабилитация",
                    "product_row_details": "Массаж и реабилитация в оборудованном помещении студии.",
                    "product_row_category": "Красота и здоровье",
                },
                "Красота и здоровье",
            ),
        ]

        for overrides, expected_category in cases:
            with self.subTest(title=overrides["title_best"]):
                offer = _build_offer(**overrides)

                _finalize_product_rows([offer])

                row = offer["publishable_row"]
                self.assertEqual(row["publish_decision"], "publish")
                self.assertEqual(row["category"], expected_category)
                self.assertFalse(_looks_like_real_estate_listing(f"{row['service_name']} {row['details']}"))

if __name__ == "__main__":
    unittest.main()
