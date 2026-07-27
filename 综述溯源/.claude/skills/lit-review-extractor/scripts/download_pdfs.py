#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_pdfs.py -- Batch PDF download for systematic review included studies
================

11-layer fallback strategy:
  L1:  Europe PMC (europepmc.org/?pdf=render)
  L2:  Unpaywall (best_oa_location.url_for_pdf)
  L3:  OpenAlex (open_access.oa_url)
  L4:  Semantic Scholar (openAccessPdf.url)
  L5:  Publisher meta tag (citation_pdf_url)
  L6:  Sci-Hub Mirror (panda985 embed/iframe)
  L7:  X-MOL academic search
  L8:  673 Scholar (Google Scholar mirror)
  L9:  Sci-Hub Direct (sci-hub.se/ru/st, needs VPN)
  L10: Playwright browser (needs VPN + Chrome CDP)
  L11: Panda985 search (search-by-title, needs VPN + Chrome CDP)

Usage:
  python download_pdfs.py                      # all 4 papers
  python download_pdfs.py --paper gandhi       # single paper
  python download_pdfs.py --paper andrade --skip-vpn  # skip VPN layers
"""

import re, json, os, sys, time, argparse, tempfile, base64
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import fitz
except ImportError:
    print("[ERROR] pip install pymupdf")
    sys.exit(1)

try:
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Border, Side
except ImportError:
    print("[ERROR] pip install openpyxl")
    sys.exit(1)

# ============================================================
# Auto-discover papers from papers/ directory
# ============================================================
BASE_DIR = Path(__file__).parent.parent  # 查找文献pdf/
PAPERS_DIR = BASE_DIR / 'papers'
UNPAYWALL_EMAIL = 'morici-review@irib.cnr.it'


def discover_papers():
    """Auto-discover all paper directories under papers/ that have extracted_data.json.
    Returns {key: {dir, json, xlsx}} dict."""
    papers = {}
    if not PAPERS_DIR.exists():
        print(f"[ERROR] papers/ directory not found at {PAPERS_DIR}")
        print(f"Create it and put your paper data there:")
        print(f"  papers/YourPaperName/extracted_data.json")
        return papers

    for d in sorted(os.listdir(str(PAPERS_DIR))):
        full = PAPERS_DIR / d
        if not full.is_dir():
            continue
        jp = full / 'extracted_data.json'
        if not jp.exists():
            continue

        # Generate a short key from directory name
        key = d.split('_')[0].split('(')[0].strip().lower()
        if not key:
            key = d[:10]

        # Find Excel file (any .xlsx that is not a temp file)
        xlsx = None
        for f in os.listdir(str(full)):
            if f.endswith('.xlsx') and not f.startswith('~$'):
                xlsx = f
                break
        if not xlsx:
            xlsx = f'{key}.xlsx'  # fallback

        papers[key] = {'dir': d, 'json': 'extracted_data.json', 'xlsx': xlsx}

    return papers


PAPERS = discover_papers()
if not PAPERS:
    # Fallback: check if there's an "output" directory from old projects
    OUTPUT_DIR = BASE_DIR / 'output'
    if OUTPUT_DIR.exists():
        for d in os.listdir(str(OUTPUT_DIR)):
            full = OUTPUT_DIR / d
            if full.is_dir():
                jp = full / 'extracted_data.json'
                if jp.exists():
                    key = d.split('_')[0].split('(')[0].strip().lower()[:10]
                    xlsx_found = None
                    for f in os.listdir(str(full)):
                        if f.endswith('.xlsx') and not f.startswith('~$'):
                            xlsx_found = f
                            break
                    PAPERS[key] = {'dir': str(full), 'json': 'extracted_data.json', 'xlsx': xlsx_found or f'{key}.xlsx'}
        if PAPERS:
            PAPERS_DIR = OUTPUT_DIR

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
REQ_TIMEOUT = 20
DL_TIMEOUT = 45
S = requests.Session()
S.headers.update({'User-Agent': UA})
SCIHUB_DOMAINS = ['https://sci-hub.se', 'https://sci-hub.ru', 'https://sci-hub.st']
SKIP_VPN = False


# ============================================================
# Utils
# ============================================================
def clean_doi(s):
    if not s: return ''
    doi = str(s).strip()
    doi = re.sub(r'^https?://doi[.]org/', '', doi, flags=re.I)
    return doi.lower().rstrip('.')

def sanitize(s):
    for c in '/\\:*?"<>|': s = s.replace(c, '_')
    s = re.sub(r'[\x00-\x1f]', '', s.replace('\n',' ').replace('\r','').strip())
    return s[:90].rstrip('. ')

def pdf_name(author, title, year=''):
    fa = author.strip().replace(' ','_').replace(',','') if author else 'Unknown'
    base = f"{fa}_{year}_{sanitize(title or 'NoTitle')}"[:180]
    return base + '.pdf'

def is_pdf(content, ct=''):
    if not content or len(content)<200: return False
    if content[:5]==b'%PDF-': return True
    if b'%PDF-' in content[:1024]: return True
    return 'application/pdf' in ct.lower()

def fetch(url, timeout=REQ_TIMEOUT):
    for _ in range(3):
        try:
            r = S.get(url, timeout=timeout, allow_redirects=True)
            return r
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(1)
        except Exception:
            raise
    return None

def resolve_html_to_pdf(html_url):
    try:
        r = fetch(html_url)
        if not r or r.status_code!=200: return None
        ct = r.headers.get('Content-Type','')
        if is_pdf(r.content, ct): return r.content
        if 'text/html' not in ct.lower(): return None
        soup = BeautifulSoup(r.text, 'html.parser')
        candidates = []
        for mn in ['citation_pdf_url','dc.identifier']:
            meta = soup.find('meta',{'name':mn})
            if meta and meta.get('content'):
                u = meta['content']
                candidates.append(u if u.startswith('http') else urljoin(r.url,u))
        for a in soup.find_all('a',href=True):
            href = a['href']
            if re.search(r'[.]pdf$|/pdf/|/epdf/', href, re.I):
                u = href if href.startswith('http') else urljoin(r.url,href)
                if u not in candidates: candidates.append(u)
        for u in candidates[:6]:
            try:
                sub = fetch(u, timeout=DL_TIMEOUT)
                if sub and sub.status_code==200 and is_pdf(sub.content, sub.headers.get('Content-Type','')):
                    return sub.content
            except: continue
        return None
    except: return None


# ============================================================
# L1-L8: API layers
# ============================================================

def L1_pmc(doi):
    """Europe PMC"""
    try:
        r = fetch(f'https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={doi}&format=json')
        if not r or r.status_code!=200: return None,None
        recs = r.json().get('records',[])
        if not recs: return None,None
        pmcid = recs[0].get('pmcid','')
        if not pmcid: return None,None
        sub = fetch(f'https://europepmc.org/articles/{pmcid}?pdf=render', timeout=DL_TIMEOUT)
        if sub and sub.status_code==200 and 'application/pdf' in sub.headers.get('Content-Type',''):
            return sub.content, 'europe_pmc'
        return None,None
    except: return None,None

def L2_unpaywall(doi):
    """Unpaywall"""
    try:
        r = fetch(f'https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}')
        if not r or r.status_code!=200: return None,None
        data = r.json()
        if not data.get('is_oa'): return None,None
        for loc in [data.get('best_oa_location')]+data.get('oa_locations',[]):
            u = (loc or {}).get('url_for_pdf') or (loc or {}).get('url')
            if not u: continue
            c = resolve_html_to_pdf(u)
            if c and is_pdf(c): return c, 'unpaywall'
        return None,None
    except: return None,None

def L3_openalex(doi):
    """OpenAlex"""
    try:
        r = fetch(f'https://api.openalex.org/works/doi:{requests.utils.quote(doi,safe="")}?mailto=oa-review@example.net&select=open_access')
        if not r or r.status_code!=200: return None,None
        oa = r.json().get('open_access',{})
        if not oa.get('is_oa') or not oa.get('oa_url'): return None,None
        c = resolve_html_to_pdf(oa['oa_url'])
        if c and is_pdf(c): return c, 'openalex'
        return None,None
    except: return None,None

def L4_semantic_scholar(doi):
    """Semantic Scholar"""
    try:
        r = fetch(f'https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=openAccessPdf')
        if not r or r.status_code!=200: return None,None
        oa = r.json().get('openAccessPdf')
        if not oa or not oa.get('url'): return None,None
        c = resolve_html_to_pdf(oa['url'])
        if c and is_pdf(c): return c, 'semantic_scholar'
        return None,None
    except: return None,None

def L5_publisher(doi):
    """Publisher meta"""
    try:
        c = resolve_html_to_pdf(f'https://doi.org/{doi}')
        if c and is_pdf(c): return c, 'publisher'
        return None,None
    except: return None,None

def L6_scihub_mirror(doi):
    """Sci-Hub mirror (panda985)"""
    for m in [f'https://sc.panda985.com/{doi}']:
        try:
            r = fetch(m, timeout=DL_TIMEOUT)
            if not r or r.status_code!=200: continue
            soup = BeautifulSoup(r.text,'html.parser')
            for tag in ['embed','iframe']:
                for el in soup.find_all(tag):
                    src = el.get('src','') or el.get('data','')
                    if src and 'pdf' in src.lower():
                        c = resolve_html_to_pdf(src if src.startswith('http') else urljoin(m,src))
                        if c and is_pdf(c): return c, 'scihub_mirror'
        except: continue
    return None,None

def L7_xmol(doi):
    """X-MOL"""
    try:
        r = fetch(f'https://www.x-mol.com/paper/search/q?q={doi}')
        if not r or r.status_code!=200: return None,None
        soup = BeautifulSoup(r.text,'html.parser')
        for a in soup.find_all('a',href=True):
            if any(k in (a.text+a.get('href','')).lower() for k in ('pdf','download','full text')):
                c = resolve_html_to_pdf(a['href'] if a['href'].startswith('http') else urljoin(r.url,a['href']))
                if c and is_pdf(c): return c, 'xmol'
        return None,None
    except: return None,None

def L8_google_scholar_mirror(doi):
    """673.org Scholar"""
    try:
        r = fetch(f'https://so.673.org/scholar?q={doi}&hl=en&as_sdt=0,5')
        if not r or r.status_code!=200: return None,None
        soup = BeautifulSoup(r.text,'html.parser')
        for a in soup.find_all('a',href=True):
            if '.pdf' in a['href'].lower() or 'gs_or_pdf' in ' '.join(a.get('class',[])):
                c = resolve_html_to_pdf(a['href'] if a['href'].startswith('http') else urljoin(r.url,a['href']))
                if c and is_pdf(c): return c, 'scholar673'
        return None,None
    except: return None,None


# ============================================================
# L9-L11: VPN layers
# ============================================================

def L9_scihub_direct(doi):
    """Sci-Hub direct (needs VPN)"""
    if SKIP_VPN: return None,None
    for domain in SCIHUB_DOMAINS:
        try:
            r = fetch(f'{domain}/{doi}', timeout=DL_TIMEOUT)
            if not r or r.status_code!=200: continue
            ct = r.headers.get('Content-Type','')
            if is_pdf(r.content, ct): return r.content, 'scihub_direct'
            # Parse HTML for PDF embed
            soup = BeautifulSoup(r.text,'html.parser')
            for tag in ['embed','iframe','object']:
                for el in soup.find_all(tag):
                    src = el.get('src','') or el.get('data','')
                    if src and ('pdf' in src.lower() or src.endswith('.pdf')):
                        c = resolve_html_to_pdf(src if src.startswith('http') else urljoin(f'{domain}',src))
                        if c and is_pdf(c): return c, 'scihub_direct'
            # Look for download links
            for a in soup.find_all('a',href=True):
                if a['href'].endswith('.pdf'):
                    c = resolve_html_to_pdf(a['href'] if a['href'].startswith('http') else urljoin(f'{domain}',a['href']))
                    if c and is_pdf(c): return c, 'scihub_direct'
        except: continue
    return None,None

def L10_playwright(doi):
    """Playwright browser (needs VPN + Chrome CDP)"""
    if SKIP_VPN: return None,None
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return None,None

    try:
        with sync_playwright() as p:
            # Connect to Chrome CDP
            try:
                browser = p.chromium.connect_over_cdp('http://localhost:9222')
                page = browser.contexts[0].pages[0]
            except:
                return None,None

            doi_url = f'https://doi.org/{doi}'
            dl_evt = {'path': None}

            def on_dl(dl):
                tmp = os.path.join(tempfile.gettempdir(), f'pwdl_{int(time.time())}.pdf')
                dl.save_as(tmp)
                dl_evt['path'] = tmp

            page.on('download', on_dl)

            try:
                page.goto(doi_url, wait_until='domcontentloaded', timeout=30000)
                time.sleep(3)
                # Click PDF buttons
                for sel in ['a[href*="pdf"]','a:has-text("PDF")','a:has-text("Download")',
                            'button:has-text("PDF")','.article-download-pdf']:
                    try:
                        btn = page.wait_for_selector(sel, timeout=3000)
                        if btn: btn.click(); time.sleep(3)
                        if dl_evt['path'] and os.path.exists(dl_evt['path']):
                            with open(dl_evt['path'],'rb') as f:
                                data = f.read()
                            os.unlink(dl_evt['path'])
                            if is_pdf(data): return data, 'playwright'
                    except PWTimeout:
                        continue
            except:
                pass

        return None,None
    except:
        return None,None

def L11_panda985_search(doi, title=''):
    """Panda985 search-by-title (needs VPN + Chrome CDP)"""
    if SKIP_VPN or not title: return None,None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None,None

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp('http://localhost:9222')
                page = browser.contexts[0].pages[0]
            except:
                return None,None

            # Search on panda985
            q = title[:120]
            search_url = f'https://sc.panda985.com/scholar?q={requests.utils.quote(q)}&hl=en'
            page.goto(search_url, wait_until='domcontentloaded', timeout=45000)
            time.sleep(3)

            # Click first external result
            clicked = False
            for sel in ['h3 a', '.gs_rt a', '.gs_ttl a']:
                for a in page.query_selector_all(sel):
                    href = a.get_attribute('href') or ''
                    if href.startswith('http') and 'panda985' not in href:
                        a.click(); time.sleep(5); clicked = True; break
                if clicked: break

            if not clicked: return None,None

            # Find PDF on publisher page
            pdf_url = None
            for sel in ['meta[name="citation_pdf_url"]','a[href$=".pdf"]',
                        'a[href*="/pdf/"]','a:has-text("PDF")',
                        'a:has-text("Download PDF")','a:has-text("View PDF")']:
                el = page.query_selector(sel)
                if el:
                    src = el.get_attribute('content') or el.get_attribute('href') or ''
                    if src:
                        pdf_url = src if src.startswith('http') else urljoin(page.url, src)
                        break

            if not pdf_url: return None,None

            # Download via browser fetch (has cookies)
            result = page.evaluate("""
                async (url) => {
                    try {
                        const r = await fetch(url, {credentials: 'include'});
                        if (!r.ok) return {error: 'HTTP ' + r.status};
                        const buf = await r.arrayBuffer();
                        const bytes = new Uint8Array(buf);
                        let bin = '';
                        for (let i = 0; i < bytes.length; i += 4096)
                            bin += String.fromCharCode.apply(null,
                                bytes.subarray(i, Math.min(i+4096, bytes.length)));
                        return {data: btoa(bin), size: bytes.length};
                    } catch(e) { return {error: e.message}; }
                }
            """, pdf_url)

            if result.get('data'):
                data = base64.b64decode(result['data'])
                if is_pdf(data) and len(data) > 5000:
                    return data, 'panda985_search'

        return None,None
    except:
        return None,None


# ============================================================
# PDF verification
# ============================================================
def extract_words(text):
    stops = {'that','this','with','from','have','been','were','they','their',
             'which','about','these','those','into','than','also','after','between','other'}
    return {w for w in re.findall(r'[a-zA-Z]{4,}', text.lower()) if w not in stops}

def verify_pdf(content, expected_title, expected_author, expected_doi):
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(content); tmp_path = tmp.name
        doc = fitz.open(tmp_path)
        if doc.page_count == 0:
            doc.close(); os.unlink(tmp_path); return False, 0.0, '0 pages'
        text = ''
        for i in range(min(2, doc.page_count)):
            text += doc[i].get_text()
        doc.close(); os.unlink(tmp_path)
        if len(text) < 80:
            return True, 0.2, 'scanned'

        etw = extract_words(expected_title or '')
        tw = extract_words(text)
        title_score = len(etw & tw) / max(len(etw), 1) if etw else 0
        author_ok = False
        if expected_author:
            parts = [p.lower() for p in expected_author.split() if len(p) >= 2]
            author_ok = sum(1 for p in parts if p in text[:2000].lower()) >= min(2, len(parts))
        doi_ok = expected_doi and expected_doi.lower() in text.lower()

        conf = 0.0; dparts = []
        if title_score >= 0.25: conf += 0.45; dparts.append(f'title={title_score:.0%}')
        elif title_score >= 0.10: conf += 0.20; dparts.append(f'title~{title_score:.0%}')
        if author_ok: conf += 0.30; dparts.append('author')
        if doi_ok: conf += 0.25; dparts.append('doi')
        detail = '; '.join(dparts) if dparts else f'low({title_score:.0%})'
        passed = conf >= 0.3 or len(content) > 80000
        return passed, conf, detail
    except Exception as e:
        return True, 0.5, f'err:{e}'


# ============================================================
# Main download logic
# ============================================================
DOWNLOADERS = [
    ('PMC', L1_pmc),
    ('Unpaywall', L2_unpaywall),
    ('OpenAlex', L3_openalex),
    ('SemScholar', L4_semantic_scholar),
    ('Publisher', L5_publisher),
    ('SciHub-Mirror', L6_scihub_mirror),
    ('X-MOL', L7_xmol),
    ('Scholar673', L8_google_scholar_mirror),
    ('SciHub-Direct', L9_scihub_direct),
    ('Playwright', L10_playwright),
    ('Panda985', L11_panda985_search),
]

def download_one(rec, pdf_dir):
    doi_raw = rec.get('doi','')
    title = rec.get('title','')
    author = rec.get('first_author','')
    year = rec.get('year','')

    if not doi_raw or doi_raw in ('DOI NOT FOUND','null',None):
        return 'no_doi', None, None, 'no DOI'
    doi = clean_doi(doi_raw)
    if not doi:
        return 'no_doi', None, None, 'invalid DOI'

    fname = pdf_name(author, title, year)
    out_path = pdf_dir / fname
    if out_path.exists() and out_path.stat().st_size > 5000:
        return 'already_done', str(out_path), 'cached', str(out_path.stat().st_size//1024)+'KB'

    for label, fn in DOWNLOADERS:
        if label in ('Panda985',):
            content, source = fn(doi, title)
        else:
            content, source = fn(doi)
        if not content or len(content) < 5000:
            continue
        passed, conf, detail = verify_pdf(content, title, author, doi)
        os.makedirs(pdf_dir, exist_ok=True)
        with open(out_path, 'wb') as f: f.write(content)
        if passed:
            return 'ok', str(out_path), source, f'{len(content)//1024}KB {detail}'
        else:
            return 'uncertain', str(out_path), source, f'{len(content)//1024}KB {detail}'
    return 'failed', None, None, 'all 11 layers failed'


def load_progress(path):
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_progress(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def process_paper(key, cfg, dry_run=False):
    dir_str = cfg['dir']
    if os.path.isabs(dir_str):
        paper_dir = Path(dir_str)
    else:
        paper_dir = PAPERS_DIR / dir_str
    json_path = (paper_dir / cfg['json']) if not os.path.isabs(cfg['json']) else Path(cfg['json'])
    # Find the actual extracted_data.json if it's in a subpath
    if not json_path.exists():
        json_path = paper_dir / 'extracted_data.json'
    xlsx_path = paper_dir / cfg['xlsx']
    pdf_dir = paper_dir / 'pdfs'
    prog_path = paper_dir / 'download_progress.json'

    if not json_path.exists():
        print(f'  [skip] {key}: {json_path} missing')
        return None

    with open(json_path, 'r', encoding='utf-8') as f:
        records = json.load(f)
    progress = load_progress(prog_path)
    os.makedirs(pdf_dir, exist_ok=True)

    print(f'\n{"="*60}')
    print(f'  {key.upper()} -- {len(records)} papers')
    print(f'  PDF -> {pdf_dir}')
    print(f'{"="*60}')

    results = []; ok = unc = fail = nodoi = 0

    for i, rec in enumerate(records):
        rkey = f"{key}_{rec.get('ref', i)}"; no = rec.get('no', i+1)
        if rkey in progress and progress[rkey].get('status') in ('ok','already_done'):
            pres = progress[rkey]
            results.append({'no':no,'status':pres['status'],'pdf_path':pres.get('pdf_path',''),
                           'source':pres.get('source',''),'details':pres.get('details','')})
            ok += 1; continue

        info = f"[{no:2d}/{len(records):2d}] {rec.get('first_author','?')[:20]}"
        if dry_run:
            print(f'  {info} dry-run'); continue

        status, pdf_path, source, detail = download_one(rec, pdf_dir)
        res = {'no':no,'ref':rec.get('ref','?'),'author':rec.get('first_author',''),
               'doi':rec.get('doi',''),'status':status,'pdf_path':pdf_path or '',
               'source':source or '','details':detail or ''}
        results.append(res); progress[rkey] = res

        if status in ('ok','already_done'):
            ok += 1; print(f'  {info} OK {source}')
        elif status == 'uncertain':
            unc += 1; print(f'  {info} ~ {source} ({detail})')
        elif status == 'failed':
            fail += 1; print(f'  {info} FAIL')
        else:
            nodoi += 1; print(f'  {info} NO DOI')

        save_progress(prog_path, progress)
        time.sleep(0.3)

    print(f'\n  Result: OK={ok} ~{unc} FAIL={fail} NODOI={nodoi}')
    if xlsx_path.exists() and not dry_run:
        update_excel(xlsx_path, results)
    return results


# ============================================================
# Excel coloring
# ============================================================
GREEN = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
RED = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
YELLOW = PatternFill(start_color='FFEB9C', end_color='FFEB9C', fill_type='solid')
BLUE = PatternFill(start_color='D9E2F3', end_color='D9E2F3', fill_type='solid')
NAVY = PatternFill(start_color='1A365D', end_color='1A365D', fill_type='solid')
BORDER = Border(left=Side('thin','D0D0D0'), right=Side('thin','D0D0D0'),
                top=Side('thin','D0D0D0'), bottom=Side('thin','D0D0D0'))

def update_excel(xlsx_path, results):
    wb = openpyxl.load_workbook(xlsx_path); ws = wb.active
    existing = ws.max_column
    sc, fc = existing+1, existing+2
    for col_idx, width in [(sc,30),(fc,55)]:
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width
    for c, text in [(sc,'PDF Status'),(fc,'PDF File')]:
        cell = ws.cell(row=3, column=c, value=text)
        cell.fill, cell.font, cell.border = NAVY, Font(color='FFFFFF', bold=True, size=11), BORDER
    rmap = {r['no']: r for r in results}
    for row in range(4, ws.max_row+1):
        no = ws.cell(row=row, column=1).value
        if no is None: continue
        try: no = int(no)
        except: continue
        res = rmap.get(no)
        if not res: continue
        st = res['status']
        if st in ('ok','already_done'):
            fill, txt = GREEN, res.get('source','')
        elif st == 'uncertain':
            fill, txt = YELLOW, res.get('source','')
        else:
            fill, txt = RED, 'FAILED'
        for c in range(1, fc+1): ws.cell(row=row, column=c).fill = fill
        ws.cell(row=row, column=sc, value=txt).fill = BLUE
        ws.cell(row=row, column=fc, value=os.path.basename(res.get('pdf_path','')) if res.get('pdf_path') else '-')
    wb.save(xlsx_path)
    print(f'  Excel updated: {os.path.basename(xlsx_path)}')


# ============================================================
# Entry point
# ============================================================
def main():
    global SKIP_VPN
    ap = argparse.ArgumentParser(description='Batch download PDFs -- 11-layer fallback')
    ap.add_argument('--paper','-p', choices=list(PAPERS.keys()), help='single paper')
    ap.add_argument('--dry-run', action='store_true', help='probe only')
    ap.add_argument('--skip-vpn', action='store_true', help='skip L9-L11 (VPN layers)')
    args = ap.parse_args()
    SKIP_VPN = args.skip_vpn

    if not SKIP_VPN:
        print('[VPN] L9-L11 enabled (Sci-Hub direct + Playwright + Panda985 search)')
    else:
        print('[skip-vpn] L9-L11 disabled')

    targets = [args.paper] if args.paper else list(PAPERS.keys())
    to, tf = 0, 0
    for k in targets:
        res = process_paper(k, PAPERS[k], dry_run=args.dry_run)
        if res:
            to += sum(1 for r in res if r['status'] in ('ok','already_done'))
            tf += sum(1 for r in res if r['status'] in ('failed','uncertain'))
    if not args.dry_run:
        print(f'\nALL DONE: OK={to} FAIL={tf}')


if __name__ == '__main__':
    main()
