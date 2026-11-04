{% macro poc_literal(name) -%}
  {% set value = var(name) %}
  {% if value is not string or not value | trim %}
    {{ exceptions.raise_compiler_error(name ~ ' must be an explicit nonempty string') }}
  {% endif %}
  '{{ value | replace("'", "''") }}'
{%- endmacro %}

{% macro poc_fingerprint(relation, order_by) -%}
  (select md5(coalesce(string_agg(to_json(t), chr(10) order by {{ order_by }}), ''))
   from {{ relation }} t)
{%- endmacro %}

{% macro validate_poc_snapshot() %}
  {% set run_id = poc_literal('run_id') %}
  {% set snapshot_id = poc_literal('snapshot_id') %}
  {% if target.schema != 'dbt_staging' or not target.path.endswith('_poc.duckdb') %}
    {{ exceptions.raise_compiler_error('POC requires dbt_staging and a *_poc.duckdb test database') }}
  {% endif %}
  {% if execute %}
    {% set validation %}
      select count(*) from {{ source('poc', 'dbt_poc_snapshot') }} s
      join {{ source('nyc311', 'pipeline_runs') }} p on s.run_id = p.run_id
      where s.run_id = {{ run_id }} and s.snapshot_id = {{ snapshot_id }}
        and p.status = 'success'
        and p.loaded_count = (select count(*) from {{ source('nyc311', 'run_members') }}
                              where run_id = {{ run_id }})
        and s.raw_hash = {{ poc_fingerprint(source('nyc311', 'raw_requests'), 'unique_key') }}
        and s.members_hash = {{ poc_fingerprint(source('nyc311', 'run_members'), 'run_id, unique_key') }}
        and s.runs_hash = {{ poc_fingerprint(source('nyc311', 'pipeline_runs'), 'run_id') }}
    {% endset %}
    {% set result = run_query(validation) %}
    {% if result.rows[0][0] != 1 %}
      {{ exceptions.raise_compiler_error('Unknown, changed, incomplete or mismatched POC snapshot/run_id') }}
    {% endif %}
  {% endif %}
  select 1
{% endmacro %}
