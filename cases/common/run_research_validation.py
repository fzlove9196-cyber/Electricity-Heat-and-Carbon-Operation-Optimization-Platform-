"""研究模式验证（经 HTTP API /api/chat，research=true）：韶关热浪 DR、Meta Odense 余热供暖。输出 cases/validation/out/research_*.json"""
import json, sys, urllib.request, os
BASE = os.environ.get("BASE", "http://127.0.0.1:8080"); OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "validation", "out")
def chat(msg, sid=None):
    b = json.dumps(dict(message=msg, session_id=sid, research=True)).encode()
    r = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/api/chat", b, {"Content-Type": "application/json"}), timeout=900).read()); return r
def study(sid): return json.loads(urllib.request.urlopen(BASE + f"/api/sessions/{sid}/study", timeout=60).read())["study"]
CASES = [("shaoguan_dr", "韶关华南数谷夏季热浪下保障热安全同时参与需求响应的最优方案", ["【澄清回答】q_firm=True; q_dr=15"]),
         ("odense_heat", "Meta Odense 数据中心余热供暖值不值，末端是散热器", ["【澄清回答】q_price=200; q_pipe=1; q_capex=150"])]
res = {}
for key, q, ans in CASES:
    r = chat(q); sid = r.get("session_id"); st = study(sid)
    first = dict(preset=st["card"].get("preset"), site=st["card"].get("site"), title=st["card"]["title"], state=st["state"])
    for a in ans: chat(a, sid)
    st = study(sid)
    if st["state"] == "plan": chat("【批准计划】", sid); st = study(sid)
    for _ in range(3):
        if st["state"] == "checkpoint" and st.get("checkpoints"):
            k = [c for c in st["checkpoints"] if c.get("status") == "open"]
            if not k: break
            chat(f"【检查点】{k[0]['id']} {k[0].get('recommend', 'adopt')}", sid); st = study(sid)
    runs = {rid: dict(label=x.get("label"), status=x.get("status"), kpis={k: x.get("kpis", {}).get(k) for k in ("cost_cny", "pue_avg", "tin_max_c", "dr_delivered_mwh", "heat_delivered_mwh", "heat_cost_cny_gj")}) for rid, x in st.get("runs", {}).items()}
    res[key] = dict(session=sid, first=first, final_state=st["state"], revisions=st.get("iter"), firm_dr=st.get("firm_dr"), runs=runs,
                    conclusions=[c["text"] for c in st.get("conclusions", [])], timeline=[t["text"] for t in st.get("timeline", [])][-12:])
    print(key, json.dumps(first, ensure_ascii=False), st["state"], len(runs), "runs"); [print("  ", c[:160]) for c in res[key]["conclusions"]]
json.dump(res, open(os.path.join(OUT, "research.json"), "w"), ensure_ascii=False, indent=1)
