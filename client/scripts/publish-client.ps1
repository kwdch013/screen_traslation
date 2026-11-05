<#
.SYNOPSIS
  Windowsクライアントを win-x64 の自己完結形式でpublishし、配布物 (zip・SHA256SUMS・manifest) を作る。

.DESCRIPTION
  再現可能なビルドの入口。CIと手元で同じコマンドを使う。署名は行わない (署名証明書は別途判断)。
  配布先に .NET SDK・Python・翻訳モデルは不要。ビルド機には .NET SDK (global.json の版) と Python 3 が必要。

.EXAMPLE
  pwsh client/scripts/publish-client.ps1 -Version 1.0.0 -OutputDir artifacts
#>
param(
	[Parameter(Mandatory = $true)][string]$Version,
	[string]$OutputDir = "artifacts",
	[string]$Commit = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($Version -notmatch '^\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$') {
	throw "版は 1.2.3 または 1.2.3-rc.1 の形式で指定してください。"
}

$clientRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $clientRoot "src/ScreenTranslation.Windows/ScreenTranslation.Windows.csproj"
$publishDir = Join-Path $OutputDir "publish-$Version"
$packageDir = Join-Path $OutputDir "package"

if (Test-Path $publishDir) { Remove-Item -Recurse -Force $publishDir }
if (Test-Path $packageDir) { Remove-Item -Recurse -Force $packageDir }

# DebugType=none: pdbにはビルド環境の絶対パスが入るため配布しない
dotnet publish $project -c Release -r win-x64 --self-contained true `
	-p:Version=$Version -p:DebugType=none -p:DebugSymbols=false `
	-p:PublishReadyToRun=false -p:ContinuousIntegrationBuild=true -o $publishDir
if ($LASTEXITCODE -ne 0) { throw "dotnet publish に失敗しました。" }

$python = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
$packager = Join-Path $PSScriptRoot "package_client.py"
$packageArgs = @(
	$packager, "package",
	"--publish-dir", $publishDir,
	"--output-dir", $packageDir,
	"--version", $Version,
	"--notices", (Join-Path $clientRoot "publish/THIRD-PARTY-NOTICES.txt"),
	"--readme", (Join-Path $clientRoot "publish/README.txt")
)
if ($Commit) { $packageArgs += @("--commit", $Commit) }
& $python @packageArgs
if ($LASTEXITCODE -ne 0) { throw "配布物の生成・検証に失敗しました。" }

# 起動入口の版 (ProductVersion) が指定の版と一致することを確認する
$exe = Join-Path $publishDir "ScreenTranslation.Windows.exe"
$productVersion = (Get-Item $exe).VersionInfo.ProductVersion
if ($productVersion -ne $Version) {
	throw "起動入口の ProductVersion ($productVersion) が指定の版 ($Version) と一致しません。"
}
Write-Host "配布物: $packageDir (版 $Version)"
