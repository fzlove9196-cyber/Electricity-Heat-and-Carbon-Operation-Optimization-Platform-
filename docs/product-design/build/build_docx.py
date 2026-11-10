# -*- coding: utf-8 -*-
"""Build sim-agent 产品功能设计说明 DOCX (editable OMML) and PDF-variant DOCX (equation images).
usage: python build_docx.py <mode: omml|img> <out.docx> [pages.json]
pages.json: {"body_start": n, "items": {key: page}} pre-fills TOC/LOF/LOT page numbers."""
import re, sys, json, os, copy
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT, WD_TAB_LEADER, WD_BREAK
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import parse_xml, OxmlElement
from lxml import etree
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MODE = sys.argv[1]; OUT = sys.argv[2]
PAGES = json.load(open(sys.argv[3])) if len(sys.argv) > 3 and os.path.exists(sys.argv[3]) else {"items": {}}
SERIF = "Noto Serif CJK SC"; SANS = "Noto Sans CJK SC"
TITLE = "sim-agent 算电热碳耦合仿真与优化平台"
SUBTITLE = "产品功能设计说明"
DATE = "2026-11-10"
MNS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
STATUS_COLOR = {"已实现": "1E7B34", "部分实现": "B26A00", "未实现": "666666", "已知缺陷": "C0392B", "研究可选": "1F5FA8"}

doc = Document()
# ---------------- styles ----------------
def set_font(style_or_run_rpr_owner, name, size=None, bold=None, color=None):
    f = style_or_run_rpr_owner.font
    f.name = name
    if size: f.size = Pt(size)
    if bold is not None: f.bold = bold
    if color: f.color.rgb = RGBColor.from_string(color)
    rpr = style_or_run_rpr_owner.element.get_or_add_rPr() if hasattr(style_or_run_rpr_owner.element, 'get_or_add_rPr') else None
    if rpr is not None:
        rf = rpr.find(qn('w:rFonts'))
        if rf is None: rf = OxmlElement('w:rFonts'); rpr.insert(0, rf)
        for a in ('w:ascii', 'w:hAnsi', 'w:eastAsia', 'w:cs'): rf.set(qn(a), name)

st = doc.styles
set_font(st['Normal'], SERIF, 10.5)
st['Normal'].paragraph_format.space_after = Pt(4)
st['Normal'].paragraph_format.line_spacing = 1.3
for lvl, size in ((1, 16), (2, 13), (3, 11.5)):
    s = st[f'Heading {lvl}']
    set_font(s, SANS, size, True, '1F3864')
    s.font.italic = False
    pf = s.paragraph_format; pf.space_before = Pt(14 if lvl == 1 else 10); pf.space_after = Pt(6); pf.keep_with_next = True
    pf.line_spacing = 1.2
for name in ('TOC 1', 'TOC 2', 'Caption', 'Table of Figures'):
    try: s = st[name]
    except KeyError: s = st.add_style(name, 1)
    set_font(s, SERIF if name != 'Caption' else SANS, 10.5 if name != 'Caption' else 9.5)
    s.base_style = st['Normal']
st['Caption'].font.bold = False; st['Caption'].font.color.rgb = RGBColor.from_string('1F3864')
for nm in ('图题', '表题'):
    s2 = st.add_style(nm, 1); s2.base_style = st['Caption']; set_font(s2, SANS, 9.5, False, '1F3864')
    s2.paragraph_format.space_after = Pt(4); s2.paragraph_format.first_line_indent = Pt(0)
st['TOC 2'].paragraph_format.left_indent = Cm(0.74)
for name in ('TOC 1', 'TOC 2', 'Table of Figures'):
    st[name].paragraph_format.space_after = Pt(1); st[name].paragraph_format.line_spacing = 1.15
st['TOC 1'].font.bold = True
set_font(st['List Bullet'], SERIF, 10.5)

sec = doc.sections[0]
sec.page_width = Cm(21); sec.page_height = Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.5); sec.top_margin = Cm(2.5); sec.bottom_margin = Cm(2.2)
TEXT_W = 16.0

# ---------------- helpers ----------------
def fld(par, instr, cached, bold=False):
    def r(): 
        run = par.add_run(); 
        if bold: run.bold = True
        return run
    b = r(); e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'begin'); b._r.append(e)
    i = r(); t = OxmlElement('w:instrText'); t.set(qn('xml:space'), 'preserve'); t.text = f' {instr} '; i._r.append(t)
    s = r(); e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'separate'); s._r.append(e)
    c = r(); c.text = str(cached)
    n = r(); e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'end'); n._r.append(e)
    return c

