"""临时诊断：更新 build/runtime-manifest.json 中 FFmpeg/FFprobe 的哈希与来源地址。

只动这两个组件：爬虫的 tesseract 条目在 HEAD 里就是空字符串占位符，
属既有状态，不在本次改动范围内。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST = Path("build/runtime-manifest.json")
SOURCE_URL = "https://www.gyan.dev/ffmpeg/builds/"
TARGETS = {"Ffmpeg": "ffmpeg/ffmpeg.exe", "Ffprobe": "ffmpeg/ffprobe.exe"}

manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
changed = []
for component in manifest["components"]:
    kind = component["kind"]
    if kind not in TARGETS:
        continue
    path = Path("runtime") / TARGETS[kind]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if component["sha256"] != digest:
        changed.append((kind, component["sha256"][:12], digest[:12]))
        component["sha256"] = digest
    component["sourceUrl"] = SOURCE_URL

MANIFEST.write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

for kind, old, new in changed:
    print(f"{kind}: {old}… -> {new}…")
if not changed:
    print("无需改动（哈希已一致）")
print("sourceUrl ->", SOURCE_URL)
