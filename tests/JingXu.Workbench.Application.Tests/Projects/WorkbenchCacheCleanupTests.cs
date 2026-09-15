using JingXu.Workbench.Application.Projects;

namespace JingXu.Workbench.Application.Tests.Projects;

public sealed class WorkbenchCacheCleanupTests
{
    [Fact]
    public void Startup_cleanup_keeps_a_cached_thumbnail_even_with_an_inactive_registration()
    {
        using var scope = new CleanupScope();
        var thumbnail = Path.Combine(scope.DataRoot, "overlay-thumbs", "cached.jpg");
        Directory.CreateDirectory(Path.GetDirectoryName(thumbnail)!);
        File.WriteAllText(thumbnail, "ready-thumbnail");
        using (TempResourceLease.Acquire(thumbnail, dataDirectory: scope.DataRoot)) { }

        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);

        Assert.True(File.Exists(thumbnail), "启动清理必须保留可复用缩略图，即使生成租约已经释放。");
        WorkbenchCacheCleanup.Cleanup(scope.DataRoot, scope.TempRoot, includeOverlayThumbCache: true);
        Assert.False(File.Exists(thumbnail));
    }

    [Fact]
    public void Cleanup_keeps_the_parent_of_a_registered_file_before_it_is_created()
    {
        using var scope = new CleanupScope();
        var folder = Path.Combine(scope.TempRoot, "jingxu-gate-preview");
        Directory.CreateDirectory(folder);
        using var resource = TempResourceLease.Acquire(Path.Combine(folder, "pending.jpg"), dataDirectory: scope.DataRoot);

        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);

        Assert.True(Directory.Exists(folder), "登记与实际写入之间，清理不能删除生产者已经创建的父目录。");
    }

    [Fact]
    public void Startup_cleanup_preserves_a_live_staging_registration()
    {
        using var scope = new CleanupScope();
        var jobId = Guid.NewGuid();
        var staging = Path.Combine(scope.DataRoot, "分镜输出", ".jingxu-tmp", jobId.ToString("N"));
        Directory.CreateDirectory(staging);
        var input = Path.Combine(staging, "i0.mp4");
        File.WriteAllText(input, "still-in-use");
        StagingLeaseStore.Track(jobId, staging, scope.DataRoot);

        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);

        Assert.True(File.Exists(input), "活跃进程登记的输入即使没有打开文件句柄，也不能被启动清理删除。");
        StagingLeaseStore.Untrack(jobId, scope.DataRoot);
        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);
        Assert.False(Directory.Exists(staging));
    }

    [Fact]
    public void Cleanup_preserves_live_preview_registered_by_another_instance()
    {
        using var scope = new CleanupScope();
        var preview = Path.Combine(scope.TempRoot, "jingxu-gate-preview", Guid.NewGuid().ToString("N") + ".jpg");
        Directory.CreateDirectory(Path.GetDirectoryName(preview)!);
        File.WriteAllText(preview, "displayed-frame-without-open-handle");
        var registry = Path.Combine(scope.DataRoot, "resource-leases");
        Directory.CreateDirectory(registry);
        using var process = System.Diagnostics.Process.GetCurrentProcess();
        File.WriteAllText(Path.Combine(registry, Guid.NewGuid().ToString("N") + ".json"),
            System.Text.Json.JsonSerializer.Serialize(new
            {
                path = preview,
                isDirectory = false,
                processId = process.Id,
                processStartTicks = process.StartTime.ToUniversalTime().Ticks
            }));

        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);

        Assert.True(File.Exists(preview), "清理必须读取跨进程登记，不能仅依赖文件句柄占用。");
    }

    [Fact]
    public void Cleanup_reclaims_registered_orphan_download_on_its_destination_volume()
    {
        using var scope = new CleanupScope();
        var part = Path.Combine(scope.Root, "destination", ".jingxu-download", Guid.NewGuid().ToString("N") + ".part");
        Directory.CreateDirectory(Path.GetDirectoryName(part)!);
        File.WriteAllText(part, "cancelled-download");
        var registry = Path.Combine(scope.DataRoot, "resource-leases");
        Directory.CreateDirectory(registry);
        File.WriteAllText(Path.Combine(registry, Guid.NewGuid().ToString("N") + ".json"),
            System.Text.Json.JsonSerializer.Serialize(new
            {
                path = part,
                isDirectory = false,
                processId = int.MaxValue,
                processStartTicks = 1L
            }));

        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);

        Assert.False(File.Exists(part));
    }

    [Fact]
    public void Failed_staging_and_known_temp_dirs_are_removed_without_touching_exports_or_library()
    {
        using var scope = new CleanupScope();
        var outputDir = Path.Combine(scope.DataRoot, "分镜输出");
        Directory.CreateDirectory(outputDir);
        var export = Path.Combine(outputDir, "成片_001.mp4");
        File.WriteAllText(export, "user-export");
        File.WriteAllText(Path.Combine(scope.DataRoot, "overlay-library.json"), "{\"schemaVersion\":1}");

        var orphanJob = Guid.NewGuid();
        var staging = Path.Combine(outputDir, WorkbenchCacheCleanup.StagingDirectoryName, orphanJob.ToString("N"));
        Directory.CreateDirectory(staging);
        File.WriteAllText(Path.Combine(staging, "output.mp4"), "half-rendered");
        File.WriteAllText(Path.Combine(staging, "filter.ffc"), "script");

        var whisper = Path.Combine(scope.TempRoot, "jingxu-whisper", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(whisper);
        File.WriteAllText(Path.Combine(whisper, "audio.wav"), "wav");

        var downloadPart = Path.Combine(scope.TempRoot, "jingxu-download");
        Directory.CreateDirectory(downloadPart);
        var partFile = Path.Combine(downloadPart, Guid.NewGuid().ToString("N") + ".part");
        File.WriteAllText(partFile, "partial");

        var unrelated = Path.Combine(scope.TempRoot, "jingxu-not-ours");
        Directory.CreateDirectory(unrelated);
        File.WriteAllText(Path.Combine(unrelated, "keep.txt"), "keep");

        var result = WorkbenchCacheCleanup.Cleanup(scope.DataRoot, scope.TempRoot);

        Assert.False(Directory.Exists(staging));
        Assert.False(Directory.Exists(whisper));
        Assert.False(File.Exists(partFile));
        Assert.True(File.Exists(export));
        Assert.Equal("user-export", File.ReadAllText(export));
        Assert.True(File.Exists(Path.Combine(scope.DataRoot, "overlay-library.json")));
        Assert.True(File.Exists(Path.Combine(unrelated, "keep.txt")));
        Assert.True(result.DeletedDirectories > 0);
    }

    [Fact]
    public void Cleanup_skips_inflight_job_staging_and_protected_subtitle()
    {
        using var scope = new CleanupScope();
        var outputDir = Path.Combine(scope.DataRoot, "分镜输出");
        var inflightId = Guid.NewGuid();
        var orphanId = Guid.NewGuid();
        var inflight = Path.Combine(outputDir, WorkbenchCacheCleanup.StagingDirectoryName, inflightId.ToString("N"));
        var orphan = Path.Combine(outputDir, WorkbenchCacheCleanup.StagingDirectoryName, orphanId.ToString("N"));
        Directory.CreateDirectory(inflight);
        Directory.CreateDirectory(orphan);
        File.WriteAllText(Path.Combine(inflight, "output.mp4"), "running");
        File.WriteAllText(Path.Combine(orphan, "output.mp4"), "leftover");

        var subtitleDir = Path.Combine(scope.TempRoot, "jingxu-subtitle-burn");
        Directory.CreateDirectory(subtitleDir);
        var protectedAss = Path.Combine(subtitleDir, Guid.NewGuid().ToString("N") + ".ass");
        var staleAss = Path.Combine(subtitleDir, Guid.NewGuid().ToString("N") + ".ass");
        File.WriteAllText(protectedAss, "Dialogue: live");
        File.WriteAllText(staleAss, "Dialogue: stale");

        WorkbenchCacheCleanup.Cleanup(
            scope.DataRoot,
            scope.TempRoot,
            protectedJobIds: [inflightId],
            protectedFiles: [protectedAss]);

        Assert.True(File.Exists(Path.Combine(inflight, "output.mp4")));
        Assert.False(Directory.Exists(orphan));
        Assert.True(File.Exists(protectedAss));
        Assert.False(File.Exists(staleAss));
    }

    [Fact]
    public void Startup_orphans_do_not_delete_overlay_thumbs_or_finished_exports()
    {
        using var scope = new CleanupScope();
        var thumbs = Path.Combine(scope.DataRoot, WorkbenchCacheCleanup.OverlayThumbsDirectoryName);
        Directory.CreateDirectory(thumbs);
        var thumb = Path.Combine(thumbs, "mask.jpg");
        File.WriteAllText(thumb, "thumb");

        var outputDir = Path.Combine(scope.DataRoot, "分镜输出");
        Directory.CreateDirectory(outputDir);
        var export = Path.Combine(outputDir, "成片.mp4");
        File.WriteAllText(export, "done");

        var staging = Path.Combine(outputDir, WorkbenchCacheCleanup.StagingDirectoryName, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(staging);
        File.WriteAllText(Path.Combine(staging, "output.mp4"), "orphan");

        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);

        Assert.True(File.Exists(thumb));
        Assert.True(File.Exists(export));
        Assert.False(Directory.Exists(staging));
    }

    [Fact]
    public void Settings_cleanup_can_remove_overlay_thumb_cache()
    {
        using var scope = new CleanupScope();
        var thumbs = Path.Combine(scope.DataRoot, WorkbenchCacheCleanup.OverlayThumbsDirectoryName);
        Directory.CreateDirectory(thumbs);
        File.WriteAllText(Path.Combine(thumbs, "mask.jpg"), "thumb");

        WorkbenchCacheCleanup.Cleanup(scope.DataRoot, scope.TempRoot, includeOverlayThumbCache: true);

        Assert.False(Directory.Exists(thumbs));
    }

    [Fact]
    public void Tracked_staging_outside_data_root_is_removed_poisoned_ref_is_not()
    {
        using var scope = new CleanupScope();
        var foreignOutput = Path.Combine(scope.TempRoot, "user-source", "分镜输出");
        var jobId = Guid.NewGuid();
        var staging = Path.Combine(foreignOutput, WorkbenchCacheCleanup.StagingDirectoryName, jobId.ToString("N"));
        Directory.CreateDirectory(staging);
        File.WriteAllText(Path.Combine(staging, "output.mp4"), "half");
        var legacyRef = Path.Combine(StagingLeaseStore.GetStoreRoot(scope.DataRoot), jobId.ToString("N") + ".ref");
        Directory.CreateDirectory(Path.GetDirectoryName(legacyRef)!);
        File.WriteAllText(legacyRef, staging);

        var userVideo = Path.Combine(scope.TempRoot, "user-source", "素材.mp4");
        Directory.CreateDirectory(Path.GetDirectoryName(userVideo)!);
        File.WriteAllText(userVideo, "source");
        var poison = Path.Combine(StagingLeaseStore.GetStoreRoot(scope.DataRoot), Guid.NewGuid().ToString("N") + ".ref");
        Directory.CreateDirectory(Path.GetDirectoryName(poison)!);
        File.WriteAllText(poison, userVideo);

        WorkbenchCacheCleanup.CleanupStartupOrphans(scope.DataRoot, scope.TempRoot);

        Assert.False(Directory.Exists(staging));
        Assert.True(File.Exists(userVideo));
        Assert.Equal("source", File.ReadAllText(userVideo));
        Assert.False(File.Exists(poison));
    }

    [Fact]
    public void Owned_temp_subtitle_path_only_matches_jingxu_subtitle_burn()
    {
        var temp = Path.Combine(Path.GetTempPath(), "jingxu-cleanup-sub-" + Guid.NewGuid().ToString("N"));
        var owned = Path.Combine(temp, "jingxu-subtitle-burn", "a.ass");
        var user = Path.Combine(temp, "我的字幕.ass");

        Assert.True(WorkbenchCacheCleanup.IsOwnedTempSubtitlePath(owned, temp));
        Assert.False(WorkbenchCacheCleanup.IsOwnedTempSubtitlePath(user, temp));
        Assert.False(WorkbenchCacheCleanup.IsOwnedTempSubtitlePath(null, temp));
    }

    private sealed class CleanupScope : IDisposable
    {
        public CleanupScope()
        {
            Root = Path.Combine(Path.GetTempPath(), "jingxu-cache-test-" + Guid.NewGuid().ToString("N"));
            DataRoot = Path.Combine(Root, "data");
            TempRoot = Path.Combine(Root, "temp");
            Directory.CreateDirectory(DataRoot);
            Directory.CreateDirectory(TempRoot);
        }

        public string Root { get; }
        public string DataRoot { get; }
        public string TempRoot { get; }

        public void Dispose()
        {
            try
            {
                if (Directory.Exists(Root))
                {
                    Directory.Delete(Root, recursive: true);
                }
            }
            catch (IOException)
            {
            }
        }
    }
}