def fld_begin(par, instr):
    run = par.add_run(); e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'begin'); run._r.append(e)
    run = par.add_run(); t = OxmlElement('w:instrText'); t.set(qn('xml:space'), 'preserve'); t.text = f' {instr} '; run._r.append(t)
    run = par.add_run(); e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'separate'); run._r.append(e)
def fld_end(par):
    run = par.add_run(); e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'end'); run._r.append(e)

PPR_AFTER_SHD = ('w:tabs','w:suppressAutoHyphens','w:kinsoku','w:wordWrap','w:overflowPunct','w:topLinePunct','w:autoSpaceDE','w:autoSpaceDN','w:bidi','w:adjustRightInd','w:snapToGrid','w:spacing','w:ind','w:contextualSpacing','w:mirrorIndents','w:suppressOverlap','w:jc','w:textDirection','w:textAlignment','w:textboxTightWrap','w:outlineLvl','w:divId','w:cnfStyle','w:rPr','w:sectPr','w:pPrChange')
def add_pbdr(par, inner):
    ppr = par._p.get_or_add_pPr()
    ppr.insert_element_before(parse_xml(f'<w:pBdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{inner}</w:pBdr>'), 'w:shd', *PPR_AFTER_SHD)
def shade(par, fill='EEF3FA', border='5B8BD0'):
    ppr = par._p.get_or_add_pPr()
    ppr.insert_element_before(parse_xml(f'<w:shd xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="clear" w:color="auto" w:fill="{fill}"/>'), *PPR_AFTER_SHD)
    add_pbdr(par, f'<w:left w:val="single" w:sz="18" w:space="6" w:color="{border}"/>')

INLINE = re.compile(r'(\*\*.+?\*\*|【(?:已实现|部分实现|未实现|已知缺陷|研究可选)】[^【\s，。；、]*|₂|(?<![A-Za-z0-9_./{-])[A-Za-zα-ωΑ-Ω][_^](?:[A-Za-z0-9]+|\{[^}]+\})(?![A-Za-z0-9_]))')
SUBSKIP = {'t_min', 't_rec', 't_allow', 'p_peak', 'p_idle'}
def add_inline(par, text, size=None, color=None, bold=False):
    pos = 0
    for m in INLINE.finditer(text):
        if m.start() > pos: _run(par, text[pos:m.start()], size, color, bold)
        tok = m.group(0)
        if tok == '₂':
            r = _run(par, '2', size, color, bold); r.font.subscript = True
        elif len(tok) > 2 and tok[1] in '_^' and not tok.startswith('**') and tok not in SUBSKIP:
            _run(par, tok[0], size, color, bold)
            r = _run(par, tok[2:].strip('{}'), size, color, bold)
            if tok[1] == '_': r.font.subscript = True
            else: r.font.superscript = True
        elif tok in SUBSKIP:
            _run(par, tok, size, color, bold)
        elif tok.startswith('**'):
            _run(par, tok[2:-2], size, color, True)
        else:
            key = re.match(r'【(.+?)】', tok).group(1)
            _run(par, tok, size, STATUS_COLOR[key], True)
        pos = m.end()
    if pos < len(text): _run(par, text[pos:], size, color, bold)
def _run(par, t, size, color, bold):
    r = par.add_run(t)
    if size: r.font.size = Pt(size)
    if color: r.font.color.rgb = RGBColor.from_string(color)
    if bold: r.bold = True
    return r

