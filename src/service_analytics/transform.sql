-- RAW preserves source strings; TRY_CAST surfaces malformed dates without aborting.
CREATE OR REPLACE TABLE requests AS
WITH normalized AS (
    SELECT r.unique_key AS request_id,
        TRY_CAST(NULLIF(trim(r.created_date), '') AS TIMESTAMP) AS created_at,
        TRY_CAST(NULLIF(trim(r.closed_date), '') AS TIMESTAMP) AS closed_at,
        COALESCE(NULLIF(upper(regexp_replace(trim(agency), '\s+', ' ', 'g')), ''), 'UNKNOWN') AS agency,
        COALESCE(NULLIF(trim(agency_name), ''), 'Unknown') AS agency_name,
        COALESCE(NULLIF(upper(regexp_replace(trim(complaint_type), '\s+', ' ', 'g')), ''), 'UNKNOWN') AS category,
        COALESCE(NULLIF(upper(trim(borough)), ''), 'UNKNOWN') AS borough,
        COALESCE(NULLIF(upper(regexp_replace(trim(status), '\s+', ' ', 'g')), ''), 'UNKNOWN') AS source_status,
        r.closed_date AS raw_closed_date,
        TRY_CAST(source_updated_at AS TIMESTAMPTZ) AS source_updated_at,
        r.fetched_at AS observed_at
    FROM raw_requests r JOIN run_members m ON r.unique_key = m.unique_key
    WHERE m.run_id = $run_id
), classified AS (
    SELECT *, CAST(created_at AS DATE) AS created_day,
        CASE WHEN source_status = 'CLOSED' THEN 'closed'
             WHEN source_status IN ('OPEN', 'IN PROGRESS', 'ASSIGNED', 'STARTED', 'PENDING') THEN 'open'
             ELSE 'unknown' END AS lifecycle
    FROM normalized
), flagged AS (
    SELECT * EXCLUDE (raw_closed_date),
        list_filter([
            CASE WHEN created_at IS NULL THEN 'missing_or_invalid_created_date' END,
            CASE WHEN NULLIF(trim(raw_closed_date), '') IS NOT NULL AND closed_at IS NULL THEN 'invalid_closed_date' END,
            CASE WHEN closed_at < created_at THEN 'negative_resolution_interval' END,
            CASE WHEN lifecycle = 'closed' AND closed_at IS NULL THEN 'closed_without_date' END,
            CASE WHEN lifecycle = 'open' AND closed_at IS NOT NULL THEN 'open_with_closed_date' END,
            CASE WHEN lifecycle = 'unknown' THEN 'unknown_status' END,
            CASE WHEN agency = 'UNKNOWN' THEN 'missing_agency' END,
            CASE WHEN category = 'UNKNOWN' THEN 'missing_category' END
        ], x -> x IS NOT NULL) AS quality_flags,
        CASE WHEN lifecycle = 'closed' AND closed_at >= created_at
             THEN epoch(closed_at - created_at) / 3600.0 END AS resolution_hours
    FROM classified
)
SELECT *, len(quality_flags) = 0 AS is_valid,
    CASE WHEN resolution_hours IS NULL THEN 'Unavailable'
         WHEN resolution_hours < 24 THEN '0-24 hours'
         WHEN resolution_hours < 72 THEN '24-72 hours'
         WHEN resolution_hours < 168 THEN '72-168 hours'
         ELSE '168+ hours' END AS resolution_band
FROM flagged;

CREATE OR REPLACE TABLE metrics AS
SELECT COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'open') AS open_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'closed') AS closed_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'unknown') AS unknown_status_requests,
    COUNT(resolution_hours) AS resolution_eligible_requests,
    median(resolution_hours) AS median_resolution_hours,
    COUNT(*) FILTER (WHERE NOT is_valid) AS flagged_requests,
    COUNT(*) FILTER (WHERE is_valid) AS valid_requests,
    100.0 * COUNT(*) FILTER (WHERE NOT is_valid) / NULLIF(COUNT(*), 0) AS flagged_pct
FROM requests;

-- A date spine makes zero-volume days visible. Seven-day comparison is descriptive.
CREATE OR REPLACE TABLE daily_metrics AS
WITH days AS (
    SELECT CAST(d AS DATE) AS created_day
    FROM pipeline_runs p,
         generate_series(CAST(p.window_start AS TIMESTAMP),
                         CAST(p.window_end AS TIMESTAMP) - INTERVAL 1 DAY, INTERVAL 1 DAY) t(d)
    WHERE p.run_id = $run_id
), counts AS (
    SELECT d.created_day, COUNT(r.request_id) AS total_requests,
        COUNT(*) FILTER (WHERE lifecycle = 'open') AS open_requests,
        COUNT(*) FILTER (WHERE lifecycle = 'closed') AS closed_requests,
        COUNT(*) FILTER (WHERE lifecycle = 'unknown') AS unknown_status_requests,
        COUNT(resolution_hours) AS resolution_eligible_requests,
        median(resolution_hours) AS median_resolution_hours,
        COUNT(r.request_id) FILTER (WHERE NOT is_valid) AS flagged_requests
    FROM days d LEFT JOIN requests r USING (created_day) GROUP BY d.created_day
), baseline AS (
    SELECT *, AVG(total_requests) OVER (
        ORDER BY created_day ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
    ) AS previous_7day_mean,
    COUNT(*) OVER (ORDER BY created_day ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS baseline_days
    FROM counts
)
SELECT *, CASE WHEN baseline_days = 7 AND previous_7day_mean > 0
    THEN total_requests / previous_7day_mean END AS volume_ratio,
    baseline_days = 7 AND previous_7day_mean > 0
        AND total_requests >= 1.5 * previous_7day_mean AS review_volume_spike
FROM baseline;

CREATE OR REPLACE TABLE category_metrics AS
SELECT category, COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'open') AS open_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'closed') AS closed_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'unknown') AS unknown_status_requests,
    COUNT(resolution_hours) AS resolution_eligible_requests,
    median(resolution_hours) AS median_resolution_hours,
    COUNT(*) FILTER (WHERE NOT is_valid) AS flagged_requests
FROM requests GROUP BY category;

CREATE OR REPLACE TABLE agency_metrics AS
SELECT agency, COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'open') AS open_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'closed') AS closed_requests,
    COUNT(*) FILTER (WHERE lifecycle = 'unknown') AS unknown_status_requests,
    COUNT(resolution_hours) AS resolution_eligible_requests,
    median(resolution_hours) AS median_resolution_hours,
    COUNT(*) FILTER (WHERE NOT is_valid) AS flagged_requests
FROM requests GROUP BY agency;

CREATE OR REPLACE TABLE quality_issues AS
SELECT rule, COUNT(*) AS affected_requests
FROM (SELECT unnest(quality_flags) AS rule FROM requests) GROUP BY rule;
