using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

public sealed class PercentageToDynamicCanvasLengthConverter : IMultiValueConverter
{
    public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture)
    {
        if (values.Length < 3
            || !TryReadFiniteDouble(values[0], culture, out var percentage)
            || !TryReadFiniteDouble(values[1], culture, out var canvasWidth)
            || !TryReadFiniteDouble(values[2], culture, out var canvasHeight))
        {
            return 0.0;
        }

        var axis = parameter as string;
        var canvasSize = axis == "Y" || axis == "Height" ? canvasHeight : canvasWidth;

        return Math.Clamp(percentage / 100.0, 0.0, 1.0) * Math.Max(0.0, canvasSize);
    }

    public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture)
    {
        throw new NotSupportedException();
    }

    private static bool TryReadFiniteDouble(object? value, CultureInfo culture, out double result)
    {
        result = 0;
        if (value is null
            || ReferenceEquals(value, DependencyProperty.UnsetValue)
            || ReferenceEquals(value, Binding.DoNothing))
        {
            return false;
        }

        try
        {
            result = value is double number
                ? number
                : System.Convert.ToDouble(value, culture);
            return double.IsFinite(result);
        }
        catch (Exception ex) when (ex is InvalidCastException or FormatException or OverflowException)
        {
            result = 0;
            return false;
        }
    }
}
