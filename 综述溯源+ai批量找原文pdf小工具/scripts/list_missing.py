# -*- coding: utf-8 -*-
"""列出 output/ 下所有项目的缺失文献清单
用法: python scripts/list_missing.py [目录名]
不带参数则列出所有子项目
"""
import sys, json, os, argparse
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

import common

def main():
    ap = argparse.ArgumentParser(description='列出 output/ 下的缺失文献清单')
    ap.add_argument('name', nargs='?', help='案例目录名（留空则列出全部）')
    args = ap.parse_args()

    if args.name:
        d = common.OUTPUT_DIR / args.name
        if not (d / 'extracted_data.json').exists():
            print(f'[ERROR] 未找到 {args.name}/extracted_data.json')
            sys.exit(1)
        targets = [d]
    else:
        targets = common.list_cases()

    if not targets:
        print('output/ 下无项目数据')
        sys.exit(0)

    for d in targets:
        recs = common.load_json(d / 'extracted_data.json', default=[])
        # 原实现按 k.split('_')[-1] 取编号，与统一的 progress key 规则不一致
        # （ref ≠ no 时会全部漏判），改为复用 common 的迁移 + 提取逻辑。
        progress = common.load_progress(d / 'download_progress.json', recs, d.name)
        okp = common.done_numbers(progress)
        missing = [r for r in recs if r.get('no') not in okp]
        print(f'\n=== {d.name}: {len(recs)} 篇, 已下 {len(recs)-len(missing)}, 缺失 {len(missing)} ===')
        for r in sorted(missing, key=lambda x: x.get('no', 0)):
            doi = r.get('doi', '') or '无DOI'
            print(f'  #{r.get("no", "?"):>3} {str(r.get("year", "")):>5} '
                  f'{r.get("first_author", "?")[:16]:18s} {doi[:45]}')


if __name__ == '__main__':
    main()
