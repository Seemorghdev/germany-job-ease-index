"""Parsers for one source each. A source turns a raw file or response into typed rows.

Adding a data source means adding one module here, one landing table in ``warehouse``,
and a staging model in ``dbt/models/staging``. Nothing else needs to change.
"""
