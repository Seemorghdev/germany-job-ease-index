select
    vintage,
    period,
    region_code,
    region_name,
    case
        when region_code = 'DE' then 'germany'
        when region_code in ('W', 'O') then 'west_east'
        else 'land'
    end as region_kind,
    occupation_code,
    occupation_digits,
    occupation_label,
    skill_level,
    measure,
    value,
    value_status,
    sheet,
    row_number,
    artifact_sha256
from {{ source('landing', 'ba_occupation_levels') }}
