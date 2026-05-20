"""向後相容 shim — 核心邏輯已移至 hospitals/tmuh.py"""

from hospitals.tmuh import TMUH as _TMUH, parse_birth_date  # noqa: F401
from hospitals.tmuh import _parse_response as parse_response  # noqa: F401

_inst = _TMUH()


def tmuh_query_one(session, id_no, birth_year, birth_month, birth_day):
    return _inst.query_one(session, id_no, birth_year, birth_month, birth_day)
