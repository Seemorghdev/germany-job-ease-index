-- How long listings stay up, per tier. Quartiles use closed listings only (those gone
-- before the latest day); open listings are counted and their current age shown, since
-- dropping them would bias lifetimes towards short ones.
with by_tier as (
    select unnest(tiers) as tier, *
    from {{ ref('mart_listing_lifetimes') }}
)

select
    t.tier,
    t.label,
    count(*) as listings,
    count(*) filter (where not b.is_open) as closed,
    count(*) filter (where b.is_open) as open,
    quantile_cont(b.lifetime_days, 0.25) filter (where not b.is_open) as closed_p25_days,
    quantile_cont(b.lifetime_days, 0.5) filter (where not b.is_open) as closed_median_days,
    quantile_cont(b.lifetime_days, 0.75) filter (where not b.is_open) as closed_p75_days,
    quantile_cont(b.lifetime_days, 0.5) filter (where b.is_open) as open_median_age_days,
    avg(case when b.part_time then 1.0 else 0.0 end) as share_part_time,
    avg(case when b.lateral_entry then 1.0 else 0.0 end) as share_lateral_entry
from by_tier as b
inner join {{ ref('tiers') }} as t using (tier)
group by t.tier, t.label