def set_cell_bg(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    tcPr.append(parse_xml(f'<w:shd xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="clear" w:color="auto" w:fill="{fill}"/>'))

def fix_widths(tb, widths):
    tbl = tb._tbl; tblPr = tbl.tblPr
    for tag in ('w:tblW', 'w:tblLayout'):
        e = tblPr.find(qn(tag))
        if e is not None: tblPr.remove(e)
    tw = OxmlElement('w:tblW'); tw.set(qn('w:w'), str(int(sum(widths) * 567))); tw.set(qn('w:type'), 'dxa'); tblPr.append(tw)
    lay = OxmlElement('w:tblLayout'); lay.set(qn('w:type'), 'fixed'); tblPr.append(lay)
    grid = tbl.tblGrid
    for gc, w in zip(grid.findall(qn('w:gridCol')), widths): gc.set(qn('w:w'), str(int(w * 567)))
    for row in tb.rows:
        for c, w in zip(row.cells, widths): c.width = Cm(w)

def keep_next(par): par.paragraph_format.keep_with_next = True

# --------------- parse source ---------------
src = open(os.path.join(HERE, 'source.md'), encoding='utf-8').read().split('\n')
blocks = []; i = 0
while i < len(src):
    l = src[i]
    if not l.strip(): i += 1; continue
    m = re.match(r'^(#{1,3}) (\S+) (.+)$', l)
    if m: blocks.append(('h', len(m.group(1)), m.group(2), m.group(3).strip())); i += 1; continue
    if l.startswith('Table:'):
        title = l[6:].strip(); rows = []; i += 1
        while i < len(src) and src[i].startswith('|'):
            if not re.match(r'^\|[-|: ]+\|$', src[i]): rows.append([c.strip() for c in src[i].strip().strip('|').split('|')])
            i += 1
        blocks.append(('t', title, rows)); continue
    m = re.match(r'^!\[(.+?)\]\((.+?)\)(?:\{(.*)\})?\s*$', l)
    if m: blocks.append(('f', m.group(1), m.group(2), m.group(3) or '')); i += 1; continue
    m = re.match(r'^\$\$(.+?)\$\$\s*(?:\{(.*)\})?\s*$', l)
    if m: blocks.append(('e', m.group(1).strip(), m.group(2) or '')); i += 1; continue
    if l.startswith('> '): blocks.append(('q', l[2:].strip())); i += 1; continue
    if l.startswith('- '): blocks.append(('b', l[2:].strip())); i += 1; continue
    m = re.match(r'^(\d+)\. (.+)$', l)
    if m: blocks.append(('n', m.group(1), m.group(2))); i += 1; continue
    blocks.append(('p', l.strip())); i += 1

# numbering pass
chap = 0; fcnt = {}; tcnt = {}; ecnt = {}
headings = []; figs = []; tabs = []
for b in blocks:
    if b[0] == 'h' and b[1] == 1: chap = int(b[2]); fcnt[chap] = tcnt[chap] = ecnt[chap] = 0
    if b[0] == 'h' and b[1] <= 2: headings.append((b[1], f'{b[2]} {b[3]}'))
    if b[0] == 'f': fcnt[chap] += 1; figs.append(f'图 {chap}-{fcnt[chap]} {b[1]}')
    if b[0] == 't': tcnt[chap] += 1; tabs.append(f'表 {chap}-{tcnt[chap]} {b[1]}')
PG = PAGES.get('items', {})

# --------------- cover ---------------
for _ in range(5): doc.add_paragraph()
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run(TITLE); r.font.size = Pt(20); r.bold = True; r.font.name = SANS; r.font.color.rgb = RGBColor.from_string('1F3864')
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(12)
r = p.add_run(SUBTITLE); r.font.size = Pt(30); r.bold = True; r.font.name = SANS; r.font.color.rgb = RGBColor.from_string('1F3864')
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before = Pt(10)
r = p.add_run('Product Functional Design Specification'); r.font.size = Pt(13); r.font.color.rgb = RGBColor.from_string('555555')
for _ in range(6): doc.add_paragraph()
info = [('文档版本', 'V1.0'), ('编制日期', '2026-11-10（亚洲/上海，UTC+8）'), ('对象系统', '本地应用 /workspace/sim-agent（Mock LLM 模式）'),
        ('依据', '当前代码与仓库文档审计；代码与文档冲突时以代码为准'), ('密级', '内部资料；不含密钥、账号或私有项目数据')]
t = doc.add_table(rows=len(info), cols=2); t.alignment = WD_TABLE_ALIGNMENT.CENTER; t.style = 'Table Grid'
for k, (a, b2) in enumerate(info):
    c0, c1 = t.rows[k].cells; c0.width = Cm(3.2); c1.width = Cm(10.5)
    c0.text = ''; c1.text = ''
    rr = c0.paragraphs[0].add_run(a); rr.bold = True; rr.font.size = Pt(10.5); set_cell_bg(c0, 'E8EEF7')
    rr = c1.paragraphs[0].add_run(b2); rr.font.size = Pt(10.5)
fix_widths(t, [3.2, 10.5])
for _ in range(4): doc.add_paragraph()
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
add_inline(p, '说明：本文对每项功能标注实现状态；交易为沙盘、规则包为示范，测试与验收口径截至 2026-11-07，详见第 9 章。', 9, '666666')
doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

# --------------- TOC / LOF / LOT ---------------
def toc_block(title, instr, entries, keyprefix, style_for):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(title); r.font.size = Pt(16); r.bold = True; r.font.name = SANS; r.font.color.rgb = RGBColor.from_string('1F3864')
    p.paragraph_format.space_after = Pt(12)
    paras = []
    for k, (lvl, text) in enumerate(entries):
        q = doc.add_paragraph(style=style_for(lvl))
        q.paragraph_format.tab_stops.add_tab_stop(Cm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        paras.append(q)
    for k, (lvl, text) in enumerate(entries):
        q = paras[k]
        if k == 0: fld_begin(q, instr)
        q.add_run(text); q.add_run('\t'); q.add_run(str(PG.get(f'{keyprefix}{k}', 0)))
        if k == len(entries) - 1: fld_end(q)
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

toc_block('目　录', 'TOC \\o "1-2" \\h \\z \\u', headings, 'h', lambda l: 'TOC 1' if l == 1 else 'TOC 2')
toc_block('图　目　录', 'TOC \\h \\z \\t "图题,1"', [(0, x) for x in figs], 'f', lambda l: 'Table of Figures')
# last toc_block adds page break; LOT then section break
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run('表　目　录'); r.font.size = Pt(16); r.bold = True; r.font.name = SANS; r.font.color.rgb = RGBColor.from_string('1F3864')
p.paragraph_format.space_after = Pt(12)
paras = []
for k, x in enumerate(tabs):
    q = doc.add_paragraph(style='Table of Figures'); q.paragraph_format.tab_stops.add_tab_stop(Cm(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS); paras.append(q)
for k, x in enumerate(tabs):
    q = paras[k]
    if k == 0: fld_begin(q, 'TOC \\h \\z \\t "表题,1"')
    q.add_run(x); q.add_run('\t'); q.add_run(str(PG.get(f't{k}', 0)))
    if k == len(tabs) - 1: fld_end(q)

# front section page numbering (roman), cover suppressed
def footer_page(section, fmt, start=None, title_pg=False):
    sp = section._sectPr
    pg = sp.find(qn('w:pgNumType'))
    if pg is None:
        pg = OxmlElement('w:pgNumType'); sp.insert_element_before(pg, 'w:cols','w:formProt','w:vAlign','w:noEndnote','w:titlePg','w:textDirection','w:bidi','w:rtlGutter','w:docGrid','w:printerSettings','w:sectPrChange')
    pg.set(qn('w:fmt'), fmt)
    if start is not None: pg.set(qn('w:start'), str(start))
    section.different_first_page_header_footer = title_pg
    f = section.footer; f.is_linked_to_previous = False
    fp = f.paragraphs[0]; fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in list(fp.runs): r._r.getparent().remove(r._r)
    fld(fp, 'PAGE', 1).font.size = Pt(9)
front = doc.sections[0]
footer_page(front, 'upperRoman', 1, title_pg=True)

body = doc.add_section(WD_SECTION.NEW_PAGE)
footer_page(body, 'decimal', 1)
body.different_first_page_header_footer = False
h = body.header; h.is_linked_to_previous = False
hp = h.paragraphs[0]; hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
r = hp.add_run(f'{TITLE} · {SUBTITLE} V1.0（{DATE}）'); r.font.size = Pt(8.5); r.font.color.rgb = RGBColor.from_string('666666')
add_pbdr(hp, '<w:bottom w:val="single" w:sz="4" w:space="1" w:color="999999"/>')
front.header.is_linked_to_previous = False

# --------------- equations ---------------
from latex2mathml.converter import convert as l2m
import mathml2omml
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
matplotlib.rcParams['mathtext.fontset'] = 'cm'
def omml(latex):
    x = mathml2omml.convert(l2m(latex))
    x = x.replace('<m:oMath><m:box><m:e>', '<m:oMath>').replace('</m:e></m:box></m:oMath>', '</m:oMath>')
    x = x.replace('<m:t></m:t>', '<m:t xml:space="preserve">\u2002</m:t>')
    x = re.sub(r'(<m:groupChrPr>(?:(?!</m:groupChr).)*?)</m:groupChr>', r'\1</m:groupChrPr>', x)  # mathml2omml closing-tag bug for \bar
    x = x.replace('<m:oMath>', f'<m:oMath {MNS}>', 1)
    el = parse_xml(x)
    M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
    for nary in el.iter(M + 'nary'):
        pr = nary.find(M + 'naryPr')
        for part, hide in (('sub', 'subHide'), ('sup', 'supHide')):
            e = nary.find(M + part)
            if e is not None and len(e) == 0:
                h = etree.SubElement(pr, M + hide); h.set(M + 'val', '1')
    return el
def eq_png(latex, path):
    e = re.sub(r'\\le(?![a-z])', r'\\leq', latex); e = re.sub(r'\\ge(?![a-z])', r'\\geq', e)
    fig = plt.figure(figsize=(0.01, 0.01)); fig.text(0, 0, f'${e}$', fontsize=11)
    fig.savefig(path, dpi=300, bbox_inches='tight', pad_inches=0.03, transparent=False, facecolor='white'); plt.close(fig)

# --------------- images ---------------
def prep_image(path):
    if not os.path.isabs(path): path = os.path.join(HERE, path); return path
    out = os.path.join(HERE, 'screens', os.path.splitext(os.path.basename(path))[0] + '.jpg')
    if not os.path.exists(out):
        im = Image.open(path).convert('RGB')
        if im.width > 1600: im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)
        im.save(out, 'JPEG', quality=86)
    return out

# --------------- body ---------------
chap = 0; fc = tc = ec = 0; hk = fk = tk = 0; first_h1 = True
for b in blocks:
    k = b[0]
    if k == 'h':
        if b[1] == 1:
            chap = int(b[2]); fc = tc = ec = 0
            p = doc.add_heading(level=1)
            if not first_h1: p.paragraph_format.page_break_before = True
            first_h1 = False
        else:
            p = doc.add_heading(level=b[1])
        p.add_run(f'{b[2]}  {b[3]}')
    elif k == 'p':
        p = doc.add_paragraph(); add_inline(p, b[1]); p.paragraph_format.first_line_indent = Pt(21)
    elif k == 'b':
        p = doc.add_paragraph(style='List Bullet'); add_inline(p, b[1])
    elif k == 'n':
        p = doc.add_paragraph(); p.paragraph_format.left_indent = Cm(0.9); p.paragraph_format.first_line_indent = Cm(-0.6)
        add_inline(p, f'{b[1]}. {b[2]}')
    elif k == 'q':
        p = doc.add_paragraph(); shade(p); add_inline(p, b[1], 9.5); p.paragraph_format.left_indent = Cm(0.3)
    elif k == 'e':
        ec += 1
        p = doc.add_paragraph(); pf = p.paragraph_format
        pf.tab_stops.add_tab_stop(Cm(TEXT_W / 2), WD_TAB_ALIGNMENT.CENTER); pf.tab_stops.add_tab_stop(Cm(TEXT_W - 0.2), WD_TAB_ALIGNMENT.RIGHT)
        pf.space_before = Pt(4); pf.space_after = Pt(6); pf.line_spacing = 1.0
        p.add_run('\t')
        if MODE == 'omml':
            p._p.append(omml(b[1]))
            p.add_run(f'\t({chap}-{ec})')
        else:
            png = os.path.join(HERE, 'eq', f'eq_{chap}_{ec}.png'); eq_png(b[1], png)
            im = Image.open(png); wcm = min(im.width / 300 * 2.54, TEXT_W - 2.4); hcm = wcm * im.height / im.width
            p.add_run().add_picture(png, width=Cm(wcm))
            nr = p.add_run(f'\t({chap}-{ec})')
            rpr = nr._r.get_or_add_rPr(); pos = OxmlElement('w:position'); pos.set(qn('w:val'), str(int(hcm / 2.54 * 72 - 8))); rpr.append(pos)
    elif k == 't':
        tc += 1
        cap = doc.add_paragraph(style='表题'); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER; keep_next(cap)
        cap.paragraph_format.space_before = Pt(6)
        cap.add_run(f'表 {chap}-{tc} {b[1]}')
        rows = b[2]; ncol = len(rows[0])
        rows = [r + [''] * (ncol - len(r)) if len(r) < ncol else r[:ncol] for r in rows]
        tb = doc.add_table(rows=len(rows), cols=ncol); tb.style = 'Table Grid'; tb.alignment = WD_TABLE_ALIGNMENT.CENTER
        # column widths by content length
        lens = [max(3, 0.5 * sum(len(r[c]) for r in rows) / len(rows) + 0.5 * min(40, max(len(r[c]) for r in rows))) for c in range(ncol)]
        tot = sum(lens); widths = [TEXT_W * l / tot for l in lens]
        mn = 1.6 if ncol <= 6 else 1.2
        widths = [max(mn, w) for w in widths]; s = sum(widths); widths = [w * TEXT_W / s for w in widths]
        fs = 9 if ncol <= 5 else (8.5 if ncol <= 7 else 7.5)
        for ri, r in enumerate(rows):
            for ci, txt in enumerate(r):
                cell = tb.cell(ri, ci); cell.width = Cm(widths[ci])
                cp = cell.paragraphs[0]; cp.paragraph_format.space_after = Pt(0); cp.paragraph_format.line_spacing = 1.1
                cp.paragraph_format.first_line_indent = Pt(0)
                add_inline(cp, txt, fs, None, ri == 0)
                if ri == 0: set_cell_bg(cell, 'D9E2F3')
        fix_widths(tb, widths)
        trPr = tb.rows[0]._tr.get_or_add_trPr(); trPr.append(parse_xml('<w:tblHeader xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))
        for row in tb.rows:
            row._tr.get_or_add_trPr().append(parse_xml('<w:cantSplit xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'))
        sp = doc.add_paragraph(); sp.paragraph_format.space_after = Pt(2)
    elif k == 'f':
        fc += 1
        path = prep_image(b[2])
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; keep_next(p); p.paragraph_format.first_line_indent = Pt(0)
        im = Image.open(path); w = TEXT_W if not b[2].startswith('/') else 15.0
        hcm = w * im.height / im.width
        if hcm > 13.5: w = w * 13.5 / hcm
        p.add_run().add_picture(path, width=Cm(w))
        cap = doc.add_paragraph(style='图题'); cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.add_run(f'图 {chap}-{fc} {b[1]}')
        if b[3]:
            keep_next(cap)
            n = doc.add_paragraph(); n.alignment = WD_ALIGN_PARAGRAPH.CENTER; add_inline(n, '注：' + b[3], 8.5, '666666')
            n.paragraph_format.space_after = Pt(8)

# strip theme font attributes so explicit fonts win (avoid Calibri/Carlito fallbacks)
for el in doc.styles.element.iter(qn('w:rFonts')):
    for a in ('w:asciiTheme','w:hAnsiTheme','w:eastAsiaTheme','w:cstheme'):
        if el.get(qn(a)) is not None: del el.attrib[qn(a)]
    for a in ('w:ascii','w:hAnsi','w:eastAsia','w:cs'):
        if el.get(qn(a)) in (None,'Calibri','Calibri Light','Cambria','Times New Roman','MS Mincho','MS Gothic'): el.set(qn(a), SERIF)
rd = doc.styles.element.find(qn('w:docDefaults'))
if rd is not None:
    for el in rd.iter(qn('w:rFonts')):
        for a in ('w:ascii','w:hAnsi','w:eastAsia','w:cs'): el.set(qn(a), SERIF)
# settings: update fields on open (Word refreshes TOC/LOF/LOT/SEQ)
settings = doc.settings.element
settings.insert_element_before(parse_xml('<w:updateFields xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:val="true"/>'),
    'w:hdrShapeDefaults','w:footnotePr','w:endnotePr','w:compat','w:docVars','w:rsids','m:mathPr','w:attachedSchema','w:themeFontLang','w:clrSchemeMapping','w:doNotIncludeSubdocsInStats','w:doNotAutoCompressPictures','w:forceUpgrade','w:captions','w:readModeInkLockDown','w:smartTagType','w:shapeDefaults','w:doNotEmbedSmartTags','w:decimalSymbol','w:listSeparator')
cp = doc.core_properties
cp.title = f'{TITLE} 产品功能设计说明'; cp.subject = '产品功能设计说明'; cp.author = 'sim-agent 产品文档'; cp.language = 'zh-CN'
cp.keywords = 'sim-agent; 产品功能设计; 算电热碳'
doc.save(OUT)
json.dump({'headings': [t for _, t in headings], 'figs': figs, 'tabs': tabs}, open(os.path.join(HERE, 'entries.json'), 'w'), ensure_ascii=False, indent=1)
print('saved', OUT, len(headings), len(figs), len(tabs))
