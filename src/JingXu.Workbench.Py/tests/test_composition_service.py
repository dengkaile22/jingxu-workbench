"""编排服务测试：批量差异化、命名与裁剪规则。"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_asset

from jingxu.application.composition_service import CompositionDraft, build_requests
from jingxu.domain.composition import OrderMode


def _assets(count: int = 4) -> list:
    return [make_asset(f"素材{i}.mp4", duration=1.0 + i * 0.1) for i in range(1, count + 1)]


def test_single_request_uses_prefix_without_suffix(tmp_path: Path) -> None:
    requests = build_requests(
        assets=_assets(3),
        draft=CompositionDraft(mode=OrderMode.SEQUENTIAL, output_prefix="混剪"),
        output_directory=tmp_path,
    )

    assert len(requests) == 1
    assert requests[0].output_path.name == "混剪.mp4"
    assert requests[0].name == "混剪 #1"


def test_batch_requests_are_numbered_and_differentiated(tmp_path: Path) -> None:
    requests = build_requests(
        assets=_assets(4),
        draft=CompositionDraft(
            mode=OrderMode.RANDOM,
            seed=100,
            batch_count=3,
            output_prefix="分镜",
        ),
        output_directory=tmp_path,
        start_index=5,
    )

    assert [request.output_path.name for request in requests] == [
        "分镜_001.mp4",
        "分镜_002.mp4",
        "分镜_003.mp4",
    ]
    assert [request.name for request in requests] == ["分镜 #5", "分镜 #6", "分镜 #7"]
    assert [request.plan.seed for request in requests] == [100, 101, 102]

    orders = [tuple(asset.display_name for asset in request.plan.assets) for request in requests]
    assert len(set(orders)) > 1


def test_batch_count_is_ignored_for_custom_sequence(tmp_path: Path) -> None:
    requests = build_requests(
        assets=_assets(3),
        draft=CompositionDraft(mode=OrderMode.CUSTOM, sequence_text="312", batch_count=5),
        output_directory=tmp_path,
    )

    assert len(requests) == 1
    assert [asset.display_name for asset in requests[0].plan.assets] == [
        "素材3.mp4",
        "素材1.mp4",
        "素材2.mp4",
    ]


def test_clips_per_plan_limits_random_batch(tmp_path: Path) -> None:
    requests = build_requests(
        assets=_assets(5),
        draft=CompositionDraft(
            mode=OrderMode.RANDOM,
            seed=7,
            batch_count=2,
            clips_per_plan=3,
        ),
        output_directory=tmp_path,
    )

    for request in requests:
        assert len(request.plan.assets) == 3


def test_existing_output_gets_incremental_suffix(tmp_path: Path) -> None:
    (tmp_path / "混剪.mp4").write_text("exists", encoding="utf-8")

    requests = build_requests(
        assets=_assets(2),
        draft=CompositionDraft(mode=OrderMode.SEQUENTIAL, output_prefix="混剪"),
        output_directory=tmp_path,
    )

    assert requests[0].output_path.name == "混剪_001.mp4"


def test_repeated_sequence_indices_are_allowed(tmp_path: Path) -> None:
    requests = build_requests(
        assets=_assets(3),
        draft=CompositionDraft(mode=OrderMode.CUSTOM, sequence_text="112"),
        output_directory=tmp_path,
    )

    assert [asset.display_name for asset in requests[0].plan.assets] == [
        "素材1.mp4",
        "素材1.mp4",
        "素材2.mp4",
    ]


def test_unknown_sequence_index_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不存在"):
        build_requests(
            assets=_assets(3),
            draft=CompositionDraft(mode=OrderMode.CUSTOM, sequence_text="19"),
            output_directory=tmp_path,
        )


def test_empty_assets_raise(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="没有可编排的素材"):
        build_requests(
            assets=[],
            draft=CompositionDraft(),
            output_directory=tmp_path,
        )
