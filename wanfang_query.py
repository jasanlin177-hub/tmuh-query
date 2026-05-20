"""向後相容 shim — 核心邏輯已移至 hospitals/wanfang.py"""

from hospitals.wanfang import Wanfang as _Wanfang, _HEADERS as HEADERS  # noqa: F401

_inst = _Wanfang()
BASE_URL = "https://wwww.wanfang.gov.tw/reg/register_cancel_cload.aspx"


def query_one(session, id_no="", alien_no="", chr_no="", max_retry=5):
    return _inst.query_one(session, id_no=id_no)
