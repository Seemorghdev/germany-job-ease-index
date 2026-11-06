import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium", app_title="What the job board looks like today")


@app.cell
def _():
    import altair as alt
    import marimo as mo

    from jobease.showcase import TIER_COLORS, column, connect, scalar

    con = connect()
    tier_scale = alt.Scale(domain=list(TIER_COLORS), range=list(TIER_COLORS.values()))
    tier_order = column(con, "select label from reference.tiers order by tier")
    return alt, con, mo, scalar, tier_order, tier_scale


@app.cell
def _(con, scalar):
    profile = con.execute(
        """
        select *
        from marts.mart_city_listing_profile
        where snapshot_date = (select max(snapshot_date) from marts.mart_city_listing_profile)
        """
    ).df()
    snapshot_days = scalar(
        con,
        "select count(distinct snapshot_date) from marts.mart_city_listing_profile",
    )
    return profile, snapshot_days


@app.cell
def _(mo, profile, snapshot_days):
    _day = profile.snapshot_date.max()
    mo.md(
        f"""
        # What the job board looks like today

        Every morning the pipeline stores **every open listing** on the BA Jobbörse for
        79 cities and 15 search terms, page by page. This page shows the latest day,
        **{_day:%d %B %Y}** ({snapshot_days} day{"s" if snapshot_days != 1 else ""} collected so
        far), as aggregates: individual listings stay private.

        Unlike the city ranking, which counts listings from the last 30 days, these counts
        include every listing still open, however old.
        """
    )
    return


@app.cell
def _(mo, profile):
    _tiers = (
        profile.assign(
            part_time=profile.share_part_time * profile.listings,
            marginal=profile.share_marginal * profile.listings,
            lateral=profile.share_lateral_entry * profile.listings,
        )
        .groupby(["tier", "tier_label"], as_index=False)[
            ["listings", "part_time", "marginal", "lateral"]
        ]
        .sum()
    )
    _tiers = _tiers.assign(
        **{
            "part-time %": 100 * _tiers.part_time / _tiers.listings,
            "Minijob %": 100 * _tiers.marginal / _tiers.listings,
            "open to career changers %": 100 * _tiers.lateral / _tiers.listings,
        }
    )[["tier_label", "listings", "part-time %", "Minijob %", "open to career changers %"]]
    mo.vstack(
        [
            mo.md(
                """
                ## Three kinds of work, three different markets

                Entry-level work has the most openings and the largest shares of part-time
                and career-changer listings; tech has the smallest. A listing matching terms
                in two tiers counts in both.
                """
            ),
            mo.ui.table(_tiers.round(1), selection=None),
        ]
    )
    return


@app.cell
def _(alt, mo, profile, tier_order):
    _ranked = profile[profile.is_ranked]
    _top_cities = (
        _ranked[_ranked.tier == "C"].nlargest(20, "listings_per_1000_unemployed").city.tolist()
    )
    _heat = _ranked[_ranked.city.isin(_top_cities)]
    _chart = (
        alt.Chart(_heat)
        .mark_rect()
        .encode(
            x=alt.X("tier_label:N", title=None, sort=tier_order),
            y=alt.Y("city:N", sort=_top_cities, title=None),
            color=alt.Color(
                "listings_per_1000_unemployed:Q",
                title="Open listings per 1,000 unemployed",
                scale=alt.Scale(scheme="greens"),
            ),
            tooltip=[
                "city",
                "tier_label",
                "listings",
                alt.Tooltip("listings_per_1000_unemployed:Q", format=".1f"),
            ],
        )
        .properties(width=300, height=480)
    )
    mo.vstack(
        [
            mo.md(
                """
                ## Open listings per 1,000 unemployed, top 20 cities for entry-level work

                Read across a row to see whether a city is strong in one kind of work or
                in all three.
                """
            ),
            _chart,
        ]
    )
    return


@app.cell
def _(alt, mo, profile):
    _entry = profile[(profile.tier == "C") & profile.is_ranked]
    _chart = (
        alt.Chart(_entry)
        .mark_circle(opacity=0.75, color="#54A24B")
        .encode(
            x=alt.X("share_part_time:Q", title="Part-time share", axis=alt.Axis(format="%")),
            y=alt.Y(
                "share_lateral_entry:Q",
                title="Open to career changers",
                axis=alt.Axis(format="%"),
            ),
            size=alt.Size("listings:Q", title="Listings"),
            tooltip=[
                "city",
                "listings",
                alt.Tooltip("share_part_time:Q", format=".0%"),
                alt.Tooltip("share_lateral_entry:Q", format=".0%"),
            ],
        )
        .properties(width=600, height=380)
    )
    mo.vstack(
        [
            mo.md(
                """
                ## Entry-level work: how flexible, how open?

                Each dot is a city. Further right, more of its entry-level listings are
                part-time; higher, more of them say they welcome career changers.
                """
            ),
            _chart,
        ]
    )
    return


@app.cell
def _(alt, con, mo, tier_order, tier_scale):
    _lifetimes = con.execute("select * from marts.mart_tier_lifetimes order by tier").df()
    _closed = int(_lifetimes.closed.sum())
    if _closed == 0:
        _body = mo.md(
            """
            ## How long do listings stay up?

            A listing's lifetime is known once it disappears, so this needs a few days of
            snapshots. For now: the typical **open** listing's age by tier.
            """
        )
        _chart = (
            alt.Chart(_lifetimes)
            .mark_bar()
            .encode(
                x=alt.X("open_median_age_days:Q", title="Median age of open listings (days)"),
                y=alt.Y("label:N", title=None, sort=tier_order),
                color=alt.Color("tier:N", scale=tier_scale, legend=None),
            )
            .properties(width=520, height=140)
        )
    else:
        _body = mo.md(
            f"""
            ## How long do listings stay up?

            {_closed:,} listings have closed since tracking began. Bars run from the first
            to the third quartile of their lifetime, the tick is the median. Open listings
            are counted separately, so long-running ones don't vanish from the picture.
            """
        )
        _chart = (
            alt.Chart(_lifetimes)
            .mark_bar(height=14)
            .encode(
                x=alt.X("closed_p25_days:Q", title="Days from first publication to removal"),
                x2="closed_p75_days:Q",
                y=alt.Y("label:N", title=None, sort=tier_order),
                color=alt.Color("tier:N", scale=tier_scale, legend=None),
                tooltip=["label", "closed", "open", "closed_median_days", "open_median_age_days"],
            )
            .properties(width=520, height=140)
        ) + alt.Chart(_lifetimes).mark_tick(color="black", thickness=2, size=18).encode(
            x="closed_median_days:Q", y=alt.Y("label:N", sort=tier_order)
        )
    mo.vstack([_body, _chart, mo.ui.table(_lifetimes.round(2), selection=None)])
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Method and privacy

        - **Collection:** the BA Jobbörse search, once a day, every listing for each city
          and term, 100 per page, at one request per second. A day counts only if every
          query completed; otherwise its listings would look like they had disappeared.
        - **Lifetime:** from the listing's first publication date to the last day it was
          seen. Listings still open are right-censored and shown separately.
        - **Privacy:** listing-level data (titles, employers) never leaves the local
          warehouse. Everything here is aggregated per city and tier.
        """
    )
    return


if __name__ == "__main__":
    app.run()
