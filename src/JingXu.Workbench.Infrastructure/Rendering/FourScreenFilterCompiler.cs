using System.Globalization;
using System.Text;
using JingXu.Workbench.Domain.Effects;

namespace JingXu.Workbench.Infrastructure.Rendering;

/// <summary>编译独立的四屏画面链，输出画布大小保持不变，音频由主轨处理。</summary>
internal static class FourScreenFilterCompiler
{
    public static string Compile(
        FourScreenClipSelection selection,
        int targetWidth,
        int targetHeight,
        bool featherEnabled,
        int featherPixels,
        string durationSeconds,
        string fpsText,
        IReadOnlyDictionary<FourScreenPosition, string> auxiliaryLabels)
    {
        var clipIndex = selection.ClipIndex;
        var prefix = $"fs{clipIndex}";
        var builder = new StringBuilder();
        var cells = selection.Cells.OrderBy(cell => cell.Position).ToArray();
        var leftWidth = targetWidth / 2;
        var rightWidth = targetWidth - leftWidth;
        var topHeight = targetHeight / 2;
        var bottomHeight = targetHeight - topHeight;
        var blendX = featherEnabled ? ResolveFeatherPixels(leftWidth, rightWidth, featherPixels) : 0;
        var blendY = featherEnabled ? ResolveFeatherPixels(topHeight, bottomHeight, featherPixels) : 0;

        // 同源同尺寸先缩放裁切一次再分流，避免当前片段在四格中重复执行相同的像素变换。
        foreach (var source in cells.GroupBy(
            cell => auxiliaryLabels.ContainsKey(cell.Position) ? Path.GetFullPath(cell.SourceAsset.Path) : string.Empty,
            StringComparer.OrdinalIgnoreCase))
        {
            var sourceCells = source.ToArray();
            var sourceLabel = $"v{clipIndex}fit";
            if (auxiliaryLabels.TryGetValue(sourceCells[0].Position, out var inputLabel))
            {
                sourceLabel = $"{prefix}source{(int)sourceCells[0].Position}";
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{inputLabel}]fps={fpsText},trim=duration={durationSeconds},setpts=PTS-STARTPTS,setsar=1[{sourceLabel}];");
                // 兼容传入独立标签的调用方；生产编译器为同源格子复用标签，不会生成这些冗余支路。
                foreach (var unusedLabel in sourceCells.Select(cell => auxiliaryLabels[cell.Position]).Distinct().Skip(1))
                {
                    builder.Append(CultureInfo.InvariantCulture, $"[{unusedLabel}]trim=duration={durationSeconds},nullsink;");
                }
            }

            var sizes = sourceCells.GroupBy(cell => (
                Width: ((int)cell.Position % 2 == 0 ? leftWidth : rightWidth) + blendX,
                Height: ((int)cell.Position < 2 ? topHeight : bottomHeight) + blendY)).ToArray();
            if (sizes.Length > 1)
            {
                builder.Append(CultureInfo.InvariantCulture, $"[{sourceLabel}]split={sizes.Length}");
                foreach (var size in sizes)
                {
                    builder.Append(CultureInfo.InvariantCulture, $"[{prefix}size{(int)size.First().Position}]");
                }

                builder.Append(';');
            }

            foreach (var size in sizes)
            {
                var resizedCells = size.ToArray();
                var input = sizes.Length == 1 ? sourceLabel : $"{prefix}size{(int)resizedCells[0].Position}";
                var (width, height) = size.Key;
                // scale 后再次限定 RGB，防止下游 xstack 协商成 4:2:0 后 crop 把奇数格子尺寸取偶数。
                builder.Append(CultureInfo.InvariantCulture,
                    $"[{input}]format=rgba,scale={width}:{height}:force_original_aspect_ratio=increase," +
                    $"format=rgba,crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,setsar=1");
                if (resizedCells.Length > 1)
                {
                    builder.Append(CultureInfo.InvariantCulture, $",split={resizedCells.Length}");
                }

                foreach (var cell in resizedCells)
                {
                    builder.Append(CultureInfo.InvariantCulture, $"[{prefix}cell{(int)cell.Position}]");
                }

                builder.Append(';');
            }
        }

