BEGIN;

-- Repo-owned PostgreSQL dashboard read layer for MVP surfaces.
--
-- Chosen representation: persistent SQL views owned by this repo and applied
-- through the tracked DB migration contour under scripts/db/migrations.
--
-- Grain-preserving rules:
-- - offers_catalog: one row per offer
-- - providers_directory: one row per provider, with optional linked-offer JSON
-- - run_monitoring: one row per run, with per-target detail in targets_json
-- - audit_review_drilldown: one row per audit row, with raw-post detail in
--   source_raw_posts_json
-- - freshness_coverage_metrics: one row per aggregate metric bucket
--
-- Read-boundary rules:
-- - these views depend only on canonical PostgreSQL tables
-- - they do not depend on Google Sheets tabs, n8n internal persistence, or
--   any runtime-local cache
-- - no default visibility filter is applied at the DB read layer; downstream
--   dashboards can filter by *_state columns explicitly

CREATE VIEW offers_catalog AS
SELECT
    o.offer_key,
    o.provider_key,
    COALESCE(NULLIF(p.canonical_name, ''), NULLIF(p.display_name_best, ''), o.provider_key) AS provider_display_name,
    o.offer_state,
    o.category_primary,
    o.category_secondary,
    o.title_best,
    o.price_text_best,
    o.price_min,
    o.price_max,
    o.currency_code,
    o.city_codes,
    o.service_tags,
    o.serbia_relevance_verdict,
    o.last_seen_at_utc,
    o.latest_post_url,
    o.dedupe_confidence,
    CASE
        WHEN o.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '7 days' THEN 'fresh_0_7d'
        WHEN o.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN 'recent_8_30d'
        WHEN o.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '90 days' THEN 'aging_31_90d'
        ELSE 'stale_91d_plus'
    END AS freshness_bucket
FROM offers AS o
JOIN providers AS p
    ON p.provider_key = o.provider_key;

COMMENT ON VIEW offers_catalog IS
    'Dashboard read surface. Grain: one offer. Source tables: offers + providers.';

CREATE VIEW providers_directory AS
SELECT
    p.provider_key,
    p.provider_state,
    p.identity_strength,
    p.canonical_name,
    p.display_name_best,
    COALESCE(NULLIF(p.canonical_name, ''), NULLIF(p.display_name_best, ''), p.provider_key) AS provider_display_name,
    p.provider_type,
    p.primary_contact_type,
    p.primary_contact_value,
    p.phones,
    p.telegram_handles,
    p.telegram_links,
    p.emails,
    p.websites,
    p.city_codes,
    p.service_category_hints,
    p.source_channel_keys,
    p.offer_count,
    p.last_seen_at_utc,
    p.latest_post_url,
    p.dedupe_confidence,
    CASE
        WHEN p.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '7 days' THEN 'fresh_0_7d'
        WHEN p.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN 'recent_8_30d'
        WHEN p.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '90 days' THEN 'aging_31_90d'
        ELSE 'stale_91d_plus'
    END AS freshness_bucket,
    COALESCE(offer_links.linked_offers_json, '[]'::JSONB) AS linked_offers_json
FROM providers AS p
LEFT JOIN LATERAL (
    SELECT
        jsonb_agg(
            jsonb_build_object(
                'offer_key', o.offer_key,
                'offer_state', o.offer_state,
                'category_primary', o.category_primary,
                'category_secondary', o.category_secondary,
                'title_best', o.title_best,
                'last_seen_at_utc', o.last_seen_at_utc,
                'latest_post_url', o.latest_post_url
            )
            ORDER BY o.last_seen_at_utc DESC, o.offer_key ASC
        ) AS linked_offers_json
    FROM offers AS o
    WHERE o.provider_key = p.provider_key
) AS offer_links
    ON TRUE;

COMMENT ON VIEW providers_directory IS
    'Dashboard read surface. Grain: one provider. Source tables: providers + offers.';

CREATE VIEW run_monitoring AS
SELECT
    sr.run_id,
    sr.run_status,
    sr.trigger_type,
    sr.started_at_utc,
    sr.finished_at_utc,
    sr.duration_ms,
    sr.requested_targets_count,
    sr.successful_target_count,
    sr.failed_target_count,
    sr.sync_mode,
    sr.max_messages,
    sr.cutoff_policy_type,
    sr.cutoff_policy_value,
    sr.llm_enabled,
    sr.raw_posts_total,
    sr.providers_total,
    sr.offers_total,
    sr.offers_upserted_total,
    sr.warnings_json,
    sr.error_type,
    sr.error_message,
    COALESCE(target_rows.targets_json, '[]'::JSONB) AS targets_json
