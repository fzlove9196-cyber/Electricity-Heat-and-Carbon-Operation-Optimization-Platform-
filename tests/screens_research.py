"""研究模式端到端截图（mock 模式，需服务已启动）：python tests/screens_research.py → screens/research_*.png"""
import os, json
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
errs = []
def full(pg, name):
    pg.evaluate("""() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol']) { const e = document.querySelector(s); e.style.height = 'auto'; e.style.overflow = 'visible'; }
      document.querySelector('#chatCol').style.maxHeight = '1400px'; }"""); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/{name}.png", full_page=True)
    pg.evaluate("() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol', '#chatCol']) { const e = document.querySelector(s); e.style.height = ''; e.style.overflow = ''; e.style.maxHeight = ''; } }")
def el(pg, sel, name, i=0):
    pg.evaluate("""() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol', '#chatLog', '#chatCol']) { const e = document.querySelector(s); e.style.height = 'auto'; e.style.maxHeight = 'none'; e.style.overflow = 'visible'; } }"""); pg.wait_for_timeout(400)
    loc = pg.locator(sel); loc = loc.last if i == -1 else loc.nth(i); loc.screenshot(path=f"{OUT}/{name}.png")
    pg.evaluate("() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol', '#chatLog', '#chatCol']) { const e = document.querySelector(s); e.style.height = ''; e.style.overflow = ''; e.style.maxHeight = ''; } }")
def ask(pg, text, wait, timeout=240000):
    pg.fill("#input", text); pg.click("#sendBtn"); pg.wait_for_selector(wait, timeout=timeout); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=timeout); pg.wait_for_timeout(800)
def last(pg, sel): pg.locator(sel).last.click()
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1700, "height": 1050}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text))
    # ---------- 研究 (b)：热浪 + DR ----------
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/"); pg.wait_for_timeout(1000)
    pg.check("#researchMode")
    ask(pg, "中卫夏季热浪下保障热安全同时参与需求响应的最优方案", ".rs-card.clar")
    full(pg, "research_b1_problem_clarify"); el(pg, "#chatLog", "research_b1z_chat_problem_clarify")
    last(pg, ".rs-card.clar [data-act=ans]"); pg.wait_for_selector(".rs-card.plan", timeout=60000); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled"); pg.wait_for_timeout(800)
    pg.click("#stepper .st[data-step=research]"); pg.wait_for_timeout(800); full(pg, "research_b2_plan_editor")
    last(pg, ".rs-card.plan [data-act=approve]"); pg.wait_for_selector("#chatLog .rs-card.ckpt", timeout=240000); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=240000); pg.wait_for_timeout(800)
    pg.click("#stepper .st[data-step=research]"); pg.wait_for_timeout(800); pg.locator("#stepBody .rchip", has_text="R2").first.click(); pg.wait_for_timeout(1200)
    full(pg, "research_b3_infeasible_checkpoint"); el(pg, "#rsRun", "research_b3z_run_diagnosis"); el(pg, "#stepBody .rs-sec", "research_b3y_checkpoint_panel", 0)
    pg.locator("#chatLog .rs-card.ckpt button").first.click(); pg.wait_for_selector("#chatLog .rs-card.conc", timeout=300000); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=300000); pg.wait_for_timeout(1000)
    pg.click("#stepper .st[data-step=research]"); pg.wait_for_timeout(800); pg.locator("#stepBody .rchip", has_text="R3").first.click(); pg.wait_for_timeout(1500)
    full(pg, "research_b4_conclusions_timeline"); el(pg, "#stepBody .rs-card.conc", "research_b4z_conclusions"); el(pg, "#stepBody .rs-cols", "research_b4y_timeline_runs"); el(pg, "#stepBody .rs-sec", "research_b4x_plan_after_revise", 0)
    ask(pg, "如果热浪再高2度会怎样", "#chatLog .rs-card.wi"); full(pg, "research_b5_whatif"); el(pg, "#chatLog .msg", "research_b5z_whatif_msg", -1)
    ask(pg, "为什么 C2 成立？", "#chatLog .msg >> text=解释 C2"); pg.locator("#chatLog").screenshot(path=f"{OUT}/research_b6_why_chat.png")
    pg.click("#stepper .st[data-step=params]"); pg.wait_for_selector(".msgref", timeout=30000); pg.wait_for_timeout(800)
    pg.locator(".msgref").first.scroll_into_view_if_needed(); pg.locator("#stepCol").screenshot(path=f"{OUT}/research_b7_param_msgref.png")
    last(pg, "#chatLog .rs-card.sed [data-act=sed]"); pg.wait_for_selector("#chatLog .msg >> text=已沉淀", timeout=120000); pg.wait_for_timeout(800)
    # ---------- 研究 (a)：冬季余热供暖 ----------
    pg.click("#newSess"); pg.wait_for_timeout(800); pg.check("#researchMode")
    ask(pg, "中卫冬季想用余热供暖，看值不值", ".rs-card.clar")
    last(pg, ".rs-card.clar [data-act=ans]"); pg.wait_for_selector(".rs-card.plan", timeout=60000); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled"); pg.wait_for_timeout(500)
    last(pg, ".rs-card.plan [data-act=approve]"); pg.wait_for_selector("#chatLog .rs-card.conc", timeout=300000); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=300000); pg.wait_for_timeout(1000)
    pg.click("#stepper .st[data-step=research]"); pg.wait_for_timeout(800); full(pg, "research_a1_heat_conclusions"); el(pg, "#stepBody .rs-card.conc", "research_a1z_heat_conclusions")
    ask(pg, "如果热价降到80会怎样", "#chatLog .rs-card.wi"); full(pg, "research_a2_heat_whatif")
    last(pg, "#chatLog .rs-card.sed [data-act=sed]"); pg.wait_for_selector("#chatLog .msg >> text=已沉淀", timeout=120000); pg.wait_for_timeout(800)
    sid = pg.evaluate("localStorage.getItem('sid')")
    pg2 = br.new_page(viewport={"width": 1100, "height": 1000}); pg2.goto(f"{B}/artifacts/{sid}/study_report.html"); pg2.wait_for_timeout(1500); pg2.screenshot(path=f"{OUT}/research_a3_report_html.png", full_page=True)
    # ---------- 复用经验：再问一个类似问题 ----------
    pg.click("#newSess"); pg.wait_for_timeout(800); pg.check("#researchMode")
    ask(pg, "中卫夏季热浪时数据中心参与晚高峰需求响应，怎么保障热安全？", ".rs-card.clar")
    pg.locator("#chatLog .rs-card.prob").last.screenshot(path=f"{OUT}/research_c1_reuse_experience.png")
    br.close()
print(json.dumps({"errors": errs[:10]}, ensure_ascii=False))
