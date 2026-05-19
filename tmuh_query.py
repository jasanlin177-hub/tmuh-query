"""
臺北醫學大學附設醫院 - 掛號查詢自動化程式
requests + ddddocr OCR 版（自動辨識驗證碼）

安裝：pip install requests ddddocr beautifulsoup4 lxml
"""

import requests
from bs4 import BeautifulSoup
import ddddocr
import re
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===== 設定你的個人資料 =====
CONFIG = {
    "id_no": "A226127572",          # 身分證字號，例: A123456789
    "pat_no": "",         # 病歷號（與身分證擇一，身分證優先）
    "member_pwd": "",     # 會員密碼（非會員留空）
    "birth_type": "A",    # "A"=本國人士(民國年), "B"=外籍人士(西元年)
    "birth_year": "074",     # 民國年，例: 075（出生西元1986年 → 民國075年）
    "birth_month": "06",    # 月份，例: 03
    "birth_day": "23",      # 日期，例: 15
}

BASE_URL = "https://www.tmuh.org.tw"
QUERY_URL = f"{BASE_URL}/service/query"
VCODE_URL = f"{BASE_URL}/Ctrl/VCode.ashx"
MAX_RETRY = 5


def get_page_state(session):
    """取得 VIEWSTATE 等 ASP.NET 隱藏欄位"""
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
    """下載驗證碼圖片並用 OCR 辨識"""
    resp = session.get(VCODE_URL, timeout=10, verify=False)
    resp.raise_for_status()
    ocr = ddddocr.DdddOcr(show_ad=False)
    result = ocr.classification(resp.content)
    clean = re.sub(r'[^a-zA-Z0-9]', '', result)
    print(f"  [OCR] 辨識驗證碼: {clean!r}")
    return clean


TMUH_FIELDS = ["看診日期", "看診醫師", "時段", "科別", "診間號碼",
               "看診序號", "預計報到時間", "門診狀態", "取消看診", "診間位置"]


def _format_appointment(headers, cells, location=""):
    """將一筆掛號資料的欄位與值組成結構化字串。"""
    lines = []
    for h, v in zip(headers, cells):
        h = h.strip()
        v = v.strip()
        if not h:
            continue
        if v and v != h:
            lines.append(f"{h}：{v}")
        else:
            lines.append(h)
    if location:
        lines.append(f"診間位置：{location}")
    return "\n".join(lines)


def parse_response(html):
    """解析回應 HTML，取出掛號資訊並格式化為結構化文字。"""
    soup = BeautifulSoup(html, "lxml")

    # 只偵測立即執行的 inline alert
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for s in scripts:
        stripped = s.strip().lstrip('//<![CDATA[').rstrip('//]]>').strip()
        m = re.match(r"alert\s*\(['\"](.+?)['\"]\)", stripped)
        if m:
            msg = m.group(1)
            if "驗證碼" in msg and ("錯誤" in msg or "重新" in msg):
                return "CAPTCHA_ERROR"
            return f"伺服器訊息：{msg}"

    # 找含掛號欄位的 table，解析為結構化資料
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        # 取得表頭（th 或第一列 td）
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True) for c in header_cells]

        if not any(h in headers for h in ["看診日期", "看診醫師", "時段"]):
            continue

        appointments = []
        i = 1
        while i < len(rows):
            cells = [td.get_text(strip=True) for td in rows[i].find_all("td")]
            if not cells or all(c == "" for c in cells):
                i += 1
                continue

            # 跳過「診間位置」標題列（由下方配對處理）
            if cells[0] == "診間位置":
                i += 1
                continue

            # 資料列：向下找相鄰的「診間位置」子列
            location = ""
            if i + 1 < len(rows):
                next_cells = [td.get_text(strip=True)
                              for td in rows[i + 1].find_all("td")]
                if next_cells and next_cells[0] == "診間位置":
                    location = next_cells[1] if len(next_cells) > 1 else ""
                    i += 2
                else:
                    i += 1
            else:
                i += 1

            appointments.append(_format_appointment(headers, cells, location))

        if appointments:
            return "\n\n".join(appointments)
        else:
            return "查無90天內掛號資料"

    # 查無資料訊息（頁面文字）
    body_text = soup.get_text()
    if "查無" in body_text or "查不到" in body_text:
        return "查無90天內掛號資料"

    return "查詢完成，但無法自動解析結果（醫院版面可能已更新）"


def query_registration():
    if not CONFIG["id_no"] and not CONFIG["pat_no"]:
        print("[錯誤] 請在 CONFIG 中填入身分證字號或病歷號")
        return None
    if not all([CONFIG["birth_year"], CONFIG["birth_month"], CONFIG["birth_day"]]):
        print("[錯誤] 請在 CONFIG 中填入出生年月日")
        return None

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": QUERY_URL,
    })

    for attempt in range(1, MAX_RETRY + 1):
        print(f"\n[嘗試 {attempt}/{MAX_RETRY}] 取得頁面狀態...")
        try:
            state = get_page_state(session)
            print("  取得驗證碼...")
            captcha = get_captcha_text(session)
        except requests.RequestException as e:
            print(f"  [!] 網路錯誤: {e}")
            time.sleep(2)
            continue

        if not captcha:
            print("  [!] 驗證碼辨識為空，重試...")
            continue

        form_data = {
            "__EVENTTARGET": "ctl00$MainPlaceHolder$ctl00$btnSubmit",
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": state["__VIEWSTATE"],
            "__VIEWSTATEGENERATOR": state["__VIEWSTATEGENERATOR"],
            "ctl00$MainPlaceHolder$ctl00$txtIDNo": CONFIG["id_no"],
            "ctl00$MainPlaceHolder$ctl00$txtPatNo": CONFIG["pat_no"],
            "ctl00$MainPlaceHolder$ctl00$txtPatPwd": CONFIG["member_pwd"],
            "ctl00$MainPlaceHolder$ctl00$cbCate": CONFIG["birth_type"],
            "ctl00$MainPlaceHolder$ctl00$cbYear": CONFIG["birth_year"],
            "ctl00$MainPlaceHolder$ctl00$cbMonth": CONFIG["birth_month"],
            "ctl00$MainPlaceHolder$ctl00$cbDay": CONFIG["birth_day"],
            "vCode": captcha,
        }

        print("  送出查詢...")
        try:
            resp = session.post(QUERY_URL, data=form_data, timeout=15, verify=False)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [!] 送出失敗: {e}")
            time.sleep(2)
            continue

        with open("debug_response.html", "w", encoding="utf-8") as f:
            f.write(resp.text)

        result = parse_response(resp.text)
        if result == "CAPTCHA_ERROR":
            print("  [!] 驗證碼錯誤，重試...")
            time.sleep(1)
            continue

        print("\n===== 掛號查詢結果 =====")
        print(result)
        return result

    print("\n[錯誤] 超過重試次數，請稍後再試")
    return None


if __name__ == "__main__":
    result = query_registration()
    if result:
        with open("result.txt", "w", encoding="utf-8") as f:
            f.write(result)
