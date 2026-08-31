using System.Globalization;
using System.Windows.Data;
using JingXu.Workbench.Domain.Stickers;

namespace JingXu.Workbench.Themes.Converters;

public sealed class EnumDisplayNameConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        if (value is StickerAspectMode mode)
        {
            return mode.GetDisplayName();
        }

        if (value is FixedAspectRatio ratio)
        {
            return ratio.GetDisplayName();
        }

        return value?.ToString() ?? string.Empty;
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
    {
        throw new NotSupportedException();
    }
}
