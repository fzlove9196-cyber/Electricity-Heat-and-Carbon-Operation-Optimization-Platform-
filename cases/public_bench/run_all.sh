#!/usr/bin/env bash
# 复现全部公开基准（需先按 results/manifest.json 中 URL 下载 raw/；脚本只读 raw/，不覆盖旧结果以外文件）
set -e; cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
if [ -z "${PY:-}" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
  elif [ -x /workspace/sdco-env/bin/python ]; then PY=/workspace/sdco-env/bin/python
  else PY="${SDCO_PYTHON:-python3}"; fi
fi
SDCO_DC_IGNORE_TAP=1 $PY bench_grid_dcopf.py --tag before; $PY bench_grid_dcopf.py --tag after
$PY bench_specpower.py
$PY bench_market_aemo.py --tag nominal_before_fix --legacy-core; $PY bench_market_aemo.py --tag nominal_after
$PY bench_market_aemo.py --tag stress_before_fix --chiller 1.05 --legacy-core; $PY bench_market_aemo.py --tag stress_after --chiller 1.05
$PY bench_dr_bdg2.py; $PY bench_dr_bdg2_agg.py; $PY bench_dr_methods.py; $PY make_report.py
