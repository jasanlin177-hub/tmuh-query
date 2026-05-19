"""
批次掛號查詢 - 從 XLSX 讀取名單，逐一查詢並將結果寫回同一份檔案
用法: python batch_query.py [查詢名單.xlsx]
"""

import sys
import time
import re
from datetime import datetime

import random
import requests
from bs4 import BeautifulSoup
import ddddocr
import urllib3
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://www.tmuh.org.tw"
QUERY_URL = f"{BASE_URL}/service/query"
VCODE_URL = f"{BASE_URL}/Ctrl/VCode.ashx"
MAX_RETRY = 5
DELAY_MIN, DELAY_MAX = 1, 5  # 每筆查詢間隔秒數（亂數）


def get_page_state(session):
    resp = session.get(QUERY_URL, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    state = {}
    for field in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTTARGET",
                  "__EVENTARGUMENT", "__LASTFOCUS"]:
        tag = soup.find("input", {"name": field})
        state[field] = tag["value"] if tag else ""
    return state


def get_captcha_text(session):
    resp = session.get(VCODE_URL, timeout=10, verify=False)
    resp.raise_for_status()
    ocr = ddddocr.DdddOcr(show_ad=False)
    clean = re.sub(r'[^a-zA-Z0-9]', '', ocr.classification(resp.content))
    return clean


def parse_response(html):
    soup = BeautifulSoup(html, "lxml")

    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for s in scripts:
        stripped = s.strip().lstrip('//<![CDATA[').rstrip('//]]>').strip()
        m = re.match(r"alert\s*\(['\"](.+?)['\"]\)", stripped)
        if m:
            msg = m.group(1)
            if "驗證碼" in msg and ("錯誤" in msg or "重新" in msg):
                return "CAPTCHA_ERROR"
            return f"伺服器訊息：{msg}"

    tables = soup.find_all("table")
    results = []
    for t in tables:
        text = t.get_text("\n", strip=True)
        if any(k in text for k in ["門診", "科別", "醫師", "掛號", "日期", "看診"]):
            results.append(text)
    if results:
        return "\n".join(results)

    body_text = soup.get_text()
    if "查無" in body_text or "查不到" in body_text:
        return "查無90天內掛號資料"

    return "查詢完成（無法解析結果）"


def parse_birth_date(raw):
    """將 '074/06/23' 或 '74/6/23' 解析為 (year_str, month_str, day_str)"""
    raw = str(raw).strip()
    parts = re.split(r'[/\-\.]', raw)
    if len(parts) != 3:
        return None
    y, m, d = [p.strip() for p in parts]
    return y.zfill(3), m.zfill(2), d.zfill(2)


def query_one(session, id_no, birth_year, birth_month, birth_day):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            state = get_page_state(session)
            captcha = get_captcha_text(session)
        except requests.RequestException as e:
            if attempt == MAX_RETRY:
                return f"網路錯誤：{e}"
            time.sleep(2)
            continue

        if not captcha:
            continue

        form_data = {
            "__EVENTTARGET": "ctl00$MainPlaceHolder$ctl00$btnSubmit",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
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
            resp = session.post(QUERY_URL, data=form_data, timeout=15, verify=False)
            resp.raise_for_status()
        except requests.RequestException as e:
            if attempt == MAX_RETRY:
                return f"送出失敗：{e}"
            time.sleep(2)
            continue

        result = parse_response(resp.text)
        if result == "CAPTCHA_ERROR":
            time.sleep(1)
            continue

        return result

    return "超過重試次數，請稍後再試"


def run_batch(xlsx_path):
    wb = load_workbook(xlsx_path)
    ws = wb.active

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": QUERY_URL,
    })

    result_col = 4
    time_col = 5

    ok_fill = PatternFill("solid", start_color="E2EFDA")
    err_fill = PatternFill("solid", start_color="FCE4D6")
    font = Font(name="Arial", size=11)

    total = 0
    for row in ws.iter_rows(min_row=2):
        id_cell = row[1]
        birth_cell = row[2]

        id_no = str(id_cell.value or "").strip()
        birth_raw = str(birth_cell.value or "").strip()

        if not id_no or not birth_raw:
            continue

        parsed = parse_birth_date(birth_raw)
        if not parsed:
            result = "出生日期格式錯誤（請填 民國年/月/日）"
            fill = err_fill
        else:
            birth_year, birth_month, birth_day = parsed
            print(f"  查詢 {id_no} ({birth_raw})...", end=" ", flush=True)
            result = query_one(session, id_no, birth_year, birth_month, birth_day)
            print(result[:40])
            fill = ok_fill if "查無" not in result and "錯誤" not in result and "失敗" not in result else err_fill
            total += 1
            if total > 1:
                delay = random.uniform(DELAY_MIN, DELAY_MAX)
                print(f"  等待 {delay:.1f} 秒...")
                time.sleep(delay)

        result_cell = ws.cell(row=row[0].row, column=result_col, value=result)
        result_cell.font = font
        result_cell.fill = fill
        result_cell.alignment = Alignment(vertical="center", wrap_text=True)

        time_cell = ws.cell(row=row[0].row, column=time_col,
                            value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        time_cell.font = font
        time_cell.fill = fill
        time_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.column_dimensions["D"].width = 45
    ws.column_dimensions["E"].width = 20

    stem = xlsx_path.rsplit(".", 1)[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = f"{stem}_{timestamp}.xlsx"
    wb.save(out_path)
    print(f"\n完成，共查詢 {total} 筆，結果已儲存至 {out_path}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "查詢名單.xlsx"
    print(f"讀取 {path} ...")
    run_batch(path)
