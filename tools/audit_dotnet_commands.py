"""把 .NET 的每个绑定命令与 Python 的对应实现做两向核对。

用途：以后新增/修改页面后，一条命令就能看出「.NET 有而 Python 没有」的项，
不必靠手工回忆。

方法（**吸取过一次教训**）：上一轮我用英文标识符搜 Python，结果漏掉了
用中文按钮文案实现的功能，误报成"缺失"。所以这里：

* 每条命令给一组**语义**关键词（中文按钮文案 + 英文函数名片段），任一命中即判"有"；
* 对"确实没有独立控件"的命令，用 ``FOLDED`` 显式登记**它被折进了哪个功能**，
  而不是默默算作缺失——否则每次跑都会重复误报。

输出分三类：已实现 / 已折入其它功能 / 真缺失。
"""

from __future__ import annotations

from pathlib import Path

PY_ROOT = Path("core/jingxu")
SOURCES = {
    path: path.read_text(encoding="utf-8", errors="replace")
    for path in PY_ROOT.rglob("*.py")
}

# 命令 -> 语义关键词（任一命中即认为存在）
COMMANDS: dict[str, tuple[str, ...]] = {
    "AddAccountCommand": ("加入账号", "+ 添加账号", "def _add_account"),
    "AddCueCommand": ("添加一行", "def _add_cue"),
    "ApplyCurrentVisualSettingsToAllLayersCommand": ("统一应用到全部层", "def _apply_visual_settings_to_all"),
    "ApplyFitPresetCommand": ("拟合方式", "适配", "fit_mode", "_fit"),
    "ApplyManualRegionAsDetectedCommand": ("手动区域", "def _confirm_manual_region", "apply_manual"),
    "ApplyMaskAspectPresetCommand": ("蒙版宽高比", "fixed_ratio", "画幅比例"),
    "ApplyRenderConcurrencyCommand": ("同时渲染任务数", "max_concurrency", "set_max_concurrency"),
    "ApplySelectedSequenceTemplateCommand": ("序列模板", "def _apply_sequence"),
    "ApplySelectedTemplateCommand": ("应用到当前", "def _apply_template"),
    "ApplyStartClipIndexToAllLayersCommand": ("统一起始片段", "def _apply_start_clip_to_all"),
    "ApplyUnifiedSizeToAllCommand": ("统一尺寸到全部层", "def _apply_unified_size"),
    "BrowseSaveDirectoryCommand": ("保存目录", "def _browse"),
    "CancelAllCommand": ("取消全部", "def _cancel_all"),
    "CancelCrawlCommand": ("取消抓取", "def _cancel_crawl"),
    "CheckEnvironmentCommand": ("重新检测", "def _refresh_environment", "check_environment"),
    "ClearAllCommand": ("全部清理", "def _clear_all"),
    "ClearBgmCommand": ("清除背景音乐", "清空背景音乐", "def _clear_bgm", "清除"),
    "ClearFinishedCommand": ("清理已完成", "clear_finished"),
    "ClearLibraryEntriesCommand": ("清空库", "def _clear_library"),
    "ClearListCommand": ("清空列表", "def _clear_all"),
    "ClearLogCommand": ("清空日志", "def _clear_log"),
    "ClearMaterialsCommand": ("清理素材", "def _clear_materials"),
    "ClearStickerLibraryCommand": ("清空素材库", "def _clear_library"),
    "ClearWorkbenchCacheCommand": ("cleanup_workspace", "清理临时文件"),
    "ConfirmAllSegmentsCommand": ("确认全部区域", "def confirm_all_segments"),
    "DeleteSelectedEffectTemplateCommand": ("删除", "def _delete_template"),
    "DeleteSelectedSequenceTemplateCommand": ("删除", "def _delete_sequence"),
    "DetectRegionsCommand": ("OCR 检测硬字幕", "def start_ocr_detection"),
    "DownloadCommand": ("开始下载", "def _start_downloads"),
    "EnqueueCommand": ("加入队列", "def _enqueue"),
    "ExportSrtCommand": ("导出 SRT", "def _export_srt"),
    "ImportAccountsCommand": ("批量导入", "def _import_accounts"),
    "ImportAudioFilesCommand": ("导入音频", "def _import_audio"),
    "ImportMaskMaterialsCommand": ("导入蒙版素材", "def _import_to_library"),
    "ImportStickersCommand": ("导入贴纸", "def _import_to_library"),
    "ImportSubtitleCommand": ("导入 SRT", "def _import_srt"),
    "LoadSequenceTemplatesCommand": ("序列模板", "def _apply_sequence_template"),
    "LoginDouyinCommand": ("扫码登录抖音", "抖音"),
    "LoginKuaishouCommand": ("扫码登录快手", "快手"),
    "OpenDataDirectoryCommand": ("打开数据目录", "def _open_data_directory"),
    "OpenReportCommand": ("打开报表", "def _open_exports_directory"),
    "OpenSelectedProductLinkCommand": ("打开链接", "def _open_result_link"),
    "OpenSelectedSampleVideoCommand": ("打开链接", "def _open_result_link"),
    "OpenSelectedVideoCommand": ("打开链接", "def _open_result_link"),
    "PauseOrResumeCommand": ("暂停调度", "pause", "resume"),
    "PickBgmFileCommand": ("选择…", "def _pick_bgm"),
    "PickImportFilesCommand": ("导入素材", "def _import"),
    "PickOutputDirectoryCommand": ("浏览…", "def _browse_output"),
    "PickVideoCommand": ("导入视频…", "def _import_video"),
    "PruneMissingLibraryEntriesCommand": ("清理失效", "def _prune_library"),
    "RefreshCommand": ("刷新", "def refresh"),
    "RefreshDiagnosticsCommand": ("重新检测", "def _start_probe"),
    "RefreshEffectPreviewFromBaseVideoCommand": ("刷新效果预览", "def _start_overlay_effect_preview"),
    "RemoveSelectedCommand": ("移除选中", "def _remove_selected"),
    "RenameSelectedEffectTemplateCommand": ("重命名", "def _rename_template"),
    "RenameSelectedSequenceTemplateCommand": ("重命名", "def _rename_sequence"),
    "RenderCommand": ("烧录字幕并入队", "加入队列", "def _enqueue"),
    "ResetSourceCropBoundsCommand": ("重置为自动取景", "def _reset_source_crop"),
    "SaveCurrentSequenceTemplateCommand": ("保存为序列模板", "def _save_sequence_template"),
    "SaveEffectTemplateCommand": ("保存为模板", "def _save_template"),
    "SendAllVideosToDownloadsCommand": ("结果送入下载", "def _send_selected"),
    "SendSelectedVideosToDownloadsCommand": ("结果送入下载", "def _send_selected"),
    "StartCrawlCommand": ("开始抓取", "def _start_crawl"),
    "SwitchWorkspaceCommand": ("_select_module", "切换工作区", "MODULE_"),
    "TranscribeCommand": ("识别当前选中素材", "def start_transcription"),
}

