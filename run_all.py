"""One command to run the whole engagement end to end.

    python run_all.py            # all stages
    python run_all.py --pause    # stop at each stage checkpoint for review
    python run_all.py --from audit   # rerun from a stage (generate|client|audit|report|evaluate)
"""
from __future__ import annotations
import argparse
import time

from src.generator.run import main as generate
from src.client_system.run import main as client
from src.audit_engine.run import main as audit
from src.reporting.run import main as report
from src.evaluation.evaluate import main as evaluate

STAGES = [
    ("generate", "Stages 1-2: reference data, portfolio and transactions", generate),
    ("client", "Stage 3: client core banking system with injected faults", client),
    ("audit", "Stages 4-5: full-population recalculation, exceptions, attribution", audit),
    ("report", "Stage 6: RCM, work paper, materiality, Power BI exports, charts", report),
    ("evaluate", "Stage 7: evaluation against ground truth", evaluate),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pause", action="store_true", help="wait for Enter after each stage")
    ap.add_argument("--from", dest="start", default="generate", choices=[s[0] for s in STAGES])
    args = ap.parse_args()
    names = [s[0] for s in STAGES]
    t0 = time.time()
    for key, label, fn in STAGES[names.index(args.start):]:
        print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
        t = time.time()
        fn()
        print(f"--> {key} finished in {time.time() - t:.1f}s")
        if args.pause:
            input("Checkpoint - review the output above, then press Enter to continue...")
    print(f"\nAll stages complete in {time.time() - t0:.1f}s. Outputs in ./outputs")


if __name__ == "__main__":
    main()
