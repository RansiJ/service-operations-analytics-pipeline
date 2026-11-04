-- Only the normalized CTE from transform.sql; classification/quality/marts stay there.
select
    r.unique_key as request_id,
    try_cast(nullif(trim(r.created_date), '') as timestamp) as created_at,
    try_cast(nullif(trim(r.closed_date), '') as timestamp) as closed_at,
    coalesce(nullif(upper(regexp_replace(trim(r.agency), '\s+', ' ', 'g')), ''), 'UNKNOWN') as agency,
    coalesce(nullif(trim(r.agency_name), ''), 'Unknown') as agency_name,
    coalesce(nullif(upper(regexp_replace(trim(r.complaint_type), '\s+', ' ', 'g')), ''), 'UNKNOWN') as category,
    coalesce(nullif(upper(trim(r.borough)), ''), 'UNKNOWN') as borough,
    coalesce(nullif(upper(regexp_replace(trim(r.status), '\s+', ' ', 'g')), ''), 'UNKNOWN') as source_status,
    r.closed_date as raw_closed_date,
    try_cast(r.source_updated_at as timestamptz) as source_updated_at,
    r.fetched_at as observed_at,
    m.run_id,
    r.last_run_id,
    {{ poc_literal('snapshot_id') }} as snapshot_id
from {{ source('nyc311', 'raw_requests') }} r
join {{ source('nyc311', 'run_members') }} m on r.unique_key = m.unique_key
where m.run_id = {{ poc_literal('run_id') }}
