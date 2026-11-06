import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium", app_title="20 years of unemployment, 400 districts")


@app.cell
def _():
    import altair as alt
    import marimo as mo
    import pandas as pd

    from jobease.showcase import connect, row, scalar

    con = connect()
    return alt, con, mo, pd, row, scalar


@app.cell
def _(con, mo, row, scalar):
    _first, _last, _months = row(
        con, "select min(month_label), max(month_label), count(*) from marts.dim_date"
    )
    _districts = scalar(con, "select count(*) from marts.dim_district where is_current")
    mo.md(
        f"""
        # 20 years of unemployment, district by district

        Every month from **{_first}** to **{_last}** ({_months} months) for all
        {_districts} German districts, from the Bundesagentur für Arbeit's monthly district
        reports. Each report repeats the previous 22 months, so the overlap is used to
        check one report against the next. District reforms (a city leaving its district,
        two districts merging) are recorded and tested, so no month goes missing
        unexplained.
        """
    )
    return


@app.cell
def _(alt, con, mo):
    _national = con.execute(
        "select month_start, national_unemployed from marts.dim_date order by month_start"
    ).df()
    _line = (
        alt.Chart(_national)
        .mark_line(color="#4C78A8")
        .encode(
            x=alt.X("month_start:T", title=None),
            y=alt.Y("national_unemployed:Q", title="Unemployed, Germany"),
            tooltip=[
                alt.Tooltip("month_start:T", format="%B %Y"),
                alt.Tooltip("national_unemployed:Q", format=","),
            ],
        )
    )
    _covid = (
        alt.Chart(alt.Data(values=[{"month_start": "2020-04-01", "label": "Covid-19"}]))
        .mark_rule(strokeDash=[4, 4], color="#999999")
        .encode(x="month_start:T")
    )
    _label = _covid.mark_text(align="left", dx=4, dy=-120, color="#666666").encode(text="label:N")
    mo.vstack(
        [
            mo.md(
                """
                ## The national picture

                Unemployment fell for a decade after the 2009 crisis, jumped in spring 2020,
                and has been rising again since 2023. The yearly saw-tooth is seasonal:
                winter is always higher.
                """
            ),
            (_line + _covid + _label).properties(width=640, height=300),
        ]
    )
    return


@app.cell
def _(alt, con, mo):
    _indexed = con.execute(
        """
        with picks as (
            select district_code, city
            from marts.mart_city_ease
            where (is_ranked and combined_rank <= 5) or city = 'Berlin'
        ),
        base as (
            select district_code, avg(unemployed) as base
            from marts.fct_unemployment_monthly
            inner join picks using (district_code)
            where year(period) = 2019 and value_status = 'value'
            group by district_code
        ),
        national_base as (
            select avg(national_unemployed) as base from marts.dim_date where year = 2019
        )
        select p.city, f.period, 100.0 * f.unemployed / b.base as index_2019
        from marts.fct_unemployment_monthly as f
        inner join picks as p using (district_code)
        inner join base as b using (district_code)
        where f.value_status = 'value' and f.period >= date '2018-01-01'
        union all
        select 'Germany', month_start,
               100.0 * national_unemployed / (select base from national_base)
        from marts.dim_date
        where month_start >= date '2018-01-01'
        """
    ).df()
    _chart = (
        alt.Chart(_indexed)
        .mark_line()
        .encode(
            x=alt.X("period:T", title=None),
            y=alt.Y(
                "index_2019:Q",
                title="Unemployed (2019 average = 100)",
                scale=alt.Scale(zero=False),
            ),
            color=alt.Color("city:N", title=None),
            strokeDash=alt.condition(
                alt.datum.city == "Germany", alt.value([4, 3]), alt.value([1, 0])
            ),
            tooltip=[
                "city",
                alt.Tooltip("period:T", format="%B %Y"),
                alt.Tooltip("index_2019:Q", format=".0f"),
            ],
        )
        .properties(width=640, height=320)
    )
    mo.vstack(
        [
            mo.md(
                """
                ## The top cities against Berlin, since 2018

                Indexed to each district's 2019 average. The ranking is a snapshot of one
                month; this shows whether the top cities got there steadily or by luck.
                """
            ),
            _chart,
        ]
    )
    return


@app.cell
def _(alt, con, mo, pd):
    _change = con.execute(
        """
        with latest as (select max(period) as last_month from marts.fct_unemployment_monthly),
        per_district as (
            select
                f.district_code,
                avg(f.unemployed) filter (where year(f.period) = 2019) as avg_2019,
                avg(f.unemployed) filter (
                    where f.period > (select last_month from latest) - interval 12 month
                ) as avg_last_12
            from marts.fct_unemployment_monthly as f
            where f.value_status = 'value'
            group by f.district_code
        )
        select d.district_name, d.land_name, p.avg_2019, p.avg_last_12,
               100.0 * (p.avg_last_12 / p.avg_2019 - 1) as change_pct
        from per_district as p
        inner join marts.dim_district as d using (district_code)
        where d.is_current and p.avg_2019 is not null and p.avg_last_12 is not null
        """
    ).df()
    _sorted = _change.sort_values("change_pct")
    _extremes = pd.concat([_sorted.head(10), _sorted.tail(10)]).assign(
        direction=lambda df: df.change_pct.gt(0).map({True: "rose", False: "fell"})
    )
    _chart = (
        alt.Chart(_extremes)
        .mark_bar()
        .encode(
            x=alt.X("change_pct:Q", title="Change in unemployed, 2019 → last 12 months (%)"),
            y=alt.Y("district_name:N", sort="x", title=None),
            color=alt.Color(
                "direction:N",
                scale=alt.Scale(domain=["fell", "rose"], range=["#54A24B", "#E45756"]),
                legend=None,
            ),
            tooltip=["district_name", "land_name", alt.Tooltip("change_pct:Q", format=".1f")],
        )
        .properties(width=560, height=440)
    )
    _median = _change.change_pct.median()
    mo.vstack(
        [
            mo.md(
                f"""
                ## Which districts changed most since before Covid?

                The typical district has {_median:+.0f}% more unemployed now than in 2019.
                The 10 biggest rises and falls:
                """
            ),
            _chart,
        ]
    )
    return


@app.cell
def _(con, mo):
    _reforms = con.execute(
        """
        select d.district_name as district, d.change, d.change_effective as effective,
               o.district_name as other_district, d.first_month, d.last_month
        from marts.dim_district as d
        left join marts.dim_district as o on o.district_code = d.counterpart_code
        where d.change is not null
        order by d.change_effective
        """
    ).df()
    mo.vstack(
        [
            mo.md(
                """
                ## District reforms in the data

                The BA restates every month of a report on the boundaries in force when it
                was published, so a reform shows up as a series that starts or stops early,
                or as a jump between two reports. Each one is recorded with its source and
                tested against the data.
                """
            ),
            mo.ui.table(_reforms, selection=None),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Method and sources

        - **Data:** "Arbeitslose nach Ländern und Kreisen", Statistik der Bundesagentur für
          Arbeit: one December report per year from 2008, plus the latest month. Downloaded,
          checked and loaded by the pipeline; each file is recorded with its URL and checksum.
        - **Checks:** every district reported every month, national totals within the
          plausible range, no month-to-month jump above 20%, overlapping reports compared,
          and four press-release figures matched exactly.

        Quelle: Statistik der Bundesagentur für Arbeit, eigene Berechnungen.
        """
    )
    return


if __name__ == "__main__":
    app.run()
