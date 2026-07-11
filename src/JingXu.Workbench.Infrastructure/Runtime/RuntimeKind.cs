namespace JingXu.Workbench.Infrastructure.Runtime;

/// <summary>第三方运行时组件种类。</summary>
public enum RuntimeKind
{
    /// <summary>FFmpeg 可执行文件。</summary>
    Ffmpeg,

    /// <summary>FFprobe 可执行文件。</summary>
    Ffprobe,

    /// <summary>whisper.cpp 命令行。</summary>
    WhisperCli,

    /// <summary>Whisper 多语言 base 模型。</summary>
    WhisperModel,

    /// <summary>Tesseract OCR。</summary>
    Tesseract
}
