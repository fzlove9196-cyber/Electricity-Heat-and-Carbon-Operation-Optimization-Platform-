"""算-电-热-碳耦合 UI 截图（需服务已启动）：python tests/screens_couple.py [preset]"""
import os, sys, json
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
PRESET = sys.argv[1] if len(sys.argv) > 1 else "zhongwei_summer_coupled_dr"; TAG = sys.argv[2] if len(sys.argv) > 2 else ""
errs = []
def step(pg, s): pg.click(f"#stepper .st[data-step={s}]"); pg.wait_for_timeout(1200)
def el(pg, sel, name):
    loc = pg.locator(sel).first; loc.scroll_into_view_if_needed(); pg.wait_for_timeout(400); loc.screenshot(path=f"{OUT}/couple_{TAG}{name}.png")
def section(pg, start, end, name):   # 截取 #stepBody 中 start..end 之间区域
    pg.evaluate("() => { for (const s of ['body','main','#v-chat','#wb','#stepCol']) { const e=document.querySelector(s); if(e){e.style.height='auto'; e.style.overflow='visible';} } }"); pg.wait_for_timeout(500)
    b = pg.evaluate(f"""() => {{ const a=document.querySelector('{start}').getBoundingClientRect(); const z=document.querySelector('{end}'); const c=z?z.getBoundingClientRect():a;
       const col=document.querySelector('#stepCol').getBoundingClientRect(); return {{x:col.x, y:a.y+window.scrollY-6, w:col.width, h:(c.y-a.y)+12}}; }}""")
    pg.screenshot(path=f"{OUT}/couple_{TAG}{name}.png", full_page=True, clip=dict(x=b["x"], y=b["y"], width=b["w"], height=max(b["h"], 200)))
    pg.evaluate("() => { for (const s of ['body','main','#v-chat','#wb','#stepCol']) { const e=document.querySelector(s); if(e){e.style.height=''; e.style.overflow='';} } }")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1600, "height": 1100}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and errs.append("console: " + m.text))
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/"); pg.wait_for_selector("#gStart"); pg.wait_for_timeout(800)
    pg.select_option("#gPreset", PRESET); pg.click("#gStart"); pg.wait_for_selector(".ptbl", timeout=120000); pg.wait_for_timeout(1500)
    pg.evaluate("() => document.querySelectorAll('details.pgrp').forEach(d => d.open = /热管理|余热|需求响应|^碳/.test(d.querySelector('summary').textContent))")
    pg.wait_for_timeout(500)
    first = pg.locator("details.pgrp[open]").first; first.scroll_into_view_if_needed()
    pg.evaluate("() => { for (const s of ['body','main','#v-chat','#wb','#stepCol']) { const e=document.querySelector(s); if(e){e.style.height='auto'; e.style.overflow='visible';} } }"); pg.wait_for_timeout(500)
    pg.locator("#stepCol").screenshot(path=f"{OUT}/couple_{TAG}01_params_groups.png")
    pg.evaluate("() => { for (const s of ['body','main','#v-chat','#wb','#stepCol']) { const e=document.querySelector(s); if(e){e.style.height=''; e.style.overflow='';} } }")
    pg.click("#pConfirm"); pg.wait_for_selector("#wfMv .mv-chart canvas", timeout=60000); pg.wait_for_timeout(1800)
    el(pg, "#wfMv .mv-chart", "02_topology_thermal_nodes")
    step(pg, "solver"); pg.wait_for_selector(".ftbl", timeout=30000); pg.wait_for_timeout(1500)
    pg.evaluate("() => { for (const s of ['body','main','#v-chat','#wb','#stepCol']) { const e=document.querySelector(s); if(e){e.style.height='auto'; e.style.overflow='visible';} } }"); pg.wait_for_timeout(600)
    pg.locator("#stepCol").screenshot(path=f"{OUT}/couple_{TAG}03_formulation.png")
    pg.evaluate("() => { for (const s of ['body','main','#v-chat','#wb','#stepCol']) { const e=document.querySelector(s); if(e){e.style.height=''; e.style.overflow='';} } }")
    pg.click("#sRun"); pg.wait_for_selector(".kpis", timeout=600000); pg.wait_for_timeout(3500)
    el(pg, "#chTin", "04_inlet_temp_safety_band"); el(pg, "#chPue", "05_dynamic_pue")
    if pg.locator("#coupleSec").count(): section(pg, "#coupleSec", "#chTin", "06_thermal_table")
    el(pg, "#chCool", "07_cooling_tes")
    if pg.locator("#chHeat canvas").count(): el(pg, "#chHeat", "08_heat_recovery")
    if pg.locator("#drSec").count(): section(pg, "#drSec", "#chLoad", "09_dr_result")
    if pg.locator("#chWater").count(): el(pg, "#chWater", "10_attribution")
    step(pg, "model"); pg.wait_for_selector("#wfMv .mv-chart canvas", timeout=60000); pg.wait_for_timeout(2500)
    el(pg, "#wfMv .mv-chart", "11_topology_solved_heatcold_flows")
    if pg.locator("#wfMv .mv-sk").count(): el(pg, "#wfMv .mv-sk", "12_sankey_elec_heat_cold")
    br.close()
print(json.dumps({"errors": errs}, ensure_ascii=False))
