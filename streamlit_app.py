import io
import random
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from hospitals import REGISTRY
from hospitals.tmuh import parse_birth_date

st.set_page_config(page_title="掛號查詢系統", page_icon="🏥", layout="centered")
st.title("🏥 掛號查詢系統")
st.caption("支援：" + "・".join(h.display_name for h in REGISTRY.values()))


def build_result_xlsx(rows):
    """rows: [(姓名, 醫院, 身分證, 出生日期, 結果, 時間), ...]"""
    wb = Workbook()
    ws = wb.active
    ws.title = "查詢結果"

    headers    = ["姓名", "醫院", "身分證字號", "出生日期", "查詢結果", "查詢時間"]
    col_widths = [12, 18, 16, 16, 45, 20]

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


# ── 單筆查詢 Tab ───────────────────────────────────────────────────────────────
tab_single, tab_batch = st.tabs(["單筆查詢", "批次查詢（XLSX）"])

with tab_single:
    st.subheader("單筆查詢")
    hosp_name = st.selectbox("醫院", list(REGISTRY.keys()), key="single_hosp")
    hosp      = REGISTRY[hosp_name]

    c1, c2 = st.columns(2)
    with c1:
        single_id = st.text_input("身分證字號", placeholder="A123456789",
                                   key="single_id").strip().upper()
    with c2:
        if hosp.needs_birth:
            single_birth = st.text_input("出生日期（民國年/月/日）",
                                          placeholder="074/06/23",
                                          key="single_birth").strip()
        else:
            st.caption(f"{hosp_name} 僅需身分證字號")
            single_birth = ""

    if st.button("查詢", key="btn_single"):
        if not single_id:
            st.warning("請填入身分證字號")
        elif hosp.needs_birth and not single_birth:
            st.warning("請填入出生日期")
        else:
            birth_args = {}
            if hosp.needs_birth:
                parsed = parse_birth_date(single_birth)
                if not parsed:
                    st.error("出生日期格式錯誤，請輸入如 074/06/23")
                    st.stop()
                birth_args = dict(birth_year=parsed[0],
                                  birth_month=parsed[1],
                                  birth_day=parsed[2])
            with st.spinner("查詢中，請稍候..."):
                session = hosp.make_session()
                result  = hosp.query_one(session, single_id, **birth_args)
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
    hosp_list = "、".join(REGISTRY.keys())
    st.caption(
        f"XLSX 欄位順序：**姓名**（可空）、**醫院**（{hosp_list}）、"
        "**身分證字號**、**出生日期**（需出生日期的醫院必填，其餘可空白）"
    )

    uploaded  = st.file_uploader("上傳查詢名單 XLSX", type=["xlsx"])
    query_all = st.checkbox("查詢所有醫院（忽略醫院欄位，同時查詢全部醫院）",
                            value=True)

    if uploaded:
        df = pd.read_excel(uploaded, dtype=str).fillna("")
        df.columns = df.columns.str.strip()
        st.dataframe(df, use_container_width=True)

        if st.button("開始批次查詢", key="btn_batch"):
            sessions = {name: h.make_session() for name, h in REGISTRY.items()}
            rows     = []
            total    = len(df)
            progress = st.progress(0, text="準備中...")
            status   = st.empty()

            for i, row in df.iterrows():
                vals    = list(row.values)
                name    = str(vals[0]).strip() if len(vals) > 0 else ""
                hospital= str(vals[1]).strip() if len(vals) > 1 else ""
                id_no   = str(vals[2]).strip() if len(vals) > 2 else ""
                birth_b = str(vals[3]).strip() if len(vals) > 3 else ""

                progress.progress(i / total, text=f"查詢 {i+1}/{total}：{id_no}")

                if not id_no:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    rows.append((name, hospital, id_no, birth_b, "身分證字號為空，略過", ts))
                    continue

                if query_all:
                    parts = []
                    for hname, hosp in REGISTRY.items():
                        status.text(f"[{hname}] {name} {id_no}")
                        if hosp.needs_birth:
                            if not birth_b:
                                parts.append(f"【{hname}】需填出生日期，略過")
                                continue
                            parsed = parse_birth_date(birth_b)
                            if not parsed:
                                parts.append(f"【{hname}】出生日期格式錯誤")
                                continue
                            r = hosp.query_one(sessions[hname], id_no,
                                               birth_year=parsed[0],
                                               birth_month=parsed[1],
                                               birth_day=parsed[2])
                        else:
                            r = hosp.query_one(sessions[hname], id_no)
                        parts.append(f"【{hname}】{r}")
                        if hosp is not list(REGISTRY.values())[-1]:
                            time.sleep(random.uniform(1, 3))
                    result   = "\n".join(parts)
                    hosp_tag = "全部"
                else:
                    hosp_tag = hospital if hospital else "北醫附醫"
                    hosp     = REGISTRY.get(hosp_tag, REGISTRY["北醫附醫"])
                    status.text(f"[{hosp_tag}] {name} {id_no}")
                    if hosp.needs_birth:
                        if not birth_b:
                            result = f"{hosp_tag}需填出生日期"
                        else:
                            parsed = parse_birth_date(birth_b)
                            if not parsed:
                                result = "出生日期格式錯誤"
                            else:
                                result = hosp.query_one(sessions[hosp_tag], id_no,
                                                        birth_year=parsed[0],
                                                        birth_month=parsed[1],
                                                        birth_day=parsed[2])
                    else:
                        result = hosp.query_one(sessions[hosp_tag], id_no)

                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rows.append((name, hosp_tag, id_no, birth_b, result, ts))

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
