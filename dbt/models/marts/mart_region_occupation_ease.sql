-- Registered vacancies per 1,000 unemployed by occupation group (KldB 2010, 2 digits) and
-- skill level, for Germany, West, East and each Land, from the newest occupation issue.
-- Grain: one row per region, occupation group and skill level (the total included).
-- `short_label` is set for the groups in the occupation_shortlist seed.
{%- set min_base = var('min_occupation_unemployed') %}

with base as (
    select *
    from {{ ref('int_occupation_levels') }}
    where occupation_digits = 2 and skill_level <> 'unknown'
),

rated as (
    select
        b.vintage,
        b.region_code,
        b.region_name,
        b.region_kind,
        b.occupation_code,
        b.occupation_label,
        s.short_label,
        b.skill_level,
        l.label_de as skill_label,
        l.sort_order,
        b.unemployed,
        b.vacancies,
        b.unemployed_year_before,
        b.vacancies_year_before,
        case
            when b.unemployed_status = 'value'
                and b.unemployed >= {{ min_base }}
                and b.vacancies_status in ('value', 'zero')
                then b.vacancies * 1000.0 / b.unemployed
        end as vacancies_per_1000_unemployed,
        case
            when b.vacancies_year_before > 0
                then 100.0 * (b.vacancies - b.vacancies_year_before) / b.vacancies_year_before
        end as vacancies_change_pct,
        case
            when b.unemployed_status is null or b.vacancies_status is null
                then 'no row for this level in the BA table'
            when b.unemployed_status <> 'value' or b.vacancies_status not in ('value', 'zero')
                then 'suppressed or missing in the BA table'
            when b.unemployed < {{ min_base }}
                then 'fewer than {{ min_base }} unemployed'
            else ''
        end as not_ranked_reason
    from base as b
    inner join {{ ref('skill_levels') }} as l using (skill_level)
    left join {{ ref('occupation_shortlist') }} as s using (occupation_code)
),

flagged as (
    select
        *,
        region_kind = 'land' and vacancies_per_1000_unemployed is not null as is_ranked
    from rated
)

select
    *,
    case
        when is_ranked
            then rank() over (
                partition by occupation_code, skill_level, is_ranked
                order by vacancies_per_1000_unemployed desc
            )
    end as rank_among_lands
from flagged
