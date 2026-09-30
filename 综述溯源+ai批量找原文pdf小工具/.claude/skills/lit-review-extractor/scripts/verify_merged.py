# -*- coding: utf-8 -*-
"""
verify_merged.py — 增强版 PDF 验证（吸取实战经验）
====================================================
针对合并后的统一 PDF 目录，逐篇验证是否匹配信息表记录。

支持的特殊情况（实战踩坑）：
  1. 多语言：波斯语论文（正文无英文，但含英文摘要部分）
  2. 扫描版：纯图片无文本层 → 标记待 OCR
  3. 乱码版：字体编码问题（文本层乱码但可 OCR）
  4. 中文文献：标题是中文 → 用作者匹配
  5. 严格匹配：作者前缀 + 标题唯一关键词（避免同作者同名混淆）

用法:
  python scripts/verify_merged.py --pdfdir "合并全部PDF" --xlsx "信息表.xlsx"
"""
import sys, os, re, argparse
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

import fitz
import pandas as pd

import common


# ---- 工具函数 ----

def first_author_prefix(author):
    """从作者字符串提取第一作者前缀（用于文件名匹配）"""
    a = str(author)
    if 'et al' in a:
        a = a.split('et al')[0]
    elif ' and ' in a:
        a = a.split(' and ')[0]
    return a.replace(',', '').replace(' ', '_').strip().lower()


# 领域停用词原先硬编码在此（空气污染×运动课题专用），现已外置到项目根的
# domain_stopwords.txt，由 common 在导入时自动加载 —— 换课题只需改那个文件。


def extract_pdf_doi(text):
    """从 PDF 文本提取 DOI"""
    m = re.search(r'10[.]\d{4,}/[^\s)\]}<>]{5,60}', text, re.I)
    return m.group(0).rstrip('.,;)}]').lower() if m else None


def get_pdf_text(path, max_pages=3):
    """读取 PDF 前几页文本（返回 (text, page_count)）"""
    doc = fitz.open(path)
    pages = doc.page_count
    text = ''
    for i in range(min(max_pages, pages)):
        text += doc[i].get_text()
    doc.close()
    return text, pages


def match_record(filename, no2row, exclude_nos=set()):
    """严格匹配：作者前缀 + 标题唯一关键词，返回 (no, score)"""
    f_lower = filename.lower()
    best_no, best_score = None, 0
    for no, row in no2row.items():
        if no in exclude_nos:
            continue
        fa = first_author_prefix(row['作者'])
        if not f_lower.startswith(fa):
            continue
        kws = common.title_keywords(str(row['文献题名']))
        fkws = set(re.findall(r'[a-zA-Z]{5,}', f_lower))
        score = len(kws & fkws)
        # 作者前缀已保证作者一致；同作者多篇文献时1个唯一关键词即可区分
        if score > best_score:
            best_score, best_no = score, no
    if best_no and best_score >= 1:
        return best_no, best_score
    return None, 0


def verify_pdf_against_record(path, row):
    """验证 PDF 内容是否匹配记录，返回 (verdict, detail)"""
    text, pages = get_pdf_text(path)
    # 原实现用 str(x) != 'nan' 判断缺失值，遇到字符串 'NaN'/'None' 会漏判
    exp_doi = str(row['DOI']) if pd.notna(row['DOI']) else ''
    title = str(row['文献题名'])
    has_cn = any('一' <= ch <= '鿿' for ch in title)

    # 1. 扫描版/无文本层
    if len(text.strip()) < 50:
        return 'scanned', f'无文本层({pages}页)，需OCR确认'

    # 2. DOI 精确匹配（金标准）
    pdf_doi = extract_pdf_doi(text)
    if pdf_doi and exp_doi:
        if pdf_doi[:20] in exp_doi.lower() or exp_doi.lower()[:20] in pdf_doi:
            return 'ok', f'DOI匹配 {pdf_doi[:25]}'

    # 3. 中文文献特殊处理（标题是中文，无法用英文关键词）
    if has_cn:
        # 若作者匹配且文件含中文内容，视为待人工确认
        return 'cn_verify', f'中文文献({pages}页)，需人工确认'

    # 4. 非英文正文（如波斯语论文）→ 检查是否有英文摘要/关键词
    #    波斯语文献正文无英文字母，但英文摘要部分含关键词
    #    判断依据：非ASCII字母字符占比高（波斯语/阿拉伯语等）
    eng_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    total_letters = sum(1 for ch in text if ch.isalpha())
    if eng_letters < 50 or (total_letters > 200 and eng_letters / total_letters < 0.3):
        # 非拉丁语系（波斯语/俄语等），正文无英文
        return 'multilang', f'非拉丁语系({pages}页, 英文{eng_letters}字)，检查英文摘要'

    # 5. 标题关键词匹配
    kws = common.title_keywords(title)
    hit = sum(1 for w in kws if w in text.lower())
    ratio = hit / len(kws) if kws else 0
    if ratio >= 0.35:
        return 'ok', f'标题命中 {hit}/{len(kws)}'
    if ratio >= 0.15:
        return 'weak', f'标题弱命中 {hit}/{len(kws)}'
    # （原此处的中文分支已被前面步骤 3 提前 return，属永不执行的死代码，已移除）
    return 'suspicious', f'内容不符({hit}/{len(kws)})'


