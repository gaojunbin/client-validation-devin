# client-validation-devin

Let your coding agent (Claude Code, Codex, Antigravity, or any agent with a shell) validate a client app on
**Devin cloud VMs**: iOS Simulator and macOS on macOS VMs, Android emulator and Linux desktop on Linux VMs,
Windows apps on Windows VMs. The agent finishes a change, Devin builds and tests it on every platform, walks
your scenarios, checks layouts in every size, theme, language and text scale, and sends back a structured report
with screenshots. The agent fixes what was found and re-validates until every platform passes. Your own machine
never boots a simulator.

```
coding agent ──commit──► client-validation-devin run ──Devin API──► one Devin validator per platform
     ▲                                                      build → tests → change under test → scenarios
     │                                                      → layout matrix → crashes/logs
     └── fix ◄── report.md: issues with location, suggested fix, screenshots ◄── structured report + evidence
```

## What you get
- Two [Agent Skills](https://agentskills.io): `client-validation-devin` (validate, fix, re-validate, release gate)
  and `client-validation-devin-setup` (onboard a repository once).
- The `client-validation-devin` CLI (Python 3.11+, standard library only) that drives the Devin API.
- A validator protocol and per-platform guides Devin follows, a JSON report contract, and Devin environment
  templates for Flutter, React Native, native Apple, native Android, Electron, Tauri and Compose Multiplatform.

## Requirements
- A Devin plan with cloud sessions and API access (Pro or higher) and a personal access token (`cog_...`).
- In Devin: connect your Git host and grant the repositories you want validated; turn on
  **Settings → Devin → Sessions → Computer use**.
- Platforms: Linux, Android and macOS/iOS VMs are available by default; Windows VMs depend on the account
  (`client-validation-devin doctor --probe-platforms` lists yours; a Windows [Outpost](https://docs.devin.ai/cloud/outposts/overview)
  is the alternative).
- Locally: git, Python 3.11+ and bash (macOS or Linux; on Windows use WSL).

## Install
One command: clones into `~/.local/share/client-validation-devin`, links the skills into Claude Code, Codex and
Antigravity, puts the CLI on your PATH, and asks for your Devin API key.

```bash
curl -fsSL https://raw.githubusercontent.com/gaojunbin/client-validation-devin/main/install.sh | bash
```

- Only some agents: `... | bash -s -- --agents claude,codex`. Skip the key for now: `--no-key`.
- Update: run the same command again. Uninstall the links: `... | bash -s -- --uninstall`.
- From a checkout: `git clone https://github.com/gaojunbin/client-validation-devin.git && cd client-validation-devin && ./install.sh`.
- Existing files are never overwritten: anything the installer did not create is left alone and reported.

## Configure the API key
1. Create a personal access token at [app.devin.ai → Settings → Devin API](https://app.devin.ai/settings/devin-api)
   (PATs tab). It starts with `cog_`; legacy `apk_` keys do not work.
2. Run `client-validation-devin login` (the installer runs it for you). The key is typed hidden, checked against
   the API, and stored with your organization id in `~/.config/client-validation-devin/env` (mode 600).
   Alternatively export `DEVIN_API_KEY` (and optionally `DEVIN_ORG_ID`); the environment wins over the file.
3. Check: `client-validation-devin available --online` in an onboarded repository, or
   `client-validation-devin doctor --probe-platforms` for the full checklist.
4. Switching to another Devin account (for example when one runs out of quota): in the new account connect the
   Git host, turn on Computer use and re-add the secrets your `.devin/qa.toml` files name, then run
   `client-validation-devin login` with its key. Environments belong to a Devin organization, so the first `run`
   in each repository stops and asks for `client-validation-devin env apply --wait` once; `doctor` lists what is
   still missing. Earlier sessions are not reused.

Never paste the key into an agent chat.

## Onboard a repository (once)
In the repository, ask your agent:

> Set up Devin cloud validation for this repo.

The `client-validation-devin-setup` skill reads the repository's own agent rules, writes `.devin/qa.toml` (what
to validate: platforms, build and test commands, devices, layout matrix, scenarios) and `.devin/blueprint.yaml`
(Devin's environment per platform), builds the Devin snapshots, runs a smoke round, and adds a conditional rule to
`AGENTS.md` / `CLAUDE.md` (below). Commit the `.devin/` folder.

## Use it from your coding agent
Ask for the feature and the validation together:

> Add a font-size slider to Settings. Then validate it on every platform with client-validation-devin and fix
> what it finds.

The agent commits, runs `client-validation-devin run --focus "<acceptance test>"`, waits (a round takes about
30 to 45 minutes per platform, platforms run in parallel), reads `report.md`, looks at the screenshots, fixes,
and runs `--rerun` until all platforms pass. Every issue in the report says where it happens, expected versus
actual, which screenshots show it, the suspected code location and a suggested fix.

| Agent | Skills folder | Invoke explicitly | Notes |
| - | - | - | - |
| Claude Code | `~/.claude/skills` | `/client-validation-devin` | can wait in the background |
| Codex | `~/.agents/skills` | `$client-validation-devin` | the CLI needs network: approve the escalation or enable sandbox network |
| Antigravity | `~/.gemini/config/skills` | `/client-validation-devin` | asks before reading the skill and running the CLI; headless `agy -p` needs permission rules |
| Any other agent | point it at `skills/client-validation-devin/SKILL.md` | | everything runs through the CLI |

## Teams: make it conditional (AGENTS.md / CLAUDE.md)
Not everyone on a team has a Devin account. Put this rule in the repository's `AGENTS.md` (have `CLAUDE.md`
import it with `@AGENTS.md`) or in `CLAUDE.md`; the setup skill adds it for you. Machines with the tool and a key
validate on Devin automatically; everyone else gets a manual check list instead of a blocked agent.

```markdown
## Client validation on Devin (only where it is set up)

After any change that can affect what a client app does or shows:
1. Run `client-validation-devin available --online` from the repository.
2. Exit code 0: cloud validation is required before you report the work as done. Follow the
   `client-validation-devin` skill: commit, run it with `--focus` written as the acceptance test of the request,
   fix what the report finds, re-run until every platform passes, and give the result with the report path.
3. Command not found or a non-zero exit: this machine is not set up, and that is fine. Do not install the tool,
   ask for keys or wait for it. Finish the work and give a manual check list (platforms, steps for each changed
   flow, what to look at). Say that the change was not validated on Devin.
4. If validation was required but could not finish (key rejected, quota used up, environment blocked), say why
   and fall back to the manual check list.
```

The full wording lives in [`skills/client-validation-devin-setup/assets/agents-snippet.md`](skills/client-validation-devin-setup/assets/agents-snippet.md).

## Commands
| Command | What it does |
| - | - |
| `login` | Store and verify your Devin API key |
| `available [--online]` | Exit 0 when this machine can validate this repository |
| `doctor [--probe-platforms]` | Full checklist: git, config, key, API, push access, repo access, VM platforms |
| `init` / `env apply --wait` / `env logs` | Create `.devin/qa.toml`; build Devin's snapshots from `.devin/blueprint.yaml`; show build warnings |
| `run [--focus TEXT] [--platforms ...] [--rerun]` | Start a round (exits 3 at once) |
| `wait --timeout 540` | Wait for the round; exits 3 while it is still running |
| `report [--branch]` | The round's report, or the latest result of every platform on the branch |
| `fetch <platform> <name>` | Download a video or evidence archive listed in the report |
| `release` | Run your release command only when every platform passed on HEAD |

Exit codes: 0 pass, 1 issues found, 2 blocked or unavailable, 3 still running, 4 usage error, 5 needs a human.
Full reference: [`skills/client-validation-devin/references/cli.md`](skills/client-validation-devin/references/cli.md).

## Limitations
- Simulators and emulators only: no physical devices, and timing is not representative.
- Each round uses Devin usage on every platform it runs; `max_parallel` and per-platform time budgets cap it.
- Apps that need sign-in need test accounts stored as Devin secrets (names go in `.devin/qa.toml`).
- Windows VMs are not enabled on every account; use an Outpost or leave Windows out.

## More
- [`DESIGN.md`](DESIGN.md): architecture, contracts, state machine, verdict policy, lessons from live runs.
- [`docs/research.md`](docs/research.md): what Devin offers (platforms, API, limits), with sources.
- Tests: `cd tests && python3 -m unittest` (offline, against a fake Devin API).

## License
[MIT](LICENSE)
