import io
import random
import time
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from tmuh_query import get_page_state, get_captcha_text, parse_response
from batch_query import parse_birth_date

st.set_page_config(page_title="北醫附醫 掛號查詢", page_icon="🏥", layout="centered")
st.title("🏥 臺北醫學大學附設醫院 掛號查詢")


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.tmuh.org.tw/service/query",
    })
    return s


def query_one(session, id_no, birth_year, birth_month, birth_day, max_retry=5):
    for _ in range(max_retry):
        try:
            state = get_page_state(session)
            captcha = get_captcha_text(session)
        except requests.RequestException as e:
            time.sleep(2)
            continue

        if not captcha:
            continue

        form_data = {
            "__EVENTTARGET": "ctl00$MainPlaceHolder$ctl00$btnSubmit",
            "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            "__VIEWSTATE": state["__VIEWSTATE"],
            "__VIEWSTATEGENERATOR": state["__VIEWSTATEGENERATOR"],
            "ctl00$MainPlaceHolder$ctl00$txtIDNo": id_no,
            "ctl00$MainPlaceHolder$ctl00$txtPatNo": "",
            "ctl00$MainPlaceHolder$ctl00$txtPatPwd": "",
            "ctl00$MainPlaceHolder$ctl00$cbCate": "A",
            "ctl00$MainPlaceHolder$ctl00$cbYear": birth_year,
            "ctl00$MainPlaceHolder$ctl00$cbMonth": birth_month,
            "ctl00$MainPlaceHolder$ctl00$cbDay": birth_day,
            "vCode": captcha,
        }

        try:
            resp = session.post(
                "https://www.tmuh.org.tw/service/query",
                data=form_data, timeout=15, verify=False
            )
            resp.raise_for_status()
        except requests.RequestException:
            time.sleep(2)
            continue

        result = parse_response(resp.text)
        if result == "CAPTCHA_ERROR":
            time.sleep(1)
            continue
        return result

    return "超過重試次數，請稍後再試"


def build_result_xlsx(rows):
    """rows: list of (姓名, 身分證, 出生日期, 結果, 時間)"""
    wb = Workbook()
    ws = wb.active
    ws.title = "查詢結果"

    headers = ["姓名", "身分證字號", "出生日期(民國年/月/日)", "查詢結果", "查詢時間"]
    col_widths = [12, 16, 22, 45, 20]

    thin = Side(style="thin", color="AAAAAA")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    h_font = Font(name="Arial", bold=True, color="FFFFFF")
    h_fill = PatternFill("solid", start_color="2F5496")
    center = Alignment(horizontal="center", vertical="center")

    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = h_font
        cell.fill = h_fill
        cell.alignment = center
        cell.border = border
        ws.column_dimensions[get_column_letter(col)].width = w

    ok_fill = PatternFill("solid", start_color="E2EFDA")
    err_fill = PatternFill("solid", start_color="FCE4D6")
    alt_fill = PatternFill("solid", start_color="EEF2F7")
    d_font = Font(name="Arial", size=11)

    for r, row in enumerate(rows, 2):
        name, id_no, bdate, result, ts = row
        is_err = any(k in (result or "") for k in ["查不到", "錯誤", "失敗", "超過"])
        fill = err_fill if is_err else (ok_fill if r % 2 == 0 else alt_fill)
        for col, val in enumerate([name, id_no, bdate, result, ts], 1):
            cell = ws.cell(row=r, column=col, value=val)
            cell.font = d_font
            cell.fill = fill
            cell.alignment = Alignment(
                vertical="center",
                horizontal="left" if col == 4 else "center",
                wrap_text=(col == 4)
            )
            cell.border = border

    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["單筆查詢", "批次查詢（XLSX）"])

# ── Tab 1: 單筆查詢 ────────────────────────────────────────────────────────────
with tab1:
    st.subheader("單筆查詢")
    col1, col2 = st.columns(2)
    with col1:
        id_no = st.text_input("身分證字號", placeholder="A123456789").strip().upper()
    with col2:
        birth_raw = st.text_input("出生日期（民國年/月/日）", placeholder="074/06/23").strip()

    if st.button("查詢", key="single"):
        if not id_no or not birth_raw:
            st.warning("請填入身分證字號與出生日期")
        else:
            parsed = parse_birth_date(birth_raw)
            if not parsed:
                st.error("出生日期格式錯誤，請輸入如 074/06/23")
            else:
                y, m, d = parsed
                with st.spinner("查詢中，請稍候..."):
                    result = query_one(make_session(), id_no, y, m, d)
                if "查不到" in result or "查無" in result:
                    st.info(result)
                elif "錯誤" in result or "失敗" in result or "超過" in result:
                    st.error(result)
                else:
                    st.success("查詢完成")
                    st.text(result)

# ── Tab 2: 批次查詢 ────────────────────────────────────────────────────────────
with tab2:
    st.subheader("批次查詢")
    st.caption("XLSX 需包含欄位：姓名（可空）、身分證字號、出生日期（民國年/月/日）")

    uploaded = st.file_uploader("上傳查詢名單 XLSX", type=["xlsx"])

    if uploaded:
        df = pd.read_excel(uploaded, dtype=str)
        df.columns = df.columns.str.strip()
        st.dataframe(df, use_container_width=True)

        if st.button("開始批次查詢", key="batch"):
            session = make_session()
            results = []
            progress = st.progress(0, text="準備中...")
            status_box = st.empty()
            total = len(df)

            for i, row in df.iterrows():
                vals = list(row.values)
                name = str(vals[0] or "").strip() if len(vals) > 0 else ""
                id_no_b = str(vals[1] or "").strip() if len(vals) > 1 else ""
                birth_b = str(vals[2] or "").strip() if len(vals) > 2 else ""

                pct = i / total
                progress.progress(pct, text=f"查詢 {i+1}/{total}：{id_no_b}")
                status_box.text(f"正在查詢：{name} {id_no_b} ({birth_b})")

                if not id_no_b or not birth_b:
                    result = "資料不完整，略過"
                else:
                    parsed = parse_birth_date(birth_b)
                    if not parsed:
                        result = "出生日期格式錯誤"
                    else:
                        y, m, d = parsed
                        result = query_one(session, id_no_b, y, m, d)

                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                results.append((name, id_no_b, birth_b, result, ts))

                if i < total - 1:
                    delay = random.uniform(1, 5)
                    time.sleep(delay)

            progress.progress(1.0, text="查詢完成！")
            status_box.empty()

            result_df = pd.DataFrame(
                results,
                columns=["姓名", "身分證字號", "出生日期", "查詢結果", "查詢時間"]
            )
            st.dataframe(result_df, use_container_width=True)

            xlsx_bytes = build_result_xlsx(results)
            fname = f"查詢結果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.download_button(
                label="⬇️ 下載結果 XLSX",
                data=xlsx_bytes,
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
