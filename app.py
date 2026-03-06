import os, time, re, glob
import streamlit as st
import openpyxl
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
from io import BytesIO
import difflib

st.markdown("""
<style>
    .stApp { background-color: #F3F3F3; color: #000000; font-family: 'Segoe UI', sans-serif; }
    h1, h2, h3 { color: #0078D4; font-weight: 600; }
    .stButton > button {
        background-color: #0078D4; color: white; border-radius: 4px;
        border: none; padding: 8px 16px; font-weight: 500;
    }
    .stButton > button:hover { background-color: #106EBE; }
    p, li, span, div { color: #000000 !important; }
    .log-box {
        background: #1e1e1e; color: #00ff88; font-family: monospace;
        font-size: 13px; padding: 12px 16px; border-radius: 6px;
        max-height: 320px; overflow-y: auto; white-space: pre-wrap;
    }
</style>
""", unsafe_allow_html=True)

st.set_page_config(page_title="Automation Hub", layout="wide", page_icon="🤖")

# ─────────────────────────────────────────────────────────────────────────────
# TOOL 1: Excel Stock Movement Filler  (UNCHANGED)
# ─────────────────────────────────────────────────────────────────────────────

def normalize_name(name):
    if not name:
        return ""
    return str(name).upper().replace(" ", "").replace("S", "")

def excel_serial_to_date(serial):
    if isinstance(serial, (float, int)):
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    if isinstance(serial, datetime):
        return serial.date()
    return None

