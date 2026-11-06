-- Completeness of each snapshot day against the current cities and search terms. Only
-- complete days count for lifetimes: a missing query would make its listings look gone.
with expected as (
    select
        (select count(*) from {{ ref('int_cities') }})
        * (select count(*) from {{ ref('tier_terms') }}) as queries_expected
),

days as (
    select
        snapshot_date,
        count(*) as queries_stored,
        count(*) filter (where truncated) as queries_truncated,
        sum(listings_stored) as listing_hits
    from {{ ref('stg_jobsuche__snapshot_queries') }} as q
    inner join {{ ref('int_cities') }} using (ags)
    inner join {{ ref('tier_terms') }} using (tier, term)
    group by snapshot_date
)

select
    d.snapshot_date,
    d.queries_stored,
    e.queries_expected,
    d.queries_truncated,
    d.listing_hits,
    d.queries_stored = e.queries_expected as is_complete
from days as d
cross join expected as e
