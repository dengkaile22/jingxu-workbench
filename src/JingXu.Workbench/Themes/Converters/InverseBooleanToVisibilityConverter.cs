using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

/// <summary>
/// <c>true</c> → <see cref="Visibility.Collapsed"/>，<c>false</c> → <see cref="Visibility.Visible"/>。
/// </summary>
public sealed class InverseBooleanToVisibilityConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is true ? Visibility.Collapsed : Visibility.Visible;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        value is Visibility.Collapsed;
}
