using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace JingXu.Workbench.Themes.Converters;

public sealed class DownloadProgressToVisibilityConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture) =>
        value is double d and > 0 ? Visibility.Visible : Visibility.Collapsed;

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}

public sealed class BytesPerSecondConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        if (value is not double bytesPerSecond || bytesPerSecond <= 0)
        {
            return "";
        }

        if (bytesPerSecond >= 1_073_741_824)
        {
            return $"{bytesPerSecond / 1_073_741_824.0:0.#} GB/s";
        }

        if (bytesPerSecond >= 1_048_576)
        {
            return $"{bytesPerSecond / 1_048_576.0:0.#} MB/s";
        }

        if (bytesPerSecond >= 1024)
        {
            return $"{bytesPerSecond / 1024.0:0.#} KB/s";
        }

        return $"{bytesPerSecond:0} B/s";
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
