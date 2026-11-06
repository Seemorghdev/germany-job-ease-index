-- Every search term of a tier must be counted for every city in the chosen batch.
select l.ags, l.tier, l.terms_counted, t.terms_expected
from {{ ref('int_city_listings') }} as l
inner join (
    select tier, count(*) as terms_expected
    from {{ ref('tier_terms') }}
    group by tier
) as t using (tier)
where l.terms_counted <> t.terms_expected
