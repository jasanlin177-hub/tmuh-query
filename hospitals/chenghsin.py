"""振興醫療財團法人振興醫院 掛號查詢"""

import re
import time
import random

import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase
from . import ocr as _ocr_mod

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE_URL    = "https://reg.chgh.org.tw/inquire_cload.aspx"
_CAPTCHA_URL = "https://reg.chgh.org.tw/ValidateNumber.ashx"
_MAX_RETRY   = 5
_PFX         = "ctl00$ContentPlaceHolder1$"


def _roc_to_western(birth_year: str) -> str:
    return str(int(birth_year) + 1911)


def _get_page_state(session):
    resp = session.get(_BASE_URL, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    fields = ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION",
              "__EVENTTARGET", "__EVENTARGUMENT"]
    state = {}
    for f in fields:
        tag = soup.find("input", {"name": f}) or soup.find("input", {"id": f})
        state[f] = tag["value"] if tag and tag.get("value") else ""
    return state


def _get_captcha(session):
    url = f"{_CAPTCHA_URL}?{random.random()}"
    resp = session.get(url, timeout=10, verify=False)
    resp.raise_for_status()
    result = _ocr_mod.classify(resp.content)
    clean = re.sub(r"\D", "", result)
    print(f"  [OCR-振興] {clean!r}")
    return clean


def _parse_response(html):
    soup = BeautifulSoup(html, "lxml")

    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for s in scripts:
        stripped = s.strip().lstrip('//<![CDATA[').rstrip('//]]>').strip()
        m = re.match(r"alert\s*\(['\"](.+?)['\"]\)", stripped)
        if m:
            msg = m.group(1)
            if any(k in msg for k in ["驗證碼", "錯誤", "重新"]):
                return "CAPTCHA_ERROR"
            return f"伺服器訊息：{msg}"

    body = soup.get_text()
    if "驗證碼輸入不正確" in body:
        return "CAPTCHA_ERROR"

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if not any(h in headers for h in ["看診日期", "門診日期", "科別", "醫師", "時段"]):
            continue
        appointments = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or all(c == "" for c in cells):
                continue
            lines = [f"{h}：{v}" for h, v in zip(headers, cells) if h and v]
            appointments.append("\n".join(lines))
        if appointments:
            return "\n\n".join(appointments)
        return "查無90天內掛號資料"

    if any(k in body for k in ["查無", "無掛號", "查不到"]):
        return "查無90天內掛號資料"
    return "查詢完成，但無法自動解析結果（醫院版面可能已更新）"


class ChengHsin(HospitalBase):
    display_name = "振興醫院"
    needs_birth  = True

    def make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": _BASE_URL,
        })
        return s

    def query_one(self, session, id_no, birth_year="", birth_month="", birth_day=""):
        western_year = _roc_to_western(birth_year)

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

            form_data = {
                **state,
                f"{_PFX}type2":             "RadioButton1",
                f"{_PFX}tb_id":             id_no,
                f"{_PFX}ddl_birthDay_year":  western_year,
                f"{_PFX}ddl_birthDay_month": birth_month,
                f"{_PFX}ddl_birthDay_day":   birth_day,
                f"{_PFX}txt_input":          captcha,
                f"{_PFX}ButtonC":            "查詢",
            }

            try:
                resp = session.post(_BASE_URL, data=form_data, timeout=15, verify=False)
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
