#!/usr/bin/env python3
"""
Meta分析/系统综述 纳入文献提取工具
=====================================
从系统综述PDF中提取"正式纳入研究"的第一作者、DOI、文章标题。
DOI 通过 OpenAlex API 验证（绿色=已验证，红色=未找到）。
顺序严格按原文表格页面顺序。

用法:
    python extract_included_studies.py <PDF路径> [--refs refs.json]

要求: pip install pymupdf xlsxwriter openpyxl pandas requests
"""

import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import re
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
import concurrent.futures
import argparse
from pathlib import Path

try:
    import fitz
except ImportError:
    print("[错误] 请先安装 pymupdf: pip install pymupdf")
    sys.exit(1)

try:
    import xlsxwriter
except ImportError:
    print("[错误] 请先安装 xlsxwriter: pip install xlsxwriter")
    sys.exit(1)


# ============================================================
# 核心函数
# ============================================================

def extract_ref_texts(pdf_path, ref_start_page, ref_end_page):
    """从 PDF 参考文献页提取每条参考文献的完整文本。返回 {ref_num: text}。"""
    doc = fitz.open(pdf_path)
    ref_map = {}

    for pg in range(ref_start_page, min(ref_end_page, doc.page_count)):
        page = doc[pg]
        lines = []
        for l in page.get_text("text").split('\n'):
            ls = l.strip()
            if not ls:
                continue
            if ls.startswith('Int. J.'):
                continue
            if re.match(r'^\d+\s+of\s+\d+$', ls):
                continue
            lines.append(ls)
        text = '\n'.join(lines)

        parts = re.split(r'\n(?=\d{1,3}\.\s)', text)
        for part in parts:
            m = re.match(r'(\d+)\.\s*(.+)', part, re.DOTALL)
            if not m:
                continue
            ref_num = int(m.group(1))
            body = re.sub(r'\s+', ' ', m.group(2).strip())
            if body and len(body) >= 30:
                ref_map[ref_num] = body

    doc.close()
    return ref_map


def extract_dois(pdf_path, ref_start, ref_end):
    """从 PDF CrossRef 链接提取 DOI，按页面顺序匹配到引用编号。"""
    doc = fitz.open(pdf_path)
    all_dois = []  # (pg, y, doi)

    for pg in range(ref_start, min(ref_end, doc.page_count)):
        page = doc[pg]
        for link in page.get_links():
            uri = link.get('uri', '')
            if 'doi.org' in uri:
                m = re.search(r'doi\.org/(10\.\S+)', uri)
                if m:
                    doi = m.group(1).rstrip('.,;')
                    rect = link.get('from', None)
                    y = (rect.y0 + rect.y1) / 2 if rect else 0
                    all_dois.append((pg, y, doi))

    all_dois.sort(key=lambda x: (x[0], x[1]))

    ref_doi = {}
    for pg in range(ref_start, min(ref_end, doc.page_count)):
        page = doc[pg]
        text = page.get_text("text")

        page_refs = []
        for line in text.split('\n'):
            m = re.match(r'^\s*(\d+)\.\s', line.strip())
            if m:
                r = int(m.group(1))
                if r not in page_refs:
                    page_refs.append(r)

        page_dois = [(p, y, d) for (p, y, d) in all_dois if p == pg]

        # 能一一对应的优先
        if abs(len(page_refs) - len(page_dois)) <= 2:
            count = min(len(page_refs), len(page_dois))
            for i in range(count):
                ref_doi[page_refs[i]] = page_dois[i][2]
        else:
            # 用 y 坐标匹配
            blocks = page.get_text("blocks")
            for ref in page_refs:
                ref_y = None
                for b in blocks:
                    if re.match(rf'^\s*{ref}\.\s', b[4].strip()):
                        ref_y = (b[1] + b[3]) / 2
                        break
                if ref_y and page_dois:
                    best = min(page_dois, key=lambda d: abs(d[1] - ref_y))
                    if abs(best[1] - ref_y) < 100:
                        ref_doi[ref] = best[2]

    doc.close()
    return ref_doi


def parse_ref(text):
    """解析参考文献文本，返回 (first_author, title, year)。"""
    yr_m = re.search(r'(\d{4})[,;]?\s+\d+[\s,\-]', text)
    year = yr_m.group(1) if yr_m else ''
    jp = yr_m.start() if yr_m else len(text)
    before = text[:jp].strip()

    segs = before.split('. ')
    ts = 0
    for i, s in enumerate(segs):
        if re.search(r'[A-Z][a-z]+,\s+[A-Z]\.', s):
            ts = i + 1
        elif re.search(r'[A-Z]\.[A-Z]\.', s):
            ts = i + 1
        elif re.search(r'et\s+al\.?\s*$', s, re.I):
            ts = i + 1
        elif i > 0 and len(s) > 60 and ';' not in s:
            break

    title = '. '.join(segs[ts:]).strip()
    title = re.sub(r'\.\s*$', '', title)

    fa = segs[0].split(',')[0].split(';')[0].strip()
    fa = re.sub(r'^et\s+al\.?\s*', '', fa, flags=re.I)
    fa = re.sub(r'^\d+\.?\s*', '', fa)

    return fa, title, year


