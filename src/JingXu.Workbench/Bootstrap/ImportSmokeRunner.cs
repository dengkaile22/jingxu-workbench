using System.IO;
using System.Text.Json;
using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Infrastructure.Media;
using JingXu.Workbench.Infrastructure.Processes;
using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Bootstrap;

/// <summary>
/// <c>--import-smoke &lt;path&gt;</c>：无 UI 探测/导入指定视频，输出 JSON，用于复现客户闪退。
/// </summary>
internal static class ImportSmokeRunner
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    public static int Run(string[] args)
    {
        var pathIndex = Array.FindIndex(args, a => string.Equals(a, "--import-smoke", StringComparison.OrdinalIgnoreCase));
        if (pathIndex < 0 || pathIndex + 1 >= args.Length)
        {
            Console.Error.WriteLine("用法: 炳恒快速混剪.exe --import-smoke <视频路径>");
            return 2;
        }

        var mediaPath = args[pathIndex + 1];
        var resultPath = pathIndex + 2 < args.Length && !args[pathIndex + 2].StartsWith('-')
            ? args[pathIndex + 2]
            : null;

        return RunAsync(mediaPath, resultPath).GetAwaiter().GetResult();
    }

    private static async Task<int> RunAsync(string mediaPath, string? resultPath)
    {
        var report = new Dictionary<string, object?>
        {
            ["path"] = mediaPath,
            ["exists"] = File.Exists(mediaPath),
            ["fileName"] = Path.GetFileName(mediaPath)
        };

        try
        {
            var index = FileSequenceParser.ExtractIndex(Path.GetFileName(mediaPath));
            report["sequenceSuccess"] = index.IsSuccess;
            report["sequenceValue"] = index.IsSuccess ? index.Value : null;
            report["sequenceError"] = index.IsSuccess ? null : index.Error;

            var appRoot = AppContext.BaseDirectory.TrimEnd(
                Path.DirectorySeparatorChar,
                Path.AltDirectorySeparatorChar);
            var probe = new FfprobeMediaProbe(
                new ExternalProcessRunner(),
                new RuntimeResolver(appRoot, ResolveFromPath));

            var info = await probe.ProbeAsync(mediaPath, CancellationToken.None).ConfigureAwait(false);
            report["probeOk"] = true;
            report["durationSeconds"] = info.Duration.TotalSeconds;
            report["width"] = info.Width;
            report["height"] = info.Height;
            report["videoCodec"] = info.VideoCodec;
            report["audioCodec"] = info.AudioCodec;
            report["hasAudio"] = info.HasAudio;
            report["frameRate"] = info.FrameRate;
            report["rotation"] = info.RotationDegrees;

            var outcomes = await CompositionOrchestrator.ImportAsync(probe, [mediaPath], CancellationToken.None)
                .ConfigureAwait(false);
            var outcome = outcomes[0];
            report["importOk"] = outcome.Asset is not null;
            report["importSequenceIndex"] = outcome.Asset?.SequenceIndex;
            report["importWarning"] = outcome.SequenceWarning;
            report["importError"] = outcome.ProbeError;
            report["success"] = outcome.Asset is not null;
        }
        catch (Exception ex)
        {
            report["probeOk"] = false;
            report["success"] = false;
            report["errorType"] = ex.GetType().FullName;
            report["error"] = ex.ToString();
        }

        var json = JsonSerializer.Serialize(report, JsonOptions);
        Console.WriteLine(json);
        if (!string.IsNullOrWhiteSpace(resultPath))
        {
            await File.WriteAllTextAsync(resultPath, json).ConfigureAwait(false);
        }

        return report.TryGetValue("success", out var ok) && ok is true ? 0 : 1;
    }

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
}
