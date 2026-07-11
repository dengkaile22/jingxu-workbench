using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

/// <summary>
/// 将枚举值与 <c>ConverterParameter</c> 指定的枚举名比较，相等则为 <c>true</c>。
/// 用于把矩形分段器（一组 RadioButton）绑定到单个枚举属性。
/// </summary>
public sealed class EnumToBooleanConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is null || parameter is not string name)
        {
            return false;
        }

        return string.Equals(value.ToString(), name, StringComparison.Ordinal);
    }

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is true && parameter is string name && targetType.IsEnum)
        {
            return Enum.Parse(targetType, name);
        }

        return Binding.DoNothing;
    }
}
