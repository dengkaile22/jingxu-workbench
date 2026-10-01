"""让爬虫自身的测试可以 ``import core.*``。"""

import importlib.util
import sys
from pathlib import Path

SPIDER_ROOT = Path(__file__).resolve().parents[2] / "extensions" / "spider"
if str(SPIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIDER_ROOT))

# 暴露外层 tests/conftest.py 中的共用辅助，防止 pytest 遍历子目录时同名 conftest 模块互相覆盖
_parent_conftest = Path(__file__).resolve().parents[1] / "conftest.py"
if _parent_conftest.is_file():
    _spec = importlib.util.spec_from_file_location("_parent_conftest", _parent_conftest)
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        make_asset = getattr(_mod, "make_asset", None)
        wait_until = getattr(_mod, "wait_until", None)
