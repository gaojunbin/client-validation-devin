---
name: client-validation-devin
description: Validate a multi-platform client app (iOS, Android, macOS, Windows, Linux, web) on Devin cloud VMs, then fix and re-validate until every platform is green and gate the release. Use after finishing a change to an app that ships on more than one platform and before calling the work done, or when asked to test on simulators, emulators, devices or other operating systems, or to check layout, overlapping UI, crashes or platform-specific bugs. Drives the client-validation-devin CLI, so nothing heavy runs locally. Not for server-only or unit-test-only changes.
compatibility: Needs git, Python 3.11+, network access to api.devin.ai, a Devin account with API access (DEVIN_API_KEY), and .devin/qa.toml in the product repo.
metadata:
  version: "0.1.0"
---

# client-validation-devin: validate on Devin, fix, repeat, release

Devin runs one validator session per platform on real VMs (macOS VM for iOS Simulator and macOS apps,
Linux VM for Android emulator, Linux desktop and web, Windows VM or Outpost for Windows). Each
validator builds the exact commit, runs tests, walks the scenarios, sweeps the layout matrix, and
returns a structured report with screenshots and logs. You own the code; validators never change it.

## Before the first run
1. `client-validation-devin` must be on PATH (installed by `install.sh`); otherwise call
   `<this skill folder>/scripts/client-validation-devin`.
2. `client-validation-devin available --online` exits 0 when this machine and repository are ready. Otherwise it
   says why: no key (the human runs `client-validation-devin login`; never ask for the key in chat) or the repo is
   not onboarded (follow the `client-validation-devin-setup` skill). When a repository's instructions make
   validation conditional and this command fails, give the human a manual check list instead of blocking.
3. Codex: the CLI needs network access; approve the escalation or enable network for the sandbox.

## The loop
1. **Local fast checks first.** Run the project's own lint and unit tests locally when they are cheap. Do not spend
   cloud validation on code that does not compile.
2. **Commit.** Validation runs on a commit, never on a dirty tree. Work on a feature branch, not the default branch.
   When the change adds a lasting user-facing feature, add a scenario for it to `.devin/qa.toml` in the same commit
   (`p0` for core flows, otherwise `p1` with `paths`), so later rounds keep checking it.
3. **Start a round.** `client-validation-devin run --focus "<acceptance test>"`. Write the focus as the acceptance
   test of the requested change: what changed, the steps to exercise it with exact labels, and the expected result
   taken from the user's requirement, e.g. `Settings gained a 字号 slider. Open 基本设置 → 字号, drag it to the
   largest value; all pages re-layout without clipping and the value survives a restart.` The validator verifies
   it first as scenario `change`, before the regular scenarios; `--rerun` reuses the last focus. Add
   `--platforms ios,android` only when the change provably cannot affect the others. `run` returns at once with
   exit code 3.
4. **Wait.** Repeat `client-validation-devin wait --timeout 540` while it exits 3. A round usually takes 20 to 60 minutes;
   Claude Code may run it in the background instead. Start all platforms in one round; if platforms are added while
   a round runs, wait on each run with `--run <run id>` (printed by `run`).
5. **Read the result.** The exit code and `report.md` (path printed by `wait`, also `client-validation-devin report`)
   tell you what to do next. Every issue, gating or not, lists where it happens, expected vs actual, evidence
   files, the suspected code location and a suggested fix; failing tests are listed by name. Open the cited
   screenshots and look at them yourself to confirm each issue. Then use the platform's `evidence.md` index
   (screenshots grouped by check, e.g. `layout-settings`) to review the screens your change touched for problems
   the validator missed (overlap, clipping, truncation, off-screen controls, wrong theme colours). When rounds were
   split by platform or by `--rerun`, `client-validation-devin report --branch` shows the latest result of every
   platform in one report, with cross-platform root causes. Files listed under "Not downloaded" (videos,
   evidence archives) come down with `client-validation-devin fetch <platform> <name>`.
6. **Triage and fix** (details: `references/fix-loop.md`):
   - Fix "Likely shared root causes" once, in shared code.
   - `build`/`test`/`crash` before `logic` before `layout`/`visual`.
   - Treat `suggested_fix` as a hint; verify it against the code before applying.
   - `blocked` is not a product bug: fix the environment, blueprint, config or access it names.
   - Run local checks again, commit with a message naming the issue ids (e.g. `fix: android-001 toolbar overlap`).
7. **Re-validate.** `client-validation-devin run --rerun`, then wait again. It re-runs only platforms that are not green, reusing
   their warm sessions; once all are green on older commits it runs one regression pass on HEAD.
8. **Repeat 5 to 7** until `wait` exits 0 and the report's `Next:` line says every platform passed on HEAD.

## Exit codes
| Code | Meaning | Do |
| - | - | - |
| 0 | all validated platforms passed | follow `Next:` (regression pass or release gate) |
| 1 | gating issues found | triage, fix, commit, `run --rerun` |
| 2 | blocked or infrastructure | fix the named environment/config/access problem; do not touch product code for it |
| 3 | still running | `client-validation-devin wait --timeout 540` again |
| 4 | usage or config error | fix the command or `.devin/qa.toml` |
| 5 | needs a human | stop and escalate (below) |

## Stop and escalate (never work around these)
- Exit 5: an issue survived two fix rounds, `max_rounds` was reached, or Devin usage limits stopped a session
  (the human waits for the quota window, adds credits, or switches accounts with `client-validation-devin login`).
- The same blocked reason twice in a row.
- Fixing an issue would require relaxing `.devin/qa.toml` scenarios or expectations: the spec is the contract; only
  the human changes what "correct" means.

`spec_feedback` lists factual errors the validator found in the spec. Correct the spec yourself only when the code
or the repository's docs prove the validator right (a stale layout rule, a wrong label or command), commit it
separately, and mention it to the human. Anything that would turn a product defect into a pass goes to the human.

When you escalate, report: the run id, each open issue (id, severity, one line), what you tried per round, the
evidence paths, and the session URLs.

## Release
`client-validation-devin release` is the only way to release: it runs `[release].command` only when every default platform passed on
the exact HEAD commit, and only when `[release].auto = true` or the human approved (`--yes`). Otherwise it prints
READY and you report that to the human.

## Rules
- Never paste `DEVIN_API_KEY` into files, prompts, commits or logs.
- Never mark a platform as passed yourself, skip a failing platform silently, or retry a blocked round unchanged.
- Never push to the `client-validation-devin/*` refs by hand or edit the run state under `/tmp/client-validation-devin/`.
- `client-validation-devin message <platform> "<text>"` is for answering a validator, not for asking it to change code.
- Clean up after a release when asked: `client-validation-devin cleanup --remote --sessions`.

## References
- `references/fix-loop.md`: triage order, root-cause grouping, regression policy, flaky results.
- `references/cli.md`: every command, flag, file and the report fields.
- `references/troubleshooting.md`: API errors, platform availability, quota, blocked validators.
