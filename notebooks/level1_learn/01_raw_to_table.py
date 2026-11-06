import marimo

__generated_with = "0.10.0"
app = marimo.App(width="medium", app_title="Lesson 1: from a raw file to a clean table")


@app.cell
def _():
    import io
    import re
    import zipfile

    import altair as alt
    import marimo as mo
    import openpyxl

    from jobease.config import load_settings
    from jobease.showcase import column, connect, scalar
    from jobease.sources import ba_unemployment
    from jobease.sources.numbers import parse_count

    settings = load_settings()
    con = connect()
    return (
        alt,
        ba_unemployment,
        column,
        con,
        io,
        mo,
        openpyxl,
        parse_count,
        re,
        scalar,
        settings,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(
        """
        # Lesson 1 · From a raw file to a clean table

        Every number in this project starts as a file someone else published. This lesson
        takes one of them, the Bundesagentur für Arbeit's monthly district report, and
        follows it all the way to a table you can query, using the same functions the
        pipeline uses.

        **You'll learn to:** look inside a file before trusting it · find where the data
        really starts · turn messy cells into clean values · check your result against the
        warehouse · ask your own questions in SQL.

        Run each cell, read what comes out, then change something and run it again. Nothing
        here can damage the data: the warehouse is opened read-only.
        """
    )
    return


@app.cell
def _(mo, settings):
    files = settings.ba.files()
    issue = files[-1]
    mo.vstack(
        [
            mo.md(
                f"""
                ## Step 1 · What files do we have?

                The BA publishes one report per month. The pipeline keeps one per year
                (each report repeats the previous 22 months), plus the latest. They live
                in `{settings.ba.dir.relative_to(settings.ba.dir.parents[2])}`:
                """
            ),
            mo.ui.table(
                [{"file": f.name, "size (KB)": round(f.stat().st_size / 1024)} for f in files],
                selection=None,
            ),
            mo.md(f"We'll work with the newest one, **{issue.name}**."),
        ]
    )
    return (issue,)


@app.cell
def _(issue, mo, zipfile):
    with zipfile.ZipFile(issue) as _archive:
        inside = _archive.namelist()
        workbook_name = next(n for n in inside if n.endswith(".xlsx"))
        workbook_bytes = _archive.read(workbook_name)
    mo.md(
        f"""
        ## Step 2 · Look inside the ZIP

        A `.zip` is a folder packed into one file. Python's `zipfile` lists what's inside
        without unpacking anything:

        {", ".join(f"`{n}`" for n in inside)}

        The Excel workbook is `{workbook_name}`, {len(workbook_bytes) / 1024:,.0f} KB.

        *Why it matters:* never assume what a download contains. Some years the BA shipped
        old `.xls` files; the pipeline checks for exactly one `.xlsx` and stops otherwise.
        """
    )
    return (workbook_bytes,)


@app.cell
def _(io, openpyxl, workbook_bytes):
    _book = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)
    sheet_names = _book.sheetnames
    raw_rows = [tuple(r) for r in _book["Übersicht_Kreise"].iter_rows(values_only=True)]
    _book.close()
    return raw_rows, sheet_names


@app.cell
def _(mo, raw_rows, sheet_names):
    from openpyxl.utils import get_column_letter

    def as_table(rows, first_row=1, columns=8):
        """Rows as a table with Excel's row numbers and column letters."""
        return [
            {"row": first_row + i}
            | {
                get_column_letter(c + 1): ("" if c >= len(r) or r[c] is None else str(r[c]))
                for c in range(columns)
            }
            for i, r in enumerate(rows)
        ]

    mo.vstack(
        [
            mo.md(
                f"""
                ## Step 3 · Open the workbook and look at the raw rows

                The workbook has {len(sheet_names)} sheets: {", ".join(sheet_names[:6])}…
                We want `Übersicht_Kreise` (overview by district). It has {len(raw_rows)}
                rows. These are the first 12, exactly as Excel stores them:
                """
            ),
            mo.ui.table(as_table(raw_rows[:12]), selection=None, page_size=12),
            mo.md(
                """
                Notice: the first rows are titles, not data. One row holds dates (the
                months), and further down each row is a district, with its code and name
                together in column A. A spreadsheet made for people to read, not for
                machines: that's normal, and it's the job of the loader to cope.
                """
            ),
        ]
    )
    return (as_table,)


