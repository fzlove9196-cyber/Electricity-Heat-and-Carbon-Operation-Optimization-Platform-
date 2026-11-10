"""寻优端到端截图（mock，需服务在 8080）：python tests/screens_opt.py → screens/opt_*.png"""
import os
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
errs = []
def ask(pg, text, wait, timeout=900000):
    pg.fill("#input", text); pg.click("#sendBtn"); pg.wait_for_selector(wait, timeout=timeout)
    pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=timeout); pg.wait_for_timeout(1200)
def shot(pg, sel, name, i=-1):
    loc = pg.locator(sel); loc = loc.last if i == -1 else loc.nth(i); loc.scroll_into_view_if_needed(); loc.screenshot(path=f"{OUT}/{name}.png")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1700, "height": 1100}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text))
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/"); pg.wait_for_timeout(1000)
    ask(pg, "乌兰察布项目寻优：我想看经济性最优和碳排放最优的方案，以及中间的折中，48个代表日，7个点", ".op-res .op-chart[data-ready]")
    shot(pg, ".op-spec", "opt_1_objective_card")
    pg.locator(".op-spec details").first.evaluate("e => e.open = true"); shot(pg, ".op-spec", "opt_1b_formulation")
    shot(pg, ".op-res", "opt_2_pareto_table")
    pg.locator(".op-res .op-tbl th[data-pl]").nth(1).click(); pg.wait_for_timeout(500); shot(pg, ".op-res .op-sel", "opt_3_click_scheme")
    shot(pg, "#chatLog .msg", "opt_4_summary_msg")
    ask(pg, "再降10%碳要多花多少钱", "#chatLog .op-res >> text=边际减排追问"); shot(pg, "#chatLog .op-res", "opt_5_abatement")
    ask(pg, "韶关：成本最低，绿电不低于90%，回收期不超过8年，全年8760", "#chatLog .op-res >> nth=2"); shot(pg, ".op-spec", "opt_6_shaoguan_spec"); shot(pg, ".op-res", "opt_6b_shaoguan_result")
    # 编辑目标卡：加约束后重算
    pg.locator(".op-spec").last.locator("[data-f=mode]").select_option("single"); pg.locator(".op-spec").last.locator("[data-cv]").first.fill("0.95")
    pg.locator(".op-spec").last.locator("[data-rerun]").click(); pg.wait_for_function("() => document.querySelectorAll('.op-res').length >= 4", timeout=900000)
    pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=900000); pg.wait_for_timeout(800); shot(pg, ".op-res", "opt_7_edited_rerun")
    pg.screenshot(path=f"{OUT}/opt_0_full_page.png", full_page=False)
    br.close()
print("errors:", errs)
