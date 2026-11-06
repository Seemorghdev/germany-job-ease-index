-- One row per current district for the map: boundary, residents, unemployed in the
-- latest month, and the change since 2019. The change is left empty where a recorded
-- reform after 2019 moved the district's boundaries, since the two figures would then
-- cover different areas. Aggregates only: publishable.
with latest as (
    select max(period) as last_month from {{ ref('fct_unemployment_monthly') }}
),

series as (
    select
        f.district_code,
        max(f.unemployed) filter (where f.period = l.last_month) as unemployed,
        avg(f.unemployed) filter (where year(f.period) = 2019) as avg_2019,
        avg(f.unemployed) filter (where f.period > l.last_month - interval 12 month)
            as avg_last_12_months
    from {{ ref('fct_unemployment_monthly') }} as f
    cross join latest as l
    where f.value_status = 'value'
    group by f.district_code
),

reformed as (
    select district_code from {{ ref('district_changes') }} where effective > date '2019-01-01'
    union
    select counterpart_code from {{ ref('district_changes') }} where effective > date '2019-01-01'
)

select
    d.district_code,
    d.district_name,
    left(d.district_code, 2) as land_code,
    l.land_name,
    d.district_type,
    p.district_population as population,
    s.unemployed,
    1000.0 * s.unemployed / p.district_population as unemployed_per_1000_residents,
    case
        when d.district_code not in (select district_code from reformed)
            then 100.0 * (s.avg_last_12_months / s.avg_2019 - 1)
    end as change_since_2019_pct,
    (select last_month from latest) as unemployment_period,
    g.geometry
from {{ ref('int_districts') }} as d
left join {{ ref('lands') }} as l on l.land_code = left(d.district_code, 2)
left join {{ ref('int_district_population') }} as p using (district_code)
left join series as s using (district_code)
left join {{ ref('stg_bkg__areas') }} as g on g.level = 'district' and g.code = d.district_code
