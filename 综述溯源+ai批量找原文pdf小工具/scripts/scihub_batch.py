# -*- coding: utf-8 -*-
"""
scihub_batch.py — Sci-Hub 批量补漏（需 VPN + Chrome 调试）
========================================================
修复: 移除 'challenge'/'验证' 误匹配词，先找PDF再判断标题
只处理剩余缺失且有DOI的文献

用法:
  python scripts/scihub_batch.py                        # 自动识别 output/ 下唯一案例
  python scripts/scihub_batch.py --name Morici_2020
"""
import sys, time, base64, argparse
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from urllib.parse import urljoin

import common

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('[ERROR] pip install playwright && python -m playwright install chromium')
    sys.exit(1)

MIRRORS = ['https://sci-hub.sg', 'https://sci-hub.st', 'https://sci-hub.ru']
# 精确验证码页特征（刻意不含 'challenge'/'验证' 这类宽泛词，避免标题误判）
CAPTCHA = ['你是机器人', '机器人吗', 'please verify', 'captcha',
           'checking your browser', '安全验证', '请稍候', 'access denied', 'robot check']
NOTFOUND = ['未找到', 'not found', 'article not found', 'не найден', 'did not find', '该文章在']
CDP_URL = 'http://localhost:9222'


def find_pdf(page):
    """在 Sci-Hub 结果页里找 PDF 源。相对路径按当前页 origin 拼接
    （原实现永远拼 sci-hub.sg，在 st/ru 镜像下会拼出错域名）。"""
    base = page.url
    for sel in ['embed[type="application/pdf"]', 'object[type="application/pdf"]',
                'meta[name="citation_pdf_url"]', 'a[href$=".pdf"]']:
        try:
            el = page.query_selector(sel)
            if el:
                src = (el.get_attribute('data') or el.get_attribute('src') or
                       el.get_attribute('content') or el.get_attribute('href') or '')
                if src:
                    return src if src.startswith('http') else urljoin(base, src)
        except Exception:
            continue
    return None


JS_FETCH_B64 = """async (u) => {
    try {
        const r = await fetch(u, {credentials: 'include'});
        if (!r.ok) return {error: 'HTTP ' + r.status};
        const b = await r.arrayBuffer(); const w = new Uint8Array(b);
        let s = '';
        for (let i = 0; i < w.length; i += 4096)
            s += String.fromCharCode.apply(null, w.subarray(i, Math.min(i+4096, w.length)));
        return {data: btoa(s), size: w.length};
    } catch(e) { return {error: e.message}; }
}"""


def main():
    ap = argparse.ArgumentParser(description='Sci-Hub 批量补漏')
    ap.add_argument('--name', '-n', help='案例目录名（留空则自动识别 output/ 下唯一案例）')
    ap.add_argument('--cdp', default=CDP_URL, help='Chrome 调试地址')
    args = ap.parse_args()

    case_dir = common.resolve_case_dir(args.name)
    paths = common.case_paths(case_dir)
    case = case_dir.name

    recs = common.load_json(paths['json'], default=[])
    if not recs:
        raise SystemExit(f'[ERROR] {paths["json"]} 为空或不存在')

    # 进度文件缺失时按「全量待处理」处理（原实现 json.load 无保护，首次运行直接崩）
    progress = common.load_progress(paths['progress'], recs, case)
    done_nos = common.done_numbers(progress)
    missing = [r for r in recs if r.get('no') not in done_nos and r.get('doi')]
    print(f'待补有 DOI: {len(missing)} 篇 -> {[r.get("no") for r in missing]}')
    if not missing:
        print('无待补文献，退出。')
        return

    common.ensure_dir(paths['pdfs'])
    p = sync_playwright().start()
    page = None
    try:
        b = p.chromium.connect_over_cdp(args.cdp)
    except Exception as e:
        p.stop()
        raise SystemExit(f'[ERROR] 连接 Chrome CDP 失败: {e}\n'
                         f'  请先运行 scripts/launch_chrome_cdp.cmd')
    try:
        page = b.contexts[0].new_page()
        page.goto('https://sci-hub.sg', wait_until='domcontentloaded', timeout=30000)
        time.sleep(2)
        print(f'已开新页: {page.url}')

        for rec in missing:
            no = rec.get('no')
            doi = common.clean_doi(rec.get('doi', ''))
            fa = rec.get('first_author', '')
            out = paths['pdfs'] / common.pdf_name(fa, rec.get('title', ''), rec.get('year', ''))
            if out.exists() and out.stat().st_size > 8000:
                print(f'#{no} 文件已存在，跳过')
                continue
            tag = f'#{no} {fa[:14]}'
            got = False
            for mirror in MIRRORS:
                try:
                    page.goto(f'{mirror}/{doi}', wait_until='commit', timeout=40000)
                    for _ in range(20):
                        time.sleep(1)
                        if 'loading' not in (page.title() or '').lower():
                            break
                    time.sleep(1)
                    # 先找 PDF（页面正常时就有），避免被标题里的 challenge 等词误导
                    pdf_url = find_pdf(page)
                    if pdf_url:
                        result = page.evaluate(JS_FETCH_B64, pdf_url)
                        data = base64.b64decode(result['data']) if result.get('data') else b''
                        if data[:5] == b'%PDF-' and len(data) > 8000:
                            ok, det = common.verify_content(data, rec)
                            if ok:
                                with open(out, 'wb') as f:
                                    f.write(data)
                                print(f'{tag} [{mirror}] OK {len(data)//1024}KB [{det}]')
                                got = True
                                break
                            print(f'{tag} [{mirror}] 内容不符({det})')
                    tl = page.title() or ''
                    if any(k in tl for k in NOTFOUND):
                        print(f'{tag} [{mirror}] 未找到')
                        continue
                    if any(k in tl.lower() for k in CAPTCHA):
                        print(f'{tag} [{mirror}] 真验证码页，跳过')
                        continue
                    print(f'{tag} [{mirror}] 无PDF (title={tl[:30]})')
                except Exception as e:
                    print(f'{tag} [{mirror}] ERR {str(e)[:60]}')

            if got:
                progress[common.progress_key(case, rec)] = {
                    'no': no, 'ref': rec.get('ref'), 'author': fa, 'doi': doi,
                    'status': 'ok', 'pdf_path': str(out),
                    'source': 'scihub_rescue', 'details': 'rescue',
                }
                common.save_progress(paths['progress'], progress)
    finally:
        # 异常时也能关闭标签页、释放 playwright（原先无保护会泄漏 page）
        if page:
            try:
                page.close()
            except Exception:
                pass
        p.stop()

    print(f'\n当前总成功: {len(common.done_numbers(progress))}/{len(recs)}')


if __name__ == '__main__':
    main()
