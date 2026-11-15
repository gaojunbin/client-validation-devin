# client-validation-devin: design

## 1. Goal
A local coding agent (Claude Code, Codex, Antigravity) finishes a change to a multi-platform client
app and, without a human, gets it validated on real OS environments in Devin's cloud (iOS Simulator,
Android emulator, macOS, Linux desktop, Windows), fixes what fails, re-validates, and only then
releases. The developer's laptop runs nothing heavier than an HTTP poller.

Non-goals: physical devices, performance profiling, store submission, replacing unit tests in CI.

## 2. Topology

```
 Local machine                                  Devin Cloud (one session per platform)
 ┌─────────────────────────────────┐            ┌──────────────────────────────────────┐
 │ Coding agent (writes the code)  │            │ Devin validator (read-only on code)  │
 │  skill client-validation-devin  (fix loop)     │            │  macOS VM : macOS app, iOS Simulator │
 │  skill client-validation-devin-setup (onboard) │  REST v3   │  Linux VM : Linux app, Android emu   │
 │  CLI  client-validation-devin ─────────────────┼──────────► │  Windows VM or Outpost : Windows app │
 │   git delivery · prompt builder │ sessions   │  build → tests → launch → scenarios  │
 │   poller · collector · verdict  │ messages   │  → layout matrix → structured report │
 │                                 │◄────────── │  + screenshots / logs / video        │
 └─────────────────────────────────┘ attachments└──────────────────────────────────────┘
          ▲  fix, commit, re-run                  boots from snapshot of .devin/blueprint.yaml
```

## 3. Invariants (the contract between local agent and validators)
1. **Single writer.** Only the local agent edits, commits or pushes product code. Validators never
   commit, push, open PRs or deploy. They may propose a patch in `suggested_fix`.
2. **Frozen contracts.** `.devin/qa.toml` (what to validate) and the report schema v1 (how results
   come back) are fixed for a run. A validator that disagrees with the spec reports it in
   `spec_feedback`; it does not improvise a different test.
3. **Two-attempt rule.** A validator gives any obstacle at most two distinct attempts, then reports
   it with the exact command, output excerpt and diagnosis. The local loop stops and escalates when
   the same issue survives two fix rounds.
4. **No human in the loop on the Devin side.** Validators never wait for input; the CLI answers
   `waiting_for_user` with a standard "decide or report blocked" reply.
5. **Evidence or it did not happen.** Every issue cites attached files (screenshots, logs).
6. **The CLI owns the verdict.** Devin's `verdict` is advisory; the CLI recomputes pass/fail from
   phases, issues and the project's `fail_on` severities.

## 4. Components

| Component | Location | Role |
| - | - | - |
| `client-validation-devin` skill | `skills/client-validation-devin/SKILL.md` | Procedure for the local agent: run, wait, read report, triage, fix, re-run, release gate |
| `client-validation-devin-setup` skill | `skills/client-validation-devin-setup/SKILL.md` | One-time project onboarding: doctor, `.devin/qa.toml`, `.devin/blueprint.yaml`, snapshot build, smoke run |
| CLI `client-validation-devin` | `skills/client-validation-devin/scripts/` | Python ≥ 3.11, standard library only. All API calls, git delivery, polling, artifact download, verdict |
| Validator protocol | `skills/client-validation-devin/assets/runner-protocol.md` | The prompt template every Devin session receives |
| Platform guides | `skills/client-validation-devin/assets/platforms/*.md` | Concrete commands per platform: build, launch, screenshot, logs, crash detection, UI tree, theme/locale/text-size switches |
| Report schema | `skills/client-validation-devin/assets/report.schema.json` | Sent as `structured_output_schema`; validated by Devin |
| Blueprint templates | `skills/client-validation-devin-setup/assets/blueprints/*.yaml` | Multi-platform environment starting points per stack |
| Installer | `install.sh` | Symlinks skills into Claude Code, Codex and Antigravity skill folders; CLI onto `PATH` |

Why the validator protocol is a prompt template and not a Devin-side skill: it versions together with
the CLI and the schema, needs no install step in Devin, and cannot drift. Devin-only instructions
must also stay out of a product repo's `.agents/skills/`, which Codex and Antigravity read too.

## 5. Project files (all Devin-related files live under `.devin/`)
- `.devin/qa.toml`: the validation spec. Product summary, default platforms, per-platform build/test
  commands, app ids, device matrix, layout matrix (themes, locales, text scale), scenarios
  (steps + expectations, priority, optional path globs), gate policy, release command.
  Example: `skills/client-validation-devin/assets/qa.example.toml`.
- `.devin/blueprint.yaml`: Devin's environment per platform (multi-document YAML, `runs-on`).

Credentials never live in the repo: `DEVIN_API_KEY` (a `cog_` PAT or service-user key) and
`DEVIN_ORG_ID` come from the environment or `~/.config/client-validation-devin/env`.