FROM service_runs AS sr
LEFT JOIN LATERAL (
    SELECT
        jsonb_agg(
            jsonb_build_object(
                'target_key', rt.target_key,
                'target_input', rt.target_input,
                'target_resolved', rt.target_resolved,
                'target_status', rt.target_status,
                'started_at_utc', rt.started_at_utc,
                'finished_at_utc', rt.finished_at_utc,
                'checkpoint_message_id', rt.checkpoint_message_id,
                'raw_posts_emitted', rt.raw_posts_emitted,
                'error_type', rt.error_type,
                'error_message', rt.error_message
            )
            ORDER BY rt.target_key ASC
        ) AS targets_json
    FROM run_targets AS rt
    WHERE rt.run_id = sr.run_id
) AS target_rows
    ON TRUE;

COMMENT ON VIEW run_monitoring IS
    'Dashboard read surface. Grain: one run. Per-target detail is preserved in targets_json from run_targets.';

CREATE VIEW audit_review_drilldown AS
SELECT
    aer.audit_row_id,
    aer.run_id,
    aer.entity_type,
    aer.entity_id,
    CASE
        WHEN aer.entity_type = 'provider' THEN COALESCE(NULLIF(p.canonical_name, ''), NULLIF(p.display_name_best, ''), aer.entity_id)
        WHEN aer.entity_type = 'offer' THEN COALESCE(NULLIF(o.title_best, ''), NULLIF(o.offer_summary, ''), aer.entity_id)
        WHEN aer.entity_type = 'raw_post' THEN COALESCE(NULLIF(rp_entity.post_url, ''), aer.entity_id)
        WHEN aer.entity_type = 'run' THEN aer.entity_id
        ELSE aer.entity_id
    END AS entity_label,
    CASE
        WHEN aer.entity_type = 'provider' THEN p.latest_post_url
        WHEN aer.entity_type = 'offer' THEN o.latest_post_url
        WHEN aer.entity_type = 'raw_post' THEN rp_entity.post_url
        ELSE ''
    END AS entity_latest_post_url,
    aer.stage,
    aer.processor_type,
    aer.processor_version,
    aer.status,
    aer.decision_code,
    aer.created_at_utc,
    aer.reason_text,
    aer.latency_ms,
    aer.review_required,
    aer.attempt_number,
    aer.model_name,
    aer.prompt_version,
    aer.tokens_input,
    aer.tokens_output,
    aer.cost_estimate_usd,
    aer.confidence,
    aer.response_excerpt,
    aer.upstream_audit_row_id,
    aer.superseded_by_audit_row_id,
    aer.output_patch_json,
    COALESCE(raw_post_rows.source_raw_posts_json, '[]'::JSONB) AS source_raw_posts_json
FROM audit_enrichment_rows AS aer
LEFT JOIN providers AS p
    ON aer.entity_type = 'provider'
   AND p.provider_key = aer.entity_id
LEFT JOIN offers AS o
    ON aer.entity_type = 'offer'
   AND o.offer_key = aer.entity_id
LEFT JOIN raw_posts AS rp_entity
    ON aer.entity_type = 'raw_post'
   AND rp_entity.raw_post_id = aer.entity_id
LEFT JOIN service_runs AS sr_entity
    ON aer.entity_type = 'run'
   AND sr_entity.run_id = aer.entity_id
LEFT JOIN LATERAL (
    SELECT
        jsonb_agg(
            jsonb_build_object(
                'raw_post_id', rp.raw_post_id,
                'post_url', rp.post_url,
                'posted_at_utc', rp.posted_at_utc,
                'text_raw', rp.text_raw,
                'source_channel_key', rp.source_channel_key
            )
            ORDER BY rp.posted_at_utc DESC, rp.raw_post_id ASC
        ) AS source_raw_posts_json
    FROM audit_source_raw_posts AS asrp
    JOIN raw_posts AS rp
        ON rp.raw_post_id = asrp.raw_post_id
    WHERE asrp.audit_row_id = aer.audit_row_id
) AS raw_post_rows
    ON TRUE;

COMMENT ON VIEW audit_review_drilldown IS
    'Dashboard read surface. Grain: one audit row. Raw-post provenance is preserved in source_raw_posts_json.';

