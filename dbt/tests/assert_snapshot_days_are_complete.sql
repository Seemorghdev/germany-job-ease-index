{{ config(severity='warn') }}
-- A day with missing queries is left out of lifetimes. Resume it the same day with
-- `jobease snapshot-listings`; `--date` resumes an earlier day.
select *
from {{ ref('int_snapshot_days') }}
where not is_complete
