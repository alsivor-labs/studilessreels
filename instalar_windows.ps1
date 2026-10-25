$ErrorActionPreference = 'Stop'
Write-Host 'Histórias Studio - Preparação do ambiente' -ForegroundColor Green
function Has-Command($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }
if (-not (Has-Command 'python') -and -not (Has-Command 'py')) {
    Write-Host 'Python não encontrado. Instale Python 3.10+ e execute este script novamente.' -ForegroundColor Yellow
    if (Has-Command 'winget') { winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements }
    exit 1
}
if (-not (Has-Command 'ffmpeg') -or -not (Has-Command 'ffprobe')) {
    Write-Host 'FFmpeg/ffprobe não encontrados. Tentando instalar com winget...' -ForegroundColor Yellow
    if (Has-Command 'winget') {
        winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
        Write-Host 'Se o FFmpeg não aparecer, feche e reabra o PowerShell para atualizar o PATH.' -ForegroundColor Yellow
    } else {
        Write-Host 'winget não encontrado. Instale FFmpeg manualmente: https://ffmpeg.org/download.html' -ForegroundColor Yellow
    }
} else { Write-Host 'FFmpeg e ffprobe detectados.' -ForegroundColor Green }
foreach ($item in @(@('ComfyUI','http://127.0.0.1:8188/system_stats'),@('Ollama','http://127.0.0.1:11434/api/tags'),@('VoiceStudio','http://127.0.0.1:3900/health'))) {
    try { $null = Invoke-WebRequest -Uri $item[1] -UseBasicParsing -TimeoutSec 3; Write-Host "$($item[0]): conectado" -ForegroundColor Green }
    catch { Write-Host "$($item[0]): indisponível. Abra o aplicativo antes de gerar." -ForegroundColor Yellow }
}
Write-Host 'Preparação concluída. Para iniciar: python server.py' -ForegroundColor Green
