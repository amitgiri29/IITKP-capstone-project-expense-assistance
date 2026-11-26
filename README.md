# Expense Policy Assistant

![SPARKS AI Lab](assets/brand/sparks-ai-lab-logo.png)

Travel expense policy assistant for **SPARKS AI Lab**, a fictional company used for this capstone. Employees can ask policy questions and get cited answers, check a claim against policy and their trip budget, upload receipts, and see the limits for their grade. Administrators can add policy documents that the assistant searches and cites.

> **Status:** application version 0.3.0. Milestones M0–M3 are built: calculations, API and UI, policy Q&A, and the admin policy library with LangChain parsing, chunking and hybrid (keyword + vector) search. **M5 travel search** works with the offline DEMO fixture provider. **M6 agents** are built for travel search: a LangGraph planner → executor → writer → critic graph with per-session checkpoints and at most one repair, where all offer IDs and amounts come from Python tools. **M4 receipt review works from text** (by decision, no vision model): paste a receipt or upload a text receipt or digital PDF invoice, check and confirm the fields the model reads, and the caps are applied in Python. Receipt photos are stored but not read, because that would need a vision model or OCR. Test receipts are in [samples/receipts/](samples/receipts/). See the [architecture document](docs/architecture/SPARKS_Expense_Assistant_Architecture_v1.1.docx) for the full picture.
>
> **Agents in one paragraph:** for a flight or hotel search, the *planner* (the configured model) picks the registered tools and fills in missing details only from what you wrote. The *executor* runs the tools: it validates the request, searches the provider, checks offers against the rule registry in Python, and retrieves the policy text. The *writer* (model) drafts the explanation, and the *critic* (code checks plus the model) verifies the draft against the tool results. A rejected draft is rewritten once; after that the verified summary is shown. Without a model, the same tools run directly. Code: `workflows/agent_graph.py`, `workflows/planner.py`, `workflows/travel_search.py`, `domain/offers.py`, `adapters/travel.py`.

---

## Quick start: one-click setup

Get the code first: unzip the shared file, or clone the repository (`git clone <repository-url>`). Then run the setup script for your system. It installs everything, checks it, and starts the app:

| Your computer | One click | Or in a terminal, from the project folder |
|---|---|---|
| **macOS** | Double-click **`setup.command`** | `bash setup.sh` |
| **Linux** | — | `bash setup.sh` |
| **Windows** | Double-click **`setup.bat`** | `powershell -ExecutionPolicy Bypass -File setup.ps1` |

The first run takes a few minutes on a normal connection and needs about 1.2 GB of disk, mostly the Python packages plus the 200 MB search model. When the browser opens at **http://127.0.0.1:8501**, sign in from the sidebar with a demo user (see [First tour](#first-tour)). Press **Ctrl+C** in the setup window to stop the app.

**After the first time**, start the app with **`bash run.sh`** on macOS and Linux, or by double-clicking **`run.bat`** on Windows. Running setup again is also safe: it skips what is already done.

**What the setup script does**

1. **Python 3.14.10.** Uses it if already installed; otherwise installs it with `uv` or `pyenv`. If neither tool exists, it asks before installing `uv`. On Windows it asks before installing Python with `winget`.
2. **Virtual environment.** Creates `.venv` in the project folder, and rebuilds it if it was made with another Python.
3. **Dependencies.** Installs the tested set from `requirements.lock.txt`, then runs `pip check`.
4. **Local settings and AI model.**
   - Creates `.env` from `.env.example` if it doesn't exist yet.
   - Uses the Claude Code CLI if it's installed.
   - Otherwise it offers to save a Claude API key in `.env` (input is hidden), or to continue without AI chat. Claims, limits and policy documents work without AI.
5. **Embedding model.** Downloads the document-search model once (about 200 MB, cached in `runtime/models/`).
6. **Self-test.** Runs the 276 automated tests, with no model calls.
7. **Start.** Starts the API and UI, waits until both are healthy, and opens the browser. Logs go to `runtime/logs/`.

**Options**

