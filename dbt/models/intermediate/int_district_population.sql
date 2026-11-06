-- Residents per district (current boundaries), summed from its municipalities.
select
    district_code,
    sum(population) as district_population,
    count(*) as municipalities_in_district
from {{ ref('int_municipalities') }}
group by district_code
