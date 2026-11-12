-- The 16 Länder, and West plus East, add up to Germany for every occupation, skill level,
-- measure and month where all the cells involved are known.
-- Unemployed people must match exactly. Germany also counts job seekers and vacancies that
-- belong to no Land (no German address, workplace abroad), so for those the parts may fall
-- short of Germany but never exceed it (October 2026: job seekers 19,182 short, vacancies
-- 641). Catches a sheet assigned to the wrong region or a Land read twice.
with parts as (
    select
        vintage,
        period,
        occupation_code,
        skill_level,
        measure,
        max(value) filter (where region_code = 'DE') as germany,
        max(value) filter (where region_code = 'W') as west,
        max(value) filter (where region_code = 'O') as east,
        sum(value) filter (where region_kind = 'land') as lands_sum,
        count(*) filter (where region_kind = 'land' and value_status in ('value', 'zero'))
            as lands_known,
        bool_and(value_status in ('value', 'zero')) filter (where region_kind <> 'land')
            as wide_known
    from {{ ref('stg_ba__occupation_levels') }}
    group by vintage, period, occupation_code, skill_level, measure
),

checked as (
    select 'lands' as check_name, *, lands_sum as parts_sum
    from parts
    where wide_known and lands_known = 16

    union all

    select 'west plus east' as check_name, *, west + east as parts_sum
    from parts
    where wide_known
)

select *
from checked
where parts_sum > germany
    or (measure = 'unemployed' and parts_sum <> germany)
