with days as (
    select cast(d as date) as created_day
    from {{ source('nyc311', 'pipeline_runs') }} p,
         generate_series(cast(p.window_start as timestamp),
                         cast(p.window_end as timestamp) - interval 1 day, interval 1 day) t(d)
    where p.run_id = {{ poc_literal('run_id') }}
), counts as (
    select d.created_day, count(r.request_id) as total_requests,
        count(*) filter (where lifecycle = 'open') as open_requests,
        count(*) filter (where lifecycle = 'closed') as closed_requests,
        count(*) filter (where lifecycle = 'unknown') as unknown_status_requests,
        count(resolution_hours) as resolution_eligible_requests,
        median(resolution_hours) as median_resolution_hours,
        count(r.request_id) filter (where not is_valid) as flagged_requests
    from days d left join {{ ref('fct_service_requests') }} r using (created_day)
    group by d.created_day
), baseline as (
    select *, avg(total_requests) over (
        order by created_day rows between 7 preceding and 1 preceding
    ) as previous_7day_mean,
    count(*) over (order by created_day rows between 7 preceding and 1 preceding) as baseline_days
    from counts
)
select *, case when baseline_days = 7 and previous_7day_mean > 0
    then total_requests / previous_7day_mean end as volume_ratio,
    baseline_days = 7 and previous_7day_mean > 0
        and total_requests >= 1.5 * previous_7day_mean as review_volume_spike
from baseline
