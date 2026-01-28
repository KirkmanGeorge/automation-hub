import streamlit as st
import openpyxl
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import random
from io import BytesIO

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
        report_df = pd.read_excel(report_file)
        damages_df = pd.read_excel(damages_file)
        
        report_df['date'] = pd.to_datetime(report_df['date'], dayfirst=True)
        
        report_df_sorted = report_df.sort_values('date')
        first_appearances = report_df_sorted.drop_duplicates(subset=['abbreviations'], keep='first')
        openings = dict(zip(first_appearances['abbreviations'], first_appearances['book quantity']))
        
        ins_df = report_df[report_df['movement_type'] == 'Stock-in'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='stock_in')
        outs_df = report_df[report_df['movement_type'] == 'Invoice Issue'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='sales')
        
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
        
        # Fill ACTUAL, DAMAGES, SALES and now also EXPECTED
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
            ws.cell(row_num, 7).value = stock_in + total_d_day  # ACTUAL
            
            ws.cell(row_num, 8).value = prod_d_day   # DAMAGES prod
            ws.cell(row_num, 10).value = pack_d_day  # DAMAGES pack
            
            # NEW: Fill EXPECTED (column F = 6)
            # Expected is close to stock_in / actual
            actual_filled = stock_in + total_d_day
            if actual_filled > 0:
                if actual_filled <= 50:
                    diff = random.randint(-5, 5)
                elif actual_filled <= 200:
                    diff = random.randint(-15, 15)
                else:
                    diff = random.randint(-30, 30)
                expected = max(0, actual_filled + diff)  # don't go negative
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

# Sidebar
st.sidebar.title("Navigation")
tool = st.sidebar.selectbox("Select Automation Tool", [
    "Excel Stock Movement Filler", 
    "Audit Compliance Checker (Coming Soon)", 
    "Financial Report Generator (Coming Soon)", 
    "Sales Dashboard (Inspired by Reference)"
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

st.sidebar.markdown("---")
st.sidebar.info("Powered by Streamlit. Deploy your own or customize further.")
