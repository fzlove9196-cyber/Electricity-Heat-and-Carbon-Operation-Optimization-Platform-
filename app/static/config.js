// 🧪 配置构建器 + 散热方式库 + 对比/扫描 + 余热供暖可行性
(function () {
  let MODES = [], TERMS = {}, SPEC = null;
  const sid = () => { if (!SID) { SID = Math.random().toString(36).slice(2, 14).replace(/[^a-z0-9]/g, "x"); localStorage.setItem("sid", SID); } return SID; };
  const num = v => v === "" || v == null ? null : +v;
  const opt = (arr, v) => arr.map(([k, n]) => `<option value="${k}" ${k === v ? "selected" : ""}>${esc(n)}</option>`).join("");
  const modeOpts = v => opt(MODES.map(m => [m.key, m.icon + " " + m.cn]), v);
  const termOpts = v => opt(Object.entries(TERMS).map(([k, t]) => [k, `${t.cn}（${t.t_min}-${t.t_max}°C）`]), v);
  const inp = (path, v, w = 70, t = "number") => `<input data-p="${path}" type="${t}" value="${v ?? ""}" style="width:${w}px" step="any">`;
  function libHtml() {
    return `<div class="cfg-lib">` + MODES.map(m => `<div class="cfg-mode ${m.family}"><b>${m.icon} ${esc(m.cn)}</b>
      <div class="muted">送/回 ${m.supply_c}/${m.return_c}°C · 自然冷却 ${m.free_basis === "wet" ? "湿球" : (m.free_basis === "dec" ? "蒸发送风温度" : "干球")} ≤${m.free_full_c}°C 满/≥${m.free_zero_c}°C 无 · WUE ${m.wue_l_kwh} L/kWh</div>
      <div class="muted">余热源 ${m.waste_heat_c}°C · 回收比例 ${m.hr_max_frac} · 典型 PUE ${m.pue_typical} · 投资 ${m.capex_cny_kw} 元/kW</div>
      <div class="muted">安全边界：${m.family === "liquid" ? `供液 ≤${m.coolant_limit_c}°C，芯片代理 ≤85°C` : `入口 ${m.t_min_c}-${m.t_rec_max_c}(推荐)/${m.t_allow_max_c}°C(允许, ASHRAE A1)`}</div>
      <div class="cfg-src">${m.sources.map(s => `<span class="tag" title="${esc(s)}">文献</span>`).join("")} ${esc(m.note)}</div></div>`).join("") + `</div>`;
  }
  function dcRow(d, i) {
    const P = `dcs.${i}.`;
    return `<tr><td>${inp(P + "name", d.name, 70, "text")}</td><td>${inp(P + "cap_it_mw", d.cap_it_mw)}</td><td>${inp(P + "racks", d.racks, 60)}</td>
      <td>${inp(P + "utilization", d.utilization, 50)}</td><td>${inp(P + "flex_share", d.flex_share, 50)}</td>
      <td><select data-p="${P}cooling_mode">${modeOpts(d.cooling_mode)}</select></td><td>${inp(P + "liquid_frac", d.liquid_frac, 50)}</td>
      <td><select data-p="${P}tes_type">${opt([["water", "水蓄冷"], ["ice", "冰蓄冷"]], d.tes_type)}</select>${inp(P + "tes_mwh", d.tes_mwh, 55)}${inp(P + "tes_mw", d.tes_mw, 50)}</td>
      <td>${inp(P + "hp_mw", d.hp_mw, 55)}<select data-p="${P}hp_type">${opt([["standard", "常规≤80°C"], ["high_temp", "高温≤95°C"]], d.hp_type)}</select></td>
      <td><button class="sm ghost" data-del="${i}">✕</button></td></tr>`;
  }
  function form() {
    const s = SPEC, b = s.battery, src = s.sources, h = s.heat, v = s.virtual;
    return `<div class="cfg-grid">
     <fieldset><legend>基本</legend>名称 ${inp("name", s.name, 160, "text")} 季节 <select data-p="season">${opt([["winter", "冬季(采暖)"], ["summer", "夏季"], ["heatwave", "热浪"]], s.season)}</select>
       气候 <select data-p="climate">${opt([["zhongwei", "中卫"], ["hohhot", "呼和浩特"], ["beijing", "北京"], ["shanghai", "上海"]], s.climate)}</select> 碳价 ${inp("carbon_price", s.carbon_price, 60)} 碳权重 ${inp("carbon_weight", s.carbon_weight, 50)}</fieldset>
     <fieldset class="wide"><legend>数据中心与散热方式 <button class="sm" id="cfgAddDc">＋ 数据中心</button></legend>
      <table class="tbl cfg-dc"><tr><th>名称</th><th>IT MW</th><th>机柜</th><th>利用率</th><th>可调比例</th><th>散热方式</th><th>液冷比例</th><th>蓄冷 类型/MWh/MW</th><th>热泵 MW/类型</th><th></th></tr>
      ${s.dcs.map(dcRow).join("")}</table></fieldset>
     <fieldset><legend>蓄能配置</legend>电池 功率 ${inp("battery.power_mw", b.power_mw)} MW 容量 ${inp("battery.energy_mwh", b.energy_mwh)} MWh 效率 ${inp("battery.eta", b.eta, 50)} SOC ${inp("battery.soc_min", b.soc_min, 45)}–${inp("battery.soc_max", b.soc_max, 45)}<br>
       蓄热罐 ${inp("heat_storage.mwh", s.heat_storage.mwh)} MWh ${inp("heat_storage.mw", s.heat_storage.mw)} MW<br>
       虚拟储能/杠杆：${["precool:虚拟储冷(预冷)", "tes:蓄冷罐", "heat:余热供热", "dr:需求响应"].map(x => { const [k, n] = x.split(":"); return `<label><input type="checkbox" data-p="virtual.${k}" ${v[k] ? "checked" : ""}> ${n}</label>`; }).join(" ")}</fieldset>
     <fieldset><legend>能源配置</legend>风电 ${inp("sources.wind_mw", src.wind_mw)} 光伏 ${inp("sources.pv_mw", src.pv_mw)} 火电 ${inp("sources.thermal_mw", src.thermal_mw)} 水电 ${inp("sources.hydro_mw", src.hydro_mw)}<br>
       燃气CHP ${inp("sources.gas_chp_mw", src.gas_chp_mw)} 外网购电上限 ${inp("sources.grid_import_mw", src.grid_import_mw)} 外送 ${inp("sources.grid_export_mw", src.grid_export_mw)} MW · PPA 价 ${inp("sources.ppa_price", src.ppa_price, 60)} 元/kWh</fieldset>
     <fieldset><legend>余热品位与供热末端</legend><label><input type="checkbox" data-p="heat.enabled" ${h.enabled ? "checked" : ""}> 启用供热</label>
       末端 <select data-p="heat.terminal_type">${termOpts(h.terminal_type)}</select> 管线 ${inp("heat.pipe_length_km", h.pipe_length_km, 50)} km 温降 ${inp("heat.pipe_dt_k_per_km", h.pipe_dt_k_per_km, 50)} K/km<br>
       补热 <select data-p="heat.booster">${opt([["gas_boiler", "燃气调峰锅炉"], ["electric", "电加热"], ["none", "无"]], h.booster)}</select> 售热价 ${inp("heat.price_cny_gj", h.price_cny_gj, 50)} 对标热价 ${inp("heat.ref_heat_price_cny_gj", h.ref_heat_price_cny_gj, 50)} 元/GJ
       热泵最高出水 ${inp("heat.hp_max_out_c", h.hp_max_out_c, 50)}°C η ${inp("heat.eta", h.eta, 45)} 设计热负荷 ${inp("heat.design_load_mw", h.design_load_mw, 55)} MW</fieldset></div>`;
  }
  function read() {
    $$("#cfgForm [data-p]").forEach(el => { const ks = el.dataset.p.split("."); let o = SPEC;
      ks.slice(0, -1).forEach(k => o = Array.isArray(o) ? o[+k] : o[k]); const k = ks.at(-1);
      o[k] = el.type === "checkbox" ? el.checked : el.type === "number" ? num(el.value) : el.value; });
    return SPEC;
  }
  function render() { $("#cfgForm").innerHTML = form();
    $("#cfgAddDc").onclick = () => { read(); const d = JSON.parse(JSON.stringify(SPEC.dcs.at(-1))); d.name = "DC" + (SPEC.dcs.length + 1); SPEC.dcs.push(d); render(); };
    $$("#cfgForm [data-del]").forEach(b => b.onclick = () => { read(); if (SPEC.dcs.length > 1) SPEC.dcs.splice(+b.dataset.del, 1); render(); }); }
  async function validate() { read(); const r = await api("/api/config/validate", {method: "POST", body: JSON.stringify({spec: SPEC})});
    $("#cfgMsg").innerHTML = (r.ok ? `<span class="ok">✅ 校验通过</span>` : `<span class="err">❌ ${r.errors.map(esc).join("；")}</span>`) + (r.warnings.length ? `<div class="warn">⚠ ${r.warnings.map(esc).join("<br>⚠ ")}</div>` : ""); return r.ok; }
  async function build() { if (!await validate()) return;
    const r = await api(`/api/sessions/${sid()}/config/build`, {method: "POST", body: JSON.stringify({spec: SPEC})});
    $("#cfgMsg").innerHTML += `<div class="ok">已构建为当前会话场景「${esc(r.scenario)}」：${r.dcs.map(d => `${esc(d.name)} ${d.cap_it_mw}MW ${esc(d.cooling)}`).join("；")}。到「🧭 仿真工作台 ②」确认参数并求解，或在「🗺 模型拓扑」查看。</div>`; }
  const COLS = [["pue", "PUE"], ["wue_l_kwh", "WUE"], ["water_m3", "耗水m³"], ["cooling_mwh", "冷却电MWh"], ["energy_cost_cny", "电费元"], ["emissions_t", "净碳t"],
    ["heat_delivered_mwh", "供热MWh"], ["t_src_c", "源温°C"], ["hp_cop", "COP"], ["terminal_margin_k", "末端裕度K"], ["boost_mwh", "补热MWh"], ["heat_cost_cny_gj", "热成本元/GJ"], ["heat_net_carbon_t", "供热净减碳t"], ["heat_verdict", "余热供暖"], ["thermal_safe", "热安全"]];
  function showRes(res) {
    const rows = res.rows, ok = rows.filter(r => r.ok), box = $("#cfgRes"); box.innerHTML = `<h3>${esc(res.title || "结果")}（${rows.length} 个配置）</h3>`;
    const vcls = v => v === "可行" ? "v-ok" : v === "有条件可行" ? "v-cond" : v === "不可行" ? "v-bad" : "";
    box.insertAdjacentHTML("beforeend", `<div class="tblwrap"><table class="tbl cfg-res"><tr><th>配置</th>${COLS.map(c => `<th>${c[1]}</th>`).join("")}</tr>` +
      rows.map(r => `<tr><td>${esc(r.label)}</td>` + (r.ok ? COLS.map(([k]) => `<td class="${k === "heat_verdict" ? vcls(r[k]) : (k === "terminal_margin_k" && r[k] < 0 ? "neg" : "")}">${esc(typeof r[k] === "number" ? (+r[k]).toLocaleString(undefined, {maximumFractionDigits: 3}) : r[k] ?? "—")}</td>`).join("") : `<td colspan="${COLS.length}" class="err">${esc(r.error)}</td>`) + "</tr>").join("") + "</table></div>");
    if (!ok.length) return;
    const ks = [["pue", "PUE"], ["wue_l_kwh", "WUE L/kWh"], ["energy_cost_cny", "电费 元/日"], ["emissions_t", "净碳 tCO2/日"], ["heat_cost_cny_gj", "热成本 元/GJ"], ["terminal_margin_k", "末端裕度 K"]];
    const wrap = document.createElement("div"); wrap.className = "cfg-charts"; box.append(wrap);
    ks.forEach(([k, n]) => chartEl({_height: 230, title: {text: n, textStyle: {fontSize: 12}}, grid: {left: 50, right: 10, bottom: 70, top: 30}, tooltip: {},
      xAxis: {type: "category", data: ok.map(r => r.label), axisLabel: {rotate: 30, fontSize: 9}}, yAxis: {type: "value", scale: k === "pue"},
      series: [{type: "bar", data: ok.map(r => ({value: r[k] ?? 0, itemStyle: {color: k === "terminal_margin_k" && r[k] < 0 ? "#e03131" : "#3b82f6"}})), label: {show: true, position: "top", fontSize: 9}}]}, wrap));
    const hv = ok.filter(r => r.heat_verdict && r.heat_verdict !== "—");
    if (hv.length) box.insertAdjacentHTML("beforeend", `<h3>余热供暖可行性判定</h3><div class="cfg-verdicts">` + hv.map(r => `<div class="cfg-v ${vcls(r.heat_verdict)}"><b>${esc(r.heat_verdict)}</b> · ${esc(r.label)}<br>
      <span class="muted">源 ${r.t_src_c}°C · COP ${esc(r.hp_cop)} · 末端裕度 ${r.terminal_margin_k} K · 补热 ${r.boost_mwh} MWh · ${r.heat_cost_cny_gj} 元/GJ · 净减碳 ${r.heat_net_carbon_t} t</span></div>`).join("") + "</div>");
  }
  async function run(body, url = "sweep") { read(); $("#cfgRes").innerHTML = `<p class="muted">⏳ 正在逐点构建并求解耦合 LP …</p>`;
    try { const r = await api(`/api/sessions/${sid()}/config/${url}`, {method: "POST", body: JSON.stringify({base: SPEC, ...body})}); showRes({title: body.title || (url === "heat_study" ? "余热供暖可行性（散热方式×末端×距离）" : "对比/扫描"), rows: r.rows}); }
    catch (e) { $("#cfgRes").innerHTML = `<p class="err">${esc(e.message)}</p>`; } }
  window.loadConfig = async function () {
    if (!MODES.length) { const m = await api("/api/cooling/modes"); MODES = m.modes; TERMS = m.terminals; }
    if (!SPEC) { const c = await api(`/api/sessions/${sid()}/config`); SPEC = c.spec; if (c.last_sweep) showRes(c.last_sweep); }
    $("#cfgLib").innerHTML = libHtml(); render();
  };
  document.addEventListener("DOMContentLoaded", () => {
    $("#cfgValidate").onclick = validate; $("#cfgBuild").onclick = build;
    $("#cfgReset").onclick = async () => { SPEC = (await api("/api/config/template")).template; render(); };
    $("#cfgCmpCool").onclick = () => run({title: "散热方式对比", params: [{path: "dcs.*.cooling_mode", values: ["air_chw", "air_iec", "air_dec", "liquid_cold_plate", "liquid_immersion", "hybrid"]}]});
    $("#cfgSweepEss").onclick = () => run({title: "电池储能容量扫描", params: [{path: "battery.energy_mwh", values: [0, 50, 100, 200, 400]}, {path: "battery.power_mw", values: [25, 100]}]});
    $("#cfgSweepTes").onclick = () => run({title: "蓄冷罐容量扫描（夏季）", base: {...read(), season: "summer"}, params: [{path: "dcs.*.tes_mwh", values: [0, 20, 40, 80]}, {path: "dcs.*.tes_mw", values: [10]}]});
    $("#cfgHeat").onclick = () => run({modes: ["air_chw", "liquid_cold_plate", "liquid_immersion"], terminals: ["floor", "radiator", "primary"], lengths_km: [1, 5, 10]}, "heat_study");
    $("#cfgCustom").onclick = () => { const p = [], a = $("#cfgP1").value.trim(), b = $("#cfgP2").value.trim();
      const vals = s => s.split(/[,，]/).map(x => x.trim()).filter(Boolean).map(x => isNaN(+x) ? x : +x);
      if (a) p.push({path: a, values: vals($("#cfgV1").value)}); if (b) p.push({path: b, values: vals($("#cfgV2").value)});
      if (p.length) run({title: "自定义扫描", params: p}); };
  });
})();
