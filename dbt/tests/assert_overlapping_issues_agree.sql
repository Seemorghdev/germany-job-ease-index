{{ config(severity='warn') }}
-- Issues overlap by up to 22 months. Where an older issue reports a different count for
-- the same month and district than the issue we use, list it: a revision by the BA, or a
-- boundary change not yet in seeds/district_changes.csv. Recorded reforms are expected to
-- differ across the reform date and are left out.
with changes as (
    select district_code, counterpart_code, effective from {{ ref('district_changes') }}
)

select
    s.period,
    s.district_code,
    s.vintage as other_vintage,
    s.unemployed as other_count,
    u.vintage as used_vintage,
    u.unemployed as used_count,
    round(s.unemployed::double / u.unemployed - 1, 4) as change
from {{ ref('stg_ba__unemployment') }} as s
inner join {{ ref('int_unemployment_monthly') }} as u using (period, district_code)
where s.vintage <> u.vintage
  and s.value_status = 'value'
  and u.value_status = 'value'
  and abs(s.unemployed::double / u.unemployed - 1) > 0.02
  and not exists (
      select 1
      from changes as c
      where s.district_code in (c.district_code, c.counterpart_code)
        and s.vintage < c.effective
        and u.vintage >= c.effective
  )
