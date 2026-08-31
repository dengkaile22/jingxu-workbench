using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Bootstrap;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Features.Shell;
using JingXu.Workbench.Infrastructure.Persistence;

namespace JingXu.Workbench.Features.AudioLibrary;

/// <summary>音频库管理模块视图模型。</summary>
public sealed partial class AudioLibraryViewModel : WorkspaceModuleViewModel
{
    private readonly AudioLibraryService _libraryService;
    private readonly IMediaProbe _mediaProbe;
    private readonly IMediaFilePicker _filePicker;
    private readonly IUiDispatcher _uiDispatcher;
    private readonly IAudioLibraryClearConfirmation _clearConfirmation;

    public AudioLibraryViewModel(
        AudioLibraryService libraryService,
        IMediaProbe mediaProbe,
        IMediaFilePicker filePicker,
        IUiDispatcher uiDispatcher,
        IAudioLibraryClearConfirmation? clearConfirmation = null)
    {
        _libraryService = libraryService ?? throw new ArgumentNullException(nameof(libraryService));
        _mediaProbe = mediaProbe ?? throw new ArgumentNullException(nameof(mediaProbe));
        _filePicker = filePicker ?? throw new ArgumentNullException(nameof(filePicker));
        _uiDispatcher = uiDispatcher ?? throw new ArgumentNullException(nameof(uiDispatcher));
        _clearConfirmation = clearConfirmation ?? new WpfAudioLibraryClearConfirmation();
    }

    public override WorkspaceModule ModuleKind => WorkspaceModule.AudioLibrary;

    public override string Title => "音频库";

    public ObservableCollection<AudioLibraryEntryRowViewModel> LibraryEntries { get; } = [];

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    private bool _hasStatusMessage;

    [ObservableProperty]
    private bool _isImporting;

    [ObservableProperty]
    private int _entryCount;

    public bool HasEntries => EntryCount > 0;

    partial void OnStatusMessageChanged(string value) => HasStatusMessage = !string.IsNullOrWhiteSpace(value);

    partial void OnEntryCountChanged(int value) => OnPropertyChanged(nameof(HasEntries));

