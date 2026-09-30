# -*- coding: utf-8 -*-
"""
sync_scripts.py — 把 scripts/ 同步到各个副本目录（单向，只写不删）
====================================================================
背景：本项目同一个脚本存了三份
  scripts/                                  ← 真源
  .claude/skills/lit-review-extractor/scripts/
  查找文献pdf/scripts/
改动容易漏同步，导致版本漂移（实测 panda985_search.py 差 277 行、
scihub_batch.py 差 243 行）。

本脚本**从不做删除**：只会把真源覆盖过去；目标里多出来的文件原样保留。
旧同名文件会被备份到 <目标>/_backup/ 下，随时可回退。

用法:
  python scripts/sync_scripts.py                # 预览变更（dry-run，默认）
  python scripts/sync_scripts.py --apply        # 真正写入
  python scripts/sync_scripts.py --apply --targets skill   # 只同步 skill 副本
"""
import sys, os, shutil, argparse, hashlib
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / 'scripts'

# 真源同步时应当跳过的东西
SKIP_NAMES = {'__pycache__', '_backup'}
SKIP_SUFFIX = {'.pyc', '.pyo'}

TARGETS = {
    'skill': BASE / '.claude' / 'skills' / 'lit-review-extractor' / 'scripts',
    'legacy': BASE / '查找文献pdf' / 'scripts',
}


def digest(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def plan(src: Path, dst: Path):
    """列出需要写入的文件清单。返回 list[(src_file, dst_file, 动作)]"""
    actions = []
    if not src.is_dir():
        return actions
    for f in sorted(src.iterdir()):
        if f.is_dir() or f.suffix in SKIP_SUFFIX or f.name in SKIP_NAMES:
            continue
        target = dst / f.name
        if not target.exists():
            actions.append((f, target, '新增'))
        elif digest(f) != digest(target):
            actions.append((f, target, '更新'))
    return actions


def main():
    ap = argparse.ArgumentParser(description='scripts/ → 副本目录单向同步（不删除任何文件）')
    ap.add_argument('--apply', action='store_true', help='真正写入（默认只预览）')
    ap.add_argument('--targets', nargs='*', choices=list(TARGETS), default=list(TARGETS),
                    help='要同步的目标（默认全部）')
    ap.add_argument('--no-backup', action='store_true', help='不备份被覆盖的旧文件')
    args = ap.parse_args()

    print(f'真源: {SRC}')
    print(f'模式: {"写入" if args.apply else "预览（加 --apply 才会真正改文件）"}\n')

    total = 0
    for key in args.targets:
        dst = TARGETS[key]
        print(f'=== {key}: {dst} ===')
        if not dst.exists():
            print(f'  目录不存在，跳过（如需请手动创建）')
            continue
        actions = plan(SRC, dst)
        if not actions:
            print('  已是最新，无需同步')
            continue
        for src_f, dst_f, act in actions:
            old = ''
            if dst_f.exists():
                old = f'  (旧文件 {dst_f.stat().st_size//1024}KB)'
            print(f'  [{act}] {src_f.name}{old}')
            if args.apply:
                if dst_f.exists() and not args.no_backup:
                    bk = dst / '_backup' / f'{dst_f.name}.{datetime.now():%Y%m%d_%H%M%S}.bak'
                    bk.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst_f, bk)
                shutil.copy2(src_f, dst_f)
        total += len(actions)
        print(f'  小计 {len(actions)} 个文件\n')

    if args.apply:
        print(f'完成，共写入 {total} 个文件。旧文件已备份到各目标下的 _backup/')
    else:
        print(f'预览完成，共 {total} 个文件待同步。加 --apply 执行写入。')


if __name__ == '__main__':
    main()
