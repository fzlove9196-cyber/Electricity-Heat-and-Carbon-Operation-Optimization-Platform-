"""拓扑编辑 + 重新仿真 UI 截图（headless Chrome，需服务已启动）。用法：python tests/screens_edit.py [preset]"""
import os, sys, json
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
PRESET = sys.argv[1] if len(sys.argv) > 1 else "helinger_typical_day"
errs, report = [], {}
def full(pg, path):
    pg.evaluate("""() => { document.body.style.height = 'auto'; document.querySelector('main').style.overflow = 'visible';
      document.querySelectorAll('.view.active').forEach(v => v.style.overflow = 'visible'); }"""); pg.wait_for_timeout(500)
    pg.screenshot(path=path, full_page=True)
    pg.evaluate("() => { document.body.style.height = ''; document.querySelector('main').style.overflow = ''; document.querySelectorAll('.view').forEach(v => v.style.overflow = ''); }")
def clip_check(pg, tag):
    r = pg.evaluate("""() => { const bad = [];
      for (const el of document.querySelectorAll('#meBar, #meSide, #meForm, .me-fields label, #meCmp table, .mv-top')) {
        if (el.scrollWidth > el.clientWidth + 2) bad.push((el.id || el.className) + ' scrollW ' + el.scrollWidth + '>' + el.clientWidth);
        const b = el.getBoundingClientRect(); if (b.right > window.innerWidth + 1) bad.push((el.id || el.className) + ' right ' + b.right); }
      return bad; }""")
    report[tag] = r or "ok"
