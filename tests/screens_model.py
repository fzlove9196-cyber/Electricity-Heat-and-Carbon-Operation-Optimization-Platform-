"""模型拓扑 UI 截图（headless Chrome，需服务已启动，Mock LLM）。用法：python tests/screens_model.py"""
import os
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
errs = []
def full(pg, path):   # 展开内部滚动容器，截取完整页面，确认无裁切
    pg.evaluate("""() => { document.body.style.height = 'auto'; document.querySelector('main').style.overflow = 'visible';
      document.querySelectorAll('.view.active').forEach(v => v.style.overflow = 'visible'); }"""); pg.wait_for_timeout(600)
    pg.screenshot(path=path, full_page=True)
    pg.evaluate("() => { document.body.style.height = ''; document.querySelector('main').style.overflow = ''; document.querySelectorAll('.view').forEach(v => v.style.overflow = ''); }")
def chat(pg, text, n_mv):
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/")
    pg.fill("#input", text); pg.click("#sendBtn")
    pg.wait_for_function(f"document.querySelectorAll('.mv-inline .mv-chart canvas').length >= {n_mv} && !document.querySelector('#sendBtn').disabled", timeout=240000)
    pg.wait_for_timeout(1200)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1440, "height": 1000}); pg.on("pageerror", lambda e: errs.append(str(e)))
    # IEEE14：建模 → 核对 → 求解
    chat(pg, "帮我建模：三个数据中心，加50MWh储能，核对模型后运行优化调度看能流", 3)
    pg.evaluate("document.querySelector('#chatLog').style.overflow='visible'; document.querySelector('main').style.overflow='visible'; document.body.style.height='auto'")
    pg.wait_for_timeout(800); pg.locator(".mv-inline").first.locator("xpath=..").screenshot(path=f"{OUT}/model_ieee14_build_chat.png")
    pg.click("text=在“模型拓扑”页打开 >> nth=0"); pg.wait_for_selector("#mvBox .mv-chart canvas"); pg.wait_for_timeout(1500)
    pg.set_viewport_size({"width": 1440, "height": 1300}); pg.wait_for_timeout(800)
    full(pg, f"{OUT}/model_ieee14_tab_solved.png")
    box = pg.locator("#mvBox .mv-chart").bounding_box()          # 悬停 + 点击元件
    pg.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2); pg.wait_for_timeout(300)
    pg.evaluate("""() => { const c = document.querySelector('#mvBox')._mv.chart; const s = c.getOption().series[0];
      const i = s.links.findIndex(l => l._t === 'br'); c.dispatchAction({type: 'showTip', seriesIndex: 0, dataType: 'edge', dataIndex: i});
      c.trigger('click', {data: s.links[i]}); }""")
    pg.wait_for_timeout(800); pg.screenshot(path=f"{OUT}/model_ieee14_click_detail.png")
    # 中卫预设
    pg.set_viewport_size({"width": 1440, "height": 1000})
    chat(pg, "建模宁夏中卫夏季大风场景，核对模型并运行调度看能流", 3)
    pg.evaluate("document.querySelector('#chatLog').style.overflow='visible'; document.querySelector('main').style.overflow='visible'; document.body.style.height='auto'")
    pg.wait_for_timeout(800); pg.locator(".mv-inline").first.locator("xpath=..").screenshot(path=f"{OUT}/model_zhongwei_build_chat.png")
    pg.click("text=在“模型拓扑”页打开 >> nth=0"); pg.wait_for_selector("#mvBox .mv-chart canvas"); pg.wait_for_timeout(1500)
    pg.set_viewport_size({"width": 1440, "height": 1300}); pg.wait_for_timeout(800)
    full(pg, f"{OUT}/model_zhongwei_tab_solved.png")
    pg.fill("#mvBox .mv-hr", "3"); pg.dispatch_event("#mvBox .mv-hr", "input"); pg.wait_for_timeout(600)
    pg.locator("#mvBox .mv-chart").screenshot(path=f"{OUT}/model_zhongwei_hour3.png")
    # 场景参数面板：编辑即预览
    pg.goto(B + "/?view=scenario"); pg.evaluate("localStorage.removeItem('scenario')"); pg.goto(B + "/?view=scenario"); pg.wait_for_selector("#scForm input")
    pg.click("#scModel"); pg.wait_for_selector("#mvBox .mv-chart canvas"); pg.wait_for_timeout(1200)
    full(pg, f"{OUT}/model_panel_preview.png")
    # 导出 HTML（独立文件）
    pg2 = br.new_page(viewport={"width": 1400, "height": 1200}); pg2.on("pageerror", lambda e: errs.append(str(e)))
    url = pg.evaluate("fetch('/api/sessions').then(r=>r.json())")[0]["id"]
    pg2.goto(f"{B}/artifacts/{url}/model_topology.html"); pg2.wait_for_selector(".mv-chart canvas"); pg2.wait_for_timeout(1200)
    pg2.screenshot(path=f"{OUT}/model_export_html.png", full_page=True)
    br.close()
print("page errors:", errs)
