$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python 3.10+ não foi encontrado. Instale Python para criar a release de desenvolvimento.' }
$version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$version -lt [version]'3.10') { throw 'A build do Windows exige Python 3.10 ou superior.' }
& python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) { & python -m pip install --upgrade pyinstaller }
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível preparar PyInstaller.' }

New-Item -ItemType Directory -Force release | Out-Null
& python -m PyInstaller --clean --noconfirm --distpath release --workpath build HistoriasStudio.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou ao gerar o executável.' }
Copy-Item README.md release\LEIA-ME.md -Force
Copy-Item docs\INSTALACAO_E_USO.md release\INSTALACAO_E_USO.md -Force
Compress-Archive -Path release\HistoriasStudio.exe,release\LEIA-ME.md,release\INSTALACAO_E_USO.md -DestinationPath release\HistoriasStudio-Windows-x64.zip -CompressionLevel Optimal -Force
Write-Host 'Release pronta em release\HistoriasStudio.exe e release\HistoriasStudio-Windows-x64.zip' -ForegroundColor Green