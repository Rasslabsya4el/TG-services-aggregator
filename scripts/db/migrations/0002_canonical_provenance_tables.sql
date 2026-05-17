BEGIN;

-- Extends the repo-owned PostgreSQL contour beyond the accepted four-table
-- business-row slice with canonical provenance storage:
-- - raw_posts
-- - audit_enrichment_rows
-- - provider_raw_post_evidence
-- - offer_raw_post_evidence
-- - audit_source_raw_posts
--
-- Still explicitly deferred after this wave:
-- - provider_identity_keys
--
-- Provenance stays normalized in dedicated child tables. Do not mirror
-- evidence edges into JSON or array columns on providers/offers.

CREATE TABLE raw_posts (
    raw_post_id TEXT PRIMARY KEY,
    source_platform TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_id BIGINT NOT NULL,
    source_channel_key TEXT NOT NULL DEFAULT '',
    chat_title TEXT NOT NULL DEFAULT '',
    chat_kind TEXT NOT NULL DEFAULT '',
    chat_username TEXT NOT NULL DEFAULT '',
    post_url TEXT NOT NULL DEFAULT '',
    posted_at_utc TIMESTAMPTZ NOT NULL,
    text_raw TEXT NOT NULL DEFAULT '',
    text_normalized TEXT NOT NULL DEFAULT '',
    text_hash_normalized TEXT NOT NULL DEFAULT '',
    text_length INTEGER NOT NULL DEFAULT 0,
    has_media BOOLEAN NOT NULL DEFAULT FALSE,
    media_type TEXT NOT NULL DEFAULT '',
    views BIGINT NOT NULL DEFAULT 0,
    forwards BIGINT NOT NULL DEFAULT 0,
    replies BIGINT NOT NULL DEFAULT 0,
    grouped_id BIGINT,
    sender_id TEXT NOT NULL DEFAULT '',
    sender_kind TEXT NOT NULL DEFAULT '',
    sender_title TEXT NOT NULL DEFAULT '',
    sender_username TEXT NOT NULL DEFAULT '',
    sender_profile_url TEXT NOT NULL DEFAULT '',
    post_author TEXT NOT NULL DEFAULT '',
    first_seen_run_id TEXT NOT NULL,
    first_seen_at_utc TIMESTAMPTZ NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    last_seen_at_utc TIMESTAMPTZ NOT NULL,
    first_seen_target_input TEXT NOT NULL DEFAULT '',
    last_seen_target_input TEXT NOT NULL DEFAULT '',
    last_seen_target_resolved TEXT NOT NULL DEFAULT '',
    output_timezone_last TEXT NOT NULL DEFAULT '',
    posted_year_month TEXT NOT NULL DEFAULT '',
    posted_iso_week TEXT NOT NULL DEFAULT '',
    content_flags_json JSONB NOT NULL DEFAULT '[]'::JSONB,
    CONSTRAINT raw_posts_raw_post_id_not_blank CHECK (btrim(raw_post_id) <> ''),
    CONSTRAINT raw_posts_source_platform_check CHECK (source_platform IN ('telegram')),
    CONSTRAINT raw_posts_chat_id_not_blank CHECK (btrim(chat_id) <> ''),
    CONSTRAINT raw_posts_source_channel_key_not_blank CHECK (btrim(source_channel_key) <> ''),
    CONSTRAINT raw_posts_first_seen_run_id_not_blank CHECK (btrim(first_seen_run_id) <> ''),
    CONSTRAINT raw_posts_last_seen_run_id_not_blank CHECK (btrim(last_seen_run_id) <> ''),
    CONSTRAINT raw_posts_text_length_nonnegative CHECK (text_length >= 0),
    CONSTRAINT raw_posts_views_nonnegative CHECK (views >= 0),
    CONSTRAINT raw_posts_forwards_nonnegative CHECK (forwards >= 0),
    CONSTRAINT raw_posts_replies_nonnegative CHECK (replies >= 0),
    CONSTRAINT raw_posts_last_seen_after_first_seen CHECK (
        last_seen_at_utc >= first_seen_at_utc
    ),
    CONSTRAINT raw_posts_content_flags_json_array CHECK (
        jsonb_typeof(content_flags_json) = 'array'
    ),
    CONSTRAINT raw_posts_first_seen_run_fk
        FOREIGN KEY (first_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT raw_posts_last_seen_run_fk
        FOREIGN KEY (last_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE raw_posts IS
    'Immutable Telegram evidence keyed by raw_post_id. Upsert boundary: raw_post_id.';

CREATE TABLE provider_raw_post_evidence (
    provider_key TEXT NOT NULL,
    raw_post_id TEXT NOT NULL,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    CONSTRAINT provider_raw_post_evidence_pk PRIMARY KEY (provider_key, raw_post_id),
    CONSTRAINT provider_raw_post_evidence_provider_key_not_blank CHECK (btrim(provider_key) <> ''),
    CONSTRAINT provider_raw_post_evidence_raw_post_id_not_blank CHECK (btrim(raw_post_id) <> ''),
    CONSTRAINT provider_raw_post_evidence_first_seen_run_id_not_blank CHECK (
        btrim(first_seen_run_id) <> ''
    ),
    CONSTRAINT provider_raw_post_evidence_last_seen_run_id_not_blank CHECK (
        btrim(last_seen_run_id) <> ''
    ),
    CONSTRAINT provider_raw_post_evidence_provider_fk
        FOREIGN KEY (provider_key) REFERENCES providers (provider_key)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT provider_raw_post_evidence_raw_post_fk
        FOREIGN KEY (raw_post_id) REFERENCES raw_posts (raw_post_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT provider_raw_post_evidence_first_seen_run_fk
        FOREIGN KEY (first_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT provider_raw_post_evidence_last_seen_run_fk
        FOREIGN KEY (last_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE provider_raw_post_evidence IS
    'Canonical provider-to-raw-post evidence edges. Upsert boundary: (provider_key, raw_post_id).';

CREATE TABLE offer_raw_post_evidence (
    offer_key TEXT NOT NULL,
    raw_post_id TEXT NOT NULL,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    CONSTRAINT offer_raw_post_evidence_pk PRIMARY KEY (offer_key, raw_post_id),
    CONSTRAINT offer_raw_post_evidence_offer_key_not_blank CHECK (btrim(offer_key) <> ''),
    CONSTRAINT offer_raw_post_evidence_raw_post_id_not_blank CHECK (btrim(raw_post_id) <> ''),
    CONSTRAINT offer_raw_post_evidence_first_seen_run_id_not_blank CHECK (
        btrim(first_seen_run_id) <> ''
    ),
    CONSTRAINT offer_raw_post_evidence_last_seen_run_id_not_blank CHECK (
        btrim(last_seen_run_id) <> ''
    ),
    CONSTRAINT offer_raw_post_evidence_offer_fk
        FOREIGN KEY (offer_key) REFERENCES offers (offer_key)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT offer_raw_post_evidence_raw_post_fk
        FOREIGN KEY (raw_post_id) REFERENCES raw_posts (raw_post_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT offer_raw_post_evidence_first_seen_run_fk
        FOREIGN KEY (first_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT offer_raw_post_evidence_last_seen_run_fk
        FOREIGN KEY (last_seen_run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE offer_raw_post_evidence IS
    'Canonical offer-to-raw-post evidence edges. Upsert boundary: (offer_key, raw_post_id).';

CREATE TABLE audit_enrichment_rows (
    audit_row_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    processor_type TEXT NOT NULL,
    processor_version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    decision_code TEXT NOT NULL,
    created_at_utc TIMESTAMPTZ NOT NULL,
    input_fingerprint TEXT NOT NULL DEFAULT '',
    output_patch_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    reason_text TEXT NOT NULL DEFAULT '',
    latency_ms BIGINT,
    review_required BOOLEAN NOT NULL DEFAULT FALSE,
    attempt_number INTEGER NOT NULL DEFAULT 0,
    model_name TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '',
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    cost_estimate_usd NUMERIC(12, 6),
    confidence NUMERIC(6, 4),
    response_excerpt TEXT NOT NULL DEFAULT '',
    upstream_audit_row_id TEXT,
    superseded_by_audit_row_id TEXT,
    CONSTRAINT audit_enrichment_rows_audit_row_id_not_blank CHECK (btrim(audit_row_id) <> ''),
    CONSTRAINT audit_enrichment_rows_run_id_not_blank CHECK (btrim(run_id) <> ''),
    CONSTRAINT audit_enrichment_rows_entity_type_check CHECK (
        entity_type IN ('raw_post', 'provider', 'offer', 'run')
    ),
    CONSTRAINT audit_enrichment_rows_entity_id_not_blank CHECK (btrim(entity_id) <> ''),
    CONSTRAINT audit_enrichment_rows_stage_not_blank CHECK (btrim(stage) <> ''),
    CONSTRAINT audit_enrichment_rows_processor_type_check CHECK (
        processor_type IN ('n8n', 'deterministic', 'llm', 'manual')
    ),
    CONSTRAINT audit_enrichment_rows_status_check CHECK (
        status IN ('success', 'error', 'skipped', 'accepted', 'rejected')
    ),
    CONSTRAINT audit_enrichment_rows_decision_code_not_blank CHECK (btrim(decision_code) <> ''),
    CONSTRAINT audit_enrichment_rows_output_patch_json_object CHECK (
        jsonb_typeof(output_patch_json) = 'object'
    ),
    CONSTRAINT audit_enrichment_rows_latency_ms_nonnegative CHECK (
        latency_ms IS NULL OR latency_ms >= 0
    ),
    CONSTRAINT audit_enrichment_rows_attempt_number_nonnegative CHECK (
        attempt_number >= 0
    ),
    CONSTRAINT audit_enrichment_rows_tokens_input_nonnegative CHECK (
        tokens_input >= 0
    ),
    CONSTRAINT audit_enrichment_rows_tokens_output_nonnegative CHECK (
        tokens_output >= 0
    ),
    CONSTRAINT audit_enrichment_rows_cost_estimate_usd_nonnegative CHECK (
        cost_estimate_usd IS NULL OR cost_estimate_usd >= 0
    ),
    CONSTRAINT audit_enrichment_rows_confidence_range CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    CONSTRAINT audit_enrichment_rows_run_fk
        FOREIGN KEY (run_id) REFERENCES service_runs (run_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT audit_enrichment_rows_upstream_fk
        FOREIGN KEY (upstream_audit_row_id) REFERENCES audit_enrichment_rows (audit_row_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT audit_enrichment_rows_superseded_fk
        FOREIGN KEY (superseded_by_audit_row_id) REFERENCES audit_enrichment_rows (audit_row_id)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE audit_enrichment_rows IS
    'Append-only canonical audit provenance. Insert boundary: audit_row_id.';

CREATE TABLE audit_source_raw_posts (
    audit_row_id TEXT NOT NULL,
    raw_post_id TEXT NOT NULL,
    CONSTRAINT audit_source_raw_posts_pk PRIMARY KEY (audit_row_id, raw_post_id),
    CONSTRAINT audit_source_raw_posts_audit_row_id_not_blank CHECK (btrim(audit_row_id) <> ''),
    CONSTRAINT audit_source_raw_posts_raw_post_id_not_blank CHECK (btrim(raw_post_id) <> ''),
    CONSTRAINT audit_source_raw_posts_audit_fk
        FOREIGN KEY (audit_row_id) REFERENCES audit_enrichment_rows (audit_row_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT audit_source_raw_posts_raw_post_fk
        FOREIGN KEY (raw_post_id) REFERENCES raw_posts (raw_post_id)
        DEFERRABLE INITIALLY DEFERRED
);

COMMENT ON TABLE audit_source_raw_posts IS
    'Canonical audit-to-raw-post provenance edges. Insert boundary: (audit_row_id, raw_post_id).';

COMMIT;
