# Autonomous Engineering Core

A small, testable prototype for a semi-automated software engineering workflow. It is not a chatbot or a claim of autonomous model capability. The initial provider is a deterministic local demo implementation and requires no API key.

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

The demo works on a disposable fixture and creates a dedicated branch/worktree under `workspaces/`. It does not push or merge. Use `python main.py --help` for CLI options.

Copy `config.example.toml` to `config.toml` to adjust local workflow settings. Do not put secrets in the config file.

## Current limits

The deterministic provider only handles the bundled demo scenario. The runner restricts command profiles, working directory, execution time, and captured output. Portable OS-level memory/CPU quotas are not included in this first version. Docker and external model APIs are not required or invoked.
