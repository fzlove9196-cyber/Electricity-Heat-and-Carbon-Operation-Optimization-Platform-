/* 信息架构（IA）：顶部一级业务域 + 左侧/页内二级任务 + 当前位置面包屑 + 功能搜索 + 下一步引导。
   只重组入口，不改各模块逻辑；旧 data-view / 视图 ID / show() 全部保留。 */
(function () {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const STEP_NAME = {goal: "① 场景与目标", params: "② 输入参数", model: "③ 模型构建", solver: "④ 求解配置", run: "⑤ 运行与校核", results: "⑥ 结果与分析", research: "🔬 研究模式"};
  // 一级业务域 → 二级任务（target: 视图名 或 "chat:步骤"）；adv=高级/配置，默认收起
  const DOMAINS = [
    {id: "build", icon: "🏗", name: "资源与建模", desc: "定义数据中心、电源、储能、散热与拓扑", items: [
      ["foundation", "项目与场景", "创建项目/多场景/版本/数据绑定"], ["templates", "基础模板库", "参考拓扑独立复制"], ["resources", "数据与设备模型库", "单位/来源/工况/版本维护"], ["config", "配置构建器", "数据中心/储能/电源/散热/余热 · 对比与扫描"], ["model", "模型拓扑 / 能流", "可视化与编辑会话模型"], ["scenario", "场景表单 (JSON)", "完整场景参数", 1]],
      next: ["chat:params", "构建为会话场景后 → ② 仿真优化：核对参数并求解"]},
    {id: "sim", icon: "🧭", name: "仿真优化", desc: "对话驱动：描述 → 参数透明 → 建模 → 求解", items: [
      ["tasks", "版本化仿真任务", "冻结输入、原引擎求解与历史追溯"], ["chat", "仿真工作台（对话）", "六步透明工作流"], ["chat:params", "参数透明核对", "单位与来源"], ["chat:model", "模型构建核对", "母线/线路/电源/储能/DC"],
      ["chat:solver", "透明模型 / 数学表述", "求解器与数学模型"], ["chat:research", "研究模式", "问题卡→计划→证据结论"]],
      next: ["tier", "得到日前最优后 → ③ 三级运行：日内滚动与实时跟踪"]},
    {id: "tier", icon: "⏱", name: "三级运行", desc: "日前基线 → 日内滚动 → 实时跟踪 · 安全兜底", items: [["tier", "三级优化运行", "日前/日内/实时/可行域/UPS/应急"]],
      next: ["market", "运行计划确定后 → ④ 电力交易运营：申报、出清与结算"]},
    {id: "ops", icon: "💹", name: "电力交易运营", desc: "P0 沙盘：台账 · 申报审批 · 日内/实时 · DR · 结算 · 审计", items: [["market", "运营工作台 (P0)", "非真实交易，沙盘闭环"]],
      next: ["chat:results", "闭环完成后 → ⑤ 结果复盘：KPI、基线对比与归因"]},
    {id: "review", icon: "📊", name: "结果复盘", desc: "KPI、基线对比、收益归因、运行日志、历史会话", items: [
      ["chat:results", "结果与分析", "KPI/基线/归因/局限"], ["chat:run", "运行日志与校核", "每步动作与交流校核"]],
      next: ["kb", "沉淀经验 → ⑥ 知识库 / 技能卡"]},
    {id: "kit", icon: "🧰", name: "知识 · 工具 · 设置", desc: "知识库检索、技能卡复用、仿真器与模型配置", items: [
      ["kb", "知识库", "上传文档，对话自动检索"], ["cards", "技能卡", "可复用任务"], ["sims", "仿真器 / 工具", "状态与已注册工具", 1], ["settings", "LLM 设置", "模型与 API Key", 1], ["help", "使用帮助", "在线手册：快速上手 · 参数配置 · 常见问题（F1）"]]},
  ];
  const label = t => { for (const d of DOMAINS) for (const it of d.items) if (it[0] === t) return it[1]; return t; };
  const domainOf = (v, step) => {
    if (v === "chat") return ["results", "run"].includes(step) ? "review" : "sim";
    return DOMAINS.find(d => d.items.some(i => i[0] === v))?.id || "sim";
  };
  let cur = {view: "chat", step: null};
  function curStep() { return $("#stepper .st.view")?.dataset.step || null; }
  function go(target) {
    const [v, step] = target.split(":");
    if (v === "help") { window.HELP?.open?.(step || undefined); return; }   // 帮助在抽屉中打开，不切换视图
    window.show(v);
    if (step && window.WF?.go) window.WF.go(step, true);
    update(v);
  }
  function update(v) {
    if (v) cur.view = v;
    cur.step = cur.view === "chat" ? curStep() : null;
    const did = domainOf(cur.view, cur.step), D = DOMAINS.find(d => d.id === did);
    const tgt = cur.step && cur.view === "chat" ? "chat:" + cur.step : cur.view;
    $("#domBar").innerHTML = DOMAINS.map((d, i) => `<button type="button" class="dom ${d.id === did ? "on" : ""}" data-dom="${d.id}" title="${d.desc}"><span class="dn">${i + 1}</span>${d.icon} ${d.name}</button>`).join('<span class="dom-arr">›</span>');
    $$("#domBar [data-dom]").forEach(b => b.onclick = () => go(DOMAINS.find(d => d.id === b.dataset.dom).items[0][0]));
    $("#crumb").innerHTML = `<span class="muted">当前位置</span> <b>${D.icon} ${D.name}</b> › ${label(cur.view === "chat" && did === "sim" ? "chat" : tgt)}${cur.view === "chat" && cur.step && did === "sim" ? ` › <span class="muted">${STEP_NAME[cur.step] || ""}</span>` : ""}
      ${D.next ? `<button type="button" class="sm ghost crumb-next" data-go-ia="${D.next[0]}">下一步：${D.next[1]}</button>` : ""}`;
    const basic = D.items.filter(i => !i[3]), adv = D.items.filter(i => i[3]);
    const pill = i => `<button type="button" class="sub ${i[0] === tgt || (i[0] === "chat" && tgt.startsWith("chat") && !D.items.some(x => x[0] === tgt)) ? "on" : ""}" data-go-ia="${i[0]}" title="${i[2]}">${i[1]}</button>`;
    $("#subBar").innerHTML = D.items.length > 1 ? basic.map(pill).join("") + (adv.length ? `<details class="sub-adv"><summary>高级与配置</summary>${adv.map(pill).join("")}</details>` : "") : "";
    $$("#topbar [data-go-ia]").forEach(b => b.onclick = () => go(b.dataset.goIa));
    // 左侧：当前域高亮；高级入口在被访问时自动展开；跳转链接高亮
    $$("#iaNav .nav-d").forEach(n => n.classList.toggle("cur", n.dataset.domain === did));
    $$("#iaNav a[data-jump]").forEach(a => a.classList.toggle("active", a.dataset.jump === tgt));
    if (tgt.startsWith("chat:") && D.items.some(x => x[0] === tgt)) $$('#iaNav a[data-view="chat"]').forEach(a => a.classList.remove("active"));
    $$("#iaNav details.nav-adv").forEach(dt => { if (dt.querySelector(`a[data-view="${cur.view}"]`)) dt.open = true; });
  }
  // 搜索菜单
  const INDEX = DOMAINS.flatMap(d => d.items.map(i => ({t: i[0], name: i[1], desc: i[2], dom: d.name, icon: d.icon}))).concat(
    [["chat:goal", "场景与目标 / 案例预设", "选案例"], ["market", "申报台账与审批", "草稿→审核→出清→结算"], ["market", "审计记录", "操作审计"], ["market", "需求响应 DR / 结算", "P0"],
     ["config", "散热方式库 / 对比扫描", "储能/蓄冷/余热"], ["tier", "UPS / 柴发 / 应急", "实时层兜底"], ["tier", "可行域", "实时可行域"],
     ["help", "帮助 / 使用手册", "在线帮助 · 快速上手 · 示例提示词"], ["help:params-overview", "参数配置手册", "参数含义、单位、默认值、范围"], ["help:faq-errors", "常见问题与报错（帮助）", "报错原因与处理"], ["help:limitations", "已知限制与诚实声明（帮助）", "能力边界"]].map(x => ({t: x[0], name: x[1], desc: x[2], dom: DOMAINS.find(d => d.id === domainOf(...x[0].split(":"))).name, icon: "↳"})));
  function search(q) {
    const box = $("#navSearchRes"); q = q.trim().toLowerCase();
    if (!q) { box.classList.add("hidden"); return; }
    const r = INDEX.filter(x => (x.name + x.desc + x.dom + x.t).toLowerCase().includes(q)).slice(0, 8);
    box.innerHTML = r.length ? r.map((x, i) => `<div class="ns-i ${i ? "" : "on"}" data-t="${x.t}"><b>${x.icon} ${x.name}</b><span class="muted"> · ${x.dom} — ${x.desc}</span></div>`).join("") : `<div class="muted ns-i">无匹配功能</div>`;
    box.classList.remove("hidden");
    $$("#navSearchRes [data-t]").forEach(e => e.onmousedown = () => { go(e.dataset.t); $("#navSearch").value = ""; box.classList.add("hidden"); });
  }
  function boot() {
    $$("#iaNav a[data-jump]").forEach(a => a.onclick = () => go(a.dataset.jump));
    const s = $("#navSearch");
    s.oninput = () => search(s.value);
    s.onkeydown = e => { if (e.key === "Enter") { const f = $("#navSearchRes [data-t]"); if (f) { go(f.dataset.t); s.value = ""; search(""); } } if (e.key === "Escape") { s.value = ""; search(""); } };
    s.onblur = () => setTimeout(() => search(""), 150);
    document.addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); s.focus(); } });
    const st = $("#stepper"); if (st) new MutationObserver(() => { if (cur.view === "chat") update(); }).observe(st, {childList: true});
    update($(".view.active")?.id?.slice(2) || "chat");
  }
  window.IA = {update, go, DOMAINS};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
