-- Processing invariants: anomalous dates/statuses are retained, never rejected here.
select request_id from {{ ref('fct_service_requests') }}
where created_day is distinct from cast(created_at as date)
   or lifecycle is distinct from case
        when source_status = 'CLOSED' then 'closed'
        when source_status in ('OPEN', 'IN PROGRESS', 'ASSIGNED', 'STARTED', 'PENDING') then 'open'
        else 'unknown' end
   or is_valid is distinct from (len(quality_flags) = 0)
   or (resolution_hours is not null) is distinct from
        coalesce(lifecycle = 'closed' and closed_at >= created_at, false)
   or resolution_hours < 0
   or (resolution_hours is not null and
       resolution_hours is distinct from epoch(closed_at - created_at) / 3600.0)
   or resolution_band is distinct from case
        when resolution_hours is null then 'Unavailable'
        when resolution_hours < 24 then '0-24 hours'
        when resolution_hours < 72 then '24-72 hours'
        when resolution_hours < 168 then '72-168 hours'
        else '168+ hours' end
