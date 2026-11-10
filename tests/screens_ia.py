from playwright.sync_api import sync_playwright
OUT="screens/ia"; errs=[]
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for w,h,tag in [(1440,900,"desk"),(1024,768,"lap"),(390,844,"mob")]:
        pg=b.new_page(viewport={"width":w,"height":h}); pg.on("pageerror",lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:8080/?_=1"); pg.wait_for_timeout(1500); pg.screenshot(path=f"{OUT}/{tag}_00_home.png")
        if tag!="desk": continue
        for t in ["config","model","chat"]:
            pg.click(f"nav a[data-view={t}]"); pg.wait_for_timeout(500)
        for t in ["chat:solver","tier","market","chat:results","kb","settings","scenario"]:
            pg.evaluate(f"IA.go('{t}')"); pg.wait_for_timeout(1200); pg.screenshot(path=f"{OUT}/{tag}_{t.replace(':','_')}.png")
            print(t, pg.inner_text("#crumb").replace("\n"," ")[:90], "| active view:", pg.evaluate("document.querySelector('.view.active').id"))
        pg.click("#domBar [data-dom=ops]"); pg.wait_for_timeout(800); print("dom click ->", pg.evaluate("document.querySelector('.view.active').id"))
        pg.fill("#navSearch","审计"); pg.wait_for_timeout(300); pg.screenshot(path=f"{OUT}/desk_search.png"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
        print("search ->", pg.evaluate("document.querySelector('.view.active').id"))
        print("ids ok", pg.evaluate("['tierPanel','mkRun','cfgBuild','stepper','chatForm','scJson','setForm','docTable','simList','cardList'].map(i=>i+':'+!!document.getElementById(i)).join(' ')"))
    b.close()
print("errors",errs)
