#requires -Version 5.1
<#
.SYNOPSIS
生成镜序工作台的应用图标（互锁取景框标记）。
输出多尺寸 PNG 压缩的 .ico 到 src/JingXu.Workbench/Assets/AppIcon.ico。
#>
[CmdletBinding()]
param(
    [string]$OutputPath = (Join-Path $PSScriptRoot '..\src\JingXu.Workbench\Assets\AppIcon.ico')
)

Add-Type -AssemblyName System.Drawing

function New-MarkPng {
    param([int]$Size)

    $bmp = New-Object System.Drawing.Bitmap($Size, $Size)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)

    $unit = $Size / 24.0
    $stroke = [Math]::Max(2.0, 3.4 * $unit)

    $primary = [System.Drawing.Color]::FromArgb(255, 0x24, 0x6B, 0x59)
    $accent = [System.Drawing.Color]::FromArgb(255, 0x1C, 0x57, 0x48)

    # 两个互锁的圆角取景框
    $r1 = New-Object System.Drawing.RectangleF(($unit*3), ($unit*3), ($unit*11), ($unit*11))
    $r2 = New-Object System.Drawing.RectangleF(($unit*10), ($unit*10), ($unit*11), ($unit*11))
    $radius = 3.0 * $unit

    foreach ($pair in @(@($r1, $primary), @($r2, $accent))) {
        $rect = $pair[0]
        $color = $pair[1]
        $path = New-Object System.Drawing.Drawing2D.GraphicsPath
        $d = $radius * 2
        $path.AddArc($rect.X, $rect.Y, $d, $d, 180, 90)
        $path.AddArc($rect.Right - $d, $rect.Y, $d, $d, 270, 90)
        $path.AddArc($rect.Right - $d, $rect.Bottom - $d, $d, $d, 0, 90)
        $path.AddArc($rect.X, $rect.Bottom - $d, $d, $d, 90, 90)
        $path.CloseFigure()
        $pen = New-Object System.Drawing.Pen($color, $stroke)
        $pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
        $g.DrawPath($pen, $path)
        $pen.Dispose()
        $path.Dispose()
    }

    $g.Dispose()

    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    return , $ms.ToArray()
}

$sizes = @(16, 32, 48, 64, 128, 256)
$pngs = @()
foreach ($s in $sizes) { $pngs += , (New-MarkPng -Size $s) }

$dir = Split-Path -Parent $OutputPath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

$fs = [System.IO.File]::Create($OutputPath)
$bw = New-Object System.IO.BinaryWriter($fs)
try {
    # ICONDIR
    $bw.Write([UInt16]0)              # reserved
    $bw.Write([UInt16]1)              # type: icon
    $bw.Write([UInt16]$sizes.Count)   # image count

    $offset = 6 + (16 * $sizes.Count)
    for ($i = 0; $i -lt $sizes.Count; $i++) {
        $s = $sizes[$i]
        $len = $pngs[$i].Length
        $dim = if ($s -ge 256) { 0 } else { $s }
        $bw.Write([Byte]$dim)         # width
        $bw.Write([Byte]$dim)         # height
        $bw.Write([Byte]0)            # palette
        $bw.Write([Byte]0)            # reserved
        $bw.Write([UInt16]1)          # color planes
        $bw.Write([UInt16]32)         # bits per pixel
        $bw.Write([UInt32]$len)       # size of PNG data
        $bw.Write([UInt32]$offset)    # offset
        $offset += $len
    }

    foreach ($png in $pngs) { $bw.Write($png) }
}
finally {
    $bw.Flush(); $bw.Dispose(); $fs.Dispose()
}

Write-Host "AppIcon.ico written to $OutputPath ($([Math]::Round((Get-Item $OutputPath).Length/1KB,1)) KB)"
