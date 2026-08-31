using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using JingXu.Workbench.Application.Composition;
using JingXu.Workbench.Application.Projects;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Features.Composition;

public sealed partial class CompositionViewModel
{
    public ObservableCollection<SequenceTemplate> SequenceTemplatesList { get; } = [];

    [ObservableProperty]
    private SequenceTemplate? _selectedSequenceTemplate;

    [ObservableProperty]
    private string _sequenceTemplateName = string.Empty;

    [ObservableProperty]
    private string _effectTemplateRenameName = string.Empty;

    public bool CanManageSelectedEffectTemplate => IsUserEffectTemplate(SelectedEffectTemplate);

    partial void OnSelectedSequenceTemplateChanged(SequenceTemplate? value) =>
        SequenceTemplateName = value?.DisplayName ?? string.Empty;

    partial void OnVariationIntensityPercentChanged(int value)
    {
        var clamped = Math.Clamp(value, 1, 200);
        if (clamped != value)
        {
            VariationIntensityPercent = clamped;
        }
    }

    [RelayCommand]
    private async Task LoadSequenceTemplatesAsync()
    {
        if (_sequenceTemplateService is null)
        {
            return;
        }

        try
        {
            var document = await _sequenceTemplateService.LoadAsync(cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() => ApplySequenceTemplateDocument(document));
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                StatusMessage = $"加载序号模板失败：{ex.GetBaseException().Message}";
            });
        }
    }

    [RelayCommand]
    private async Task SaveCurrentSequenceTemplateAsync()
    {
        if (_sequenceTemplateService is null)
        {
            ValidationMessage = "序号模板服务未装配。";
            return;
        }

        var name = SequenceTemplateName.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            ValidationMessage = "请输入要保存的序号模板名称。";
            return;
        }

        var template = new SequenceTemplate(Guid.NewGuid(), name, SequenceExpression);
        try
        {
            var document = await _sequenceTemplateService.UpsertAsync(template, cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplySequenceTemplateDocument(document, template.Id);
                StatusMessage = $"已保存序号模板「{name}」。";
                ValidationMessage = string.Empty;
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                ValidationMessage = $"保存序号模板失败：{ex.GetBaseException().Message}";
            });
        }
    }

    [RelayCommand]
    private void ApplySelectedSequenceTemplate()
    {
        if (SelectedSequenceTemplate is null)
        {
            return;
        }

        Mode = CompositionMode.CustomSequence;
        SequenceExpression = SelectedSequenceTemplate.Expression;
        RefreshPreview();
        StatusMessage = $"已应用序号模板「{SelectedSequenceTemplate.DisplayName}」。";
        ValidationMessage = string.Empty;
    }

    [RelayCommand]
    private async Task RenameSelectedSequenceTemplateAsync()
    {
        if (_sequenceTemplateService is null || SelectedSequenceTemplate is null)
        {
            return;
        }

        var name = SequenceTemplateName.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            ValidationMessage = "请输入新的序号模板名称。";
            return;
        }

        var selectedId = SelectedSequenceTemplate.Id;
        try
        {
            var result = await _sequenceTemplateService.RenameAsync(
                    selectedId,
                    name,
                    cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplySequenceTemplateDocument(result.Document, selectedId);
                if (result.Renamed)
                {
                    StatusMessage = $"已重命名序号模板为「{name}」。";
                    ValidationMessage = string.Empty;
                }
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                ValidationMessage = $"重命名序号模板失败：{ex.GetBaseException().Message}";
            });
        }
    }

    [RelayCommand]
    private async Task DeleteSelectedSequenceTemplateAsync()
    {
        if (_sequenceTemplateService is null || SelectedSequenceTemplate is null)
        {
            return;
        }

        var selectedId = SelectedSequenceTemplate.Id;
        try
        {
            var result = await _sequenceTemplateService.DeleteAsync(
                    selectedId,
                    cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplySequenceTemplateDocument(result.Document);
                if (result.Removed)
                {
                    StatusMessage = "已删除序号模板。";
                    ValidationMessage = string.Empty;
                }
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                ValidationMessage = $"删除序号模板失败：{ex.GetBaseException().Message}";
            });
        }
    }

    [RelayCommand(CanExecute = nameof(CanManageSelectedEffectTemplate))]
    private async Task RenameSelectedEffectTemplateAsync()
    {
        if (_templateService is null)
        {
            return;
        }

        await _initialEffectTemplateLoadTask.ConfigureAwait(false);
        var selected = SelectedEffectTemplate;
        if (selected is null || !IsUserEffectTemplate(selected))
        {
            return;
        }

        var name = EffectTemplateRenameName.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            ValidationMessage = "请输入新的效果模板名称。";
            return;
        }

        try
        {
            var result = await _templateService.RenameUserTemplateAsync(
                    selected.Id,
                    name,
                    cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyTemplateDocument(result.Document);
                if (result.Renamed)
                {
                    StatusMessage = $"已重命名效果模板为「{name}」。";
                    ValidationMessage = string.Empty;
                }
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                ValidationMessage = $"重命名效果模板失败：{ex.GetBaseException().Message}";
            });
        }
    }

    [RelayCommand(CanExecute = nameof(CanManageSelectedEffectTemplate))]
    private async Task DeleteSelectedEffectTemplateAsync()
    {
        if (_templateService is null)
        {
            return;
        }

        await _initialEffectTemplateLoadTask.ConfigureAwait(false);
        var selected = SelectedEffectTemplate;
        if (selected is null || !IsUserEffectTemplate(selected))
        {
            return;
        }

        try
        {
            var result = await _templateService.DeleteUserTemplateAsync(
                    selected.Id,
                    cancellationToken: CancellationToken.None)
                .ConfigureAwait(false);
            _uiDispatcher.Invoke(() =>
            {
                ApplyTemplateDocument(result.Document);
                if (result.Removed)
                {
                    SelectedEffectTemplate = EffectTemplates.None;
                    StatusMessage = "已删除效果模板。";
                    ValidationMessage = string.Empty;
                }
            });
        }
        catch (Exception ex)
        {
            _uiDispatcher.Invoke(() =>
            {
                ValidationMessage = $"删除效果模板失败：{ex.GetBaseException().Message}";
            });
        }
    }

    private void ApplySequenceTemplateDocument(SequenceTemplateDocument document, Guid? preferredTemplateId = null)
    {
        var selectedId = preferredTemplateId ?? SelectedSequenceTemplate?.Id;
        SequenceTemplatesList.Clear();
        foreach (var template in document.Templates)
        {
            SequenceTemplatesList.Add(template);
        }

        SelectedSequenceTemplate = SequenceTemplatesList.FirstOrDefault(template => template.Id == selectedId)
            ?? SequenceTemplatesList.FirstOrDefault();
    }

    private static bool IsUserEffectTemplate(EffectVariationTemplate? template) =>
        template is not null
        && template.Id != EffectTemplates.None.Id
        && template.Id != EffectTemplates.StandardVariation().Id;
}
