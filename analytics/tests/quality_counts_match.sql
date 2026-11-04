with expected as (
    select rule, count(*) as affected_requests
    from (select unnest(quality_flags) as rule from {{ ref('fct_service_requests') }})
    group by rule
)
(select * from expected except all select * from {{ ref('mart_quality_issues') }})
union all
(select * from {{ ref('mart_quality_issues') }} except all select * from expected)
