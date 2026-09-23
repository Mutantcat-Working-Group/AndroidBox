#!/usr/bin/env pwsh
# Install the Windows QEMU (and optionally NSIS) build prerequisites.
#
# The community Chocolatey feed intermittently answers 504, which used to fail
# both the display smoke test and the Windows installer build. Every install is
# therefore retried, and QEMU falls back to the upstream Windows installer so a
# flaky feed cannot take the CI down.

[CmdletBinding()]
param(
    [string]$QemuVersion = '2026.8.11',
    [string]$QemuSetupUrl = 'https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.exe',
    [switch]$IncludeNsis
)

$ErrorActionPreference = 'Stop'

function Install-ChocoPackage {
    param([Parameter(Mandatory = $true)][string]$Id, [string]$Version)

    $specifier = if ($Version) { @($Id, "--version=$Version") } else { @($Id) }
    foreach ($attempt in 1..3) {
        Write-Host "Installing $($specifier -join ' ') (attempt $attempt of 3)"
        & choco install @specifier --no-progress -y
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "::warning::$Id install failed with exit code $LASTEXITCODE; retrying"
        Start-Sleep -Seconds 20
    }
    throw "Chocolatey could not install $Id"
}

$qemuDirectory = 'C:\Program Files\qemu'
$qemuBinary = Join-Path $qemuDirectory 'qemu-system-x86_64.exe'

Install-ChocoPackage -Id 'qemu' -Version $QemuVersion

if (-not (Test-Path $qemuBinary)) {
    # The pinned package may be missing from the feed as well, so fall back to
    # the same upstream build the package itself ships.
    $setup = Join-Path $env:RUNNER_TEMP 'qemu-w64-setup.exe'
    Write-Host "::notice::Falling back to $QemuSetupUrl"
    Invoke-WebRequest -Uri $QemuSetupUrl -OutFile $setup -TimeoutSec 900
    $process = Start-Process -FilePath $setup -ArgumentList '/S' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "QEMU installer exited with $($process.ExitCode)" }
    if (-not (Test-Path $qemuBinary)) { throw "QEMU is still missing at $qemuBinary" }
}

if (-not (Test-Path (Join-Path $qemuDirectory 'share'))) {
    throw "QEMU data files are missing under $qemuDirectory"
}
$qemuDirectory | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append

if ($IncludeNsis) {
    $nsisDirectory = 'C:\Program Files\NSIS'
    Install-ChocoPackage -Id 'nsis'
    if (-not (Test-Path (Join-Path $nsisDirectory 'makensis.exe'))) {
        throw "NSIS is missing under $nsisDirectory"
    }
    $nsisDirectory | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
}
