using System.Windows;

namespace JingXu.Workbench.Features.AudioLibrary;

public interface IAudioLibraryClearConfirmation
{
    bool ConfirmClear(int entryCount);
}

public sealed class WpfAudioLibraryClearConfirmation : IAudioLibraryClearConfirmation
{
    public bool ConfirmClear(int entryCount) =>
        MessageBox.Show(
            $"确定清空音频库中的 {entryCount} 条记录吗？\n\n" +
            "只清空软件音频库，不会删除电脑中的原音频文件。",
            "确认清空音频库",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No) == MessageBoxResult.Yes;
}