def process_excel(template_file, report_file, damages_file, output_name="filled_template.xlsx"):
    try:
        template_bytes = template_file.read()
        wb_temp = openpyxl.load_workbook(BytesIO(template_bytes))
        ws_temp = wb_temp['Sheet1']
        template_first_date = None
        for r in range(1, ws_temp.max_row + 1):
            date_val = ws_temp.cell(r, 1).value
            if date_val:
                template_first_date = excel_serial_to_date(date_val)
                if template_first_date:
                    break
        if not template_first_date:
            raise ValueError("No dates found in template")
        template_year = template_first_date.year
        report_df  = pd.read_excel(report_file)
        damages_df = pd.read_excel(damages_file)
        report_df['date'] = pd.to_datetime(report_df['date'], dayfirst=True)
        report_df['date'] = report_df['date'].apply(lambda d: d.replace(year=template_year))
        report_df_sorted = report_df.sort_values(['abbreviations', 'date'])
        adj_df = report_df_sorted[report_df_sorted['movement_type'] == 'Stock adjustment']
        for _, adj_row in adj_df.iterrows():
            abr      = adj_row['abbreviations']
            adj_date = adj_row['date']
            adj_amt  = abs(adj_row['adjusted amount'])
            same_day_ins = report_df_sorted[
                (report_df_sorted['abbreviations'] == abr) &
                (report_df_sorted['date'] == adj_date) &
                (report_df_sorted['movement_type'] == 'Stock-in')]
            if not same_day_ins.empty:
                i = same_day_ins.index[-1]
                report_df_sorted.at[i, 'adjusted amount'] = max(0, report_df_sorted.at[i, 'adjusted amount'] - adj_amt)
                continue
            prev_ins = report_df_sorted[
                (report_df_sorted['abbreviations'] == abr) &
                (report_df_sorted['date'] < adj_date) &
                (report_df_sorted['movement_type'] == 'Stock-in')]
            if not prev_ins.empty:
                i = prev_ins.index[-1]
                report_df_sorted.at[i, 'adjusted amount'] = max(0, report_df_sorted.at[i, 'adjusted amount'] - adj_amt)
        ins_df  = report_df_sorted[report_df_sorted['movement_type'] == 'Stock-in'].groupby(
            ['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='stock_in')
        outs_df = report_df_sorted[report_df_sorted['movement_type'] == 'Invoice Issue'].groupby(
            ['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='sales')
        first_appearances = report_df_sorted.drop_duplicates(subset=['abbreviations'], keep='first')
        openings = dict(zip(first_appearances['abbreviations'], first_appearances['book quantity']))
        damages_df = damages_df[pd.notna(damages_df['quantity'])]
        wb = openpyxl.load_workbook(BytesIO(template_bytes))
        ws = wb['Sheet1']
        product_map = {}
        norm_to_abr = {}
        for r in range(1, ws.max_row + 1):
            full = ws.cell(r, 2).value
            abr  = ws.cell(r, 3).value
            if full and abr:
                product_map[str(full).strip().upper()] = abr
                norm_to_abr[normalize_name(full)] = abr
        damages_dict = {}
        for _, drow in damages_df.iterrows():
            full = str(drow['good name']).strip().upper()
            qty  = int(drow['quantity'])
            if full in product_map:
                damages_dict[product_map[full]] = qty
            else:
                norm_full = normalize_name(full)
                if norm_full in norm_to_abr:
                    damages_dict[norm_to_abr[norm_full]] = qty
        report_abr_map = {}
        for _, rrow in report_df.iterrows():
            full       = str(rrow['good name']).strip().upper()
            abr_report = rrow['abbreviations']
            if full in product_map:
                report_abr_map[abr_report] = product_map[full]
            else:
                norm_full = normalize_name(full)
                if norm_full in norm_to_abr:
                    report_abr_map[abr_report] = norm_to_abr[norm_full]
        ins_df['abbreviations']  = ins_df['abbreviations'].map(report_abr_map).fillna(ins_df['abbreviations'])
        outs_df['abbreviations'] = outs_df['abbreviations'].map(report_abr_map).fillna(outs_df['abbreviations'])
        mapped_openings = {report_abr_map.get(k, k): v for k, v in openings.items()}
        date_abr_to_row = {}
        current_date = None
        for r in range(1, ws.max_row + 1):
            date_val = ws.cell(r, 1).value
            if date_val:
                current_date = excel_serial_to_date(date_val)
            abr = ws.cell(r, 3).value
            if current_date and abr:
                date_abr_to_row[(current_date, abr)] = r
        if date_abr_to_row:
            first_date = min(d[0] for d in date_abr_to_row)
            for abr, open_bal in mapped_openings.items():
                key = (first_date, abr)
                if key in date_abr_to_row:
                    ws.cell(date_abr_to_row[key], 4).value = open_bal
        damages_per_day = {}
        for abr, total_d in damages_dict.items():
            abr_ins = ins_df[ins_df['abbreviations'] == abr]
            if abr_ins.empty:
                continue
            days           = abr_ins['date'].dt.date.values
            stock_ins      = abr_ins['stock_in'].values
            total_stock_in = stock_ins.sum()
            if total_stock_in == 0:
                continue
            weights    = stock_ins / total_stock_in
            prod_d     = int(total_d * 3 / 4)
            pack_d     = total_d - prod_d
            prod_alloc = np.zeros(len(days), dtype=int)
            pack_alloc = np.zeros(len(days), dtype=int)
            for _ in range(prod_d):
                prod_alloc[np.random.choice(len(days), p=weights)] += 1
            for _ in range(pack_d):
                pack_alloc[np.random.choice(len(days), p=weights)] += 1
            damages_per_day[abr] = {days[i]: (prod_alloc[i], pack_alloc[i]) for i in range(len(days))}
        for _, irow in ins_df.iterrows():
            dt       = irow['date'].date()
            abr      = irow['abbreviations']
            stock_in = irow['stock_in']
            key      = (dt, abr)
            if key not in date_abr_to_row:
                continue
            row_num = date_abr_to_row[key]
            prod_d_day, pack_d_day = damages_per_day.get(abr, {}).get(dt, (0, 0))
            total_d_day = prod_d_day + pack_d_day
            ws.cell(row_num, 7).value  = stock_in + total_d_day
            ws.cell(row_num, 8).value  = prod_d_day
            ws.cell(row_num, 10).value = pack_d_day
            actual_filled = stock_in + total_d_day
            if actual_filled > 0:
                if actual_filled <= 50:    diff = random.randint(-1, 1)
                elif actual_filled <= 200: diff = random.randint(-4, 6)
                else:                      diff = random.randint(-6, 12)
                ws.cell(row_num, 6).value = max(0, actual_filled + diff)
        for _, orow in outs_df.iterrows():
            dt  = orow['date'].date()
            abr = orow['abbreviations']
            key = (dt, abr)
            if key in date_abr_to_row:
                ws.cell(date_abr_to_row[key], 13).value = orow['sales']
        output_bytes = BytesIO()
        wb.save(output_bytes)
        output_bytes.seek(0)
        return output_bytes
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# TOOL 2: EFRIS Invoice Enricher
# ─────────────────────────────────────────────────────────────────────────────

def _parse_pdf_bytes(pdf_bytes):
    """Extract Section D line items from EFRIS invoice PDF bytes."""
    import pdfplumber, io
    items = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                # Try table extraction first
                for table in (page.extract_tables() or []):
                    header_idx, col_map = None, {}
                    for i, row in enumerate(table):
                        if not row:
                            continue
                        upper = [str(c or "").upper().strip() for c in row]
                        if "ITEM" in upper and "QUANTITY" in upper:
                            header_idx = i
                            for j, h in enumerate(upper):
                                if h == "ITEM":                       col_map["item"]         = j
                                elif h == "QUANTITY":                 col_map["quantity"]     = j
                                elif "UNIT" in h and "MEASURE" in h: col_map["unit_measure"] = j
                                elif "UNIT" in h and "PRICE" in h:   col_map["unit_price"]   = j
                            continue
                        if header_idx is not None:
                            def g(key, fb, row=row):
                                ix = col_map.get(key, fb)
                                return str(row[ix] or "").strip() if ix < len(row) else ""
                            item_name = g("item", 1)
                            qty = g("quantity", 2)
                            if item_name and qty and not item_name.upper().startswith("TAX"):
                                items.append({
                                    "item": item_name,
                                    "quantity": qty,
                                    "unit_measure": g("unit_measure", 3),
                                    "unit_price": g("unit_price", 4),
                                })
                    if items:
                        return items

                # Fallback: raw text line-by-line
                text = page.extract_text() or ""
                in_d = False
                for line in text.split("\n"):
                    line = line.strip()
                    if "Section D" in line or "Goods & Services" in line:
                        in_d = True
                        continue
                    if "Section E" in line or "Tax Details" in line:
                        break
                    if not in_d:
                        continue
                    # e.g. "1. Red Oxide GL - 4Ltr 10 TN-Tin 39,000 390,000 A"
                    m = re.match(
                        r"\d+\.?\s+(.+?)\s+(\d[\d,]*)\s+(\S[\S\-]*)\s+([\d,]+)\s+[\d,]+",
                        line
                    )
                    if m:
                        items.append({
                            "item": m.group(1).strip(),
                            "quantity": m.group(2).strip(),
                            "unit_measure": m.group(3).strip(),
                            "unit_price": m.group(4).strip(),
                        })
    except Exception as e:
        print(f"[PDF PARSE ERROR] {e}")
    return items


def _get_driver():
    """Build a Selenium Chrome driver using system Chromium installed via Dockerfile."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-zygote")
    options.add_argument("--single-process")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--shm-size=1gb")
    # Enable performance/network logging so we can capture PDF URL
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    browser_candidates = [
        "/usr/lib/chromium/chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    driver_candidates = [
        "/usr/lib/chromium/chromedriver",
        "/usr/bin/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
    ]

    # Also glob-search under /usr in case paths differ
    if not any(os.path.exists(p) for p in browser_candidates):
        hits = glob.glob("/usr/**/chromium", recursive=True)
        browser_candidates = [h for h in hits if os.access(h, os.X_OK)] + browser_candidates

    if not any(os.path.exists(p) for p in driver_candidates):
        hits = glob.glob("/usr/**/chromedriver", recursive=True)
        driver_candidates = [h for h in hits if os.access(h, os.X_OK)] + driver_candidates

    browser = next((p for p in browser_candidates if os.path.exists(p)), None)
    driver_bin = next((p for p in driver_candidates if os.path.exists(p)), None)

    print(f"[CHROMIUM]    {browser}")
    print(f"[CHROMEDRIVER] {driver_bin}")

    if browser:
        options.binary_location = browser
    if driver_bin:
        return webdriver.Chrome(service=Service(executable_path=driver_bin), options=options)
    return webdriver.Chrome(options=options)


def _scrape_fdn(driver, fdn, log_fn=None):
    """
    Validate FDN on EFRIS, capture the invoice PDF via CDP network logs,
    download it and parse with pdfplumber.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import requests as req_lib, json

    def dbg(msg):
        print(msg)
        if log_fn:
            log_fn(msg)

    items = []
    original_handle = driver.current_window_handle

    try:
        driver.get("https://efris.ura.go.ug/")
        wait = WebDriverWait(driver, 20)
        dbg("  [1] Loaded EFRIS")

        # Type FDN
        inp = wait.until(EC.presence_of_element_located((By.XPATH,
            "//input[@placeholder and ("
            "contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'fiscal')"
            " or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'fdn')"
            ")]"
        )))
        inp.clear()
        inp.send_keys(str(fdn))
        time.sleep(0.4)
        dbg("  [2] FDN typed")

        # Click Validate
        btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//button[contains(translate(normalize-space(.),"
            "'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VALIDATE')]"
        )))
        btn.click()
        time.sleep(3)
        dbg("  [3] Validated")

        # Wait for verification
        wait.until(EC.presence_of_element_located((By.XPATH,
            "//*[contains(text(),'erified') or contains(text(),'Validation')]"
        )))
        time.sleep(1)
        dbg("  [4] Invoice verified")

        handles_before = set(driver.window_handles)

        # Click View Document
        vbtn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//button[contains(translate(normalize-space(.),"
            "'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VIEW DOCUMENT')]"
        )))
        vbtn.click()
        time.sleep(5)
        dbg("  [5] View Document clicked")

        # ── Strategy 1: capture PDF URL from CDP performance logs ─────────────
        pdf_url = None
        try:
            logs = driver.get_log("performance")
            for entry in logs:
                msg = json.loads(entry["message"])["message"]
                if msg.get("method") == "Network.responseReceived":
                    url = msg.get("params", {}).get("response", {}).get("url", "")
                    mime = msg.get("params", {}).get("response", {}).get("mimeType", "")
                    if "pdf" in mime.lower() or (url and ".pdf" in url.lower()):
                        pdf_url = url
                        dbg(f"  [6-CDP] PDF URL: {pdf_url}")
                        break
        except Exception as e:
            dbg(f"  [6-CDP] Log error: {e}")

        # ── Strategy 2: new tab URL ───────────────────────────────────────────
        if not pdf_url:
            new_handles = set(driver.window_handles) - handles_before
            if new_handles:
                driver.switch_to.window(list(new_handles)[0])
                time.sleep(2)
                pdf_url = driver.current_url
                dbg(f"  [6-TAB] New tab URL: {pdf_url}")
                driver.close()
                driver.switch_to.window(original_handle)
            else:
                cur = driver.current_url
                dbg(f"  [6-SAME] Same tab URL: {cur}")
                if "efris.ura.go.ug" in cur and cur != "https://efris.ura.go.ug/":
                    pdf_url = cur

        # ── Strategy 3: scan page source for any URL with pdf/invoice ─────────
        if not pdf_url:
            src = driver.page_source
            # Find all http URLs in the page
            all_urls = re.findall(r'https?://[^\s"\'<>\\]+', src)
            for u in all_urls:
                if ".pdf" in u.lower() or "printInvoice" in u or "viewDoc" in u:
                    pdf_url = u
                    dbg(f"  [6-SRC] Found in source: {pdf_url}")
                    break

        # ── Strategy 4: check embedded elements ──────────────────────────────
        if not pdf_url:
            for tag in ["embed", "iframe", "object", "a"]:
                for el in driver.find_elements(By.TAG_NAME, tag):
                    for attr in ["src", "data", "href"]:
                        val = el.get_attribute(attr) or ""
                        if val and ("pdf" in val.lower() or "invoice" in val.lower()):
                            pdf_url = val
                            dbg(f"  [6-EL] {tag}.{attr}: {pdf_url}")
                            break
                    if pdf_url:
                        break
                if pdf_url:
                    break

        dbg(f"  [7] Final PDF URL: {pdf_url}")

        # ── Download PDF ──────────────────────────────────────────────────────
        pdf_bytes = None
        if pdf_url and pdf_url.startswith("http"):
            cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Referer": "https://efris.ura.go.ug/",
            }
            try:
                resp = req_lib.get(pdf_url, cookies=cookies, headers=headers, timeout=30)
                dbg(f"  [8] Download: {resp.status_code}, {len(resp.content)} bytes, type: {resp.headers.get('content-type','?')}")
                if resp.status_code == 200 and len(resp.content) > 500:
                    pdf_bytes = resp.content
            except Exception as e:
                dbg(f"  [8] Download error: {e}")
        elif pdf_url and pdf_url.startswith("blob:"):
            dbg("  [8] Blob URL — extracting via JS")
            try:
                js = ("var cb=arguments[arguments.length-1];"
                      "fetch(arguments[0]).then(r=>r.arrayBuffer())"
                      ".then(b=>cb(Array.from(new Uint8Array(b))))"
                      ".catch(e=>cb([]));")
                arr = driver.execute_async_script(js, pdf_url)
                if arr:
                    pdf_bytes = bytes(arr)
                    dbg(f"  [8] Blob: {len(pdf_bytes)} bytes")
            except Exception as e:
                dbg(f"  [8] Blob error: {e}")

        # ── Parse PDF ─────────────────────────────────────────────────────────
        if pdf_bytes:
            dbg(f"  [9] Parsing PDF ({len(pdf_bytes)} bytes)...")
            items = _parse_pdf_bytes(pdf_bytes)
            dbg(f"  [9] Parsed {len(items)} items: {[i['item'] for i in items]}")
        else:
            dbg("  [9] No PDF bytes captured")

    except Exception as e:
        dbg(f"  [ERR] {e}")

    try:
        if driver.current_window_handle != original_handle:
            driver.switch_to.window(original_handle)
    except Exception:
        pass

    return items


