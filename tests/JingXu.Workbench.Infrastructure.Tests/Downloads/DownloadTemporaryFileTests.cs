using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Infrastructure.Downloads;

namespace JingXu.Workbench.Infrastructure.Tests.Downloads;

public sealed class DownloadTemporaryFileTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Download_uses_a_partial_file_on_the_destination_volume(bool existingOutput)
    {
        var root = Path.Combine(Path.GetTempPath(), "jingxu-download-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var output = Path.Combine(root, "video.mp4");
        if (existingOutput) { await File.WriteAllTextAsync(output, "old"); }
        var inspected = false;
        using var contentStream = new InspectingStream(() =>
        {
            var folder = Path.Combine(root, ".jingxu-download");
            Assert.True(Directory.Exists(folder), "下载半成品必须位于目标目录所在卷。");
            Assert.Single(Directory.GetFiles(folder, "*.part"));
            inspected = true;
        });
        using var client = new HttpClient(new ContentHandler(contentStream));
        try
        {
            await new HttpClientVideoDownloader(client).DownloadAsync("https://example.com/video.mp4", output,
                new Progress<DownloadProgress>(), default);
            Assert.True(inspected);
            Assert.Equal("downloaded", await File.ReadAllTextAsync(output));
            Assert.Empty(Directory.GetFiles(root, "*.part", SearchOption.AllDirectories));
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    [Fact]
    public async Task Cancellation_removes_partial_file_and_keeps_existing_output()
    {
        var root = Path.Combine(Path.GetTempPath(), "jingxu-download-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        var output = Path.Combine(root, "video.mp4");
        await File.WriteAllTextAsync(output, "old");
        using var cancellation = new CancellationTokenSource();
        using var contentStream = new InspectingStream(() =>
        {
            Assert.True(Directory.Exists(Path.Combine(root, ".jingxu-download")));
            cancellation.Cancel();
        });
        using var client = new HttpClient(new ContentHandler(contentStream));
        try
        {
            await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
                new HttpClientVideoDownloader(client).DownloadAsync("https://example.com/video.mp4", output,
                    new Progress<DownloadProgress>(), cancellation.Token));
            Assert.Equal("old", await File.ReadAllTextAsync(output));
            Assert.Empty(Directory.GetFiles(root, "*.part", SearchOption.AllDirectories));
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private sealed class ContentHandler(Stream stream) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StreamContent(stream) });
    }

    private sealed class InspectingStream(Action inspect) : MemoryStream("downloaded"u8.ToArray())
    {
        private bool _inspected;
        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (!_inspected) { _inspected = true; inspect(); }
            return base.ReadAsync(buffer, cancellationToken);
        }
    }
}
