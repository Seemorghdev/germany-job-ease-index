-- One row per listing ever seen: when it was published, first and last seen, and its
-- lifetime so far. A listing still open on the latest day is right-censored: its
-- lifetime is a lower bound. Lifetime counts from the board's first-publication date,
-- so listings that were already open when tracking began still get their full age.
with days as (
    select min(snapshot_date) as first_day, max(snapshot_date) as last_day
    from {{ ref('fct_listing_snapshot') }}
),

per_listing as (
    select
        reference,
        min(snapshot_date) as first_seen,
        max(snapshot_date) as last_seen,
        count(*) as days_seen,
        min(published_on) as published_on,
        arg_max(occupation, snapshot_date) as occupation,
        arg_max(employer_hash, snapshot_date) as employer_hash,
        bool_or(part_time) as part_time,
        bool_or(marginal) as marginal,
        bool_or(lateral_entry) as lateral_entry,
        list_sort(list_distinct(flatten(list(tiers)))) as tiers
    from {{ ref('fct_listing_snapshot') }}
    group by reference
)

select
    p.*,
    p.last_seen = d.last_day as is_open,
    p.published_on is null and p.first_seen = d.first_day as is_left_censored,
    date_diff('day', coalesce(p.published_on, p.first_seen), p.last_seen) as lifetime_days,
    date_diff('day', p.first_seen, p.last_seen) + 1 - p.days_seen as days_missing
from per_listing as p
cross join days as d
