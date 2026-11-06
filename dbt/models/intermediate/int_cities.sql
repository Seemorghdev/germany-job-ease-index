-- Cities to index, with the district they belong to and how much of it they make up.
-- Districts come from the AGS (first five digits), never from a name match.
select
    m.ags,
    m.city,
    m.official_name,
    m.population,
    m.district_code,
    d.district_name,
    d.type_code as district_type_code,
    d.district_type,
    d.is_kreisfrei,
    p.district_population,
    p.municipalities_in_district,
    m.population::double / p.district_population as district_coverage
from {{ ref('int_municipalities') }} as m
left join {{ ref('int_districts') }} as d using (district_code)
left join {{ ref('int_district_population') }} as p using (district_code)
where m.population >= {{ var('min_population') }}