## 6. Flows

### 6.1 Setup (once per project; `client-validation-devin-setup`)
1. `client-validation-devin doctor --probe-platforms`: Python, git, credentials, `/v3/self`, org, available VM
   platforms (from the documented 400 response), repo visible to Devin, config validity.
2. Human step only if missing: connect the Git host to Devin; enable Computer Use; request Windows
   access or start an Outpost.
3. Detect the stack and targets; `client-validation-devin init` writes `.devin/qa.toml`; the agent fills commands,
   devices and 3-8 `p0` scenarios derived from the app's real flows.
4. Write `.devin/blueprint.yaml` from the closest template; `client-validation-devin env apply --wait` uploads it
   (database mode) and builds the snapshots.
5. Smoke: `client-validation-devin run --platforms <one> --wait`; commit `.devin/`.

### 6.2 One validation round (`client-validation-devin run`)
1. Load and validate config; resolve HEAD commit (dirty tree refused unless `--allow-dirty`).
2. Deliver code: **push** (default) force-pushes `HEAD` to the tool-owned ref
   `refs/heads/client-validation-devin/<branch>`; **bundle** uploads `git bundle` of HEAD as an attachment
   (for repos Devin cannot pull, no LFS/submodules).
3. Per platform: reuse the platform's previous session (send a round message) or create one with
   `platform`, `repos`, `structured_output_schema`, tags, limits, session secrets.
4. Persist `run.json`; return immediately (agents with command timeouts call `client-validation-devin wait`).

### 6.3 Waiting (`client-validation-devin wait --timeout N`)
Polls every `poll_seconds`. Per platform state machine:

| Observation | Action |
| - | - |
| `structured_output.round_token` matches and `report_status == "final"` | done (after up to 3 min of settling while the validator is still `working`, so late evidence uploads are not missed) |
| `waiting_for_user` / `waiting_for_approval` without final report | auto-reply (max 2), then `blocked` |
| `finished` or `suspended: inactivity` without final report | one nudge asking for the report, then `blocked` |
| `suspended` for quota/credits/limits | `infra` (abort the run) |
| `error`, or `exit` without report | `infra` |
| platform time budget exceeded | "write the report now" message, 10 min grace, then terminate → `blocked` |

Exit codes: `0` all pass, `1` actionable failures, `2` blocked/infra, `3` still running,
`4` usage/config error, `5` needs a human (max rounds or stuck issue).

### 6.4 Collect and verdict (automatic at the end of `wait`)
Downloads the final structured output, this round's attachments (through the API attachment endpoint;
the web-app URLs in attachment lists reject API tokens) and the message transcript to
`/tmp/client-validation-devin/<repo>/<branch>/runs/<run-id>/<platform>/`, writes `evidence.md` (files grouped by
check), then `report.json` and `report.md`. Videos and archives are listed, not downloaded
(`client-validation-devin fetch` gets and safely unpacks one). Verdict per platform:
`blocked` if no final report, report blocked, or checkout/build blocked by environment;
`fail` if the build failed, a test still failed on the validator's retry, or any issue severity is in
`fail_on`; otherwise `pass` (other issues are listed in full below the gate). `report` re-renders
`report.md` from `report.json`; `report --branch` merges the latest result of every platform on the
branch and groups cross-platform root causes (same scenario/screen, a shared source file in
`suspected_location`, or similar titles).

### 6.4a Acceptance of the change under test
`run --focus` carries the acceptance test of the requested change (what changed, steps, expected
result). The validator verifies it first as scenario `change`, before the regular scenarios, so a new
feature is tested even before `.devin/qa.toml` has a scenario for it; `--rerun` reuses the last focus.

### 6.5 Fix loop (driven by the skill)
1. Read `report.md`; open the cited screenshots and do an independent visual review.
2. Group issues by root cause (an issue on several platforms usually means shared code).
3. Fix minimally, run local fast checks, commit.
4. `client-validation-devin run --rerun`: re-runs non-passing platforms first; when all passed on older commits,
   re-runs those on the final HEAD (regression pass).
5. Stop on: all platforms pass on HEAD (→ release gate); `max_rounds`; an issue fingerprint
   (`id`, else hash of platform+category+title) present after two fix rounds; quota/infra errors.

### 6.6 Release gate (`client-validation-devin release`)
Runs `[release].command` only if every default platform passed on the exact HEAD commit and
`auto = true`; otherwise prints READY and leaves the decision to the human.

