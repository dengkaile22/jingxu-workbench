using JingXu.Workbench.Domain.Subtitles;

namespace JingXu.Workbench.Application.Abstractions;

/// <summary>字幕文档编解码（SRT/ASS）。</summary>
public interface ISubtitleDocumentCodec
{
    SubtitleFileFormat Format { get; }

    IReadOnlyList<SubtitleCue> Read(string content, string sourcePath);

    string Write(IReadOnlyList<SubtitleCue> cues, SubtitleStyle? style = null);
}

/// <summary>按格式选择编解码器。</summary>
public interface ISubtitleCodecRegistry
{
    ISubtitleDocumentCodec GetCodec(SubtitleFileFormat format);

    ISubtitleDocumentCodec ResolveByPath(string path);
}
