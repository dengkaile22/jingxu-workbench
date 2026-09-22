"""同名输出不得互相覆盖（真实缺陷回归）。

**缺陷**：``unique_output_path`` 只在磁盘上找重名，而同一批次的任务在入队时
**都还没落盘**。于是分别调用 ``build_requests``（顺序拼接 / 随机批量 / 自定义序号）
会各自算出同一个文件名，后渲染的任务把先渲染的**直接覆盖**。

实测：四种配置共 5 条请求，最终目录里只有 3 个 mp4。
这与 README 承诺的「同名文件自动追加三位序号，不静默覆盖」直接矛盾。

修法：``build_requests`` 增加 ``reserved_paths``（别处已占用的路径），
并在本批次内累积已分配路径；``RenderQueue.reserved_output_paths`` 暴露
"尚未结束任务"的输出路径供壳层传入。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from conftest import make_asset  # noqa: E402

from jingxu.application.composition_service import (  # noqa: E402
    CompositionDraft,
    build_requests,
)
from jingxu.domain.composition import OrderMode  # noqa: E402
from jingxu.domain.render import RenderSettings  # noqa: E402
from jingxu.infrastructure.queue import JobState, RenderQueue  # noqa: E402

SETTINGS = RenderSettings(width=270, height=480, fps=25)


def _assets(count: int = 3) -> list:
    """造带序号的素材：自定义序号模式按文件名序号匹配，所以序号必须存在。"""
    return [make_asset(f"clip_{index + 1}.mp4") for index in range(count)]


def _drafts() -> list[CompositionDraft]:
    return [
        CompositionDraft(mode=OrderMode.SEQUENTIAL, settings=SETTINGS),
        CompositionDraft(mode=OrderMode.RANDOM, seed=7, batch_count=2, settings=SETTINGS),
        CompositionDraft(mode=OrderMode.CUSTOM, sequence_text="312", settings=SETTINGS),
    ]


def _names_across_drafts(tmp_path: Path, *, reserve: bool) -> list[str]:
    """模拟壳层连续入队三种配置，返回全部输出文件名。"""
    reserved: list[Path] = []
    names: list[str] = []
    for draft in _drafts():
        built = build_requests(
            assets=_assets(),
            draft=draft,
            output_directory=tmp_path,
            reserved_paths=reserved if reserve else (),
        )
        names.extend(request.output_path.name for request in built)
        if reserve:
            reserved.extend(request.output_path for request in built)
    return names


# ── 回归 ────────────────────────────────────────────────────────────────────


def test_without_reservation_names_collide(tmp_path: Path) -> None:
    """不传 reserved_paths 时会撞名——这正是缺陷本身，留在测试里当反例。

    这条**故意断言缺陷行为**：它说明"只改 build_requests 内部"不够，
    必须由调用方跨批次传递已占用路径。若哪天这个反例不再成立（例如底层改成
    全局注册表），说明实现变了，应当同步更新本测试与调用方。
    """
    names = _names_across_drafts(tmp_path, reserve=False)

    assert len(names) > len(set(names)), "预期会撞名，实际没有——实现可能已改变"


def test_reserved_paths_make_names_unique(tmp_path: Path) -> None:
    """传了 reserved_paths 后，跨三次调用的输出名必须两两不同。"""
    names = _names_across_drafts(tmp_path, reserve=True)

    # 三份草稿共 4 条请求：顺序拼接 1 + 随机批量 2 + 自定义序号 1
    assert len(names) == 4
    assert len(set(names)) == len(names), f"仍有重名：{names}"


def test_reserved_paths_avoid_existing_files(tmp_path: Path) -> None:
    """磁盘上已存在的文件同样要避开（原有行为不能退化）。"""
    (tmp_path / "混剪.mp4").write_bytes(b"x")

    built = build_requests(
        assets=_assets(), draft=_drafts()[0], output_directory=tmp_path
    )

    assert built[0].output_path.name == "混剪_001.mp4"


def test_queue_exposes_pending_output_paths(tmp_path: Path) -> None:
    """队列要能报出「尚未结束任务」的输出路径，供调用方预留。"""
    queue = RenderQueue(Path("ffmpeg"))
    # 不 start()：任务停在排队态，正好是"已入队但还没落盘"的场景
    draft = _drafts()[0]
    built = build_requests(assets=_assets(), draft=draft, output_directory=tmp_path)
    queue.enqueue(built[0])

    assert queue.reserved_output_paths == [built[0].output_path]

    # 结束的任务不再占用（用状态判断，不依赖真实渲染）
    job = queue.jobs[0]
    assert job.state is JobState.QUEUED


def test_queue_reservation_shrinks_after_finish(tmp_path: Path) -> None:
    """任务结束后应从预留集合里消失，避免长期占用导致文件名越滚越大。"""
    queue = RenderQueue(Path("ffmpeg"))
    built = build_requests(assets=_assets(), draft=_drafts()[0], output_directory=tmp_path)
    job = queue.enqueue(built[0])

    # 直接驱动状态机到终态（不跑真实渲染）
    queue.cancel(job.id)

    assert queue.reserved_output_paths == []


def test_shell_passes_queue_reservations() -> None:
    """壳层入队时必须把队列的预留路径传下去（回归：漏传就会覆盖）。"""
    import inspect  # noqa: PLC0415

    from jingxu.ui import shell_window  # noqa: PLC0415

    source = inspect.getsource(shell_window.ShellWindow._enqueue)
    assert "reserved_paths=" in source
    assert "reserved_output_paths" in source


@pytest.mark.parametrize("batch", [1, 3])
def test_single_call_names_are_unique(tmp_path: Path, batch: int) -> None:
    """同一批次内部（批量 1 与 3）也不得重名。"""
    draft = CompositionDraft(mode=OrderMode.RANDOM, seed=1, batch_count=batch, settings=SETTINGS)
    built = build_requests(assets=_assets(), draft=draft, output_directory=tmp_path)
    names = [request.output_path.name for request in built]

    assert len(set(names)) == len(names)
