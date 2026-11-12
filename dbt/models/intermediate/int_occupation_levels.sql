-- The newest occupation issue, one row per region, occupation and skill level, with each
-- measure for the reporting month and for the same month a year earlier side by side.
-- A null value means the BA suppressed or left out that cell; 0 means no cases.
with latest as (
    select max(vintage) as vintage from {{ ref('stg_ba__occupation_levels') }}
),

issue as (
    select o.*
    from {{ ref('stg_ba__occupation_levels') }} as o
    inner join latest using (vintage)
)

select
    vintage,
    region_code,
    any_value(region_name) as region_name,
    any_value(region_kind) as region_kind,
    occupation_code,
    any_value(occupation_digits) as occupation_digits,
    any_value(occupation_label) as occupation_label,
    skill_level,
    {%- for measure in ['unemployed', 'jobseekers', 'vacancies', 'vacancy_inflow_12m'] %}
    max(value) filter (where measure = '{{ measure }}' and period = vintage) as {{ measure }},
    max(value_status) filter (where measure = '{{ measure }}' and period = vintage)
        as {{ measure }}_status,
    max(value) filter (where measure = '{{ measure }}' and period < vintage)
        as {{ measure }}_year_before
    {%- if not loop.last %},{% endif %}
    {%- endfor %}
from issue
group by vintage, region_code, occupation_code, skill_level
