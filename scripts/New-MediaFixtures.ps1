#requires -Version 5.1
<#
.SYNOPSIS
Generate six lavfi test clips for M2 media integration tests.
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory = "",
    [int]$DurationSeconds = 30,
    [string]$FfmpegPath = ""
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $PSScriptRoot '..\tests\JingXu.Workbench.IntegrationTests\Media\Fixtures\generated'
}

function Resolve-FfmpegPath {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath) -and (Test-Path -LiteralPath $ExplicitPath)) {
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }

    throw "FFmpeg not found. Install FFmpeg or pass -FfmpegPath."
}

function New-ToneClip {
    param(
        [string]$Executable,
        [string]$Destination,
        [int]$SequenceIndex,
        [string]$Color,
        [int]$FrequencyHz,
        [int]$Seconds
    )

    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }

    $colorInput = "color=c=${Color}:size=320x240:rate=24:duration=${Seconds}"
    $audioInput = "sine=frequency=${FrequencyHz}:sample_rate=48000:duration=${Seconds}"
    $metadata = "title=seq-${SequenceIndex}"

    & $Executable -y `
        -f lavfi -i $colorInput `
        -f lavfi -i $audioInput `
        -shortest `
        -c:v libx264 -pix_fmt yuv420p `
        -c:a aac -b:a 128k `
        -metadata $metadata `
        $Destination | Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to generate $Destination (exit code $LASTEXITCODE)."
    }
}

$ffmpeg = Resolve-FfmpegPath -ExplicitPath $FfmpegPath
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$segments = @(
    @{ Index = 1; Color = 'red'; Frequency = 200 },
    @{ Index = 2; Color = 'green'; Frequency = 300 },
    @{ Index = 3; Color = 'blue'; Frequency = 400 },
    @{ Index = 4; Color = 'yellow'; Frequency = 500 },
    @{ Index = 5; Color = 'magenta'; Frequency = 600 },
    @{ Index = 6; Color = 'cyan'; Frequency = 700 }
)

foreach ($segment in $segments) {
    $target = Join-Path $OutputDirectory ("{0}.mp4" -f $segment.Index)
    Write-Host "Generating $($segment.Index).mp4 ..."
    New-ToneClip -Executable $ffmpeg -Destination $target -SequenceIndex $segment.Index `
        -Color $segment.Color -FrequencyHz $segment.Frequency -Seconds $DurationSeconds
}

Write-Host "Fixtures written to $OutputDirectory"
