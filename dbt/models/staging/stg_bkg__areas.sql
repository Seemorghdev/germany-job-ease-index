-- The latest BKG edition only.
select
    level,
    code,
    name,
    kind,
    area_km2,
    geometry,
    edition
from {{ source('landing', 'bkg_areas') }}
where edition = (select max(edition) from {{ source('landing', 'bkg_areas') }})
