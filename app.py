# ── Auto-install Playwright Chromium browser on first run (Streamlit Cloud) ──
# Uses a sentinel file so install only runs once per container, not every rerun.
import subprocess
import sys
import os

_SENTINEL = os.path.join(os.path.expanduser("~"), ".pw_chromium_installed")
if not os.path.exists(_SENTINEL):
    # Download the Chromium binary.
    # System libraries are handled by packages.txt (apt-installed by Streamlit Cloud as root).
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True, timeout=300
    )
    open(_SENTINEL, "w").close()
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import openpyxl
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import random
from io import BytesIO
import asyncio
import difflib


# Custom CSS for Microsoft Store-like appearance (Fluent Design inspired) - fixed colors for visibility
st.markdown("""
<style>
    /* General body */
    .stApp {
        background-color: #F3F3F3;
        color: #000000;
        font-family: 'Segoe UI', sans-serif;
    }
    
    /* Headers */
    h1, h2, h3 {
        color: #0078D4;
        font-weight: 600;
    }
    
    /* Buttons */
    .stButton > button {
        background-color: #0078D4;
        color: white;
        border-radius: 4px;
        border: none;
        padding: 8px 16px;
        font-weight: 500;
        transition: background-color 0.3s ease;
    }
    .stButton > button:hover {
        background-color: #106EBE;
    }
    
    /* Cards / Containers */
    .stExpander, .stMarkdown {
        background-color: white;
        border-radius: 8px;
        box-shadow: 0 1.6px 3.6px rgba(0,0,0,0.1), 0 0.3px 0.9px rgba(0,0,0,0.08);
        padding: 16px;
        margin-bottom: 16px;
    }
    
    /* File uploader */
    .stFileUploader {
        border: 1px solid #D3D3D3;
        border-radius: 4px;
        padding: 8px;
    }
    
    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #FFFFFF;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .sidebar .sidebar-content {
        padding: 16px;
    }
    
    /* Inputs */
    .stTextInput > div > div > input {
        border-radius: 4px;
        border: 1px solid #D3D3D3;
        padding: 8px;
    }
    
    /* Selectbox */
    .stSelectbox > div > div {
        border-radius: 4px;
        border: 1px solid #D3D3D3;
    }
    
    /* Ensure text visibility */
    p, li, span, div {
        color: #000000 !important;
    }

    /* Progress log box */
    .log-box {
        background: #1e1e1e;
        color: #00ff88;
        font-family: monospace;
        font-size: 13px;
        padding: 12px 16px;
        border-radius: 6px;
        max-height: 320px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
</style>
""", unsafe_allow_html=True)

st.set_page_config(page_title="Automation Hub", layout="wide", page_icon="🤖")

# ─────────────────────────────────────────────────────────────────────────────
# EXISTING TOOL: Excel Stock Movement Filler
# ─────────────────────────────────────────────────────────────────────────────

