"""Phase 1 UI 截图（headless Chrome，需服务已启动）。用法：python tests/screens_phase1.py"""
import json, os, urllib.request
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens")
ss = json.load(urllib.request.urlopen(B + "/api/sessions"))
sid = lambda kw: next(s["id"] for s in ss if kw in s["title"])
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    # 1) Pareto 交互图（ECharts）
    pg.goto(f"{B}/?s={sid('Pareto')}"); pg.wait_for_selector(".echart canvas", timeout=30000); pg.wait_for_timeout(1500)
    el = pg.locator(".echart").nth(1); el.scroll_into_view_if_needed(); pg.wait_for_timeout(800)
    el.hover(position={"x": 300, "y": 200}); pg.wait_for_timeout(300)
    pg.screenshot(path=f"{OUT}/phase1_pareto_chat.png")
    pg.locator(".echart").nth(1).locator("xpath=..").screenshot(path=f"{OUT}/phase1_pareto_detail.png")
    # 2) 任务 + 迁移 KPI / 任务窗口图
    pg.goto(f"{B}/?s={sid('30个任务')}"); pg.wait_for_selector("img[src*='jobs_windows']", timeout=30000); pg.wait_for_timeout(1500)
    pg.locator("td:text-is('jobs_deadline_met_pct')").last.scroll_into_view_if_needed(); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/phase1_jobs_kpis.png")
    pg.locator("img[src*='jobs_windows']").last.scroll_into_view_if_needed(); pg.wait_for_timeout(800)
    pg.screenshot(path=f"{OUT}/phase1_jobs_windows.png")
    # 3) 场景参数：碳感知 + 链路 + 任务表
    pg2 = br.new_page(viewport={"width": 1440, "height": 2300})
    pg2.goto(f"{B}/?view=scenario"); pg2.evaluate("localStorage.removeItem('scenario')"); pg2.goto(f"{B}/?view=scenario")
    pg2.wait_for_selector("#genJobs"); pg2.fill("#nJobs", "12"); pg2.click("#genJobs"); pg2.wait_for_timeout(1500)
    pg2.wait_for_selector("#carbonChart canvas", timeout=15000); pg2.wait_for_timeout(800)
    pg2.screenshot(path=f"{OUT}/phase1_scenario_form.png")
    # 4) 知识库：中文混合检索
    pg2.set_viewport_size({"width": 1440, "height": 1100})
    pg2.goto(f"{B}/?view=kb"); pg2.fill("#kbQuery", "Alibaba GPU trace 数据集"); pg2.click("#kbSearchBtn")
    pg2.wait_for_selector("#kbResult .card", timeout=60000); pg2.wait_for_timeout(500)
    pg2.screenshot(path=f"{OUT}/phase1_kb_search.png")
    br.close()
print("ok")
