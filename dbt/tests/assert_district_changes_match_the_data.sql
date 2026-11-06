-- A recorded reform must be visible in the data: a created district reports counts, an
-- abolished one stops reporting, and both sides of a boundary change keep reporting.
-- Catches a mistyped code or effective date.
select c.*, d.first_month, d.last_month, d.is_current
from {{ ref('district_changes') }} as c
left join {{ ref('dim_district') }} as d using (district_code)
left join {{ ref('dim_district') }} as o on o.district_code = c.counterpart_code
where d.district_code is null
   or o.district_code is null
   or (c.change in ('created', 'boundary') and not d.is_current)
   or (c.change = 'abolished' and d.is_current)
   or (c.change in ('abolished', 'boundary') and not o.is_current)
