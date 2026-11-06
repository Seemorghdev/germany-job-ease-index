-- Districts on current boundaries: the latest Destatis directory, plus districts created
-- after that edition (seeds/district_changes.csv), which the BA already reports, minus
-- abolished ones.
with latest_edition as (
    select max(edition) as edition
    from {{ ref('stg_destatis__districts') }}
),

directory as (
    select d.district_code, d.district_name, d.type_code, 'destatis ' || d.edition as source
    from {{ ref('stg_destatis__districts') }} as d
    inner join latest_edition using (edition)
),

changes as (
    select * from {{ ref('district_changes') }}
),

created as (
    select c.district_code, c.district_name, c.type_code, 'district_changes' as source
    from changes as c
    where c.change = 'created'
      and c.district_code not in (select district_code from directory)
)

select
    u.district_code,
    u.district_name,
    u.type_code,
    t.label as district_type,
    t.is_kreisfrei,
    u.source
from (select * from directory union all select * from created) as u
left join {{ ref('district_types') }} as t using (type_code)
where u.district_code not in (
    select district_code from changes where change = 'abolished'
)
