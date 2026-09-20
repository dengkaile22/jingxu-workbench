"""让爬虫自身的测试可以 ``import core.*``。"""

import sys
from pathlib import Path

SPIDER_ROOT = Path(__file__).resolve().parents[1]
if str(SPIDER_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIDER_ROOT))
