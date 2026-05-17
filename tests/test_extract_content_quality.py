from __future__ import annotations

import unittest

from scripts.extract.extractor import extract_structured_post
from scripts.extract.merge import merge_structured_posts


def _merge_single_raw_post(raw_post: dict) -> dict:
    structured = extract_structured_post(raw_post, "tz-test-content-quality")
    result = merge_structured_posts(
        {
            "run_id": "tz-test-content-quality",
            "structured_posts": [structured],
        }
    )
    return result["offers"][0]


class ExtractContentQualityTests(unittest.TestCase):
    def test_exact_service_anchor_pedicure_gets_compact_fact_pack(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:5062",
            "post_key": "tg:test:5062",
            "chat_id": "2143000733",
            "message_id": 5062,
            "source_channel_key": "example_source_alpha",
            "chat_title": "Сербия - Специалисты, услуги, работа",
            "chat_kind": "supergroup",
            "chat_username": "example_source_alpha",
            "post_url": "https://t.me/example_source_alpha/5062",
            "posted_at_utc": "2026-04-20T10:00:00Z",
            "text_raw": (
                "Medicinski pedikir na kućnoj adresi (Beograd / Novi Sad)\n"
                "Ako vaši roditelji ili baka i deka imaju problem sa stopalima, tu sam da pomognem 🤍\n"
                "Radim nežno, strpljivo i sa razumevanjem\n"
                "Medicinska sestra po struci, sa iskustvom u radu sa starijima\n"
                "Rad u skladu sa higijenskim standardima\n"
                "#Masaža_stopala\n"
                "#Nega_stopala\n"
                "Pomažem kod bola, zadebljale kože, uraslih noktiju i otežanog hoda\n"
                "Dolazim na adresu — bez stresa i napora za vaše najbliže.\n"
                "+381600000001 Example Provider"
            ),
            "sender_title": "Example Provider",
            "_run_id": "tz-test-content-quality",
            "_target_key": "example_source_alpha",
            "_telegram_target_input": "@example_source_alpha",
            "_telegram_target_resolved": "@example_source_alpha",
        }
        offer = _merge_single_raw_post(raw_post)
        self.assertEqual(offer["offer_state"], "candidate")
        self.assertTrue(offer["title_best"].startswith("Medicinski pedikir"))
        self.assertLess(len(offer["description_best"]), len(raw_post["text_raw"]))
        self.assertNotIn("+381600000001", offer["description_best"])
        self.assertEqual(offer["contact_candidate_display"], "+381600000001")
        self.assertEqual(offer["source_anchor_text"], "@example_source_alpha/5062")
        self.assertEqual(offer["freshness_at_utc"], "2026-04-20T10:00:00Z")

    def test_exact_service_anchor_logistics_is_compacted_without_losing_facts(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:40483",
            "post_key": "tg:test:40483",
            "chat_id": "1922228422",
            "message_id": 40483,
            "source_channel_key": "example_source_gamma",
            "chat_title": "Сербия Услуги",
            "chat_kind": "channel",
            "chat_username": "example_source_gamma",
            "post_url": "https://t.me/example_source_gamma/40483",
            "posted_at_utc": "2026-04-20T11:00:00Z",
            "text_raw": (
                "✅ Грузоперевозки №1 в Белграде \n\n"
                "🇷🇸 𝑹𝑼𝑺 𝑳𝑶𝑮𝑰𝑺𝑻𝑰𝑪𝑺 🇷🇸\n\n"
                "🚚 Квартирные и Офисные переезды \"под ключ\", доставка мебели из IKEA \n"
                "🚛 Перевозка любых грузов весом до 1500кг, объём кузова 10 м³\n"
                "💪 Проф. Грузчики\n"
                "🛠️ Разборка & Сборка мебели\n"
                "📦 Защитная упаковка \n"
                "✅ Предузетник\n"
                "💰 Различные способы оплаты (дин/евро/руб) \n"
                "🌍 Работаем по Белграду и всей Сербии, Европе & России \n\n"
                "☎️ +381600000002\n"
                "📲 WhatsApp, Viber, Telegram"
            ),
            "sender_title": "Example Provider",
            "_run_id": "tz-test-content-quality",
            "_target_key": "example_source_gamma",
            "_telegram_target_input": "@example_source_gamma",
            "_telegram_target_resolved": "@example_source_gamma",
        }
        offer = _merge_single_raw_post(raw_post)
        self.assertEqual(offer["offer_state"], "candidate")
        self.assertEqual(offer["title_best"], "Грузоперевозки №1 в Белграде")
        self.assertLess(len(offer["description_best"]), len(raw_post["text_raw"]))
        self.assertNotIn("+381600000002", offer["description_best"])
        self.assertEqual(offer["contact_candidate_display"], "+381600000002")
        self.assertIn("ad_dump_compacted", offer["fact_pack_flags"])
        self.assertEqual(offer["source_anchor_text"], "@example_source_gamma/40483")

    def test_greeting_and_self_intro_do_not_become_service_meaning(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:intro",
            "post_key": "tg:test:intro",
            "chat_id": "5000",
            "message_id": 42,
            "source_channel_key": "example_source_mu",
            "chat_title": "Маникюр Белград",
            "chat_kind": "channel",
            "chat_username": "example_source_mu",
            "post_url": "https://t.me/example_source_mu/42",
            "posted_at_utc": "2026-04-21T12:00:00Z",
            "text_raw": (
                "Всем привет!\n"
                "Меня зовут Нина, я мастер маникюра и педикюра в Нови Саде\n"
                "Делаю маникюр, педикюр и укрепление гелем\n"
                "Пишите @example_nina_nails"
            ),
            "sender_title": "Example Provider",
            "_run_id": "tz-test-content-quality",
            "_target_key": "example_source_mu",
            "_telegram_target_input": "@example_source_mu",
            "_telegram_target_resolved": "@example_source_mu",
        }
        offer = _merge_single_raw_post(raw_post)

        self.assertEqual(offer["offer_state"], "candidate")
        self.assertNotIn("Всем привет", offer["title_best"])
        self.assertNotIn("Меня зовут", offer["title_best"])
        self.assertNotIn("Меня зовут", offer["description_best"])
        self.assertIn("greeting_filtered", offer["fact_pack_flags"])
        self.assertIn("self_intro_filtered", offer["fact_pack_flags"])
        self.assertEqual(offer["contact_candidate_display"], "@example_nina_nails")

    def test_resale_post_is_rejected_before_fact_pack(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:resale",
            "post_key": "tg:test:resale",
            "chat_id": "6000",
            "message_id": 7,
            "source_channel_key": "example_source_omicron",
            "chat_title": "Продажа в Сербии",
            "chat_kind": "channel",
            "chat_username": "example_source_omicron",
            "post_url": "https://t.me/example_source_omicron/7",
            "posted_at_utc": "2026-04-21T13:00:00Z",
            "text_raw": (
                "Продам iPhone 15 Pro Max 256GB, 8GB RAM, состояние 10/10\n"
                "Цена 950 eur\n"
                "Пишите @example_seller"
            ),
            "_run_id": "tz-test-content-quality",
            "_target_key": "example_source_omicron",
            "_telegram_target_input": "@example_source_omicron",
            "_telegram_target_resolved": "@example_source_omicron",
        }
        offer = _merge_single_raw_post(raw_post)

        self.assertEqual(offer["offer_state"], "rejected")
        self.assertEqual(offer["offer_rejection_reason"], "non_service_resale")
        self.assertEqual(offer["title_best"], "")
        self.assertEqual(offer["description_best"], "")
        self.assertIn("resale", offer["fact_pack_flags"])

    def test_empty_offer_is_suppressed(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:empty",
            "post_key": "tg:test:empty",
            "chat_id": "7000",
            "message_id": 8,
            "source_channel_key": "example_empty_feed",
            "chat_title": "Empty feed",
            "chat_kind": "channel",
            "chat_username": "example_empty_feed",
            "post_url": "https://t.me/example_empty_feed/8",
            "posted_at_utc": "2026-04-21T14:00:00Z",
            "text_raw": "🙂🙂🙂\n@example_just_contact",
            "_run_id": "tz-test-content-quality",
            "_target_key": "example_empty_feed",
            "_telegram_target_input": "@example_empty_feed",
            "_telegram_target_resolved": "@example_empty_feed",
        }
        offer = _merge_single_raw_post(raw_post)

        self.assertEqual(offer["offer_state"], "suppressed")
        self.assertEqual(offer["offer_rejection_reason"], "empty_offer")
        self.assertEqual(offer["title_best"], "")
        self.assertEqual(offer["description_best"], "")
        self.assertIn("empty_offer", offer["fact_pack_flags"])

    def test_distinct_author_fallback_contacts_are_emitted_without_explicit_post_contacts(self) -> None:
        raw_post = {
            "raw_post_id": "tg:test:author-fallback",
            "post_key": "tg:test:author-fallback",
            "chat_id": "8000",
            "message_id": 19,
            "source_channel_key": "example_source_kappa",
            "chat_title": "Сербия Услуги",
            "chat_kind": "channel",
            "chat_username": "example_source_kappa",
            "post_url": "https://t.me/example_source_kappa/19",
            "posted_at_utc": "2026-04-23T08:00:00Z",
            "text_raw": "Ремонт бойлеров и выезд по Белграду в день обращения.",
            "sender_id": "555001",
            "sender_title": "Example Provider",
            "sender_username": "example_boiler_master",
            "sender_profile_url": "https://t.me/example_boiler_master",
            "sender_phone": "+381600000003",
            "_run_id": "tz-test-content-quality",
            "_target_key": "example_source_kappa",
            "_telegram_target_input": "@example_source_kappa",
            "_telegram_target_resolved": "@example_source_kappa",
        }
        structured = extract_structured_post(raw_post, "tz-test-content-quality")
        offer = merge_structured_posts(
            {
                "run_id": "tz-test-content-quality",
                "structured_posts": [structured],
            }
        )["offers"][0]

        self.assertEqual(structured["author_signals"]["sender_phone"], "381600000003")
        self.assertEqual(offer["explicit_contact_snapshot_telegram_handles"], [])
        self.assertEqual(offer["explicit_contact_snapshot_phones"], [])
        self.assertEqual(offer["author_fallback_telegram_handles"], ["example_boiler_master"])
        self.assertEqual(offer["author_fallback_telegram_links"], ["https://t.me/example_boiler_master"])
        self.assertEqual(offer["author_fallback_phones"], ["381600000003"])


if __name__ == "__main__":
    unittest.main()