def normalize_name(name):
    if not name:
        return ""
    norm = str(name).upper().replace(" ", "").replace("S", "")
    return norm

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
        
        report_df = pd.read_excel(report_file)
        damages_df = pd.read_excel(damages_file)
        
        report_df['date'] = pd.to_datetime(report_df['date'], dayfirst=True)
        report_df['date'] = report_df['date'].apply(lambda d: d.replace(year=template_year))
        
        report_df_sorted = report_df.sort_values(['abbreviations', 'date'])
        adj_df = report_df_sorted[report_df_sorted['movement_type'] == 'Stock adjustment']
        
        for _, adj_row in adj_df.iterrows():
            abr = adj_row['abbreviations']
            adj_date = adj_row['date']
            adj_amt = abs(adj_row['adjusted amount'])
            
            same_day_ins = report_df_sorted[(report_df_sorted['abbreviations'] == abr) & 
                                            (report_df_sorted['date'] == adj_date) & 
                                            (report_df_sorted['movement_type'] == 'Stock-in')]
            if not same_day_ins.empty:
                last_same_idx = same_day_ins.index[-1]
                new_val = report_df_sorted.at[last_same_idx, 'adjusted amount'] - adj_amt
                report_df_sorted.at[last_same_idx, 'adjusted amount'] = max(0, new_val)
                continue
            
            prev_ins = report_df_sorted[(report_df_sorted['abbreviations'] == abr) & 
                                        (report_df_sorted['date'] < adj_date) & 
                                        (report_df_sorted['movement_type'] == 'Stock-in')]
            if not prev_ins.empty:
                last_prev_idx = prev_ins.index[-1]
                new_val = report_df_sorted.at[last_prev_idx, 'adjusted amount'] - adj_amt
                report_df_sorted.at[last_prev_idx, 'adjusted amount'] = max(0, new_val)
        
        ins_df = report_df_sorted[report_df_sorted['movement_type'] == 'Stock-in'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='stock_in')
        outs_df = report_df_sorted[report_df_sorted['movement_type'] == 'Invoice Issue'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='sales')
        
        first_appearances = report_df_sorted.drop_duplicates(subset=['abbreviations'], keep='first')
        openings = dict(zip(first_appearances['abbreviations'], first_appearances['book quantity']))
        
        damages_df = damages_df[pd.notna(damages_df['quantity'])]
        
        wb = openpyxl.load_workbook(BytesIO(template_bytes))
        ws = wb['Sheet1']
        
        product_map = {}
        norm_to_abr = {}
        for r in range(1, ws.max_row + 1):
            full = ws.cell(r, 2).value
            abr = ws.cell(r, 3).value
            if full and abr:
                product_map[str(full).strip().upper()] = abr
                norm_to_abr[normalize_name(full)] = abr
        
        damages_dict = {}
        for _, drow in damages_df.iterrows():
            full = str(drow['good name']).strip().upper()
            qty = int(drow['quantity'])
            if full in product_map:
                damages_dict[product_map[full]] = qty
            else:
                norm_full = normalize_name(full)
                if norm_full in norm_to_abr:
                    damages_dict[norm_to_abr[norm_full]] = qty
        
        report_abr_map = {}
        for _, rrow in report_df.iterrows():
            full = str(rrow['good name']).strip().upper()
            abr_report = rrow['abbreviations']
            if full in product_map:
                report_abr_map[abr_report] = product_map[full]
            else:
                norm_full = normalize_name(full)
                if norm_full in norm_to_abr:
                    report_abr_map[abr_report] = norm_to_abr[norm_full]
        
        ins_df['abbreviations'] = ins_df['abbreviations'].map(report_abr_map).fillna(ins_df['abbreviations'])
        outs_df['abbreviations'] = outs_df['abbreviations'].map(report_abr_map).fillna(outs_df['abbreviations'])
        
        mapped_openings = {}
        for abr_report, open_bal in openings.items():
            mapped_abr = report_abr_map.get(abr_report, abr_report)
            mapped_openings[mapped_abr] = open_bal
        
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
            first_date = min(d[0] for d in date_abr_to_row.keys())
            for abr, open_bal in mapped_openings.items():
                key = (first_date, abr)
                if key in date_abr_to_row:
                    row_num = date_abr_to_row[key]
                    ws.cell(row_num, 4).value = open_bal
        
        damages_per_day = {}
        for abr, total_d in damages_dict.items():
            abr_ins = ins_df[ins_df['abbreviations'] == abr]
            if abr_ins.empty:
                continue
            days = abr_ins['date'].dt.date.values
            stock_ins = abr_ins['stock_in'].values
            total_stock_in = stock_ins.sum()
            if total_stock_in == 0:
                continue
            weights = stock_ins / total_stock_in
            
            prod_d = int(total_d * 3 / 4)
            pack_d = total_d - prod_d
            
            prod_alloc = np.zeros(len(days), dtype=int)
            for _ in range(prod_d):
                idx = np.random.choice(len(days), p=weights)
                prod_alloc[idx] += 1
            
            pack_alloc = np.zeros(len(days), dtype=int)
            for _ in range(pack_d):
                idx = np.random.choice(len(days), p=weights)
                pack_alloc[idx] += 1
            
            damages_per_day[abr] = {days[i]: (prod_alloc[i], pack_alloc[i]) for i in range(len(days))}
        
        for _, irow in ins_df.iterrows():
            dt = irow['date'].date()
            abr = irow['abbreviations']
            stock_in = irow['stock_in']
            key = (dt, abr)
            if key not in date_abr_to_row:
                continue
            row_num = date_abr_to_row[key]
            
            d_day = damages_per_day.get(abr, {}).get(dt, (0, 0))
            prod_d_day, pack_d_day = d_day
            
            total_d_day = prod_d_day + pack_d_day
            ws.cell(row_num, 7).value = stock_in + total_d_day
            ws.cell(row_num, 8).value = prod_d_day
            ws.cell(row_num, 10).value = pack_d_day
            
            actual_filled = stock_in + total_d_day
            if actual_filled > 0:
                if actual_filled <= 50:
                    diff = random.randint(-1, 1)
                elif actual_filled <= 200:
                    diff = random.randint(-4, 6)
                else:
                    diff = random.randint(-6, 12)
                expected = max(0, actual_filled + diff)
                ws.cell(row_num, 6).value = expected
        
        for _, orow in outs_df.iterrows():
            dt = orow['date'].date()
            abr = orow['abbreviations']
            sales = orow['sales']
            key = (dt, abr)
            if key in date_abr_to_row:
                row_num = date_abr_to_row[key]
                ws.cell(row_num, 13).value = sales
        
        output_bytes = BytesIO()
        wb.save(output_bytes)
        output_bytes.seek(0)
        
        return output_bytes
    
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# NEW TOOL: EFRIS FDN Invoice Validator & Excel Enricher
# ─────────────────────────────────────────────────────────────────────────────

