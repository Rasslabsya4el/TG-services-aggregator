BEGIN;

-- Task: DATA-DB-SCHEMA-05
-- First repo-owned PostgreSQL baseline for canonical business tables.
--
-- Included in this migration:
-- - service_runs
-- - run_targets
-- - providers
-- - offers
--
-- Explicitly deferred to the next provenance/identity wave:
-- - raw_posts
-- - audit_enrichment_rows
-- - provider_identity_keys
-- - provider_raw_post_evidence
-- - offer_raw_post_evidence
-- - audit_source_raw_posts
--
-- Do not invent fallback JSON/array mirrors for deferred identity/evidence data
-- inside the four core tables below. Those write targets remain owned by the
-- deferred child-table wave.

CREATE TABLE service_runs (
    run_id TEXT PRIMARY KEY,
    run_status TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    started_at_utc TIMESTAMPTZ NOT NULL,
    finished_at_utc TIMESTAMPTZ,
    duration_ms BIGINT,
    requested_targets_count INTEGER NOT NULL DEFAULT 0,
    successful_target_count INTEGER NOT NULL DEFAULT 0,
    failed_target_count INTEGER NOT NULL DEFAULT 0,
    sync_mode TEXT NOT NULL,
    max_messages INTEGER,
    cutoff_policy_type TEXT NOT NULL,
    cutoff_policy_value TEXT NOT NULL DEFAULT '',
    llm_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    raw_posts_total INTEGER NOT NULL DEFAULT 0,
    providers_total INTEGER NOT NULL DEFAULT 0,
    offers_total INTEGER NOT NULL DEFAULT 0,
    offers_upserted_total INTEGER NOT NULL DEFAULT 0,
    fetch_messages_seen_total INTEGER NOT NULL DEFAULT 0,
    structured_posts_total INTEGER NOT NULL DEFAULT 0,
    llm_calls_total INTEGER NOT NULL DEFAULT 0,
    llm_tokens_input_total INTEGER NOT NULL DEFAULT 0,
    llm_tokens_output_total INTEGER NOT NULL DEFAULT 0,
    llm_cost_estimate_usd NUMERIC(12, 6) NOT NULL DEFAULT 0,
    llm_review_required_count INTEGER NOT NULL DEFAULT 0,
    error_type TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    google_sheet_id TEXT NOT NULL DEFAULT '',
    providers_sheet_name TEXT NOT NULL DEFAULT '',
    offers_sheet_name TEXT NOT NULL DEFAULT '',
    requested_targets_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    successful_targets_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    failed_targets_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    warnings_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    checkpoint_targets_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    layer_resolution_counts_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    field_resolution_counts_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    response_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    CONSTRAINT service_runs_run_id_not_blank CHECK (btrim(run_id) <> ''),
    CONSTRAINT service_runs_run_status_check CHECK (
        run_status IN ('started', 'success', 'partial_success', 'error', 'cancelled')
    ),
    CONSTRAINT service_runs_trigger_type_not_blank CHECK (btrim(trigger_type) <> ''),
    CONSTRAINT service_runs_sync_mode_not_blank CHECK (btrim(sync_mode) <> ''),
    CONSTRAINT service_runs_cutoff_policy_type_check CHECK (
        cutoff_policy_type IN ('since_date', 'days_back', 'months_back')
    ),
    CONSTRAINT service_runs_duration_nonnegative CHECK (
        duration_ms IS NULL OR duration_ms >= 0
    ),
    CONSTRAINT service_runs_finished_after_started CHECK (
        finished_at_utc IS NULL OR finished_at_utc >= started_at_utc
    ),
    CONSTRAINT service_runs_requested_targets_count_nonnegative CHECK (
        requested_targets_count >= 0
    ),
    CONSTRAINT service_runs_successful_target_count_nonnegative CHECK (
        successful_target_count >= 0
    ),
    CONSTRAINT service_runs_failed_target_count_nonnegative CHECK (
        failed_target_count >= 0
    ),
    CONSTRAINT service_runs_max_messages_nonnegative CHECK (
        max_messages IS NULL OR max_messages >= 0
    ),
    CONSTRAINT service_runs_raw_posts_total_nonnegative CHECK (
        raw_posts_total >= 0
    ),
    CONSTRAINT service_runs_providers_total_nonnegative CHECK (
        providers_total >= 0
    ),
    CONSTRAINT service_runs_offers_total_nonnegative CHECK (
        offers_total >= 0
    ),
    CONSTRAINT service_runs_offers_upserted_total_nonnegative CHECK (
        offers_upserted_total >= 0
    ),
    CONSTRAINT service_runs_fetch_messages_seen_total_nonnegative CHECK (
        fetch_messages_seen_total >= 0
    ),
    CONSTRAINT service_runs_structured_posts_total_nonnegative CHECK (
        structured_posts_total >= 0
    ),
    CONSTRAINT service_runs_llm_calls_total_nonnegative CHECK (
        llm_calls_total >= 0
    ),
    CONSTRAINT service_runs_llm_tokens_input_total_nonnegative CHECK (
        llm_tokens_input_total >= 0
    ),
    CONSTRAINT service_runs_llm_tokens_output_total_nonnegative CHECK (
        llm_tokens_output_total >= 0
    ),
    CONSTRAINT service_runs_llm_cost_estimate_usd_nonnegative CHECK (
        llm_cost_estimate_usd >= 0
    ),
    CONSTRAINT service_runs_llm_review_required_count_nonnegative CHECK (
        llm_review_required_count >= 0
    ),
    CONSTRAINT service_runs_requested_targets_json_array CHECK (
        jsonb_typeof(requested_targets_json) = 'array'
    ),
    CONSTRAINT service_runs_successful_targets_json_array CHECK (
        jsonb_typeof(successful_targets_json) = 'array'
    ),
    CONSTRAINT service_runs_failed_targets_json_array CHECK (
        jsonb_typeof(failed_targets_json) = 'array'
    ),
    CONSTRAINT service_runs_warnings_json_array CHECK (
        jsonb_typeof(warnings_json) = 'array'
    ),
    CONSTRAINT service_runs_checkpoint_targets_json_array CHECK (
        jsonb_typeof(checkpoint_targets_json) = 'array'
    ),
    CONSTRAINT service_runs_layer_resolution_counts_json_object CHECK (
        jsonb_typeof(layer_resolution_counts_json) = 'object'
    ),
    CONSTRAINT service_runs_field_resolution_counts_json_object CHECK (
        jsonb_typeof(field_resolution_counts_json) = 'object'
    ),
    CONSTRAINT service_runs_response_json_object CHECK (
        jsonb_typeof(response_json) = 'object'
    )
);

