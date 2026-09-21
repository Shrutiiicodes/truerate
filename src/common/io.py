"""Persistence: parquet + SQL through SQLAlchemy. Set ITAC_DB_URL to use
PostgreSQL, e.g. postgresql+psycopg2://user:pw@host/itac."""
from __future__ import annotations
import os
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine
from .paths import SQLITE_URL, GENERATED


def db_url() -> str:
    return os.environ.get("ITAC_DB_URL", SQLITE_URL)


def save_table(df: pd.DataFrame, name: str, folder: Path = GENERATED, to_sql: bool = True) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    df.to_parquet(folder / f"{name}.parquet", index=False)
    if to_sql:
        eng = create_engine(db_url())
        out = df.copy()
        for c in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[c]):
                out[c] = out[c].dt.strftime("%Y-%m-%d")
        out.to_sql(name, eng, if_exists="replace", index=False, chunksize=50_000)
        eng.dispose()


def load_table(name: str, folder: Path = GENERATED) -> pd.DataFrame:
    return pd.read_parquet(folder / f"{name}.parquet")
