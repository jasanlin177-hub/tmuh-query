import io
import random
import time
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from tmuh_query import parse_birth_date, tmuh_query_one
from wanfang_query import query_one as wanfang_query_one, HEADERS as WF_HEADERS

st.set_page_config(page_title="掛號查詢系統", page_icon="🏥", layout="centered")
st.title("🏥 掛號查詢系統")
st.caption("支援：臺北醫學大學附設醫院・萬芳醫院")


def make_tmuh_session():
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


def make_wf_session():
    s = requests.Session()
    s.headers.update(WF_HEADERS)
    return s


def build_result_xlsx(rows):
    """rows: [(姓名, 醫院, 身分證, 出生日期, 結果, 時間), ...]"""
    wb = Workbook()
    ws = wb.active
    ws.title = "查詢結果"

    headers    = ["姓名", "醫院", "身分證字號", "出生日期", "查詢結果", "查詢時間"]
    col_widths = [12, 12, 16, 16, 45, 20]

    thin   = Side(style="thin", color="AAAAAA")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    h_font = Font(name="Arial", bold=True, color="FFFFFF")
    h_fill = PatternFill("solid", start_color="2F5496")

    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font  = h_font
        cell.fill  = h_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
        ws.column_dimensions[get_column_letter(col)].width = w

    ok_fill  = PatternFill("solid", start_color="E2EFDA")
    err_fill = PatternFill("solid", start_color="FCE4D6")
    alt_fill = PatternFill("solid", start_color="EEF2F7")
    d_font   = Font(name="Arial", size=11)

    for r, row in enumerate(rows, 2):
        result = row[4] or ""
        is_err = any(k in result for k in ["查不到", "錯誤", "失敗", "超過", "格式"])
        fill   = err_fill if is_err else (ok_fill if r % 2 == 0 else alt_fill)
        for col, val in enumerate(row, 1):
            cell = ws.cell(row=r, column=col, value=val)
            cell.font   = d_font
            cell.fill   = fill
            cell.border = border
            cell.alignment = Alignment(
                vertical="center",
                horizontal="left" if col == 5 else "center",
                wrap_text=(col == 5)
            )

    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_tmuh, tab_wf, tab_batch = st.tabs([
    "北醫附醫 單筆查詢",
    "萬芳醫院 單筆查詢",
    "批次查詢（XLSX）",
])

# ── 北醫附醫 單筆查詢 ──────────────────────────────────────────────────────────
with tab_tmuh:
    st.subheader("臺北醫學大學附設醫院")
    c1, c2 = st.columns(2)
    with c1:
        tmuh_id = st.text_input("身分證字號", placeholder="A123456789", key="tmuh_id").strip().upper()
    with c2:
        tmuh_birth = st.text_input("出生日期（民國年/月/日）", placeholder="074/06/23", key="tmuh_birth").strip()

    if st.button("查詢", key="btn_tmuh"):
        if not tmuh_id or not tmuh_birth:
            st.warning("請填入身分證字號與出生日期")
        else:
            parsed = parse_birth_date(tmuh_birth)
            if not parsed:
                st.error("出生日期格式錯誤，請輸入如 074/06/23")
            else:
                y, m, d = parsed
                with st.spinner("查詢中，請稍候..."):
                    result = tmuh_query_one(make_tmuh_session(), tmuh_id, y, m, d)
                if any(k in result for k in ["查不到", "查無"]):
                    st.info(result)
                elif any(k in result for k in ["錯誤", "失敗", "超過"]):
                    st.error(result)
                else:
                    st.success("查詢完成")
                    st.text(result)

# ── 萬芳醫院 單筆查詢 ──────────────────────────────────────────────────────────
with tab_wf:
    st.subheader("萬芳醫院")
    wf_id = st.text_input("身分證字號", placeholder="A123456789", key="wf_id").strip().upper()
    st.caption("萬芳醫院僅需身分證字號，不需出生日期")

    if st.button("查詢", key="btn_wf"):
        if not wf_id:
            st.warning("請填入身分證字號")
        else:
            with st.spinner("查詢中，請稍候..."):
                result = wanfang_query_one(make_wf_session(), id_no=wf_id)
            if any(k in result for k in ["查不到", "查無"]):
                st.info(result)
            elif any(k in result for k in ["錯誤", "失敗", "超過"]):
                st.error(result)
            else:
                st.success("查詢完成")
                st.text(result)

