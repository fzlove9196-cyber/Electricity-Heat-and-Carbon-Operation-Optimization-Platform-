"""B2: SPECpower_ssj2008 公开结果 (40 台服务器, 2007-2026 均匀抽样) 验证 利用率->功率 映射。
来源 https://www.spec.org/power_ssj2008/results/ (公开发布结果, SPEC 使用条款允许引用公开结果; 本仓库仅保存原文用于复现)
模型 (直接调用 app.power_model):
  identity    : P = u * P_peak (引擎默认 power_model='identity' 的隐含假设：电功率与工作量成正比)
  idle_dynamic: P = P_idle + (P_peak-P_idle) u  (仅用 Active Idle 与 100% 两点标定)
  pdu_pwl_3   : 断点 u={0, 0.5实测, 1实测} (3 点标定, 其余 8 点留出)
误差在留出负载点 (实测 Actual Load 10%..90%) 上计算。"""
import re, os, sys, glob, json, hashlib
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from app import power_model as PM
D = os.path.join(os.path.dirname(__file__), "raw/specpower"); OUT = os.path.join(os.path.dirname(__file__), "results")
rows = []
for f in sorted(glob.glob(D + "/power_ssj2008-*.txt")):
    t = open(f, errors="ignore").read()
    m = re.findall(r"^\s*(\d+)%\s*\|\s*([\d.]+)%\s*\|\s*[\d,]+\s*\|\s*([\d,.]+)\s*\|", t, re.M)
    idle = re.search(r"Active Idle\s*\|\s*0\s*\|\s*([\d,.]+)", t)
    if len(m) < 10 or not idle: continue
    sut = re.search(r"Hardware Vendor:\s*(.+)", t); mdl = re.search(r"Model:\s*(.+)", t); yr = re.search(r"Hardware Availability:\s*(.+)", t)
    u = np.array([float(a)/100 for _, a, _ in m[:10]]); p = np.array([float(c.replace(",", "")) for *_, c in m[:10]])
    rows.append(dict(file=os.path.basename(f), sha256=hashlib.sha256(open(f, "rb").read()).hexdigest(),
                     vendor=(sut.group(1).strip() if sut else ""), model=(mdl.group(1).strip() if mdl else ""), avail=(yr.group(1).strip() if yr else ""),
                     util=u.tolist(), power_w=p.tolist(), idle_w=float(idle.group(1).replace(",", ""))))
res = []
for r in rows:
    u = np.array(r["util"]); p = np.array(r["power_w"]); idle = r["idle_w"]; i100 = 0; i50 = 5
    peak_u, peak_p = u[i100], p[i100]
    hold = [i for i in range(1, 10) if i != i50]            # 留出 90%..10% 中除 50% 的 8 点
    peak_extrap = idle + (peak_p - idle)/peak_u               # 线性外推到 u=1
    pred_id = np.array([PM.eval_idle_dynamic(u[i], 1.0, idle, peak_extrap) for i in hold])
    pred_iden = np.array([u[i]*peak_extrap for i in hold])
    bps = [(0.0, idle), (u[i50], p[i50]), (peak_u, peak_p)]
    pred_pwl = np.array([PM.eval_pwl(u[i], bps) for i in hold])
    bps5 = PM.breakpoints_from_curve(u[[0, 2, 5, 8]], p[[0, 2, 5, 8]], idle_mw=idle)   # 标定点: idle,80%,50%,20%(实测) ; 留出点同上去掉 2,8
    hold5 = [i for i in hold if i not in (2, 8)]
    pred_pwl5 = np.array([PM.eval_pwl(u[i], bps5) for i in hold5]); y5 = p[hold5]
    y = p[hold]
    e = lambda pr: float(np.mean(np.abs(pr - y)/y)*100)
    res.append(dict(file=r["file"], vendor=r["vendor"], model=r["model"], avail=r["avail"], idle_frac=idle/peak_p,
                    mape_identity=e(pred_iden), mape_idle_dynamic=e(pred_id), mape_pwl3=e(pred_pwl), mape_pwl5=float(np.mean(np.abs(pred_pwl5-y5)/y5)*100), mape_idle_dynamic_same_holdout=float(np.mean(np.abs(pred_id[[hold.index(i) for i in hold5]]-y5)/y5)*100),
                    maxape_idle_dynamic=float(np.max(np.abs(pred_id-y)/y)*100)))
A = lambda k: np.array([x[k] for x in res])
summ = {k: dict(median=float(np.median(A(k))), p90=float(np.percentile(A(k), 90)), max=float(A(k).max())) for k in ("mape_identity", "mape_idle_dynamic", "mape_pwl3", "mape_pwl5", "mape_idle_dynamic_same_holdout", "maxape_idle_dynamic", "idle_frac")}
crit = dict(idle_dynamic_median_mape_le_5=summ["mape_idle_dynamic"]["median"] <= 5, pwl3_median_mape_le_3=summ["mape_pwl3"]["median"] <= 3,
            pwl3_better_than_idle_dynamic=summ["mape_pwl3"]["median"] <= summ["mape_idle_dynamic"]["median"],
            pwl5_median_mape_le_3=summ["mape_pwl5"]["median"] <= 3, pwl5_p90_mape_le_5=summ["mape_pwl5"]["p90"] <= 5)
# 早期(<=2012) vs 近年(>=2018)
def yr(s):
    m = re.search(r"(20\d\d)", s); return int(m.group(1)) if m else None
for lab, cond in (("avail<=2012", lambda y: y and y <= 2012), ("avail>=2018", lambda y: y and y >= 2018)):
    sel = [x for x in res if cond(yr(x["avail"]))]
    if sel: summ[lab] = dict(n=len(sel), idle_frac_median=float(np.median([x["idle_frac"] for x in sel])),
                             idle_dynamic_mape_median=float(np.median([x["mape_idle_dynamic"] for x in sel])),
                             identity_mape_median=float(np.median([x["mape_identity"] for x in sel])))
out = dict(n_servers=len(res), summary=summ, criteria=crit, per_server=res, raw=[{k: r[k] for k in ("file", "sha256", "util", "power_w", "idle_w")} for r in rows])
json.dump(out, open(OUT + "/b2_specpower.json", "w"), indent=1, ensure_ascii=False)
print(len(res), json.dumps(summ, indent=1), crit)
