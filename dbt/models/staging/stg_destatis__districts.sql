select
    edition,
    district_code,
    name as district_name,
    type_code
from {{ source('landing', 'destatis_districts') }}
