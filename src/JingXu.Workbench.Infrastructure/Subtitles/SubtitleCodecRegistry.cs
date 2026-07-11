using JingXu.Workbench.Application.Abstractions;
using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Infrastructure.Subtitles;

/// <summary>字幕编解码器注册表。</summary>
public sealed class SubtitleCodecRegistry : ISubtitleCodecRegistry
{
    private readonly Dictionary<SubtitleFileFormat, ISubtitleDocumentCodec> _codecs;

    public SubtitleCodecRegistry()
        : this(new ISubtitleDocumentCodec[] { new SrtSubtitleCodec(), new AssSubtitleCodec() })
    {
    }

    public SubtitleCodecRegistry(IEnumerable<ISubtitleDocumentCodec> codecs)
    {
        _codecs = codecs.ToDictionary(x => x.Format);
    }

    public ISubtitleDocumentCodec GetCodec(SubtitleFileFormat format) =>
        _codecs.TryGetValue(format, out var codec)
            ? codec
            : throw new InvalidOperationException($"不支持的字幕格式：{format}");

    public ISubtitleDocumentCodec ResolveByPath(string path)
    {
        var extension = Path.GetExtension(path);
        return extension.ToLowerInvariant() switch
        {
            ".srt" => GetCodec(SubtitleFileFormat.Srt),
            ".ass" or ".ssa" => GetCodec(SubtitleFileFormat.Ass),
            _ => throw new InvalidOperationException($"无法根据扩展名识别字幕格式：{extension}")
        };
    }
}
