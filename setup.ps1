# One-command setup for Windows (PowerShell 5.1 or 7). Double-click setup.bat, or run:
#   powershell -ExecutionPolicy Bypass -File setup.ps1 [-NoStart] [-Provider claude_code|anthropic|none]
#                                                     [-SkipTests] [-SkipModelDownload] [-Yes]
# Installs Python 3.14.10 if needed (winget), creates .venv, installs the locked dependencies,
# prepares .env, picks a model provider, downloads the embedding model, runs the self-tests
# and starts the app. Re-running is safe.
param(
    [switch]$NoStart,
    [ValidateSet('', 'claude_code', 'anthropic', 'none')][string]$Provider = '',
    [switch]$SkipTests,
    [switch]$SkipModelDownload,
    [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$PythonVersion = '3.14.10'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor White }
function Ok($text)   { Write-Host "    [ok] $text" -ForegroundColor Green }
function Warn($text) { Write-Host "    [!] $text" -ForegroundColor Yellow }
function Stop-Setup($text) { Write-Host "`nSetup stopped: $text" -ForegroundColor Red; exit 1 }
function Confirm-Step($question) {
    if ($Yes) { return $true }
    $reply = Read-Host "    $question [Y/n]"
    return ($reply -eq '' -or $reply -match '^[Yy]')
}
function Get-PyVersion($exe, $extra = @()) {
    try { return (& $exe @extra -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null) } catch { return $null }
}

if (-not (Test-Path 'requirements.lock.txt') -or -not (Test-Path 'api\main.py')) {
    Stop-Setup 'run this script from the project folder (it contains README.md).'
}

# ------------------------------------------------------------------ 1. Python
Step "1/7  Python $PythonVersion"
$Py = $null; $PyArgs = @()
if ((Get-PyVersion '.venv\Scripts\python.exe') -eq $PythonVersion) { $Py = (Resolve-Path '.venv\Scripts\python.exe').Path }
elseif ((Get-Command py -ErrorAction SilentlyContinue) -and ((Get-PyVersion 'py' @('-3.14')) -like '3.14.*')) { $Py = 'py'; $PyArgs = @('-3.14') }
elseif ((Get-Command python -ErrorAction SilentlyContinue) -and ((Get-PyVersion 'python') -like '3.14.*')) { $Py = 'python' }
if (-not $Py) {
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Confirm-Step "Python 3.14 was not found. Install Python $PythonVersion with winget?")) {
        winget install --id Python.Python.3.14 --version $PythonVersion --exact --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            Warn "exact $PythonVersion not offered by winget; installing the latest 3.14"
            winget install --id Python.Python.3.14 --exact --scope user --accept-package-agreements --accept-source-agreements
        }
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        if ((Get-Command py -ErrorAction SilentlyContinue) -and ((Get-PyVersion 'py' @('-3.14')) -like '3.14.*')) { $Py = 'py'; $PyArgs = @('-3.14') }
    }
}
if (-not $Py) { Stop-Setup "install Python $PythonVersion from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run setup again." }
$Found = Get-PyVersion $Py $PyArgs
if ($Found -ne $PythonVersion) { Warn "using Python $Found; the team standard is $PythonVersion" }
Ok "using $Py $PyArgs ($Found)"

# ------------------------------------------------------------------ 2. venv
Step '2/7  Virtual environment (.venv)'
$Vpy = Join-Path $Root '.venv\Scripts\python.exe'
if ((Test-Path $Vpy) -and ((Get-PyVersion $Vpy) -ne $Found)) {
    Warn ".venv uses another Python; recreating it"
    Remove-Item -Recurse -Force (Join-Path $Root '.venv')
}
if (-not (Test-Path $Vpy)) { & $Py @PyArgs -m venv .venv; Ok 'created .venv' } else { Ok '.venv already exists' }

# ------------------------------------------------------------------ 3. dependencies
Step '3/7  Dependencies (requirements.lock.txt, about 1 GB on first install)'
& $Vpy -m pip install --quiet --upgrade pip
& $Vpy -m pip install --quiet -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { Stop-Setup 'dependency install failed (see above). Tell the setup owner; do not change versions.' }
& $Vpy -m pip check | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Setup 'pip check reported broken requirements.' }
Ok 'dependencies installed, pip check clean'

