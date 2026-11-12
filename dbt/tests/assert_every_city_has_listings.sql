-- The marts need one complete batch: every indexed city counted for every current term.
-- Fails if a city is missing from the chosen batch. A build with no listings loaded at all
-- (snapshots not collected) passes; assert_seven_consecutive_snapshot_days warns about that.
select c.ags, c.city
from {{ ref('int_cities') }} as c
left join (select distinct ags from {{ ref('int_city_listings') }}) as l using (ags)
where l.ags is null
    and exists (select 1 from {{ ref('int_city_listings') }})