CREATE VIEW freshness_coverage_metrics AS
WITH offer_base AS (
    SELECT
        o.offer_key,
        o.offer_state,
        COALESCE(NULLIF(o.category_primary, ''), 'uncategorized') AS category_primary_bucket,
        CASE
            WHEN o.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '7 days' THEN 'fresh_0_7d'
            WHEN o.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN 'recent_8_30d'
            WHEN o.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '90 days' THEN 'aging_31_90d'
            ELSE 'stale_91d_plus'
        END AS freshness_bucket,
        CASE
            WHEN cardinality(o.city_codes) = 0 THEN ARRAY['unknown']::TEXT[]
            ELSE o.city_codes
        END AS city_codes,
        o.last_seen_at_utc
    FROM offers AS o
),
offer_city_base AS (
    SELECT
        ob.offer_state,
        ob.last_seen_at_utc,
        city.city_code
    FROM offer_base AS ob
    CROSS JOIN LATERAL unnest(ob.city_codes) AS city(city_code)
),
provider_base AS (
    SELECT
        p.provider_key,
        p.provider_state,
        p.identity_strength,
        CASE
            WHEN p.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '7 days' THEN 'fresh_0_7d'
            WHEN p.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '30 days' THEN 'recent_8_30d'
            WHEN p.last_seen_at_utc >= CURRENT_TIMESTAMP - INTERVAL '90 days' THEN 'aging_31_90d'
            ELSE 'stale_91d_plus'
        END AS freshness_bucket,
        CASE
            WHEN cardinality(p.city_codes) = 0 THEN ARRAY['unknown']::TEXT[]
            ELSE p.city_codes
        END AS city_codes,
        p.last_seen_at_utc
    FROM providers AS p
),
provider_city_base AS (
    SELECT
        pb.provider_state,
        pb.identity_strength,
        pb.last_seen_at_utc,
        city.city_code
    FROM provider_base AS pb
    CROSS JOIN LATERAL unnest(pb.city_codes) AS city(city_code)
)
SELECT
    'offer_freshness'::TEXT AS metric_family,
    ob.freshness_bucket AS metric_bucket,
    ob.freshness_bucket,
    ob.offer_state,
    ''::TEXT AS provider_state,
    ''::TEXT AS identity_strength,
    ''::TEXT AS category_primary,
    ''::TEXT AS city_code,
    ''::TEXT AS target_status,
    COUNT(*)::BIGINT AS metric_value,
    MAX(ob.last_seen_at_utc) AS latest_entity_seen_at_utc,
    NULL::TIMESTAMPTZ AS latest_run_started_at_utc,
    NULL::BIGINT AS requested_targets_total,
    NULL::BIGINT AS successful_targets_total,
    NULL::BIGINT AS failed_targets_total,
    NULL::BIGINT AS raw_posts_total,
    NULL::BIGINT AS providers_total,
    NULL::BIGINT AS offers_total,
    NULL::BIGINT AS raw_posts_emitted_total
FROM offer_base AS ob
GROUP BY ob.freshness_bucket, ob.offer_state

UNION ALL

SELECT
    'provider_freshness'::TEXT AS metric_family,
    pb.freshness_bucket AS metric_bucket,
    pb.freshness_bucket,
    ''::TEXT AS offer_state,
    pb.provider_state,
    pb.identity_strength,
    ''::TEXT AS category_primary,
    ''::TEXT AS city_code,
    ''::TEXT AS target_status,
    COUNT(*)::BIGINT AS metric_value,
    MAX(pb.last_seen_at_utc) AS latest_entity_seen_at_utc,
    NULL::TIMESTAMPTZ AS latest_run_started_at_utc,
    NULL::BIGINT AS requested_targets_total,
    NULL::BIGINT AS successful_targets_total,
    NULL::BIGINT AS failed_targets_total,
    NULL::BIGINT AS raw_posts_total,
    NULL::BIGINT AS providers_total,
    NULL::BIGINT AS offers_total,
    NULL::BIGINT AS raw_posts_emitted_total
FROM provider_base AS pb
GROUP BY pb.freshness_bucket, pb.provider_state, pb.identity_strength

UNION ALL

SELECT
    'offer_category_coverage'::TEXT AS metric_family,
    ob.category_primary_bucket AS metric_bucket,
    ''::TEXT AS freshness_bucket,
    ob.offer_state,
    ''::TEXT AS provider_state,
    ''::TEXT AS identity_strength,
    ob.category_primary_bucket AS category_primary,
    ''::TEXT AS city_code,
    ''::TEXT AS target_status,
    COUNT(*)::BIGINT AS metric_value,
    MAX(ob.last_seen_at_utc) AS latest_entity_seen_at_utc,
    NULL::TIMESTAMPTZ AS latest_run_started_at_utc,
    NULL::BIGINT AS requested_targets_total,
    NULL::BIGINT AS successful_targets_total,
    NULL::BIGINT AS failed_targets_total,
    NULL::BIGINT AS raw_posts_total,
    NULL::BIGINT AS providers_total,
    NULL::BIGINT AS offers_total,
    NULL::BIGINT AS raw_posts_emitted_total
FROM offer_base AS ob
GROUP BY ob.category_primary_bucket, ob.offer_state

UNION ALL

