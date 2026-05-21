"""萬芳醫院 掛號查詢"""

import re
import time

import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase
from . import ocr as _ocr_mod

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE_URL    = "https://wwww.wanfang.gov.tw/reg/register_cancel_cload.aspx"
_CAPTCHA_URL = "https://wwww.wanfang.gov.tw/reg/ValidateNumber.ashx"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": _BASE_URL,
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}
_MAX_RETRY = 5


def _get_page_state(session):
    resp = session.get(_BASE_URL, timeout=25, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    fields = ["__EVENTTARGET", "__EVENTARGUMENT", "__LASTFOCUS",
              "__VIEWSTATE", "__VIEWSTATEGENERATOR",
              "__VIEWSTATEENCRYPTED", "__EVENTVALIDATION"]
    state = {}
    for f in fields:
        tag = soup.find("input", {"name": f}) or soup.find("input", {"id": f})
        state[f] = tag["value"] if tag and tag.get("value") else ""
    return state


def _get_captcha(session):
    resp = session.get(_CAPTCHA_URL, timeout=10, verify=False)
    resp.raise_for_status()
    result = _ocr_mod.classify(resp.content)
    clean = re.sub(r"\D", "", result)
    print(f"  [OCR-萬芳] {clean!r}")
    return clean


def _parse_response(html):
    soup = BeautifulSoup(html, "lxml")
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for s in scripts:
        stripped = s.strip().lstrip('//<![CDATA[').rstrip('//]]>').strip()
        m = re.match(r"alert\s*\(['\"](.+?)['\"]\)", stripped)
        if m:
            msg = m.group(1)
            if any(k in msg for k in ["驗證碼", "重新輸入", "錯誤"]):
                return "CAPTCHA_ERROR"
            return f"伺服器訊息：{msg}"

    body = soup.get_text()
    if "驗證碼錯誤" in body or "請重新輸入驗證碼" in body:
        return "CAPTCHA_ERROR"

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if not any(h in headers for h in ["就診日期", "看診日期", "門診日期", "科別", "就診科別", "醫師", "就診醫師"]):
            continue
        appointments = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or all(c == "" for c in cells):
                continue
            lines = [f"{h}：{v}" for h, v in zip(headers, cells) if h and v]
            if lines:
                appointments.append("\n".join(lines))
        if appointments:
            return "\n\n".join(appointments)
        return "查無90天內掛號資料"

    if "查無資料" in body or "查不到" in body or "無掛號" in body:
        return "查無90天內掛號資料"

    return "查詢完成（無法解析結果）"


class Wanfang(HospitalBase):
    display_name = "萬芳醫院"
    needs_birth  = False

    def make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(_HEADERS)
        return s

    def query_one(self, session, id_no, birth_year="", birth_month="", birth_day=""):
        for attempt in range(1, _MAX_RETRY + 1):
            try:
                state   = _get_page_state(session)
                captcha = _get_captcha(session)
            except requests.RequestException as e:
                if attempt == _MAX_RETRY:
                    return f"網路錯誤：{e}"
                time.sleep(2)
                continue

            if len(captcha) < 4:
                print("  [!] 驗證碼過短，重試...")
                continue

            payload = {
                **state,
                "ctl00$ContentPlaceHolder1$tb_id":     id_no,
                "ctl00$ContentPlaceHolder1$tb_id2":    "",
                "ctl00$ContentPlaceHolder1$tb_ChrNo":  "",
                "ctl00$ContentPlaceHolder1$txt_input": captcha,
                "ctl00$ContentPlaceHolder1$ButtonC":   "查詢",
            }
            try:
                resp = session.post(_BASE_URL, data=payload, timeout=25, verify=False)
                resp.raise_for_status()
            except requests.RequestException as e:
                if attempt == _MAX_RETRY:
                    return f"送出失敗：{e}"
                time.sleep(2)
                continue

            result = _parse_response(resp.text)
            if result == "CAPTCHA_ERROR":
                print("  [!] 驗證碼錯誤，重試...")
                time.sleep(1)
                continue
            return result

        return "超過重試次數，請稍後再試"
