-- One row per month and district, taken from the newest issue that covers the month.
-- Taking each month from a single issue keeps that month's districts on one territorial
-- status: an issue reports all its months on the boundaries in force when it was published.
with issue_per_month as (
    select
        period,
        max(vintage) as vintage,
        count(distinct vintage) as issues_covering
    from {{ ref('stg_ba__unemployment') }}
    group by period
)

select
    s.period,
    s.district_code,
    s.district_label,
    s.unemployed,
    s.value_status,
    s.vintage,
    i.issues_covering
from {{ ref('stg_ba__unemployment') }} as s
inner join issue_per_month as i using (period, vintage)
