from .tmuh import TMUH
from .wanfang import Wanfang
from .tpech import TPECH
from .mmh import MMH
from .chenghsin import ChengHsin
from .cgmh import CGMH
from .ntuh import NTUH
from .tvgh import TVGH

REGISTRY = {
    "北醫附醫":        TMUH(),
    "萬芳醫院":        Wanfang(),
    "臺北市立聯合醫院":  TPECH(),
    "馬偕醫院（台北）":  MMH(area="tp", branch="台北"),
    "馬偕醫院（淡水）":  MMH(area="ts", branch="淡水"),
    "振興醫院":        ChengHsin(),
    "長庚醫院（台北）":  CGMH(),
    "臺大附醫":        NTUH(),
    "臺北榮總":        TVGH(),
}
