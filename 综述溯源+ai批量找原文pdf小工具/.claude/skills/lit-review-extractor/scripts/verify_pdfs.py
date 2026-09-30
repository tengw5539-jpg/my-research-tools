#!/usr/bin/env python3
"""
Module 2 PDF Verification -- production-grade cross-check
=========================================================
Scans all output/*/pdfs/ directories, matches each PDF to its record
via DOI extraction + title-keyword + author-name matching.
Handles scanned papers (image-only PDFs with no text layer).

Exit 0 = all clear, Exit 1 = need fixing.
"""
import os, sys, re, json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import fitz
import common

if not common.OUTPUT_DIR.exists():
    print('[FATAL] Cannot find output/ directory')
    sys.exit(2)

OUTPUT = common.OUTPUT_DIR
ISSUES = []

def issue(level, paper, ref, msg):
    ISSUES.append({'level': level, 'paper': paper, 'ref': ref, 'msg': msg})
    tag = {'CRITICAL': '!!!', 'ERROR': '!!', 'WARNING': '!', 'INFO': '  '}.get(level, '?')
    if level != 'INFO':
        print(f'  {tag} [{level}] {msg}')

def extract_doi(text, max_chars=12000):
    if not text: return None
    for pat in [r'10[.]\d{4,}/[^\s)}\]<>]{5,60}', r'doi[:\s]*(10[.]\d{4,}/[^\s]{5,60})',
                r'doi[.]org/(10[.]\d{4,}/[^\s]{5,60})', r'DOI[:\s]+(10[.]\d{4,}/[^\s]{5,60})']:
        m = re.search(pat, text[:max_chars], re.I)
        if m:
            g = m.group(1) if m.lastindex else m.group(0)
            return g.rstrip('.,;)}]').lower()
    return None

def keywords(s, min_len=6):
    stops = {'that','this','with','from','have','been','were','they','their','which',
             'about','these','those','into','than','also','after','between','other',
             'introduction','methods','results','discussion','conclusion','abstract',
             'should','could','would','during','among','older','using','being'}
    return {w for w in re.findall(fr'[a-zA-Z]{{{min_len},}}', s.lower()) if w not in stops}

def match_score(rec, pdf_file, pdf_text):
    """Score record-PDF match. Returns (score, method).

    原先拿「文件名 vs 记录标题」做匹配 —— 而文件名正是由下载脚本按同一条纪录
    生成的，等于自己证明自己，永远匹配不上"下错文献"的情况。
    现改为对 PDF 正文做作者 / 标题关键词比对；仅当无文本层（扫描版）时
    才退回文件名信号。
    """
    author = (rec.get('first_author', '') or '').strip().lower().replace(',', '').replace(' ', '')
    rec_doi = common.clean_doi(rec.get('doi', ''))
    title = (rec.get('title', '') or '').lower()

    # DOI match (gold standard)
    if common.doi_match(common.extract_doi(pdf_text), rec_doi, 25):
        return (10, 'doi')

    if len((pdf_text or '').strip()) < 50:
        # 扫描版：无正文可用，只能退化到文件名信号
        fa = pdf_file.split('_')[0].lower().replace('-', '')
        return (4, 'scanned') if author[:4] and author[:4] in fa else (0, 'none')

    head = pdf_text[:8000].lower()
    score = 0

    # 作者姓氏是否出现在正文前部
    author_parts = [w for w in re.findall(r'[a-z]{3,}', author)]
    if author_parts and any(p in head for p in author_parts[-2:]):
        score += 4

    # 标题实义词的命中比例
    tw = keywords(title, 6)
    if tw:
        hits = sum(1 for w in tw if w in head)
        ratio = hits / len(tw)
        if ratio >= 0.6:
            score += 6
        elif ratio >= 0.35:
            score += 4
        elif ratio >= 0.2:
            score += 2

    if score >= 7: return (score, 'strong')
    if score >= 4: return (score, 'ok')
    if score >= 2: return (score, 'loose')
    return (score, 'none')

