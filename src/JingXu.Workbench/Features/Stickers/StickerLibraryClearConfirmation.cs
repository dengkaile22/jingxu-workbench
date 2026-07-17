using System.Windows;

namespace JingXu.Workbench.Features.Stickers;

/// <summary>贴纸素材库清空确认交互，便于视图模型测试取消与确认分支。</summary>
public interface IStickerLibraryClearConfirmation
{
    bool ConfirmClear(int entryCount);
}

/// <summary>生产环境使用的 WPF 确认弹窗。</summary>
public sealed class WpfStickerLibraryClearConfirmation : IStickerLibraryClearConfirmation
{
    public bool ConfirmClear(int entryCount) =>
        MessageBox.Show(
            $"确定清空贴纸素材库中的 {entryCount} 条记录吗？\n\n" +
            "只清空软件素材库，不会删除电脑中的 PNG/GIF 原文件，也不会删除当前贴纸轨道。",
            "确认清空贴纸素材库",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning,
            MessageBoxResult.No) == MessageBoxResult.Yes;
}
