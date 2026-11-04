with expected_days as (
    select cast(d as date) as created_day
    from {{ source('nyc311', 'pipeline_runs') }} p,
         generate_series(cast(p.window_start as timestamp),
                         cast(p.window_end as timestamp) - interval 1 day, interval 1 day) t(d)
    where run_id = {{ poc_literal('run_id') }}
), checked as (
    -- Independent correlated calculation, rather than repeating the model's window frame.
    select d.*, p.n, p.mean
    from {{ ref('mart_daily_metrics') }} d,
    lateral (
        select count(*) as n, avg(total_requests) as mean
        from {{ ref('mart_daily_metrics') }} prior
        where prior.created_day >= d.created_day - interval 7 day
          and prior.created_day < d.created_day
    ) p
)
(select created_day from expected_days except all
 select created_day from {{ ref('mart_daily_metrics') }})
union all
(select created_day from {{ ref('mart_daily_metrics') }} except all
 select created_day from expected_days)
union all
select created_day from checked
where baseline_days is distinct from n
   or previous_7day_mean is distinct from mean
   or volume_ratio is distinct from case when n = 7 and mean > 0 then total_requests / mean end
   or review_volume_spike is distinct from (n = 7 and mean > 0 and total_requests >= 1.5 * mean)
