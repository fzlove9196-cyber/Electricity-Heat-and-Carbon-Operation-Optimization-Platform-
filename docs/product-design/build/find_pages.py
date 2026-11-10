import json, subprocess, sys, re
pdf, out = sys.argv[1], sys.argv[2]
E = json.load(open('entries.json'))
n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout).group(1))
norm = lambda s: re.sub(r'\s+', '', s)
pages = [[norm(l) for l in subprocess.run(['pdftotext', '-f', str(i), '-l', str(i), '-layout', pdf, '-'], capture_output=True, text=True).stdout.split('\n') if l.strip()] for i in range(1, n + 1)]
body = next(i for i, p in enumerate(pages) if any('产品功能设计说明V1.0（2026-11-10）' in l for l in p[:3]))
def locate(entries, prefix, cap=24):
    res = {}; cur = body; miss = []
    for k, e in enumerate(entries):
        key = norm(e)[:cap]; found = None
        for pi in range(cur, n):
            if any(l.startswith(key) for l in pages[pi]): found = pi; break
        if found is None: miss.append(e); res[f'{prefix}{k}'] = 0; continue
        cur = found; res[f'{prefix}{k}'] = found - body + 1
    return res, miss
items = {}; allmiss = []
for entries, pre in ((E['headings'], 'h'), (E['figs'], 'f'), (E['tabs'], 't')):
    r, m = locate(entries, pre); items.update(r); allmiss += m
json.dump({'body_start': body + 1, 'total_pages': n, 'items': items}, open(out, 'w'), ensure_ascii=False, indent=1)
print('pages', n, 'body starts at physical page', body + 1, 'missing', len(allmiss)); [print('  MISS', x) for x in allmiss]