| Option (macOS/Linux · Windows) | Effect |
|---|---|
| `--provider anthropic` · `-Provider anthropic` | Use a Claude API key from `.env` instead of Claude Code. `claude_code` switches back; `none` means no AI chat. |
| `--no-start` · `-NoStart` | Set up only; don't start the app. |
| `--skip-tests` · `-SkipTests` | Skip the self-test. |
| `--skip-model-download` · `-SkipModelDownload` | Let the API download the embedding model on first start instead. |
| `--yes` · `-Yes` | Answer yes to install prompts; never ask questions. Use this for unattended runs. |
| `EA_API_PORT=8100 EA_UI_PORT=8601 bash run.sh` | Use other ports. On Windows, set `$env:EA_API_PORT` and `$env:EA_UI_PORT` first. |

The scripts never commit, upload or print secrets. Your API key stays in `.env` on your machine, and `.env` is git-ignored.

> Tested end-to-end on macOS (Apple silicon) from the shared zip: new `.venv`, `.env` created, model downloaded, 276 tests passed, app running with AI online and hybrid search. The Linux path uses the same script but hasn't been run on a Linux machine yet. The Windows scripts (`setup.ps1`, `run.ps1`, `.bat`) haven't been run yet either; if one fails, use the manual steps below and tell the setup owner.

The rest of this README covers manual setup, configuration and troubleshooting. You don't need it if the quick start worked.

---

