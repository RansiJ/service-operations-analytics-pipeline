-- Both directions catch missing RAW rows, extra IDs and incorrect cohort selection.
with expected as (
    select unique_key from {{ source('nyc311', 'run_members') }}
    where run_id = {{ poc_literal('run_id') }}
), actual as (
    select request_id from {{ ref('stg_service_requests') }}
)
(select unique_key from expected except all select request_id from actual)
union all
(select request_id from actual except all select unique_key from expected)
