"""Command-line entry point: ``jobease <command>``."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from jobease import export, launchd, map_export, pipeline, tour_video, warehouse
from jobease.config import REPO_ROOT, load_settings
from jobease.sources import bkg, xlsx


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobease", description=__doc__)
    parser.add_argument("--config", type=Path, help="settings file (default: config/inputs.toml)")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect-xlsx", help="preview a sheet with column letters")
    inspect.add_argument("file", type=Path)
    inspect.add_argument("--sheet")
    inspect.add_argument("--rows", type=int, default=15)
    inspect.add_argument("--inner-suffix", help="inner .xlsx name suffix, for ZIP archives")

    download = commands.add_parser(
        "download-ba", help="download BA issues (one per year) into the input folder"
    )
    download.add_argument("first_year", type=int)
    download.add_argument("last_year", type=int)
    download.add_argument("--month", type=int, default=12, help="reporting month (default 12)")

    commands.add_parser("ingest-ba", help="load every BA district unemployment issue")
    commands.add_parser("ingest-gvisys", help="load the Destatis municipality directory")
    commands.add_parser("ingest-bkg", help="load BKG state and district boundaries")

    geo = commands.add_parser("inspect-geo", help="list the layers of a BKG VG250 ZIP")
    geo.add_argument("file", type=Path)
    geo.add_argument("--inner-suffix", default=".gpkg")
    geo.add_argument("--layer", action="append", default=[], help="also count Geofaktor values")

    fetch = commands.add_parser("fetch-counts", help="fetch listing counts from the BA job board")
    fetch.add_argument("--batch-id", help="resume an interrupted batch")
    fetch.add_argument("--limit-cities", type=int, help="only the first N cities (smoke test)")

    commands.add_parser("export", help="write data/exports/city_ease.csv and summary.json")
    commands.add_parser("export-map", help="write docs/map/data.js for the district map")
    commands.add_parser("status", help="row counts of the landing tables")

    snapshot = commands.add_parser(
        "snapshot-listings", help="store today's open listings per city and term (S2)"
    )
    snapshot.add_argument("--date", type=date.fromisoformat, help="resume this day (YYYY-MM-DD)")
    snapshot.add_argument("--limit-cities", type=int, help="only the first N cities (smoke test)")

    schedule = commands.add_parser(
        "launchd-plist", help="print the macOS launchd job for the daily snapshot"
    )
    schedule.add_argument("--hour", type=int, default=9)
    schedule.add_argument("--minute", type=int, default=0)

    tour = commands.add_parser("record-tour", help="record docs/tour/index.html as an MP4")
    tour.add_argument("--out", type=Path, default=tour_video.DEFAULT_OUT)
    tour.add_argument("--fps", type=int, help="frames per second (default: the page's own)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "inspect-xlsx":
        print(
            xlsx.preview(
                args.file, sheet_name=args.sheet, rows=args.rows, inner_suffix=args.inner_suffix
            )
        )
        return 0

    if args.command == "inspect-geo":
        with (
            bkg.open_geopackage(args.file, args.inner_suffix) as gpkg,
            bkg.spatial_connection() as con,
        ):
            for layer in bkg.layers(con, gpkg):
                print(f"{layer['name']}: {layer['features']} features, fields {layer['fields']}")
            for name in args.layer:
                print(f"{name} Geofaktor counts: {bkg.geofactor_counts(con, gpkg, name)}")
        return 0

    if args.command == "launchd-plist":
        (REPO_ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)  # launchd won't
        sys.stdout.buffer.write(launchd.plist(REPO_ROOT, hour=args.hour, minute=args.minute))
        return 0

    if args.command == "record-tour":
        recording = tour_video.record_tour(args.out, fps=args.fps)
        width, height = recording.size
        print(
            f"{recording.path}  {width}x{height}  {recording.frames} frames  "
            f"{recording.seconds:.1f} s"
        )
        return 0

    settings = load_settings(args.config)
    if args.command == "snapshot-listings":
        print(
            pipeline.snapshot_listings(
                settings, snapshot_date=args.date, limit_cities=args.limit_cities
            )
        )
        return 0
    if args.command == "download-ba":
        if args.first_year > args.last_year or not 1 <= args.month <= 12:
            print("download-ba: need first_year <= last_year and 1 <= month <= 12")
            return 2
        vintages = [date(y, args.month, 1) for y in range(args.last_year, args.first_year - 1, -1)]
        summaries = pipeline.download_ba(settings, vintages)
        for s in summaries:
            print(f"{s.vintage}  {s.status:<11} {s.detail}")
        return 1 if any(s.status in {"failed", "not tried"} for s in summaries) else 0
    if args.command == "ingest-ba":
        for summary in pipeline.ingest_ba(settings):
            print(summary)
    elif args.command == "ingest-gvisys":
        print(pipeline.ingest_gvisys(settings))
    elif args.command == "ingest-bkg":
        print(pipeline.ingest_bkg(settings))
    elif args.command == "export-map":
        for path in map_export.export_map(settings):
            print(path)
    elif args.command == "fetch-counts":
        print(
            pipeline.fetch_counts(settings, batch_id=args.batch_id, limit_cities=args.limit_cities)
        )
    elif args.command == "export":
        for path in export.export(settings):
            print(path)
    elif args.command == "status":
        with warehouse.connect(settings.warehouse) as con:
            for table, count in warehouse.table_counts(con).items():
                print(f"landing.{table}: {count:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
