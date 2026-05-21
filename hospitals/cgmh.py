"""長庚醫療財團法人 台北長庚 掛號查詢（AJAX JSON 格式）"""

import json
import re
import time
import random

import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase
from . import ocr as _ocr_mod

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_QUERY_URL   = "https://register.cgmh.org.tw/Query/1"
_AJAX_URL    = "https://register.cgmh.org.tw/Ajax"
_CAPTCHA_URL = "https://register.cgmh.org.tw/Content/BuildCaptcha.aspx"
_MAX_RETRY   = 5


def _birth_to_cgmh(birth_year: str, birth_month: str, birth_day: str) -> str:
    """'074','06','23' → '740623'（民國年去前導零）"""
    return f"{int(birth_year)}{birth_month.zfill(2)}{birth_day.zfill(2)}"


def _get_csrf_token(session):
    resp = session.get(_QUERY_URL, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    tag = (soup.find("input", {"name": "__RequestVerificationToken"}) or
           soup.find("meta",  {"name": "__RequestVerificationToken"}))
    if tag:
        return tag.get("value") or tag.get("content") or ""
    return ""


def _get_captcha(session):
    resp = session.get(f"{_CAPTCHA_URL}?{random.random()}", timeout=10, verify=False)
    resp.raise_for_status()
    result = _ocr_mod.classify(resp.content)
    clean = re.sub(r'\s+', '', result)
    print(f"  [OCR-長庚] {clean!r}")
    return clean


def _parse_response(text: str) -> str:
    # 回應為 JSON 格式
    try:
        data = json.loads(text)
    except Exception:
        # fallback: 純文字錯誤訊息
        if any(k in text for k in ["驗證碼", "驗證失敗"]):
            return "CAPTCHA_ERROR"
        return "查詢完成，但無法解析回應"

    code_err  = str(data.get("codeError", "N")).upper()
    query_list = data.get("QueryList", "") or ""

    if code_err == "Y":
        return "CAPTCHA_ERROR"

    if not query_list.strip():
        return "查無90天內掛號資料"

    # QueryList 是 HTML 片段，解析 table
    soup = BeautifulSoup(query_list, "lxml")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if not any(h in headers for h in ["看診日期", "門診日期", "科別", "醫師", "時段", "診次"]):
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

    return soup.get_text("\n", strip=True) or "查無90天內掛號資料"


class CGMH(HospitalBase):
    display_name = "長庚醫院（台北）"
    needs_birth  = True

    def make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer":          _QUERY_URL,
            "X-Requested-With": "XMLHttpRequest",
            "Accept":           "application/json, text/javascript, */*; q=0.01",
        })
        return s

    def query_one(self, session, id_no, birth_year="", birth_month="", birth_day=""):
        birthday = _birth_to_cgmh(birth_year, birth_month, birth_day)

        for attempt in range(1, _MAX_RETRY + 1):
            try:
                csrf_token = _get_csrf_token(session)
                captcha    = _get_captcha(session)
            except requests.RequestException as e:
                if attempt == _MAX_RETRY:
                    return f"網路錯誤：{e}"
                time.sleep(2)
                continue

            if len(captcha) < 3:
                print("  [!] 驗證碼過短，重試...")
                continue

            val = json.dumps([
                {"name": "hospitalID",   "value": "1"},
                {"name": "patNumber",    "value": ""},
                {"name": "ENOCO",        "value": ""},
                {"name": "KD01",         "value": ""},
                {"name": "KD02",         "value": ""},
                {"name": "KD03",         "value": ""},
                {"name": "KD04",         "value": ""},
                {"name": "KD05",         "value": ""},
                {"name": "KD06",         "value": ""},
                {"name": "isFirst",      "value": "N"},
                {"name": "idType",       "value": ""},
                {"name": "idNumber",     "value": id_no},
                {"name": "birthday",     "value": birthday},
                {"name": "verification", "value": captcha},
            ], ensure_ascii=False, separators=(",", ":"))

            payload = {
                "__RequestVerificationToken": csrf_token,
                "Func": "QuerySearch",
                "Val":  val,
            }

            try:
                resp = session.post(_AJAX_URL, data=payload, timeout=15, verify=False)
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
