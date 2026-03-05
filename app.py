import subprocess, sys, os, time
import streamlit as st

# ─── Install Chromium at runtime (runs once via sentinel file) ────────────────
# packages.txt is unreliable on Streamlit Cloud — we do it ourselves here.
_SENTINEL = os.path.expanduser("~/.chromium_ready")
if not os.path.exists(_SENTINEL):
    with st.spinner("⚙️ First-time setup: installing Chromium (takes ~60s)..."):
        cmds = [
            ["apt-get", "update", "-qq"],
            ["apt-get", "install", "-y", "-qq",
             "chromium", "chromium-driver",
             "libglib2.0-0", "libnss3", "libatk1.0-0",
             "libatk-bridge2.0-0", "libcups2", "libdrm2",
             "libxkbcommon0", "libxcomposite1", "libxdamage1",
             "libxfixes3", "libxrandr2", "libgbm1",
             "libasound2", "libpango-1.0-0", "libcairo2"],
        ]
        for cmd in cmds:
            subprocess.run(cmd, capture_output=True)
        # Try snap chromium as fallback
        r = subprocess.run(["which", "chromium"], capture_output=True, text=True)
        if not r.stdout.strip():
            subprocess.run(["apt-get", "install", "-y", "-qq", "chromium-browser", "chromium-chromedriver"],
                           capture_output=True)
        open(_SENTINEL, "w").close()
    st.rerun()
# ─────────────────────────────────────────────────────────────────────────────

