"""运营沙盘 REST API（/api/market/*）。所有写操作写审计；真实外部下单返回 403。"""
from __future__ import annotations
import os, tempfile
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import PlainTextResponse, FileResponse
from . import core as M, store

router = APIRouter(prefix="/api/market", tags=["market-sandbox"])

def _wrap(fn, *a, **k):
    try: return fn(*a, **k)
    except PermissionError as e: raise HTTPException(403, str(e))
    except M.MarketError as e: raise HTTPException(400, str(e))

@router.get("/info")
def info(): return {"mode": M.OPS_MODE, "real_trading": False, "message": M.REAL_SUBMIT_MSG,
                    "cases": list(M.CASE_FILES), "rules": [r["id"] for r in M.list_rules()]}

@router.get("/rules")
def rules(): return M.list_rules()

@router.post("/rules")
def rule_save(body: dict): return _wrap(M.save_custom_rule, body, body.get("actor", "user"))

@router.get("/portfolios")
def portfolios(): return M.list_portfolios()

@router.post("/portfolios/from_case/{key}")
def pf_case(key: str, body: dict | None = None):
    if key not in M.CASE_FILES: raise HTTPException(404, f"未知案例 {key}")
    return _wrap(M.portfolio_from_case, key, (body or {}).get("actor", "user"), (body or {}).get("with_backup", True))

@router.post("/portfolios")
def pf_create(body: dict):
    if body.get("dt_hours",1)!=1: raise HTTPException(400,"市场沙盘仅支持1h；禁止把15min默默当1h")
    return _wrap(M.create_portfolio, body["name"], body["rule_id"], body["resources"], body.get("price_cny_kwh"), body.get("actor", "user"))

@router.get("/portfolios/{pid}")
def pf_get(pid: str): return _wrap(M.get_portfolio, pid)

@router.get("/portfolios/{pid}/capability")
def pf_cap(pid: str): return _wrap(lambda: M.capability(M.get_portfolio(pid)))

@router.get("/portfolios/{pid}/prices")
def pf_prices(pid: str, seed: int = 7): return _wrap(lambda: M.prices(M.get_portfolio(pid), seed))

@router.post("/portfolios/{pid}/dayahead")
def pf_da(pid: str, body: dict | None = None):
    def go():
        b = body or {}; p = M.get_portfolio(pid); pr = M.prices(p, b.get("seed", 7))
        plan = M.optimize(p, pr["forecast"])
        if not plan["ok"]: raise M.MarketError(plan["status"])
        bid = M.build_bid(p, plan, pr["forecast"]); chk = M.check_bid(p, bid, pr["forecast"])
        rec = M.save_bid(p, bid, chk, b.get("actor", "operator"))
        return {"bid": rec, "plan_g": plan["g"], "per": plan["per"], "prices": pr}
    return _wrap(go)

@router.post("/portfolios/{pid}/loop")
def pf_loop(pid: str, body: dict | None = None):
    b = body or {}
    return _wrap(M.run_closed_loop, pid, actor=b.get("actor", "operator"), reviewer=b.get("reviewer", "reviewer"),
                 intraday=b.get("intraday"), instruction=b.get("instruction"), seed=b.get("seed", 7),
                 meter_error_pct=b.get("meter_error_pct", 1.5), auto_approve=b.get("auto_approve", True))

@router.post("/portfolios/{pid}/import/prices")
async def pf_imp_prices(pid: str, file: UploadFile = File(...)):
    return _wrap(M.import_prices_csv, pid, (await file.read()).decode("utf-8-sig"))

@router.post("/dr/baseline")
def dr_bl(body: dict):
    hist = body.get("history") or (M.import_meter_csv(body["csv"]) if body.get("csv") else None)
    if not hist: raise HTTPException(400, "需 history 或 csv")
    return M.dr_baseline(hist, body.get("method", "similar_days_avg"), body.get("event_hours", [19, 20]), body.get("actual"),
                         body.get("n_days", 5), body.get("adjust_window_h", 2), body.get("adjust_cap_pct", 20))

@router.get("/bids")
def bids(portfolio: str | None = None): return M.list_bids(portfolio)

@router.get("/bids/{bid_id}")
def bid_get(bid_id: str): return _wrap(M.get_bid, bid_id)

@router.post("/bids/{bid_id}/transition")
def bid_tr(bid_id: str, body: dict):
    return _wrap(M.transition, bid_id, body["to"], body.get("actor", "user"), body.get("comment", ""))

@router.post("/bids/{bid_id}/external_submit")
def bid_ext(bid_id: str, body: dict | None = None):
    return _wrap(M.transition, bid_id, "external_submit", (body or {}).get("actor", "user"))

@router.get("/bids/{bid_id}/export.csv", response_class=PlainTextResponse)
def bid_csv(bid_id: str): return _wrap(M.export_bid_csv, bid_id)

@router.get("/bids/{bid_id}/export.xlsx")
def bid_xlsx(bid_id: str):
    path = os.path.join(tempfile.mkdtemp(), f"{bid_id}.xlsx"); _wrap(M.export_bid_xlsx, bid_id, path)
    return FileResponse(path, filename=f"{bid_id}_sandbox.xlsx")

@router.get("/audit")
def audit(limit: int = 200, obj: str | None = None): return store.audit_list(limit, obj)

@router.get("/audit/verify")
def audit_verify(): return store.audit_verify()

@router.get("/runs")
def runs(): return list(store.load("runs.json", {}).values())
