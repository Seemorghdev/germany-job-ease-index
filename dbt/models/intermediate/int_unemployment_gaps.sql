-- Months in which a district has no count, grouped into consecutive runs.
--   starts: the district's series begins after the first month (a new district code)
--   ends:   the series stops before the last month (the code was abolished)
--   gap:    months missing in between (suppressed, empty or zero values)
-- Every run needs a reason in seeds/unemployment_gap_reasons.csv. The key months are
-- chosen to stay fixed as history grows: `starts` is keyed by the first month with a
-- count, `ends` by the first month without one.
with months as (
    select * from {{ ref('int_months') }}
),

districts as (
    select distinct district_code from {{ ref('int_unemployment_monthly') }}
),

grid as (
    select
        d.district_code,
        m.month_start,
        m.month_index,
        coalesce(u.value_status, 'missing') as value_status
    from districts as d
    cross join months as m
    left join {{ ref('int_unemployment_monthly') }} as u
        on u.district_code = d.district_code and u.period = m.month_start
),

runs as (
    select
        district_code,
        month_start,
        value_status,
        month_index - row_number() over (
            partition by district_code order by month_index
        ) as run_id
    from grid
    where value_status <> 'value'
),

gaps as (
    select
        district_code,
        min(month_start) as gap_start,
        max(month_start) as gap_end,
        count(*) as months,
        array_to_string(list_sort(list_distinct(list(value_status))), ', ') as statuses
    from runs
    group by district_code, run_id
),

bounds as (
    select min(month_start) as first_month, max(month_start) as last_month from months
)

select
    g.district_code,
    case
        when g.gap_start = b.first_month and g.gap_end = b.last_month then 'never'
        when g.gap_start = b.first_month then 'starts'
        when g.gap_end = b.last_month then 'ends'
        else 'gap'
    end as kind,
    case
        when g.gap_start = b.first_month then cast(g.gap_end + interval 1 month as date)
        else g.gap_start
    end as from_month,
    case
        when g.gap_start > b.first_month and g.gap_end < b.last_month then g.gap_end
    end as to_month,
    g.gap_start,
    g.gap_end,
    g.months,
    g.statuses
from gaps as g
cross join bounds as b
