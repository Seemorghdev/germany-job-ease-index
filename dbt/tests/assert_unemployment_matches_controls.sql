-- The BA issues must reproduce figures the BA published in its own press releases.
-- Catches a wrong sheet, shifted month columns or the wrong issue.
select
    c.period,
    c.district_code,
    c.unemployed as expected,
    u.unemployed as actual,
    c.source
from {{ ref('controls_unemployment') }} as c
left join {{ ref('int_unemployment_monthly') }} as u using (period, district_code)
where u.unemployed is distinct from c.unemployed
