namespace JingXu.Workbench.Application.Abstractions;

public record DownloadProgress(
    long BytesReceived,
    long? TotalBytes,
    double BytesPerSecond,
    double Percent);

public interface IVideoDownloader
{
    Task DownloadAsync(
        string url,
        string outputPath,
        IProgress<DownloadProgress> progress,
        CancellationToken cancellationToken);
}
