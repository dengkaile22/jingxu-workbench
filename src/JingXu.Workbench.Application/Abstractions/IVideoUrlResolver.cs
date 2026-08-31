namespace JingXu.Workbench.Application.Abstractions;

public sealed record ResolvedVideoInfo(
    string DirectMediaUrl,
    string? Title = null,
    bool IsDirectMedia = true);

public interface IVideoUrlResolver
{
    Task<ResolvedVideoInfo> ResolveAsync(string inputUrl, CancellationToken cancellationToken);
}
