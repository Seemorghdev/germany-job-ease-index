-- National unemployment never moved by a fifth from one month to the next since 2005
-- (the sharpest rise, spring 2020, was about 13%). A bigger jump means districts were
-- dropped, doubled, or read from the wrong column.
with totals as (
    select
        month_label,
        national_unemployed,
        lag(national_unemployed) over (order by month_start) as previous
    from {{ ref('dim_date') }}
)

select *, national_unemployed::double / previous - 1 as change
from totals
where previous is not null
  and abs(national_unemployed::double / previous - 1) > 0.20
