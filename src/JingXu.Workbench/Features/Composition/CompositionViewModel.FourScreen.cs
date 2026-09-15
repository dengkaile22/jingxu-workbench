using CommunityToolkit.Mvvm.ComponentModel;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Features.Composition;

public sealed partial class CompositionViewModel
{
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsFourScreenSettingsEnabled))]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private bool _enableFourScreen;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(EnqueueCommand))]
    private int _fourScreenStartClipIndex = 1;

    [ObservableProperty]
    private bool _fourScreenUseRandomCurrentFolder;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(FourScreenFeatherLabel))]
    private bool _fourScreenFeatherEnabled = true;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(FourScreenFeatherLabel))]
    private int _fourScreenFeatherPixels = FourScreenEffectPlan.DefaultFeatherPixels;

    public bool IsFourScreenSettingsEnabled => EnableVariationEffects && EnableFourScreen;

    public string FourScreenFeatherLabel => FourScreenFeatherEnabled ? $"{FourScreenFeatherPixels} 像素" : "关闭";

    partial void OnEnableFourScreenChanged(bool value)
    {
        if (value)
        {
            EnableDoubleScreen = false;
        }

        RefreshQualityHint();
    }

    partial void OnFourScreenUseRandomCurrentFolderChanged(bool value) => RefreshQualityHint();

    partial void OnFourScreenFeatherEnabledChanged(bool value) => RefreshQualityHint();

    partial void OnFourScreenFeatherPixelsChanged(int value) => RefreshQualityHint();

    private void ApplyFourScreenTemplate(FourScreenSettingsDto? settings)
    {
        FourScreenStartClipIndex = Math.Max(settings?.StartClipIndex ?? 1, 1);
        FourScreenUseRandomCurrentFolder = settings?.UseRandomCurrentFolder ?? false;
        FourScreenFeatherEnabled = settings?.FeatherEnabled ?? true;
        FourScreenFeatherPixels = Math.Clamp(settings?.FeatherPixels ?? FourScreenEffectPlan.DefaultFeatherPixels,
            0, FourScreenEffectPlan.MaxFeatherPixels);
        EnableFourScreen = settings?.Enabled ?? false;
        if (EnableFourScreen)
        {
            EnableVariationEffects = true;
        }
    }

    private FourScreenSettingsDto CreateFourScreenSettings() => new()
    {
        Enabled = EnableVariationEffects && EnableFourScreen,
        StartClipIndex = FourScreenStartClipIndex,
        UseRandomCurrentFolder = FourScreenUseRandomCurrentFolder,
        FeatherEnabled = FourScreenFeatherEnabled,
        FeatherPixels = FourScreenFeatherPixels
    };
}
