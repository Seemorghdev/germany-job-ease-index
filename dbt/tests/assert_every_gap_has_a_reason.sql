-- S1 gate: every month a district has no count is explained, either by a district reform
-- (seeds/district_changes.csv: a created district starts late, an abolished one ends early)
-- or by a row in seeds/unemployment_gap_reasons.csv. Together with the grid in
-- int_unemployment_gaps this means
-- rows with a count = districts x months - explained gap months.
select g.*
from {{ ref('int_unemployment_gaps') }} as g
left join {{ ref('district_changes') }} as c
    on c.district_code = g.district_code
    and (
        (g.kind = 'starts' and c.change = 'created')
        or (g.kind = 'ends' and c.change = 'abolished')
    )
left join {{ ref('unemployment_gap_reasons') }} as r
    on r.district_code = g.district_code
    and r.kind = g.kind
    and r.from_month = g.from_month
    and r.to_month is not distinct from g.to_month
where c.district_code is null
  and r.district_code is null
