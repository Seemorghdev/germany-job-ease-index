-- One row per complete snapshot day and listing, however many cities and terms found it.
-- Attributes come from the board and are the same in every hit of one day.
select
    l.snapshot_date,
    l.reference,
    any_value(l.title) as title,
    any_value(l.employer) as employer,
    any_value(l.employer_hash) as employer_hash,
    any_value(l.occupation) as occupation,
    min(l.published_on) as published_on,
    max(l.changed_at) as changed_at,
    any_value(l.postcode) as postcode,
    any_value(l.full_time) as full_time,
    any_value(l.part_time) as part_time,
    any_value(l.marginal) as marginal,
    any_value(l.lateral_entry) as lateral_entry,
    any_value(l.contract_duration) as contract_duration,
    any_value(l.pay_info) as pay_info,
    list_sort(list_distinct(list(l.tier))) as tiers,
    list_sort(list_distinct(list(l.ags))) as city_codes,
    count(*) as query_hits
from {{ ref('stg_jobsuche__listings') }} as l
inner join {{ ref('int_snapshot_days') }} as d
    on d.snapshot_date = l.snapshot_date and d.is_complete
group by l.snapshot_date, l.reference
