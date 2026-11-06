select ags, name, lon, lat, edition
from {{ source('landing', 'bkg_municipality_points') }}
where edition = (select max(edition) from {{ source('landing', 'bkg_municipality_points') }})
