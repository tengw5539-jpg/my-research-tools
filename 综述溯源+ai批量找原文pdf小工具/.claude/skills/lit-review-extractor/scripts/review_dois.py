#!/usr/bin/env python3
import sys
sys.stdout.reconfigure(encoding='utf-8')
"""
纳入文献 DOI 审查工具
=====================
在生成 Excel 后运行，自动检测常见错误：
  1. 同一 DOI 分配给多篇文献
  2. 同一作者同年多篇论文的 DOI 混淆
  3. DOI 指向错误论文（标题关键词不匹配）
  4. 单作者论文被遗漏
  5. 作者名字异常（含表头文本、过短等）
  6. 标题与参考文献原文差异过大

用法:
    python review_dois.py <Excel路径> <PDF路径> [--ref-pages 38-41]

输出: 审查报告，标注每个问题的严重级别和修复建议
"""

import re, json, os, time, urllib.request, urllib.error, concurrent.futures, argparse
from pathlib import Path

try:
    import fitz
except ImportError:
    print("[Error] pip install pymupdf")
    sys.exit(1)

# ============================================================
# 从 PDF 提取参考文献原文
# ============================================================

def extract_ref_texts(pdf_path, ref_start, ref_end):
    doc = fitz.open(pdf_path)
    ref_map = {}
    for pg in range(ref_start, min(ref_end, doc.page_count)):
        page = doc[pg]
        lines = [l.strip() for l in page.get_text("text").split('\n') if l.strip()
                 and not l.startswith('Int. J.') and not re.match(r'^\d+\s+of\s+\d+$', l)]
        text = '\n'.join(lines)
        parts = re.split(r'\n(?=\d{1,3}\.\s)', text)
        for part in parts:
            m = re.match(r'(\d+)\.\s*(.+)', part, re.DOTALL)
            if not m: continue
            ref_map[int(m.group(1))] = re.sub(r'\s+', ' ', m.group(2).strip())
    doc.close()
    return ref_map

def parse_ref_first_author(text):
    """Extract first author surname from reference text."""
    m = re.search(r'(\d{4})[,;]?\s+\d+[\s,\-]', text)
    border = m.start() if m else len(text)
    before = text[:border].strip()
    seg = before.split('. ')[0]
    fa = seg.split(',')[0].split(';')[0].strip()
    fa = re.sub(r'^et\s+al\.?\s*', '', fa, flags=re.I)
    fa = re.sub(r'^\d+\.?\s*', '', fa)
    return fa

# ============================================================
# 审查规则
# ============================================================

issues = []

def add_issue(level, title, detail, fix):
    issues.append({'level': level, 'title': title, 'detail': detail, 'fix': fix})

# ============================================================
# 规则1: DOI 唯一性检查
# ============================================================

def check_doi_uniqueness(rows):
    doi_count = {}
    for r in rows:
        d = r.get('doi', '')
        if d:
            doi_count.setdefault(d, []).append(r['ref'])
    for doi, refs in doi_count.items():
        if len(refs) > 1:
            add_issue(
                'CRITICAL', f'同一 DOI 分配给 {len(refs)} 篇不同文献',
                f'DOI {doi} 同时分配给 refs {refs}。同一 DOI 不可能属于两篇不同论文。',
                f'逐篇在 CrossRef 中搜索标题，确认哪篇真正拥有此 DOI，为另一篇重新搜索。'
            )

# ============================================================
# 规则2: 同作者同年多篇论文
# ============================================================

def check_same_author_year(rows):
    groups = {}
    for r in rows:
        fa = r.get('first_author', '').strip()
        yr = r.get('year', '')
        if fa and yr:
            key = f'{fa} {yr}'
            groups.setdefault(key, []).append(r)

    for key, group in groups.items():
        if len(group) > 1:
            refs = [r['ref'] for r in group]
            dois = [r['doi'] for r in group]
            titles = [r['title'][:80] for r in group]
            add_issue(
                'WARNING', f'同作者同年 {len(group)} 篇论文: {key}',
                f'refs {refs}\n  标题: ' + '\n  标题: '.join(titles),
                f'确认每篇 DOI 是否与论文主题对应（如 OZONE vs NO2）。如主题相似，对比全文确认无误。'
            )

# ============================================================
# 规则3: 单作者论文检查
# ============================================================

def check_single_author(rows, ref_texts):
    for r in rows:
        ref = r['ref']
        rt = ref_texts.get(ref, '')
        if rt and 'et al.' not in rt:
            # Single author paper - verify it's not a false detection
            fa = parse_ref_first_author(rt)
            if len(fa) < 2 or re.search(r'main\s+findings', fa, re.I):
                add_issue(
                    'ERROR', f'ref {ref}: 疑似单作者论文提取失败',
                    f'参考文献原文不含 "et al."，解析出的第一作者为空或异常: "{fa}"',
                    f'从原文手动读取: {rt[:150]}...'
                )

