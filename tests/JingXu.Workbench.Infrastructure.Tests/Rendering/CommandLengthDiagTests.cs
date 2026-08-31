using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Domain.Composition;
using JingXu.Workbench.Domain.Effects;
using JingXu.Workbench.Domain.Media;
using JingXu.Workbench.Domain.Overlays;
using JingXu.Workbench.Domain.Rendering;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Infrastructure.Tests.Rendering;

public sealed class CommandLengthDiagTests
{
    [Theory]
    [InlineData(6, 1, 2, false)]
    [InlineData(6, 3, 5, true)]
    [InlineData(15, 2, 8, false)]
    public void Scripted_filter_keeps_argv_under_budget_for_rich_jobs(
        int clipCount,
        int overlayCount,
        int stickers,
        bool withGhost)
    {
        const string deep =
            @"C:\Users\Administrator\OneDrive\Desktop\炳恒混剪素材库\客户项目\商品短视频\2026年07月批次\竖屏3x4成片\原始素材归档";
        var request = BuildRequest(
            deep,
            clipCount,
            overlayCount,
            stickers,
            withBgm: true,
            withEffect: true,
            withDoubleScreen: true,
            withBoost: true,
            withGhost);

        var result = FfmpegCommandCompiler.Compile(
            @"C:\runtime\ffmpeg\ffmpeg.exe",
            request,
            Path.Combine(Path.GetDirectoryName(request.OutputPath)!, ".jingxu-tmp", "output.mp4"));

        var filter = result.TryGetFilterComplex();
        Assert.NotNull(filter);
        Assert.True(filter.Length > 1_000);
        Assert.Contains("-filter_complex_script", result.Command.Arguments);
        Assert.DoesNotContain("-filter_complex", result.Command.Arguments);
        Assert.True(
            result.Command.EstimatedCommandLineLength <= RenderPreflight.MaxCommandLineLength,
            $"argv {result.Command.EstimatedCommandLineLength} exceeded budget; filter was {filter.Length} chars");
    }

    [Fact]
    public void Extreme_path_length_stays_under_budget_after_aliasing()
    {
        var deep = @"C:\media\" + new string('长', 20_000);
        var request = BuildRequest(
            deep,
            clipCount: 6,
            overlayCount: 2,
            stickers: 3,
            withBgm: true,
            withEffect: true,
            withDoubleScreen: true,
            withBoost: true);

        var result = FfmpegCommandCompiler.Compile(
            @"C:\ffmpeg.exe",
            request,
            @"C:\out\temp.mp4");

        Assert.Contains("-filter_complex_script", result.Command.Arguments);
        Assert.DoesNotContain(result.Command.Arguments, a => a.Contains(new string('长', 100), StringComparison.Ordinal));
        Assert.True(result.InputAliases.Count >= 6);
        Assert.True(FfmpegCommandCompiler.ValidateCommandBudget(result.Command).IsSuccess);
    }

    private static RenderRequest BuildRequest(
        string baseDir,
        int clipCount,
        int overlayCount,
        int stickers,
        bool withBgm,
        bool withEffect,
        bool withDoubleScreen,
        bool withBoost,
        bool withGhost = false)
    {
        var clips = new List<PlannedClip>();
        var offset = TimeSpan.Zero;
        for (var i = 1; i <= clipCount; i++)
        {
            var path = Path.Combine(baseDir, $"素材_{i:00}_竖屏商品展示视频.mp4");
            var info = new MediaInfo(TimeSpan.FromSeconds(8), 1080, 1440, 30m, "h264", "aac", true, 0);
            clips.Add(new PlannedClip(new MediaAsset(Guid.NewGuid(), path, i, info), offset, info.Duration));
            offset += info.Duration;
        }

        var plan = new CompositionPlan(clips, offset, 1, TimeSpan.Zero);
        var layers = new List<OverlayLayer>();
        if (withGhost)
        {
            layers.Add(OverlayLayer.CreateSelfGhostPreset(TimeSpan.FromSeconds(3)));
        }

        for (var i = 0; i < overlayCount; i++)
        {
            var layer = OverlayLayer.CreateScreenshotPreset(
                Path.Combine(baseDir, $"蒙版层_{i}_顶部覆盖素材.mp4"),
                TimeSpan.FromSeconds(3)) with
            {
                TopFade = 1,
                Feather = 0.4,
                Scale = 1.15
            };
            layers.Add(layer);
        }

        var stickerList = new List<ImageSticker>();
        for (var i = 0; i < stickers; i++)
        {
            stickerList.Add(ImageSticker.Create(
                Path.Combine(baseDir, $"贴纸_{i}_logo.png"),
                0.1 + i * 0.05,
                0.2,
                0.2,
                0.15).Value!);
        }

        BgmMixPlan? bgm = withBgm ? BgmMixPlan.Create(Path.Combine(baseDir, "bgm_track.mp3")).Value! : null;
        var effect = withEffect ? EffectTemplates.StandardVariation().Materialize(1) : null;
        DoubleScreenEffectPlan? ds = withDoubleScreen ? new DoubleScreenEffectPlan(StartClipIndex: 2) : null;
        MaterializedMainMaterialBoost? boost = null;
        if (withBoost)
        {
            var planBoost = MainMaterialBoostPlan.Create(
                enableVolume: true,
                volumeMode: MainMaterialBoostMode.Fixed,
                volumeMinPercent: 105,
                volumeMaxPercent: 105,
                enableScale: true,
                scaleMode: MainMaterialBoostMode.Fixed,
                scaleMinPercent: 108,
                scaleMaxPercent: 108).Value!;
            boost = planBoost.Materialize(1, clipCount);
        }

        return new RenderRequest(
            plan,
            Path.Combine(baseDir, "分镜输出", "成片_001.mp4"),
            RenderProfile.Balanced,
            OutputAspect.InheritFirst,
            layers,
            HasEffects: withEffect || stickers > 0 || withDoubleScreen || withBoost,
            HasOverlays: layers.Count > 0,
            HasBgm: withBgm,
            HasMainMaterialBoost: withBoost,
            Effect: effect,
            Bgm: bgm,
            Stickers: stickerList,
            MainMaterialBoost: boost,
            DoubleScreen: ds);
    }
}
