-- One row per indexed city for the map: position, rank and listings per 1,000
-- unemployed in each tier. Aggregates only: publishable.
select
    c.ags,
    c.city,
    c.population,
    c.district_code,
    c.is_ranked,
    c.combined_rank,
    p.lon,
    p.lat,
    max(t.listings_per_1000_unemployed) filter (where t.tier = 'A') as rate_a,
    max(t.listings_per_1000_unemployed) filter (where t.tier = 'B') as rate_b,
    max(t.listings_per_1000_unemployed) filter (where t.tier = 'C') as rate_c
from {{ ref('mart_city_ease') }} as c
left join {{ ref('stg_bkg__municipality_points') }} as p using (ags)
left join {{ ref('mart_city_tier_ease') }} as t using (ags)
group by all