# ------------------------------------------------------------------ 4. .env and model
Step '4/7  Local settings (.env) and AI model'
if (-not (Test-Path '.env')) {
    if (Test-Path '.env.example') { Copy-Item '.env.example' '.env' } else { New-Item '.env' -ItemType File | Out-Null }
    Ok 'created .env from .env.example'
} else { Ok '.env already exists (left as is)' }
function Get-EnvValue($name) {
    return (& $Vpy -c "import sys; from dotenv import dotenv_values; print(dotenv_values('.env').get(sys.argv[1]) or '')" $name).Trim()
}
function Set-EnvValue($name, $value) {
    & $Vpy -c "import sys; from dotenv import set_key; set_key('.env', sys.argv[1], sys.argv[2], quote_mode='never')" $name $value | Out-Null
}
$Current = Get-EnvValue 'EXPENSE_MODEL_PROVIDER'
$HasClaude = [bool](Get-Command claude -ErrorAction SilentlyContinue)
if (-not $Provider) {
    if ($Current) { $Provider = $Current }
    elseif ($HasClaude) { $Provider = 'claude_code' }
    elseif ((Get-EnvValue 'ANTHROPIC_API_KEY') -or $env:ANTHROPIC_API_KEY) { $Provider = 'anthropic' }
    elseif (-not $Yes) {
        Write-Host '    Claude Code was not found on this machine. Policy chat needs a model:'
        Write-Host '      1) Enter a Claude API key now (saved only in .env on this machine)'
        Write-Host '      2) Continue without AI chat (everything else works; add a key later)'
        $choice = Read-Host '    Choose 1 or 2 [2]'
        if ($choice -eq '1') {
            $secure = Read-Host '    Paste ANTHROPIC_API_KEY (input hidden)' -AsSecureString
            $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
            if ($key) { Set-EnvValue 'ANTHROPIC_API_KEY' $key; $Provider = 'anthropic' } else { $Provider = 'none' }
            Remove-Variable key, secure
        } else { $Provider = 'none' }
    } else { $Provider = 'none' }
}
if ($Provider -eq 'anthropic') { Set-EnvValue 'EXPENSE_MODEL_PROVIDER' 'anthropic' }
elseif ($Current -and $Current -ne 'claude_code') { Set-EnvValue 'EXPENSE_MODEL_PROVIDER' 'claude_code' }
switch ($Provider) {
    'claude_code' { if ($HasClaude) { Ok "model: Claude Code CLI. Run 'claude' once to sign in if you haven't." } else { Warn 'model: claude_code selected, but the claude CLI is not on PATH, so chat will show AI offline.' } }
    'anthropic'   { if ((Get-EnvValue 'ANTHROPIC_API_KEY') -or $env:ANTHROPIC_API_KEY) { Ok 'model: Claude API (key found)' } else { Warn 'model: anthropic selected, but ANTHROPIC_API_KEY is empty. Add it to .env, then restart.' } }
    'none'        { Warn 'model: none configured. Policy chat shows AI offline; claims, limits and documents work.' }
}

# ------------------------------------------------------------------ 5. embedding model
Step '5/7  Embedding model for document search'
if (-not $SkipModelDownload) {
    Write-Host '    Downloading BAAI/bge-small-en-v1.5 on first run (about 200 MB, then cached in runtime\models)...'
    $warm = "from core.context import build_context`nc = build_context(with_model=False)`nr = c.retriever`nprint('    mode=%s vectors=%d %s' % (r.mode, r.vector_count(), r.vector_error or ''))`nc.store.close()`nraise SystemExit(0 if r.mode == 'hybrid' or c.settings.embeddings.provider == 'none' else 3)"
    & $Vpy -c $warm
    if ($LASTEXITCODE -eq 0) { Ok 'hybrid search ready' } else { Warn 'embedding model unavailable (offline?). The app will use keyword search; re-run setup later.' }
} else { Warn 'skipped; the API downloads the model on first start' }

# ------------------------------------------------------------------ 6. self-test
Step '6/7  Self-test'
if (-not $SkipTests -and (Test-Path 'tests')) {
    New-Item -ItemType Directory -Force 'runtime' | Out-Null
    & $Vpy -m pytest -p no:warnings -p no:cacheprovider *> 'runtime\setup-tests.log'
    if ($LASTEXITCODE -ne 0) { Stop-Setup 'self-tests failed; see runtime\setup-tests.log' }
    Ok ((Get-Content 'runtime\setup-tests.log' | Select-Object -Last 1))
} else { Warn 'skipped' }

# ------------------------------------------------------------------ 7. start
Step '7/7  Start'
if (-not $NoStart) { & (Join-Path $Root 'run.ps1') } else { Ok 'setup complete. Start the app any time by double-clicking run.bat' }
