-- Every district shape in the BKG edition belongs to a current district, and the other
-- way round (mart_district_map tests the second). A mismatch means the BKG edition and
-- the BA data are on different boundaries: record the reform in district_changes.csv.
select g.code, g.name
from {{ ref('stg_bkg__areas') }} as g
left join {{ ref('int_districts') }} as d on d.district_code = g.code
where g.level = 'district' and d.district_code is null
