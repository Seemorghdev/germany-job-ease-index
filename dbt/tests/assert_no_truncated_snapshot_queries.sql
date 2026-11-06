{{ config(severity='warn') }}
-- A query that hit snapshot_max_pages misses listings, which then look shorter-lived.
-- Raise snapshot_max_pages in config/inputs.toml if this lists anything.
select snapshot_date, ags, tier, term, listings_reported, listings_stored, pages
from {{ ref('stg_jobsuche__snapshot_queries') }}
where truncated
