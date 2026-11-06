{#- Use the configured schema name as-is (staging, intermediate, marts, reference),
    instead of dbt's default "<target>_<custom>". -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name is not none else target.schema }}
{%- endmacro %}
