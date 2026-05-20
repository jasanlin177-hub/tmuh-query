from abc import ABC, abstractmethod
import requests


class HospitalBase(ABC):
    display_name: str
    needs_birth: bool

    @abstractmethod
    def make_session(self) -> requests.Session: ...

    @abstractmethod
    def query_one(self, session: requests.Session, id_no: str,
                  birth_year: str = "", birth_month: str = "", birth_day: str = "") -> str: ...