import openpyxl
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
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
        transition: background-color 0.3s ease;
    }
    .stButton > button:hover { background-color: #106EBE; }
    .stExpander, .stMarkdown {
        background-color: white; border-radius: 8px;
        box-shadow: 0 1.6px 3.6px rgba(0,0,0,0.1), 0 0.3px 0.9px rgba(0,0,0,0.08);
        padding: 16px; margin-bottom: 16px;
    }
    .stFileUploader { border: 1px solid #D3D3D3; border-radius: 4px; padding: 8px; }
    section[data-testid="stSidebar"] { background-color: #FFFFFF; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .stTextInput > div > div > input { border-radius: 4px; border: 1px solid #D3D3D3; padding: 8px; }
    .stSelectbox > div > div { border-radius: 4px; border: 1px solid #D3D3D3; }
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
# EXISTING TOOL: Excel Stock Movement Filler  (UNCHANGED)
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
# NEW TOOL: EFRIS Invoice Enricher
# ─────────────────────────────────────────────────────────────────────────────

def _find_binary(names):
    """Return the first existing path from a list of candidates."""
    import shutil
    for n in names:
        p = shutil.which(n) or (n if os.path.exists(n) else None)
        if p:
            return p
    return None

def _get_chrome_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-extensions")
    options.add_argument("--single-process")
    options.add_argument("--no-zygote")

    browser = _find_binary([
        "chromium", "chromium-browser",
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "google-chrome", "google-chrome-stable",
    ])
    driver_bin = _find_binary([
        "chromedriver",
        "/usr/bin/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
    ])

    if browser:
        options.binary_location = browser
    if driver_bin:
        return webdriver.Chrome(service=Service(executable_path=driver_bin), options=options)

    # Last resort: webdriver-manager
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.core.os_manager import ChromeType
    try:
        drv = ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()
    except Exception:
        drv = ChromeDriverManager().install()
    return webdriver.Chrome(service=Service(executable_path=drv), options=options)


def _scrape_fdn(driver, fdn):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    items = []
    try:
        driver.get("https://efris.ura.go.ug/")
        wait = WebDriverWait(driver, 20)
        fdn_input = wait.until(EC.presence_of_element_located((By.XPATH,
            "//input[contains(@placeholder,'Fiscal Document') or "
            "contains(@placeholder,'fiscal') or contains(@placeholder,'FDN')]")))
        fdn_input.clear()
        fdn_input.send_keys(str(fdn))
        time.sleep(0.4)
        validate_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//button[contains(translate(.,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VALIDATE')]")))
        validate_btn.click()
        time.sleep(3)
        wait.until(EC.presence_of_element_located((By.XPATH,
            "//*[contains(text(),'erified') or contains(text(),'Validation Report')]")))
        time.sleep(1)
        view_btn = wait.until(EC.element_to_be_clickable((By.XPATH,
            "//button[contains(translate(.,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VIEW DOCUMENT')]")))
        view_btn.click()
        time.sleep(4)
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            time.sleep(2)
        for table in driver.find_elements(By.TAG_NAME, "table"):
            rows = table.find_elements(By.TAG_NAME, "tr")
            header_idx, col_map = None, {}
            for i, row in enumerate(rows):
                cells = row.find_elements(By.XPATH, ".//td | .//th")
                texts = [c.text.strip() for c in cells]
                upper = [t.upper() for t in texts]
                if header_idx is None:
                    if "ITEM" in upper and "QUANTITY" in upper:
                        header_idx = i
                        for j, h in enumerate(upper):
                            if h == "ITEM":                       col_map["item"]         = j
                            elif h == "QUANTITY":                 col_map["quantity"]     = j
                            elif "UNIT" in h and "MEASURE" in h: col_map["unit_measure"] = j
                            elif "UNIT" in h and "PRICE" in h:   col_map["unit_price"]   = j
                        continue
                if header_idx is not None and texts:
                    def _g(key, fb):
                        ix = col_map.get(key, fb)
                        return texts[ix] if ix < len(texts) else ""
                    item_name = _g("item", 1)
                    qty = _g("quantity", 2)
                    if item_name and qty:
                        items.append({"item": item_name, "quantity": qty,
                                      "unit_measure": _g("unit_measure", 3),
                                      "unit_price": _g("unit_price", 4)})
            if items:
                break
        if len(driver.window_handles) > 1:
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
    except Exception:
        try:
            if len(driver.window_handles) > 1:
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
        except Exception:
            pass
    return items


def fuzzy_match_product(target, candidates):
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
            '<div class="log-box">' + "<br>".join(log_lines[-60:]) + "</div>",
            unsafe_allow_html=True)

    # Show what binaries are available after our install
    import shutil
    for name in ["chromium", "chromium-browser", "chromedriver"]:
        p = shutil.which(name)
        log(f"{'✅' if p else '❌'}  {name}  →  {p or 'not found'}")

    log("🚀  Starting browser...")
    try:
        driver = _get_chrome_driver()
        log("✅  Browser started!")
    except Exception as e:
        st.error(f"Browser failed to start: {e}")
        return purchases_df

    fdn_cache = {}
    try:
        for idx, row in purchases_df.iterrows():
            fdn  = str(row.get("FDN", "")).strip()
            desc = str(row.get("Description of Goods", "")).strip()
            row_num = idx + 2
            progress_bar.progress((idx + 1) / total, text=f"Row {idx+1}/{total} — FDN: {fdn}")
            if not fdn or fdn.lower() == "nan":
                log(f"[Row {row_num}] ⚠️  Skipped — no FDN")
                continue
            if fdn not in fdn_cache:
                log(f"[Row {row_num}] 🔍  FDN: {fdn}  |  Product: {desc}")
                try:
                    fdn_cache[fdn] = _scrape_fdn(driver, fdn)
                    log(f"[Row {row_num}] ✅  {len(fdn_cache[fdn])} item(s) found")
                except Exception as e:
                    fdn_cache[fdn] = []
                    log(f"[Row {row_num}] ❌  Error: {e}")
            else:
                log(f"[Row {row_num}] 📋  Cached — FDN: {fdn}")
            invoice_items = fdn_cache[fdn]
            if not invoice_items:
                log(f"[Row {row_num}] ⚠️  No items — FDN: {fdn}")
                continue
            invoice_names = [i["item"] for i in invoice_items]
            matched = fuzzy_match_product(desc, invoice_names)
            if matched:
                hit = next((i for i in invoice_items if i["item"].strip().upper() == matched.strip().upper()), None)
                if hit:
                    purchases_df.at[idx, "Quantity"]     = hit["quantity"]
                    purchases_df.at[idx, "Unit Measure"] = hit["unit_measure"]
                    purchases_df.at[idx, "Unit Price"]   = hit["unit_price"]
                    log(f"[Row {row_num}] ✔️  '{desc}' → Qty:{hit['quantity']}  Unit:{hit['unit_measure']}  Price:{hit['unit_price']}")
                else:
                    log(f"[Row {row_num}] ⚠️  Lookup failed: {matched}")
            else:
                log(f"[Row {row_num}] ⚠️  No match for '{desc}'")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    log("🏁  All rows processed.")
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
        hi_fill = PatternFill("solid", fgColor="FFF2CC")
        new_cols = {"Quantity", "Unit Measure", "Unit Price"}
        for i, c in enumerate(ws[1]):
            if c.value in new_cols:
                for row in ws.iter_rows(min_row=2, min_col=i+1, max_col=i+1):
                    for cell in row:
                        cell.fill = hi_fill
    output.seek(0)
    return output


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR NAVIGATION
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("Navigation")
tool = st.sidebar.selectbox("Select Automation Tool", [
    "Excel Stock Movement Filler",
    "EFRIS Invoice Enricher",
    "Audit Compliance Checker (Coming Soon)",
    "Financial Report Generator (Coming Soon)",
    "Sales Dashboard (Inspired by Reference)",
])

st.title("Automation Hub")
st.markdown("Your professional platform for automating tasks. Clean, modern design inspired by Microsoft interfaces.")

if tool == "Excel Stock Movement Filler":
    st.header("Excel Stock Movement Filler")
    output_name   = st.text_input("Output Filename (will add .xlsx)", value="filled_template")
    output_name   = output_name.removesuffix('.xlsx').strip() + ".xlsx"
    template_file = st.file_uploader("Upload Template (.xlsx)", type="xlsx")
    report_file   = st.file_uploader("Upload Movement Report (.xlsx)", type="xlsx")
    damages_file  = st.file_uploader("Upload Damages (.xlsx)", type="xlsx")
    if st.button("Process Files"):
        if template_file and report_file and damages_file:
            with st.spinner("Processing..."):
                output_bytes = process_excel(template_file, report_file, damages_file, output_name)
                if output_bytes:
                    st.success("Processing complete!")
                    st.download_button(label="Download Filled Template", data=output_bytes,
                        file_name=output_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("Upload all required files.")

elif tool == "EFRIS Invoice Enricher":
    st.header("EFRIS Invoice Enricher")
    st.markdown("""
    Upload your **Purchases Report** (.xlsx). The tool will:
    1. Read each row's **FDN** and **Description of Goods**
    2. Open EFRIS in a headless browser, validate each FDN and view the invoice
    3. Match the product and extract **Quantity**, **Unit Measure**, **Unit Price**
    4. Generate a downloadable enriched Excel file (new columns highlighted in yellow)

    > ⚠️ May take several minutes for large files. Each unique FDN is only scraped once.
    """)
    col1, col2 = st.columns([2, 1])
    with col1:
        purchases_file = st.file_uploader("Upload Purchases Report (.xlsx)", type=["xlsx"], key="efris_upload")
    with col2:
        output_filename = st.text_input("Output Filename", value="enriched_purchases_report", key="efris_out")
        output_filename = output_filename.removesuffix(".xlsx").strip() + ".xlsx"
    if purchases_file:
        try:
            preview_df = pd.read_excel(purchases_file, nrows=5)
            purchases_file.seek(0)
            st.markdown("**Preview (first 5 rows):**")
            st.dataframe(preview_df, use_container_width=True)
            missing = {"FDN", "Description of Goods"} - set(preview_df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}")
                purchases_file = None
        except Exception as e:
            st.error(f"Could not read file: {e}")
            purchases_file = None
    if st.button("🚀 Start EFRIS Validation & Enrichment",
                 disabled=(purchases_file is None), key="efris_run"):
        st.markdown("---")
        st.markdown("### Live Progress")
        progress_bar    = st.progress(0, text="Starting...")
        log_placeholder = st.empty()
        try:
            full_df     = pd.read_excel(purchases_file)
            enriched_df = run_efris_enrichment(full_df, log_placeholder, progress_bar)
            progress_bar.progress(1.0, text="✅ Done!")
            st.success("Enrichment complete!")
            output_bytes = build_output_excel(enriched_df)
            st.download_button(label="⬇️ Download Enriched Excel", data=output_bytes,
                file_name=output_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            filled = enriched_df["Quantity"].notna().sum()
            st.info(f"📊 **{filled} / {len(enriched_df)}** rows successfully enriched.")
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")

elif tool == "Audit Compliance Checker (Coming Soon)":
    st.header("Audit Compliance Checker")
    st.info("Upload financial docs for automated compliance checks. Coming soon.")

elif tool == "Financial Report Generator (Coming Soon)":
    st.header("Financial Report Generator")
    st.info("Generate audit-ready reports from raw data. Feature in development.")

elif tool == "Sales Dashboard (Inspired by Reference)":
    st.header("Sales Dashboard")
    st.info("Interactive sales reports with filters, charts, and exports. Upload data to get started.")
    sales_data = st.file_uploader("Upload Sales Data (.xlsx)", type="xlsx")
    if sales_data:
        st.write("Data uploaded – dashboard coming soon!")

st.sidebar.markdown("---")
st.sidebar.info("Powered by Streamlit. Deploy your own or customize further.")