# ── 批次查詢 ───────────────────────────────────────────────────────────────────
with tab_batch:
    st.subheader("批次查詢")
    st.caption(
        "XLSX 欄位順序：**姓名**（可空）、**醫院**（北醫附醫／萬芳醫院）、"
        "**身分證字號**、**出生日期**（北醫附醫必填，萬芳可空白）"
    )

    uploaded    = st.file_uploader("上傳查詢名單 XLSX", type=["xlsx"])
    query_all   = st.checkbox("查詢所有醫院（忽略醫院欄位，同時查詢北醫附醫與萬芳醫院）",
                              value=True)

    if uploaded:
        df = pd.read_excel(uploaded, dtype=str).fillna("")
        df.columns = df.columns.str.strip()
        st.dataframe(df, use_container_width=True)

        if st.button("開始批次查詢", key="btn_batch"):
            tmuh_sess = make_tmuh_session()
            wf_sess   = make_wf_session()
            rows      = []
            total     = len(df)
            progress  = st.progress(0, text="準備中...")
            status    = st.empty()

            for i, row in df.iterrows():
                vals    = list(row.values)
                name    = str(vals[0]).strip() if len(vals) > 0 else ""
                hospital= str(vals[1]).strip() if len(vals) > 1 else ""
                id_no_b = str(vals[2]).strip() if len(vals) > 2 else ""
                birth_b = str(vals[3]).strip() if len(vals) > 3 else ""

                progress.progress(i / total, text=f"查詢 {i+1}/{total}：{id_no_b}")

                if not id_no_b:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    rows.append((name, hospital, id_no_b, birth_b, "身分證字號為空，略過", ts))
                    continue

                if query_all:
                    parts = []
                    # 北醫附醫
                    status.text(f"[北醫附醫] {name} {id_no_b}")
                    if not birth_b:
                        parts.append("【北醫附醫】需填出生日期，略過")
                    else:
                        parsed = parse_birth_date(birth_b)
                        if not parsed:
                            parts.append("【北醫附醫】出生日期格式錯誤")
                        else:
                            y, m, d = parsed
                            r = tmuh_query_one(tmuh_sess, id_no_b, y, m, d)
                            parts.append(f"【北醫附醫】{r}")
                    time.sleep(random.uniform(1, 5))
                    # 萬芳醫院
                    status.text(f"[萬芳醫院] {name} {id_no_b}")
                    r = wanfang_query_one(wf_sess, id_no=id_no_b)
                    parts.append(f"【萬芳醫院】{r}")
                    result   = "\n".join(parts)
                    hosp_tag = "全部"
                else:
                    hosp_tag = hospital if hospital else "北醫附醫"
                    is_wf    = "萬芳" in hosp_tag
                    status.text(f"[{hosp_tag}] {name} {id_no_b}")
                    if is_wf:
                        result = wanfang_query_one(wf_sess, id_no=id_no_b)
                    else:
                        if not birth_b:
                            result = "北醫附醫需填出生日期"
                        else:
                            parsed = parse_birth_date(birth_b)
                            if not parsed:
                                result = "出生日期格式錯誤"
                            else:
                                y, m, d = parsed
                                result = tmuh_query_one(tmuh_sess, id_no_b, y, m, d)

                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rows.append((name, hosp_tag, id_no_b, birth_b, result, ts))

                if i < total - 1:
                    time.sleep(random.uniform(1, 5))

            progress.progress(1.0, text="查詢完成！")
            status.empty()

            result_df = pd.DataFrame(
                rows,
                columns=["姓名", "醫院", "身分證字號", "出生日期", "查詢結果", "查詢時間"]
            )
            st.dataframe(result_df, use_container_width=True)

            xlsx_bytes = build_result_xlsx(rows)
            fname = f"查詢結果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            st.download_button(
                label="⬇️ 下載結果 XLSX",
                data=xlsx_bytes,
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
