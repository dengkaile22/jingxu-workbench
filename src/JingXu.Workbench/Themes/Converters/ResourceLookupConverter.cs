using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

/// <summary>
/// 将资源键字符串解析为实际资源（例如画刷或几何图形）。
/// 用于把 <c>StatusPresentation</c> 暴露的 IconKey / FillKey 绑定到具体资源。
/// </summary>
public sealed class ResourceLookupConverter : IValueConverter
{
    public object? Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is not string key || string.IsNullOrEmpty(key))
        {
            return DependencyProperty.UnsetValue;
        }

        return System.Windows.Application.Current?.TryFindResource(key) ?? DependencyProperty.UnsetValue;
    }

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
