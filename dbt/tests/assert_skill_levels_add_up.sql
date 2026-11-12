-- In every region, occupation, measure and month, the skill levels never add up to more
-- than the occupation's total ("keine Angabe" included). Only checked where every cell
-- involved is known (a value or "-"), so a suppressed level can't trip it.
-- The levels may fall short: the BA leaves out level rows it won't show (October 2026:
-- 3,353 of 23,942 cells short, by 1-3 in most, never over). A level row read under the
-- wrong occupation, or a measure read from the wrong column, would push some sums over.
with sums as (
    select
        vintage,
        period,
        region_code,
        occupation_code,
        measure,
        max(value) filter (where skill_level = 'total') as total,
        bool_and(value_status in ('value', 'zero')) filter (where skill_level = 'total')
            as total_known,
        sum(value) filter (where skill_level <> 'total') as levels_sum,
        bool_and(value_status in ('value', 'zero')) filter (where skill_level <> 'total')
            as levels_known
    from {{ ref('stg_ba__occupation_levels') }}
    group by vintage, period, region_code, occupation_code, measure
)

select *
from sums
where total_known and levels_known and levels_sum > total