def fuzzy_match_product(target: str, candidates: list[str]) -> str | None:
    """
    Return the best fuzzy match from candidates for the target product name.
    Returns None if no match exceeds the similarity threshold.
    """
    target_clean = target.strip().upper()
    candidates_clean = [c.strip().upper() for c in candidates]
    matches = difflib.get_close_matches(target_clean, candidates_clean, n=1, cutoff=0.55)
    if matches:
        idx = candidates_clean.index(matches[0])
        return candidates[idx]
    return None


async def scrape_fdn_async(fdn: str, page) -> list[dict]:
    """
    Given an already-open Playwright page and an FDN string,
    navigate to EFRIS, paste the FDN, validate, click View Document,
    and scrape all invoice line items.

    Returns a list of dicts:
        [{"item": str, "quantity": str, "unit_measure": str, "unit_price": str}, ...]
    """
    EFRIS_URL = "https://efris.ura.go.ug/"
    items = []

    try:
        await page.goto(EFRIS_URL, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)

        # ── Locate the FDN input (top-left "Fiscal Document Validation" section) ──
        fdn_input = page.locator('input[placeholder*="Fiscal Document"]')
        await fdn_input.wait_for(timeout=10000)
        await fdn_input.fill("")
        await fdn_input.type(str(fdn), delay=40)
        await page.wait_for_timeout(300)

        # ── Click the Validate button ──
        validate_btn = page.locator('button:has-text("Validate")')
        await validate_btn.click()
        await page.wait_for_timeout(3000)

        # ── Wait for the popup / modal to appear ──
        # The popup typically contains "Invoice is verified" or "Fiscal Document Validation Report"
        popup = page.locator('text=Fiscal Document Validation Report').first
        await popup.wait_for(timeout=12000)
        await page.wait_for_timeout(800)

        # ── Click "View Document" button inside the popup ──
        view_doc_btn = page.locator('button:has-text("View Document")')
        await view_doc_btn.wait_for(timeout=8000)
        await view_doc_btn.click()
        await page.wait_for_timeout(4000)

        # ── Scrape the invoice table (Section D: Goods & Services Details) ──
        # The invoice renders in a new tab OR same page with a table.
        # We handle both cases: check if a new page opened.
        context = page.context
        pages = context.pages
        invoice_page = pages[-1]  # Latest page (new tab if opened)

        if invoice_page != page:
            await invoice_page.wait_for_load_state("domcontentloaded")
            await invoice_page.wait_for_timeout(2000)
        else:
            invoice_page = page

        # Try to find the invoice items table rows
        # The table usually has columns: No. | Item | Quantity | Unit Measure | Unit Price | Total | Tax Category
        rows = await invoice_page.locator("table tr").all()

        header_found = False
        col_map = {}

        for row in rows:
            cells = await row.locator("td, th").all()
            cell_texts = [((await c.inner_text()).strip()) for c in cells]

            if not header_found:
                # Look for a header row containing "Item" and "Quantity"
                upper_texts = [t.upper() for t in cell_texts]
                if "ITEM" in upper_texts and "QUANTITY" in upper_texts:
                    header_found = True
                    for i, h in enumerate(upper_texts):
                        if "ITEM" in h:
                            col_map["item"] = i
                        elif "QUANTITY" in h:
                            col_map["quantity"] = i
                        elif "UNIT" in h and "MEASURE" in h:
                            col_map["unit_measure"] = i
                        elif "UNIT" in h and "PRICE" in h:
                            col_map["unit_price"] = i
                    continue

            if header_found and cell_texts:
                # Skip rows that look like section headers or summary rows
                if len(cell_texts) < max(col_map.values(), default=0) + 1:
                    continue
                item_name = cell_texts[col_map.get("item", 1)] if col_map.get("item", 1) < len(cell_texts) else ""
                qty       = cell_texts[col_map.get("quantity", 2)] if col_map.get("quantity", 2) < len(cell_texts) else ""
                unit_m    = cell_texts[col_map.get("unit_measure", 3)] if col_map.get("unit_measure", 3) < len(cell_texts) else ""
                unit_p    = cell_texts[col_map.get("unit_price", 4)] if col_map.get("unit_price", 4) < len(cell_texts) else ""

                if item_name and qty:
                    items.append({
                        "item": item_name,
                        "quantity": qty,
                        "unit_measure": unit_m,
                        "unit_price": unit_p,
                    })

        # Close invoice tab if it was a new tab
        if invoice_page != page:
            await invoice_page.close()

    except Exception as e:
        items = []  # Return empty on error; caller logs the error

    return items


