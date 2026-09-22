"""临时诊断：核对 build/runtime-manifest.json 里能就地校验的组件哈希。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST = Path("build/runtime-manifest.json")
manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

all_ok = True
for component in manifest["components"]:
    target = Path("runtime") / component["relativePath"]
    if not target.is_file():
        print(f"  {component['kind']:<14} 源文件不在仓库（构建时放入）：{component['relativePath']}")
        continue
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    same = actual == component["sha256"]
    all_ok = all_ok and same
    print(f"  {component['kind']:<14} {'一致' if same else '不一致!'}  {component['relativePath']}")

print()
print("ffmpeg sourceUrl:", manifest["components"][0]["sourceUrl"])
print("全部一致:", all_ok)