@app.cell
def _(ba_unemployment, mo, raw_rows):
    _counts = [
        {
            "row": i + 1,
            "cells that are months": sum(ba_unemployment.parse_month(v) is not None for v in r),
        }
        for i, r in enumerate(raw_rows[:15])
    ]
    header_row = next(c["row"] for c in _counts if c["cells that are months"] >= 6)
    mo.vstack(
        [
            mo.md(
                """
                ## Step 4 · Find the header row

                Instead of hard-coding "the months are in row 3", the loader asks each row:
                *how many of your cells look like a month?* (`parse_month` understands real
                dates and text like "Oktober 2026".)
                """
            ),
            mo.ui.table(_counts, selection=None, page_size=15),
            mo.md(
                f"""
                Row **{header_row}** is the header. If the BA moves it next year, the loader
                still finds it. *Lesson:* look for data by what it is, not where it was last time.
                """
            ),
        ]
    )
    return (header_row,)


@app.cell
def _(mo, parse_count, raw_rows, re):
    label_pattern = re.compile(r"^\s*(\d{5})\s+(\S.*?)\s*$")
    _row = next(r for r in raw_rows if isinstance(r[0], str) and r[0].startswith("05515"))
    _code, _name = label_pattern.match(_row[0]).groups()
    _examples = ["4.180", "223254", 2104.0, "*", None]

    def _show(value):
        try:
            return repr(parse_count(value))
        except ValueError as error:
            return f"error: {error}"

    mo.vstack(
        [
            mo.md(
                f"""
                ## Step 5 · Clean one row

                Here's Münster's row, column A: `{_row[0]!r}`

                The regular expression `^\\s*(\\d{{5}})\\s+(\\S.*?)\\s*$` reads it as *five digits,
                spaces, then the rest*, giving code **{_code}** and name **{_name}**. The code is
                what we join on later, never the name (two districts can both be called
                "München": the city 09162 and the Landkreis 09184).

                Numbers need cleaning too. `parse_count` turns cells into whole numbers:
                """
            ),
            mo.ui.table(
                [{"cell": repr(v), "parse_count(cell)": _show(v)} for v in _examples],
                selection=None,
            ),
            mo.md(
                """
                `"4.180"` is German for 4,180. `"*"` means the BA withheld the number to
                protect privacy, so it becomes *missing* (`None`), not 0. Treating missing
                as zero is one of the most common data bugs there is.
                """
            ),
        ]
    )
    return


@app.cell
def _(ba_unemployment, issue, mo, settings):
    parsed = ba_unemployment.parse_workbook(
        issue,
        sheet_name=settings.ba.sheet,
        label_column=settings.ba.label_column,
        inner_suffix=settings.ba.inner_suffix,
    )
    _statuses = {s: parsed.count(s) for s in ("value", "suppressed", "empty", "zero")}
    mo.md(
        f"""
        ## Step 6 · Let the loader do all of it

        `ba_unemployment.parse_workbook` does steps 2 to 5 for every row, and a few more
        checks. The result for **{issue.name}**:

        - reporting month (the *vintage*): **{parsed.vintage:%B %Y}**
        - months covered: {parsed.months[0]:%b %Y} to {parsed.months[-1]:%b %Y}
          ({len(parsed.months)} months)
        - districts: {len({r.district_code for r in parsed.rows})}
        - rows (one per district and month): {len(parsed.rows):,}
        - values: {_statuses}

        Months after the reporting month are in the sheet as zeros (not yet reported), so
        the loader drops them, and it fails loudly if anything there isn't zero.
        """
    )
    return (parsed,)


@app.cell
def _(con, mo, parsed):
    _mine = {
        r.period: r.unemployed
        for r in parsed.rows
        if r.district_code == "05515" and r.period.year == parsed.vintage.year
    }
    _stored = con.execute(
        """
        select period, unemployed
        from landing.ba_unemployment_monthly
        where vintage = ? and district_code = '05515' and year(period) = ?
        order by period
        """,
        [parsed.vintage, parsed.vintage.year],
    ).fetchall()
    _compare = [
        {
            "month": f"{period:%Y-%m}",
            "parsed just now": _mine.get(period),
            "in the warehouse": stored,
            "same?": "✓" if _mine.get(period) == stored else "✗",
        }
        for period, stored in _stored
    ]
    mo.vstack(
        [
            mo.md(
                """
                ## Step 7 · Check against the warehouse

                The pipeline stored the same file in `landing.ba_unemployment_monthly`.
                Querying it with SQL should give exactly what we parsed by hand (Münster,
                this year):
                """
            ),
            mo.ui.table(_compare, selection=None),
            mo.md(
                """
                *Lesson:* when two routes to the same number agree, you can trust both a bit
                more. The pipeline's dbt tests do this kind of check automatically, for
                example against figures from the BA's own press releases.
                """
            ),
        ]
    )
    return


@app.cell
def _(column, con, mo):
    _names = column(
        con,
        "select district_name || ' (' || district_code || ')' from marts.dim_district "
        "where is_current order by district_name",
    )
    district_picker = mo.ui.dropdown(
        options=_names, value="Münster, Stadt (05515)", label="District"
    )
    mo.vstack(
        [
            mo.md(
                """
                ## Step 8 · One district, 20 years

                After loading every yearly report, dbt combines them into one clean series
                per district (`marts.fct_unemployment_monthly`). Pick any district:
                """
            ),
            district_picker,
        ]
    )
    return (district_picker,)


