"""Reading .xlsx workbooks, including ones shipped inside a ZIP archive."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, cast

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet._read_only import ReadOnlyWorksheet


class WorkbookError(ValueError):
    """The file isn't the workbook we expected."""


class RowSource(Protocol):
    """The part of a worksheet we read. openpyxl's stubs mistype ``iter_rows`` on
    read-only sheets, so sheets are exposed through this protocol instead."""

    def iter_rows(
        self,
        min_row: int | None = None,
        max_row: int | None = None,
        min_col: int | None = None,
        max_col: int | None = None,
        values_only: bool = False,
    ) -> Iterator[tuple[Any, ...]]: ...


def _is_xlsx(names: list[str]) -> bool:
    return "[Content_Types].xml" in names and "xl/workbook.xml" in names


def read_xlsx_bytes(path: Path, inner_suffix: str | None = None) -> bytes:
    """Return the .xlsx bytes, unwrapping one ZIP layer if the file is an archive."""
    data = path.read_bytes()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise WorkbookError(f"{path.name} is neither an .xlsx file nor a ZIP archive") from exc
    with archive:
        names = archive.namelist()
        if _is_xlsx(names):
            return data
        candidates = [
            n
            for n in names
            if n.lower().endswith(".xlsx") and (inner_suffix is None or n.endswith(inner_suffix))
        ]
        if len(candidates) != 1:
            raise WorkbookError(
                f"{path.name}: expected exactly one inner workbook"
                f"{f' ending in {inner_suffix!r}' if inner_suffix else ''}, found {candidates}"
            )
        return archive.read(candidates[0])


@contextmanager
def open_workbook(path: Path, inner_suffix: str | None = None) -> Iterator[Workbook]:
    workbook = openpyxl.load_workbook(
        io.BytesIO(read_xlsx_bytes(path, inner_suffix)), read_only=True, data_only=True
    )
    try:
        yield workbook
    finally:
        workbook.close()


def sheet(workbook: Workbook, name: str) -> RowSource:
    if name not in workbook.sheetnames:
        raise WorkbookError(f"no sheet {name!r}; available: {workbook.sheetnames}")
    worksheet = workbook[name]
    if not isinstance(worksheet, ReadOnlyWorksheet):
        raise WorkbookError(f"sheet {name!r} is not a worksheet")
    return cast(RowSource, worksheet)


def iter_columns(
    worksheet: RowSource, columns: Mapping[str, str]
) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield ``(row_number, {field: value})`` for the named column letters."""
    index = {field: column_index_from_string(letter) - 1 for field, letter in columns.items()}
    width = max(index.values()) + 1
    for row_number, row in enumerate(worksheet.iter_rows(max_col=width, values_only=True), start=1):
        yield row_number, {f: (row[i] if i < len(row) else None) for f, i in index.items()}


def preview(path: Path, *, sheet_name: str | None, rows: int, inner_suffix: str | None) -> str:
    """A plain-text preview of a sheet, with column letters, to confirm a layout by eye."""
    with open_workbook(path, inner_suffix) as workbook:
        lines = [f"sheets: {workbook.sheetnames}"]
        name = sheet_name or workbook.sheetnames[0]
        worksheet = sheet(workbook, name)
        lines.append(f"--- sheet {name!r}, first {rows} rows ---")
        for row_number, row in enumerate(
            worksheet.iter_rows(max_row=rows, values_only=True), start=1
        ):
            cells = [
                f"{get_column_letter(i)}={value!r}"
                for i, value in enumerate(row, start=1)
                if value is not None
            ]
            lines.append(f"{row_number:>3}: " + " | ".join(cells))
    return "\n".join(lines)
