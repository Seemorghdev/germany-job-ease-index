-- v4 bug: matching by name put München (city) on Landkreis München's figures.
-- A kreisfreie Stadt is its own district: exactly one municipality, same population.
select
    ags,
    city,
    district_code,
    district_name,
    population,
    district_population,
    municipalities_in_district
from {{ ref('int_cities') }}
where is_kreisfrei
  and (municipalities_in_district <> 1 or population <> district_population)
