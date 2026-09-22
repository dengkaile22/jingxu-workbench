"""一次性同步脚本：把爬虫项目的 profile_lock.py 复制为工作台副本。

唯一真源：src/JingXu.Spider/core/profile_lock.py
副本：    src/JingXu.Workbench.Py/jingxu/infrastructure/profile_lock.py（仅替换模块 docstring）

用法：python tools/sync_profile_lock.py
"""

from __future__ import annotations

from pathlib import Path

SOURCE = Path("src/JingXu.Spider/core/profile_lock.py")
TARGET = Path("src/JingXu.Workbench.Py/jingxu/infrastructure/profile_lock.py")
MARKER = "from __future__ import annotations"

HEADER = (
    '"""浏览器档案占用检测（``src/JingXu.Spider/core/profile_lock.py`` 的逐字副本）。\n'
    "\n"
    "**请勿直接修改本文件**：唯一真源在爬虫项目的 ``core/profile_lock.py``——爬虫与\n"
    "工作台必须对同一件事给出同一答案。改完真源后运行 ``python tools/sync_profile_lock.py``\n"
    "重新同步；工作台测试 ``tests/test_spider_profile_lock_parity.py`` 断言两份文件正文\n"
    "逐字节相同。\n"
    "\n"
    '"""\n\n'
)


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    body = text[text.index(MARKER) :]
    TARGET.write_text(HEADER + body, encoding="utf-8", newline="\n")
    print(f"synced -> {TARGET} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