# ============================================================
# 规则4: 作者名异常检测
# ============================================================

BAD_AUTHOR_PATTERNS = [
    (r'^main\s+findings', '含 PDF 页眉 "Main Findings"'),
    (r'^benefits?\s+of', '含 PDF 页眉 "Benefits of"'),
    (r'^risks?\s+of', '含 PDF 页眉 "Risks of"'),
    (r'^pollutants?\s+during', '含 PDF 页眉 "Pollutants during"'),
    (r'^table\s+\d', '含 "Table X" 表头'),
    (r'^yes\s+yes', '含 MDPI 表格数据泄露'),
    (r'^t\s+tell', '含 MDPI 表格数据泄露'),
    (r'^\d+\.?\d*$', '纯数字'),
]

def check_author_names(rows, ref_texts):
    for r in rows:
        fa = r.get('first_author', '').strip()
        for pattern, desc in BAD_AUTHOR_PATTERNS:
            if re.search(pattern, fa, re.I):
                # Try to get correct author from ref text
                rt = ref_texts.get(r['ref'], '')
                correct = parse_ref_first_author(rt) if rt else '?'
                add_issue(
                    'ERROR', f'ref {r["ref"]}: 作者名异常 — {desc}',
                    f'当前值: "{fa}"',
                    f'从参考文献原文提取的正确值: "{correct}"。更新 Excel 中该行的 First Author。'
                )
                break

# ============================================================
# 规则5: 标题-参考文献匹配度
# ============================================================

def check_title_match(rows, ref_texts):
    for r in rows:
        title = r.get('title', '')
        rt = ref_texts.get(r['ref'], '')
        if not title or not rt:
            continue

        # Compare significant keywords
        title_words = set(w.lower() for w in title.split() if len(w) > 3)
        ref_words = set(w.lower() for w in rt.split() if len(w) > 3)
        if not title_words:
            continue

        overlap = len(title_words & ref_words)
        ratio = overlap / len(title_words)

        if ratio < 0.15 and len(title) > 20:
            add_issue(
                'WARNING', f'ref {r["ref"]}: 标题与参考文献原文差异大 (相似度 {ratio:.0%})',
                f'DOI 标题: {title[:120]}\n  原文引用: {rt[:120]}',
                f'在 PubMed/CrossRef 中确认该 DOI 是否真的指向这篇论文。可能需要重新搜索。'
            )

# ============================================================
# 规则6: DOI 有效性检查
# ============================================================

