-- Registered vacancies per 1,000 unemployed by skill level, for Germany, West, East and
-- each Land, from the newest occupation issue. Grain: one row per region and skill level
-- (the total included, "keine Angabe" left out).
--
-- Shares are of the region's total, which includes "keine Angabe": unemployed people
-- without a stated target level, about 6% nationally. So the four levels' shares add up to
-- a little under 1.
{%- set min_base = var('min_occupation_unemployed') %}

with base as (
    select *
    from {{ ref('int_occupation_levels') }}
    where occupation_code = 'total' and skill_level <> 'unknown'
),

totals as (
    select region_code, unemployed as region_unemployed, vacancies as region_vacancies
    from base
    where skill_level = 'total'
),

rated as (
    select
        b.vintage,
        b.region_code,
        b.region_name,
        b.region_kind,
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
            when b.unemployed_year_before > 0
                then 100.0 * (b.unemployed - b.unemployed_year_before) / b.unemployed_year_before
        end as unemployed_change_pct,
        b.unemployed * 1.0 / nullif(t.region_unemployed, 0) as share_of_unemployed,
        b.vacancies * 1.0 / nullif(t.region_vacancies, 0) as share_of_vacancies,
        case
            when b.unemployed_status <> 'value' or b.vacancies_status not in ('value', 'zero')
                then 'suppressed or missing in the BA table'
            when b.unemployed < {{ min_base }}
                then 'fewer than {{ min_base }} unemployed'
            else ''
        end as not_ranked_reason
    from base as b
    inner join totals as t using (region_code)
    inner join {{ ref('skill_levels') }} as l using (skill_level)
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
                partition by skill_level, is_ranked
                order by vacancies_per_1000_unemployed desc
            )
    end as rank_among_lands
from flagged
