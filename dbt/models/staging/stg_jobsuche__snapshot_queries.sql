select
    snapshot_date,
    ags,
    tier,
    term,
    fetched_at,
    total as listings_reported,
    pages,
    listings as listings_stored,
    truncated,
    facets_json
from {{ source('landing', 'jobsuche_snapshot_queries') }}
