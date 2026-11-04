{{ config(materialized='ephemeral') }}

select *, cast(created_at as date) as created_day,
    case when source_status = 'CLOSED' then 'closed'
         when source_status in ('OPEN', 'IN PROGRESS', 'ASSIGNED', 'STARTED', 'PENDING') then 'open'
         else 'unknown' end as lifecycle
from {{ ref('stg_service_requests') }}
