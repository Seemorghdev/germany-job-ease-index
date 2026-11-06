-- Every month from the first to the last one in the unemployment history.
with bounds as (
    select min(period) as first_month, max(period) as last_month
    from {{ ref('int_unemployment_monthly') }}
)

select
    cast(month_start as date) as month_start,
    row_number() over (order by month_start) as month_index
from (
    select unnest(
        generate_series(first_month::timestamp, last_month::timestamp, interval 1 month)
    ) as month_start
    from bounds
)
