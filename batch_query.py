"""
批次掛號查詢 - 從 XLSX 讀取名單，逐一查詢並將結果寫回新檔案
支援醫院：北醫附醫、萬芳醫院
用法: python batch_query.py [查詢名單.xlsx]

XLSX 欄位順序：姓名 | 醫院 | 身分證字號 | 出生日期(民國年/月/日) | 查詢結果 | 查詢時間
"""

import sys
import re
import time
import random
from datetime import datetime

import requests
import urllib3
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

from wanfang_query import query_one as wanfang_query_one
from tmuh_query import parse_birth_date, tmuh_query_one, parse_response

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TMUH_QUERY_URL = "https://www.tmuh.org.tw/service/query"
DELAY_MIN = 1
DELAY_MAX = 5


def _tmuh_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": TMUH_QUERY_URL,
    })
    return s


def _wanfang_session():
    from wanfang_query import BASE_URL, HEADERS
    s = requests.Session()
    s.headers.update(HEADERS)
    return s




def run_batch(xlsx_path):
    wb = load_workbook(xlsx_path)
    ws = wb.active

    result_col = 5
    time_col   = 6

    ok_fill  = PatternFill("solid", start_color="E2EFDA")
    err_fill = PatternFill("solid", start_color="FCE4D6")
    font     = Font(name="Arial", size=11)

    tmuh_session  = _tmuh_session()
    wf_session    = _wanfang_session()

    total = 0
    for row in ws.iter_rows(min_row=2):
        if len(row) < 4:
            continue

        name      = str(row[0].value or "").strip()
        hospital  = str(row[1].value or "").strip()
        id_no     = str(row[2].value or "").strip()
        birth_raw = str(row[3].value or "").strip()

        if not id_no:
            continue

        hospital_tag = hospital if hospital else "北醫附醫"
        is_wanfang   = "萬芳" in hospital_tag

        print(f"  [{hospital_tag}] {id_no} ({birth_raw})...", end=" ", flush=True)

        if is_wanfang:
            result = wanfang_query_one(wf_session, id_no=id_no)
        else:
            if not birth_raw:
                result = "北醫附醫需填出生日期"
                fill = err_fill
            else:
                parsed = parse_birth_date(birth_raw)
                if not parsed:
                    result = "出生日期格式錯誤"
                else:
                    y, m, d = parsed
                    result = tmuh_query_one(tmuh_session, id_no, y, m, d)

        print(result[:50])
        is_err = any(k in result for k in ["查不到", "錯誤", "失敗", "超過", "格式"])
        fill = err_fill if is_err else ok_fill
        total += 1

        result_cell = ws.cell(row=row[0].row, column=result_col, value=result)
        result_cell.font = font
        result_cell.fill = fill
        result_cell.alignment = Alignment(vertical="center", wrap_text=True)

        time_cell = ws.cell(row=row[0].row, column=time_col,
                            value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        time_cell.font = font
        time_cell.fill = fill
        time_cell.alignment = Alignment(horizontal="center", vertical="center")

        if total > 1:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            print(f"  等待 {delay:.1f} 秒...")
            time.sleep(delay)

    ws.column_dimensions["E"].width = 45
    ws.column_dimensions["F"].width = 20

    stem      = xlsx_path.rsplit(".", 1)[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = f"{stem}_{timestamp}.xlsx"
    wb.save(out_path)
    print(f"\n完成，共查詢 {total} 筆，結果已儲存至 {out_path}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "查詢名單.xlsx"
    print(f"讀取 {path} ...")
    run_batch(path)