def fuzzy_match(target, candidates):
    t  = target.strip().upper()
    cs = [c.strip().upper() for c in candidates]
    ms = difflib.get_close_matches(t, cs, n=1, cutoff=0.55)
    return candidates[cs.index(ms[0])] if ms else None


def run_efris_enrichment(purchases_df, log_placeholder, progress_bar):
    for col in ["Quantity", "Unit Measure", "Unit Price"]:
        if col not in purchases_df.columns:
            purchases_df[col] = None

    total, log_lines = len(purchases_df), []

    def log(msg):
        log_lines.append(msg)
        log_placeholder.markdown(
            '<div class="log-box">' + "<br>".join(log_lines[-80:]) + "</div>",
            unsafe_allow_html=True)

    # Show binary diagnostics
    import shutil
    for name in ["chromium", "chromium-browser", "chromedriver"]:
        p = shutil.which(name) or next(
            (c for c in [f"/usr/lib/chromium/{name}", f"/usr/bin/{name}"] if os.path.exists(c)), None)
        log(f"{'✅' if p else '❌'}  {name} → {p or 'not found'}")

    log("🚀 Starting browser...")
    try:
        driver = _get_driver()
        log("✅ Browser started!")
    except Exception as e:
        st.error(f"Browser failed: {e}")
        return purchases_df

    fdn_cache = {}
    try:
        for idx, row in purchases_df.iterrows():
            fdn  = str(row.get("FDN", "")).strip()
            desc = str(row.get("Description of Goods", "")).strip()
            row_num = idx + 2
            progress_bar.progress(min((idx + 1) / total, 1.0), text=f"Row {idx+1}/{total} — {fdn}")

            if not fdn or fdn.lower() == "nan":
                log(f"[Row {row_num}] ⚠️  Skipped — no FDN")
                continue

            if fdn not in fdn_cache:
                log(f"[Row {row_num}] 🔍  FDN: {fdn} | {desc}")
                try:
                    fdn_cache[fdn] = _scrape_fdn(driver, fdn, log_fn=log)
                    log(f"[Row {row_num}] ✅  {len(fdn_cache[fdn])} item(s) found")
                except Exception as e:
                    fdn_cache[fdn] = []
                    log(f"[Row {row_num}] ❌  {e}")
            else:
                log(f"[Row {row_num}] 📋  Cached — {fdn}")

            invoice_items = fdn_cache[fdn]
            if not invoice_items:
                continue

            invoice_names = [i["item"] for i in invoice_items]
            matched = fuzzy_match(desc, invoice_names)
            if matched:
                hit = next((i for i in invoice_items
                            if i["item"].strip().upper() == matched.strip().upper()), None)
                if hit:
                    purchases_df.at[idx, "Quantity"]     = hit["quantity"]
                    purchases_df.at[idx, "Unit Measure"] = hit["unit_measure"]
                    purchases_df.at[idx, "Unit Price"]   = hit["unit_price"]
                    log(f"[Row {row_num}] ✔️  '{desc}' → Qty:{hit['quantity']} Unit:{hit['unit_measure']} Price:{hit['unit_price']}")
                else:
                    log(f"[Row {row_num}] ⚠️  Lookup failed: {matched}")
            else:
                log(f"[Row {row_num}] ⚠️  No match for '{desc}'")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    log("🏁 All rows processed.")
    return purchases_df


