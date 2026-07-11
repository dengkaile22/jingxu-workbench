using System.IO;
using System.Text.Json;
using JingXu.Workbench.Application.Overlays;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Features.Overlays;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// <c>--overlay-smoke &lt;path&gt; [mode]</c>：无 UI 复现蒙版页添加层流程，输出 JSON。
/// mode 可选：free（默认）、full、shape。
/// </summary>
internal static class OverlaySmokeRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static int Run(string[] args)
    {
        var pathIndex = Array.FindIndex(args, a => string.Equals(a, "--overlay-smoke", StringComparison.OrdinalIgnoreCase));
        if (pathIndex < 0 || pathIndex + 1 >= args.Length)
        {
            Console.Error.WriteLine("用法: JingXu.Workbench.exe --overlay-smoke <蒙版视频路径> [free|full|shape]");
            return 2;
        }

        var mediaPath = args[pathIndex + 1];
        var modeToken = pathIndex + 2 < args.Length && !args[pathIndex + 2].StartsWith('-')
            ? args[pathIndex + 2]
            : "free";

        if (!TryParseMode(modeToken, out var mode))
        {
            Console.Error.WriteLine($"未知蒙版模式「{modeToken}」，可选：free、full、shape。");
            return 2;
        }

        return RunAsync(mediaPath, mode).GetAwaiter().GetResult();
    }

    private static async Task<int> RunAsync(string mediaPath, OverlayMode mode)
    {
        var report = new Dictionary<string, object?>
        {
            ["path"] = mediaPath,
            ["exists"] = File.Exists(mediaPath),
            ["fileName"] = Path.GetFileName(mediaPath),
            ["mode"] = mode.ToString()
        };

        try
        {
            if (!File.Exists(mediaPath))
            {
                report["success"] = false;
                report["error"] = "蒙版素材不存在或无法访问。";
                WriteReport(report);
                return 1;
            }

            var appRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var probe = new FfprobeMediaProbe(
                new ExternalProcessRunner(),
                new RuntimeResolver(appRoot, ResolveFromPath));

            var info = await probe.ProbeAsync(mediaPath, CancellationToken.None).ConfigureAwait(false);
            report["probeOk"] = true;
            report["durationSeconds"] = info.Duration.TotalSeconds;
            report["width"] = info.Width;
            report["height"] = info.Height;

            if (info.Duration <= TimeSpan.Zero)
            {
                report["success"] = false;
                report["error"] = "蒙版素材时长无效（必须大于 0 秒）。";
                WriteReport(report);
                return 1;
            }

            var layer = mode switch
            {
                OverlayMode.FreeCover => OverlayLayer.CreateScreenshotPreset(mediaPath, info.Duration),
                OverlayMode.FullFrameLowOpacity => OverlayLayer.CreateFullFramePreset(mediaPath, info.Duration),
                OverlayMode.ShapeMask => OverlayLayer.CreateShapeMask(
                    mediaPath,
                    info.Duration,
                    new Domain.Common.NormalizedRect(0.1, 0.1, 0.8, 0.4)),
                _ => throw new ArgumentOutOfRangeException(nameof(mode), mode, null)
            };

            var state = new OverlayWorkbenchState();
            var picker = new FixedMediaFilePicker(mediaPath);
            var vm = new OverlayEditorViewModel(picker, state, probe, new WpfUiDispatcher());

            var command = mode switch
            {
                OverlayMode.FreeCover => vm.AddFreeCoverCommand,
                OverlayMode.FullFrameLowOpacity => vm.AddFullFrameCommand,
                OverlayMode.ShapeMask => vm.AddShapeMaskCommand,
                _ => throw new ArgumentOutOfRangeException(nameof(mode), mode, null)
            };

            await command.ExecuteAsync(null).ConfigureAwait(false);

            report["layerCount"] = vm.Layers.Count;
            report["statusMessage"] = vm.StatusMessage;
            report["sourcePath"] = vm.Selected?.Layer.SourcePath;
            report["success"] = vm.Layers.Count == 1 && vm.Selected?.Layer.SourcePath == mediaPath;

            if (report["success"] is not true)
            {
                report["error"] = string.IsNullOrWhiteSpace(vm.StatusMessage)
                    ? "添加蒙版层后列表为空，原因未知。"
                    : vm.StatusMessage;
            }
        }
        catch (Exception ex)
        {
            report["success"] = false;
            report.TryAdd("probeOk", false);
            report["errorType"] = ex.GetType().FullName;
            report["error"] = ex.GetBaseException().Message;
        }

        WriteReport(report);
        return report.TryGetValue("success", out var ok) && ok is true ? 0 : 1;
    }

    private static bool TryParseMode(string token, out OverlayMode mode)
    {
        switch (token.Trim().ToLowerInvariant())
        {
            case "free":
            case "freecover":
                mode = OverlayMode.FreeCover;
                return true;
            case "full":
            case "fullframe":
                mode = OverlayMode.FullFrameLowOpacity;
                return true;
            case "shape":
            case "shapemask":
                mode = OverlayMode.ShapeMask;
                return true;
            default:
                mode = default;
                return false;
        }
    }

    private static void WriteReport(Dictionary<string, object?> report) =>
        Console.WriteLine(JsonSerializer.Serialize(report, JsonOptions));

    private static string? ResolveFromPath(string executableName)
    {
        var pathValue = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathValue))
        {
            return null;
        }

        foreach (var directory in pathValue.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim(), executableName);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            catch
            {
                // ignore
            }
        }

        return null;
    }

    private sealed class FixedMediaFilePicker(string path) : IMediaFilePicker
    {
        public IReadOnlyList<string>? PickVideoFiles() => [path];

        public string? PickAudioFile() => path;

        public string? PickImageFile() => path;
    }
}