COMMENT ON TABLE service_runs IS
    'Canonical business run log. Upsert boundary: run_id.';

CREATE TABLE run_targets (
    run_id TEXT NOT NULL,
    target_key TEXT NOT NULL,
    target_input TEXT NOT NULL,
    target_resolved TEXT NOT NULL DEFAULT '',
    target_status TEXT NOT NULL,
    started_at_utc TIMESTAMPTZ,
    finished_at_utc TIMESTAMPTZ,
    checkpoint_message_id BIGINT,
    raw_posts_emitted INTEGER NOT NULL DEFAULT 0,
    error_type TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    target_stats_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    CONSTRAINT run_targets_pk PRIMARY KEY (run_id, target_key),
    CONSTRAINT run_targets_service_runs_fk
        FOREIGN KEY (run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT run_targets_target_key_not_blank CHECK (btrim(target_key) <> ''),
    CONSTRAINT run_targets_target_input_not_blank CHECK (btrim(target_input) <> ''),
    CONSTRAINT run_targets_target_status_check CHECK (
        target_status IN ('requested', 'success', 'error', 'skipped')
    ),
    CONSTRAINT run_targets_finished_after_started CHECK (
        started_at_utc IS NULL OR finished_at_utc IS NULL OR finished_at_utc >= started_at_utc
    ),
    CONSTRAINT run_targets_raw_posts_emitted_nonnegative CHECK (
        raw_posts_emitted >= 0
    ),
    CONSTRAINT run_targets_target_stats_json_object CHECK (
        jsonb_typeof(target_stats_json) = 'object'
    )
);

COMMENT ON TABLE run_targets IS
    'Per-target run detail. Upsert boundary: (run_id, target_key). Sheets run_target_row_key is not canonical.';

CREATE TABLE providers (
    provider_key TEXT PRIMARY KEY,
    provider_state TEXT NOT NULL,
    identity_strength TEXT NOT NULL,
    display_name_best TEXT NOT NULL DEFAULT '',
    canonical_name TEXT NOT NULL DEFAULT '',
    provider_type TEXT NOT NULL DEFAULT '',
    provider_summary TEXT NOT NULL DEFAULT '',
    primary_contact_type TEXT NOT NULL DEFAULT '',
    primary_contact_value TEXT NOT NULL DEFAULT '',
    latest_post_url TEXT NOT NULL DEFAULT '',
    first_seen_at_utc TIMESTAMPTZ NOT NULL,
    last_seen_at_utc TIMESTAMPTZ NOT NULL,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    times_seen INTEGER NOT NULL DEFAULT 0,
    offer_count INTEGER NOT NULL DEFAULT 0,
    dedupe_confidence TEXT NOT NULL DEFAULT '',
    provider_merge_override_group TEXT NOT NULL DEFAULT '',
    provider_suppression_reason TEXT NOT NULL DEFAULT '',
    phones TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    telegram_handles TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    telegram_links TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    instagram_handles TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    instagram_links TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    emails TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    websites TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    facebook_links TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    city_codes TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    service_category_hints TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    source_channel_keys TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    provider_quality_flags_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    CONSTRAINT providers_provider_key_not_blank CHECK (btrim(provider_key) <> ''),
    CONSTRAINT providers_provider_state_check CHECK (
        provider_state IN ('candidate', 'accepted', 'suppressed', 'rejected')
    ),
    CONSTRAINT providers_identity_strength_check CHECK (
        identity_strength IN ('strong', 'provisional')
    ),
    CONSTRAINT providers_first_seen_run_id_not_blank CHECK (
        btrim(first_seen_run_id) <> ''
    ),
    CONSTRAINT providers_last_seen_run_id_not_blank CHECK (
        btrim(last_seen_run_id) <> ''
    ),
    CONSTRAINT providers_last_seen_after_first_seen CHECK (
        last_seen_at_utc >= first_seen_at_utc
    ),
    CONSTRAINT providers_times_seen_nonnegative CHECK (
        times_seen >= 0
    ),
    CONSTRAINT providers_offer_count_nonnegative CHECK (
        offer_count >= 0
    ),
    CONSTRAINT providers_dedupe_confidence_check CHECK (
        dedupe_confidence IN ('', 'low', 'medium', 'high')
    ),
    CONSTRAINT providers_provider_quality_flags_json_array CHECK (
        jsonb_typeof(provider_quality_flags_json) = 'array'
    ),
    CONSTRAINT providers_first_seen_run_fk
        FOREIGN KEY (first_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT providers_last_seen_run_fk
        FOREIGN KEY (last_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE providers IS
    'Canonical provider row. Upsert boundary: provider_key. Strong identity-key exclusivity lands in deferred provider_identity_keys.';

CREATE TABLE offers (
    offer_key TEXT PRIMARY KEY,
    provider_key TEXT NOT NULL,
    offer_state TEXT NOT NULL,
    service_signature_key TEXT NOT NULL,
    category_primary TEXT NOT NULL DEFAULT '',
    category_secondary TEXT NOT NULL DEFAULT '',
    title_best TEXT NOT NULL DEFAULT '',
    description_best TEXT NOT NULL DEFAULT '',
    description_full_best TEXT NOT NULL DEFAULT '',
    offer_summary TEXT NOT NULL DEFAULT '',
    price_text_best TEXT NOT NULL DEFAULT '',
    price_min NUMERIC(12, 2),
    price_max NUMERIC(12, 2),
    currency_code TEXT NOT NULL DEFAULT '',
    latest_post_url TEXT NOT NULL DEFAULT '',
    first_seen_at_utc TIMESTAMPTZ NOT NULL,
    last_seen_at_utc TIMESTAMPTZ NOT NULL,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    times_seen INTEGER NOT NULL DEFAULT 0,
    dedupe_confidence TEXT NOT NULL DEFAULT '',
    serbia_relevance_verdict TEXT NOT NULL DEFAULT '',
    offer_rejection_reason TEXT NOT NULL DEFAULT '',
    offer_merge_override_group TEXT NOT NULL DEFAULT '',
    service_tags TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    city_codes TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    contact_snapshot_phones TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    contact_snapshot_telegram_handles TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    contact_snapshot_telegram_links TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    source_channel_keys TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    offer_quality_flags_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    CONSTRAINT offers_provider_service_signature_uq UNIQUE (provider_key, service_signature_key),
    CONSTRAINT offers_provider_fk
        FOREIGN KEY (provider_key) REFERENCES providers (provider_key)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT offers_first_seen_run_fk
        FOREIGN KEY (first_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT offers_last_seen_run_fk
        FOREIGN KEY (last_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT offers_offer_key_not_blank CHECK (btrim(offer_key) <> ''),
    CONSTRAINT offers_provider_key_not_blank CHECK (btrim(provider_key) <> ''),
    CONSTRAINT offers_service_signature_key_not_blank CHECK (
        btrim(service_signature_key) <> ''
    ),
    CONSTRAINT offers_offer_state_check CHECK (
        offer_state IN ('candidate', 'accepted', 'suppressed', 'rejected', 'stale')
    ),
    CONSTRAINT offers_first_seen_run_id_not_blank CHECK (
        btrim(first_seen_run_id) <> ''
    ),
    CONSTRAINT offers_last_seen_run_id_not_blank CHECK (
        btrim(last_seen_run_id) <> ''
    ),
    CONSTRAINT offers_last_seen_after_first_seen CHECK (
        last_seen_at_utc >= first_seen_at_utc
    ),
    CONSTRAINT offers_times_seen_nonnegative CHECK (
        times_seen >= 0
    ),
    CONSTRAINT offers_dedupe_confidence_check CHECK (
        dedupe_confidence IN ('', 'low', 'medium', 'high')
    ),
    CONSTRAINT offers_price_min_nonnegative CHECK (
        price_min IS NULL OR price_min >= 0
    ),
    CONSTRAINT offers_price_max_nonnegative CHECK (
        price_max IS NULL OR price_max >= 0
    ),
    CONSTRAINT offers_price_range_check CHECK (
        price_min IS NULL OR price_max IS NULL OR price_max >= price_min
    ),
    CONSTRAINT offers_serbia_relevance_verdict_check CHECK (
        serbia_relevance_verdict IN ('', 'serbia_relevant', 'outside_serbia', 'uncertain')
    ),
    CONSTRAINT offers_offer_quality_flags_json_array CHECK (
        jsonb_typeof(offer_quality_flags_json) = 'array'
    )
);

COMMENT ON TABLE offers IS
    'Canonical offer row. Upsert boundary: offer_key. Natural intra-provider dedupe also enforced by UNIQUE(provider_key, service_signature_key).';

COMMIT;
