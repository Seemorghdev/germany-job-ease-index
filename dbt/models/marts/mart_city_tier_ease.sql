-- One row per city and tier: listings, the rate per 1,000 unemployed, and the tier rank.
-- Rank follows the rate, not raw volume: a big city doesn't win by being big.
with cities as (
    select * from {{ ref('int_cities') }}
),

unemployment as (
    select * from {{ ref('int_unemployment_latest') }}
),

listings as (
    select * from {{ ref('int_city_listings') }}
),

tiers as (
    select * from {{ ref('tiers') }}
),

base as (
    select
        c.ags,
        c.city,
        t.tier,
        t.label as tier_label,
        t.slug as tier_slug,
        l.batch_id,
        l.listings_summed as listings,
        u.period as unemployment_period,
        u.unemployed as district_unemployed,
        1000.0 * l.listings_summed / nullif(u.unemployed, 0) as listings_per_1000_unemployed,
        c.district_coverage >= {{ var('min_district_coverage') }} as is_ranked
    from cities as c
    cross join tiers as t
    left join listings as l on l.ags = c.ags and l.tier = t.tier
    left join unemployment as u on u.district_code = c.district_code
)

select
    *,
    case
        when is_ranked then row_number() over (
            partition by tier, is_ranked
            order by listings_per_1000_unemployed desc nulls last, listings desc nulls last, ags
        )
    end as tier_rank
from base
