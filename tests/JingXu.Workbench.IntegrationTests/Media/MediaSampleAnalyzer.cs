using JingXu.Workbench.Infrastructure.Processes;

namespace JingXu.Workbench.IntegrationTests.Media;

/// <summary>从渲染输出中采样中心像素与主导音频频率。</summary>
internal static class MediaSampleAnalyzer
{
    private const int FrameWidth = 320;
    private const int FrameHeight = 240;

    public static async Task<Rgb24> SampleCenterPixelAsync(
        string ffmpegPath,
        string videoPath,
        TimeSpan timestamp,
        CancellationToken cancellationToken = default) =>
        await SamplePixelAsync(ffmpegPath, videoPath, timestamp, FrameWidth / 2, FrameHeight / 2, cancellationToken);

    public static async Task<Rgb24> SamplePixelAsync(
        string ffmpegPath,
        string videoPath,
        TimeSpan timestamp,
        int x,
        int y,
        CancellationToken cancellationToken = default)
    {
        var tempPng = Path.Combine(Path.GetTempPath(), "jingxu-frame-" + Guid.NewGuid().ToString("N") + ".png");
        try
        {
            var request = ProcessRequest.Create(
                ffmpegPath,
                [
                    "-y",
                    "-ss", FormatSeconds(timestamp),
                    "-i", videoPath,
                    "-frames:v", "1",
                    "-f", "image2",
                    tempPng
                ]);

            var result = await new ExternalProcessRunner().RunAsync(request, progress: null, cancellationToken);
            if (result.ExitCode != 0 || !File.Exists(tempPng))
            {
                throw new InvalidOperationException($"帧采样失败：{result.StandardError.Trim()}");
            }

            return ReadPixel(tempPng, x, y);
        }
        finally
        {
            try { File.Delete(tempPng); }
            catch (IOException) { }
        }
    }

    public static async Task<int> SampleDominantFrequencyAsync(
        string ffmpegPath,
        string videoPath,
        TimeSpan timestamp,
        TimeSpan window,
        CancellationToken cancellationToken = default)
    {
        var tempPcm = Path.Combine(Path.GetTempPath(), "jingxu-pcm-" + Guid.NewGuid().ToString("N") + ".raw");
        try
        {
            var request = ProcessRequest.Create(
                ffmpegPath,
                [
                    "-y",
                    "-ss", FormatSeconds(timestamp),
                    "-i", videoPath,
                    "-t", FormatSeconds(window),
                    "-vn",
                    "-ac", "1",
                    "-ar", "8000",
                    "-f", "s16le",
                    tempPcm
                ]);

            var result = await new ExternalProcessRunner().RunAsync(request, progress: null, cancellationToken);
            if (result.ExitCode != 0 || !File.Exists(tempPcm))
            {
                throw new InvalidOperationException($"音频采样失败：{result.StandardError.Trim()}");
            }

            var samples = await File.ReadAllBytesAsync(tempPcm, cancellationToken);
            return EstimateDominantFrequency(samples, sampleRate: 8000);
        }
        finally
        {
            try { File.Delete(tempPcm); }
            catch (IOException) { }
        }
    }

    private static Rgb24 ReadPixel(string pngPath, int x, int y)
    {
        using var stream = File.OpenRead(pngPath);
        using var image = System.Drawing.Image.FromStream(stream);
        using var bitmap = new System.Drawing.Bitmap(image);
        return ReadPixel(bitmap, x, y);
    }

    public static Rgb24 ReadImageCenterPixel(string imagePath)
    {
        using var stream = File.OpenRead(imagePath);
        using var image = System.Drawing.Image.FromStream(stream);
        using var bitmap = new System.Drawing.Bitmap(image);
        return ReadPixel(bitmap, bitmap.Width / 2, bitmap.Height / 2);
    }

    private static Rgb24 ReadPixel(System.Drawing.Bitmap bitmap, int x, int y)
    {
        var sampleX = Math.Clamp(x, 0, bitmap.Width - 1);
        var sampleY = Math.Clamp(y, 0, bitmap.Height - 1);
        var color = bitmap.GetPixel(sampleX, sampleY);
        return new Rgb24(color.R, color.G, color.B);
    }

    private static int EstimateDominantFrequency(byte[] pcmBytes, int sampleRate)
    {
        if (pcmBytes.Length < 4)
        {
            return 0;
        }

        var sampleCount = pcmBytes.Length / 2;
        var bestFrequency = 0;
        var bestPower = 0.0;

        foreach (var frequency in Enumerable.Range(150, 651))
        {
            var power = GoertzelPower(pcmBytes, sampleCount, sampleRate, frequency);
            if (power > bestPower)
            {
                bestPower = power;
                bestFrequency = frequency;
            }
        }

        return bestFrequency;
    }

    private static double GoertzelPower(byte[] pcmBytes, int sampleCount, int sampleRate, int targetFrequency)
    {
        var k = (int)Math.Round(0.5 + sampleCount * targetFrequency / (double)sampleRate);
        var omega = 2.0 * Math.PI * k / sampleCount;
        var cosine = Math.Cos(omega);
        var sine = Math.Sin(omega);
        var coefficient = 2.0 * cosine;

        double q0 = 0;
        double q1 = 0;
        double q2 = 0;

        for (var index = 0; index < sampleCount; index++)
        {
            var sample = BitConverter.ToInt16(pcmBytes, index * 2) / 32768.0;
            q0 = coefficient * q1 - q2 + sample;
            q2 = q1;
            q1 = q0;
        }

        var real = q1 - q2 * cosine;
        var imag = q2 * sine;
        return real * real + imag * imag;
    }

    private static string FormatSeconds(TimeSpan duration) =>
        duration.TotalSeconds.ToString("0.######", System.Globalization.CultureInfo.InvariantCulture);
}
