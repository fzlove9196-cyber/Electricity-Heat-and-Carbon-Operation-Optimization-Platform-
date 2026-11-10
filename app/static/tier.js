/* 三级优化面板：日前基线 / 日内滚动 / 实时跟踪 + 可行域带宽 */
(function () {
  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  function sid() {
    return (window.App && App.sessionId) || localStorage.getItem("sid") || "";
  }
  async function api(path, body) {
    const s = sid();
    const opt = body == null
      ? { method: "GET" }
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const r = await fetch(`/api/sessions/${s}/tier${path}`, opt);
    return r.json();
  }
  function ensurePanel() {
    let box = document.getElementById("tierPanel");
    if (box) return box;
    const stepCol = document.getElementById("tierHost") || document.getElementById("stepCol") || document.getElementById("stepBody");
    box = el("div", "tier-panel");
    box.id = "tierPanel";
    box.innerHTML = `
      <div class="tier-h">⏱ 三级优化
        <button type="button" class="sm ghost" id="tierRefresh">刷新</button>
        <button type="button" class="sm" id="tierRunDA">日前基线</button>
        <button type="button" class="sm" id="tierRunID">日内滚动</button>
        <button type="button" class="sm ghost" id="tierRunEnv">可行域</button>
        <button type="button" class="sm ghost" id="tierRunRT">实时跟踪</button>
        <button type="button" class="sm ghost" id="tierBackup">UPS/柴发</button>
        <button type="button" class="sm ghost" id="tierEmerg">应急</button>
      </div>
      <div class="tier-soc" style="margin:6px 0;font-size:12px">
        <label>SOC实测(JSON，可选) <input id="tierSocMeas" placeholder='{"ESS_ZW":0.42}' style="width:220px"/></label>
        <label style="margin-left:8px">from_t <input id="tierFromT" type="number" value="8" min="0" max="23" style="width:48px"/></label>
      </div>
      <div id="tierMsg" class="muted"></div>
      <div id="tierBackupInfo" class="muted" style="font-size:12px"></div>
      <div id="tierTimeline" class="tier-tl"></div>
      <div id="tierCharts" class="tier-charts">
        <div id="tierSiteChart" style="height:220px"></div>
        <div id="tierEnvChart" style="height:220px"></div>
      </div>`;
    if (stepCol) stepCol.prepend(box);
    else document.querySelector("main")?.appendChild(box);
    document.getElementById("tierRefresh").onclick = () => refresh();
    document.getElementById("tierRunDA").onclick = async () => {
      setMsg("求解日前基线…"); await api("/baseline", {}); await refresh();
    };
    document.getElementById("tierRunID").onclick = async () => {
      setMsg("日内滚动（可先改预测/SOC实测）…");
      const fromT = parseInt(document.getElementById("tierFromT")?.value || "8", 10);
      const body = { from_t: fromT, text_patch: "光伏降10%" };
      const raw = (document.getElementById("tierSocMeas")?.value || "").trim();
      if (raw) {
        try { body.soc_measured = JSON.parse(raw); }
        catch (e) { setMsg("SOC JSON 无效: " + e); return; }
      }
      await api("/reoptimize", body); await refresh();
    };
    document.getElementById("tierBackup").onclick = async () => {
      setMsg("配置【假设】UPS + 柴发…");
      await api("/backup", { ups: true, diesel: true, replace: true });
      await refresh();
    };
    document.getElementById("tierEmerg").onclick = async () => {
      setMsg("切换应急模式…");
      const cur = window._tierEmerg || false;
      const out = await api("/emergency", { enabled: !cur });
      window._tierEmerg = !!(out && out.emergency_mode);
      setMsg("emergency_mode=" + window._tierEmerg);
      await refresh();
    };
    document.getElementById("tierRunEnv").onclick = async () => {
      setMsg("计算可行域…");
      await api("/envelope", { stage: "day_ahead", stride: 2 });
      await api("/envelope", { stage: "intra_day", from_t: 8, stride: 2 });
      await refresh();
    };
    document.getElementById("tierRunRT").onclick = async () => {
      setMsg("实时 MPC-lite…"); await api("/realtime", { mode: "mpc_lite", dt_min: 10 }); await refresh();
    };
    return box;
  }
  function setMsg(t) { const m = document.getElementById("tierMsg"); if (m) m.textContent = t || ""; }
  function renderTimeline(data) {
    const box = document.getElementById("tierTimeline");
    if (!box) return;
    const tl = data.timeline || [];
    if (!tl.length) { box.innerHTML = "<span class='muted'>尚无三级时间线。可点「日前基线」或对话「三级优化」。</span>"; return; }
    box.innerHTML = tl.map(x => {
      const st = x.stage || "";
      const detail = st === "real_time"
        ? `RMSE ${x.rmse_mw?.toFixed?.(2) ?? x.rmse_mw} MW · Tin≤${x.max_tin_c?.toFixed?.(1) ?? "—"}°C`
        : `成本 ${x.cost_cny != null ? Math.round(x.cost_cny) : "—"} · 碳 ${x.emissions_tco2 != null ? Number(x.emissions_tco2).toFixed(2) : "—"} t · 热安全 ${x.thermal_safe ?? "—"}`
          + (x.soc_source ? ` · SOC:${x.soc_source}` : "");
      return `<div class="tier-pill ${st}"><b>${({day_ahead:"日前基线",intra_day:"日内滚动",real_time:"实时跟踪"}[st]||st)}</b><span>${detail}</span></div>`;
    }).join("");
  }
  function chartSite(data) {
    const dom = document.getElementById("tierSiteChart");
    if (!dom || !window.echarts) return;
    const da = data.baseline_meta?.site_grid_mw || [];
    const id = data.intra_day_site_mw || [];
    if (!da.length && !id.length) { dom.innerHTML = ""; return; }
    const c = echarts.init(dom);
    const hours = Array.from({ length: 24 }, (_, i) => i);
    c.setOption({
      title: { text: "关口功率：日前基线 vs 日内滚动", left: 0, textStyle: { fontSize: 12 } },
      tooltip: { trigger: "axis" },
      legend: { data: ["日前基线", "日内滚动"], top: 20 },
      grid: { left: 50, right: 20, top: 50, bottom: 30 },
      xAxis: { type: "category", data: hours, name: "h" },
      yAxis: { type: "value", name: "MW" },
      series: [
        { name: "日前基线", type: "line", data: da, showSymbol: false },
        { name: "日内滚动", type: "line", data: id, showSymbol: false, lineStyle: { type: "dashed" } },
      ],
    });
  }
  function chartEnv(data) {
    const dom = document.getElementById("tierEnvChart");
    if (!dom || !window.echarts) return;
    const eh = data.envelope_hours || {};
    const da = eh.day_ahead || [];
    const id = eh.intra_day || [];
    if (!da.length && !id.length) { dom.innerHTML = ""; return; }
    const c = echarts.init(dom);
    const mk = (rows, key) => (rows || []).filter(r => r.ok).map(r => [r.hour, r[key]]);
    c.setOption({
      title: { text: "可行响应域带宽（逐步收缩）", left: 0, textStyle: { fontSize: 12 } },
      tooltip: { trigger: "axis" },
      legend: { data: ["日前上", "日前下", "日内上", "日内下"], top: 20 },
      grid: { left: 50, right: 20, top: 50, bottom: 30 },
      xAxis: { type: "value", name: "h", min: 0, max: 23 },
      yAxis: { type: "value", name: "MW" },
      series: [
        { name: "日前上", type: "line", data: mk(da, "p_up_mw"), showSymbol: true },
        { name: "日前下", type: "line", data: mk(da, "p_down_mw"), showSymbol: true, areaStyle: { opacity: 0.08 } },
        { name: "日内上", type: "line", data: mk(id, "p_up_mw"), showSymbol: true, lineStyle: { type: "dashed" } },
        { name: "日内下", type: "line", data: mk(id, "p_down_mw"), showSymbol: true, lineStyle: { type: "dashed" } },
      ],
    });
  }
  async function refresh() {
    ensurePanel();
    try {
      const data = await api("");
      if (!data || data.ok === false) { setMsg(data?.error || "无三级数据"); return; }
      renderTimeline(data);
      chartSite(data);
      chartEnv(data);
      const soc = data.last_roll?.soc_source ? ` · SOC来源 ${data.last_roll.soc_source}` : "";
      const bak = document.getElementById("tierBackupInfo");
      if (bak) {
        const b = data.backup?.resources || [];
        bak.textContent = b.length
          ? ("备用资源: " + b.map(r => r.type + ":" + r.name).join(", ") + (data.emergency_mode ? " · 应急ON" : ""))
          : (data.emergency_mode ? "应急ON（尚未配置 UPS/柴发）" : "");
      }
      if (typeof data.emergency_mode === "boolean") window._tierEmerg = data.emergency_mode;
      setMsg(`时间线 ${ (data.timeline||[]).length } 步` + (data.last_patch ? ` · 补丁 ${JSON.stringify(data.last_patch.patch||{})}` : "") + soc);
    } catch (e) {
      setMsg(String(e));
    }
  }
  function boot() {
    ensurePanel();
    // soft refresh when session changes
    document.addEventListener("tier:refresh", refresh);
    setTimeout(refresh, 800);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  window.TierPanel = { refresh, ensurePanel };
})();
