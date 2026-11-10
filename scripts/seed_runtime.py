#!/usr/bin/env python3
"""Create an empty DATA_DIR's foundation catalog and import knowledge_seed.

Safe to re-run: foundation seed and knowledge seed are both idempotent
(templates/library are skipped if already present; knowledge is skipped if
any document already exists).

Usage (from the repository root, with the venv active):

    python scripts/seed_runtime.py
    # or
    DATA_DIR=./data python scripts/seed_runtime.py
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

def main():
    from app.foundation import service as F, store as S
    from app import knowledge as kb
    with S.LOCK:
        F.seed()
        F.seed_public_climate()
        catalog = {k: S.all(k) for k in ("template", "library", "project", "scenario", "version", "task")}
    kb_out = kb.seed_from_repo()
    summary = {
        "data_dir": os.path.abspath(__import__("app.settings", fromlist=["DATA_DIR"]).DATA_DIR),
        "foundation": {k: len(v) for k, v in catalog.items()},
        "knowledge": {k: kb_out.get(k) for k in ("ok", "seeded", "reason", "n_docs", "errors") if k in kb_out or k == "ok"},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not kb_out.get("ok", True):
        sys.exit(1)

if __name__ == "__main__":
    main()
