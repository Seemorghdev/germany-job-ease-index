select
    vintage,
    period,
    district_code,
    district_label,
    unemployed,
    value_status,
    artifact_sha256
from {{ source('landing', 'ba_unemployment_monthly') }}
