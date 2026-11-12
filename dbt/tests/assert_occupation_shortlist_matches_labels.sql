-- Every shortlisted occupation code exists, with a BA label that contains the expected
-- text: a typo in the seed would otherwise chart the wrong occupation under the right name.
with labels as (
    select distinct occupation_code, occupation_label
    from {{ ref('stg_ba__occupation_levels') }}
    where region_code = 'DE'
)

select s.occupation_code, s.short_label, s.label_must_contain, l.occupation_label
from {{ ref('occupation_shortlist') }} as s
left join labels as l using (occupation_code)
where l.occupation_label is null
   or not contains(lower(l.occupation_label), lower(s.label_must_contain))
