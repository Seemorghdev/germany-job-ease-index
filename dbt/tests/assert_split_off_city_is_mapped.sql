{{ config(severity='warn') }}
-- A city that left its district after the latest Destatis edition still sits in the old
-- district there, while the BA already counts it separately. Until its AGS is entered in
-- seeds/district_changes.csv (municipality_ags), the old district's population includes it
-- but its unemployed don't.
select c.*
from {{ ref('district_changes') }} as c
where c.change = 'created'
  and c.municipality_ags is null
  and c.district_code not in (
      select district_code
      from {{ ref('stg_destatis__districts') }}
      where edition = (select max(edition) from {{ ref('stg_destatis__districts') }})
  )
