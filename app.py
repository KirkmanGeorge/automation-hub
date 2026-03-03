import streamlit as st
import openpyxl
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import random
from io import BytesIO
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import pdfplumber
    import requests
except ImportError as e:
    st.error(f"Missing library: {str(e)}. Please add to requirements.txt: selenium, pdfplumber, requests")
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
</style>
""", unsafe_allow_html=True)
st.set_page_config(page_title="Automation Hub", layout="wide", page_icon="🤖")
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
       
        # Find first template date to get year/month
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
       
        # Adjust report dates to template year (for mismatch cases)
        report_df['date'] = report_df['date'].apply(lambda d: d.replace(year=template_year))
       
        # Pre-process stock adjustments: always subtract the adjustment amount (as reduction) from same day stock-in if exists, else previous; clamp to 0
        report_df_sorted = report_df.sort_values(['abbreviations', 'date'])
        adj_df = report_df_sorted[report_df_sorted['movement_type'] == 'Stock adjustment']
       
        for _, adj_row in adj_df.iterrows():
            abr = adj_row['abbreviations']
            adj_date = adj_row['date']
            adj_amt = abs(adj_row['adjusted amount']) # Always treat as positive reduction (subtract absolute value)
           
            # First, try same day stock-in
            same_day_ins = report_df_sorted[(report_df_sorted['abbreviations'] == abr) &
                                            (report_df_sorted['date'] == adj_date) &
                                            (report_df_sorted['movement_type'] == 'Stock-in')]
            if not same_day_ins.empty:
                last_same_idx = same_day_ins.index[-1]
                new_val = report_df_sorted.at[last_same_idx, 'adjusted amount'] - adj_amt
                report_df_sorted.at[last_same_idx, 'adjusted amount'] = max(0, new_val)
                continue # Processed, skip to next adjustment
           
            # If no same day, fall back to previous days
            prev_ins = report_df_sorted[(report_df_sorted['abbreviations'] == abr) &
                                        (report_df_sorted['date'] < adj_date) &
                                        (report_df_sorted['movement_type'] == 'Stock-in')]
            if not prev_ins.empty:
                last_prev_idx = prev_ins.index[-1]
                new_val = report_df_sorted.at[last_prev_idx, 'adjusted amount'] - adj_amt
                report_df_sorted.at[last_prev_idx, 'adjusted amount'] = max(0, new_val)
       
        ins_df = report_df_sorted[report_df_sorted['movement_type'] == 'Stock-in'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='stock_in')
        outs_df = report_df_sorted[report_df_sorted['movement_type'] == 'Invoice Issue'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='sales')
       
        # Openings: first appearance in the month, use book quantity
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

def get_invoice_data(fdn, description):
    # Set up Selenium
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.binary_location = "/usr/bin/chromium-browser"
    service = Service(executable_path="/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        driver.get("https://efris.ura.go.ug/")
        
        # Wait for the input field - adjust XPath or selector as per actual site structure
        input_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//input[contains(@placeholder, "Enter Fiscal Document Validation") or @id="fdnInput"]'))  # Adjust this XPath
        )
        input_field.send_keys(str(fdn))
        
        # Assume auto-validate or press enter; if there's a button, click it
        input_field.send_keys(Keys.ENTER)
        # Or: validate_button = driver.find_element(By.ID, "validateButton")  # Adjust
        # validate_button.click()
        
        # Wait for popup
        popup = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "popup"))  # Adjust selector for popup
        )
        
        # Click View Document
        view_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//button[text()="View Document"]'))  # Adjust XPath
        )
        view_button.click()
        
        # Assume it loads the PDF in the same or new tab; get the current URL if it's PDF
        WebDriverWait(driver, 10).until(EC.url_contains(".pdf"))  # Wait if URL changes to PDF
        pdf_url = driver.current_url
        
        # Download PDF
        response = requests.get(pdf_url)
        response.raise_for_status()
        
        with BytesIO(response.content) as pdf_bytes:
            with pdfplumber.open(pdf_bytes) as pdf:
                # Assume the items table is on the first page; adjust if needed
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        # Assume header is first row
                        header = table[0]
                        # Find indices of columns
                        desc_idx = header.index("Description") if "Description" in header else -1
                        qty_idx = header.index("Quantity") if "Quantity" in header else -1
                        unit_meas_idx = header.index("Unit of Measure") if "Unit of Measure" in header else -1
                        unit_price_idx = header.index("Unit Price") if "Unit Price" in header else -1
                        
                        if desc_idx == -1 or qty_idx == -1 or unit_meas_idx == -1 or unit_price_idx == -1:
                            continue
                        
                        for row in table[1:]:
                            row_desc = row[desc_idx].strip() if len(row) > desc_idx else ""
                            if description.strip().lower() in row_desc.lower():
                                return {
                                    'quantity': row[qty_idx].strip() if len(row) > qty_idx else "",
                                    'unit_measure': row[unit_meas_idx].strip() if len(row) > unit_meas_idx else "",
                                    'unit_price': row[unit_price_idx].strip() if len(row) > unit_price_idx else ""
                                }
        
        # If not found
        raise ValueValue(f"Product '{description}' not found in invoice for FDN {fdn}")
    
    finally:
        driver.quit()

# Sidebar
st.sidebar.title("Navigation")
tool = st.sidebar.selectbox("Select Automation Tool", [
    "Excel Stock Movement Filler",
    "Audit Compliance Checker (Coming Soon)",
    "Financial Report Generator (Coming Soon)",
    "Sales Dashboard (Inspired by Reference)",
    "Purchases Report Processor"  # New functionality
])
st.title("Automation Hub")
st.markdown("Your professional platform for automating tasks. Clean, modern design inspired by Microsoft interfaces. High-contrast for comfortable viewing.")
if tool == "Excel Stock Movement Filler":
    st.header("Excel Stock Movement Filler")
    output_name = st.text_input("Output Filename (will add .xlsx)", value="filled_template")
    output_name = output_name.removesuffix('.xlsx').strip() + ".xlsx"
   
    template_file = st.file_uploader("Upload Template (.xlsx)", type="xlsx")
    report_file = st.file_uploader("Upload Movement Report (.xlsx)", type="xlsx")
    damages_file = st.file_uploader("Upload Damages (.xlsx)", type="xlsx")
   
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
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        else:
            st.warning("Upload all required files.")
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
elif tool == "Purchases Report Processor":
    st.header("Purchases Report Processor")
    output_name = st.text_input("Output Filename (will add .xlsx)", value="processed_purchases")
    output_name = output_name.removesuffix('.xlsx').strip() + ".xlsx"
   
    purchases_file = st.file_uploader("Upload Detailed Purchases Report (.xlsx)", type="xlsx")
   
    if st.button("Process File"):
        if purchases_file:
            with st.spinner("Processing..."):
                try:
                    df = pd.read_excel(purchases_file)
                    # Ensure columns exist
                    if 'FDN' not in df.columns or 'Description of Goods' not in df.columns:
                        raise ValueError("Excel must have 'FDN' and 'Description of Goods' columns.")
                    
                    df['Quantity'] = ''
                    df['Unit Measure'] = ''
                    df['Unit Price'] = ''
                    
                    for index, row in df.iterrows():
                        fdn = row['FDN']
                        description = row['Description of Goods']
                        data = get_invoice_data(fdn, description)
                        df.at[index, 'Quantity'] = data['quantity']
                        df.at[index, 'Unit Measure'] = data['unit_measure']
                        df.at[index, 'Unit Price'] = data['unit_price']
                    
                    output_bytes = BytesIO()
                    df.to_excel(output_bytes, index=False)
                    output_bytes.seek(0)
                    
                    st.success("Processing complete!")
                    st.download_button(
                        label="Download Processed Report",
                        data=output_bytes,
                        file_name=output_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                except Exception as e:
                    st.error(f"Error: {str(e)}")
        else:
            st.warning("Upload the required file.")
st.sidebar.markdown("---")
st.sidebar.info("Powered by Streamlit. Deploy your own or customize further.")
