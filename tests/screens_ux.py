"""透明化工作流 UI 截图（需服务已启动）：对话驱动（暂停确认）+ 六个步骤。用法：python tests/screens_ux.py"""
import os, json
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
errs, report = [], {}
def clip(pg, tag):
    r = pg.evaluate("""() => { const bad = [];
      for (const el of document.querySelectorAll('#stepper, #stepBody table, #stepBody .kpi, #stepBody .wf-kv > div, .wf-confirm, #chatForm, .lg')) {
        if (el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflowX !== 'auto') bad.push((el.id || el.className) + ' scrollW ' + el.scrollWidth + '>' + el.clientWidth);
        const b = el.getBoundingClientRect(); if (b.right > window.innerWidth + 1) bad.push((el.id || el.className) + ' right ' + Math.round(b.right)); }
      if (document.querySelector('.katex-error')) bad.push('katex-error');
      return bad.slice(0, 8); }""")
    report[tag] = r or "ok"
def shot(pg, name, full=True):
    if full:
        pg.evaluate("""() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol']) { const e = document.querySelector(s); e.style.height = 'auto'; e.style.overflow = 'visible'; }
          document.querySelector('#chatCol').style.maxHeight = '1100px'; }"""); pg.wait_for_timeout(600)
    pg.screenshot(path=f"{OUT}/{name}.png", full_page=full)
    if full: pg.evaluate("() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol', '#chatCol']) { const e = document.querySelector(s); e.style.height = ''; e.style.overflow = ''; e.style.maxHeight = ''; } }")
def step(pg, s): pg.click(f"#stepper .st[data-step={s}]"); pg.wait_for_timeout(900)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1600, "height": 1000}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text))
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/"); pg.wait_for_selector("#gStart"); pg.wait_for_timeout(800)
    clip(pg, "01_goal"); shot(pg, "ux_01_goal_onboarding", full=False)
    # 对话驱动：中卫夏季大风 -> 智能体建模后暂停
    pg.fill("#input", "中卫夏季大风日，优化调度并分析"); pg.click("#sendBtn")
    pg.wait_for_selector("[data-goparams]", timeout=120000); pg.wait_for_selector(".ptbl", timeout=60000); pg.wait_for_timeout(1200)
    clip(pg, "02_params"); shot(pg, "ux_02_params_paused")
    pg.locator("#stepCol").screenshot(path=f"{OUT}/ux_02b_params_panel_view.png")
    # 修改一个参数（储能容量）
    pg.fill("[data-path='storage.0.energy_mwh']", "300"); pg.dispatch_event("[data-path='storage.0.energy_mwh']", "change"); pg.wait_for_timeout(1500)
    pg.click("#pConfirm"); pg.wait_for_selector("#wfMv .mv-chart canvas", timeout=60000); pg.wait_for_timeout(1500)
    clip(pg, "03_model"); shot(pg, "ux_03_model_check")
    step(pg, "solver"); pg.wait_for_selector(".ftbl", timeout=30000); pg.wait_for_timeout(800)
    clip(pg, "04_solver"); shot(pg, "ux_04_solver_formulation")
    pg.click("#sRun"); pg.wait_for_selector(".kpis", timeout=300000); pg.wait_for_timeout(2500)
    clip(pg, "06_results"); shot(pg, "ux_06_results_explain")
    step(pg, "run"); pg.wait_for_selector(".lgs .lg"); pg.wait_for_timeout(600)
    clip(pg, "05_run"); shot(pg, "ux_05_run_log")
    step(pg, "solver"); pg.wait_for_timeout(800); shot(pg, "ux_04b_solver_with_size", full=False)
    # 错误提示：非法参数
    step(pg, "params"); pg.fill("[data-path='storage.0.soc0']", "5"); pg.dispatch_event("[data-path='storage.0.soc0']", "change"); pg.wait_for_timeout(1200)
    pg.screenshot(path=f"{OUT}/ux_07_error_toast.png")
    br.close()
print(json.dumps({"errors": errs, "clip": report}, ensure_ascii=False, indent=1))
