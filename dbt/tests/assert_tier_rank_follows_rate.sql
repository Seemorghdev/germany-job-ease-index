-- v3 bug: ranking by raw listing volume put Berlin first.
-- Within a tier, a better rank must never have a lower rate per 1,000 unemployed.
select
    better.tier,
    better.ags as better_ags,
    better.tier_rank as better_rank,
    better.listings_per_1000_unemployed as better_rate,
    worse.ags as worse_ags,
    worse.tier_rank as worse_rank,
    worse.listings_per_1000_unemployed as worse_rate
from {{ ref('mart_city_tier_ease') }} as better
inner join {{ ref('mart_city_tier_ease') }} as worse
    on better.tier = worse.tier
   and better.is_ranked
   and worse.is_ranked
   and better.tier_rank < worse.tier_rank
where better.listings_per_1000_unemployed < worse.listings_per_1000_unemployed
