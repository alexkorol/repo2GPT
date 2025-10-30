# Repo2GPT
Repo2GPT is a Python application that clones a GitHub repository (or points at an existing local checkout) and produces:

- A **repomap** describing the directory structure plus key classes/functions per source file.
- A **consolidated code bundle** that merges the relevant source files into a single prompt-friendly text file.

### Language-aware summaries

Repo2GPT extracts richer function and type information for Python, JavaScript/TypeScript, Go, Rust, Ruby, and PHP source files, helping the repo map highlight the most relevant entry points in those ecosystems.

The tool now defaults to a code-centric include list so that dependency locks, build artefacts, and other filler stay out of your prompt window. When you do need to override the defaults, Repo2GPT recognises `.gptignore` / `.gptinclude` files as well as inline CLI switches.

### Install the Required Packages:

With the virtual environment activated (optional), install the packages listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Running tests

Repo2GPT includes a pytest suite that covers critical helpers and a full repository processing path. After installing the
dependencies, run:

```bash
pytest
```

Use the same command in continuous integration jobs once dependency installation has completed.

## Usage

With everything set up, you can now use Repo2GPT:

```bash
python main.py <repo-url-or-path> \
  --copy both \
  --extra-include "*.yml" \
  --extra-extensions md
```

Key options:

- `--copy {map|code|both}` will push the generated outputs into the system clipboard, ready for pasting into your AI chat.
- `.gptignore` / `.gptinclude` files (at the repo root or supplied via `--gptignore` / `--gptinclude`) mirror the patterns used by popular alternatives such as git2gpt. Include patterns **add** to the default code-centric filter: code files remain eligible even when a `.gptinclude` exists, while non-code files require a matching include rule.
- `--extra-ignore`, `--extra-include`, and `--extra-extensions` let you fine-tune experiment-specific filters without editing dotfiles.
- `--max-file-bytes` (default 500 KB) prevents enormous compiled or vendor files from exploding the output; pass `0` to disable.
- `--include-all` reverts to the legacy “include everything” behaviour if you really need it.
- `--enable-token-counts` prints an estimated token budget for each consolidated chunk; install the optional `tiktoken` package for model-aware counts.
- `--chunk-size` splits the consolidated output into numbered files once a chunk nears the requested token ceiling (set to `0` to disable).

Repo2GPT writes `repomap.txt` and `consolidated_code.txt` to your current working directory unless you override the paths. If the targets live inside the repository directory, they are automatically excluded from the generated output.

### Token planning & chunked output

Install the optional tokenizer dependency to obtain model-compatible counts:

```bash
pip install tiktoken
```

Then invoke Repo2GPT with the token helpers enabled:

```bash
python main.py <repo-url-or-path> \
  --enable-token-counts \
  --chunk-size 3500
```

The CLI now reports token usage per chunk, the total estimated budget, and whether the counts are approximate (when `tiktoken` is unavailable). When chunking is enabled, the primary consolidated file retains its original name and subsequent chunks are written as `<name>_partXX.ext`. Clipboard copies combine the numbered chunks with lightweight headings so you can paste the full series into your prompt workflow.

## API service

Repo2GPT now ships with a FastAPI-powered service that accepts repository processing jobs and streams progress back to clients. The API layers asynchronous job execution, on-disk persistence, and live Server-Sent Event (SSE) feeds on top of the existing snapshot engine.

### Running the server locally

Install the dependencies and start the application with Uvicorn:

```bash
pip install -r requirements.txt
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Set `REPO2GPT_STORAGE_ROOT` if you want processed artifacts and status files to live somewhere other than the default `~/.repo2gpt/jobs` directory. Jobs are persisted on disk so they survive restarts.

### Submitting jobs

Create a job with `POST /jobs`. The payload must include a `source` describing where the repository comes from (`git`, `archive_url`, or `archive_upload`) and optional processing tweaks:

```json
{
  "source": {
    "type": "git",
    "url": "https://github.com/openai/repo2gpt.git",
    "ref": "main"
  },
  "chunk_token_limit": 3500,
  "enable_token_counts": true,
  "options": {
    "ignore_patterns": ["*.ipynb"],
    "allow_non_code": false
  }
}
```

The endpoint responds immediately with a job identifier while processing continues in the background. The work runs in an asynchronous task so request threads remain free.

### Tracking status and artifacts

- `GET /jobs/{id}` returns the job metadata, progress log, and any token statistics.
- `GET /jobs/{id}/artifacts` fetches the generated repo map and consolidated chunks once the job has completed.
- `GET /jobs/{id}/events` streams incremental updates as SSE messages. Clients receive progress notifications, chunk statistics, and final status changes in near real time.
- `GET /healthz` exposes a simple readiness probe for load balancers and orchestration systems.

SSE streams emit `status`, `progress`, `chunk`, `repomap`, and `tokens` events, each carrying structured JSON data. The server keeps connections alive with heartbeat comments so browsers do not time out on long-running repositories.

### Authentication

Set the `REPO2GPT_API_KEY` environment variable to enforce API-key based authentication. When configured, every request must include an `X-API-Key` header that matches the configured secret. Leave the variable unset for unauthenticated local development.

### Deployment

The repository provides a production-ready Dockerfile. Build and run the container with:

```bash
docker build -t repo2gpt-api .
docker run --rm -p 8000:8000 -e REPO2GPT_API_KEY=super-secret \
  -e REPO2GPT_STORAGE_ROOT=/data/jobs -v $(pwd)/jobs:/data/jobs repo2gpt-api
```

For bare-metal or virtual machine deployments you can rely on Gunicorn’s Uvicorn worker class:

```bash
gunicorn api.server:app -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 --workers 2 --timeout 300
```

Make sure the `REPO2GPT_STORAGE_ROOT` directory is writable by the service account and, when authentication is enabled, store the API key securely (for example via environment-injected secrets).

## Future plans

- Add ASM traversal and mapping similar to ctags.
- Ship a web version or VS Code extension.
- Better language-specific parsers for the repo map summaries.

## License

Repo2GPT is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for more details.
