-- Two BA publications, one count: a region's unemployed in the occupation workbook must
-- equal the sum of its districts in the district issues for the same month (within
-- `occupation_district_tolerance`). Catches a wrong reporting month or a wrong region.
-- Fails, too, if the two sources share no month, so the check can't pass by not running.
with occupation as (
    select region_code, period, value as occupation_file
    from {{ ref('stg_ba__occupation_levels') }}
    where occupation_code = 'total'
      and skill_level = 'total'
      and measure = 'unemployed'
      and period = vintage
      and value_status = 'value'
      and region_kind in ('germany', 'land')
),

by_land as (
    select left(district_code, 2) as region_code, period, sum(unemployed) as district_files
    from {{ ref('fct_unemployment_monthly') }}
    group by left(district_code, 2), period
),

districts as (
    select region_code, period, district_files from by_land
    union all
    select 'DE' as region_code, period, sum(district_files) as district_files
    from by_land
    group by period
),

compared as (
    select o.region_code, o.period, o.occupation_file, d.district_files
    from occupation as o
    inner join districts as d using (region_code, period)
)

select region_code, period, occupation_file, district_files
from compared
where abs(occupation_file - district_files)
    > {{ var('occupation_district_tolerance') }} * district_files

union all

select 'none' as region_code, null as period, null as occupation_file, null as district_files
where not exists (select 1 from compared)
