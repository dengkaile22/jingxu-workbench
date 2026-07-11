using JingXu.Workbench.Infrastructure.Runtime;

namespace JingXu.Workbench.Infrastructure.Tests.Runtime;

public sealed class RuntimeResolverTests
{
    [Fact]
    public void Bundled_runtime_wins_over_user_and_path()
    {
        using var dir = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe", "user/ffmpeg.exe");
        var result = new RuntimeResolver(dir.AppRoot, dir.PathLookup).Resolve("ffmpeg", dir.UserPath);
        Assert.Equal(dir.BundledFfmpeg, result.Path);
    }

    [Fact]
    public void Bundled_runtime_reports_bundled_source()
    {
        using var dir = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffmpeg.exe");
        var result = new RuntimeResolver(dir.AppRoot, dir.PathLookup).Resolve("ffmpeg", dir.UserPath);
        Assert.Equal(RuntimeSource.Bundled, result.Source);
    }

    [Fact]
    public void Bundled_folder_also_provides_ffprobe()
    {
        using var dir = RuntimeLayout.WithExecutables("app/runtime/ffmpeg/ffprobe.exe");
        var result = new RuntimeResolver(dir.AppRoot, dir.PathLookup).Resolve("ffprobe", dir.UserPath);
        Assert.Equal(dir.BundledFfprobe, result.Path);
        Assert.Equal(RuntimeSource.Bundled, result.Source);
    }

    [Fact]
    public void User_directory_wins_over_path_when_no_bundled()
    {
        using var dir = RuntimeLayout.WithExecutables("user/ffmpeg.exe").AddPathExecutable("ffmpeg");
        var result = new RuntimeResolver(dir.AppRoot, dir.PathLookup).Resolve("ffmpeg", dir.UserPath);
        Assert.Equal(dir.UserFfmpeg, result.Path);
        Assert.Equal(RuntimeSource.User, result.Source);
    }

    [Fact]
    public void Path_lookup_used_as_last_resort()
    {
        using var dir = RuntimeLayout.Create().AddPathExecutable("ffmpeg");
        var result = new RuntimeResolver(dir.AppRoot, dir.PathLookup).Resolve("ffmpeg", dir.UserPath);
        Assert.Equal(RuntimeSource.Path, result.Source);
        Assert.True(System.IO.File.Exists(result.Path));
    }

    [Fact]
    public void Missing_tool_throws_localized_exception()
    {
        using var dir = RuntimeLayout.Create();
        var resolver = new RuntimeResolver(dir.AppRoot, dir.PathLookup);
        var exception = Assert.Throws<RuntimeToolNotFoundException>(() => resolver.Resolve("ffmpeg", dir.UserPath));
        Assert.Contains("ffmpeg", exception.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Null_user_directory_falls_back_to_path()
    {
        using var dir = RuntimeLayout.Create().AddPathExecutable("ffmpeg");
        var result = new RuntimeResolver(dir.AppRoot, dir.PathLookup).Resolve("ffmpeg", userDirectory: null);
        Assert.Equal(RuntimeSource.Path, result.Source);
    }
}
