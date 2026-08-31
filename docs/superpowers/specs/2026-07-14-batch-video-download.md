# 批量链接下载模块设计规格

## 概述

将现有的「字幕实验室」模块替换为「批量下载」模块，支持从粘贴的直链批量下载视频文件。

## 功能需求

### 核心流程

1. 用户粘贴多个视频直链（一行一个）到文本框
2. 系统自动按粘贴顺序编号 1, 2, 3…N，生成默认文件名 `1.mp4`、`2.mp4`…
3. 用户可以双击编辑每个文件序号和文件名
4. 用户可选择保存目录（默认 `D:\下载` 或自定义）
5. 点击「开始下载」并发下载（最多 5 个同时）
6. 每个链接有独立进度条、下载速度显示
7. 下载完成后列表保留，可「清空列表」以准备下一批

### 界面布局

```
┌─ 批量下载 ──────────────────────────────────┐
│ 保存目录: [D:\视频下载] [浏览]                │
├─────────────────────────────────────────────┤
│ 粘贴视频链接（每行一个，支持批量粘贴）：        │
│ ┌─────────────────────────────────────────┐ │
│ │ https://v26-default.365yg.com/xxx...    │ │
│ │ https://v26-default.365yg.com/xxx...    │ │
│ │ https://v26-default.365yg.com/xxx...    │ │
│ │                                         │ │
│ └─────────────────────────────────────────┘ │
│ [解析链接]                                    │
├─────────────────────────────────────────────┤
│ 文件列表：                                    │
│ ┌─────────────────────────────────────────┐ │
│ │ #  文件名             进度    速度      │ │
│ │ 1  商品视频_01.mp4  ████████ 80% 5MB/s │ │
│ │ 2  商品视频_02.mp4  ██████░░ 60% 4MB/s │ │
│ │ 3  商品视频_03.mp4  ░░░░░░░░ 待下载    │ │
│ │ 4  商品视频_04.mp4  ░░░░░░░░ 待下载    │ │
│ │ 5  商品视频_05.mp4  ░░░░░░░░ 待下载    │ │
│ │ 6  商品视频_06.mp4  ✓✓✓✓✓✓✓✓ 已完成  │ │
│ └─────────────────────────────────────────┘ │
│ [开始下载] [全部暂停] [清空列表]              │
└─────────────────────────────────────────────┘
```

### 状态说明

每个下载项的状态流转：

| 状态 | 含义 |
|------|------|
| Pending | 等待下载（解析后默认） |
| Downloading | 下载中（显示进度条 + 速度） |
| Completed | 下载完成（绿色勾） |
| Failed | 下载失败（红色叹号 + 错误信息） |
| Cancelled | 用户取消 |

## 技术方案

### 架构

遵循现有 Clean Architecture 模式，新增文件：

```
src/JingXu.Workbench.Application/
  Abstractions/
    IVideoDownloader.cs           # 下载器接口
  Downloads/
    DownloadState.cs               # 下载项状态枚举
    DownloadItem.cs                # 下载项记录
    DownloadUrlParser.cs           # URL 解析（提取文件名、验证格式）

src/JingXu.Workbench.Infrastructure/
  Downloads/
    HttpClientVideoDownloader.cs   # HttpClient 实现

src/JingXu.Workbench/
  Features/Downloads/
    DownloadViewModel.cs           # 下载模块 VM
    DownloadView.xaml              # 下载模块视图
    DownloadView.xaml.cs           # 代码后置
```

### 下载接口设计

```csharp
public interface IVideoDownloader
{
    Task DownloadAsync(
        string url,
        string outputPath,
        IProgress<DownloadProgress> progress,
        CancellationToken cancellationToken);
}

public record DownloadProgress(
    long BytesReceived,
    long TotalBytes,
    double BytesPerSecond,
    double Percent);
```

### HttpClient 实现要点

- 使用 `HttpCompletionOption.ResponseHeadersRead` 流式读取
- `SemaphoreSlim(5)` 控制最大并发
- 每 200ms 计算下载速度（滑动窗口）
- 支持断点续传？（暂不支持，后续可加）

### 并发控制

ViewModel 内置 `SemaphoreSlim(5)`：
- 用户点击「开始下载」后，遍历所有 Pending 项
- 每次最多 5 个同时下载
- 一个完成后自动启动下一个 Pending 项
- 点击「全部暂停」取消所有活跃 CancellationToken

### 涉及修改的现有文件

| 文件 | 变更 |
|------|------|
| `WorkspaceModule.cs` | Subtitles → Downloads |
| `ShellViewModel.cs` | 替换 SubtitleLabViewModel → DownloadViewModel |
| `ShellWindow.xaml` | 替换 DataTemplate、导航标签名、图标 |
| `AppCompositionRoot.cs` | 替换 DI 注入 |
| `Themes/Controls.xaml` | 新增下载进度条样式 |

### 删除/保留

- 字幕模块的 5 个源文件保留在 `Features/Subtitles/` 中，不删除
- 从导航栏和 DI 中移除 Subtitles 引用
- SubtitleLabViewModel 及其依赖不再实例化

## 非功能需求

- 下载中 UI 不卡顿（进度报告在后台线程）
- 文件名自动去重（同名追加 `_1`、`_2`）
- 下载失败显示具体错误，不吞异常
- 保存目录跨进程重启记忆（记入项目配置或用户设置）
