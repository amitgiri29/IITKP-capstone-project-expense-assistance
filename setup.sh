#!/usr/bin/env bash
# One-command setup for macOS and Linux: installs Python 3.14.10 if needed, creates .venv,
# installs the locked dependencies, prepares .env, picks a model provider, downloads the
# embedding model, runs the self-tests and starts the app.
#
#   bash setup.sh                      # set up and start (re-running is safe)
#   bash setup.sh --no-start           # set up only; start later with: bash run.sh
#   bash setup.sh --provider anthropic # claude_code | anthropic | none (no AI chat)
#   bash setup.sh --skip-tests --skip-model-download --yes
set -euo pipefail

PYTHON_VERSION="3.14.10"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

START=1; RUN_TESTS=1; WARM_MODEL=1; ASSUME_YES=0; PROVIDER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-start) START=0 ;;
    --skip-tests) RUN_TESTS=0 ;;
    --skip-model-download) WARM_MODEL=0 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --provider) shift; PROVIDER="${1:-}" ;;
    --provider=*) PROVIDER="${1#*=}" ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see bash setup.sh --help)"; exit 2 ;;
  esac
  shift
done
case "$PROVIDER" in ""|claude_code|anthropic|none) ;; *) echo "--provider must be claude_code, anthropic or none"; exit 2 ;; esac

bold() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mSetup stopped:\033[0m %s\n' "$*"; exit 1; }
interactive() { [ -t 0 ] && [ "$ASSUME_YES" = 0 ]; }
confirm() {  # confirm "question" -> 0 for yes. Non-interactive runs use --yes.
  if [ "$ASSUME_YES" = 1 ]; then return 0; fi
  if [ ! -t 0 ]; then return 1; fi
  local reply; read -r -p "    $1 [Y/n] " reply; [ -z "$reply" ] || [[ "$reply" =~ ^[Yy] ]]
}

[ -f requirements.lock.txt ] && [ -f api/main.py ] || die "run this script from the project folder (it contains README.md)."
case "$(uname -s)" in Darwin|Linux) ;; *) die "on Windows, double-click setup.bat or run: powershell -ExecutionPolicy Bypass -File setup.ps1" ;; esac

# ---------------------------------------------------------------- 1. Python 3.14.10
bold "1/7  Python $PYTHON_VERSION"
version_of() { "$1" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true; }
PY=""
for candidate in .venv/bin/python python3.14 "$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python3" python3; do
  if command -v "$candidate" >/dev/null 2>&1 && [ "$(version_of "$candidate")" = "$PYTHON_VERSION" ]; then
    PY="$(command -v "$candidate")"; break
  fi
done
if [ -z "$PY" ] && command -v uv >/dev/null 2>&1; then
  echo "    Installing Python $PYTHON_VERSION with uv (prebuilt, about 30 MB)…"
  uv python install "$PYTHON_VERSION" >/dev/null && PY="$(uv python find "$PYTHON_VERSION")"
fi
if [ -z "$PY" ] && command -v pyenv >/dev/null 2>&1; then
  echo "    Installing Python $PYTHON_VERSION with pyenv (compiles from source, a few minutes)…"
  pyenv install -s "$PYTHON_VERSION" && PY="$(pyenv root)/versions/$PYTHON_VERSION/bin/python3"
fi
if [ -z "$PY" ]; then
  echo "    Python $PYTHON_VERSION was not found, and neither uv nor pyenv is installed."
  if confirm "Install uv (Astral's Python installer, user-level, no admin rights) and use it to get Python $PYTHON_VERSION?"; then
    if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
      brew install uv
    else
      command -v curl >/dev/null 2>&1 || die "curl is needed to install uv. Install Python $PYTHON_VERSION yourself and re-run."
      curl -LsSf https://astral.sh/uv/install.sh | sh
      export PATH="$HOME/.local/bin:$PATH"
    fi
    uv python install "$PYTHON_VERSION" >/dev/null && PY="$(uv python find "$PYTHON_VERSION")"
  fi
fi
if [ -z "$PY" ]; then  # last resort: another 3.14 patch release works with the lockfile
  for candidate in python3.14 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && [[ "$(version_of "$candidate")" == 3.14.* ]]; then
      PY="$(command -v "$candidate")"; warn "using Python $(version_of "$PY"); the team standard is $PYTHON_VERSION"; break
    fi
  done
fi
[ -n "$PY" ] || die "install Python $PYTHON_VERSION (https://www.python.org/downloads/ or pyenv), then re-run bash setup.sh."
ok "using $PY"

# ---------------------------------------------------------------- 2. virtual environment
bold "2/7  Virtual environment (.venv)"
if [ -x .venv/bin/python ] && [ "$(version_of .venv/bin/python)" != "$(version_of "$PY")" ]; then
  warn ".venv uses Python $(version_of .venv/bin/python); recreating it with $(version_of "$PY")"
  rm -rf ./.venv
fi
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
  ok "created .venv"
else
  ok ".venv already exists"
fi
VPY="$ROOT/.venv/bin/python"

