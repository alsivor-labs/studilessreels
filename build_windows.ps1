$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python 3.10+ não foi encontrado. Instale Python para criar a release de desenvolvimento.' }
$version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$version -lt [version]'3.10') { throw 'A build do Windows exige Python 3.10 ou superior.' }
& python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) { & python -m pip install --upgrade pyinstaller }
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível preparar PyInstaller.' }

$env:TEMP = Join-Path $PSScriptRoot 'build-native\pip-temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $PSScriptRoot 'build-native\pip-cache'
New-Item -ItemType Directory -Force $env:TEMP,$env:PIP_CACHE_DIR | Out-Null
$vendor = Join-Path $PSScriptRoot 'build-native\vendor'
if (-not (Test-Path (Join-Path $vendor 'webview\__init__.py'))) {
    & python -m pip install --no-build-isolation --no-cache-dir --target $vendor pywebview==6.2.1
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível preparar pywebview e WebView2 para a janela desktop.' }
}
New-Item -ItemType Directory -Force release-login | Out-Null
& python -m PyInstaller --clean --noconfirm --distpath release-login --workpath build-native HistoriasStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou ao gerar o executável.' }
Copy-Item README.md release-login\LEIA-ME.md -Force
Copy-Item docs\INSTALACAO_E_USO.md release-login\INSTALACAO_E_USO.md -Force
Compress-Archive -Path release-login\HistoriasStudio.exe,release-login\LEIA-ME.md,release-login\INSTALACAO_E_USO.md -DestinationPath release-login\HistoriasStudio-Windows-x64.zip -CompressionLevel Optimal -Force
Write-Host 'Release pronta em release-login\HistoriasStudio.exe e release-login\HistoriasStudio-Windows-x64.zip' -ForegroundColor Green