def build_output_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Purchases Report")
        ws = writer.sheets["Purchases Report"]
        for col_cells in ws.columns:
            max_len = max((len(str(c.value or "")) for c in col_cells), default=10)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 50)
        from openpyxl.styles import PatternFill, Font, Alignment
        hdr_fill = PatternFill("solid", fgColor="0078D4")
        for cell in ws[1]:
            cell.fill = hdr_fill
            cell.font = Font(bold=True, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center")
        hi_fill  = PatternFill("solid", fgColor="FFF2CC")
        new_cols = {"Quantity", "Unit Measure", "Unit Price"}
        for i, c in enumerate(ws[1]):
            if c.value in new_cols:
                for row in ws.iter_rows(min_row=2, min_col=i+1, max_col=i+1):
                    for cell in row:
                        cell.fill = hi_fill
    output.seek(0)
    return output


# ─────────────────────────────────────────────────────────────────────────────
# NAVIGATION
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("Navigation")
tool = st.sidebar.selectbox("Select Tool", [
    "Excel Stock Movement Filler",
    "EFRIS Invoice Enricher",
    "Audit Compliance Checker (Coming Soon)",
    "Financial Report Generator (Coming Soon)",
    "Sales Dashboard (Coming Soon)",
])

st.title("Automation Hub")
st.markdown("Your professional platform for automating tasks.")

if tool == "Excel Stock Movement Filler":
    st.header("Excel Stock Movement Filler")
    output_name   = st.text_input("Output Filename", value="filled_template")
    output_name   = output_name.removesuffix(".xlsx").strip() + ".xlsx"
    template_file = st.file_uploader("Upload Template (.xlsx)", type="xlsx")
    report_file   = st.file_uploader("Upload Movement Report (.xlsx)", type="xlsx")
    damages_file  = st.file_uploader("Upload Damages (.xlsx)", type="xlsx")
    if st.button("Process Files"):
        if template_file and report_file and damages_file:
            with st.spinner("Processing..."):
                out = process_excel(template_file, report_file, damages_file, output_name)
                if out:
                    st.success("Done!")
                    st.download_button("Download", data=out, file_name=output_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("Upload all 3 files.")

elif tool == "EFRIS Invoice Enricher":
    st.header("EFRIS Invoice Enricher")
    st.markdown("""
    Upload your **Purchases Report** (.xlsx) with columns **FDN** and **Description of Goods**.
    The tool opens each invoice on EFRIS, reads the PDF, and fills in
    **Quantity**, **Unit Measure**, and **Unit Price** for every row.
    > Duplicate FDNs are only fetched once.
    """)
    col1, col2 = st.columns([2, 1])
    with col1:
        purchases_file = st.file_uploader("Upload Purchases Report (.xlsx)", type=["xlsx"], key="ef_up")
    with col2:
        out_name = st.text_input("Output Filename", value="enriched_purchases", key="ef_out")
        out_name = out_name.removesuffix(".xlsx").strip() + ".xlsx"

    if purchases_file:
        try:
            prev = pd.read_excel(purchases_file, nrows=5)
            purchases_file.seek(0)
            st.markdown("**Preview:**")
            st.dataframe(prev, use_container_width=True)
            missing = {"FDN", "Description of Goods"} - set(prev.columns)
            if missing:
                st.error(f"Missing columns: {missing}")
                purchases_file = None
        except Exception as e:
            st.error(str(e))
            purchases_file = None

    if st.button("🚀 Start Enrichment", disabled=(purchases_file is None), key="ef_run"):
        st.markdown("---")
        prog = st.progress(0, text="Starting...")
        log_ph = st.empty()
        try:
            df = pd.read_excel(purchases_file)
            enriched = run_efris_enrichment(df, log_ph, prog)
            prog.progress(1.0, text="✅ Done!")
            st.success("Complete!")
            st.download_button("⬇️ Download Enriched Excel",
                data=build_output_excel(enriched), file_name=out_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            filled = enriched["Quantity"].notna().sum()
            st.info(f"📊 {filled} / {len(enriched)} rows enriched.")
        except Exception as e:
            st.error(f"Error: {e}")

elif "Coming Soon" in tool:
    st.info("Feature coming soon.")

st.sidebar.markdown("---")
st.sidebar.info("Powered by Streamlit on Railway.")