# ---------------------------------------------------------------- 3. dependencies
bold "3/7  Dependencies (requirements.lock.txt, about 1 GB on first install)"
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet -r requirements.lock.txt || die "dependency install failed (see above). Tell the setup owner; do not change versions."
"$VPY" -m pip check >/dev/null || die "pip check reported broken requirements."
ok "$( "$VPY" -m pip freeze | wc -l | tr -d ' ') packages installed, pip check clean"

# ---------------------------------------------------------------- 4. .env and model provider
bold "4/7  Local settings (.env) and AI model"
if [ ! -f .env ]; then
  if [ -f .env.example ]; then cp .env.example .env; else : > .env; fi
  ok "created .env from .env.example"
else
  ok ".env already exists (left as is)"
fi
chmod 600 .env 2>/dev/null || true

env_get() { "$VPY" - "$1" <<'PY'
import sys
from dotenv import dotenv_values
print(dotenv_values('.env').get(sys.argv[1]) or '')
PY
}
env_set() { "$VPY" - "$1" "$2" <<'PY'
import sys
from dotenv import set_key
set_key('.env', sys.argv[1], sys.argv[2], quote_mode='never')
PY
}

CURRENT="$(env_get EXPENSE_MODEL_PROVIDER)"
if [ -z "$PROVIDER" ]; then
  if [ -n "$CURRENT" ]; then
    PROVIDER="$CURRENT"
  elif command -v claude >/dev/null 2>&1; then
    PROVIDER="claude_code"
  elif [ -n "$(env_get ANTHROPIC_API_KEY)" ] || [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    PROVIDER="anthropic"
  elif interactive; then
    echo "    Claude Code was not found on this machine. Policy chat needs a model:"
    echo "      1) Enter a Claude API key now (saved only in .env on this machine)"
    echo "      2) Continue without AI chat (everything else works; add a key later)"
    read -r -p "    Choose 1 or 2 [2]: " choice
    if [ "${choice:-2}" = 1 ]; then
      read -r -s -p "    Paste ANTHROPIC_API_KEY (input hidden): " key; echo
      [ -n "$key" ] && env_set ANTHROPIC_API_KEY "$key" && PROVIDER="anthropic" || PROVIDER="none"
      unset key
    else
      PROVIDER="none"
    fi
  else
    PROVIDER="none"
  fi
fi
# Write the choice to .env only when it differs from the committed default (claude_code), so a
# re-run can still auto-detect. EXPENSE_MODEL_PROVIDER overrides config/settings.toml locally.
if [ "$PROVIDER" = anthropic ]; then env_set EXPENSE_MODEL_PROVIDER anthropic
elif [ -n "$CURRENT" ] && [ "$CURRENT" != claude_code ]; then env_set EXPENSE_MODEL_PROVIDER claude_code; fi
case "$PROVIDER" in
  claude_code)
    if command -v claude >/dev/null 2>&1; then ok "model: Claude Code CLI ($(claude --version 2>/dev/null | head -1)). Run 'claude' once to sign in if you haven't."
    else warn "model: claude_code selected, but the claude CLI is not on PATH, so chat will show AI offline."; fi ;;
  anthropic)
    if [ -n "$(env_get ANTHROPIC_API_KEY)" ] || [ -n "${ANTHROPIC_API_KEY:-}" ]; then ok "model: Claude API (key found)"
    else warn "model: anthropic selected, but ANTHROPIC_API_KEY is empty. Add it to .env, then restart."; fi ;;
  none)
    warn "model: none configured. Policy chat shows AI offline; claims, limits and documents work." ;;
esac

# ---------------------------------------------------------------- 5. embedding model
bold "5/7  Embedding model for document search"
if [ "$WARM_MODEL" = 1 ]; then
  echo "    Downloading BAAI/bge-small-en-v1.5 on first run (about 200 MB, then cached in runtime/models)…"
  if "$VPY" - <<'PY'
from core.context import build_context
context = build_context(with_model=False)
retriever = context.retriever
print('    mode=%s vectors=%d %s' % (retriever.mode, retriever.vector_count(), retriever.vector_error or ''))
context.store.close()
raise SystemExit(0 if retriever.mode == 'hybrid' or context.settings.embeddings.provider == 'none' else 3)
PY
  then ok "hybrid search ready"
  else warn "embedding model unavailable (offline?). The app will use keyword search; re-run setup later to enable hybrid search."; fi
else
  warn "skipped; the API downloads the model on first start"
fi

# ---------------------------------------------------------------- 6. self-test
bold "6/7  Self-test"
if [ "$RUN_TESTS" = 1 ] && [ -d tests ]; then
  mkdir -p runtime
  "$VPY" -m pytest -p no:warnings -p no:cacheprovider >runtime/setup-tests.log 2>&1 \
    && ok "$(tail -1 runtime/setup-tests.log)" \
    || die "self-tests failed; see runtime/setup-tests.log"
else
  warn "skipped"
fi

# ---------------------------------------------------------------- 7. start
bold "7/7  Start"
chmod +x run.sh setup.sh setup.command 2>/dev/null || true
if [ "$START" = 1 ]; then
  exec bash "$ROOT/run.sh"
else
  ok "setup complete. Start the app any time with: bash run.sh"
fi
