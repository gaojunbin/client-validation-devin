# Devin capability research (as of 2026-11-15)

Scope: what Devin (Cognition) offers that lets a *local* coding agent (Claude Code, Codex,
Antigravity) validate multi-platform client apps in the cloud. Every claim below links to the
page it came from. Items marked **Unverified** need a live API key to confirm.

## 1. Cloud machines per platform

| Target | Devin VM | How it is selected | Status | Usage cost vs Linux |
| - | - | - | - | - |
| Linux desktop (Ubuntu) | Linux (default) | `platform` omitted / `linux` / `default` | GA | 1x |
| Android | Linux VM + Android emulator (KVM) | blueprint installs SDK + system image | GA | 1x |
| macOS app | macOS VM (Apple silicon) | `platform: "macos"` | GA on Pro/Teams by default | 1x (promotional) |
| iOS / iPadOS | macOS VM + iOS Simulator | `platform: "macos"` | GA on Pro/Teams by default | 1x (promotional) |
| Windows app | Windows VM | `platform: "windows"` | **Limited access, contact sales** | ~1.09x |
| Any OS you own | Devin Outposts worker | `platform: "<outpost-name>"` | Pro, Max, Teams | your hardware |

Sources: [macOS support](https://docs.devin.ai/onboard-devin/environment/macos-support),
[Windows support](https://docs.devin.ai/onboard-devin/environment/windows-support),
[Android emulator](https://docs.devin.ai/onboard-devin/environment/android-emulation),
[iOS tutorial](https://docs.devin.ai/tutorial-library/ios-app) ("Pro or Teams: macOS sessions are available by default"),
[Usage](https://docs.devin.ai/admin/billing/usage),
[Outposts](https://docs.devin.ai/cloud/outposts/overview) ("available on all Pro, Max, and Teams accounts").

### macOS VM facts
- Preinstalled: Xcode 26 (default) + Xcode 27 RC, iOS 26/27 simulator runtimes, `xcodebuild`,
  `xcrun simctl`, Swift, Homebrew, Node/Python/Java/Rust, `gh`, `jq`, `ffmpeg`, Chrome.
- User `devin` (password `devin` for TCC prompts), shell zsh, repos at `/Users/devin/repos/<repo>`,
  uploaded files at `/Users/devin/.files/`.
- No physical devices (no USB passthrough), no nested virtualization (Docker runs under QEMU TCG,
  15-25x slower), profiling numbers are not representative.
- Sleep snapshots the disk; running processes (simulators, dev servers) stop and must be restarted.

### Windows VM facts
- Git Bash default shell, optional `shell: powershell` for blueprint steps, `choco` packages,
  home `/c/Users/Administrator`, Computer Use on a full Windows desktop (WPF/WinForms/etc.).
- Sessions may sleep after 30 min idle instead of 5.

### Android facts
- Runs on the Linux VM; the emulator window sits on Devin's desktop. `adb` for install, logs,
  screenshots, `uiautomator dump`; Computer Use for taps and visual checks.
- `x86_64` system images recommended; KVM acceleration now works on first start
  ([release notes 2026](https://docs.devin.ai/release-notes/2026)).

## 2. Computer Use and evidence
- Full desktop on Linux, Windows and macOS (mouse, keyboard, screenshots); agent screen is
  1024x768, recordings/screenshots captured at 2x
  ([Computer Use](https://docs.devin.ai/work-with-devin/computer-use)).
- Must be enabled once: **Settings > Devin > Sessions > Computer use** (admin).
- Testing & recordings: Devin records annotated videos and sends them as message attachments
  ([Testing & recordings](https://docs.devin.ai/work-with-devin/testing-and-recordings)).
- Chrome exposes CDP on `localhost:29229` for Playwright scripts.

## 3. Environment as code (blueprints and snapshots)
- Blueprint YAML: `initialize` (tools), `maintenance` (deps), `knowledge` (commands); one snapshot per
  platform selected by `runs-on: default|linux|macos|windows`; multi-platform via `---` documents
  ([Blueprints](https://docs.devin.ai/onboard-devin/environment/blueprints),
  [reference](https://docs.devin.ai/onboard-devin/environment/blueprint-reference)).
- Git-backed mode: `.devin/blueprint.yaml` on the default branch, synced via
  `POST /v3beta1/organizations/{org}/snapshot-setup/sync`
  ([git-backed blueprints](https://docs.devin.ai/onboard-devin/environment/git-backed-blueprints)).
- Database mode via API: `POST/PATCH /v3/organizations/{org}/snapshot-setup/blueprints`
  (`repo_name`, `contents`), then `POST .../snapshot-setup/builds`; build status
  `pending -> running -> succeeded|failed|cancelled`. Creating a repo blueprint also adds the repo to
  the environment.
- Periodic rebuilds: ~24 h (weekly for macOS). Sessions boot a fresh copy and pull latest code.

## 4. Programmatic control

### REST API v3 (base `https://api.devin.ai/v3`)
Auth: `Authorization: Bearer cog_...` (personal access token or service user key)
([Authentication](https://docs.devin.ai/api-reference/authentication),
[PATs](https://docs.devin.ai/api-reference/personal-access-tokens)). Org id is on
**Settings > Devin API**; `GET /v3/self` returns `org_id` for org-scoped principals.

| Need | Endpoint |
| - | - |
| Create session | `POST /organizations/{org}/sessions` |
| Get session (status, `structured_output`, `acus_consumed`, `pull_requests`) | `GET /organizations/{org}/sessions/{id}` |
| Send message (auto-resumes a sleeping session) | `POST /organizations/{org}/sessions/{id}/messages` `{message, attachment_urls}` |
| List messages | `GET /organizations/{org}/sessions/{id}/messages?after=&first=` |
| List attachments (`source: devin|user`) | `GET /organizations/{org}/sessions/{id}/attachments` |
| Upload a file for a session | `POST /organizations/{org}/attachments` (multipart `file`) |
| Download attachment | `GET /organizations/{org}/attachments/{uuid}/{name}` (307 to presigned URL) |
| Terminate (optionally archive) | `DELETE /organizations/{org}/sessions/{id}?archive=true` |
| Blueprints / builds | `/organizations/{org}/snapshot-setup/blueprints`, `/builds` |
| Repositories visible to Devin | `GET /organizations/{org}/repositories` |

Create-session fields that matter here
([Create Session](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions)):
`prompt` (required), `platform` (`macos`, `windows`, outpost pool; unknown values return **400 listing
the valid labels**), `repos`, `attachment_urls`, `structured_output_schema` (JSON Schema draft 7,
max 64 KB, self-contained), `structured_output_required` (default true: the agent must call
`provide_structured_output` with `is_final=true` before its turn ends), `tags`, `title`,
`max_acu_limit`, `devin_mode` (`normal|fast|lite|ultra|fusion|swe-2-*`), `session_secrets`
(`[{key, value, sensitive}]`, session-only), `secret_ids`, `knowledge_ids`, `playbook_id`,
`resumable`, `memory_enabled`.

Session status: `new|claimed|running|exit|error|suspended|resuming`; `status_detail` while running:
`working|waiting_for_user|waiting_for_approval|finished`; while suspended: `inactivity|user_request|
usage_limit_exceeded|out_of_credits|out_of_quota|...`. Sessions sleep after ~5 min idle and do not
consume usage while asleep ([Usage](https://docs.devin.ai/admin/billing/usage)).

Docs inconsistency: the attachments list is documented both as a bare array and as `{items: [...]}`;
clients must accept both.

Verified against the live API (2026-11-15, personal access token, Pro plan):
- `GET /v3/self` returns `principal_type: pat_user` and `org_id`, so `DEVIN_ORG_ID` is optional.
- The org's platform labels are `linux`, `macos`, `windows` (from the 400 on an unknown `platform`).
- Repositories list: `{items, has_next_page, end_cursor, total}` with `repo_full_name`.
- Blueprints list: `{"data": [...]}` (a third list envelope).
- One build trigger produced one build per platform (separate build ids, no platform field); build
  logs (`GET .../builds/{id}/logs` → presigned URL) are JSON lines with `phase`, `step`, `msg`.
- Session attachment `url`s point at `https://app.devin.ai/attachments/{uuid}/{name}` and return 401
  for API tokens; `GET /v3/organizations/{org}/attachments/{uuid}/{name}` with the token downloads
  them (`uuid` = `attachment_id`).
- Session ids come back without the `devin-` prefix and work as-is in every session endpoint.

### Devin MCP (`https://mcp.devin.ai/mcp`)
Tools: `devin_session_create|search|interact|events|gather`, playbooks, knowledge, schedules,
integrations, wiki tools. Claude Code: `claude mcp add -s user -t http devin https://mcp.devin.ai/mcp
-H "Authorization: Bearer <cog_key>" -H "X-Org-Id: <org>"`
([Devin MCP](https://docs.devin.ai/work-with-devin/devin-mcp)). The documented create tool lists
prompt, title, playbook, tags and ACU limit only, so platform choice and structured-output schema
are **Unverified** over MCP; the REST API is the dependable path.

### Other surfaces
- Devin CLI: `devin --cloud -p "<prompt>"`, `/platform`, `devin ssh <session>`, `devin forward`
  ([Cloud CLI](https://docs.devin.ai/cli/cloud), [SSH](https://docs.devin.ai/cli/ssh)).
- TypeScript SDK `@cognition-ai/sdk` (beta, `0.0.1-beta.N`, API may change between betas)
  with typed structured output ([SDK](https://docs.devin.ai/sdk)).
- Handoff from any agent via the Sessions API
  ([handoff](https://docs.devin.ai/work-with-devin/devin-handoff)).
- Community reference: [floweredao/devin-vm](https://github.com/floweredao/devin-vm) uses a macOS
  session as an SSH build box (`platform: "macos"`, "do nothing" prompt, keep-alive messages);
  confirms the create-session call and `/v3/self` org lookup against the live API.

## 5. Devin-side skills
Devin loads Agent Skills (`SKILL.md`) from repos at `.agents/skills`, `.devin/skills`,
`.claude/skills`, `.codex/skills` and six other folders, and from plugins; invoke with
`@skills:<name>` in any prompt, including API prompts
([Devin Skills](https://docs.devin.ai/product-guides/skills)).

## 6. Local agents: where skills live (Agent Skills standard, agentskills.io)

| Agent | User scope | Repo scope |
| - | - | - |
| Claude Code | `~/.claude/skills/<name>/SKILL.md` | `.claude/skills/` |
| Codex | `~/.agents/skills/` (symlinks followed) | `.agents/skills/` from CWD up to repo root |
| Antigravity (App/IDE/CLI) | `~/.gemini/config/skills/` (legacy `~/.gemini/antigravity/skills/`) | `.agents/skills/` |
| Devin | Customize page / plugins | `.agents/skills/`, `.devin/skills/`, ... |

Sources: [Codex skills](https://developers.openai.com/codex/skills),
[Antigravity skills](https://antigravity.google/docs/skills),
[spec](https://agentskills.io/specification).

Consequence: anything placed in a product repo's `.agents/skills/` is visible to Codex,
Antigravity *and* Devin. Devin-only instructions must not live there.

## 7. Plans and limits (self-serve)
- Pro $20/month: daily + weekly quota shared by cloud sessions, CLI and Desktop; on-demand credits
  after that; MCP integrations included
  ([Self-serve plans](https://docs.devin.ai/admin/billing/self-serve)).
- API access is listed from Pro upward (per the devin-vm README, October 2026; **Unverified** on the
  pricing page).
- Concurrent session cap for Pro is not documented; one third-party source says 10.
  **Unverified**: the CLI must handle `429` and queue.

## 8. Implications for the design
1. Every requested platform is reachable: Linux, Android and macOS/iOS today; Windows needs either
   Cognition to enable the `windows` VM or an Outpost on a Windows machine.
2. REST v3 is the control plane (platform selection, structured output, attachments, messages).
3. Structured output gives a machine-checkable report contract; attachments carry screenshots,
   logs and videos back.
4. Blueprints make per-platform toolchains reproducible and warm; without them each run pays the
   setup cost.
5. Sessions can be resumed with a message, so a fix loop can reuse a warm VM per platform.
