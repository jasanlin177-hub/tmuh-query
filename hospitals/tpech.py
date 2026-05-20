"""臺北市立聯合醫院 掛號查詢"""

import re
import time

import ddddocr
import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE_URL    = "https://webreg.tpech.gov.tw/RegOnline3_1.aspx"
_QUERY_URL   = f"{_BASE_URL}?ChaId=A103&tab=3"
_CAPTCHA_URL = "https://webreg.tpech.gov.tw/ValidateCode.aspx"
_MAX_RETRY   = 5


def _get_page_state(session):
    resp = session.get(_QUERY_URL, timeout=15, verify=False)
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
    resp = session.get(_CAPTCHA_URL, timeout=10, verify=False)
    resp.raise_for_status()
    ocr = ddddocr.DdddOcr(show_ad=False)
    result = ocr.classification(resp.content)
    clean = re.sub(r"\D", "", result)
    print(f"  [OCR-聯合] {clean!r}")
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

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True) for c in header_cells]
        if not any(h in headers for h in ["看診日期", "看診醫師", "時段", "門診日期", "科別"]):
            continue
        appointments = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or all(c == "" for c in cells):
                continue
            lines = []
            for h, v in zip(headers, cells):
                h, v = h.strip(), v.strip()
                if h and v and v != h:
                    lines.append(f"{h}：{v}")
                elif h:
                    lines.append(h)
            appointments.append("\n".join(lines))
        if appointments:
            return "\n\n".join(appointments)
        return "查無90天內掛號資料"

    body = soup.get_text()
    if "查無" in body or "查不到" in body or "無資料" in body:
        return "查無90天內掛號資料"
    return "查詢完成，但無法自動解析結果（醫院版面可能已更新）"


class TPECH(HospitalBase):
    display_name = "臺北市立聯合醫院"
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

            if len(captcha) < 4:
                print("  [!] 驗證碼過短，重試...")
                continue

            form_data = {
                "__VIEWSTATE":          state["__VIEWSTATE"],
                "__VIEWSTATEGENERATOR": state["__VIEWSTATEGENERATOR"],
                "__EVENTVALIDATION":    state["__EVENTVALIDATION"],
                "__EVENTTARGET":        "",
                "__EVENTARGUMENT":      "",
                "no":        id_no,
                "PAT_IDNO":  "1",
                "yeartype":  "A",
                "y1":        birth_year,
                "m1":        birth_month,
                "d1":        birth_day,
                "TextBox1":  captcha,
                "YRadio":    "A103",
                "Button1":   "查詢",
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
