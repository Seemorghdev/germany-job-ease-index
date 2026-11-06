{{
    config(
        materialized='incremental',
        unique_key=['snapshot_date', 'reference'],
        incremental_strategy='delete+insert',
    )
}}
-- One row per complete snapshot day and listing. Built incrementally: each run reloads
-- the latest stored day and adds newer ones; `dbt build --full-refresh` rebuilds all.
-- Private: listing-level, never exported.
select *
from {{ ref('int_listing_days') }}
{% if is_incremental() %}
where snapshot_date >= (select coalesce(max(snapshot_date), date '1900-01-01') from {{ this }})
{% endif %}
