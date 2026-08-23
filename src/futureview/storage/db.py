from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb
import polars as pl


class DuckStore:
    """Small persistence layer for market data, rankings, and backtest state."""

    def __init__(self, path: str | Path = "data/futureview.duckdb") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

    def initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        schema = schema_path.read_text(encoding="utf-8")
        with self.connect() as con:
            con.execute(schema)

    def upsert_frame(self, table: str, frame: pl.DataFrame) -> None:
        """Insert or replace rows using the destination table's primary key."""
        if frame.is_empty():
            return
        with self.connect() as con:
            con.register("incoming_frame", frame.to_arrow())
            con.execute(
                f"INSERT OR REPLACE INTO {table} BY NAME SELECT * FROM incoming_frame"
            )
            con.unregister("incoming_frame")

    def query(self, sql: str, params: Iterable[object] | None = None) -> pl.DataFrame:
        with self.connect() as con:
            relation = con.execute(sql, list(params or []))
            return pl.from_arrow(relation.fetch_arrow_table())

    def latest_rankings(self, limit: int = 50) -> pl.DataFrame:
        return self.query(
            """
            SELECT *
            FROM daily_rankings
            WHERE date = (SELECT max(date) FROM daily_rankings)
            ORDER BY rank
            LIMIT ?
            """,
            [limit],
        )
