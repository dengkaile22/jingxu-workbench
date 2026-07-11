using System.Globalization;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

/// <summary>将数值取一半并取反，用于 Canvas 中心锚点偏移。</summary>
public sealed class HalfNegateConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is double d)
        {
            return -d / 2.0;
        }

        if (value is int i)
        {
            return -i / 2.0;
        }

        return 0.0;
    }

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
