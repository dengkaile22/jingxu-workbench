"""生成宣传片用的演示素材：商品短视频 + 蒙版视频。

要点：FFmpeg 滤镜里的 Windows 盘符冒号需要特殊转义，极易踩坑。
本脚本把字体复制到工作目录并统一使用「相对路径 + ASCII 文件名」，
把转义问题降到零。所有产物写入 scratchpad/promo/demo/。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

FFMPEG = Path(__file__).resolve().parents[2] / "runtime" / "ffmpeg" / "ffmpeg.exe"
WIN_FONTS = Path(r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
DEMO = ROOT / "demo"
PRODUCTS = DEMO / "products"
MASKS = DEMO / "masks"
TMP = ROOT / "tmp"

FONT_BD = "assets/fonts/msyhbd.ttc"
FONT_RG = "assets/fonts/msyh.ttc"


def ensure_fonts() -> None:
    FONTS.mkdir(parents=True, exist_ok=True)
    for name in ("msyhbd.ttc", "msyh.ttc"):
        target = FONTS / name
        if not target.exists():
            shutil.copy2(WIN_FONTS / name, target)


def run(args: list[str]) -> None:
    result = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {' '.join(args)}\n{result.stderr}")


def write_text_file(name: str, text: str) -> str:
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / name
    path.write_text(text, encoding="utf-8")
    return f"tmp/{name}"


PRODUCT_SPECS = [
    # (文件名, 主标题, 副标题, 价格, c0, c1, 时长)
    ("商品素材_01口红", "口红 · 正红色号", "丝绒雾面 · 显白不拔干", "¥69", "0xE84A6F", "0xFFB199", 6),
    ("商品素材_02面霜", "保湿面霜 · 50g", "熬夜急救 · 24h锁水", "¥129", "0x4A6FE8", "0x8FD0FF", 7),
    ("商品素材_03耳机", "蓝牙耳机 · 主动降噪", "40dB降噪 · 续航36h", "¥199", "0x5B3FD4", "0xE88FD0", 6),
    ("商品素材_04空气炸锅", "空气炸锅 · 5L大容量", "可视窗口 · 一键定时", "¥299", "0x1F9E6E", "0xD9F26B", 8),
    ("商品素材_05洗衣凝珠", "洗衣凝珠 · 四合一", "深层去渍 · 留香72h", "¥39.9", "0xE86F3A", "0xFFD9A0", 5),
    ("商品素材_06保温杯", "保温杯 · 316不锈钢", "12h保温 · 单手开盖", "¥89", "0x2B6FD4", "0x6BE3E0", 7),
]


def make_product(index: int, name: str, title: str, subtitle: str, price: str, c0: str, c1: str, dur: int) -> None:
    tag = f"p{index:02d}"
    title_file = write_text_file(f"{tag}_title.txt", title)
    sub_file = write_text_file(f"{tag}_sub.txt", subtitle)
    price_file = write_text_file(f"{tag}_price.txt", price)
    out = f"demo/products/{name}.mp4"
    filters = (
        f"drawtext=fontfile={FONT_BD}:textfile={title_file}:"
        f"fontcolor=white:fontsize=64:"
        f"x=(w-text_w)/2:y=h*0.30,"
        f"drawtext=fontfile={FONT_RG}:textfile={sub_file}:"
        f"fontcolor=white@0.85:fontsize=32:"
        f"x=(w-text_w)/2:y=h*0.30+110,"
        f"drawbox=x=(iw-320)/2:y=ih*0.52:w=320:h=140:color=white@0.18:t=fill,"
        f"drawtext=fontfile={FONT_BD}:textfile={price_file}:"
        f"fontcolor=white:fontsize=88:"
        f"x=(w-text_w)/2:y=h*0.52+22"
    )
    run(
        [
            "-f", "lavfi",
            "-i", f"gradients=s=720x1280:d={dur}:c0={c0}:c1={c1}:x0=0:y0=0:x1=720:y1=1280:speed=0.04:type=linear",
            "-vf", filters,
            "-t", str(dur),
            "-r", "25",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            out,
        ]
    )
    print("OK", name)


def make_mask_video(name: str, shape_png: Path, dur: int = 4) -> None:
    """黑底白形状蒙版视频：由 Qt 生成的白色形状 PNG 叠在黑底上。"""
    out = f"demo/masks/{name}.mp4"
    run(
        [
            "-f", "lavfi",
            "-i", f"color=c=black:s=720x1280:d={dur}:r=25",
            "-i", f"demo/masks/{shape_png.name}",
            "-filter_complex", "[0:v][1:v]overlay=(W-w)/2:(H-h)/2[v];[v]format=yuv420p",
            "-t", str(dur),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-movflags", "+faststart",
            out,
        ]
    )
    print("OK", name)


def main() -> int:
    ensure_fonts()
    for directory in (PRODUCTS, MASKS, TMP):
        directory.mkdir(parents=True, exist_ok=True)
    for index, spec in enumerate(PRODUCT_SPECS, start=1):
        make_product(index, *spec)
    for mask_name, png_name in (
        ("蒙版_圆形聚焦", "shape_circle.png"),
        ("蒙版_圆角竖条", "shape_roundrect.png"),
    ):
        make_mask_video(mask_name, MASKS / png_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
