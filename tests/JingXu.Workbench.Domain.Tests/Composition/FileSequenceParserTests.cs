using JingXu.Workbench.Domain.Composition;

namespace JingXu.Workbench.Domain.Tests.Composition;

public sealed class FileSequenceParserTests
{
    // --- ExtractIndex ---

    [Theory]
    [InlineData("商品_片段_12.mp4", 12)]
    [InlineData("clip9-final.mp4", 9)]
    [InlineData("video_3_v2.mov", 2)]
    [InlineData("1.mp4", 1)]
    [InlineData("素材100.mkv", 100)]
    public void Extracts_last_numeric_token(string fileName, int expected) =>
        Assert.Equal(expected, FileSequenceParser.ExtractIndex(fileName).Value);

    [Theory]
    [InlineData("no-number.mp4")]
    [InlineData("")]
    [InlineData("   ")]
    public void Returns_failure_for_missing_or_empty_filename(string fileName) =>
        Assert.False(FileSequenceParser.ExtractIndex(fileName).IsSuccess);

    // --- Parse compact ---

    [Fact]
    public void Parses_compact_single_digit_expression() =>
        Assert.Equal([2, 6, 4, 5, 1, 3], FileSequenceParser.Parse("264513").Value);

    [Fact]
    public void Compact_rejects_zero_digit()
    {
        var result = FileSequenceParser.Parse("1023");
        Assert.False(result.IsSuccess);
        Assert.Contains("第 2 项", result.Error!);
    }

    // --- Parse comma ---

    [Fact]
    public void Parses_comma_expression_with_multi_digit_and_duplicates() =>
        Assert.Equal([2, 6, 14, 14, 3], FileSequenceParser.Parse("2,6,14,14,3").Value);

    [Fact]
    public void Comma_expression_allows_spaces() =>
        Assert.Equal([1, 2, 3], FileSequenceParser.Parse(" 1 , 2 , 3 ").Value);

    // --- Invalid expressions ---

    [Theory]
    [InlineData("")]
    [InlineData("2,a,3")]
    [InlineData("   ")]
    public void Rejects_ambiguous_or_invalid_expression(string value) =>
        Assert.False(FileSequenceParser.Parse(value).IsSuccess);

    [Fact]
    public void Comma_expression_rejects_negative_number()
    {
        var result = FileSequenceParser.Parse("1,-2,3");
        Assert.False(result.IsSuccess);
    }

    [Fact]
    public void Comma_expression_rejects_empty_token()
    {
        var result = FileSequenceParser.Parse("1,,3");
        Assert.False(result.IsSuccess);
        Assert.Contains("第 2 项", result.Error!);
    }

    [Fact]
    public void Error_message_identifies_specific_position()
    {
        var result = FileSequenceParser.Parse("2,abc,3");
        Assert.False(result.IsSuccess);
        Assert.Contains("第 2 项", result.Error!);
        Assert.Contains("abc", result.Error!);
    }
}
