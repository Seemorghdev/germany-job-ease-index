-- Listing counts per city and tier from one complete batch: the pinned one if
-- `jobsuche_batch` is set, else the latest complete batch.
-- Counts are summed across a tier's search terms; a listing matching two terms counts
-- twice. Every city uses the same terms, so rates stay comparable between cities.
-- Distinct counts arrive with listing-level snapshots (stage S2).
with chosen_batch as (
    select batch_id
    from {{ ref('int_jobsuche__batches') }}
    where is_complete
    {%- if var('jobsuche_batch') %}
      and batch_id = '{{ var("jobsuche_batch") }}'
    {%- endif %}
    order by batch_id desc
    limit 1
)

select
    c.batch_id,
    c.ags,
    c.tier,
    sum(c.listings) as listings_summed,
    count(*) as terms_counted,
    max(c.fetched_at) as fetched_at
from {{ ref('stg_jobsuche__counts') }} as c
inner join chosen_batch using (batch_id)
inner join {{ ref('tier_terms') }} as t using (tier, term)
group by c.batch_id, c.ags, c.tier