## 7. Validator protocol (summary of `runner-protocol.md`)
Checkout exact commit → build (env fixes allowed, code fixes forbidden) → automated tests (one retry;
only failures that reproduce fail the phase, flaky ones become `test` issues) → install/launch smoke
with crash detection → the change under test (scenario `change`) → p0 scenarios, then p1 scenarios
relevant to changed paths → layout matrix (devices/window sizes × theme × locale × text scale, with
per-platform overrides) with screenshots and UI tree overlap checks → stability sweep (logs, crashes,
ANRs, hangs) → attach screenshots individually (logs and UI trees only as issue evidence, no duplicate
archives) → final structured output. Re-runs verify the previous round's issues first and keep their ids.

## 7a. Lessons from the first live runs (2026-11-15)
Two real products, an Electron desktop app for macOS and Windows with a SwiftUI iOS app, and a
Kotlin/Jetpack Compose Android app, ran end to end on all four platforms. Fixed in the tool as a result: blueprint list envelope `{"data": [...]}`; attachment
downloads through the API endpoint; `latest` pointer and ledger races between overlapping runs; run
id collisions; per-platform layout overrides; full issue details and test failures in reports;
evidence index, archive/video handling and `fetch`; settle window after the final report; the change
under test; `env logs` because snapshot builds report success when a warm-up step only warned;
`report --branch`; doctor's HTTPS-remote hint; setup reads the repository's agent rules first.

## 8. Platform matrix

| `qa.toml` platform | Devin VM (`platform`) | Interaction | Evidence tools |
| - | - | - | - |
| `ios` | `macos` | Simulator via Computer Use, XCUITest, `simctl` | `simctl io screenshot`, unified log, `.ips` crash reports, xcresult |
| `android` | `linux` | emulator via Computer Use, `adb input`, Espresso | `screencap`, `logcat -b crash`, ANR traces, `uiautomator dump` |
| `macos` | `macos` | Computer Use, AppleScript | `screencapture`, DiagnosticReports, AX tree |
| `linux` | `linux` | Computer Use, `xdotool` | ImageMagick `import`, stderr/core dumps, AT-SPI tree |
| `windows` | `windows` or Outpost | Computer Use, PowerShell UI Automation | `CopyFromScreen`, Event Log/WER, UIA tree |
| `web` | `linux` | Chrome + Playwright over CDP `:29229` | screenshots, console errors, DOM overflow checks |

## 9. Cost controls
Blueprint snapshots (warm toolchains and caches), session reuse across rounds, re-running only
non-passing platforms until the final regression pass, optional `devin_mode` and `max_acu_limit`,
platform time budgets, p1 scenarios only when their paths changed, videos off by default.

## 10. Security
API key only from env or a user-level file, sent via unredirected header (never forwarded to
presigned storage URLs), never logged. Validators get test credentials through Devin secrets or
session-only `session_secrets`. Push mode writes only the tool-owned `client-validation-devin/*` refs. Prompts carry
`git diff --stat`, never the diff itself.

Recorded decisions (security gate review, 2026-11-15):
- `[release].command` is an argv array executed without a shell (multi-step releases belong in a
  script in the repo). It runs only through the release gate: green HEAD plus `auto = true` or the
  human's `--yes`.
- Downloads accept only `https://` URLs (or the configured API base), so a malformed attachment URL
  cannot read local files through `file://`.
- API error details are scrubbed of the API key and of every `session_secrets` value before they reach
  stderr or `run.json` (validation errors can echo request fields).
- Attachment names become single path components (`safe_name`: no separators, no leading dots).
- The state root `/tmp/client-validation-devin` is created with mode 0700: reports, transcripts and screenshots can
  contain application data.
- Issue fingerprints use truncated SHA-256; they are identifiers, not a security control.

## 11. Cross-agent compatibility
Skills follow the Agent Skills standard (`name`, `description`, Markdown body, `scripts/`,
`references/`, `assets/`). Everything executable is one CLI on `PATH`, so any agent with a shell can
drive it. Long waits are chunked (`wait --timeout`, exit code 3) because Codex and Antigravity may cap
command duration; Claude Code may also run `wait` in the background.

## 12. Risks and open decisions

| Risk / decision | Mitigation / default |
| - | - |
| Windows VM not enabled on the account | `doctor` reports it; options: request access, Outpost on a Windows box, or drop `windows` from `default_platforms` |
| Platform labels differ (`linux` vs `default`) | CLI retries with labels parsed from the 400 response |
| Concurrent-session cap unknown | CLI backs off on `429`; `max_parallel` setting |
| Validator flakiness | scripted tests where possible, explicit scenario steps, two-attempt rule, local visual review |
| Scratch branches on the remote | tool-owned namespace, `client-validation-devin cleanup` |
| Structured output semantics across turns | `round_token` + `report_status` inside the payload decide freshness |

## 13. Roadmap
Layout-lint helper shipped to the VM (UI tree → overlap/off-screen findings), SSH remote-exec mode
for fast deterministic test re-runs, PR comment with the summary and session links, baseline
screenshot diffs, TestFlight / Play internal-track distribution after a green run.
