{#
    Dialect compatibility layer.

    Every model in this project is written once and compiles to both DuckDB and
    BigQuery. The only places the two dialects genuinely diverge for this
    warehouse are date arithmetic, safe casting and date-series generation, so
    those four are isolated here. Nothing else in models/ branches on adapter
    type - if you find yourself adding a target.type check inside a model, it
    belongs in this file instead.
#}


{% macro datediff_days(start_date, end_date) %}
{#- Whole days between two dates: end - start. -#}
{%- if target.type == 'bigquery' -%}
    date_diff({{ end_date }}, {{ start_date }}, day)
{%- else -%}
    date_diff('day', {{ start_date }}, {{ end_date }})
{%- endif -%}
{% endmacro %}


{% macro date_trunc_to(date_part, date_column) %}
{%- if target.type == 'bigquery' -%}
    date_trunc({{ date_column }}, {{ date_part }})
{%- else -%}
    date_trunc('{{ date_part }}', {{ date_column }})
{%- endif -%}
{% endmacro %}


{% macro safe_cast(column, type) %}
{#- Cast that yields null on failure instead of erroring the whole load. Used
    anywhere a value originates from a free-text source field. -#}
{%- if target.type == 'bigquery' -%}
    safe_cast({{ column }} as {{ type }})
{%- else -%}
    try_cast({{ column }} as {{ type }})
{%- endif -%}
{% endmacro %}


{% macro date_spine(start_date, end_date) %}
{#- FROM-clause fragment producing a date series correlated against an
    enclosing relation (typically a bounds CTE holding start/end columns).
    Emits the leading comma so the model reads as one continuous FROM list.
    DuckDB's unnest is implicitly lateral; BigQuery takes UNNEST directly as
    a comma cross join over a value table. Both yield a single date_day
    column, inclusive of both bounds. -#}
{%- if target.type == 'bigquery' -%}
, unnest(generate_date_array({{ start_date }}, {{ end_date }}, interval 1 day)) as date_day
{%- else -%}
, unnest(generate_series({{ start_date }}, {{ end_date }}, interval '1 day')) as date_day(date_day)
{%- endif -%}
{% endmacro %}


{% macro surrogate_key(columns) %}
{#- Null-safe, deterministic hash key. '__NULL__' is used rather than letting a
    null poison the concatenation, so two rows differing only by a null still
    hash differently instead of both collapsing to null. -#}
    md5(
    {%- for column in columns %}
        coalesce(cast({{ column }} as {{ dbt.type_string() }}), '__NULL__')
        {%- if not loop.last %} || '|' || {% endif -%}
    {% endfor -%}
    )
{% endmacro %}


{% macro generate_schema_name(custom_schema_name, node) -%}
{#- Overrides dbt's default of <target_schema>_<custom_schema>. In production a
    mart should live in `marts`, not `dev_marts`, and Looker Studio connections
    are configured per dataset - so the custom schema name is used verbatim. -#}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
