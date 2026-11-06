import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium", app_title="Where is it easiest to land a job?")


@app.cell
def _():
    import altair as alt
    import marimo as mo

    from jobease.showcase import TIER_COLORS, connect, scalar

    con = connect()
    tier_scale = alt.Scale(domain=list(TIER_COLORS), range=list(TIER_COLORS.values()))
    return alt, con, mo, scalar, tier_scale


@app.cell
def _(con, mo, scalar):
    _period = scalar(
        con, "select strftime(max(unemployment_period), '%B %Y') from marts.mart_city_ease"
    )
    _ranked = scalar(con, "select count(*) from marts.mart_city_ease where is_ranked")
    mo.md(
        f"""
        # Where in Germany is it easiest to land a job?

        For every German city with 100,000+ residents, this counts job-board listings
        posted in the last 30 days and divides them by the people out of work in the
        city's district. That gives **listings per 1,000 unemployed**: roughly, how many
        openings each job seeker competes for.

        It's done for three kinds of work: **A Tech**, **B Office & support** and
        **C Entry-level** (warehouse, retail, cleaning and similar). The combined rank
        weights entry-level double. Unemployment: BA, {_period}. {_ranked} cities ranked.
        """
    )
    return


@app.cell
def _(con):
    top = con.execute(
        """
        select
            c.combined_rank as rank,
            c.city,
            c.district_unemployed as unemployed,
            max(t.listings_per_1000_unemployed) filter (where t.tier = 'A') as tech,
            max(t.listings_per_1000_unemployed) filter (where t.tier = 'B') as office,
            max(t.listings_per_1000_unemployed) filter (where t.tier = 'C') as entry
        from marts.mart_city_ease as c
        inner join marts.mart_city_tier_ease as t using (ags)
        where c.is_ranked
        group by all
        order by rank
        """
    ).df()
    return (top,)


@app.cell
def _(mo, top):
    _berlin = top[top.city == "Berlin"].iloc[0]
    _best = top.iloc[0]
    mo.md(
        f"""
        ## The top of the list is mid-sized university cities

        **{_best.city}** ranks first, with {_best.entry:.0f} entry-level listings per 1,000
        unemployed. **Berlin** ranks {int(_berlin["rank"])} of {len(top)}, at
        {_berlin.entry:.0f}. Berlin has more listings than anywhere else, but far more people
        looking, so each opening is contested by about {_best.entry / _berlin.entry:.1f} times
        as many job seekers.
        """
    )
    return


@app.cell
def _(mo, top):
    mo.ui.table(
        top.head(15).round(1),
        selection=None,
        label="Top 15 cities: listings per 1,000 unemployed, by tier",
    )
    return


@app.cell
def _(alt, con, mo, tier_scale):
    _focus = con.execute(
        """
        with picks as (
            select ags from marts.mart_city_ease where is_ranked and combined_rank <= 8
            union select ags from marts.mart_city_ease
            where city in ('Berlin', 'Hamburg', 'München', 'Köln', 'Leipzig')
        )
        select t.city, t.tier, t.tier_label, t.listings_per_1000_unemployed as rate,
               c.combined_rank
        from marts.mart_city_tier_ease as t
        inner join marts.mart_city_ease as c using (ags)
        inner join picks using (ags)
        """
    ).df()
    _chart = (
        alt.Chart(_focus)
        .mark_bar()
        .encode(
            x=alt.X("rate:Q", title="Listings per 1,000 unemployed"),
            y=alt.Y("city:N", sort=alt.SortField("combined_rank"), title=None),
            color=alt.Color("tier:N", scale=tier_scale, legend=None),
            row=alt.Row("tier_label:N", title=None),
            tooltip=["city", "tier_label", alt.Tooltip("rate:Q", format=".1f")],
        )
        .properties(width=520, height=220)
    )
    mo.vstack(
        [
            mo.md("## The top 8 next to the big cities"),
            _chart,
        ]
    )
    return


@app.cell
def _(alt, con, mo):
    _cities = con.execute(
        """
        select c.city, c.population, c.district_unemployed as unemployed,
               t.listings_per_1000_unemployed as entry_rate, c.is_ranked
        from marts.mart_city_ease as c
        inner join marts.mart_city_tier_ease as t on t.ags = c.ags and t.tier = 'C'
        """
    ).df()
    _chart = (
        alt.Chart(_cities)
        .mark_circle(opacity=0.75)
        .encode(
            x=alt.X("unemployed:Q", scale=alt.Scale(type="log"), title="Unemployed in district"),
            y=alt.Y("entry_rate:Q", title="Entry-level listings per 1,000 unemployed"),
            size=alt.Size("population:Q", legend=None),
            color=alt.Color(
                "is_ranked:N",
                scale=alt.Scale(domain=[True, False], range=["#54A24B", "#BBBBBB"]),
                legend=alt.Legend(title="Ranked"),
            ),
            tooltip=["city", "unemployed", alt.Tooltip("entry_rate:Q", format=".1f")],
        )
        .properties(width=620, height=380)
    )
    mo.vstack(
        [
            mo.md(
                """
                ## Bigger isn't easier

                Each dot is a city. Further right means more unemployed people in its
                district; higher means more entry-level openings per job seeker. The largest
                labour markets sit low: volume grows, but competition grows faster.
                """
            ),
            _chart,
        ]
    )
    return


@app.cell
def _(con, mo):
    _not_ranked = con.execute(
        """
        select city, district_name as district, round(100 * district_coverage) as city_share_pct
        from marts.mart_city_ease
        where not is_ranked
        order by city_share_pct
        """
    ).df()
    mo.vstack(
        [
            mo.md(
                f"""
                ## {len(_not_ranked)} cities aren't ranked, on purpose

                Unemployment is published per district (Kreis). When a city is only a small
                part of its district, such as Recklinghausen or Moers, the district's
                unemployed mostly live elsewhere, and the rate would be meaningless. Cities
                below half of their district's population are left out.
                """
            ),
            mo.ui.table(_not_ranked, selection=None),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Method and sources

        - **Listings:** BA Jobbörse, one count per city and search term (15 terms over
          three tiers), posted in the last 30 days, within the city itself.
        - **Unemployed:** Statistik der Bundesagentur für Arbeit, district level, checked
          against four figures from BA press releases.
        - **Cities and districts:** Destatis Gemeindeverzeichnis. Cities are matched to
          districts by official code, never by name.
        - **Pipeline:** Python loaders → DuckDB → dbt (staging, intermediate, marts, 100+
          data tests) → Dagster. Source: `germany-job-ease-index`.

        Quelle: Statistik der Bundesagentur für Arbeit, eigene Berechnungen.
        """
    )
    return


if __name__ == "__main__":
    app.run()