def verify_dois(doi_list):
    """通过 OpenAlex API 批量验证 DOI。"""
    def verify_one(doi):
        try:
            url = (f"https://api.openalex.org/works/doi:{doi}"
                   f"?select=title,publication_year,authorships")
            req = urllib.request.Request(url, headers={'User-Agent': 'meta-trace'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read().decode())
                t = d.get('title', '')
                y = d.get('publication_year', '')
                fa = ''
                au = d.get('authorships', [])
                if au:
                    fa = au[0].get('author', {}).get('display_name', '')
                return doi, t, fa, str(y) if y else ''
        except Exception:
            return doi, '', '', ''

    verified = {}
    done = 0
    print(f"  [OpenAlex] 验证 {len(doi_list)} 个 DOI...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(verify_one, d): d for d in doi_list}
        for f in concurrent.futures.as_completed(futures):
            doi, t, fa, yr = f.result()
            if t:
                verified[doi] = {'title': t, 'first_author': fa, 'year': yr}
            done += 1
            if done % 10 == 0:
                print(f"    {done}/{len(doi_list)}...")
    return verified


def search_crossref(missing):
    """对缺失的 DOI 用 CrossRef API 搜索。返回 {ref_num: doi}。"""
    found = {}
    for ref_num, ref_text in missing:
        kws = urllib.parse.quote(ref_text[:200].replace(' ', '+'))
        try:
            url = f"https://api.crossref.org/works?query={kws}&rows=3&select=DOI,title,issued"
            req = urllib.request.Request(url, headers={'User-Agent': 'meta-trace'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            best_d, best_s = None, 0
            for item in data.get('message', {}).get('items', []):
                dt = item.get('title', [''])[0].lower()
                iy = item.get('issued', {}).get('date-parts', [[0]])[0][0]
                rw = set(w.lower() for w in ref_text.split() if len(w) > 3)
                dw = set(w.lower() for w in dt.split() if len(w) > 3)
                s = len(rw & dw) / max(len(rw), 1)
                if s > best_s and s > 0.15:
                    best_s = s
                    best_d = item.get('DOI', '')
            if best_d:
                found[ref_num] = best_d
                print(f"    [ref{ref_num}] CrossRef -> {best_d}")
            time.sleep(1)
        except Exception as e:
            print(f"    [ref{ref_num}] CrossRef 失败: {e}")
    return found


def build_excel(rows, out_path, config):
    """生成带颜色的 Excel。"""
    wb = xlsxwriter.Workbook(out_path)
    NAVY, GBG, GTX = '#1A365D', '#C6EFCE', '#006100'
    RBG, RTX = '#FFC7CE', '#9C0006'

    def mkfmt(bg, fg, **kw):
        base = {'font_size': 10, 'border': 1, 'text_wrap': True, 'valign': 'top',
                'bg_color': bg, 'font_color': fg}
        base.update(kw)
        return wb.add_format(base)

    gf = mkfmt(GBG, GTX)
    rf = mkfmt(RBG, RTX)
    gno = mkfmt(GBG, GTX, align='center')
    rno = mkfmt(RBG, RTX, align='center')
    gdoi = mkfmt(GBG, GTX, font_name='Consolas', font_size=9)
    rdoi = mkfmt(RBG, RTX, font_name='Consolas', font_size=9, italic=True)
    hdr_f = wb.add_format({'bold': True, 'font_size': 11, 'bg_color': NAVY,
                           'font_color': 'white', 'border': 1, 'text_wrap': True,
                           'valign': 'vcenter', 'align': 'center'})
    tif = wb.add_format({'bold': True, 'font_size': 15, 'font_color': NAVY})
    suf = wb.add_format({'font_size': 10, 'font_color': '#888888', 'italic': True})

    green_n = sum(1 for r in rows if r['is_green'])

    # ---- Sheet 1 ----
    ws = wb.add_worksheet('Included Studies')
    ptitle = config.get('paper_title', 'Systematic Review / Meta-Analysis')
    pcitation = config.get('paper_citation', '')
    ws.merge_range(0, 0, 0, 3, f'{ptitle} -- Included Studies (N={len(rows)})', tif)
    ws.set_row(0, 30)
    st = f'DOIs verified: {green_n}/{len(rows)} via OpenAlex'
    if pcitation:
        st = f'{pcitation} | {st}'
    ws.merge_range(1, 0, 1, 3, st, suf)
    ws.set_row(1, 18)

    for j, (h, w) in enumerate([('No.', 5), ('First Author', 20), ('DOI', 30), ('Title', 85)]):
        ws.write(2, j, h, hdr_f)
        ws.set_column(j, j, w)
    ws.set_row(2, 30)
    ws.freeze_panes(3, 0)

    for i, r in enumerate(rows):
        row = i + 3
        c, n, d = (gf, gno, gdoi) if r['is_green'] else (rf, rno, rdoi)
        ws.write(row, 0, r['no'], n)
        ws.write(row, 1, r['first_author'], c)
        ws.write(row, 2, f"https://doi.org/{r['doi']}" if r['doi'] else 'DOI NOT FOUND', d)
        ws.write(row, 3, r['title'], c)
        ws.set_row(row, 52 if len(r.get('title', '')) < 120 else 68)
    ws.autofilter(2, 0, len(rows) + 2, 3)

    # ---- Sheet 2: groups if provided ----
    eg = config.get('effect_groups')
    if eg:
        ws2 = wb.add_worksheet('By Effect Direction')
        ws2.merge_range(0, 0, 0, 4, 'Studies by Effect Direction', tif)
        ws2.set_row(0, 28)
        for j, w in enumerate([5, 20, 30, 10, 85]):
            ws2.set_column(j, j, w)
        colors = ['#C6EFCE', '#FFC7CE', '#FFEB9C', '#D6E4F0', '#E8DAEF']
        row2 = 2
        for idx, (label, ref_set) in enumerate(eg.items()):
            bg = colors[idx % len(colors)]
            sub = [r for r in rows if r['ref'] in ref_set]
            if not sub:
                continue
            gh = wb.add_format({'bold': True, 'font_size': 11, 'bg_color': bg,
                                'font_color': '#333', 'border': 1, 'text_wrap': True})
            gc = wb.add_format({'font_size': 10, 'border': 1, 'bg_color': bg,
                                'text_wrap': True, 'valign': 'top'})
            gn = wb.add_format({'font_size': 10, 'border': 1, 'bg_color': bg,
                                'align': 'center', 'valign': 'top'})
            ws2.merge_range(row2, 0, row2, 4, f'{label} ({len(sub)} studies)', gh)
            ws2.set_row(row2, 24)
            row2 += 1
            for r in sub:
                ws2.write(row2, 0, r['no'], gn)
                ws2.write(row2, 1, r['first_author'], gc)
                ws2.write(row2, 2, f"https://doi.org/{r['doi']}" if r['doi'] else 'NOT FOUND', gc)
                ws2.write(row2, 3, r.get('year', ''), gn)
                ws2.write(row2, 4, r['title'], gc)
                ws2.set_row(row2, 42)
                row2 += 1
            row2 += 1

    # ---- Sheet 3: RED items ----
    ws3 = wb.add_worksheet('Missing DOIs')
    ws3.merge_range(0, 0, 0, 3, 'Missing DOIs -- Manual Lookup Required', tif)
    ws3.set_row(0, 28)
    for j, w in enumerate([5, 20, 85, 10]):
        ws3.set_column(j, j, w)
    reds = [r for r in rows if not r['is_green']]
    for i, r in enumerate(reds):
        ws3.write(i + 2, 0, r['no'], rno)
        ws3.write(i + 2, 1, r['first_author'], rf)
        ws3.write(i + 2, 2, r['title'], rf)
        ws3.write(i + 2, 3, r.get('year', ''), rno)
        ws3.set_row(i + 2, 45)

    wb.close()
    return green_n, len(rows) - green_n


# ============================================================
# 主流程
# ============================================================

def main():
    p = argparse.ArgumentParser(description='系统综述纳入文献提取：第一作者+DOI+标题')
    p.add_argument('pdf', help='PDF 文件路径')
    p.add_argument('--refs', '-r', help='纳入文献引用编号列表 (JSON文件)')
    p.add_argument('--output', '-o', help='输出 Excel 路径')
    p.add_argument('--ref-pages', help='参考文献页码范围, 如 38-41')
    p.add_argument('--title', help='论文标题 (用于Excel表头)')
    p.add_argument('--citation', help='论文引用 (用于Excel副标题)')
    args = p.parse_args()

    if not os.path.exists(args.pdf):
        print(f"[错误] 找不到文件: {args.pdf}")
        sys.exit(1)

    # 输出路径
    out = args.output
    if not out:
        oname = Path(args.pdf).stem
        odir = os.path.join(os.path.dirname(args.pdf) or '.', 'output')
        os.makedirs(odir, exist_ok=True)
        out = os.path.join(odir, f'{oname}_extracted.xlsx')

    # 参考文献页码范围
    ref_start, ref_end = 37, 41  # 默认
    if args.ref_pages:
        parts = [int(x) for x in args.ref_pages.split('-')]
        ref_start = parts[0] - 1
        ref_end = parts[1]

    print(f"[输入] {args.pdf}")
    print(f"[输出] {out}")
    print(f"[参考文献页] {ref_start+1}-{ref_end}")

    # (1) 提取参考文献文本
    print("\n[1/5] 提取参考文献文本...")
    ref_texts = extract_ref_texts(args.pdf, ref_start, ref_end)
    print(f"  共提取 {len(ref_texts)} 条")

    # (2) 提取 DOI
    print("\n[2/5] 提取 DOI...")
    doi_map = extract_dois(args.pdf, ref_start, ref_end)
    print(f"  共提取 {len(doi_map)} 个 DOI")

    # (3) 确定纳入研究列表
    print("\n[3/5] 确定纳入研究列表...")
    if args.refs:
        with open(args.refs, 'r', encoding='utf-8') as f:
            study_refs = json.load(f)
        print(f"  从文件读入 {len(study_refs)} 个引用编号")
    else:
        # 自动检测：从 DOI 映射中取所有编号
        study_refs = sorted(doi_map.keys())
        if not study_refs:
            study_refs = sorted(ref_texts.keys())
        print(f"  自动检测 {len(study_refs)} 个引用编号")

    if not study_refs:
        print("[错误] 未检测到纳入研究。请用 --refs 手动指定。")
        sys.exit(1)

    # (4) 解析 + 验证 DOI
    print("\n[4/5] 解析参考文献并验证 DOI...")
    dois_to_verify = list(set(doi_map.values()))
    verified = verify_dois(dois_to_verify)

    rows = []
    missing_pairs = []
    for seq, ref in enumerate(study_refs, 1):
        rt = ref_texts.get(ref, '')
        fa, title, year = parse_ref(rt) if rt else (f'[ref {ref}]', '', '')
        doi = doi_map.get(ref, '')
        # 绿色只代表「经 OpenAlex 验证」。原先 elif doi: is_green = True 会把
        # 仅从 PDF 链接里抓到、但 API 查不到的 DOI 也标绿，与表头说明自相矛盾。
        verified_flag = bool(doi and doi in verified)
        is_green = verified_flag

        if verified_flag:
            v = verified[doi]
            if v.get('first_author') and len(v['first_author']) > 2:
                fa = v['first_author']
            if v.get('title') and len(v['title']) > 10:
                title = v['title']
            if v.get('year'):
                year = v['year']
        else:
            missing_pairs.append((ref, rt))

        rows.append({
            'no': seq, 'ref': ref, 'first_author': fa, 'doi': doi,
            'title': title, 'year': year, 'is_green': is_green,
        })

    if missing_pairs:
        print(f"  CrossRef 搜索 {len(missing_pairs)} 个缺失 DOI...")
        found = search_crossref(missing_pairs)
        for r in rows:
            if not r['is_green'] and r['ref'] in found:
                r['doi'] = found[r['ref']]
                r['is_green'] = True

    gn = sum(1 for r in rows if r['is_green'])
    rn = sum(1 for r in rows if not r['is_green'])
    print(f"\n  [OK] DOI 已验证: {gn}/{len(rows)}")
    print(f"  [MISS] DOI 未找到: {rn}/{len(rows)}")
    for r in rows:
        if not r['is_green']:
            print(f"    ref{r['ref']}: {r['first_author']} -- {r['title'][:80]}")

    # (5) 保存 JSON 数据
    json_out = os.path.join(os.path.dirname(out), 'extracted_data.json')
    print(f"\n[5/5] 保存 JSON: {json_out}")
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    # (6) 生成 Excel
    print(f"\n[6/6] 生成 Excel: {out}")
    config = {}
    if args.title:
        config['paper_title'] = args.title
    if args.citation:
        config['paper_citation'] = args.citation
    gn2, rn2 = build_excel(rows, out, config)

    print(f"\n{'='*60}")
    print(f"[OK] 完成!")
    print(f"  Total: {len(rows)}")
    print(f"  GREEN (DOI verified): {gn2}")
    print(f"  RED (DOI missing): {rn2}")
    if rn2 > 0:
        print(f"  See Sheet 'Missing DOIs' for manual lookup list")
    print(f"  Output: {out}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