## 1. What you need

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.14.10** | Use the same patch version across the team. [pyenv](https://github.com/pyenv/pyenv) is easiest on macOS/Linux; on Windows use the python.org installer. |
| A model provider | — | Needed only for **Policy chat**. Everything else works without one. See [step 4](#4-choose-a-model-provider). |
| Docker (optional) | Docker Engine with Compose v2 | Only for running in containers. Rancher Desktop or Docker Desktop both work. |

Allow about 1 GB of disk for the virtual environment.

## 2. Get the code

Unzip the shared project folder (or clone the team repository once it exists). Open a terminal **in the project root**, the folder that contains this README.

```bash
cd expense_assistant_capstone
```

## 3. Create the Python environment (manual setup)

Skip steps 3–5 if you used the [one-click setup](#quick-start-one-click-setup).

**macOS / Linux**

```bash
# Install Python 3.14.10 once (pyenv shown; skip if you already have it)
pyenv install 3.14.10

# Create and activate a virtual environment in the project folder
"$(pyenv root)/versions/3.14.10/bin/python3.14" -m venv .venv
source .venv/bin/activate

# Install the exact, tested dependency set
python -m pip install --upgrade pip
python -m pip install -r requirements.lock.txt
python -m pip check
```

**Windows (PowerShell)**

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock.txt
python -m pip check
```

To confirm it worked, `python --version` should print `Python 3.14.10` and `pip check` should say `No broken requirements found.`

> **First start downloads an embedding model.** The API downloads `BAAI/bge-small-en-v1.5` (about 200 MB) from Hugging Face into `runtime/models/` the first time it starts, which takes about 20 seconds on a good connection. It runs on the CPU and costs nothing. Without internet access, the app still works in keyword-only search mode; see [Policy documents and search](#policy-documents-and-search-rag).

> The lockfile was resolved on macOS (Apple silicon) and also builds on Linux arm64 in Docker. If a package fails to install on your machine, tell the setup owner instead of changing versions. `requirements-proposed.txt` lists the direct dependencies if the lock needs regenerating.

## 4. Choose a model provider

The model is set in [config/settings.toml](config/settings.toml) under `[model]`. Pick **one** option.

### Option A — Claude Code (default, no API key)

The app calls your local Claude Code CLI in print mode, using your existing Claude Code sign-in. Tools are disabled and nothing is saved.

1. Install Claude Code and check that `claude --version` works in your terminal.
2. Run `claude` once and complete the sign-in.
3. Leave `config/settings.toml` as it is (`provider = "claude_code"`, `model_id = "claude-sonnet-5-5"`).

Each policy answer takes about 10–15 seconds and is charged to your Claude Code account (about USD 0.05 per answer in testing). This option works only on your own machine, not inside Docker.

### Option B — Claude API key

1. Copy the example environment file:

   ```bash
   cp .env.example .env          # Windows: copy .env.example .env
   ```

   Open `.env` and add (or fill in) this line:

   ```
   ANTHROPIC_API_KEY=your-key-here
   ```

2. Add this line to `.env` as well, or run `bash setup.sh --provider anthropic`, which does it for you:

   ```
   EXPENSE_MODEL_PROVIDER=anthropic
   ```

   `EXPENSE_MODEL_PROVIDER` overrides `provider` in `config/settings.toml` on your machine only, so the shared file stays unchanged. `EXPENSE_EMBEDDINGS_PROVIDER` does the same for `[embeddings]`. Restart the API after changing either one.

`.env` is git-ignored. **Never commit it, paste keys into chat, or put them in `settings.toml`.**

### Option C — Another hosted model

In `config/settings.toml`:

- set `provider = "openai_compatible"`
- set `base_url` to the endpoint and `model_id` to its model name
- set `api_key_env` to the name of the variable in `.env` that holds its key

This adapter hasn't been tested against a live endpoint yet.

### Option D — Qwen hosted on your own Colab GPU

[colab/qwen_vllm_server.ipynb](colab/qwen_vllm_server.ipynb) serves `Qwen/Qwen3-4B-Instruct-2507` (vLLM) and the `bge-small-en-v1.5` embedding model on a Colab L4 GPU behind one HTTPS URL with an API key. Run it in Colab, paste the `.env` block it prints, check it with `python -m scripts.check_hosted_model`, then restart the API. No change to `settings.toml` is needed: the `EXPENSE_MODEL_*` and `EXPENSE_EMBEDDINGS_*` overrides in `.env` take precedence. If the hosted embeddings don't answer when the API starts, the app falls back to the local bge-small model automatically. See [colab/README.md](colab/README.md).

### No model at all

The app still runs. Claims, receipts, travel limits and the policy library all work. Policy chat shows "capability unavailable" and the sidebar shows **AI offline**.

## 5. Run the app

**Easiest:** `bash run.sh` (macOS/Linux) or `run.bat` (Windows) starts both servers in one window, and **Ctrl+C** stops both. To run them separately instead, open **two terminals** in the project root and activate the virtual environment in each (`source .venv/bin/activate`).

**Terminal 1 — API**

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — UI**

```bash
python -m streamlit run ui/app.py --server.port 8501
```

Then open **http://127.0.0.1:8501** in your browser.

To check that it's healthy while running:

```bash
curl http://127.0.0.1:8000/health      # {"status":"ok",...}
curl http://127.0.0.1:8000/ready       # lists any failing component
```

`/ready` listing `travel` as failing is expected until milestone M5.

### First tour

Sign in on the start screen by choosing one of the three fixed (synthetic) accounts:

| User | Grade | Role | Try this |
|---|---|---|---|
| Arjun Mehta | E | employee | Ask "What is my hotel cap in Bengaluru?", then run the sample claim on **Claims & Verification**. |
| Kavya Iyer | M | employee | Compare the caps on **Travel Band Limits** with Arjun's. |
| Rohan Desai | M | admin | Open **Policy Documents**, upload a PDF, Word, `.txt` or `.md` guidance document, then ask the assistant about it. |

Grade and role come from [config/profiles.toml](config/profiles.toml) on the server, so the browser can't change them. **Sign out · delete session data** in the sidebar removes everything that session created.

To stop the app, press `Ctrl+C` in both terminals.

### Policy documents and search (RAG)

Only **Rohan Desai** (the administrator) can add documents. Use **Policy Documents → Add a policy document** and pick a file.

**What you can upload**
- PDF with a text layer, Word `.docx`, `.txt` or `.md`, up to 10 MB. You can also paste text.
- PDFs can have at most 200 pages.
- Scanned or image-only PDFs and password-protected PDFs are rejected, because OCR isn't permitted.

**What happens on upload**
1. A LangChain loader reads the file. PDFs are read page by page.
2. LangChain text splitters cut it into sections of about 1,800 characters with a 200-character overlap. Markdown is split at its headings first.
3. A vector is created for each section, and the search index is rebuilt.
4. The page shows something like *"4 sections · 2 pages · 4 vectors created (fastembed:BAAI/bge-small-en-v1.5) · Searchable now"*, with a preview of the sections.

**How questions are answered**
- Each question is searched two ways: keyword search (BM25) and meaning search (vectors). The two result lists are merged.
- Only documents for the user's organization, service date and geography are searched.
- The assistant header shows **Hybrid retrieval** when vectors are on, and **Keyword retrieval** when they aren't.

Uploaded documents can be searched and cited, but they never change a cap. Caps always come from the rule registry.

**Test documents:** [samples/policy_documents/](samples/policy_documents/README.md) has fictional documents in every supported format (PDF, Word, `.txt`, `.md`), plus three negative tests: a cap-override attempt, a prompt injection and a scanned PDF that must be rejected. It also lists the questions to ask and the expected answers.

## 6. Run with Docker (optional)

The Claude Code provider isn't available inside containers, so use **Option B** (or C):

1. Set `provider = "anthropic"` in `config/settings.toml` and put `ANTHROPIC_API_KEY` in `.env`.
2. Build and start:

   ```bash
   docker compose up --build
   ```

3. Open **http://127.0.0.1:8501**. The API is at http://127.0.0.1:8000.

- **Data:** kept in the `app-data` Docker volume. That includes the embedding model, which is downloaded once on the first start, so the API takes a minute or two to report healthy that first time.
- **Stopping:** press `Ctrl+C`, or run `docker compose down` (add `-v` to also delete the data volume).
- **Image contents:** it runs as a non-root user and contains no `.env` and no test answer keys.
- **First pull times out:** this can happen right after starting Rancher Desktop. Wait a minute and run the command again.

## 7. Run the tests and checks

```bash
python -m pytest                           # 276 unit and integration tests, no model calls or model downloads
python validate_package.py                 # documentation, data and file-hash consistency
python -m evaluation.driver --through M3   # golden cases; model-dependent ones show BLOCKED_CAPABILITY
```

Add `--embeddings` to a driver run to use hybrid retrieval; without it the driver is keyword-only, so offline runs never download a model. `python -m evaluation.driver --milestone M3 --allow-model` runs the 31 policy cases against the configured model. It spends real model credit (roughly USD 1.50 with Claude Code), so only run it when you mean to. Results go to `runtime/evaluation/`.

If you change a source file of a generated document (`SPECIFICATION.txt`, `policy_sources/policy.json`, `docs/TEAM_PLAN.txt`, `docs/REQUIREMENTS.json`), run `python3 build_package.py` first, then `python validate_package.py`. `build_package.py` needs `python-docx`.

## 8. Configuration at a glance

| File | What it controls |
|---|---|
| [config/settings.toml](config/settings.toml) | Model provider and model, embeddings, travel provider (M5), retrieval and chunking settings, telemetry. To use another file, set `EXPENSE_CONFIG=/path/to/settings.toml`. |
| [config/profiles.toml](config/profiles.toml) | Demo travelers and their grade and role. |
| `.env` (you create it) | Secrets only, referenced by name from `settings.toml`. |
| [policy_sources/rule_registry.json](policy_sources/rule_registry.json) | Every cap and threshold used in calculations. Change it only through a reviewed edit. |
| [policy_sources/reference_data.json](policy_sources/reference_data.json) | Countries, city tiers and aliases, FX fixtures, status and error codes. |
| [.streamlit/config.toml](.streamlit/config.toml) | UI theme and server options. |

### Embeddings: switching to the hosted API

The `[embeddings]` section of `config/settings.toml` picks one of three modes:

| `provider` | What it does |
|---|---|
| `"fastembed"` | **Default.** Local CPU model, free, about 200 MB on first download. A stand-in until the hosted API arrives. |
| `"openai_compatible"` | The hosted embedding API. Set `base_url` (for example `https://<host>/v1`) and `model_id`, and set `api_key_env` to the name of a variable you add to `.env`, such as `EMBEDDINGS_API_KEY`. |
| `"none"` | Keyword-only search. |

When you change the provider or model, restart the API. Existing sections are embedded again automatically, because cached vectors are stored per model. Check `http://127.0.0.1:8000/ready`: `components.embeddings` shows the provider, the model, how many vectors exist, and any error.

The hosted adapter has been tested only against a mock server so far. Once you have the keys, upload a small document and confirm it reports vectors created.

## 9. Project layout

| Folder | Contents |
|---|---|
| `ui/` | Streamlit app (`ui/app.py`), design system (`ui/theme.py`), self-hosted fonts |
| `api/` | FastAPI app (`api/main.py`), security, uploads, error format, `openapi.json` |
| `domain/` | Plain-Python calculations: registry resolver, money arithmetic, FX, budget, deadline, duplicates |
| `retrieval/` | LangChain loaders and splitters for uploads, hybrid BM25 + vector retrieval, applicability parsing, citation checks |
| `workflows/` | Request guards and the policy-question pipeline |
| `adapters/` | Model providers (Claude Code, Anthropic SDK, OpenAI-compatible), embeddings (FastEmbed, OpenAI-compatible, SQLite cache) and telemetry |
| `core/` | Settings, SQLite store, event log, redaction, application context |
| `evaluation/` | Golden-case driver and comparators |
| `tests/` | Unit and integration tests, plus the 120 golden cases (never shown to the app or the model) |
| `policy_sources/` | The fictional policy, rule registry and reference data |
| `config/`, `assets/`, `architecture/`, `docs/`, `scripts/` | Configuration, logo, diagrams, documentation, tooling |
| `runtime/` | Local database, uploads, embedding-model cache, logs and evaluation results. Git-ignored; safe to delete while the app is stopped. |
| `setup.sh`, `setup.command`, `run.sh` | One-click setup and start for macOS and Linux |
| `setup.ps1`, `setup.bat`, `run.ps1`, `run.bat` | One-click setup and start for Windows |
| `colab/` | Colab notebook that hosts the Qwen model and embeddings on a GPU (Option D) |
| `samples/policy_documents/` | Fictional test documents for policy upload, with expected answers |

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| Sidebar shows **AI offline** | **Option A:** check that `claude --version` works in the terminal running the API and that you've signed in. **Option B:** check that `ANTHROPIC_API_KEY` is in `.env` and `provider = "anthropic"`. Restart the API after any change. |
| macOS says `setup.command` **can't be opened** | It was downloaded, so macOS quarantined it. Right-click the file, choose **Open**, then **Open** again; or run `bash setup.sh` in Terminal. |
| Windows says **running scripts is disabled** | Use `setup.bat`, which bypasses the policy for this one script, or run `powershell -ExecutionPolicy Bypass -File setup.ps1`. |
| Setup stops at **Python 3.14.10** | Install it from [python.org](https://www.python.org/downloads/) (on Windows, tick *Add python.exe to PATH*), then run setup again. |
| Setup stops at **self-tests failed** | Open `runtime/setup-tests.log` and send the last lines to the setup owner. |
| `run.sh` says **port is already in use** | The app is probably already running in another window. Use that one, or start on other ports: `EA_API_PORT=8100 EA_UI_PORT=8601 bash run.sh`. |
| UI shows **Api Unreachable** | The API isn't running on port 8000. Start terminal 1. |
| `Address already in use` | Another process is using port 8000 or 8501. Stop it, or pick another port; for the API, also set `api_base_url` in `config/settings.toml`. |
| `python --version` isn't 3.14.10 | The virtual environment isn't active, or was created with another Python. Recreate `.venv` with 3.14.10. |
| **Rate Limited** error | More than 10 requests in one minute for one session. Wait for the time shown. |
| UI looks stale after editing code | Restart the Streamlit terminal; Streamlit doesn't reload imported modules. |
| Header shows **Keyword retrieval** instead of **Hybrid retrieval** | The embedding model couldn't load (often no internet on first start), or `provider = "none"`. See `components.embeddings.error` at `/ready`, fix it, and restart the API. Search still works in keyword mode. |
| Upload says **No text could be extracted** | The PDF is a scan with no text layer. Export it from the original document, or paste the text. |
| A page shows a generic error | Details are logged in the API terminal with a request ID; the UI hides internals on purpose. |

## 11. Sharing the project

Leave out these local-only items when you share the folder: `.venv/`, `runtime/`, `.env`, `__pycache__/`, `.pytest_cache/`. For example, from the folder above the project:

```bash
zip -r expense_assistant_capstone.zip expense_assistant_capstone \
  -x "*/.venv/*" "*/runtime/*" "*/.playwright-cli/*" "*/.env" "*/__pycache__/*" "*/.pytest_cache/*" "*/.DS_Store"
```

The zip is about 4 MB and keeps the scripts executable. Each teammate unzips it and runs the [one-click setup](#quick-start-one-click-setup) with their own Claude Code sign-in or API key.

**Via GitHub.** Commit the project to a **private** repository. `.gitignore` already leaves out `.venv/`, `runtime/`, `.env` and the other local-only items, and `.gitattributes` keeps the right line endings for the shell (`LF`) and Windows (`CRLF`) scripts. Teammates then run:

```bash
git clone <repository-url>
cd expense_assistant_capstone
bash setup.sh            # Windows: double-click setup.bat
```

If `setup.sh` loses its executable bit after a clone or unzip, `bash setup.sh` still works. Follow [docs/REPOSITORY_WORKFLOW.txt](docs/REPOSITORY_WORKFLOW.txt) for branches and reviews. Before the first push, check that `git status` doesn't list `.env`.

## 12. Data and safety

- Use **synthetic data only**. Don't enter real employee, patient or receipt details. Follow the athenahealth PHI guidance: http://go/claude-phi-guidelines
- The assistant only searches and reviews. It never books, pays or approves claims.
- Calculation caps come only from the reviewed rule registry. Documents added by administrators can be searched and cited but never change a cap.

## 13. Documentation map

| Document | Use it for |
|---|---|
| [Architecture & Implementation Overview v1.0 (Word)](docs/architecture/SPARKS_Expense_Assistant_Architecture_v1.1.docx) | Architecture diagrams, technology roles, implemented use cases |
| [SPECIFICATION.txt](SPECIFICATION.txt) | The full specification (version 1.6) |
| [docs/IMPLEMENTATION_BACKLOG.txt](docs/IMPLEMENTATION_BACKLOG.txt) | Milestones M0–M8 and their status |
| [docs/DECISIONS.json](docs/DECISIONS.json) | Decisions made so far and open items |
| [docs/CHANGELOG.txt](docs/CHANGELOG.txt) | What changed and why |
| [docs/TEST_PROTOCOL.txt](docs/TEST_PROTOCOL.txt) | How golden cases are run and scored |
| [docs/M0_REGISTRY_REVIEW.txt](docs/M0_REGISTRY_REVIEW.txt) | Rule-registry sign-off checklist (needs a second reviewer) |
| [docs/AWS_DEPLOYMENT_PLAN.txt](docs/AWS_DEPLOYMENT_PLAN.txt) · [docs/LANGSMITH_PLAN.txt](docs/LANGSMITH_PLAN.txt) | Plans for the AWS deployment (M8) and LangSmith tracing |
| `START_HERE.html` | Searchable catalog of the golden test cases (open locally) |

**When files disagree**, this order wins: the policy and rule registry, then reference data, then the golden cases, then the specification, then the contracts and schemas. Generated files — the three `.docx` copies of the spec, `docs/REQUIREMENTS.txt`, the golden exports and `manifest.json` — are produced by `build_package.py`. Never edit them by hand.

Version set: application 0.2.0 · specification 1.6 · fictional policy 1.1 · golden suite 1.1.

## 14. For developers and coding assistants

Before changing code, read [MODEL_HANDOFF.txt](MODEL_HANDOFF.txt), [AGENTS.md](AGENTS.md), [IMPLEMENTATION_CONTRACT.json](IMPLEMENTATION_CONTRACT.json) and [docs/BEFORE_IMPLEMENTATION.txt](docs/BEFORE_IMPLEMENTATION.txt). `CLAUDE.md` and `GEMINI.md` point to the same instructions. Every number and enumeration must come from the rule registry and reference data, never hard-coded.
