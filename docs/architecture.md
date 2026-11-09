# Architecture and acceptance plan

## Purpose

Build a small, testable software-engineering workflow that coordinates planning, code changes, tests, review, and a final report. The first implementation uses deterministic local role providers; it does not claim model intelligence or require an external model service.

## Components

- `main.py` / `autonomous_eng`: CLI entry point and task intake.
- `core.models`: typed task, role-contract, step-status, and result records.
- `core.context`: SQLite task and step history, persisted across runs.
- `core.engine`: explicit workflow state machine and failure reporting.
- `roles`: separate planner, executor, and reviewer interfaces, each replaceable by a future provider.
- `tools.git_tools`: isolated Git worktree and branch operations with status/diff inspection.
- `tools.runner`: fixed command profiles, path containment, timeout, and bounded output.
- `fixtures/buggy_project`: disposable regression target for the first scenario.

## Trust boundaries

Task text, model/provider output, repository files, Git output, and subprocess output are untrusted. The runner accepts only registered test profiles, does not invoke a shell, runs only in the selected worktree, and rejects working directories outside the configured root. Execution has a timeout, bounded captured output, and a minimal environment. File edits and review diffs are capped at 1 MiB. No credentials are logged or stored in task context. The workflow never pushes, merges, deletes user data, or changes security settings.

## Short implementation plan

1. Record this architecture and establish Python packaging/configuration.
2. Add data contracts and persistent task/step state; cover them with unit tests.
3. Add role contracts, safe runner, Git worktree handling, and the workflow engine.
4. Add a CLI and a disposable buggy fixture; verify successful and failed runs end to end.
5. Document setup and limits, add sample configuration and CI.

## Acceptance criteria

- A CLI task is persisted and each workflow stage ends in a recorded success or failure with a reason.
- A successful demo applies a regression fix in a separate branch/worktree, runs its regression test, passes review, and reports the result.
- A failing test or rejected command is reported and persisted without claiming success.
- Unit and integration tests cover success and failure paths.
- The runner rejects unregistered commands and out-of-root working directories, times out long commands, and bounds captured output.
- A clean checkout can be configured and tested using the documented commands and CI workflow.

## Known first-version limits

The demo provider is deterministic and only handles the included fixture scenario. The process can still access files allowed to the current OS user; this is not an OS sandbox. Portable OS-level memory/CPU quotas are not available in this dependency-free Windows-first version. Docker is optional and is not used. GitHub authentication and remote publication are separate operations and must be verified before publishing.
