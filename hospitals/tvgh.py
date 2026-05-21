"""臺北榮民總醫院 掛號查詢（初診＋複診合併）"""

import re
import time

import time

import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase
from . import ocr as _ocr_mod

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_BASE      = "https://www6.vghtpe.gov.tw"
_MAX_RETRY = 5

_FORMS = [
    {
        "label":     "複診",
        "form_url":  f"{_BASE}/reg/queryForm.do?type=return",
        "query_url": f"{_BASE}/reg/queryResultreturn.do",
        "type":      "return",
    },
    {
        "label":     "初診",
        "form_url":  f"{_BASE}/reg/queryForm.do?type=first",
        "query_url": f"{_BASE}/reg/queryResultfirst.do",
        "type":      "first",
    },
]


def _birth_to_tvgh(birth_year: str, birth_month: str, birth_day: str):
    return str(int(birth_year) + 1911), birth_month.zfill(2), birth_day.zfill(2)


def _fetch_captcha(session, form_url, query_type, label):
    session.get(form_url, timeout=15, verify=False)   # 建立 session cookie
    url = f"{_BASE}/reg/captcha.jpg?time={int(time.time() * 1000)}&type={query_type}"
    resp = session.get(url, timeout=10, verify=False)
    resp.raise_for_status()
    clean = re.sub(r"\D", "", _ocr_mod.classify(resp.content))
    print(f"  [OCR-榮總{label}] {clean!r}")
    return clean


def _parse_response(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    body = soup.get_text()

    if "操作逾時" in body or "session" in body.lower():
        return "CAPTCHA_ERROR"

    if "驗證碼" in body and ("錯誤" in body or "不正確" in body):
        return "CAPTCHA_ERROR"

    if "資料錯誤" in body or "查無" in body or "查不到" in body:
        return "NO_DATA"

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if not any(h in headers for h in ["日期", "看診日期", "門診日期", "科別", "醫師", "時段", "診次"]):
            continue
        _SKIP = {"取消/再次掛號", "取消", "操作"}
        appointments = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells or all(c == "" for c in cells):
                continue
            lines = [f"{h}：{v}" for h, v in zip(headers, cells)
                     if h and v and h not in _SKIP]
            if lines:
                appointments.append("\n".join(lines))
        if appointments:
            return "\n\n".join(appointments)
        return "NO_DATA"

    return "查詢完成，但無法自動解析結果（醫院版面可能已更新）"


def _query_form(session, form, id_no, yyyy, mm, dd) -> str:
    """單一表單（初診或複診）查詢，失敗回傳 NO_DATA。"""
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            captcha = _fetch_captcha(session, form["form_url"], form["type"], form["label"])
        except requests.RequestException as e:
            if attempt == _MAX_RETRY:
                return f"網路錯誤：{e}"
            time.sleep(2)
            continue

        if not captcha or len(captcha) < 3:
            print(f"  [!] 驗證碼過短（{form['label']}），重試...")
            continue

        # 步驟1：AJAX 驗證驗證碼
        try:
            vr = session.post(
                f"{_BASE}/reg/validateCaptcha.do",
                data={"inputCode": captcha, "type": "query"},
                timeout=10, verify=False
            )
            vr.raise_for_status()
            if "false" in vr.text.lower() or "error" in vr.text.lower():
                print(f"  [!] validateCaptcha 回傳失敗（{form['label']}），重試...")
                time.sleep(1)
                continue
        except requests.RequestException as e:
            if attempt == _MAX_RETRY:
                return f"網路錯誤：{e}"
            time.sleep(2)
            continue

        # 步驟2：送出查詢表單
        payload = {
            "type":        form["type"],
            "lang":        "",
            "pid":         id_no,
            "pbirth_yyyy": yyyy,
            "pbirth_mm":   mm,
            "pbirth_dd":   dd,
            "inputCode":   captcha,
            "myButton":    "確定",
        }
        try:
            resp = session.post(form["query_url"], data=payload, timeout=15, verify=False)
            resp.raise_for_status()
        except requests.RequestException as e:
            if attempt == _MAX_RETRY:
                return f"送出失敗：{e}"
            time.sleep(2)
            continue

        result = _parse_response(resp.text)
        if result == "CAPTCHA_ERROR":
            print(f"  [!] 驗證碼錯誤（{form['label']}），重試...")
            time.sleep(1)
            continue
        return result

    return "超過重試次數"


class TVGH(HospitalBase):
    display_name = "臺北榮總"
    needs_birth  = True

    def make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": _FORMS[0]["form_url"],
        })
        return s

    def query_one(self, session, id_no, birth_year="", birth_month="", birth_day=""):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        yyyy, mm, dd = _birth_to_tvgh(birth_year, birth_month, birth_day)

        def _run(form):
            s = self.make_session()
            return form["label"], _query_form(s, form, id_no, yyyy, mm, dd)

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(_run, form) for form in _FORMS]
            results = {label: r for label, r in (f.result() for f in as_completed(futures))}

        parts = []
        for form in _FORMS:
            r = results.get(form["label"], "NO_DATA")
            if r not in ("NO_DATA", "超過重試次數") and "錯誤" not in r and "失敗" not in r:
                parts.append(f"【{form['label']}】\n{r}")

        return "\n\n".join(parts) if parts else "查無90天內掛號資料"
