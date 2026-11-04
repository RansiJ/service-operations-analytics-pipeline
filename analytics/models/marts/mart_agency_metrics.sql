select agency, count(*) as total_requests,
    count(*) filter (where lifecycle = 'open') as open_requests,
    count(*) filter (where lifecycle = 'closed') as closed_requests,
    count(*) filter (where lifecycle = 'unknown') as unknown_status_requests,
    count(resolution_hours) as resolution_eligible_requests,
    median(resolution_hours) as median_resolution_hours,
    count(*) filter (where not is_valid) as flagged_requests
from {{ ref('fct_service_requests') }} group by agency