@app.cell
def _(alt, con, district_picker, mo):
    _code = district_picker.value[-6:-1]
    _series = con.execute(
        """
        select period, unemployed
        from marts.fct_unemployment_monthly
        where district_code = ? and value_status = 'value'
        order by period
        """,
        [_code],
    ).df()
    _chart = (
        alt.Chart(_series)
        .mark_line(color="#4C78A8")
        .encode(
            x=alt.X("period:T", title=None),
            y=alt.Y("unemployed:Q", title="Unemployed", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("period:T", format="%B %Y"), "unemployed"],
        )
        .properties(width=640, height=260, title=district_picker.value)
    )
    mo.vstack(
        [
            _chart,
            mo.md(
                "The saw-tooth is the seasons: unemployment rises every winter. "
                "Try Berlin, a rural Landkreis, or the district you're moving to."
            ),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Exercises

        Try each one in the SQL scratchpad at the bottom first. Open the answer only after.
        The tables you'll need: `landing.ba_unemployment_monthly` (raw, one slice per
        report), `marts.fct_unemployment_monthly` (clean, one row per month and district),
        `marts.dim_district` and `marts.dim_date`.
        """
    )
    return


@app.cell
def _(con, mo, scalar):
    def exercise(question, sql, note=""):
        try:
            result = mo.ui.table(con.execute(sql).df(), selection=None)
        except Exception as error:  # show the error rather than breaking the lesson
            result = mo.md(f"**Error:** `{error}`")
        answer = mo.vstack([mo.md(f"```sql\n{sql.strip()}\n```"), result, mo.md(note)])
        return mo.vstack([mo.md(question), mo.accordion({"Show the answer": answer})])

    _latest = scalar(con, "select max(vintage) from landing.ba_unemployment_monthly")
    mo.vstack(
        [
            exercise(
                "**1.** How many districts does the newest report contain?",
                f"""
                select count(distinct district_code) as districts
                from landing.ba_unemployment_monthly
                where vintage = date '{_latest}'
                """,
                "`count(distinct …)` counts each district once, though it has many months.",
            ),
            exercise(
                "**2.** Which five districts had the most unemployed in the latest month?",
                """
                select d.district_name, f.unemployed
                from marts.fct_unemployment_monthly as f
                join marts.dim_district as d using (district_code)
                where f.period = (select max(period) from marts.fct_unemployment_monthly)
                order by f.unemployed desc
                limit 5
                """,
                "A join adds the name; the sub-query finds the latest month.",
            ),
            exercise(
                "**3.** Reports overlap. In how many reports does March 2025 appear, and "
                "do they agree for Berlin (11000)?",
                """
                select vintage, unemployed
                from landing.ba_unemployment_monthly
                where period = date '2025-03-01' and district_code = '11000'
                order by vintage
                """,
                "Same month, different reports: when they differ, the BA revised its figure.",
            ),
            exercise(
                "**4.** In which month since 2007 was national unemployment highest, and lowest?",
                """
                (select 'highest' as which, month_label, national_unemployed
                 from marts.dim_date order by national_unemployed desc limit 1)
                union all
                (select 'lowest', month_label, national_unemployed
                 from marts.dim_date order by national_unemployed limit 1)
                """,
                "Each half sorts and keeps one row; `union all` stacks them.",
            ),
        ]
    )
    return


@app.cell
def _(mo):
    scratchpad = mo.ui.code_editor(
        value=(
            "-- Your SQL here. The warehouse is read-only, so experiment freely.\n"
            "select district_code, district_name, first_month, last_month\n"
            "from marts.dim_district\n"
            "where land_name = 'Bayern'\n"
            "order by district_name\n"
            "limit 10"
        ),
        language="sql",
        min_height=180,
        label="SQL scratchpad",
    )
    scratchpad
    return (scratchpad,)


@app.cell
def _(con, mo, scratchpad):
    try:
        _result = mo.ui.table(con.execute(scratchpad.value).df(), selection=None)
    except Exception as _error:  # a typo in the scratchpad shouldn't break the lesson
        _result = mo.md(f"**Error:** `{_error}`")
    _result
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## What you've done

        You took a file built for people to read, found where its data starts without
        hard-coding it, cleaned codes and numbers, kept "missing" separate from "zero", and
        checked the result two ways. That's most of what a data loader does.

        **Next lesson:** joining. Cities to districts by code, why joining on names breaks
        (the München bug), and how a dbt test catches it.
        """
    )
    return


if __name__ == "__main__":
    app.run()
