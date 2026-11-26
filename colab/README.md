# Hosted Qwen + embeddings on Google Colab

`qwen_vllm_server.ipynb` runs the expense assistant's model server on a Colab GPU and exposes it over one
HTTPS URL protected by an API key:

- **Chat and tool calling:** `Qwen/Qwen3-4B-Instruct-2507` on vLLM (OpenAI-compatible `/v1/chat/completions`)
- **Embeddings:** `BAAI/bge-small-en-v1.5` on the GPU (OpenAI-compatible `/v1/embeddings`)

The app talks to both through its existing `openai_compatible` adapters. You configure them only in your
local `.env`; `config/settings.toml` stays unchanged.

## Steps

1. Open the notebook in Colab (File → Upload notebook), choose **Runtime → Change runtime type → L4 GPU**, then **Run all**.
   The first run takes about 8–12 minutes.
   **After any disconnect or restart: Runtime → Run all.** You never need to run steps one by one. Every step reuses
   what is still there: it skips the install and download, waits for a vLLM that is still loading, keeps a running
   gateway, and keeps the same tunnel URL while it works. The stop cell does nothing unless you set `CONFIRM_STOP = True`.
   The monitor (step 8) restarts any server that goes down while the runtime is alive.
   **Google Drive checkpoints** (`MyDrive/colab_expense_assistant`, on by default; a fresh runtime asks once for
   Drive access): the pip package cache (~3–4 GB, so a fresh runtime reinstalls vLLM without downloading it), the API
   key (the same key on every runtime), and the black-box log. The 8 GB model copy (`DRIVE_CACHE_MODEL`) is off by
   default: Colab downloads it from Hugging Face about as fast, and 15 GB of Drive fits the packages or the model, not
   both. The notebook checks Drive's free space before writing.
   To keep the same URL and key even on a fresh runtime, add Colab Secrets `COLAB_API_KEY`, and `NGROK_AUTHTOKEN` +
   `NGROK_DOMAIN` (ngrok's free static domain) with `TUNNEL = "ngrok"`. Then `.env` never needs to change.
2. Copy the block printed in step 7 into the project's `.env`, replacing any older hosted block.
3. On your laptop, from the project folder: `.venv\Scripts\python.exe -m scripts.check_hosted_model`.
   It should print `OK` for the model and the embeddings.
4. Restart the app (`run.bat`). `http://127.0.0.1:8000/ready` then shows the hosted model and
   `"active_model": "openai_compatible:BAAI/bge-small-en-v1.5"`.

## What happens when Colab stops

| Part | Behaviour |
|---|---|
| Embeddings | Checked once when the API starts. If the hosted endpoint does not answer, the app uses the local copy of the same model (`[embeddings].fallback_provider = "fastembed"`) and `/ready` shows `fallback_reason`. Restart the API after Colab is back to switch to the hosted model again. |
| Chat model | No fallback. Answers fail with a provider error until you restart the notebook, paste the new `.env` block and restart the API. To go back to Claude Code, remove the block from `.env` and restart. |

The tunnel URL changes every Colab session. A fixed `COLAB_API_KEY` in Colab Secrets keeps the key stable.

## Environment overrides the app reads

| Variable | Overrides |
|---|---|
| `EXPENSE_MODEL_PROVIDER`, `EXPENSE_MODEL_ID`, `EXPENSE_MODEL_BASE_URL`, `EXPENSE_MODEL_API_KEY_ENV` | `[model]` provider, model_id, base_url, api_key_env |
| `EXPENSE_MODEL_MAX_OUTPUT_TOKENS`, `EXPENSE_MODEL_TIMEOUT_SECONDS`, `EXPENSE_MODEL_SUPPORTS_VISION` | `[model]` limits and capability flag (Qwen3-4B is text-only) |
| `EXPENSE_EMBEDDINGS_PROVIDER`, `EXPENSE_EMBEDDINGS_MODEL_ID`, `EXPENSE_EMBEDDINGS_BASE_URL`, `EXPENSE_EMBEDDINGS_API_KEY_ENV` | `[embeddings]` provider, model_id, base_url, api_key_env |
| `EXPENSE_EMBEDDINGS_FALLBACK_PROVIDER` | `[embeddings].fallback_provider` (`fastembed` or `none`) |

## Limits to know

- **Vision:** `Qwen3-4B-Instruct-2507` cannot read images. Receipt reading (milestone M4) will need a vision model on
  the same endpoint, such as a Qwen VL model. That decision belongs to M4.
- **Data:** synthetic data only. The endpoint is public but requires the API key. Request bodies are not logged by the gateway.
- **Cost:** the GPU uses Colab compute units while the runtime is connected.
