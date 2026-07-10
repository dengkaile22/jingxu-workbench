using System.Text.RegularExpressions;
using JingXu.Workbench.Domain.Common;

namespace JingXu.Workbench.Domain.Composition;

/// <summary>
/// 从文件名提取序号，解析紧凑和逗号分隔的序号表达式。
/// </summary>
public static partial class FileSequenceParser
{
    /// <summary>
    /// 提取文件名中最后一个连续数字片段作为序号。
    /// 例如 "商品_片段_12.mp4" → 12。
    /// </summary>
    public static Result<int> ExtractIndex(string fileName)
    {
        if (string.IsNullOrWhiteSpace(fileName))
        {
            return Result<int>.Failure("文件名不能为空。");
        }

        // 去除扩展名后查找最后一个连续数字片段
        var nameWithoutExtension = Path.GetFileNameWithoutExtension(fileName);
        var matches = LastNumericTokenRegex().Matches(nameWithoutExtension);

        if (matches.Count == 0)
        {
            return Result<int>.Failure($"文件名 \"{fileName}\" 中未找到数字序号。");
        }

        var lastMatch = matches[^1];
        if (!int.TryParse(lastMatch.Value, out var index) || index <= 0)
        {
            return Result<int>.Failure($"文件名 \"{fileName}\" 中的序号 \"{lastMatch.Value}\" 必须是正整数。");
        }

        return Result<int>.Success(index);
    }

    /// <summary>
    /// 解析序号表达式。支持两种格式：
    /// <list type="bullet">
    /// <item>紧凑单位数字：如 "264513" → [2,6,4,5,1,3]</item>
    /// <item>逗号分隔任意位数：如 "2,6,14,5,1,3" → [2,6,14,5,1,3]</item>
    /// </list>
    /// 允许重复序号。
    /// </summary>
    public static Result<IReadOnlyList<int>> Parse(string expression)
    {
        if (string.IsNullOrWhiteSpace(expression))
        {
            return Result<IReadOnlyList<int>>.Failure("序号表达式不能为空。");
        }

        var trimmed = expression.Trim();

        // 包含逗号时使用逗号模式
        if (trimmed.Contains(','))
        {
            return ParseCommaExpression(trimmed);
        }

        // 全部由数字组成时使用紧凑模式
        if (AllDigitsRegex().IsMatch(trimmed))
        {
            return ParseCompactExpression(trimmed);
        }

        return Result<IReadOnlyList<int>>.Failure($"序号表达式 \"{expression}\" 格式无效，仅支持紧凑数字或逗号分隔格式。");
    }

    private static Result<IReadOnlyList<int>> ParseCompactExpression(string expression)
    {
        var indices = new List<int>(expression.Length);

        for (var i = 0; i < expression.Length; i++)
        {
            var digit = expression[i] - '0';
            if (digit is < 1 or > 9)
            {
                return Result<IReadOnlyList<int>>.Failure(
                    $"序号表达式第 {i + 1} 项 \"{expression[i]}\" 不是有效的正整数（1-9）。");
            }

            indices.Add(digit);
        }

        if (indices.Count == 0)
        {
            return Result<IReadOnlyList<int>>.Failure("序号表达式不能为空。");
        }

        return Result<IReadOnlyList<int>>.Success(indices);
    }

    private static Result<IReadOnlyList<int>> ParseCommaExpression(string expression)
    {
        var tokens = expression.Split(',');
        var indices = new List<int>(tokens.Length);

        for (var i = 0; i < tokens.Length; i++)
        {
            var token = tokens[i].Trim();
            if (string.IsNullOrWhiteSpace(token))
            {
                return Result<IReadOnlyList<int>>.Failure(
                    $"序号表达式第 {i + 1} 项为空。");
            }

            if (!int.TryParse(token, out var index) || index <= 0)
            {
                return Result<IReadOnlyList<int>>.Failure(
                    $"序号表达式第 {i + 1} 项 \"{token}\" 不是有效的正整数。");
            }

            indices.Add(index);
        }

        if (indices.Count == 0)
        {
            return Result<IReadOnlyList<int>>.Failure("序号表达式不能为空。");
        }

        return Result<IReadOnlyList<int>>.Success(indices);
    }

    [GeneratedRegex(@"\d+")]
    private static partial Regex LastNumericTokenRegex();

    [GeneratedRegex(@"^\d+$")]
    private static partial Regex AllDigitsRegex();
}
