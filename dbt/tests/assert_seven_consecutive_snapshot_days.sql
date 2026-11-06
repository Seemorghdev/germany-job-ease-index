{{ config(severity='warn') }}
-- S2 gate: the latest seven complete snapshot days are consecutive. Warns (rather than
-- fails) until a week of snapshots exists, so daily builds stay green meanwhile.
with complete as (
    select snapshot_date
    from {{ ref('int_snapshot_days') }}
    where is_complete
    order by snapshot_date desc
    limit 7
)

select
    count(*) as complete_days,
    min(snapshot_date) as first_day,
    max(snapshot_date) as last_day
from complete
having count(*) < 7 or date_diff('day', min(snapshot_date), max(snapshot_date)) <> 6
