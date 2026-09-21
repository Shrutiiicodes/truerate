"""Stage 1-2 driver: reference data, portfolio, transactions -> parquet + SQL."""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from src.common.config import load_yaml
from src.common.io import save_table
from src.client_system.book import build_book
from .reference import write_benchmarks
from .portfolio import generate_loans, product_master_table
from .transactions import build_skeleton, resolve_and_tabulate


def main() -> dict:
    t0 = time.time()
    cfg = load_yaml("products.yaml")
    rng = np.random.default_rng(cfg["portfolio"]["seed"])
    bench = write_benchmarks()
    loans = generate_loans(cfg, rng)
    book = build_book(loans, cfg, bench)
    ev = build_skeleton(book, cfg, rng)
    tx = resolve_and_tabulate(book, ev)
    save_table(product_master_table(cfg), "products")
    save_table(loans, "loans")
    save_table(bench, "benchmark_rates")
    save_table(tx, "transactions")
    checkpoint(loans, tx)
    print(f"[generator] done in {time.time() - t0:.1f}s")
    return {"loans": len(loans), "transactions": len(tx)}


def checkpoint(loans: pd.DataFrame, tx: pd.DataFrame) -> None:
    print("\n=== CHECKPOINT - Stage 2: portfolio summary by product ===")
    s = loans.groupby("product_code").agg(
        loans=("loan_id", "size"), principal_cr=("principal_inr", lambda x: x.sum() / 1e7),
        median_principal=("principal_inr", "median"), median_tenure=("tenure_months", "median"),
        with_moratorium=("moratorium_months", lambda x: int((x > 0).sum())),
        premium_mean=("risk_premium_pct", "mean"))
    t = tx.merge(loans[["loan_id", "product_code"]], on="loan_id").pivot_table(
        index="product_code", columns="txn_type", values="txn_id", aggfunc="count", fill_value=0)
    print(s.round(2).to_string())
    print("\nTransactions by type:")
    print(t.to_string())


if __name__ == "__main__":
    main()
