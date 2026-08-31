using System.Globalization;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

/// <summary>把 0–100 的百分比转换为 0–1 的不透明度。</summary>
public sealed class PercentageToOpacityConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        if (value is null)
        {
            return 1.0;
        }

        var doubleValue = value is double d ? d : System.Convert.ToDouble(value, culture);
        return Math.Clamp(doubleValue / 100.0, 0.0, 1.0);
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
    {
        if (value is null)
        {
            return 100.0;
        }

        var doubleValue = value is double d ? d : System.Convert.ToDouble(value, culture);
        return Math.Clamp(doubleValue * 100.0, 0.0, 100.0);
    }
}
