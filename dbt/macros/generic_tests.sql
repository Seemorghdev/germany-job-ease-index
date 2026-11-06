{#- Generic tests. Defined here rather than pulled from a package, so the project has no
    external dbt dependencies. -#}

{% test accepted_range(model, column_name, min_value=none, max_value=none) %}
select *
from {{ model }}
where {{ column_name }} is not null
  and (
    {% if min_value is not none %}{{ column_name }} < {{ min_value }}{% else %}false{% endif %}
    or {% if max_value is not none %}{{ column_name }} > {{ max_value }}{% else %}false{% endif %}
  )
{% endtest %}


{% test unique_combination(model, combination) %}
select {{ combination | join(', ') }}, count(*) as occurrences
from {{ model }}
group by {{ combination | join(', ') }}
having count(*) > 1
{% endtest %}


{% test matches_pattern(model, column_name, pattern) %}
select *
from {{ model }}
where {{ column_name }} is not null
  and not regexp_full_match({{ column_name }}, '{{ pattern }}')
{% endtest %}
