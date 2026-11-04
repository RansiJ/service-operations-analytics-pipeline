select rule, count(*) as affected_requests
from (select unnest(quality_flags) as rule from {{ ref('fct_service_requests') }})
group by rule
