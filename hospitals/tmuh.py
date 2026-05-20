"""臺北醫學大學附設醫院 掛號查詢"""

import re
import time

import ddddocr
import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE_URL  = "https://www.tmuh.org.tw"
_QUERY_URL = f"{_BASE_URL}/service/query"
_VCODE_URL = f"{_BASE_URL}/Ctrl/VCode.ashx"
_MAX_RETRY = 5


def parse_birth_date(raw: str):
    """'074/06/23' → ('074', '06', '23')"""
    parts = re.split(r'[/\-\.]', str(raw).strip())
    if len(parts) != 3:
        return None
    y, m, d = [p.strip() for p in parts]
    return y.zfill(3), m.zfill(2), d.zfill(2)


def _get_page_state(session):
    resp = session.get(_QUERY_URL, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    state = {}
    for field in ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTTARGET",
                  "__EVENTARGUMENT", "__LASTFOCUS"]:
        tag = soup.find("input", {"name": field})
        state[field] = tag["value"] if tag else ""
    return state


def _get_captcha(session):
    resp = session.get(_VCODE_URL, timeout=10, verify=False)
    resp.raise_for_status()
    ocr = ddddocr.DdddOcr(show_ad=False)
    result = ocr.classification(resp.content)
    clean = re.sub(r'[^a-zA-Z0-9]', '', result)
    print(f"  [OCR-北醫] {clean!r}")
    return clean


def _format_appointment(headers, cells, location=""):
    lines = []
    for h, v in zip(headers, cells):
        h, v = h.strip(), v.strip()
        if not h:
            continue
        if v and v != h:
            lines.append(f"{h}：{v}")
        else:
            lines.append(h)
    if location:
        lines.append(f"診間位置：{location}")
    return "\n".join(lines)


def _parse_response(html):
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

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
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
            if cells[0] == "診間位置":
                i += 1
                continue
            location = ""
            if i + 1 < len(rows):
                next_cells = [td.get_text(strip=True) for td in rows[i + 1].find_all("td")]
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
        return "查無90天內掛號資料"

    body_text = soup.get_text()
    if "查無" in body_text or "查不到" in body_text:
        return "查無90天內掛號資料"
    return "查詢完成，但無法自動解析結果（醫院版面可能已更新）"


class TMUH(HospitalBase):
    display_name = "北醫附醫"
    needs_birth  = True

    def make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": _QUERY_URL,
        })
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

            if not captcha:
                continue

            form_data = {
                "__EVENTTARGET":   "ctl00$MainPlaceHolder$ctl00$btnSubmit",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS":     "",
                "__VIEWSTATE":     state["__VIEWSTATE"],
                "__VIEWSTATEGENERATOR": state["__VIEWSTATEGENERATOR"],
                "ctl00$MainPlaceHolder$ctl00$txtIDNo":    id_no,
                "ctl00$MainPlaceHolder$ctl00$txtPatNo":   "",
                "ctl00$MainPlaceHolder$ctl00$txtPatPwd":  "",
                "ctl00$MainPlaceHolder$ctl00$cbCate":     "A",
                "ctl00$MainPlaceHolder$ctl00$cbYear":     birth_year,
                "ctl00$MainPlaceHolder$ctl00$cbMonth":    birth_month,
                "ctl00$MainPlaceHolder$ctl00$cbDay":      birth_day,
                "vCode": captcha,
            }
            try:
                resp = session.post(_QUERY_URL, data=form_data, timeout=15, verify=False)
                resp.raise_for_status()
            except requests.RequestException as e:
                if attempt == _MAX_RETRY:
                    return f"送出失敗：{e}"
                time.sleep(2)
                continue

            result = _parse_response(resp.text)
            if result == "CAPTCHA_ERROR":
                time.sleep(1)
                continue
            return result

        return "超過重試次數，請稍後再試"
