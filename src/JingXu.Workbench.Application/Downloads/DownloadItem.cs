namespace JingXu.Workbench.Application.Downloads;

public enum DownloadItemState
{
    Pending,
    Downloading,
    Completed,
    Failed,
    Cancelled
}

public sealed record DownloadItem(
    Guid Id,
    string Url,
    int Index,
    string FileName,
    string OutputPath,
    DownloadItemState State,
    double ProgressPercent,
    double BytesPerSecond,
    long BytesReceived,
    long? TotalBytes,
    string? ErrorMessage)
{
    public static DownloadItem Create(string url, int index, string outputPath)
    {
        var fileName = $"{index}.mp4";
        return new DownloadItem(
            Guid.NewGuid(),
            url,
            index,
            fileName,
            outputPath,
            DownloadItemState.Pending,
            0, 0, 0, null, null);
    }

    public DownloadItem WithProgress(double percent, double speed, long received, long? total) =>
        this with
        {
            State = DownloadItemState.Downloading,
            ProgressPercent = percent,
            BytesPerSecond = speed,
            BytesReceived = received,
            TotalBytes = total
        };

    public DownloadItem Complete() =>
        this with { State = DownloadItemState.Completed, ProgressPercent = 100 };

    public DownloadItem Fail(string error) =>
        this with { State = DownloadItemState.Failed, ErrorMessage = error };

    public DownloadItem Cancel() =>
        this with { State = DownloadItemState.Cancelled };
}
