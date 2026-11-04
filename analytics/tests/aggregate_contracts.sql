{% for model in ['mart_overall_metrics', 'mart_category_metrics', 'mart_agency_metrics', 'mart_daily_metrics'] %}
select '{{ model }}' as failed_model from {{ ref(model) }}
where total_requests is null or total_requests < 0
   or total_requests is distinct from open_requests + closed_requests + unknown_status_requests
   or resolution_eligible_requests < 0 or resolution_eligible_requests > closed_requests
   or flagged_requests < 0 or flagged_requests > total_requests
   or (resolution_eligible_requests = 0) is distinct from (median_resolution_hours is null)
   or median_resolution_hours < 0
union all
{% endfor %}
select 'overall_cardinality_or_denominator'
where (select count(*) from {{ ref('mart_overall_metrics') }}) <> 1
   or exists (
       select 1 from {{ ref('mart_overall_metrics') }}
       where total_requests <> (select count(*) from {{ ref('fct_service_requests') }})
          or valid_requests + flagged_requests is distinct from total_requests
          or flagged_pct is distinct from 100.0 * flagged_requests / nullif(total_requests, 0)
   )
{% for model in ['mart_category_metrics', 'mart_agency_metrics', 'mart_daily_metrics'] %}
union all
select '{{ model }}_total'
where (select coalesce(sum(total_requests), 0) from {{ ref(model) }}) <>
      (select count(*) from {{ ref('fct_service_requests') }}
       {% if model == 'mart_daily_metrics' %} where created_at is not null {% endif %})
{% endfor %}
