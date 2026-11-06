select
    batch_id,
    fetched_at,
    ags,
    search_name,
    tier,
    term,
    radius_km,
    window_days,
    total as listings
from {{ source('landing', 'jobsuche_counts') }}
