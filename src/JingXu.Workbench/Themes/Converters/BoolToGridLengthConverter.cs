using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

/// <summary>
/// 将布尔值映射为 <see cref="GridLength"/>（像素）。<c>ConverterParameter</c>
/// 形如 <c>"144|36"</c>，<c>true</c> 取前者，<c>false</c> 取后者。
/// 用于队列底栏与检查器的折叠。
/// </summary>
public sealed class BoolToGridLengthConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (parameter is not string spec)
        {
            return new GridLength(1, GridUnitType.Star);
        }

        var parts = spec.Split('|');
        var chosen = value is true ? parts[0] : parts[^1];
        return double.TryParse(chosen, NumberStyles.Float, CultureInfo.InvariantCulture, out var pixels)
            ? new GridLength(pixels)
            : new GridLength(1, GridUnitType.Star);
    }

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
