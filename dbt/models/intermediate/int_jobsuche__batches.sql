-- One row per job-board batch. A batch is complete when every indexed city has a count
-- for every current search term. Only complete batches feed the marts.
with terms as (
    select tier, term from {{ ref('tier_terms') }}
),

expected as (
    select
        (select count(*) from terms) as terms_expected,
        (select count(*) from {{ ref('int_cities') }}) as cities_expected
),

matched as (
    select c.*
    from {{ ref('stg_jobsuche__counts') }} as c
    inner join terms using (tier, term)
    inner join {{ ref('int_cities') }} as city using (ags)
),

per_batch as (
    select
        batch_id,
        count(distinct ags) as cities_counted,
        count(*) as counts_matched,
        min(fetched_at) as started_at,
        max(fetched_at) as finished_at,
        any_value(radius_km) as radius_km,
        any_value(window_days) as window_days,
        count(distinct radius_km) as radius_variants,
        count(distinct window_days) as window_variants
    from matched
    group by batch_id
)

select
    b.*,
    e.terms_expected,
    e.cities_expected,
    b.cities_counted = e.cities_expected
        and b.counts_matched = e.cities_expected * e.terms_expected
        and b.radius_variants = 1
        and b.window_variants = 1 as is_complete
from per_batch as b
cross join expected as e
