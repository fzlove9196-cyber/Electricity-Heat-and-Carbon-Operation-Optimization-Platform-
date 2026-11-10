"""配置构建器 / 散热方式 / 对比 / 余热可行性 / 拓扑热网 截图（服务需已启动）：python tests/screens_cfg.py"""
import os
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
errs = []
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1600, "height": 1100}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/"); pg.wait_for_timeout(800)
    pg.click("nav a[data-view=config]"); pg.wait_for_selector(".cfg-mode"); pg.wait_for_timeout(800)
    pg.locator("#v-config").screenshot(path=f"{OUT}/cfg_01_builder.png")
    # 三个数据中心，分别选不同散热方式
    pg.click("#cfgAddDc"); pg.click("#cfgAddDc"); pg.wait_for_timeout(300)
    pg.select_option("select[data-p='dcs.1.cooling_mode']", "liquid_cold_plate"); pg.select_option("select[data-p='dcs.2.cooling_mode']", "liquid_immersion")
    pg.fill("input[data-p='dcs.2.racks']", "400"); pg.fill("input[data-p='battery.energy_mwh']", "100"); pg.fill("input[data-p='battery.power_mw']", "50")
    pg.fill("input[data-p='dcs.0.tes_mwh']", "40"); pg.fill("input[data-p='dcs.0.tes_mw']", "20")
    pg.click("#cfgValidate"); pg.wait_for_timeout(800)
    pg.locator("#cfgForm").screenshot(path=f"{OUT}/cfg_02_cooling_selection.png")
    pg.click("#cfgCmpCool"); pg.wait_for_selector(".cfg-res", timeout=180000); pg.wait_for_timeout(2500)
    pg.locator("#cfgRes").screenshot(path=f"{OUT}/cfg_03_comparison_table.png")
    pg.click("#cfgHeat"); pg.wait_for_selector(".cfg-verdicts", timeout=300000); pg.wait_for_timeout(2500)
    pg.locator("#cfgRes").screenshot(path=f"{OUT}/cfg_04_heat_feasibility_verdict.png")
    pg.locator(".cfg-verdicts").screenshot(path=f"{OUT}/cfg_04b_verdict_cards.png")
    pg.click("#cfgBuild"); pg.wait_for_timeout(2500)
    sid = pg.evaluate("SID")
    pg.evaluate(f"fetch('/api/sessions/{sid}/model/rerun', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{baseline:false, ac:false}})}}).then(r=>r.json())")
    pg.wait_for_timeout(9000)
    pg.click("nav a[data-view=model]"); pg.wait_for_timeout(5000)
    ch = pg.locator("#mvBox .mv-chart").first
    (ch if ch.count() else pg.locator("#mvBox")).screenshot(path=f"{OUT}/cfg_05_topology_heat_network.png")
    sk = pg.locator("#mvBox .mv-sk").first
    if sk.count(): sk.screenshot(path=f"{OUT}/cfg_07_sankey_heat.png")
    pg.goto(B + "/"); pg.wait_for_timeout(2500)
    try:
        pg.click("#stepper .st[data-step=params]"); pg.wait_for_selector(".ptbl", timeout=20000); pg.wait_for_timeout(1000)
        pg.evaluate("() => document.querySelectorAll('details.pgrp').forEach(d => d.open = /散热方式|余热品位|蓄能/.test(d.querySelector('summary').textContent))")
        pg.evaluate("() => { for (const s of ['body','main','#v-chat','#wb','#stepCol']) { const e=document.querySelector(s); if(e){e.style.height='auto'; e.style.overflow='visible';} } }"); pg.wait_for_timeout(600)
        pg.locator("#stepCol").screenshot(path=f"{OUT}/cfg_06_param_groups.png")
    except Exception as e: errs.append(f"params: {e}")
    br.close()
print("errors:", errs)
