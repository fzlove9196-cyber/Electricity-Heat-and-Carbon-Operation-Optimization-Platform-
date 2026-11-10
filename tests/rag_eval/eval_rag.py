"""RAG 检索评测：hit@1 / hit@3 / 平均延迟。用法：
DATA_DIR=<数据目录副本> python tests/rag_eval/eval_rag.py [--label before|after] [--out file.json]
相关性判定：返回片段文本包含任一期望子串即算命中（文档片段）。"""
import json, os, sys, time, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
QUERIES = [
    ("Alibaba GPU trace 数据集", ["cluster-trace-gpu-v2020"]),
    ("PUE 参考值", ["Uptime Institute 2024", "全球平均 PUE"]),
    ("碳感知调度 碳强度", ["Carbon-Aware Computing for Datacenters", "边际碳强度"]),
    ("AI训练 功率波动", ["Power Stabilization for AI Training", "AI 训练 DC 功率摆动", "训练/微调周期性"]),
    ("national grid carbon emission factor", ["0.5306"]),
    ("H100 GPU peak and idle power", ["H100 700"]),
    ("东数西算 绿电占比要求", [">80%"]),
    ("spatial migration latency and bandwidth constraints", ["带宽：m_ik"]),
    ("distributionally robust scheduling under uncertainty", ["分布鲁棒", "DRO 调度"]),
    ("Azure LLM inference trace", ["Azure LLM Inference"]),
    ("储能 SOC 约束怎么设置", ["10%–95%", "SOC_min ≤ SOC"]),
    ("UPS frequency regulation demonstration", ["Basefarm", "UPS 调频示范"]),
]
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--label", default="run"); ap.add_argument("--out"); a = ap.parse_args()
    from app import knowledge as kb
    kb.retrieve("warmup 预热")
    rows = []; h1 = h3 = 0; lat = []
    for q, exp in QUERIES:
        t = time.time(); docs = kb.search_docs(q, k=3); dt = time.time() - t; lat.append(dt)
        hits = [any(e in d["text"] for e in exp) for d in docs]
        r1 = bool(hits[:1] and hits[0]); r3 = any(hits[:3]); h1 += r1; h3 += r3
        rows.append(dict(query=q, hit1=r1, hit3=r3, latency_ms=round(dt*1000), top=[d["source"] for d in docs]))
        print(f"{'✓' if r1 else ('~' if r3 else '✗')} {dt*1000:6.0f}ms  {q}  -> {[d['source'] for d in docs]}")
    n = len(QUERIES); lat_sorted = sorted(lat)
    summ = dict(label=a.label, n=n, hit1=round(h1/n, 3), hit3=round(h3/n, 3), avg_latency_ms=round(1000*sum(lat)/n),
                p95_latency_ms=round(1000*lat_sorted[int(0.95*(n-1))]), config=kb.backend_info() if hasattr(kb, "backend_info") else "bm25(char-bigram)")
    print(json.dumps(summ, ensure_ascii=False))
    if a.out: json.dump(dict(summary=summ, rows=rows), open(a.out, "w"), ensure_ascii=False, indent=1)
if __name__ == "__main__": main()
