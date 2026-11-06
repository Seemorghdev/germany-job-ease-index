-- One row per month in the unemployment history, with national totals as a sanity check.
with national as (
    select
        period as month_start,
        count(*) filter (where value_status = 'value') as districts_reported,
        sum(unemployed) as national_unemployed
    from {{ ref('int_unemployment_monthly') }}
    group by period
)

select
    m.month_start,
    strftime(m.month_start, '%Y-%m') as month_label,
    year(m.month_start) as year,
    month(m.month_start) as month,
    quarter(m.month_start) as quarter,
    m.month_start = (select max(month_start) from {{ ref('int_months') }}) as is_latest,
    coalesce(n.districts_reported, 0) as districts_reported,
    n.national_unemployed
from {{ ref('int_months') }} as m
left join national as n using (month_start)