# ---- 主流程 ----

def main():
    ap = argparse.ArgumentParser(description='增强版PDF验证')
    ap.add_argument('--pdfdir', required=True, help='PDF目录')
    ap.add_argument('--xlsx', required=True, help='信息表.xlsx')
    ap.add_argument('--sheet', default='Sheet1', help='工作表名')
    args = ap.parse_args()

    pdf_dir = Path(args.pdfdir)
    if not pdf_dir.exists():
        print(f'[ERROR] 目录不存在: {pdf_dir}')
        sys.exit(1)

    df = pd.read_excel(args.xlsx, sheet_name=args.sheet)
    no2row = {int(row['序号']): row for _, row in df.iterrows()}

    files = sorted(f for f in os.listdir(pdf_dir) if f.endswith('.pdf'))
    print(f'=== 验证 {len(files)} 个 PDF vs 信息表 {len(no2row)} 条记录 ===\n')

    results = []
    for f in files:
        path = pdf_dir / f
        # 匹配记录
        no, score = match_record(f, no2row)
        if no is None:
            # 中文文献回退（标题含中文的按作者匹配）
            f_lower = f.lower()
            cn_match = None
            for no_c, row_c in no2row.items():
                if any('一' <= ch <= '鿿' for ch in str(row_c['文献题名'])):
                    if first_author_prefix(row_c['作者'])[:8] in f_lower:
                        cn_match = no_c
                        break
            if cn_match:
                no = cn_match
            else:
                results.append((f, None, 'unmatched', '无法匹配信息表记录'))
                continue

        row = no2row[no]
        verdict, detail = verify_pdf_against_record(path, row)
        results.append((f, no, verdict, detail))

    # 汇总
    from collections import Counter
    verdicts = Counter(r[2] for r in results)
    print(f'验证结果:')
    for v in ['ok', 'weak', 'scanned', 'cn_verify', 'multilang', 'suspicious', 'unmatched']:
        if verdicts.get(v):
            print(f'  {v:12s}: {verdicts[v]}')

    print('\n=== 需要关注的 ===')
    for f, no, verdict, detail in results:
        if verdict in ('weak', 'scanned', 'cn_verify', 'multilang', 'suspicious', 'unmatched'):
            print(f'  [{verdict}] #{no} {detail}')
            print(f'      {f[:60]}')

    # 检查信息表里哪些记录没对应PDF
    matched_nos = {r[1] for r in results if r[1] is not None}
    missing_nos = [no for no in no2row if no not in matched_nos]
    if missing_nos:
        print(f'\n=== 信息表中无对应PDF的序号 ===')
        for no in sorted(missing_nos):
            print(f'  #{no} {str(no2row[no]["作者"])[:16]} ({no2row[no]["年份"]})')
    else:
        print('\n所有信息表记录都有对应PDF')

    # 结论
    bad = verdicts.get('suspicious', 0) + verdicts.get('unmatched', 0)
    if bad:
        print(f'\n>>> {bad} 篇存疑/无法匹配，需人工核查 <<<')
        sys.exit(1)
    else:
        print('\n>>> 验证通过（扫描/多语言/中文项已标注待确认）<<<')
        sys.exit(0)


if __name__ == '__main__':
    main()
