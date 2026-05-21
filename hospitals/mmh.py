"""台北馬偕紀念醫院 掛號查詢（無驗證碼）"""

import re
import requests
import urllib3
from bs4 import BeautifulSoup

from .base import HospitalBase

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_QUERY_URL = "https://www.mmh.org.tw/check_registerdone.php"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.mmh.org.tw/check_register.php",
    "Origin":  "https://www.mmh.org.tw",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _birth_to_mmh(birth_year: str, birth_month: str, birth_day: str) -> str:
    """'074','06','23' → '740623'（民國年去前導零，月日各2碼）"""
    y = str(int(birth_year))   # 074 → 74
    m = birth_month.zfill(2)
    d = birth_day.zfill(2)
    return f"{y}{m}{d}"


def _parse_response(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # 結果都在 section.register_act 區塊內
    section = soup.find("section", class_="register_act")
    scope   = section if section else soup

    # 無掛號
    if any(k in scope.get_text() for k in ["查無掛號", "查無資料", "無預約", "查不到"]):
        return "查無90天內掛號資料"

    # 有掛號：解析 table
    for table in scope.find_all("table"):
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

    return "查詢完成，但無法自動解析結果（醫院版面可能已更新）"


class MMH(HospitalBase):
    needs_birth = True

    def __init__(self, area: str = "tp", branch: str = "台北"):
        self.area         = area
        self.display_name = f"馬偕醫院（{branch}）"

    def make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(_HEADERS)
        return s

    def query_one(self, session, id_no, birth_year="", birth_month="", birth_day=""):
        birth = _birth_to_mmh(birth_year, birth_month, birth_day)
        payload = {
            "workflag":   "checkreg",
            "area":       self.area,
            "txtID":      id_no,
            "txtBirth":   birth,
            "txtwebword": "",
        }
        try:
            resp = session.post(_QUERY_URL, data=payload, timeout=15, verify=False)
            resp.raise_for_status()
        except requests.RequestException as e:
            return f"網路錯誤：{e}"

        return _parse_response(resp.text)