def run_efris_enrichment(purchases_df: pd.DataFrame, log_placeholder, progress_bar) -> pd.DataFrame:
    """
    Synchronous wrapper that drives the async Playwright scraping.
    Processes each row in the DataFrame, validates its FDN on EFRIS,
    and fills Quantity, Unit Measure, Unit Price columns.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        st.error("Playwright is not installed. Add `playwright` to your requirements.txt and run `playwright install chromium`.")
        return purchases_df

    # Add output columns if they don't exist
    if "Quantity" not in purchases_df.columns:
        purchases_df["Quantity"] = None
    if "Unit Measure" not in purchases_df.columns:
        purchases_df["Unit Measure"] = None
    if "Unit Price" not in purchases_df.columns:
        purchases_df["Unit Price"] = None

    total_rows = len(purchases_df)
    log_lines = []

    def log(msg):
        log_lines.append(msg)
        log_placeholder.markdown(
            '<div class="log-box">' + "<br>".join(log_lines[-60:]) + "</div>",
            unsafe_allow_html=True,
        )

    # Cache: fdn → list of invoice items (avoid re-scraping same FDN)
    fdn_cache: dict[str, list[dict]] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        for idx, row in purchases_df.iterrows():
            fdn = str(row.get("FDN", "")).strip()
            desc = str(row.get("Description of Goods", "")).strip()

            row_num = idx + 2  # Excel row (1-indexed + header)
            progress = (idx + 1) / total_rows
            progress_bar.progress(progress, text=f"Row {idx+1}/{total_rows} — FDN: {fdn}")

            if not fdn or fdn.lower() == "nan":
                log(f"[Row {row_num}] ⚠️  Skipped — no FDN")
                continue

            # Use cache if available
            if fdn not in fdn_cache:
                log(f"[Row {row_num}] 🔍  Validating FDN: {fdn}  |  Product: {desc}")
                try:
                    import asyncio
                    invoice_items = asyncio.get_event_loop().run_until_complete(
                        scrape_fdn_async(fdn, page)
                    )
                    fdn_cache[fdn] = invoice_items
                    log(f"[Row {row_num}] ✅  Found {len(invoice_items)} item(s) on invoice")
                except Exception as e:
                    fdn_cache[fdn] = []
                    log(f"[Row {row_num}] ❌  Error scraping FDN {fdn}: {e}")
            else:
                log(f"[Row {row_num}] 📋  Using cached data for FDN: {fdn}")

            invoice_items = fdn_cache[fdn]

            if not invoice_items:
                log(f"[Row {row_num}] ⚠️  No invoice items found for FDN: {fdn}")
                continue

            # Match the Excel product description to an invoice item
            invoice_names = [item["item"] for item in invoice_items]
            matched_name = fuzzy_match_product(desc, invoice_names)

            if matched_name:
                matched_item = next(
                    (i for i in invoice_items if i["item"].strip().upper() == matched_name.strip().upper()),
                    None,
                )
                if matched_item:
                    purchases_df.at[idx, "Quantity"]     = matched_item["quantity"]
                    purchases_df.at[idx, "Unit Measure"] = matched_item["unit_measure"]
                    purchases_df.at[idx, "Unit Price"]   = matched_item["unit_price"]
                    log(f"[Row {row_num}] ✔️  Matched '{desc}' → '{matched_name}' | Qty: {matched_item['quantity']} | Unit: {matched_item['unit_measure']} | Price: {matched_item['unit_price']}")
                else:
                    log(f"[Row {row_num}] ⚠️  Match found but item lookup failed for: {matched_name}")
            else:
                log(f"[Row {row_num}] ⚠️  No fuzzy match for '{desc}' among invoice items: {invoice_names}")

        browser.close()

    log("🏁  All rows processed.")
    return purchases_df


def build_output_excel(df: pd.DataFrame) -> BytesIO:
    """Convert enriched DataFrame to downloadable Excel bytes."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Purchases Report")
        ws = writer.sheets["Purchases Report"]

        # Auto-fit column widths
        for col_cells in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col_cells), default=10)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 50)

        # Style header row
        from openpyxl.styles import PatternFill, Font, Alignment
        header_fill = PatternFill("solid", fgColor="0078D4")
        header_font = Font(bold=True, color="FFFFFF")
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        # Highlight the three new columns
        new_cols = ["Quantity", "Unit Measure", "Unit Price"]
        new_col_indices = [
            i + 1 for i, cell in enumerate(ws[1]) if cell.value in new_cols
        ]
        highlight_fill = PatternFill("solid", fgColor="FFF2CC")
        for col_idx in new_col_indices:
            for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
                for cell in row:
                    cell.fill = highlight_fill

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
st.markdown("Your professional platform for automating tasks. Clean, modern design inspired by Microsoft interfaces. High-contrast for comfortable viewing.")

