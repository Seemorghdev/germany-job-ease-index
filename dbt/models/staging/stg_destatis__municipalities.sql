select
    edition,
    ags,
    substr(ags, 1, 5) as district_code,
    name as official_name,
    trim(split_part(name, ',', 1)) as city,
    population,
    area_km2
from {{ source('landing', 'destatis_municipalities') }}