        if (blendX == 0 && blendY == 0)
        {
            builder.Append(CultureInfo.InvariantCulture,
                $"[{prefix}cell0][{prefix}cell1][{prefix}cell2][{prefix}cell3]" +
                $"xstack=inputs=4:layout=0_0|{leftWidth}_0|0_{topHeight}|{leftWidth}_{topHeight}:shortest=1,format=yuv420p[v{clipIndex}];");
            return builder.ToString();
        }

        for (var row = 0; row < 2; row++)
        {
            if (blendX == 0)
            {
                builder.Append(CultureInfo.InvariantCulture, $"[{prefix}cell{row * 2}][{prefix}cell{row * 2 + 1}]hstack=inputs=2:shortest=1[{prefix}row{row}];");
                continue;
            }

            var rowHeight = (row == 0 ? topHeight : bottomHeight) + blendY;
            builder.Append(CultureInfo.InvariantCulture,
                $"[{prefix}cell{row * 2 + 1}]pad={targetWidth}:{rowHeight}:{leftWidth - blendX}:0:color=black[{prefix}row{row}base];");
            AppendFeatherMask(builder, $"{prefix}cell{row * 2}", $"{prefix}row{row}fade",
                leftWidth + blendX, rowHeight, "X", leftWidth + blendX, blendX * 2, fpsText);
            builder.Append(CultureInfo.InvariantCulture,
                $"[{prefix}row{row}base][{prefix}row{row}fade]overlay=0:0:format=rgb:shortest=1[{prefix}row{row}];");
        }

        if (blendY == 0)
        {
            builder.Append(CultureInfo.InvariantCulture, $"[{prefix}row0][{prefix}row1]vstack=inputs=2:shortest=1,format=yuv420p[v{clipIndex}];");
            return builder.ToString();
        }

        // 先横向互补混合，再纵向互补混合；交点四格权重为两轴权重乘积，总和恒为 1。
        builder.Append(CultureInfo.InvariantCulture,
            $"[{prefix}row1]format=rgba,pad={targetWidth}:{targetHeight}:0:{topHeight - blendY}:color=black[{prefix}base];");
        AppendFeatherMask(builder, $"{prefix}row0", $"{prefix}topfade",
            targetWidth, topHeight + blendY, "Y", topHeight + blendY, blendY * 2, fpsText);
        builder.Append(CultureInfo.InvariantCulture,
            $"[{prefix}base][{prefix}topfade]overlay=0:0:format=rgb:shortest=1,format=yuv420p[v{clipIndex}];");
        return builder.ToString();
    }

    internal static int ResolveFeatherPixels(int firstCellSize, int secondCellSize, int requestedPixels) =>
        Math.Clamp(requestedPixels, 0, Math.Min(firstCellSize, secondCellSize) / 3);

    private static void AppendFeatherMask(
        StringBuilder builder, string sourceLabel, string outputLabel,
        int maskWidth, int maskHeight, string axis, int end, int featherWidth, string fpsText)
    {
        // 蒙版与时间无关，只计算一帧灰度；alphamerge 缓存末帧，由主视频时间轴决定输出结束。
        builder.Append(CultureInfo.InvariantCulture,
            $"nullsrc=size={maskWidth}x{maskHeight}:rate={fpsText},format=gray,trim=end_frame=1," +
            $"geq=lum='255*clip(({end}-{axis})/{featherWidth},0,1)'[{outputLabel}mask];" +
            $"[{sourceLabel}]format=rgba[{outputLabel}rgba];" +
            $"[{outputLabel}rgba][{outputLabel}mask]alphamerge=eof_action=repeat:repeatlast=1[{outputLabel}];");
    }
}