# ─────────────────────────────────────────────────────────────────────────────
# TOOL: Excel Stock Movement Filler  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

if tool == "Excel Stock Movement Filler":
    st.header("Excel Stock Movement Filler")
    output_name = st.text_input("Output Filename (will add .xlsx)", value="filled_template")
    output_name = output_name.removesuffix('.xlsx').strip() + ".xlsx"
    
    template_file = st.file_uploader("Upload Template (.xlsx)", type="xlsx")
    report_file   = st.file_uploader("Upload Movement Report (.xlsx)", type="xlsx")
    damages_file  = st.file_uploader("Upload Damages (.xlsx)", type="xlsx")
    
    if st.button("Process Files"):
        if template_file and report_file and damages_file:
            with st.spinner("Processing..."):
                output_bytes = process_excel(template_file, report_file, damages_file, output_name)
                if output_bytes:
                    st.success("Processing complete!")
                    st.download_button(
                        label="Download Filled Template",
                        data=output_bytes,
                        file_name=output_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
        else:
            st.warning("Upload all required files.")

# ─────────────────────────────────────────────────────────────────────────────
# TOOL: EFRIS Invoice Enricher  (NEW)
# ─────────────────────────────────────────────────────────────────────────────

elif tool == "EFRIS Invoice Enricher":
    st.header("EFRIS Invoice Enricher")
    st.markdown(
        """
        Upload your **Purchases Report** (.xlsx). The tool will:
        1. Read each row's **FDN** and **Description of Goods**
        2. Automatically open [efris.ura.go.ug](https://efris.ura.go.ug/), validate each FDN and view the invoice
        3. Match each product to the corresponding invoice line item
        4. Add **Quantity**, **Unit Measure**, and **Unit Price** columns to your report
        5. Generate a downloadable enriched Excel file

        > ⚠️ **Note:** This tool launches a headless browser — it may take a few minutes depending on the number of unique FDNs.
        > The tool caches invoice data per FDN, so duplicate FDNs are only scraped once.
        """
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        purchases_file = st.file_uploader(
            "Upload Purchases Report (.xlsx)",
            type=["xlsx"],
            key="efris_upload",
        )
    with col2:
        output_filename = st.text_input(
            "Output Filename",
            value="enriched_purchases_report",
            key="efris_output_name",
        )
        output_filename = output_filename.removesuffix(".xlsx").strip() + ".xlsx"

    # Preview the uploaded file
    if purchases_file:
        try:
            preview_df = pd.read_excel(purchases_file, nrows=5)
            purchases_file.seek(0)
            st.markdown("**Preview (first 5 rows):**")
            st.dataframe(preview_df, use_container_width=True)

            # Validate required columns
            required_cols = {"FDN", "Description of Goods"}
            missing = required_cols - set(preview_df.columns)
            if missing:
                st.error(f"Missing required columns: {missing}. Please check your Excel file.")
                purchases_file = None
        except Exception as e:
            st.error(f"Could not read file: {e}")
            purchases_file = None

    run_btn = st.button(
        "🚀 Start EFRIS Validation & Enrichment",
        disabled=(purchases_file is None),
        key="efris_run",
    )

    if run_btn and purchases_file:
        st.markdown("---")
        st.markdown("### Live Progress")
        progress_bar   = st.progress(0, text="Starting...")
        log_placeholder = st.empty()

        try:
            full_df = pd.read_excel(purchases_file)
            purchases_file.seek(0)

            enriched_df = run_efris_enrichment(full_df, log_placeholder, progress_bar)

            progress_bar.progress(1.0, text="✅ Done!")
            st.success("Enrichment complete! Download your file below.")

            output_bytes = build_output_excel(enriched_df)
            st.download_button(
                label="⬇️ Download Enriched Excel",
                data=output_bytes,
                file_name=output_filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            # Summary stats
            filled = enriched_df["Quantity"].notna().sum()
            total  = len(enriched_df)
            st.info(f"📊 **{filled} / {total}** rows successfully enriched with invoice data.")

        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# PLACEHOLDER TOOLS  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

elif tool == "Audit Compliance Checker (Coming Soon)":
    st.header("Audit Compliance Checker")
    st.info("Upload financial docs for automated compliance checks. Coming soon – contact for early access.")

elif tool == "Financial Report Generator (Coming Soon)":
    st.header("Financial Report Generator")
    st.info("Generate audit-ready reports from raw data. Feature in development.")

elif tool == "Sales Dashboard (Inspired by Reference)":
    st.header("Sales Dashboard")
    st.info("Interactive sales reports with filters, charts, and exports. Inspired by your SALES_MANAGEMENT system. Upload data to get started.")
    sales_data = st.file_uploader("Upload Sales Data (.xlsx)", type="xlsx")
    if sales_data:
        st.write("Data uploaded – dashboard coming soon!")

st.sidebar.markdown("---")
st.sidebar.info("Powered by Streamlit. Deploy your own or customize further.")
