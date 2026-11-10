/* 产品内在线帮助入口：顶栏「❓ 帮助」、F1 / Shift+? 上下文帮助、各模块标题旁 ?、快捷提示中的「打开完整使用帮助」。
   帮助在右侧抽屉 iframe（/help/<slug>?embed=1）中打开，不刷新产品、不丢会话；Esc 或 ✕ 关闭。
   只读：不写知识库、不调用 LLM、不改会话。 */
(function () {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const STEPS = ["goal", "params", "model", "solver", "run", "results", "research"];
  let M = null, drawer, frame, newWin, lastFocus = null, curSlug = null;
  const loadManifest = async () => (M = M || await fetch("/api/help/manifest").then(r => r.json()));

  function current() {
    const v = $(".view.active")?.id?.slice(2) || "chat";
    const st = v === "chat" ? $("#stepper .st.view")?.dataset.step : null;
    return {v, step: st || null};
  }
  async function contextSlug(v, step) {
    const m = await loadManifest(), c = m.context || {};
    if (!v) ({v, step} = current());
    return (step && c[v + ":" + step]) || c[v] || c.default || m.home || "welcome";
  }
  function build() {
    drawer = document.createElement("div");
    drawer.id = "helpDrawer"; drawer.className = "help-drawer hidden";
    drawer.setAttribute("role", "dialog"); drawer.setAttribute("aria-label", "使用帮助");
    drawer.innerHTML = `<div class="hd-mask" data-close></div><div class="hd-panel"><div class="hd-bar"><b>📘 使用帮助</b><span class="muted">F1 当前功能帮助 · Esc 关闭</span><a id="helpNewWin" class="sm ghost" target="_blank" rel="noopener" href="/help">↗ 新窗口打开</a><button type="button" class="sm ghost" data-close aria-label="关闭帮助">✕ 返回产品</button></div><iframe id="helpFrame" title="使用帮助"></iframe></div>`;
    document.body.appendChild(drawer);
    frame = $("#helpFrame"); newWin = $("#helpNewWin");
    drawer.querySelectorAll("[data-close]").forEach(b => b.onclick = close);
  }
  async function open(slug) {
    if (!drawer) build();
    if (!slug) slug = await contextSlug();
    lastFocus = document.activeElement;
    if (slug !== curSlug || !frame.getAttribute("src")) { frame.src = "/help/" + encodeURIComponent(slug) + "?embed=1"; curSlug = slug; }
    newWin.href = "/help/" + slug;
    drawer.classList.remove("hidden");
    setTimeout(() => frame.focus(), 50);
  }
  function close() {
    if (!drawer || drawer.classList.contains("hidden")) return false;
    drawer.classList.add("hidden");
    try { lastFocus?.focus?.(); } catch (e) {}
    return true;
  }
  const isOpen = () => drawer && !drawer.classList.contains("hidden");
  function openView(href) {
    const q = new URLSearchParams(href.split("?")[1] || ""), v = q.get("view"), st = q.get("step");
    if (!v || !document.getElementById("v-" + v)) return;
    close();
    const tgt = v === "chat" && STEPS.includes(st) ? "chat:" + st : v;
    if (window.IA?.go) window.IA.go(tgt); else window.show?.(v);
  }
  window.addEventListener("message", e => {
    if (e.origin !== location.origin || !e.data || e.data.source !== "sdco-help") return;
    if (e.data.type === "close") close();
    else if (e.data.type === "open-view") openView(String(e.data.href || ""));
    else if (e.data.type === "page") { curSlug = e.data.slug; if (newWin) newWin.href = "/help/" + e.data.slug; }
  });
  document.addEventListener("keydown", e => {
    const t = e.target, typing = t && (/INPUT|TEXTAREA|SELECT/.test(t.tagName) || t.isContentEditable);
    if (e.key === "F1") { e.preventDefault(); isOpen() ? close() : open(); return; }
    if (e.key === "?" && e.shiftKey && !typing && !e.ctrlKey && !e.metaKey) { e.preventDefault(); open(); return; }
    if (e.key === "Escape" && close()) e.stopPropagation();
  }, true);

  // 各模块标题旁的上下文 ?
  function injectCtx() {
    $$("section.view").forEach(sec => {
      const h = sec.querySelector("h2"); if (!h || h.querySelector(".ctx-help")) return;
      const v = sec.id.slice(2), b = document.createElement("button");
      b.type = "button"; b.className = "ctx-help"; b.textContent = "?"; b.title = "查看本功能的使用帮助（F1）"; b.setAttribute("aria-label", "本功能使用帮助");
      b.onclick = async ev => { ev.stopPropagation(); open(await contextSlug(v, v === "chat" ? current().step : null)); };
      h.appendChild(b);
    });
  }
  function boot() {
    const top = $("#helpTopBtn"); if (top) top.onclick = () => open();
    const full = $("#helpOpenFull");
    if (full) full.onclick = () => { $("#helpPop")?.classList.add("hidden"); open(); };
    injectCtx();
    let tm; const main = $("main");
    if (main) new MutationObserver(() => { clearTimeout(tm); tm = setTimeout(injectCtx, 200); }).observe(main, {childList: true, subtree: true});
    const hq = new URLSearchParams(location.search).get("help");
    if (hq !== null) open(/^[a-z0-9][a-z0-9-]{0,63}$/.test(hq) ? hq : undefined);
  }
  window.HELP = {open, close, contextSlug};
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
