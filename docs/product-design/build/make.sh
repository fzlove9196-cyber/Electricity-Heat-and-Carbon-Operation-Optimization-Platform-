#!/usr/bin/env bash
# Two-pass build: DOCX (editable OMML) + PDF (from image-equation variant; LibreOffice here lacks the Math module)
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python; OUTD=../deliverables; NAME="sim-agent_产品功能设计说明_2026-11-10"
TMP=$(mktemp -d)
$PY build_docx.py img "$TMP/pdfsrc.docx"
soffice --headless --convert-to pdf --outdir "$TMP" "$TMP/pdfsrc.docx" >/dev/null 2>&1
$PY find_pages.py "$TMP/pdfsrc.pdf" pages.json
$PY build_docx.py img "$TMP/pdfsrc.docx" pages.json
soffice --headless --convert-to pdf --outdir "$TMP" "$TMP/pdfsrc.docx" >/dev/null 2>&1
$PY find_pages.py "$TMP/pdfsrc.pdf" pages_check.json
cmp <(python3 -c "import json;print(json.load(open('pages.json'))['items'])") <(python3 -c "import json;print(json.load(open('pages_check.json'))['items'])") && echo "page numbers stable"
$PY build_docx.py omml "$OUTD/$NAME.docx" pages.json
cp "$TMP/pdfsrc.pdf" "$OUTD/$NAME.pdf"
cp "$TMP/pdfsrc.docx" ./pdf_variant_equation_images.docx
rm -rf "$TMP"; ls -la "$OUTD"
