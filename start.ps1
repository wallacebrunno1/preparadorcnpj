# ==============================================================================
# SDSuper - Web Launcher de 1 Linha (PowerShell)
# Execução instantânea em servidores Windows sem necessidade de instalação
# Uso no cliente: irm https://is.gd/sdsuper | iex
# ==============================================================================

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Host.UI.RawUI.WindowTitle = "SDSuper - Launcher de Troca de CNPJ & Permissoes"

Write-Host ""
Write-Host " =====================================================================" -ForegroundColor DarkCyan
Write-Host "  [SDSUPER] UTILITARIO DE FILIAIS & TROCA DE CNPJ (STITCH DARK UI)    " -ForegroundColor Cyan
Write-Host " =====================================================================" -ForegroundColor DarkCyan
Write-Host ""

$workDir = "$env:LOCALAPPDATA\SDSuper_Util"
if (-not (Test-Path $workDir)) {
    New-Item -ItemType Directory -Path $workDir -Force | Out-Null
}

$exePath = Join-Path $workDir "Utilitario_SDSuper.exe"
$port = 8089
$url = "http://localhost:$port"

# URL de download do executavel hospedado no GitHub Releases ou servidor
# Substitua pela sua URL final quando publicar no GitHub:
$downloadUrl = "https://raw.githubusercontent.com/wallacebrunno1/preparadorcnpj/main/Utilitario_SDSuper.exe"

# Verifica se o processo ja esta em execucao
$running = Get-Process "Utilitario_SDSuper" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host " [*] O Utilitario ja esta em execucao! Abrindo no navegador..." -ForegroundColor Green
    Start-Process $url
    exit
}

# Se o executavel nao existir localmente, faz o download com barra de progresso
if (-not (Test-Path $exePath)) {
    Write-Host " [*] Baixando versao mais recente do Utilitario..." -ForegroundColor Yellow
    Write-Host "     Destino: $exePath" -ForegroundColor DarkGray
    
    try {
        $wc = New-Object System.Net.WebClient
        # Download direto
        $wc.DownloadFile($downloadUrl, $exePath)
        Write-Host " [OK] Download concluido com sucesso!" -ForegroundColor Green
    }
    catch {
        Write-Host " [!] Nao foi possivel baixar automaticamente pela nuvem." -ForegroundColor Red
        Write-Host "     Erro: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "     Tentando carregar arquivo local se disponivel..." -ForegroundColor Yellow
        
        # Tenta pasta atual
        $localExe = Join-Path (Get-Location) "Utilitario_SDSuper.exe"
        if (Test-Path $localExe) {
            $exePath = $localExe
        } else {
            Write-Host " [ERRO] Utilitario_SDSuper.exe nao encontrado. Verifique a conexao de internet." -ForegroundColor Red
            Read-Host "Pressione ENTER para sair..."
            exit
        }
    }
}

Write-Host " [*] Iniciando servidor do Utilitario na porta $port..." -ForegroundColor Cyan

# Inicia o processo em segundo plano
$proc = Start-Process -FilePath $exePath -WorkingDirectory $workDir -PassThru -WindowStyle Minimized

Write-Host " [*] Aguardando inicializacao do servidor..." -ForegroundColor DarkGray
$tentativas = 0
$pronto = $false

while ($tentativas -lt 15 -and -not $pronto) {
    Start-Sleep -Milliseconds 600
    try {
        $tcp = Test-NetConnection -ComputerName "127.0.0.1" -Port $port -WarningAction SilentlyContinue
        if ($tcp.TcpTestSucceeded) {
            $pronto = $true
        }
    } catch {
        # Fallback para versoes antigas de PowerShell sem Test-NetConnection
        try {
            $sock = New-Object System.Net.Sockets.TcpClient
            $sock.Connect("127.0.0.1", $port)
            $pronto = $true
            $sock.Close()
        } catch { }
    }
    $tentativas++
}

Write-Host " [OK] Servidor ativo! Abrindo interface Stitch Dark no navegador..." -ForegroundColor Green
Write-Host "      Link: $url" -ForegroundColor White
Write-Host ""
Write-Host " Pressione qualquer tecla nesta janela para encerrar o utilitario." -ForegroundColor DarkGray

Start-Process $url

# Aguarda o tecnico terminar para fechar
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# Encerra o utilitario ao fechar a janela
Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
Write-Host " [*] Utilitario finalizado. Obrigado!" -ForegroundColor Cyan
Start-Sleep -Seconds 1
