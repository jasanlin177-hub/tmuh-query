"""國立臺灣大學醫學院附設醫院 掛號查詢（ASP.NET MVC）"""

import re
import time
import random

import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase
from . import ocr as _ocr_mod

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE_URL  = "https://reg.ntuh.gov.tw/WebReg/WebReg/InquiryCancelReg"
_MAX_RETRY = 5


def _get_page_state(session):
    resp = session.get(_BASE_URL, timeout=15, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    token_tag = (soup.find("input", {"name": "__RequestVerificationToken"}) or
                 soup.find("meta",  {"name": "__RequestVerificationToken"}))
    csrf = token_tag.get("value") or token_tag.get("content") if token_tag else ""

    img_tag = soup.find("img", {"src": re.compile(r"ValidNumerImage", re.I)})
    captcha_src = img_tag["src"] if img_tag else "ValidNumerImage"

    # 將相對路徑補全
    if not captcha_src.startswith("http"):
        base = _BASE_URL.rsplit("/", 1)[0]
        captcha_src = f"{base}/{captcha_src.lstrip('/')}"

    return csrf, captcha_src


def _get_captcha(session, captcha_url):
    resp = session.get(f"{captcha_url}&_={random.random()}", timeout=10, verify=False)
    resp.raise_for_status()
    result = _ocr_mod.classify(resp.content)
    clean = re.sub(r'\s+', '', result)
    print(f"  [OCR-臺大] {clean!r}")
    return clean


def _parse_response(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    body = soup.get_text()

    if any(k in body for k in ["驗證碼錯誤", "驗證碼不正確", "驗證碼有誤", "請填寫必填欄位"]):
        return "CAPTCHA_ERROR"

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if not any(h in headers for h in ["看診日期", "門診日期", "科別", "醫師", "時段", "診次", "掛號日期"]):
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

    if any(k in body for k in ["查無", "無掛號", "查不到", "無預約", "查無預約"]):
        return "查無90天內掛號資料"
    return "查詢完成，但無法自動解析結果（醫院版面可能已更新）"


class NTUH(HospitalBase):
    display_name = "臺大附醫"
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
        for attempt in range(1, _MAX_RETRY + 1):
            try:
                csrf, captcha_url = _get_page_state(session)
                captcha = _get_captcha(session, captcha_url)
            except requests.RequestException as e:
                if attempt == _MAX_RETRY:
                    return f"網路錯誤：{e}"
                time.sleep(2)
                continue

            if len(captcha) < 3:
                print("  [!] 驗證碼過短，重試...")
                continue

            payload = {
                "__RequestVerificationToken": csrf,
                "vHospCode":        "T0",
                "RadInputType":     "personID",
                "txtInputID":       id_no,
                "txtBirthday_Year":  str(int(birth_year)),
                "txtBirthday_Month": str(int(birth_month)),
                "txtBirthday_Day":   str(int(birth_day)),
                "txtVerifyCode":    captcha,
                "btnAction":        "formSubmit",
            }

            try:
                resp = session.post(_BASE_URL, data=payload, timeout=15, verify=False,
                                    allow_redirects=True)
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