# ========== Main ==========
papers = []
for d in sorted(os.listdir(str(OUTPUT))):
    fd = OUTPUT / d
    if not fd.is_dir(): continue
    jp = fd / 'extracted_data.json'
    pd = fd / 'pdfs'
    if jp.exists() and pd.is_dir(): papers.append((d, str(fd), str(jp), str(pd)))

if not papers:
    print('No papers found under output/')
    sys.exit(0)

grand_ok = 0
for dirname, dirpath, jpath, pdfpath in papers:
    with open(jpath, encoding='utf-8') as f: records = json.load(f)
    pdfs = sorted(os.listdir(pdfpath))
    ref2r = {r['ref']: r for r in records}

    print(f'\n--- {dirname[:60]} ({len(records)} recs, {len(pdfs)} PDFs) ---')

    if len(pdfs) != len(records):
        issue('ERROR', dirname, '--', f'Count: {len(pdfs)} PDFs vs {len(records)} records')

    # Score every PDF against every record
    scored = {}  # pdf_file -> [(ref, score, method)]
    for pf in pdfs:
        pp = os.path.join(pdfpath, pf)
        sz = os.path.getsize(pp)
        if sz < 5000:
            issue('CRITICAL', dirname, pf, f'{sz}b too small')
            continue
        try:
            doc = fitz.open(pp)
            if doc.page_count == 0:
                issue('CRITICAL', dirname, pf, '0 pages'); doc.close(); continue
            text = ''
            for i in range(doc.page_count): text += doc[i].get_text()
            doc.close()
        except Exception as e:
            issue('CRITICAL', dirname, pf, str(e)[:40]); continue

        s = []
        for r in records:
            sc, mt = match_score(r, pf, text)
            if sc > 0: s.append((r['ref'], sc, mt))
        s.sort(key=lambda x: -x[1])
        if s: scored[pf] = s

    # Greedy assign best match
    used_pdfs, used_refs = set(), set()
    for pf, scores in sorted(scored.items(), key=lambda x: -x[1][0][1]):
        for ref, score, method in scores:
            if ref not in used_refs and pf not in used_pdfs:
                used_refs.add(ref); used_pdfs.add(pf)
                grand_ok += 1
                if method == 'loose':
                    issue('WARNING', dirname, ref, f'Loose match -> {pf[:50]}')
                break

    unmatched_r = sorted(set(r['ref'] for r in records) - used_refs)
    for ref in unmatched_r:
        r = ref2r[ref]
        issue('ERROR', dirname, ref, f'NO PDF: {r.get("first_author","?")} DOI={r.get("doi","")}')
    unmatched_p = sorted(set(pdfs) - used_pdfs)
    for pf in unmatched_p:
        issue('WARNING', dirname, pf.split('_')[0], f'Extra PDF: {pf[:50]}')
    for pf in pdfs:
        if pf in used_pdfs and os.path.getsize(os.path.join(pdfpath, pf)) < 15000:
            issue('WARNING', dirname, pf.split('_')[0], f'Small PDF {os.path.getsize(os.path.join(pdfpath,pf))//1024}KB: {pf[:50]}')

    paper_ok = len(used_refs)
    print(f'  Result: {paper_ok}/{len(records)} matched')

print(f'\n{"="*50}')
lvl = {}
for i in ISSUES: lvl[i['level']] = lvl.get(i['level'], 0) + 1
for k in ['CRITICAL','ERROR','WARNING','INFO']:
    if k in lvl: print(f'{k}: {lvl[k]}')
print(f'PDFs verified: {grand_ok}')
if lvl.get('CRITICAL',0) + lvl.get('ERROR',0) > 0:
    print(f'\n>>> {lvl.get("CRITICAL",0)+lvl.get("ERROR",0)} issues -- FIX BEFORE SUBMITTING <<<')
    sys.exit(1)
else:
    print('\n>>> ALL CHECKS PASSED <<<')
    sys.exit(0)
