from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "db" / "migrations"

EXPECTED_VIEW_COLUMNS = {
    "offers_catalog": [
        "offer_key",
        "provider_key",
        "provider_display_name",
        "offer_state",
        "category_primary",
        "category_secondary",
        "title_best",
        "price_text_best",
        "price_min",
        "price_max",
        "currency_code",
        "city_codes",
        "service_tags",
        "serbia_relevance_verdict",
        "last_seen_at_utc",
        "latest_post_url",
        "dedupe_confidence",
        "freshness_bucket",
    ],
    "providers_directory": [
        "provider_key",
        "provider_state",
        "identity_strength",
        "canonical_name",
        "display_name_best",
        "provider_display_name",
        "provider_type",
        "primary_contact_type",
        "primary_contact_value",
        "phones",
        "telegram_handles",
        "telegram_links",
        "emails",
        "websites",
        "city_codes",
        "service_category_hints",
        "source_channel_keys",
        "offer_count",
        "last_seen_at_utc",
        "latest_post_url",
        "dedupe_confidence",
        "freshness_bucket",
        "linked_offers_json",
    ],
    "run_monitoring": [
        "run_id",
        "run_status",
        "trigger_type",
        "started_at_utc",
        "finished_at_utc",
        "duration_ms",
        "requested_targets_count",
        "successful_target_count",
        "failed_target_count",
        "sync_mode",
        "max_messages",
        "cutoff_policy_type",
        "cutoff_policy_value",
        "llm_enabled",
        "raw_posts_total",
        "providers_total",
        "offers_total",
        "offers_upserted_total",
        "warnings_json",
        "error_type",
        "error_message",
        "targets_json",
    ],
    "audit_review_drilldown": [
        "audit_row_id",
        "run_id",
        "entity_type",
        "entity_id",
        "entity_label",
        "entity_latest_post_url",
        "stage",
        "processor_type",
        "processor_version",
        "status",
        "decision_code",
        "created_at_utc",
        "reason_text",
        "latency_ms",
        "review_required",
        "attempt_number",
        "model_name",
        "prompt_version",
        "tokens_input",
        "tokens_output",
        "cost_estimate_usd",
        "confidence",
        "response_excerpt",
        "upstream_audit_row_id",
        "superseded_by_audit_row_id",
        "output_patch_json",
        "source_raw_posts_json",
    ],
    "freshness_coverage_metrics": [
        "metric_family",
        "metric_bucket",
        "freshness_bucket",
        "offer_state",
        "provider_state",
        "identity_strength",
        "category_primary",
        "city_code",
        "target_status",
        "metric_value",
        "latest_entity_seen_at_utc",
        "latest_run_started_at_utc",
        "requested_targets_total",
        "successful_targets_total",
        "failed_targets_total",
        "raw_posts_total",
        "providers_total",
        "offers_total",
        "raw_posts_emitted_total",
    ],
}

EXPECTED_VIEW_DEPENDENCIES = {
    "offers_catalog": {"offers", "providers"},
    "providers_directory": {"offers", "providers"},
    "run_monitoring": {"run_targets", "service_runs"},
    "audit_review_drilldown": {
        "audit_enrichment_rows",
        "audit_source_raw_posts",
        "offers",
        "providers",
        "raw_posts",
        "service_runs",
    },
    "freshness_coverage_metrics": {"offers", "providers", "run_targets", "service_runs"},
}


def _schema_dsn(base_dsn: str, schema_name: str) -> str:
    return make_conninfo(base_dsn, options=f"-c search_path={schema_name},public")


def _apply_migrations(base_dsn: str, schema_name: str) -> None:
    migration_paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_paths:
        raise AssertionError("DB migrations were not found for dashboard read proof.")

    with psycopg.connect(base_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
            cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name)))
            for migration_path in migration_paths:
                cursor.execute(migration_path.read_text(encoding="utf-8"))


def _drop_schema(base_dsn: str, schema_name: str) -> None:
    with psycopg.connect(base_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))


