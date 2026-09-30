#!/usr/bin/env python3
"""Sci-Hub Chrome CDP batch download -- needs Chrome debug mode + VPN"""
import json, os, sys, time, re, random, base64
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = Path(__file__).parent.parent
PAPERS_DIR = BASE / 'papers'
SCIHUB = 'https://sci-hub.st'


def discover_papers():
    papers = {}
    for d in sorted(os.listdir(str(PAPERS_DIR))):
        full = PAPERS_DIR / d
        if not full.is_dir(): continue
        jp = full / 'extracted_data.json'
        if not jp.exists(): continue
        key = d.split('_')[0][:10]
        papers[key] = {'dir': d}
    return papers


def load_failed_all():
    P = discover_papers()
    all_failed, info = [], {}
    for k, cfg in P.items():
        pp = PAPERS_DIR / cfg['dir'] / 'download_progress.json'
        jp = PAPERS_DIR / cfg['dir'] / 'extracted_data.json'
        with open(jp, encoding='utf-8') as f: recs = json.load(f)
        prog = json.load(open(pp, encoding='utf-8')) if pp.exists() else {}
        for r in recs:
            rk = f"{k}_{r.get('ref','?')}"
            if rk not in prog or prog[rk].get('status') not in ('ok', 'already_done'):
                all_failed.append((k, r))
        info[k] = (PAPERS_DIR / cfg['dir'] / 'pdfs', pp, prog)
    return all_failed, info


def sani(s):
    for c in '/\\:*?"<>|': s = s.replace(c, '_')
    return re.sub(r'[\x00-\x1f]', '', s.strip())[:90].rstrip('. ')

def fn(a, t, y=''):
    fa = (a or 'X').strip().replace(' ', '_').replace(',', '')
    return (f"{fa}_{y}_{sani(t or 'X')}"[:180] + '.pdf')

def find_pdf(page):
    for sel in ['object[type="application/pdf"]','embed[type="application/pdf"]',
                 'meta[name="citation_pdf_url"]']:
        el = page.query_selector(sel)
        if el:
            src = el.get_attribute('data') or el.get_attribute('src') or el.get_attribute('content') or ''
            if src: return urljoin(page.url, src)
    for a in page.query_selector_all('a[href$=".pdf"]'):
        return urljoin(page.url, a.get_attribute('href') or '')
    return None


all_failed, info = load_failed_all()
if not all_failed:
    print('All papers already downloaded!'); sys.exit(0)
print(f'\n{len(all_failed)} papers via Sci-Hub CDP\n')

p = sync_playwright().start()
try:
    b = p.chromium.connect_over_cdp('http://localhost:9222')
    page = b.contexts[0].pages[0]
    print(f'Connected: {page.title()[:60]}\n')
except:
    print('ERROR: Chrome CDP not available. Run launch_chrome_for_scihub.cmd first.')
    p.stop(); sys.exit(1)

ok = fail = 0
for idx, (pk, rec) in enumerate(all_failed):
    doi = (rec.get('doi','') or '').replace('https://doi.org/','').strip().lower()
    a = rec.get('first_author',''); t = rec.get('title',''); y = rec.get('year',''); ref = rec.get('ref','?')
    if not doi: fail += 1; continue
    pdf_dir, pp, prog = info[pk]
    out = pdf_dir / fn(a, t, y); os.makedirs(pdf_dir, exist_ok=True)
    tag = f"[{idx+1:3d}/{len(all_failed)}] {pk} ref{str(ref):3s} {a[:16]}"
    if idx > 0: time.sleep(random.uniform(3, 8))
    try:
        page.goto(f'{SCIHUB}/{doi}', wait_until='domcontentloaded', timeout=45000)
        time.sleep(2)
        tl = page.title().lower()
        if 'verify' in tl or 'captcha' in tl or 'robot' in tl:
            print(f'{tag} CAPTCHA in Chrome -> Enter'); input(); time.sleep(2)
        pdf_url = find_pdf(page)
        if not pdf_url:
            fail += 1; ct = page.content()[:500].lower()
            print(f'{tag} FAIL ("not found" in ct and "no Sci-Hub" or "no PDF")')
            status = 'failed'
        else:
            r = page.evaluate("async(u)=>{try{let r=await fetch(u,{credentials:'include'});if(!r.ok)return{error:'HTTP '+r.status};let b=await r.arrayBuffer();let w=new Uint8Array(b);let s='';for(let i=0;i<w.length;i+=4096)s+=String.fromCharCode.apply(null,w.subarray(i,Math.min(i+4096,w.length)));return{data:btoa(s),size:w.length}}catch(e){return{error:e.message}}}", pdf_url)
            if r.get('data'):
                d = base64.b64decode(r['data']); sz = len(d)
                if d[:5] == b'%PDF-' and sz > 5000:
                    with open(out,'wb') as f: f.write(d)
                    ok += 1; status = 'ok'; print(f'{tag} OK {sz//1024}KB')
                else: fail += 1; status = 'failed'; print(f'{tag} FAIL ({sz}b)')
            else: fail += 1; status = 'failed'; print(f'{tag} FAIL ({r.get("error","?")})')
    except Exception as e: fail += 1; status = 'failed'; print(f'{tag} FAIL ({str(e)[:40]})')
    rk = f"{pk}_{ref}"
    prog[rk] = {'no':rec.get('no',idx+1),'ref':ref,'author':a,'doi':doi,'status':status,
                'pdf_path':str(out) if status=='ok' else '','source':'scihub' if status=='ok' else '',
                'details':f'{ok}/{len(all_failed)}' if status=='ok' else 'failed'}
    with open(pp,'w',encoding='utf-8') as f: json.dump(prog,f,ensure_ascii=False,indent=2)

p.stop()
print(f'\nOK={ok} FAIL={fail}')
