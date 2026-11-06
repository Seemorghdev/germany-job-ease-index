-- Municipalities of the latest Destatis edition on current district boundaries: a city
-- that left its district after that edition is moved via seeds/district_changes.csv.
with latest_edition as (
    select max(edition) as edition
    from {{ ref('stg_destatis__municipalities') }}
)

select
    m.ags,
    m.city,
    m.official_name,
    m.population,
    coalesce(c.district_code, m.district_code) as district_code
from {{ ref('stg_destatis__municipalities') }} as m
inner join latest_edition using (edition)
left join {{ ref('district_changes') }} as c
    on c.municipality_ags = m.ags and c.change = 'created'