def check_doi_validity(rows):
    """全量 DOI 校验 via OpenAlex。

    原先只抽检 rows[:5] + rows[-5:] + 硬编码的三个 ref（51/64/76，来自某次排错的
    遗留），而 CLAUDE.md / SKILL.md 宣称是"全量检查" —— 名实不符。
    改为全量，并对网络类错误与「OpenAlex 无此 DOI」区分对待（后者才算 ERROR）。
    """
    samples = {r['ref']: r for r in rows}

    def verify_one(ref, the_doi):
        for attempt in range(3):
            try:
                url = f"https://api.openalex.org/works/doi:{the_doi}?select=title,publication_year,authorships"
                req = urllib.request.Request(url, headers={'User-Agent': 'review'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    d = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:            # 限流：退避重试
                    time.sleep(2 * (attempt + 1))
                    continue
                return ref, the_doi, None, '', ''
            except urllib.error.URLError:
                time.sleep(1 + attempt)
                continue
            except Exception:
                return ref, the_doi, None, '', ''
        else:
            return ref, the_doi, None, '', ''     # None = 未能连通（网络问题）

        try:
            title = d.get('title', '')
            year = str(d.get('publication_year', ''))
            fa = ''
            au = d.get('authorships', [])
            if au: fa = au[0].get('author', {}).get('display_name', '')
            return ref, the_doi, title, fa, year
        except Exception:
            return ref, the_doi, None, '', ''

    n = sum(1 for r in samples.values() if r.get('doi'))
    print(f"  [Full-check] 全量校验 {n} 个 DOI via OpenAlex（限流时自动退避）...")
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {}
        for ref, r in samples.items():
            if r.get('doi'):
                futures[ex.submit(verify_one, ref, r['doi'])] = ref
        for f in concurrent.futures.as_completed(futures):
            ref, doi, title, fa, yr = f.result()
            results[ref] = (title, fa, yr)

    for ref, r in samples.items():
        if ref not in results:
            r_doi = r.get('doi', '')
            add_issue(
                'ERROR', f'ref {ref}: DOI 无法通过 OpenAlex 验证',
                f'DOI: {r_doi}',
                f'检查 DOI 格式，或在浏览器中手动访问 https://doi.org/{r_doi}'
            )
            continue

        title, fa, yr = results[ref]
        r_title = r.get('title', '')
        r_fa = r.get('first_author', '')
        r_doi = r.get('doi', '')

        if title is None:
            # None = 请求没连通，不是 DOI 本身无效。降级为 WARNING，避免网络抖动造成误报
            add_issue(
                'WARNING', f'ref {ref}: OpenAlex 请求失败（网络/限流），未能校验',
                f'DOI: {r_doi}',
                f'稍后重跑本脚本；若持续失败再手动访问 https://doi.org/{r_doi}'
            )
            continue

        if not title:
            add_issue(
                'ERROR', f'ref {ref}: DOI 在 OpenAlex 无对应记录',
                f'DOI: {r_doi}',
                f'检查 DOI 格式，或在浏览器中手动访问 https://doi.org/{r_doi}'
            )
            continue

        # Check year match
        if yr and r.get('year') and yr != r['year']:
            add_issue(
                'WARNING', f'ref {ref}: 年份不匹配 — OpenAlex 返回 {yr} vs 预期 {r["year"]}',
                f'DOI: {r_doi}\n  OpenAlex 标题: {title[:120]}',
                f'确认 PDF 参考文献原文年份是否正确。如果年份不同但标题一致，可能论文年份在文中引用与参考文献列表不一致。'
            )

        # Check title keyword overlap
        if title and r_title:
            tw = set(title.lower().split())
            rw = set(r_title.lower().split())
            common = set(w for w in tw & rw if len(w) > 3)
            if len(common) < 3:
                add_issue(
                    'WARNING', f'ref {ref}: DOI 指向的文献标题与 Excel 中的不符',
                    f'OpenAlex: {title[:150]}\n  Excel:   {r_title[:150]}',
                    f'在浏览器中访问 https://doi.org/{r_doi} 确认实际指向的论文。'
                )

# ============================================================
# 主流程
# ============================================================

def main():
    p = argparse.ArgumentParser(description='审查纳入文献 DOI 质量')
    p.add_argument('excel', help='Excel 文件路径 (目前仅支持 JSON，请导出 extracted_data.json)')
    p.add_argument('pdf', help='原始 PDF 路径')
    p.add_argument('--ref-pages', default='38-41', help='参考文献页码范围')
    p.add_argument('--json', help='如果 Excel 不可用，直接用 extracted_data.json')
    args = p.parse_args()

    # 从 JSON 读入数据（支持直接传 JSON 或从 Excel 所在目录找）
    data_path = args.json
    if not data_path:
        json_candidate = os.path.join(os.path.dirname(args.excel), 'extracted_data.json')
        if os.path.exists(json_candidate):
            data_path = json_candidate
        else:
            print("[错误] 需要 extracted_data.json。请先运行 extract_included_studies.py")
            print("  或使用 --json 指定 JSON 文件路径")
            sys.exit(1)

    with open(data_path, 'r', encoding='utf-8') as f:
        rows = json.load(f)

    pp = [int(x) for x in args.ref_pages.split('-')]
    ref_start = pp[0] - 1
    ref_end = pp[1]

    print(f"审查 {len(rows)} 条记录...")
    print(f"  参考文献页: PDF {pp[0]}-{pp[1]}\n")

    # 提取参考文献原文
    ref_texts = extract_ref_texts(args.pdf, ref_start, ref_end)

    # 运行所有审查规则
    print("[1] DOI 唯一性...")
    check_doi_uniqueness(rows)

    print("[2] 同作者同年冲突...")
    check_same_author_year(rows)

    print("[3] 单作者论文...")
    check_single_author(rows, ref_texts)

    print("[4] 作者名异常...")
    check_author_names(rows, ref_texts)

    print("[5] 标题匹配度...")
    check_title_match(rows, ref_texts)

    print("[6] DOI 抽样验证...")
    check_doi_validity(rows)

    # 输出报告
    print(f"\n{'='*70}")
    print(f"审查报告 — {len(issues)} 个问题")
    print(f"{'='*70}")

    if not issues:
        print("\n  All checks passed — no issues found.")
        return

    levels = {'CRITICAL': 0, 'ERROR': 0, 'WARNING': 0}
    for iss in issues:
        levels[iss['level']] = levels.get(iss['level'], 0) + 1

    print(f"\n  CRITICAL: {levels.get('CRITICAL', 0)}")
    print(f"  ERROR:    {levels.get('ERROR', 0)}")
    print(f"  WARNING:  {levels.get('WARNING', 0)}")

    for iss in issues:
        level_mark = {'CRITICAL': '[!!!]', 'ERROR': '[!!]', 'WARNING': '[!]'}.get(iss['level'], '[?]')
        print(f"\n{level_mark} [{iss['level']}] {iss['title']}")
        print(f"    详情: {iss['detail']}")
        print(f"    修复: {iss['fix']}")

    print(f"\n{'='*70}")
    print("修复后请重新运行本脚本验证。")


if __name__ == '__main__':
    main()
