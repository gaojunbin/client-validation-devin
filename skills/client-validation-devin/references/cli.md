# client-validation-devin CLI reference

Global flags: `-C <dir>` (any directory inside the product repo), `--config <path>` (default `.devin/qa.toml`).

| Command | What it does |
| - | - |
| `login [--org ID] [--key-stdin] [--no-verify]` | Ask for the Devin API key with hidden input, check it against `/v3/self`, store it (and the detected org) in `~/.config/client-validation-devin/env` with mode 600, editing a symlinked file in place |
| `available [--online]` | Exit 0 when this machine can validate this repository (key configured, `.devin/qa.toml` present; `--online` also checks the key); otherwise print why and exit 2. Used by repositories that make validation conditional |
| `init [--force]` | Write `.devin/qa.toml` from the example (refuses to overwrite a symlink) |
| `doctor [--probe-platforms]` | Check Python, git, config, credentials, API, org, push access, Devin repo access, and warn when this organization has not built the repository's environment or lacks a secret `[secrets]` names; with the flag, list the VM platforms the org can use |
| `run [--platforms a,b] [--rerun] [--focus TEXT] [--scenarios id,id] [--fresh] [--allow-dirty] [--force-round] [--dry-run] [--wait --timeout S]` | Start a round. Exits 3 at once unless `--wait`. `--dry-run` only renders prompts (no push, no API). When the repository has `.devin/blueprint.yaml`, it first checks that the current Devin organization has built this repository's environment (with bundle delivery, only once the organization has the blueprint) and otherwise exits 2 with the next command (`env apply --wait`, or `env status --build <id> --wait` while the first build runs); it notes secrets named in `[secrets]` that the organization lacks |
| `wait [--run ID] [--timeout S]` | Poll until done or timeout (default 540 s). On completion collects artifacts and writes the report. Without `--run` it waits on the most recently started run; runs of one branch may overlap and finalize safely (branch lock) |
| `status [--run ID] [--json]` | Show the run without acting on sessions |
| `report [--run ID] [--json] [--branch]` | Print the round's report (re-rendered from `report.json`); exit code = the round's exit code. `--branch` merges the latest result of every platform on this branch (rounds split by platform or `--rerun`) with cross-platform root causes, written to `branch-report.md` |
| `fetch <platform> <name> [--run ID]` | Download a file listed under "Not downloaded" (videos, archives); zip archives are unpacked safely and `evidence.md` is rebuilt |
| `message <platform> "<text>"` | Send a message to that platform's session |
| `stop [--archive]` | Terminate the run's active sessions |
| `release [--yes]` | Release gate (see SKILL.md) |
| `cleanup [--remote] [--sessions] [--local]` | Delete the scratch ref, terminate+archive ledger sessions, remove local state for this branch |
| `env apply\|sync\|status\|logs [--build ID] [--wait] [--timeout S] [--switch-from-git]` | Upload `.devin/blueprint.yaml` (database mode) or sync it from the default branch, build snapshots, follow a build; `logs` (also printed after `apply --wait`) shows each repository's build result and any warm-up `WARN` |

## Files
- Product repo: `.devin/qa.toml` (spec), `.devin/blueprint.yaml` (environment).
- Credentials: `DEVIN_API_KEY` (required, `cog_...`), `DEVIN_ORG_ID` (optional, resolved from `/v3/self`),
  `DEVIN_API_BASE` (optional) from the environment or `~/.config/client-validation-devin/env` (`KEY=value` lines; override the path
  with `CLIENT_VALIDATION_DEVIN_ENV_FILE`).
- State: `/tmp/client-validation-devin/<owner__repo>/<branch>/` (override with `CLIENT_VALIDATION_DEVIN_HOME`):
  - `ledger.json`: last verdict, commit, session and open issues per platform; issue streaks; rounds since green.
  - `runs/<run-id>/run.json`: session ids, round tokens, states.
  - `runs/<run-id>/<platform>/`: `prompt.md`, `session.json`, `report.json` (validator output), `messages.json`,
    `transcript.md`, `attachments/`, `evidence.md` (attachments grouped by check), `collected.json`.
    Videos and archives are listed in the report instead of downloaded; `fetch` gets one on demand.
  - `runs/<run-id>/report.json` and `report.md`: the aggregated round.
  - `branch-report.md`: written by `report --branch`.

## Delivery
- `push` (default): `git push --force origin HEAD:refs/heads/client-validation-devin/<branch>`; the validator fetches that ref and
  checks out the exact commit. Needs the repo connected to Devin.
- `bundle`: `git bundle create <repo>-<sha>.bundle HEAD` uploaded as a session attachment. No push. No LFS objects or
  submodules; large repos upload slowly.

## Report fields (validator output, `assets/report.schema.json`)
`verdict`, `summary`, `phases.{checkout,build,tests,launch,scenarios,layout}.status`, `tests`, `scenarios[]`,
`issues[]` (`id`, `severity`, `category`, `title`, `scenario`, `screen`, `device`, `repro_steps`, `expected`, `actual`,
`evidence`, `log_excerpt`, `suspected_location`, `suggested_fix`, `confidence`, `status_vs_previous`),
`fixed_issue_ids`, `blocked_reason`, `spec_feedback`, `evidence_files`.

## Verdict policy (the CLI's, not the validator's)
- `blocked`: no final report for this round, validator verdict blocked, checkout failed, or the build environment was
  blocked; also any session error, a session the current key cannot see (deleted, or another organization), or a
  usage limit. A usage limit (session suspended, or creation refused) also makes the round "needs a human" (exit 5).
- `fail`: build failed, tests failed, an issue with severity in `[run].fail_on`, a failed scenario without an issue, or
  a validator `fail` without any issue.
- `pass`: everything else; issues below the gate are listed as warnings.
