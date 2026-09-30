# -*- coding: utf-8 -*-
"""
prep_from_info.py — 从 信息表.xlsx 生成 download_pdfs.py 的输入 extracted_data.json
功能：
  1. 读取信息表（序号/文献题名/作者/年份/DOI/初步结局分类）
  2. 提取 first_author
  3. 对缺失 DOI 的文献用 OpenAlex 按标题搜索补全（打印候选供人工确认）
  4. 输出 output/文献pdf/extracted_data.json
"""
import sys, re, json, time
from pathlib import Path
import pandas as pd
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = Path(__file__).parent.parent
XLSX = BASE / '信息表.xlsx'
OUT_DIR = None
OUT_JSON = None

S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
MAILTO = 'litreview-prep@example.org'


def first_author(author: str) -> str:
    if not author:
        return 'Unknown'
    a = str(author).strip()
    if 'et al' in a:
        a = a.split('et al')[0].strip().rstrip(', ').strip()
    elif ' and ' in a:
        a = a.split(' and ')[0].strip().rstrip(', ').strip()
    # 归一化为 "Last, F."
    return a


def openalex_search(title: str, year: str, author: str, topn=5):
    """OpenAlex 标题搜索，返回候选列表 [{doi,title,year,display_name,matched}]"""
    q = title.replace('–', '-').replace('—', '-')
    # 保留字母数字与空格，其余标点剔除（原先还在此无差别纠正 'reposnses'/'deisel'
    # 等特定笔误，那是某一批数据的遗留，通用场景有害，已移除）
    q = re.sub(r'[^A-Za-z0-9 -]', ' ', q)
    words = [w for w in q.split() if len(w) > 2]
    q = ' '.join(words[:12])
    try:
        r = S.get('https://api.openalex.org/works',
                  params={'search': q, 'per-page': topn, 'select': 'doi,title,publication_year,display_name,authorships'},
                  timeout=30)
        if r.status_code != 200:
            return []
        out = []
        for w in r.json().get('results', []):
            fa = ''
            if w.get('authorships'):
                fa = w['authorships'][0].get('author', {}).get('display_name', '')
            out.append({
                'doi': w.get('doi', ''),
                'title': (w.get('title') or '')[:150],
                'year': w.get('publication_year'),
                'display_name': (w.get('display_name') or '')[:80],
                'first_author': fa,
            })
        return out
    except Exception as e:
        print(f'    [openalex error] {e}')
        return []


def parse_year(v) -> int | None:
    """从年份字段提取 4 位年份。原实现直接 int(year)，遇到 '2020a'/'nan'/空值会崩。"""
    m = re.search(r'(1[89]|20)\d{2}', str(v or ''))
    return int(m.group(0)) if m else None


def title_sim(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def main():
    global OUT_DIR, OUT_JSON, XLSX
    import argparse
    ap = argparse.ArgumentParser(description='从 信息表.xlsx 生成 extracted_data.json')
    ap.add_argument('--name', default='文献pdf', help='输出目录名（默认 output/文献pdf/）')
    ap.add_argument('--xlsx', default=str(XLSX), help='信息表路径（默认 信息表.xlsx）')
    args = ap.parse_args()
    OUT_DIR = BASE / 'output' / args.name
    OUT_JSON = OUT_DIR / 'extracted_data.json'
    XLSX = Path(args.xlsx)
    if not XLSX.exists():
        raise SystemExit(f'[ERROR] 找不到信息表: {XLSX}\n  用 --xlsx 指定路径')
    try:
        df = pd.read_excel(XLSX, sheet_name='Sheet1')
    except ValueError as e:
        raise SystemExit(f'[ERROR] 读取 {XLSX} 失败: {e}')

    required_cols = ['序号', '文献题名', '作者', '年份', 'DOI', '初步结局分类']
    lack = [c for c in required_cols if c not in df.columns]
    if lack:
        raise SystemExit(f'[ERROR] 信息表缺少必需列: {lack}\n  实际列: {list(df.columns)}')

    records = []
    missing = []

    for _, row in df.iterrows():
        no = int(row['序号'])
        title = str(row['文献题名']).strip()
        author = str(row['作者']).strip()
        year = str(row['年份']).strip()
        doi = str(row['DOI']).strip() if pd.notna(row['DOI']) else ''
        outcome = str(row['初步结局分类']).strip() if pd.notna(row['初步结局分类']) else ''

        rec = {
            'no': no,
            'ref': str(no),
            'first_author': first_author(author),
            'authors_raw': author,
            'title': title,
            'year': year,
            'doi': doi if doi and doi.lower() != 'nan' else '',
            'outcome_class': outcome,
        }
        records.append(rec)
        if not rec['doi']:
            missing.append(rec)

    print(f'信息表: {len(records)} 条记录, 缺 DOI: {len(missing)} 条')

    # --- DOI 补全（OpenAlex 标题搜索） ---
    resolved = {}
    for rec in missing:
        print(f'\n[{rec["no"]}] {rec["first_author"]} {rec["year"]}')
        print(f'    T: {rec["title"][:100]}')
        cands = openalex_search(rec['title'], rec['year'], rec['first_author'])
        if not cands:
            print('    -> 无候选')
            continue
        for i, c in enumerate(cands):
            score = title_sim(rec['title'], c['title'])
            flag = ' <== YEAR' if (rec_year and c['year'] == rec_year) else ''
            print(f'    {i}: sim={score:.2f} year={c["year"]} doi={c["doi"]}')
            print(f'       {c["title"][:90]}')
            print(f'       authors: {c["first_author"][:60]}{flag}')
        # 自动选：年份匹配优先，其次标题相似度
        rec_year = parse_year(rec['year'])
        year_ok = [c for c in cands if rec_year and c.get('year') == rec_year]
        pool = year_ok if year_ok else cands
        best = max(pool, key=lambda c: title_sim(rec['title'], c['title']))
        print(f'    => AUTO 选: doi={best["doi"]} sim={title_sim(rec["title"], best["title"]):.2f}')
        resolved[rec['no']] = best

    # 应用补全（仅当标题相似度足够高）
    for rec in records:
        if rec['doi']:
            continue
        cand = resolved.get(rec['no'])
        if not cand or not cand.get('doi'):
            continue
        sim = title_sim(rec['title'], cand['title'])
        if sim >= 0.45:
            rec['doi'] = cand['doi'].replace('https://doi.org/', '')
            rec['doi_source'] = 'openalex_auto'
            print(f'  [补全] #{rec["no"]} -> {rec["doi"]} (sim={sim:.2f})')
        else:
            print(f'  [保留缺失] #{rec["no"]} sim={sim:.2f} 过低，不自动补全')

    # 汇总缺DOI
    still_missing = [r for r in records if not r.get('doi')]
    print(f'\n仍缺 DOI: {len(still_missing)} 条')
    for r in still_missing:
        print(f'  #{r["no"]} {r["first_author"]} {r["year"]}')

    # --- 输出 ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f'\n已写入: {OUT_JSON}  ({len(records)} 条)')


if __name__ == '__main__':
    main()
