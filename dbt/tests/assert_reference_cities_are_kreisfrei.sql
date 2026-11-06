-- Known kreisfreie Städte must be indexed and typed as such. If this fails, the
-- district type mapping (seeds/district_types.csv) or the GV-ISys columns are off.
with expected (ags, city) as (
    values
        ('11000000', 'Berlin'),
        ('02000000', 'Hamburg'),
        ('09162000', 'München'),
        ('05315000', 'Köln'),
        ('05515000', 'Münster'),
        ('09161000', 'Ingolstadt')
)

select e.ags, e.city, c.district_type, c.is_kreisfrei
from expected as e
left join {{ ref('int_cities') }} as c using (ags)
where c.ags is null or not c.is_kreisfrei