SELECT
    'offer_city_coverage'::TEXT AS metric_family,
    ocb.city_code AS metric_bucket,
    ''::TEXT AS freshness_bucket,
    ocb.offer_state,
    ''::TEXT AS provider_state,
    ''::TEXT AS identity_strength,
    ''::TEXT AS category_primary,
    ocb.city_code,
    ''::TEXT AS target_status,
    COUNT(*)::BIGINT AS metric_value,
    MAX(ocb.last_seen_at_utc) AS latest_entity_seen_at_utc,
    NULL::TIMESTAMPTZ AS latest_run_started_at_utc,
    NULL::BIGINT AS requested_targets_total,
    NULL::BIGINT AS successful_targets_total,
    NULL::BIGINT AS failed_targets_total,
    NULL::BIGINT AS raw_posts_total,
    NULL::BIGINT AS providers_total,
    NULL::BIGINT AS offers_total,
    NULL::BIGINT AS raw_posts_emitted_total
FROM offer_city_base AS ocb
GROUP BY ocb.city_code, ocb.offer_state

UNION ALL

SELECT
    'provider_city_coverage'::TEXT AS metric_family,
    pcb.city_code AS metric_bucket,
    ''::TEXT AS freshness_bucket,
    ''::TEXT AS offer_state,
    pcb.provider_state,
    pcb.identity_strength,
    ''::TEXT AS category_primary,
    pcb.city_code,
    ''::TEXT AS target_status,
    COUNT(*)::BIGINT AS metric_value,
    MAX(pcb.last_seen_at_utc) AS latest_entity_seen_at_utc,
    NULL::TIMESTAMPTZ AS latest_run_started_at_utc,
    NULL::BIGINT AS requested_targets_total,
    NULL::BIGINT AS successful_targets_total,
    NULL::BIGINT AS failed_targets_total,
    NULL::BIGINT AS raw_posts_total,
    NULL::BIGINT AS providers_total,
    NULL::BIGINT AS offers_total,
    NULL::BIGINT AS raw_posts_emitted_total
FROM provider_city_base AS pcb
GROUP BY pcb.city_code, pcb.provider_state, pcb.identity_strength

UNION ALL

SELECT
    'run_target_coverage'::TEXT AS metric_family,
    rt.target_status AS metric_bucket,
    ''::TEXT AS freshness_bucket,
    ''::TEXT AS offer_state,
    ''::TEXT AS provider_state,
    ''::TEXT AS identity_strength,
    ''::TEXT AS category_primary,
    ''::TEXT AS city_code,
    rt.target_status,
    COUNT(*)::BIGINT AS metric_value,
    NULL::TIMESTAMPTZ AS latest_entity_seen_at_utc,
    MAX(sr.started_at_utc) AS latest_run_started_at_utc,
    NULL::BIGINT AS requested_targets_total,
    NULL::BIGINT AS successful_targets_total,
    NULL::BIGINT AS failed_targets_total,
    NULL::BIGINT AS raw_posts_total,
    NULL::BIGINT AS providers_total,
    NULL::BIGINT AS offers_total,
    COALESCE(SUM(rt.raw_posts_emitted), 0)::BIGINT AS raw_posts_emitted_total
FROM run_targets AS rt
JOIN service_runs AS sr
    ON sr.run_id = rt.run_id
GROUP BY rt.target_status

UNION ALL

SELECT
    'run_summary'::TEXT AS metric_family,
    'all_runs'::TEXT AS metric_bucket,
    ''::TEXT AS freshness_bucket,
    ''::TEXT AS offer_state,
    ''::TEXT AS provider_state,
    ''::TEXT AS identity_strength,
    ''::TEXT AS category_primary,
    ''::TEXT AS city_code,
    ''::TEXT AS target_status,
    COUNT(*)::BIGINT AS metric_value,
    NULL::TIMESTAMPTZ AS latest_entity_seen_at_utc,
    MAX(sr.started_at_utc) AS latest_run_started_at_utc,
    COALESCE(SUM(sr.requested_targets_count), 0)::BIGINT AS requested_targets_total,
    COALESCE(SUM(sr.successful_target_count), 0)::BIGINT AS successful_targets_total,
    COALESCE(SUM(sr.failed_target_count), 0)::BIGINT AS failed_targets_total,
    COALESCE(SUM(sr.raw_posts_total), 0)::BIGINT AS raw_posts_total,
    COALESCE(SUM(sr.providers_total), 0)::BIGINT AS providers_total,
    COALESCE(SUM(sr.offers_total), 0)::BIGINT AS offers_total,
    NULL::BIGINT AS raw_posts_emitted_total
FROM service_runs AS sr;

COMMENT ON VIEW freshness_coverage_metrics IS
    'Dashboard read surface. Grain: one aggregate metric bucket. Source tables: offers, providers, service_runs, run_targets.';

COMMIT;
