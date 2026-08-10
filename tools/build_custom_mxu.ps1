$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$cacheRoot = Join-Path $projectRoot '.cache'
$sourceDir = Join-Path $cacheRoot 'mxu-v2.1.3'
$patchFile = Join-Path $PSScriptRoot 'mxu-v2.1.3-log-retention.patch'

if (-not (Test-Path -LiteralPath $patchFile -PathType Leaf)) {
    throw "Missing MXU patch: $patchFile"
}

if (-not (Test-Path -LiteralPath $sourceDir)) {
    New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
    git clone --depth 1 --branch v2.1.3 https://github.com/MistEO/MXU.git $sourceDir
    if ($LASTEXITCODE -ne 0) { throw 'Failed to clone MXU v2.1.3' }
} elseif (-not (Test-Path -LiteralPath (Join-Path $sourceDir '.git') -PathType Container)) {
    throw "Refusing non-MXU Git workspace: $sourceDir"
}

Push-Location $sourceDir
try {
    $head = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne '353c674b6aea4e7da617e4cb882effa744c1e05e') {
        throw "MXU baseline mismatch; expected v2.1.3, got $head"
    }

    $ErrorActionPreference = 'SilentlyContinue'
    git apply --check $patchFile 2>$null
    $canApply = $LASTEXITCODE -eq 0
    $ErrorActionPreference = 'Stop'
    if ($canApply) {
        git apply $patchFile
        if ($LASTEXITCODE -ne 0) { throw 'Failed to apply MXU log-retention patch' }
    } else {
        $ErrorActionPreference = 'SilentlyContinue'
        git apply --reverse --check $patchFile 2>$null
        $alreadyApplied = $LASTEXITCODE -eq 0
        $ErrorActionPreference = 'Stop'
        if (-not $alreadyApplied) {
            throw 'MXU workspace is neither clean nor already patched; inspect local changes'
        }
    }

    pnpm install
    if ($LASTEXITCODE -ne 0) { throw 'Failed to install MXU frontend dependencies' }
    pnpm tauri build --target x86_64-pc-windows-msvc --no-bundle
    if ($LASTEXITCODE -ne 0) { throw 'Failed to build custom MXU' }
} finally {
    Pop-Location
}

$result = Join-Path $sourceDir 'src-tauri\target\x86_64-pc-windows-msvc\release\mxu.exe'
if (-not (Test-Path -LiteralPath $result -PathType Leaf)) {
    throw "Build finished without expected executable: $result"
}
Write-Host "Custom MXU built: $result"
