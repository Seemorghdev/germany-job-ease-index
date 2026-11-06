-- The job board per city and tier on each complete snapshot day: how many listings are
-- open, how many are part-time, Minijobs or open to career changers, and how old they
-- are. Aggregates only, so this is safe to publish; the listing-level tables are not.
-- Counts every open listing, unlike mart_city_tier_ease (last 30 days only).
with hits as (
    select distinct
        l.snapshot_date,
        l.ags,
        l.tier,
        l.reference,
        l.published_on,
        l.full_time,
        l.part_time,
        l.marginal,
        l.lateral_entry
    from {{ ref('stg_jobsuche__listings') }} as l
    inner join {{ ref('int_snapshot_days') }} as d
        on d.snapshot_date = l.snapshot_date and d.is_complete
)

select
    h.snapshot_date,
    h.ags,
    c.city,
    h.tier,
    t.label as tier_label,
    count(*) as listings,
    1000.0 * count(*) / nullif(any_value(u.unemployed), 0) as listings_per_1000_unemployed,
    avg(case when h.full_time then 1.0 else 0.0 end) as share_full_time,
    avg(case when h.part_time then 1.0 else 0.0 end) as share_part_time,
    avg(case when h.marginal then 1.0 else 0.0 end) as share_marginal,
    avg(case when h.lateral_entry then 1.0 else 0.0 end) as share_lateral_entry,
    quantile_cont(date_diff('day', h.published_on, h.snapshot_date), 0.5) as median_age_days,
    any_value(c.district_coverage) >= {{ var('min_district_coverage') }} as is_ranked
from hits as h
inner join {{ ref('int_cities') }} as c using (ags)
inner join {{ ref('tiers') }} as t using (tier)
left join {{ ref('int_unemployment_latest') }} as u on u.district_code = c.district_code
group by h.snapshot_date, h.ags, c.city, h.tier, t.label
