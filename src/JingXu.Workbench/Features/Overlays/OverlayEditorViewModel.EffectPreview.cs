using System.IO;
using System.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Projects;

namespace JingXu.Workbench.Features.Overlays;

public sealed partial class OverlayEditorViewModel
{
    private TempResourceLease? _previewResource;
    private readonly string _previewSessionId = Guid.NewGuid().ToString("N");

    partial void OnEffectPreviewImagePathChanged(string? value)
    {
        var previous = _previewResource;
        _previewResource = string.IsNullOrWhiteSpace(value) ? null : TempResourceLease.Acquire(value);
        previous?.Dispose();
    }

    public const string EffectPreviewBaseVideoDialogTitle = "选择用于叠层静帧预览的主片";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RefreshEffectPreviewFromBaseVideoCommand))]
    private string? _effectPreviewBaseVideoPath;

    /// <summary>蓝框内的渐变止点，仅用于快速交互示意；右侧合成静帧使用实际渲染滤镜。</summary>
    public double PreviewTopFadeSolidStopOffset => Math.Clamp(1 - TopFade, 0, 1);

    /// <summary>蓝框内的羽化强度，仅用于快速交互示意；右侧合成静帧使用实际渲染滤镜。</summary>
    public double PreviewFeatherBlurRadius => Math.Round(Math.Clamp(Feather, 0, 1) * 12, 2);

    public string PreviewVisualEffectHint =>
        $"蓝框示意：上向渐变 {TopFade:P0}，羽化 {Feather:P0}；右侧合成静帧显示真实渲染效果。";

    public bool HasEffectPreviewBaseVideo =>
        !string.IsNullOrWhiteSpace(EffectPreviewBaseVideoPath) && File.Exists(EffectPreviewBaseVideoPath);

    public string EffectPreviewBaseVideoName => HasEffectPreviewBaseVideo
        ? Path.GetFileName(EffectPreviewBaseVideoPath) ?? "未选择"
        : "未选择";

    partial void OnEffectPreviewBaseVideoPathChanged(string? value)
    {
        OnPropertyChanged(nameof(HasEffectPreviewBaseVideo));
        OnPropertyChanged(nameof(EffectPreviewBaseVideoName));
        InvalidateEffectPreview(
            string.IsNullOrWhiteSpace(value)
                ? null
                : "已选择预览主片，点击“刷新合成预览”生成真实叠层静帧。");
    }

    private void NotifyPreviewVisualEffectChanged()
    {
        OnPropertyChanged(nameof(PreviewTopFadeSolidStopOffset));
        OnPropertyChanged(nameof(PreviewFeatherBlurRadius));
        OnPropertyChanged(nameof(PreviewVisualEffectHint));
    }

    private bool CanRefreshEffectPreviewFromBaseVideo() =>
        Selected is not null && HasEffectPreviewBaseVideo && _frameExtractor is not null;

    [RelayCommand]
    private void ChooseEffectPreviewBaseVideo()
    {
        try
        {
            var paths = _uiDispatcher.Invoke(() => _filePicker.PickVideoFiles(EffectPreviewBaseVideoDialogTitle));
            var path = paths?.FirstOrDefault(File.Exists);
            if (path is null)
            {
                return;
            }

            EffectPreviewBaseVideoPath = path;
            StatusMessage = $"已选择预览主片「{Path.GetFileName(path)}」，可刷新合成预览。";
        }
        catch (Exception ex)
        {
            StatusMessage = $"选择预览主片失败：{ToChineseOverlayError(ex)}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanRefreshEffectPreviewFromBaseVideo))]
    private async Task RefreshEffectPreviewFromBaseVideoAsync() =>
        await RefreshEffectPreviewAsync().ConfigureAwait(true);

    private void InvalidateEffectPreview(string? reason = null)
    {
        Interlocked.Increment(ref _previewGeneration);
        var previous = EffectPreviewImagePath;
        EffectPreviewImagePath = null;
        EffectPreviewHint = HasEffectPreviewBaseVideo
            ? reason ?? "当前蒙版参数已变更，点击“刷新合成预览”查看真实渐变、羽化和叠层效果。"
            : "请选择预览主片后，再刷新真实叠层静帧；这里不会用蒙版缩略图冒充合成预览。";
        OnPropertyChanged(nameof(HasEffectPreviewImage));
        TryDeleteOwnedOverlayPreview(previous);
    }

    /// <summary>只删 %TEMP%\JingXu\overlay-preview\mask-composite-*.jpg，不删用户素材或蒙版库缩略图。</summary>
    private static void TryDeleteOwnedOverlayPreview(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        try
        {
            var previewDirectory = Path.GetFullPath(Path.Combine(JingXu.Workbench.Application.Projects.WorkbenchDataPaths.GetTempDirectory(), "JingXu", "overlay-preview"))
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                + Path.DirectorySeparatorChar;
            var fullPath = Path.GetFullPath(path);
            if (!fullPath.StartsWith(previewDirectory, StringComparison.OrdinalIgnoreCase)
                || !Path.GetFileName(fullPath).StartsWith("mask-composite-", StringComparison.OrdinalIgnoreCase)
                || !string.Equals(Path.GetExtension(fullPath), ".jpg", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (File.Exists(fullPath))
            {
                File.Delete(fullPath);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
        {
        }
    }
}
