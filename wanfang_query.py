"""
萬芳醫院掛號查詢核心模組
使用 ddddocr 辨識純數字驗證碼（與北醫附醫共用同一套件，不需額外安裝）
"""

import re
import time

import requests
from bs4 import BeautifulSoup
import ddddocr
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL    = "https://wwww.wanfang.gov.tw/reg/register_cancel_cload.aspx"
CAPTCHA_URL = "https://wwww.wanfang.gov.tw/reg/ValidateNumber.ashx"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}


def get_page_state(session):
    resp = session.get(BASE_URL, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    fields = [
        "__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS",
        "__VIEWSTATE", "__VIEWSTATEGENERATOR",
        "__VIEWSTATEENCRYPTED", "__EVENTVALIDATION",
    ]
    state = {}
    for f in fields:
        tag = soup.find("input", {"name": f}) or soup.find("input", {"id": f})
        state[f] = tag["value"] if tag and tag.get("value") else ""
    return state


def get_captcha_text(session):
    resp = session.get(CAPTCHA_URL, timeout=10, verify=False)
    resp.raise_for_status()
    ocr = ddddocr.DdddOcr(show_ad=False)
    result = ocr.classification(resp.content)
    # 萬芳驗證碼為純數字
    clean = re.sub(r"\D", "", result)
    print(f"  [OCR-萬芳] 辨識驗證碼: {clean!r}")
    return clean


def parse_response(html):
    soup = BeautifulSoup(html, "lxml")

    # 偵測 inline JS alert
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for s in scripts:
        stripped = s.strip().lstrip('//<![CDATA[').rstrip('//]]>').strip()
        m = re.match(r"alert\s*\(['\"](.+?)['\"]\)", stripped)
        if m:
            msg = m.group(1)
            if any(k in msg for k in ["驗證碼", "重新輸入", "錯誤"]):
                return "CAPTCHA_ERROR"
            return f"伺服器訊息：{msg}"

    # 偵測頁面文字中的驗證碼錯誤
    body = soup.get_text()
    if "驗證碼錯誤" in body or "請重新輸入驗證碼" in body:
        return "CAPTCHA_ERROR"

    # 找含掛號資訊的 table
    tables = soup.find_all("table")
    results = []
    for t in tables:
        text = t.get_text("\n", strip=True)
        if any(k in text for k in ["門診", "科別", "醫師", "掛號", "日期", "看診", "取消"]):
            results.append(text)
    if results:
        return "\n\n".join(results)

    if "查無資料" in body or "查不到" in body or "無掛號" in body:
        return "查無90天內掛號資料"

    return "查詢完成（無法解析結果）"


def query_one(session, id_no="", alien_no="", chr_no="", max_retry=5):
    for attempt in range(1, max_retry + 1):
        try:
            state = get_page_state(session)
            captcha = get_captcha_text(session)
        except requests.RequestException as e:
            if attempt == max_retry:
                return f"網路錯誤：{e}"
            time.sleep(2)
            continue

        if len(captcha) < 4:
            print("  [!] 驗證碼過短，重試...")
            continue

        payload = {
            **state,
            "ctl00$ContentPlaceHolder1$tb_id":     id_no,
            "ctl00$ContentPlaceHolder1$tb_id2":    alien_no,
            "ctl00$ContentPlaceHolder1$tb_ChrNo":  chr_no,
            "ctl00$ContentPlaceHolder1$txt_input": captcha,
            "ctl00$ContentPlaceHolder1$ButtonC":   "查詢",
        }

        try:
            resp = session.post(BASE_URL, data=payload, timeout=15, verify=False)
            resp.raise_for_status()
        except requests.RequestException as e:
            if attempt == max_retry:
                return f"送出失敗：{e}"
            time.sleep(2)
            continue

        result = parse_response(resp.text)
        if result == "CAPTCHA_ERROR":
            print("  [!] 驗證碼錯誤，重試...")
            time.sleep(1)
            continue

        return result

    return "超過重試次數，請稍後再試"


if __name__ == "__main__":
    import sys
    id_no = sys.argv[1] if len(sys.argv) > 1 else ""
    if not id_no:
        print("用法: python wanfang_query.py <身分證字號>")
        sys.exit(1)
    s = requests.Session()
    s.headers.update(HEADERS)
    result = query_one(s, id_no=id_no)
    print("\n===== 萬芳掛號查詢結果 =====")
    print(result)
