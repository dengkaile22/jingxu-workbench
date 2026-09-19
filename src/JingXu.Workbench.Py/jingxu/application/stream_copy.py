"""无损直拷判定：素材流参数一致且没有任何需转码处理时启用。"""

from __future__ import annotations

from jingxu.domain.render import RenderRequest, TranscodeReason, render_decision

_REASON_MESSAGES: dict[TranscodeReason, str] = {
    TranscodeReason.OVERLAY: "启用的图层需要重新编码。",
    TranscodeReason.EFFECTS: "分屏或差异化滤镜需要重新编码。",
    TranscodeReason.SUBTITLE: "字幕处理（含硬字幕去除）需要重新编码。",
    TranscodeReason.BGM: "背景音乐混音需要重新编码。",
    TranscodeReason.STREAM_MISMATCH: "素材的编码或尺寸参数不一致。",
    TranscodeReason.TRANSITION: "交叉转场需要重新编码。",
    TranscodeReason.MAIN_MATERIAL_BOOST: "主轨音量/缩放调整需要重新编码。",
    TranscodeReason.OUTPUT_RESOLUTION: "导出分辨率需要重新编码。",
    TranscodeReason.OUTPUT_FRAME_RATE: "导出帧率需要重新编码。",
    TranscodeReason.ASPECT_CHANGE: "画幅与首个素材不一致。",
}


def stream_copy_blockers(request: RenderRequest) -> tuple[str, ...]:
    """返回阻止无损直拷的全部原因（空元组表示可以直拷）。

    「质量档」不属于阻止项：是否直拷由用户在界面上选择的无损档决定，
    本函数只回答“在无处理的前提下流结构是否允许直拷”。
    """
    decision = render_decision(request)
    return tuple(
        _REASON_MESSAGES[reason] for reason in decision.reasons if reason is not TranscodeReason.QUALITY_PRESET
    )


def stream_copy_eligible(request: RenderRequest) -> bool:
    """是否存在任何阻止直拷的原因。"""
    return not stream_copy_blockers(request)
