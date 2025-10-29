# Repo2GPT
Repo2GPT is a Python application that clones a GitHub repository (or points at an existing local checkout) and produces:

- A **repomap** describing the directory structure plus key classes/functions per source file.
- A **consolidated code bundle** that merges the relevant source files into a single prompt-friendly text file.

The tool now defaults to a code-centric include list so that dependency locks, build artefacts, and other filler stay out of your prompt window. When you do need to override the defaults, Repo2GPT recognises `.gptignore` / `.gptinclude` files as well as inline CLI switches.

### Install the Required Packages:

With the virtual environment activated (optional), install the packages listed in `requirements.txt`:

```bash
pip install -r requirements.txt
```

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

Repo2GPT writes `repomap.txt` and `consolidated_code.txt` to your current working directory unless you override the paths. If the targets live inside the repository directory, they are automatically excluded from the generated output.

## Future plans

- Add ASM traversal and mapping similar to ctags.
- Ship a web version or VS Code extension.
- Add token estimates and chunked output helpers for extra-long repositories.
- Better language-specific parsers for the repo map summaries.

## License

Repo2GPT is licensed under the terms of the MIT license. See [LICENSE](LICENSE) for more details.
