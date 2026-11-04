select request_id from {{ ref('stg_service_requests') }}
where run_id is distinct from {{ poc_literal('run_id') }}
   or snapshot_id is distinct from {{ poc_literal('snapshot_id') }}
union all
select 'audit_count_mismatch'
from {{ source('nyc311', 'pipeline_runs') }}
where run_id = {{ poc_literal('run_id') }}
  and loaded_count <> (select count(*) from {{ ref('stg_service_requests') }})
