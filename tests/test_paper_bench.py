"""Paper-bench：用已核验公开数字对照引擎；不编造论文数值。"""
import json, os, subprocess, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, "cases", "paper_bench", "run_paper_bench.py")
RES = os.path.join(ROOT, "cases", "paper_bench", "meta", "results.json")


# always run paper_bench
def test_paper_bench_all_pass():
    py = os.environ.get("SDCO_PYTHON")
    if not py:
        for cand in (
            os.path.join(ROOT, ".venv", "bin", "python"),
            "/workspace/sdco-env/bin/python",
            sys.executable,
        ):
            if os.path.isfile(cand):
                py = cand
                break
        else:
            py = sys.executable
    r = subprocess.run([py, RUN], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
    data = json.load(open(RES, encoding="utf-8"))
    assert data["n_fail"] == 0, data
    assert data["n_pass"] >= 5
    for row in data["results"]:
        assert row["pass_fail"] == "PASS", row


def test_manifest_has_sourced_urls():
    man = json.load(open(os.path.join(ROOT, "cases", "paper_bench", "meta", "manifest.json"), encoding="utf-8"))
    assert len(man) >= 5
    for cid, meta in man.items():
        assert meta["paper"].get("url"), cid
        assert "sourced" in meta and "assumed" in meta
