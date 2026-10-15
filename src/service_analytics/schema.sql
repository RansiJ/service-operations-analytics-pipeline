CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id VARCHAR PRIMARY KEY, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    window_start DATE, window_end DATE, status VARCHAR,
    source_count BIGINT, extracted_count BIGINT DEFAULT 0, loaded_count BIGINT DEFAULT 0,
    rejected_count BIGINT DEFAULT 0, duplicate_count BIGINT DEFAULT 0,
    flagged_count BIGINT DEFAULT 0, error VARCHAR
);

CREATE TABLE IF NOT EXISTS raw_requests (
    unique_key VARCHAR PRIMARY KEY,
    created_date VARCHAR, closed_date VARCHAR, agency VARCHAR, agency_name VARCHAR,
    complaint_type VARCHAR, descriptor VARCHAR, status VARCHAR, borough VARCHAR,
    resolution_action_updated_date VARCHAR, source_updated_at VARCHAR,
    source_payload JSON NOT NULL, fetched_at TIMESTAMPTZ, last_run_id VARCHAR
);

CREATE TABLE IF NOT EXISTS run_members (
    run_id VARCHAR, unique_key VARCHAR, PRIMARY KEY (run_id, unique_key)
);

CREATE TABLE IF NOT EXISTS raw_rejections (
    run_id VARCHAR, row_number BIGINT, source_payload JSON, reason VARCHAR
);
