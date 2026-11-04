-- Same request schema as the historical table; traceability remains in staging.
with flagged as (
    select * exclude (raw_closed_date, run_id, last_run_id, snapshot_id),
        list_filter([
            case when created_at is null then 'missing_or_invalid_created_date' end,
            case when nullif(trim(raw_closed_date), '') is not null and closed_at is null then 'invalid_closed_date' end,
            case when closed_at < created_at then 'negative_resolution_interval' end,
            case when lifecycle = 'closed' and closed_at is null then 'closed_without_date' end,
            case when lifecycle = 'open' and closed_at is not null then 'open_with_closed_date' end,
            case when lifecycle = 'unknown' then 'unknown_status' end,
            case when agency = 'UNKNOWN' then 'missing_agency' end,
            case when category = 'UNKNOWN' then 'missing_category' end
        ], x -> x is not null) as quality_flags,
        case when lifecycle = 'closed' and closed_at >= created_at
             then epoch(closed_at - created_at) / 3600.0 end as resolution_hours
    from {{ ref('int_service_requests_classified') }}
)
select *, len(quality_flags) = 0 as is_valid,
    case when resolution_hours is null then 'Unavailable'
         when resolution_hours < 24 then '0-24 hours'
         when resolution_hours < 72 then '24-72 hours'
         when resolution_hours < 168 then '72-168 hours'
         else '168+ hours' end as resolution_band
from flagged
