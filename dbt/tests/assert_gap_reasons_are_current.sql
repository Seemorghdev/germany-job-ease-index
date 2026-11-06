-- A reason that matches no gap is stale: the gap was fixed or its months changed.
select r.*
from {{ ref('unemployment_gap_reasons') }} as r
left join {{ ref('int_unemployment_gaps') }} as g
    on g.district_code = r.district_code
    and g.kind = r.kind
    and g.from_month = r.from_month
    and g.to_month is not distinct from r.to_month
where g.district_code is null