    /// <summary>初始加载（由壳层导航触发或首次构造时调用）。</summary>
    public async Task LoadAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var document = await _libraryService.LoadAsync(cancellationToken: cancellationToken)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() => ApplyLibraryDocument(document));
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() => StatusMessage = $"加载音频库失败：{ex.GetBaseException().Message}");
        }
    }

    [RelayCommand]
    private async Task ImportAudioFilesAsync()
    {
        if (IsImporting)
        {
            return;
        }

        _uiDispatcher.Invoke(() => IsImporting = true);

        var paths = _filePicker.PickAudioFiles("选择音频文件（MP3/WAV/M4A/AAC/FLAC/OGG）");
        if (paths is null || paths.Count == 0)
        {
            _uiDispatcher.Invoke(() => IsImporting = false);
            return;
        }

        _uiDispatcher.Invoke(() => StatusMessage = $"已选择 {paths.Count} 个文件，正在探测…");

        try
        {
            var successCount = 0;
            var failCount = 0;
            string? lastError = null;

            foreach (var rawPath in paths)
            {
                if (string.IsNullOrWhiteSpace(rawPath))
                {
                    failCount++;
                    continue;
                }

                var path = rawPath;
                if (!File.Exists(path))
                {
                    failCount++;
                    lastError = $"文件不存在：{path}";
                    continue;
                }

                _uiDispatcher.Invoke(() => StatusMessage = $"正在探测音频…（{Path.GetFileName(path)}）");

                try
                {
                    var info = await _mediaProbe.ProbeAsync(path, CancellationToken.None)
                        .ConfigureAwait(false);
                    if (info.Duration <= TimeSpan.Zero)
                    {
                        failCount++;
                        lastError = $"音频时长无效：{Path.GetFileName(path)}";
                        continue;
                    }

                    await _libraryService.RegisterAsync(
                        path,
                        info.Duration,
                        cancellationToken: CancellationToken.None)
                        .ConfigureAwait(false);

                    successCount++;
                }
                catch (MediaProbeException ex)
                {
                    failCount++;
                    lastError = $"探测失败：{ex.Message}";
                }
                catch (Exception ex)
                {
                    failCount++;
                    lastError = $"导入失败：{ex.GetBaseException().Message}";
                }
            }

            await LoadAsync(CancellationToken.None).ConfigureAwait(false);

            _uiDispatcher.Invoke(() =>
            {
                if (failCount == 0)
                {
                    StatusMessage = successCount == 1
                        ? "已导入 1 个音频文件。"
                        : $"已导入 {successCount} 个音频文件。";
                }
                else
                {
                    StatusMessage = successCount == 0
                        ? lastError ?? "导入失败。"
                        : $"已导入 {successCount} 个，失败 {failCount} 个。";
                }
            });
        }
        finally
        {
            _uiDispatcher.Invoke(() => IsImporting = false);
        }
    }

    [RelayCommand]
    private async Task RemoveEntryAsync(AudioLibraryEntryRowViewModel? entry)
    {
        if (entry is null)
        {
            StatusMessage = "请选择要从音频库移除的音频。";
            return;
        }

        try
        {
            await _libraryService.RemoveAsync(entry.Id, CancellationToken.None).ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                LibraryEntries.Remove(entry);
                EntryCount = LibraryEntries.Count;
                StatusMessage = $"已从音频库移除「{entry.DisplayName}」（不会删除原文件）。";
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
                StatusMessage = $"移除音频失败：{ex.GetBaseException().Message}");
        }
    }

    [RelayCommand]
    private async Task ClearAllAsync()
    {
        var count = EntryCount;
        if (count == 0)
        {
            return;
        }

        if (!_clearConfirmation.ConfirmClear(count))
        {
            StatusMessage = "已取消清空音频库。";
            return;
        }

        try
        {
            var (document, removed) = await _libraryService.ClearAllAsync(CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyLibraryDocument(document);
                StatusMessage = removed == 0
                    ? "音频库已为空。"
                    : $"已清空音频库（{removed} 条）；电脑中的原文件未删除。";
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
                StatusMessage = $"清空音频库失败：{ex.GetBaseException().Message}");
        }
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        await LoadAsync(CancellationToken.None).ConfigureAwait(false);
        StatusMessage = "已刷新音频库。";
    }

    private void ApplyLibraryDocument(AudioLibraryDocument document)
    {
        LibraryEntries.Clear();
        foreach (var entry in document.Entries
                     .OrderByDescending(e => e.LastUsedAt ?? DateTimeOffset.MinValue)
                     .ThenBy(e => e.FilePath, StringComparer.OrdinalIgnoreCase))
        {
            LibraryEntries.Add(new AudioLibraryEntryRowViewModel(entry));
        }

        EntryCount = LibraryEntries.Count;
    }
}

/// <summary>音频库条目行视图模型。</summary>
public sealed class AudioLibraryEntryRowViewModel
{
    private readonly AudioLibraryEntry _entry;

    public AudioLibraryEntryRowViewModel(AudioLibraryEntry entry)
    {
        _entry = entry;
    }

    public Guid Id => _entry.Id;

    public string FilePath => _entry.FilePath;

    public string FileName => _entry.FileName;

    public string DisplayName => _entry.DisplayName ?? Path.GetFileNameWithoutExtension(_entry.FilePath);

    public TimeSpan Duration => _entry.Duration;

    public string DurationText => Duration.TotalHours >= 1
        ? $"{(int)Duration.TotalHours}:{Duration.Minutes:D2}:{Duration.Seconds:D2}"
        : $"{Duration.Minutes:D2}:{Duration.Seconds:D2}";

    public string LastUsedText => _entry.LastUsedAt is null
        ? "尚未使用"
        : _entry.LastUsedAt.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);

    public bool FileExists => File.Exists(_entry.FilePath);

    public string StatusLabel => FileExists ? "可用" : "缺失";
}