def node_px(pg, pred):   # 找到节点的屏幕坐标
    pg.evaluate("() => document.querySelector('#mvBox .mv-chart').scrollIntoView({block: 'center'})"); pg.wait_for_timeout(200)
    return pg.evaluate("""(pred) => { const c = document.querySelector('#mvBox')._mv.chart, s = c.getOption().series[0], f = new Function('n', 'return ' + pred);
      const i = s.data.findIndex(f); if (i < 0) return null; const n = s.data[i];
      const lay = c.convertToPixel({seriesIndex: 0}, [n.x, n.y]); const r = c.getDom().getBoundingClientRect();
      return [r.left + lay[0], r.top + lay[1], n.name]; }""", pred)
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1500, "height": 1100}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("dialog", lambda d: d.accept())
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/?view=model"); pg.wait_for_selector("#meBar")
    pg.select_option("#mePreset", PRESET); pg.click("#meNew"); pg.wait_for_selector("#mvBox .mv-chart canvas"); pg.wait_for_timeout(1200)
    pg.check("#meOn"); pg.wait_for_timeout(600)
    pg.click("#meRun"); pg.wait_for_function("document.querySelector('#meCmp table')", timeout=180000); pg.wait_for_timeout(1500)
    clip_check(pg, "first_run"); full(pg, f"{OUT}/edit_01_loaded_first_run.png")
    # 选中储能 -> 改功率/容量
    x, y, nm = node_px(pg, "n._t==='dev' && n._o.kind==='ess'"); pg.mouse.click(x, y); pg.wait_for_selector("#meSave"); pg.wait_for_timeout(500)
    pg.fill("#meForm [data-k=power_mw]", "200"); pg.fill("#meForm [data-k=energy_mwh]", "800")
    clip_check(pg, "edit_form"); pg.locator("#meWrap").screenshot(path=f"{OUT}/edit_02_select_storage_form.png")
    pg.click("#meSave"); pg.wait_for_function("document.querySelector('#meMsg').textContent.includes('修改储能')", timeout=60000); pg.wait_for_timeout(800)
    # 新增母线 + 用图中点击选端点连线（变压器）
    pg.select_option("#meAdd", "bus"); pg.fill("#meForm [data-k=name]", "新建光伏站35kV"); pg.fill("#meForm [data-k=vn_kv]", "35"); pg.click("#meAddGo")
    pg.wait_for_function("document.querySelector('#meMsg').textContent.includes('新增母线')", timeout=60000); pg.wait_for_timeout(800)
    pg.locator("#meWrap").screenshot(path=f"{OUT}/edit_03_new_bus_dangling_warning.png")
    pg.select_option("#meAdd", "trafo"); pg.wait_for_timeout(300)
    hv = node_px(pg, "n._t==='bus' && n._o.name.includes('华电风电场')")
    pg.mouse.click(hv[0], hv[1]); pg.wait_for_timeout(400); lv = node_px(pg, "n._t==='bus' && n._o.name.includes('新建光伏站')"); pg.mouse.click(lv[0], lv[1]); pg.wait_for_timeout(400)
    report["picked"] = pg.evaluate("() => [...document.querySelectorAll('#meForm .me-bus')].map(s => s.options[s.selectedIndex].text)")
    pg.fill("#meForm [data-k=name]", "新建35kV升压变"); pg.fill("#meForm [data-k=sn_mva]", "150")
    pg.locator("#meWrap").screenshot(path=f"{OUT}/edit_04_connect_pick_endpoints.png")
    pg.click("#meAddGo"); pg.wait_for_function("document.querySelector('#meMsg').textContent.includes('新增变压器')", timeout=60000); pg.wait_for_timeout(800)
    pg.select_option("#meAdd", "pv"); pg.wait_for_timeout(300); lv = node_px(pg, "n._t==='bus' && n._o.name.includes('新建光伏站')")
    pg.select_option("#meForm [data-k=bus]", str(pg.evaluate("() => document.querySelector('#mvBox')._mv.chart.getOption().series[0].data.find(n => n._t==='bus' && n._o.name.includes('新建光伏站'))._o.i")))
    pg.fill("#meForm [data-k=cap_mw]", "120"); pg.click("#meAddGo"); pg.wait_for_function("document.querySelector('#meMsg').textContent.includes('新增光伏')", timeout=60000); pg.wait_for_timeout(800)
    # 拖拽新母线
    lv = node_px(pg, "n._t==='bus' && n._o.name.includes('新建光伏站')")
    pg.mouse.move(lv[0], lv[1]); pg.mouse.down(); pg.mouse.move(lv[0] - 120, lv[1] - 60, steps=8); pg.mouse.up(); pg.wait_for_timeout(800)
    report["drag_msg"] = pg.inner_text("#meMsg")
    # 重新仿真 -> 前后对比
    pg.click("#meRun"); pg.wait_for_function("document.querySelector('#meMsg').textContent.includes('重新仿真完成')", timeout=180000); pg.wait_for_timeout(1500)
    clip_check(pg, "rerun"); full(pg, f"{OUT}/edit_05_rerun_compare_energyflow.png"); pg.locator("#meSide").screenshot(path=f"{OUT}/edit_06_compare_panel.png")
    report["compare"] = pg.inner_text("#meCmp")
    # 校验错误示例：孤立母线 + 数据中心（无电源孤岛）
    pg.select_option("#meAdd", "bus"); pg.fill("#meForm [data-k=name]", "孤立测试母线"); pg.click("#meAddGo"); pg.wait_for_timeout(1200)
    pg.select_option("#meAdd", "dc"); pg.wait_for_timeout(300)
    bi = pg.evaluate("() => document.querySelector('#mvBox')._mv.chart.getOption().series[0].data.find(n => n._t==='bus' && n._o.name==='孤立测试母线')._o.i")
    pg.select_option("#meForm [data-k=bus]", str(bi)); pg.fill("#meForm [data-k=name]", "DC_TEST"); pg.click("#meAddGo"); pg.wait_for_timeout(1500)
    pg.click("#meRun"); pg.wait_for_timeout(1500); report["rerun_blocked_msg"] = pg.inner_text("#meMsg")
    pg.locator("#meSide").screenshot(path=f"{OUT}/edit_07_validation_errors.png")
    pg.click("#meUndo"); pg.wait_for_timeout(1200); pg.click("#meUndo"); pg.wait_for_timeout(1200); report["after_undo_valid"] = pg.inner_text("#meValid")[:200]
    pg.click("#meRedo"); pg.wait_for_timeout(1200); pg.click("#meUndo"); pg.wait_for_timeout(1200)
    full(pg, f"{OUT}/edit_08_after_undo_redo.png")
    report["sid"] = pg.evaluate("SID")
    # 智能体对话看到编辑后的模型
    pg.click("nav a[data-view=chat]"); pg.fill("#input", "帮我优化调度并分析"); pg.click("#sendBtn")
    pg.wait_for_function("!document.querySelector('#sendBtn').disabled && document.querySelectorAll('.mv-inline .mv-chart canvas').length>=1", timeout=240000); pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/edit_09_chat_uses_edited_model.png")
    br.close()
report["page_errors"] = errs
print(json.dumps(report, ensure_ascii=False, indent=1))
