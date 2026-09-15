using JingXu.Workbench.Application.Rendering;
using JingXu.Workbench.Infrastructure.Rendering;

namespace JingXu.Workbench.Application.Tests.Rendering;

public sealed class RenderPreflightTests
{
    [Fact]
    public void Disk_preflight_requires_output_plus_temp_times_one_point_two_five()
    {
        var result = RenderPreflight.CheckDisk(requiredBytes: 800, availableBytes: 999);
        Assert.False(result.IsSuccess);
        Assert.True(RenderPreflight.CheckDisk(800, 1000).IsSuccess);
    }

    [Fact]
    public void Default_output_uses_source_or_project_storyboard_folder()
    {
        Assert.Equal(@"C:\素材\分镜输出", OutputNamePolicy.DefaultDirectory([@"C:\素材"], @"C:\项目"));
        Assert.Equal(@"C:\项目\分镜输出", OutputNamePolicy.DefaultDirectory([@"C:\素材A", @"D:\素材B"], @"C:\项目"));
        Assert.Equal(@"C:\素材\分镜输出", RenderRequestFactory.ResolveDefaultOutputDirectory([@"C:\素材\a.mp4"], @"C:\项目"));
        Assert.Equal(@"C:\项目\分镜输出", RenderRequestFactory.ResolveDefaultOutputDirectory(
            [@"C:\素材A\a.mp4", @"D:\素材B\b.mp4"],
            @"C:\项目"));
        var configured = Environment.GetEnvironmentVariable("JINGXU_DATA_DIRECTORY");
        var dataRoot = !string.IsNullOrWhiteSpace(configured) && Path.IsPathFullyQualified(configured)
            ? Path.GetFullPath(configured)
            : Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "JingXu");
        Assert.Equal(Path.Combine(dataRoot, "分镜输出"), RenderRequestFactory.DefaultOutputDirectory);
    }

    [Fact]
    public void Command_budget_uses_shared_limit()
    {
        var result = RenderPreflight.CheckCommandBudget(RenderPreflight.MaxCommandLineLength + 1);
        Assert.False(result.IsSuccess);
        Assert.Contains("命令过长", result.Error, StringComparison.Ordinal);
    }
}
