-- A city with zero listings across every tier almost certainly means the job board
-- didn't recognise its name. Fix it in seeds/city_search_overrides.csv.
select ags, city, sum(listings) as listings_all_tiers
from {{ ref('mart_city_tier_ease') }}
group by ags, city
having coalesce(sum(listings), 0) = 0
