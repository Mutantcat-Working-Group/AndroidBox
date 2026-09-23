#!/usr/bin/env pwsh
# Install the Windows QEMU (and optionally NSIS) build prerequisites.
#
# The community Chocolatey feed is flaky from time to time - it once answered
# 504 while resolving the qemu package, which took the Windows display smoke
# test and the Windows installer build down with it. Every install therefore
# retries, and both tools fall back to their official upstream archives so a
# broken feed cannot fail the pipeline.

[CmdletBinding()]
param(
    [string]$QemuVersion = '2026.8.11',
    [string]$QemuSetupUrl = 'https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.exe',
    [string]$NsisZipUrl = 'https://prdownloads.sourceforge.net/nsis/nsis-3.12.zip?download',
    [switch]$IncludeNsis
)

$ErrorActionPreference = 'Stop'

function Install-ChocoPackage {
    param([Parameter(Mandatory = $true)][string]$Id, [string]$Version)

    # Keep this a real array: a single-element array produced by an if
    # expression is unwrapped to a string, and splatting that string hands the
    # package id to Chocolatey one character at a time.
    $arguments = @($Id)
    if ($Version) { $arguments += "--version=$Version" }
    foreach ($attempt in 1..3) {
        Write-Host "Installing $($arguments -join ' ') (attempt $attempt of 3)"
        & choco install @arguments --no-progress -y
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "::warning::$Id install failed with exit code $LASTEXITCODE; retrying"
        Start-Sleep -Seconds 20
    }
    throw "Chocolatey could not install $Id"
}

function Add-ToPath {
    param([Parameter(Mandatory = $true)][string]$Directory)
    Write-Host "Adding $Directory to PATH"
    $Directory | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
}

$qemuDirectory = 'C:\Program Files\qemu'
$qemuBinary = Join-Path $qemuDirectory 'qemu-system-x86_64.exe'

Install-ChocoPackage -Id 'qemu' -Version $QemuVersion

if (-not (Test-Path $qemuBinary)) {
    # The pinned package may be missing from the feed as well, so fall back to
    # the same upstream build the package itself ships.
    $setup = Join-Path $env:RUNNER_TEMP 'qemu-w64-setup.exe'
    Write-Host "::notice::QEMU is missing after Chocolatey, falling back to $QemuSetupUrl"
    Invoke-WebRequest -Uri $QemuSetupUrl -OutFile $setup -TimeoutSec 900
    $process = Start-Process -FilePath $setup -ArgumentList '/S' -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "QEMU installer exited with $($process.ExitCode)" }
    if (-not (Test-Path $qemuBinary)) { throw "QEMU is still missing at $qemuBinary" }
}

if (-not ((Test-Path (Join-Path $qemuDirectory 'share')) -or (Test-Path (Join-Path $qemuDirectory 'share' 'qemu')))) {
    throw "QEMU data files are missing under $qemuDirectory"
}
Add-ToPath -Directory $qemuDirectory

if ($IncludeNsis) {
    Install-ChocoPackage -Id 'nsis'
    if (Get-Command makensis -ErrorAction SilentlyContinue) {
        Write-Host 'makensis is available through Chocolatey'
    } else {
        # Writing to GITHUB_PATH does not refresh PATH in this process, so the
        # extracted binary is checked on disk rather than with Get-Command.
        $nsisDirectory = Join-Path $env:RUNNER_TEMP 'nsis'
        $archive = Join-Path $env:RUNNER_TEMP 'nsis.zip'
        Write-Host "::notice::makensis is missing after Chocolatey, falling back to $NsisZipUrl"
        Invoke-WebRequest -Uri $NsisZipUrl -OutFile $archive -TimeoutSec 900
        Expand-Archive -Path $archive -DestinationPath $nsisDirectory -Force
        $makensis = Get-ChildItem -Path $nsisDirectory -Filter 'makensis.exe' -File -Recurse |
            Select-Object -First 1
        if (-not $makensis) { throw "NSIS archive did not contain makensis.exe" }
        Add-ToPath -Directory $makensis.DirectoryName
    }
}
