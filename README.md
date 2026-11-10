# Autonomous Engineering Core

A local-first software engineering agent with an isolated deterministic demo and an Ollama coding provider that runs models on this computer.

See [docs/architecture.md](docs/architecture.md) for the architecture, trust boundaries, acceptance criteria, and first-version limits.

## Requirements

- Python 3.11 or newer
- Git
- No Docker or third-party Python packages required

## Quick start

```powershell
python -m unittest discover -s tests -v
python main.py demo
```

The demo works on a disposable fixture and creates a dedicated branch/worktree under `workspaces/`. After tests and review, the workflow commits its changes on that isolated branch. It never pushes automatically.

## Local coding agent

The AI provider is Ollama and is restricted to `localhost`; source code and task prompts are not sent to an external API. Install Ollama separately, then download a local coding model once:

```powershell
ollama pull qwen2.5-coder:7b
```

Start Ollama, then launch the dashboard with `python main.py dashboard`. Open `http://127.0.0.1:8765/`, enter a local Git repository path and a feature request, and submit it. Each request gets its own clone, worktree, and `agent/<task-id>` branch. The dashboard displays run status and stage details.

The command-line equivalent is `python main.py run --repo D:\Projects\my-app --objective "Add a sales dashboard"`.

After reviewing a successful task, publish its branch with `python main.py publish TASK_ID --confirm`. This pushes only that task branch to the configured `origin`; it does not merge or open a pull request.

Copy `config.example.toml` to `config.toml` to adjust local workflow settings. Do not put secrets in the config file.

## Current limits

The demo provider only handles the bundled calculator scenario. The current safe test runner supports Python `unittest` projects. Ollama and the configured model must be installed locally before the AI workflow can run. GitHub publishing remains an explicit command after review. The runner restricts command profiles, working directory, execution time, and captured output. Portable OS-level memory/CPU quotas are not included. Docker and external model APIs are not used.
