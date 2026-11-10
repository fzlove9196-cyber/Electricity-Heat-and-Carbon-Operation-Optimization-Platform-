"""第二轮真实项目验证截图（mock，需服务已启动）：python tests/screens_validation.py → screens/val_*.png"""
import os
from playwright.sync_api import sync_playwright
B = os.getenv("B", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(__file__), "..", "screens"); os.makedirs(OUT, exist_ok=True)
errs = []
def full(pg, name):
    pg.evaluate("""() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol']) { const e = document.querySelector(s); if (e) { e.style.height = 'auto'; e.style.overflow = 'visible'; } }
      const c = document.querySelector('#chatCol'); if (c) c.style.maxHeight = '1400px'; }"""); pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/{name}.png", full_page=True)
    pg.evaluate("() => { for (const s of ['body', 'main', '#v-chat', '#wb', '#stepCol', '#chatCol']) { const e = document.querySelector(s); if (e) { e.style.height = ''; e.style.overflow = ''; e.style.maxHeight = ''; } } }")
def ask(pg, text, wait, timeout=300000):
    pg.fill("#input", text); pg.click("#sendBtn"); pg.wait_for_selector(wait, timeout=timeout); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=timeout); pg.wait_for_timeout(800)
def study(pg, q, tag):
    pg.goto(B + "/"); pg.evaluate("localStorage.removeItem('sid')"); pg.goto(B + "/"); pg.wait_for_timeout(1000)
    pg.check("#researchMode"); ask(pg, q, ".rs-card.clar"); full(pg, f"val_{tag}_1_problem")
    pg.locator(".rs-card.clar [data-act=ans]").last.click(); pg.wait_for_selector(".rs-card.plan", timeout=60000); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled"); pg.wait_for_timeout(800)
    pg.locator(".rs-card.plan [data-act=approve]").last.click()
    pg.wait_for_selector("#chatLog .rs-card.conc, #chatLog .rs-card.ckpt", timeout=300000); pg.wait_for_function("() => !document.querySelector('#sendBtn').disabled", timeout=300000); pg.wait_for_timeout(1000)
    if pg.locator("#chatLog .rs-card.ckpt").count() and not pg.locator("#chatLog .rs-card.conc").count():
        pg.locator("#chatLog .rs-card.ckpt button").first.click(); pg.wait_for_selector("#chatLog .rs-card.conc", timeout=300000); pg.wait_for_timeout(1000)
    pg.click("#stepper .st[data-step=research]"); pg.wait_for_timeout(1000); full(pg, f"val_{tag}_2_conclusions")
    try:
        pg.click("#stepper .st[data-step=model]"); pg.wait_for_timeout(2500); full(pg, f"val_{tag}_3_model")
    except Exception as e: errs.append(f"model step: {e}")
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = br.new_page(viewport={"width": 1700, "height": 1050}); pg.on("pageerror", lambda e: errs.append(str(e)))
    study(pg, "韶关华南数谷夏季热浪下保障热安全同时参与需求响应的最优方案", "shaoguan_dr")
    study(pg, "Meta Odense 数据中心余热供暖值不值，末端是散热器", "odense_heat")
    br.close()
print("errors:", errs)
