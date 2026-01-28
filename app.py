import streamlit as st
import openpyxl
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import random
from pathlib import Path
import io

st.set_page_config(page_title="Automation Hub", layout="wide", page_icon="🤖")

def excel_serial_to_date(serial):
    if isinstance(serial, (float, int)):
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date()
    if isinstance(serial, datetime):
        return serial.date()
    return None

def process_excel(template_file, report_file, damages_file):
    try:
        # Read uploaded files
        template_bytes = template_file.read()
        report_df = pd.read_excel(report_file)
        damages_df = pd.read_excel(damages_file)
        
        report_df['date'] = pd.to_datetime(report_df['date'], dayfirst=True)
        
        ins_df = report_df[report_df['movement_type'] == 'Stock-in'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='stock_in')
        outs_df = report_df[report_df['movement_type'] == 'Invoice Issue'].groupby(['date', 'abbreviations'])['adjusted amount'].sum().reset_index(name='sales')
        
        first_mov = report_df.sort_values('date').groupby('abbreviations').first().reset_index()
        openings = dict(zip(first_mov['abbreviations'], first_mov['book quantity']))
        
        damages_df = damages_df[pd.notna(damages_df['quantity'])]
        
        wb = openpyxl.load_workbook(io.BytesIO(template_bytes))
        ws = wb['Sheet1']
        
        product_map = {}
        for r in range(1, ws.max_row + 1):
            full = ws.cell(r, 2).value
            abr = ws.cell(r, 3).value
            if full and abr:
                product_map[str(full).strip().upper()] = abr
        
        damages_dict = {}
        for _, drow in damages_df.iterrows():
            full = str(drow['good name']).strip().upper()
            qty = int(drow['quantity'])
            if full in product_map:
                damages_dict[product_map[full]] = qty
        
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
            for abr, open_bal in openings.items():
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
        
        for _, orow in outs_df.iterrows():
            dt = orow['date'].date()
            abr = orow['abbreviations']
            sales = orow['sales']
            key = (dt, abr)
            if key in date_abr_to_row:
                row_num = date_abr_to_row[key]
                ws.cell(row_num, 13).value = sales
        
        output_bytes = io.BytesIO()
        wb.save(output_bytes)
        output_bytes.seek(0)
        
        return output_bytes
    
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return None

# Sidebar for navigation
st.sidebar.title("Automation Hub")
tool = st.sidebar.selectbox("Select Tool", ["Excel Stock Movement Filler", "Audit Task 1 (Coming Soon)", "Audit Task 2 (Coming Soon)", "Sales Reports (Inspired by Reference)"])

st.title("Professional Automation System")
st.markdown("Welcome to your online automation platform. Upload files and process with one click. Expandable for audit firm tasks.")

if tool == "Excel Stock Movement Filler":
    st.header("Excel Stock Movement Filler")
    template_file = st.file_uploader("Upload Template (.xlsx)", type="xlsx")
    report_file = st.file_uploader("Upload Movement Report (.xlsx)", type="xlsx")
    damages_file = st.file_uploader("Upload Damages (.xlsx)", type="xlsx")
    
    if st.button("Process Files"):
        if template_file and report_file and damages_file:
            with st.spinner("Processing..."):
                output_bytes = process_excel(template_file, report_file, damages_file)
                if output_bytes:
                    st.success("Done!")
                    st.download_button(
                        label="Download Filled Template",
                        data=output_bytes,
                        file_name="filled_template.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
        else:
            st.warning("Please upload all three files.")
elif tool == "Audit Task 1 (Coming Soon)":
    st.header("Audit Task 1")
    st.info("This feature for audit firms is under development. Contact for customization.")
elif tool == "Audit Task 2 (Coming Soon)":
    st.header("Audit Task 2")
    st.info("Coming soon: Automated audit reports and compliance checks.")
elif tool == "Sales Reports (Inspired by Reference)":
    st.header("Sales Reports Module")
    st.info("Inspired by your sales management system. Upload data for reports, filters, and dashboards. Feature in progress.")

st.sidebar.markdown("---")
st.sidebar.info("Built for easy access from any computer. Add more automations as needed.")
