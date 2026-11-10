#!/usr/bin/env bash
# 部署后 HTTP 全流程测试（Mock 模式）
set -e; B=${B:-http://127.0.0.1:8080}; J="Content-Type: application/json"; cd "$(dirname "$0")"
echo "== 1. 聊天(流式) 算电协同"; curl -sN -X POST $B/api/chat/stream -H "$J" -d '{"message":"三个数据中心，加50MWh储能，峰谷电价，帮我优化调度并分析"}' > /tmp/s1.txt
grep -o '"type": "tool_end", "id": "[^"]*", "name": "[a-z_]*", "ok": [a-z]*' /tmp/s1.txt | sed 's/.*"name": //'
SID=$(grep -o '"session_id": "[a-z0-9]*"' /tmp/s1.txt | head -1 | cut -d'"' -f4); echo "session=$SID"
curl -s $B/artifacts/$SID/report.md | grep -E "节省|电压范围|日放电量"
echo "== 2. 上传文档 -> 检索"; curl -s -F "file=@data/ess_guide.md" $B/api/kb/docs; echo
curl -s -X POST $B/api/chat -H "$J" -d '{"message":"根据知识库，储能SOC约束一般怎么设置？"}' | python3 -c "import sys,json;d=json.load(sys.stdin);print('tools',[m['name'] for m in d['messages'] if m['role']=='tool']);print('citations',d['citations']);t=[json.loads(m['content']) for m in d['messages'] if m['role']=='tool'][0];print('top', t['docs'][0]['source'], t['docs'][0]['text'][:60])"
echo "== 3. 教技能卡 -> 复用"; curl -s -X POST $B/api/chat -H "$J" -d '{"message":"记住：配网数据中心接入校核。类型：配网校核。关键词：配网 数据中心 接入 校核 电压。步骤：run_opendss -> run_matpower。参数：{\"run_opendss\":{\"dc_kw\":6000},\"run_matpower\":{\"case\":\"case33bw\",\"mode\":\"runpf\"}}。校验：电压0.93-1.07"}' | python3 -c "import sys,json;d=json.load(sys.stdin);print([json.loads(m['content']) for m in d['messages'] if m['role']=='tool'])"
curl -s -X POST $B/api/chat -H "$J" -d '{"message":"帮我做一下数据中心接入配网的校核"}' | python3 -c "import sys,json;d=json.load(sys.stdin);e=d['events'];print('retrieval',[x for x in e if x['type']=='retrieval']);print('calls',[(x['name'],x['ok'],x.get('result',{}).get('vmin_pu')) for x in e if x['type']=='tool_end'])"
echo "== 4. 其他接口"; curl -s $B/api/simulators | python3 -c "import sys,json;[print(s['available'],s['name']) for s in json.load(sys.stdin)['simulators']]"
curl -s $B/api/cards | python3 -c "import sys,json;print('cards',[(c['title'],c['uses']) for c in json.load(sys.stdin)])"
curl -s -X PUT $B/api/settings -H "$J" -d '{"LLM_API_KEY":"sk-test-123456789"}' >/dev/null; curl -s $B/api/settings; echo
curl -s -X PUT $B/api/settings -H "$J" -d '{"LLM_API_KEY":""}' >/dev/null
echo "== 5. Phase1: Pareto（碳）"; curl -s -X POST $B/api/chat -H "$J" -d '{"message":"做一下成本和碳排放的Pareto分析，三个数据中心加50MWh储能"}' > /tmp/s5.json
python3 -c "import json;d=json.load(open('/tmp/s5.json'));e=d['events'];t=[x for x in e if x['type']=='tool_end'];print('calls',[(x['name'],x['ok']) for x in t]);assert all(x['ok'] for x in t);p=[x for x in t if x['name']=='run_pareto_sweep'][0]['result'];print('pareto',[(q['weight'],q['cost_cny'],q['emissions_tco2']) for q in p['points']]);print('tradeoff',p['tradeoff']);print('SID',d['session_id'])"
SID5=$(python3 -c "import json;print(json.load(open('/tmp/s5.json'))['session_id'])"); curl -sf -o /dev/null $B/artifacts/$SID5/pareto_echarts.json && curl -sf -o /dev/null $B/artifacts/$SID5/pareto.png && echo "pareto artifacts OK"
curl -sf -o /dev/null $B/static/vendor/echarts.min.js && echo "echarts local bundle OK"
echo "== 6. Phase1: 任务+截止时间+迁移"; curl -s -X POST $B/api/chat -H "$J" -d '{"message":"30个任务带截止时间，考虑迁移时延和带宽，碳价100，帮我优化调度"}' | python3 -c "import sys,json;d=json.load(sys.stdin);e=d['events'];t=[x for x in e if x['type']=='tool_end'];assert all(x['ok'] for x in t),[x['result'] for x in t if not x['ok']];k=[x for x in t if x['name']=='compute_kpis'][0]['result']['kpis'];print({a:k[a] for a in ['jobs_n','jobs_deadline_met_pct','jobs_migrated_n','jobs_latency_sensitive_migrated_n','migrated_mwh','migration_energy_mwh','link_max_util_pct','emissions_tco2','cost_cny']})"
echo "== 7. Phase1: 场景面板接口 / RAG"; curl -s -X POST $B/api/jobs/generate -H "$J" -d '{"n_jobs":12}' | python3 -c "import sys,json;d=json.load(sys.stdin);print('jobs',len(d['jobs']),'links',len(d['links']))"
curl -s -X POST $B/api/carbon/profile -H "$J" -d 'null' | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:round(sum(v)/24,4) for k,v in d.items()})"
curl -s "$B/api/kb/search?q=Alibaba%20GPU%20trace%20%E6%95%B0%E6%8D%AE%E9%9B%86" | python3 -c "import sys,json;d=json.load(sys.stdin);print('kb',[x['source'] for x in d['docs']],d['latency_ms'],'ms',d['backend'])"
echo "ALL HTTP E2E OK"