def _iso_week(value: datetime) -> str:
    iso_year, iso_week, _ = value.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _seed_dashboard_rows(schema_dsn: str) -> None:
    now = datetime.now(timezone.utc)

    run1_started = now - timedelta(days=2, hours=3)
    run1_finished = run1_started + timedelta(minutes=25)
    run2_started = now - timedelta(days=120, hours=2)
    run2_finished = run2_started + timedelta(minutes=18)

    provider1_seen = now - timedelta(days=2)
    offer1_seen = now - timedelta(days=2, hours=1)
    raw_post1_time = run1_started - timedelta(minutes=5)

    provider2_seen = now - timedelta(days=120)
    offer2_seen = now - timedelta(days=125)
    raw_post2_time = run2_started - timedelta(minutes=7)

    with psycopg.connect(schema_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO service_runs (
                    run_id,
                    run_status,
                    trigger_type,
                    started_at_utc,
                    finished_at_utc,
                    duration_ms,
                    requested_targets_count,
                    successful_target_count,
                    failed_target_count,
                    sync_mode,
                    max_messages,
                    cutoff_policy_type,
                    cutoff_policy_value,
                    llm_enabled,
                    raw_posts_total,
                    providers_total,
                    offers_total,
                    offers_upserted_total,
                    warnings_json,
                    error_type,
                    error_message
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    "run-dashboard-1",
                    "partial_success",
                    "webhook",
                    run1_started,
                    run1_finished,
                    1_500_000,
                    2,
                    1,
                    1,
                    "sheet_first_incremental",
                    25,
                    "months_back",
                    "1",
                    True,
                    1,
                    1,
                    1,
                    1,
                    Jsonb(["target failure retained for monitoring proof"]),
                    "target_partial_failure",
                    "novi_sad_cleaning target failed",
                ),
            )
            cursor.execute(
                """
                INSERT INTO service_runs (
                    run_id,
                    run_status,
                    trigger_type,
                    started_at_utc,
                    finished_at_utc,
                    duration_ms,
                    requested_targets_count,
                    successful_target_count,
                    failed_target_count,
                    sync_mode,
                    max_messages,
                    cutoff_policy_type,
                    cutoff_policy_value,
                    llm_enabled,
                    raw_posts_total,
                    providers_total,
                    offers_total,
                    offers_upserted_total,
                    warnings_json,
                    error_type,
                    error_message
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    "run-dashboard-2",
                    "success",
                    "scheduled",
                    run2_started,
                    run2_finished,
                    1_080_000,
                    1,
                    1,
                    0,
                    "sheet_first_incremental",
                    20,
                    "months_back",
                    "4",
                    False,
                    1,
                    1,
                    1,
                    1,
                    Jsonb([]),
                    "",
                    "",
                ),
            )

            cursor.executemany(
                """
                INSERT INTO run_targets (
                    run_id,
                    target_key,
                    target_input,
                    target_resolved,
                    target_status,
                    started_at_utc,
                    finished_at_utc,
                    checkpoint_message_id,
                    raw_posts_emitted,
                    error_type,
                    error_message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        "run-dashboard-1",
                        "example_belgrade_cleaning",
                        "@example_belgrade_cleaning",
                        "https://t.me/example_belgrade_cleaning",
                        "success",
                        run1_started,
                        run1_finished - timedelta(minutes=10),
                        101,
                        1,
                        "",
                        "",
                    ),
                    (
                        "run-dashboard-1",
                        "example_novi_sad_cleaning",
                        "@example_novi_sad_cleaning",
                        "https://t.me/example_novi_sad_cleaning",
                        "error",
                        run1_started,
                        run1_finished,
                        None,
                        0,
                        "fetch_failed",
                        "rate limit",
                    ),
                    (
                        "run-dashboard-2",
                        "example_subotica_services",
                        "@example_subotica_services",
                        "https://t.me/example_subotica_services",
                        "success",
                        run2_started,
                        run2_finished,
                        202,
                        1,
                        "",
                        "",
                    ),
                ],
            )

            cursor.executemany(
                """
                INSERT INTO providers (
                    provider_key,
                    provider_state,
                    identity_strength,
                    display_name_best,
                    canonical_name,
                    provider_type,
                    primary_contact_type,
                    primary_contact_value,
                    latest_post_url,
                    first_seen_at_utc,
                    last_seen_at_utc,
                    first_seen_run_id,
                    last_seen_run_id,
                    times_seen,
                    offer_count,
                    dedupe_confidence,
                    phones,
                    telegram_handles,
                    telegram_links,
                    emails,
                    websites,
                    city_codes,
                    service_category_hints,
                    source_channel_keys
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    (
                        "provider-db-dash-1",
                        "candidate",
                        "strong",
                        "Provider One",
                        "Provider One",
                        "individual",
                        "telegram_handle",
                        "example_provider_one",
                        "https://t.me/example_belgrade_cleaning/101",
                        provider1_seen,
                        provider1_seen,
                        "run-dashboard-1",
                        "run-dashboard-1",
                        1,
                        1,
                        "high",
                        ["+381600000004"],
                        ["example_provider_one"],
                        ["https://t.me/example_provider_one"],
                        ["one@example.com"],
                        ["https://provider-one.example.com"],
                        ["belgrade"],
                        ["cleaning"],
                        ["example_belgrade_cleaning"],
                    ),
                    (
                        "provider-db-dash-2",
                        "accepted",
                        "provisional",
                        "Provider Two",
                        "",
                        "team",
                        "phone",
                        "+381600000005",
                        "https://t.me/example_subotica_services/202",
                        provider2_seen,
                        provider2_seen,
                        "run-dashboard-2",
                        "run-dashboard-2",
                        1,
                        1,
                        "medium",
                        ["+381600000005"],
                        ["example_provider_two"],
                        ["https://t.me/example_provider_two"],
                        ["two@example.com"],
                        ["https://provider-two.example.com"],
                        [],
                        ["repair"],
                        ["example_subotica_services"],
                    ),
                ],
            )

            cursor.executemany(
                """
                INSERT INTO offers (
                    offer_key,
                    provider_key,
                    offer_state,
                    service_signature_key,
                    category_primary,
                    category_secondary,
                    title_best,
                    price_text_best,
                    price_min,
                    price_max,
                    currency_code,
                    latest_post_url,
                    first_seen_at_utc,
                    last_seen_at_utc,
                    first_seen_run_id,
                    last_seen_run_id,
                    times_seen,
                    dedupe_confidence,
                    serbia_relevance_verdict,
                    service_tags,
                    city_codes
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    (
                        "offer-db-dash-1",
                        "provider-db-dash-1",
                        "candidate",
                        "svc-cleaning-1",
                        "cleaning",
                        "apartment_cleaning",
                        "Apartment Cleaning",
                        "30 EUR",
                        Decimal("30"),
                        Decimal("30"),
                        "EUR",
                        "https://t.me/example_belgrade_cleaning/101",
                        offer1_seen,
                        offer1_seen,
                        "run-dashboard-1",
                        "run-dashboard-1",
                        1,
                        "high",
                        "serbia_relevant",
                        ["cleaning"],
                        ["belgrade"],
                    ),
                    (
                        "offer-db-dash-2",
                        "provider-db-dash-2",
                        "stale",
                        "svc-repair-1",
                        "",
                        "",
                        "Home Repair",
                        "",
                        None,
                        None,
                        "",
                        "https://t.me/example_subotica_services/202",
                        offer2_seen,
                        offer2_seen,
                        "run-dashboard-2",
                        "run-dashboard-2",
                        1,
                        "medium",
                        "serbia_relevant",
                        ["repair"],
                        [],
                    ),
                ],
            )

            cursor.executemany(
                """
                INSERT INTO raw_posts (
                    raw_post_id,
                    source_platform,
                    chat_id,
                    message_id,
                    source_channel_key,
                    chat_title,
                    chat_kind,
                    chat_username,
                    post_url,
                    posted_at_utc,
                    text_raw,
                    text_normalized,
                    text_hash_normalized,
                    text_length,
                    first_seen_run_id,
                    first_seen_at_utc,
                    last_seen_run_id,
                    last_seen_at_utc,
                    first_seen_target_input,
                    last_seen_target_input,
                    last_seen_target_resolved,
                    posted_year_month,
                    posted_iso_week
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    (
                        "tg:dash:100:101",
                        "telegram",
                        "100",
                        101,
                        "example_belgrade_cleaning",
                        "Belgrade Cleaning",
                        "channel",
                        "example_belgrade_cleaning",
                        "https://t.me/example_belgrade_cleaning/101",
                        raw_post1_time,
                        "Apartment cleaning in Belgrade",
                        "Apartment cleaning in Belgrade",
                        "hash-dash-1",
                        31,
                        "run-dashboard-1",
                        raw_post1_time,
                        "run-dashboard-1",
                        raw_post1_time,
                        "@example_belgrade_cleaning",
                        "@example_belgrade_cleaning",
                        "https://t.me/example_belgrade_cleaning",
                        raw_post1_time.strftime("%Y-%m"),
                        _iso_week(raw_post1_time),
                    ),
                    (
                        "tg:dash:200:202",
                        "telegram",
                        "200",
                        202,
                        "example_subotica_services",
                        "Subotica Services",
                        "channel",
                        "example_subotica_services",
                        "https://t.me/example_subotica_services/202",
                        raw_post2_time,
                        "Home repair in Subotica",
                        "Home repair in Subotica",
                        "hash-dash-2",
                        24,
                        "run-dashboard-2",
                        raw_post2_time,
                        "run-dashboard-2",
                        raw_post2_time,
                        "@example_subotica_services",
                        "@example_subotica_services",
                        "https://t.me/example_subotica_services",
                        raw_post2_time.strftime("%Y-%m"),
                        _iso_week(raw_post2_time),
                    ),
                ],
            )

            cursor.executemany(
                """
                INSERT INTO provider_raw_post_evidence (
                    provider_key,
                    raw_post_id,
                    first_seen_run_id,
                    last_seen_run_id
                )
                VALUES (%s, %s, %s, %s)
                """,
                [
                    ("provider-db-dash-1", "tg:dash:100:101", "run-dashboard-1", "run-dashboard-1"),
                    ("provider-db-dash-2", "tg:dash:200:202", "run-dashboard-2", "run-dashboard-2"),
                ],
            )

            cursor.executemany(
                """
                INSERT INTO offer_raw_post_evidence (
                    offer_key,
                    raw_post_id,
                    first_seen_run_id,
                    last_seen_run_id
                )
                VALUES (%s, %s, %s, %s)
                """,
                [
                    ("offer-db-dash-1", "tg:dash:100:101", "run-dashboard-1", "run-dashboard-1"),
                    ("offer-db-dash-2", "tg:dash:200:202", "run-dashboard-2", "run-dashboard-2"),
                ],
            )

            cursor.executemany(
                """
                INSERT INTO audit_enrichment_rows (
                    audit_row_id,
                    run_id,
                    entity_type,
                    entity_id,
                    stage,
                    processor_type,
                    processor_version,
                    status,
                    decision_code,
                    created_at_utc,
                    output_patch_json,
                    reason_text,
                    latency_ms,
                    review_required,
                    attempt_number,
                    model_name,
                    prompt_version,
                    tokens_input,
                    tokens_output,
                    cost_estimate_usd,
                    confidence,
                    response_excerpt
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                [
                    (
                        "audit:run-dashboard-1:offer:1",
                        "run-dashboard-1",
                        "offer",
                        "offer-db-dash-1",
                        "llm_service_relevance",
                        "llm",
                        "extr_llm_05_v1",
                        "accepted",
                        "service_accept",
                        run1_finished - timedelta(minutes=1),
                        Jsonb({"offer_state": "candidate"}),
                        "Accepted cleaning offer",
                        320,
                        False,
                        1,
                        "gpt-5-mini-2025-08-07",
                        "post_merge_llm_v1_service_relevance",
                        210,
                        44,
                        Decimal("0.0019"),
                        Decimal("0.9100"),
                        "accepted",
                    ),
                    (
                        "audit:run-dashboard-2:provider:1",
                        "run-dashboard-2",
                        "provider",
                        "provider-db-dash-2",
                        "provider_merge",
                        "deterministic",
                        "merge_v1",
                        "success",
                        "provider_observed",
                        run2_finished - timedelta(minutes=1),
                        Jsonb({"provider_state": "accepted"}),
                        "Provider retained for dashboard drilldown proof",
                        25,
                        True,
                        1,
                        "",
                        "",
                        0,
                        0,
                        None,
                        Decimal("0.6200"),
                        "review suggested",
                    ),
                ],
            )

            cursor.executemany(
                """
                INSERT INTO audit_source_raw_posts (
                    audit_row_id,
                    raw_post_id
                )
                VALUES (%s, %s)
                """,
                [
                    ("audit:run-dashboard-1:offer:1", "tg:dash:100:101"),
                    ("audit:run-dashboard-2:provider:1", "tg:dash:200:202"),
                ],
            )

        connection.commit()


@unittest.skipUnless(os.environ.get("TG_SERVICES_DB_DSN"), "TG_SERVICES_DB_DSN is not set")
class DashboardReadViewsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_dsn = os.environ["TG_SERVICES_DB_DSN"]
        cls.schema_name = f"tz_data_dash_05_{uuid.uuid4().hex[:10]}"
        cls.schema_dsn = _schema_dsn(cls.base_dsn, cls.schema_name)
        _apply_migrations(cls.base_dsn, cls.schema_name)
        _seed_dashboard_rows(cls.schema_dsn)

    @classmethod
    def tearDownClass(cls) -> None:
        _drop_schema(cls.base_dsn, cls.schema_name)

    def test_view_columns_match_contract(self) -> None:
        with psycopg.connect(self.schema_dsn) as connection:
            with connection.cursor() as cursor:
                for view_name, expected_columns in EXPECTED_VIEW_COLUMNS.items():
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = %s
                          AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (self.schema_name, view_name),
                    )
                    observed_columns = [row[0] for row in cursor.fetchall()]
                    self.assertEqual(observed_columns, expected_columns, view_name)

    def test_view_dependencies_stay_inside_canonical_db_boundary(self) -> None:
        with psycopg.connect(self.schema_dsn) as connection:
            with connection.cursor() as cursor:
                for view_name, expected_dependencies in EXPECTED_VIEW_DEPENDENCIES.items():
                    cursor.execute(
                        """
                        SELECT DISTINCT table_name
                        FROM information_schema.view_table_usage
                        WHERE view_schema = %s
                          AND view_name = %s
                        ORDER BY table_name
                        """,
                        (self.schema_name, view_name),
                    )
                    observed_dependencies = {row[0] for row in cursor.fetchall()}
                    self.assertEqual(observed_dependencies, expected_dependencies, view_name)

    def test_dashboard_views_return_expected_shapes(self) -> None:
        with psycopg.connect(self.schema_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT offer_key, provider_display_name, freshness_bucket
                    FROM offers_catalog
                    ORDER BY offer_key
                    """
                )
                self.assertEqual(
                    cursor.fetchall(),
                    [
                        ("offer-db-dash-1", "Provider One", "fresh_0_7d"),
                        ("offer-db-dash-2", "Provider Two", "stale_91d_plus"),
                    ],
                )

                cursor.execute(
                    """
                    SELECT provider_key, provider_display_name, freshness_bucket, linked_offers_json
                    FROM providers_directory
                    ORDER BY provider_key
                    """
                )
                provider_rows = cursor.fetchall()
                self.assertEqual(provider_rows[0][0:3], ("provider-db-dash-1", "Provider One", "fresh_0_7d"))
                self.assertEqual(provider_rows[0][3][0]["offer_key"], "offer-db-dash-1")
                self.assertEqual(provider_rows[1][0:3], ("provider-db-dash-2", "Provider Two", "stale_91d_plus"))
                self.assertEqual(provider_rows[1][3][0]["offer_state"], "stale")

                cursor.execute(
                    """
                    SELECT run_id, run_status, targets_json
                    FROM run_monitoring
                    ORDER BY run_id
                    """
                )
                run_rows = cursor.fetchall()
                self.assertEqual(len(run_rows), 2)
                self.assertEqual(run_rows[0][0:2], ("run-dashboard-1", "partial_success"))
                self.assertEqual(len(run_rows[0][2]), 2)
                self.assertEqual({target["target_status"] for target in run_rows[0][2]}, {"success", "error"})
                self.assertEqual(run_rows[1][0:2], ("run-dashboard-2", "success"))
                self.assertEqual(len(run_rows[1][2]), 1)

                cursor.execute(
                    """
                    SELECT audit_row_id, entity_type, entity_label, source_raw_posts_json
                    FROM audit_review_drilldown
                    ORDER BY audit_row_id
                    """
                )
                audit_rows = cursor.fetchall()
                self.assertEqual(audit_rows[0][0:3], ("audit:run-dashboard-1:offer:1", "offer", "Apartment Cleaning"))
                self.assertEqual(audit_rows[0][3][0]["raw_post_id"], "tg:dash:100:101")
                self.assertEqual(audit_rows[1][0:3], ("audit:run-dashboard-2:provider:1", "provider", "Provider Two"))
                self.assertEqual(audit_rows[1][3][0]["source_channel_key"], "example_subotica_services")

                cursor.execute(
                    """
                    SELECT
                        metric_family,
                        metric_bucket,
                        offer_state,
                        provider_state,
                        identity_strength,
                        category_primary,
                        city_code,
                        target_status,
                        metric_value,
                        requested_targets_total,
                        successful_targets_total,
                        failed_targets_total,
                        raw_posts_total,
                        providers_total,
                        offers_total,
                        raw_posts_emitted_total
                    FROM freshness_coverage_metrics
                    ORDER BY metric_family, metric_bucket, offer_state, provider_state, identity_strength
                    """
                )
                metric_rows = cursor.fetchall()
                metrics = [
                    {
                        "metric_family": row[0],
                        "metric_bucket": row[1],
                        "offer_state": row[2],
                        "provider_state": row[3],
                        "identity_strength": row[4],
                        "category_primary": row[5],
                        "city_code": row[6],
                        "target_status": row[7],
                        "metric_value": row[8],
                        "requested_targets_total": row[9],
                        "successful_targets_total": row[10],
                        "failed_targets_total": row[11],
                        "raw_posts_total": row[12],
                        "providers_total": row[13],
                        "offers_total": row[14],
                        "raw_posts_emitted_total": row[15],
                    }
                    for row in metric_rows
                ]

                self.assertIn(
                    {
                        "metric_family": "offer_freshness",
                        "metric_bucket": "fresh_0_7d",
                        "offer_state": "candidate",
                        "provider_state": "",
                        "identity_strength": "",
                        "category_primary": "",
                        "city_code": "",
                        "target_status": "",
                        "metric_value": 1,
                        "requested_targets_total": None,
                        "successful_targets_total": None,
                        "failed_targets_total": None,
                        "raw_posts_total": None,
                        "providers_total": None,
                        "offers_total": None,
                        "raw_posts_emitted_total": None,
                    },
                    metrics,
                )
                self.assertIn(
                    {
                        "metric_family": "offer_category_coverage",
                        "metric_bucket": "uncategorized",
                        "offer_state": "stale",
                        "provider_state": "",
                        "identity_strength": "",
                        "category_primary": "uncategorized",
                        "city_code": "",
                        "target_status": "",
                        "metric_value": 1,
                        "requested_targets_total": None,
                        "successful_targets_total": None,
                        "failed_targets_total": None,
                        "raw_posts_total": None,
                        "providers_total": None,
                        "offers_total": None,
                        "raw_posts_emitted_total": None,
                    },
                    metrics,
                )
                self.assertIn(
                    {
                        "metric_family": "offer_city_coverage",
                        "metric_bucket": "unknown",
                        "offer_state": "stale",
                        "provider_state": "",
                        "identity_strength": "",
                        "category_primary": "",
                        "city_code": "unknown",
                        "target_status": "",
                        "metric_value": 1,
                        "requested_targets_total": None,
                        "successful_targets_total": None,
                        "failed_targets_total": None,
                        "raw_posts_total": None,
                        "providers_total": None,
                        "offers_total": None,
                        "raw_posts_emitted_total": None,
                    },
                    metrics,
                )
                self.assertIn(
                    {
                        "metric_family": "provider_city_coverage",
                        "metric_bucket": "unknown",
                        "offer_state": "",
                        "provider_state": "accepted",
                        "identity_strength": "provisional",
                        "category_primary": "",
                        "city_code": "unknown",
                        "target_status": "",
                        "metric_value": 1,
                        "requested_targets_total": None,
                        "successful_targets_total": None,
                        "failed_targets_total": None,
                        "raw_posts_total": None,
                        "providers_total": None,
                        "offers_total": None,
                        "raw_posts_emitted_total": None,
                    },
                    metrics,
                )
                self.assertIn(
                    {
                        "metric_family": "run_target_coverage",
                        "metric_bucket": "error",
                        "offer_state": "",
                        "provider_state": "",
                        "identity_strength": "",
                        "category_primary": "",
                        "city_code": "",
                        "target_status": "error",
                        "metric_value": 1,
                        "requested_targets_total": None,
                        "successful_targets_total": None,
                        "failed_targets_total": None,
                        "raw_posts_total": None,
                        "providers_total": None,
                        "offers_total": None,
                        "raw_posts_emitted_total": 0,
                    },
                    metrics,
                )
                self.assertIn(
                    {
                        "metric_family": "run_summary",
                        "metric_bucket": "all_runs",
                        "offer_state": "",
                        "provider_state": "",
                        "identity_strength": "",
                        "category_primary": "",
                        "city_code": "",
                        "target_status": "",
                        "metric_value": 2,
                        "requested_targets_total": 3,
                        "successful_targets_total": 2,
                        "failed_targets_total": 1,
                        "raw_posts_total": 2,
                        "providers_total": 2,
                        "offers_total": 2,
                        "raw_posts_emitted_total": None,
                    },
                    metrics,
                )


if __name__ == "__main__":
    unittest.main()
