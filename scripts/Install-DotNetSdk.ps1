[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$modulePath = Join-Path $PSScriptRoot 'Install-DotNetSdk.Core.psm1'
Import-Module -Name $modulePath -Force

Install-DotNetSdk
