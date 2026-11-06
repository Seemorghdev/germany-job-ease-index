-- Unemployed people per district and month: the history behind every rate in the index.
-- Grain: one row per month and district code that the BA reported in that month.
select
    period,
    district_code,
    unemployed,
    value_status,
    vintage as source_vintage
from {{ ref('int_unemployment_monthly') }}
