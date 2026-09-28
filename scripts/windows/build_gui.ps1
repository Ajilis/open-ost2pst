param(
    [string]$OutputName = "OpenOST2PST"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $repoRoot

try {
    $pyInstallerArgs = @(
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", $OutputName,
        "--paths", "src",
        "--hidden-import", "pypff",
        "src/open_ost2pst/gui.py"
    )

    python -m PyInstaller @pyInstallerArgs

    $exe = Join-Path $repoRoot "dist\$OutputName.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "PyInstaller did not create $exe"
    }

    Write-Host "Built: $exe"
    Get-FileHash -LiteralPath $exe -Algorithm SHA256
}
finally {
    Pop-Location
}
