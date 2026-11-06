-- One row per city: its district, the plausibility of its denominator, and the combined
-- rank, a weighted average of tier ranks (weights in seeds/tiers.csv).
with cities as (
    select * from {{ ref('int_cities') }}
),

unemployment as (
    select * from {{ ref('int_unemployment_latest') }}
),

combined as (
    select
        r.ags,
        sum(r.tier_rank * t.weight) / sum(t.weight) as combined_score
    from {{ ref('mart_city_tier_ease') }} as r
    inner join {{ ref('tiers') }} as t using (tier)
    where r.is_ranked
    group by r.ags
),

base as (
    select
        c.ags,
        c.city,
        c.official_name,
        c.population,
        c.district_code,
        c.district_name,
        c.district_type,
        c.is_kreisfrei,
        c.district_population,
        c.municipalities_in_district,
        c.district_coverage,
        u.period as unemployment_period,
        u.unemployed as district_unemployed,
        u.unemployed::double / c.district_population as unemployed_share_of_population,
        c.district_coverage >= {{ var('min_district_coverage') }} as is_ranked,
        case
            when c.district_coverage < {{ var('min_district_coverage') }}
                then 'City holds ' || printf('%.0f', 100 * c.district_coverage)
                    || '% of its district''s population; the unemployment count mostly '
                    || 'describes other places.'
        end as not_ranked_reason,
        k.combined_score
    from cities as c
    left join unemployment as u using (district_code)
    left join combined as k using (ags)
)

select
    *,
    case
        when is_ranked then row_number() over (
            partition by is_ranked
            order by combined_score, ags
        )
    end as combined_rank
from base
