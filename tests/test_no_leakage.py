"""The audit engine must never see the answers. Fails if any audit_engine module
references ground-truth paths, the evaluation package, the client's engine or its
fault-injection config - statically (source/imports) or at runtime (sys.modules)."""
import ast
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "src" / "audit_engine"
FORBIDDEN_TEXT = ["ground_truth", "injected_faults", "affected_loan_periods", "correct_ledger", "injection.yaml"]
FORBIDDEN_IMPORTS = ["src.evaluation", "src.client_system", "evaluation", "client_system"]


def test_audit_engine_source_has_no_ground_truth_references():
    for py in AUDIT.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        for bad in FORBIDDEN_TEXT:
            assert bad not in text, f"{py.name} references '{bad}'"


def test_audit_engine_imports_are_clean():
    for py in AUDIT.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert not any(n == f or n.startswith(f + ".") for f in FORBIDDEN_IMPORTS), f"{py.name} imports {n}"


def test_shared_modules_do_not_expose_ground_truth():
    for py in (ROOT / "src" / "common").glob("*.py"):
        assert "ground_truth" not in py.read_text(encoding="utf-8"), f"common/{py.name} exposes ground truth"
    assert "ground_truth" not in (ROOT / "config" / "audit.yaml").read_text(encoding="utf-8")


def test_runtime_import_graph_is_clean():
    code = ("import sys; import src.audit_engine.run, src.audit_engine.attribution; "
            "bad=[m for m in sys.modules if m.startswith(('src.evaluation','src.client_system'))]; "
            "print(','.join(bad)); sys.exit(1 if bad else 0)")
    res = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, f"audit engine pulled in: {res.stdout} {res.stderr}"
