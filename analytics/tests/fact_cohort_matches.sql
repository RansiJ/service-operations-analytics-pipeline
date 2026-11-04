(select request_id from {{ ref('stg_service_requests') }}
 except all select request_id from {{ ref('fct_service_requests') }})
union all
(select request_id from {{ ref('fct_service_requests') }}
 except all select request_id from {{ ref('stg_service_requests') }})
