-- The latest reporting month, one row per district with a count.
select
    period,
    district_code,
    district_label,
    unemployed
from {{ ref('int_unemployment_monthly') }}
where period = (select max(period) from {{ ref('int_unemployment_monthly') }})
  and value_status = 'value'
