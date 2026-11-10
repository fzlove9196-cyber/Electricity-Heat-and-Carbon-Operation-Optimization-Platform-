// 运营工作台（P0 沙盘）：组合台账 → 日前申报/检查 → 审批 → 沙盘出清 → 日内 → 实时分解 → DR → 结算 → 审计
(function () {
  const q = s => document.querySelector(s);
  const J = async (u, o) => { const r = await fetch(u, o); const t = await r.text(); let j; try { j = JSON.parse(t) } catch { j = t }
    if (!r.ok) throw new Error((j && j.detail) || t); return j; };
  const post = (u, b) => J(u, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(b || {})});
  const fmt = x => typeof x === "number" ? x.toLocaleString("zh-CN", {maximumFractionDigits: 2}) : String(x);
  const tbl = (rows, cols) => `<table class="tbl"><tr>${cols.map(c => `<th>${c[1]}</th>`).join("")}</tr>${rows.map(r => `<tr>${cols.map(c => `<td>${fmt(typeof c[0] === "function" ? c[0](r) : r[c[0]] ?? "")}</td>`).join("")}</tr>`).join("")}</table>`;
  let cur = "pf-zhongwei", last = null;
  const msg = (t, bad) => { q("#mkMsg").innerHTML = `<span style="color:${bad ? "#c33" : "#2a7"}">${t}</span>`; };
  async function loadCap() {
    const key = cur.slice(3); await post(`/api/market/portfolios/from_case/${key}`);
    const c = await J(`/api/market/portfolios/${cur}/capability`);
    q("#mkCap").innerHTML = `<h4>聚合资源台账 · 规则包 <b>${c.rule}</b></h4>` +
      tbl(c.resources, [["name", "资源"], ["type", "类型"], [r => r.flex_up_mw_max ?? r.power_mw ?? r.pmax_mw, "上调/功率 MW"],
        [r => r.energy_usable_mwh ?? r.batch_mwh ?? "", "可用能量/批处理 MWh"], [r => r.thermal_cap_it_mw_min ?? "", "热安全IT上限 MW"],
        [r => r.cooling_inertia_mwh_th ?? "", "冷却热惯性 MWh_th"], [r => r.type === "diesel" ? (r.market_allowed ? "允许" : "规则禁止") : "", "柴发参与"]]) +
      (c.excluded.length ? `<p class="hint">已剔除（跨省不可混用）：${c.excluded.map(e => e.name).join("、")}</p>` : "");
  }
  async function runLoop() {
    msg("运行闭环中…");
    try { last = await post(`/api/market/portfolios/${cur}/loop`, {seed: +q("#mkSeed").value || 7}); } catch (e) { return msg(e.message, 1); }
    const k = last.kpi; msg(`完成 ${last.run_id} · ${last.rule_label} · ${last.disclaimer}`);
    q("#mkKpi").innerHTML = [["沙盘净成本 元", k.net_cost_cny], ["未优化对照 元", k.cf_net_cost_cny], ["节省 元", k.saving_cny], ["节省 %", k.saving_pct],
      ["偏差 MWh", k.abs_dev_mwh], ["偏差 %", k.abs_dev_pct], ["偏差考核 元", k.deviation_penalty_cny], ["DR 响应率", k.dr_ratio],
      ["DR 补偿 元", k.dr_payment_cny], ["跟踪RMSE MW", k.tracking_rmse_mw], ["热安全", k.thermal_ok ? "✅ 通过" : "❌"], ["最大温变 K/h", k.max_rate_k_h]]
      .map(([a, b]) => `<div class="card" style="display:inline-block;margin:4px;padding:6px 10px;min-width:120px"><div class="hint">${a}</div><b>${fmt(b)}</b></div>`).join("");
    const ch = echarts.init(q("#mkChart")); const x = [...Array(24).keys()];
    ch.setOption({tooltip: {trigger: "axis"}, legend: {}, xAxis: {data: x}, yAxis: [{name: "MW"}, {name: "元/MWh"}],
      series: [["日前计划", last.day_ahead.plan_g], ["日前沙盘中标", last.day_ahead.cleared_mw], ["日内调整", last.intra_day.q_id], ["实际计量", last.real_time.actual_mw]]
        .map(([n, d]) => ({name: n, type: "line", data: d})).concat([{name: "沙盘日前价", type: "bar", yAxisIndex: 1, data: last.prices.da, itemStyle: {opacity: .3}}])});
    const dec = last.real_time.decomposition;
    q("#mkRt").innerHTML = `<h4>实时指令：${dec.instruction.hours.join(",")} 时 下调 ${dec.instruction.mw} MW（${dec.instruction.source || ""}）· 分解顺序 ${dec.order}</h4>` +
      tbl(dec.tickets, [["t", "时"], ["name", "资源"], ["kind", "手段"], ["mw", "MW"], [r => r.note || "", "备注"]]) +
      `<p>热安全：${dec.thermal_ok ? "通过" : "不通过"}；峰值温度 ${JSON.stringify(dec.max_temp_c)}</p>` +
      `<h4>DR 基线（${last.dr.baseline.method}，修正系数 ${last.dr.baseline.adjust_ratio}）</h4><p class="hint">${last.dr.assessment.formula}<br>${last.dr.history_note}</p>`;
    const st = last.settlement;
    q("#mkSt").innerHTML = `<h4>结算复盘（${st.formula}）</h4>` + tbl([st], [["da_cny", "日前"], ["id_cny", "日内"], ["rt_cny", "实时"], ["deviation_penalty_cny", "偏差考核"], ["dr_payment_cny", "DR补偿"], ["dr_penalty_cny", "DR考核"], ["net_cost_cny", "净成本"]]) +
      `<details><summary>逐时</summary>${tbl(st.hours, [["t", "时"], ["q_da", "日前"], ["q_id", "日内"], ["actual", "实际"], ["dev_pct", "偏差%"], ["penalty_cny", "考核元"]])}</details>`;
    loadBids(); loadAudit();
  }
  async function loadBids() {
    const bs = (await J(`/api/market/bids?portfolio=${cur}`)).slice(-8).reverse();
    q("#mkBids").innerHTML = tbl(bs, [["id", "申报"], ["stage", "阶段"], ["status", "状态"], [b => b.check.feasible ? "✅" : "❌ " + (b.check.issues || []).join(";"), "物理检查"],
      [b => `<a href="/api/market/bids/${b.id}/export.csv" target="_blank">CSV</a> <a href="/api/market/bids/${b.id}/export.xlsx">XLSX</a> ` +
        ["submitted", "approved", "rejected"].map(t => `<button class="sm" data-b="${b.id}" data-t="${t}">${t}</button>`).join("") +
        ` <button class="sm" data-b="${b.id}" data-t="external_submit" title="真实外部下单不可执行">真实提交</button>`, "操作"]]).replace(/&lt;/g, "<");
    q("#mkBids").querySelectorAll("button[data-b]").forEach(btn => btn.onclick = async () => {
      const t = btn.dataset.t;
      try { await post(t === "external_submit" ? `/api/market/bids/${btn.dataset.b}/external_submit` : `/api/market/bids/${btn.dataset.b}/transition`,
        {to: t, actor: q("#mkActor").value}); msg(`${btn.dataset.b} → ${t}`); } catch (e) { msg(e.message, 1); }
      loadBids(); loadAudit(); });
  }
  async function loadAudit() {
    const [a, v] = await Promise.all([J("/api/market/audit?limit=15"), J("/api/market/audit/verify")]);
    q("#mkAudit").innerHTML = `<p>哈希链校验：${v.ok ? "✅ 完整" : "❌ 断裂"}（${v.n ?? ""} 条）</p>` +
      tbl(a.reverse(), [["ts", "时间"], ["actor", "操作人"], ["action", "动作"], ["obj", "对象"], [r => r.ok ? "✓" : "拒绝", "结果"], ["hash", "哈希"]]);
  }
  window.loadMarket = async function () {
    const info = await J("/api/market/info"); q("#mkInfo").textContent = `模式：${info.mode}（${info.message}）`;
    await loadCap(); loadBids(); loadAudit();
  };
  document.addEventListener("DOMContentLoaded", () => {
    q("#mkCase").onchange = e => { cur = "pf-" + e.target.value; window.loadMarket(); };
    q("#mkRun").onclick = runLoop;
    q("#mkPriceFile").onchange = async e => { const fd = new FormData(); fd.append("file", e.target.files[0]);
      try { await J(`/api/market/portfolios/${cur}/import/prices`, {method: "POST", body: fd}); msg("已导入价格 CSV（覆盖沙盘预测价）"); } catch (er) { msg(er.message, 1); } };
  });
})();
