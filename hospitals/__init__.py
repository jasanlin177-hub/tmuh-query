from .tmuh import TMUH
from .wanfang import Wanfang
from .tpech import TPECH

REGISTRY = {
    "北醫附醫":      TMUH(),
    "萬芳醫院":      Wanfang(),
    "臺北市立聯合醫院": TPECH(),
}
