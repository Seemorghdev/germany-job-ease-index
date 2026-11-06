-- Every district code that appears in the unemployment history, current or abolished.
-- Type comes from the current district list (int_districts), so abolished codes have none.
with series as (
    select
        district_code,
        arg_max(district_label, period) as district_name,
        min(period) filter (where value_status = 'value') as first_month,
        max(period) filter (where value_status = 'value') as last_month,
        count(*) filter (where value_status = 'value') as months_with_count
    from {{ ref('int_unemployment_monthly') }}
    group by district_code
)

select
    s.district_code,
    s.district_name,
    left(s.district_code, 2) as land_code,
    l.land_name,
    d.district_type,
    d.is_kreisfrei,
    c.change,
    c.effective as change_effective,
    c.counterpart_code,
    s.first_month,
    s.last_month,
    s.months_with_count,
    s.last_month = (select max(month_start) from {{ ref('int_months') }}) as is_current
from series as s
left join {{ ref('lands') }} as l on l.land_code = left(s.district_code, 2)
left join {{ ref('int_districts') }} as d using (district_code)
left join {{ ref('district_changes') }} as c using (district_code)
