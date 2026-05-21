"""共用 ddddocr 單例，避免每次呼叫重新載入模型（~1-2s）"""

import threading
import ddddocr

_lock = threading.Lock()
_ocr  = None


def classify(image_bytes: bytes) -> str:
    global _ocr
    if _ocr is None:
        with _lock:
            if _ocr is None:
                _ocr = ddddocr.DdddOcr(show_ad=False)
    return _ocr.classification(image_bytes)
