-- Tests formatting, never business quality. NULL dates and anomalous statuses stay.
select request_id from {{ ref('stg_service_requests') }}
where agency = '' or category = '' or source_status = ''
   or agency is distinct from upper(agency)
   or category is distinct from upper(category)
   or source_status is distinct from upper(source_status)
   or agency_name is null or agency_name = '' or agency_name <> trim(agency_name)
   or borough is null or borough = '' or borough <> upper(trim(borough))
