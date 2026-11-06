-- The marts need one complete batch: every indexed city counted for every current term.
-- Fails if no batch is complete, or if a city is missing from the chosen batch.
select c.ags, c.city
from {{ ref('int_cities') }} as c
left join (select distinct ags from {{ ref('int_city_listings') }}) as l using (ags)
where l.ags is null