# 没有独立控件、但能力已被**折入**其它功能的命令。
# 值写明折到哪儿，便于人工复核这条判断是否仍然成立。
FOLDED: dict[str, str] = {
    "ApplyBoundsCommand": "Python 表单/画布即时生效，不需要单独的「应用参数」按钮",
    "ParseUrlsCommand": "折入「开始下载」：解析链接与入队是同一次动作",
    "LoadConfigCommand": "配置自动持久化，无需手动「加载配置」",
    "SaveConfigCommand": "配置自动持久化，无需手动「保存配置」",
    "ChooseEffectPreviewBaseVideoCommand": "效果预览直接用商品组首段素材，无需选预览主片",
}

hits: dict[str, list[str]] = {}
missing: list[str] = []

for command, keywords in sorted(COMMANDS.items()):
    found: list[str] = []
    for path, text in SOURCES.items():
        for keyword in keywords:
            if keyword in text:
                found.append(f"{path.name}:{keyword}")
                break
        if found:
            break
    if found:
        hits[command] = found
    elif command in FOLDED:
        continue
    else:
        missing.append(command)

print(f"已实现：{len(hits)}")
print(f"已折入其它功能：{len(FOLDED)}")
for command, reason in sorted(FOLDED.items()):
    print(f"  {command:<46} {reason}")
print()
print(f"真缺失：{len(missing)}")
for command in missing:
    print(f"  {command}   关键词={COMMANDS[command]}")

