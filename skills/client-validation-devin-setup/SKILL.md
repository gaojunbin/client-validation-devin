---
name: client-validation-devin-setup
description: One-time onboarding of a client-app repository for Devin cloud validation with the client-validation-devin skill. Use when a project has no .devin/qa.toml, when `client-validation-devin doctor` fails, when a platform is added, or when asked to set up or repair Devin validation, blueprints or cloud environments for iOS, Android, macOS, Windows, Linux or web builds. Writes .devin/qa.toml and .devin/blueprint.yaml, builds the Devin snapshots, and proves the setup with a smoke round.
compatibility: Needs the client-validation-devin CLI (installed with the client-validation-devin skill), git, Python 3.11+, network access to api.devin.ai and DEVIN_API_KEY.
metadata:
  version: "0.1.0"
---

# client-validation-devin-setup: onboard a product repository

Outcome: `client-validation-devin doctor --probe-platforms` passes, `.devin/qa.toml` describes what to validate,
`.devin/blueprint.yaml` gives every target platform a warm Devin snapshot, and one smoke round has run.
`client-validation-devin` must be on PATH (or call `<client-validation-devin skill folder>/scripts/client-validation-devin`).

## Steps
1. **Doctor.** Run `client-validation-devin doctor --probe-platforms`. Fix what you can; collect the human-only items (below)
   and ask for them in one message. Note which VM platforms the organization offers.
2. **Inventory the project.** Read the repository's agent instructions first (`CLAUDE.md`, `AGENTS.md`,
   contributing docs) and obey them in everything you write: forbidden strings (for example server addresses that
   may live in one file only), test environments, language and commit conventions. Identify the stack and the
   shipped platforms from the files listed in `references/stacks.md`. Read the README, UI specification, app entry
   points and navigation to learn the real screens, exact labels and flows; when design docs revise themselves,
   the latest section wins.
3. **Write the spec.** `client-validation-devin init`, then edit `.devin/qa.toml`:
   - `[product]`: name and a factual two-sentence summary; `repo` only if the remote URL is not `owner/name`.
   - `[run].default_platforms`: the shipped platforms the organization can run. A platform without a VM (often
     `windows`) stays out of the defaults until the human gets access or sets up an Outpost.
   - `[platforms.*]`: `setup`, `build`, `test`, `artifact`, `app_id`, and `devices` (mobile) or `window_sizes`
     (desktop) from `references/stacks.md`, adjusted to this project. Verify every command against the project's
     own scripts; do not invent targets.
   - `[layout]`: themes the app supports, the shipped locales plus one long-string locale, text scales. A platform
     that differs (for example a desktop app without a dark theme) overrides them with its own `themes`, `locales`
     or `text_scale` keys. When the language is an in-app setting rather than the OS locale, say so in `notes`.
   - `[[scenarios]]`: see "Writing scenarios".
   - `[secrets]`: names only. Test accounts live in Devin secrets (human step) or local env vars (`from_env`).
   - `[release]`: leave `command = []` and `auto = false` unless the human specified both. The command is an argv
     array run without a shell; put multi-step releases in a script.
4. **Write the environment.** Copy the closest `assets/blueprints/<stack>.yaml` to `.devin/blueprint.yaml`, delete
   the documents for platforms not shipped, align tool versions with the project files (Flutter/Node/JDK/SDK
   levels, Xcode scheme), and keep the `knowledge` build commands identical to `.devin/qa.toml`.
5. **Build the snapshots.** `client-validation-devin env apply --wait` (repeat `client-validation-devin env status
   --build <id> --wait` while it exits 3). One trigger rebuilds every platform's snapshot for every configured
   repository. A build reports success even when a warm-up step only printed a warning, so read the summary that
   follows (or `client-validation-devin env logs`): each repository should show its build result
   (`BUILD SUCCESSFUL`, `** BUILD SUCCEEDED **`) and no `WARN` line. Fix the blueprint and apply again on failure.
   Two failed fixes: stop and report the log excerpt to the human.
6. **Review a prompt.** `client-validation-devin run --dry-run` and read one rendered `prompt.md` end to end: commands, devices and
   scenarios must be exactly what a tester needs.
7. **Smoke round.** `client-validation-devin run --platforms <one target>` then `client-validation-devin wait --timeout 540` until it stops
   returning 3. `blocked` means the setup is wrong (fix blueprint or spec); product issues mean the setup works.
   Then run the remaining default platforms once.
8. **Tell the project's agents.** Add the block in `assets/agents-snippet.md` to the repository's agent
   instructions, adapted to its platforms: into `AGENTS.md` when it exists (and make sure `CLAUDE.md` imports it
   with `@AGENTS.md`), otherwise into `CLAUDE.md`. The block makes validation conditional on
   `client-validation-devin available`, so contributors without Devin fall back to manual checks. Show the human the
   diff before committing it.
9. **Commit** `.devin/qa.toml`, `.devin/blueprint.yaml` and the instructions change on the working branch. Ask
   before pushing to the default branch.
10. **Report**: platforms configured, platforms unavailable and why, open human steps, smoke results.

## Human-only steps (ask; never work around them)
- Create a personal access token (Settings > Devin API > PATs) and store it with `client-validation-devin login`
  (hidden input; never ask the human to paste the key into the chat).
- Connect the Git host to Devin and grant this repository (Settings > Integrations) for push delivery.
- Turn on Computer Use (Settings > Devin > Sessions); admin only.
- Windows: request Windows VMs from Cognition, or run `devin worker start --outpost=<name>` on a Windows machine
  with Chrome and set `[platforms.windows].vm = "<name>"`.
- Store app test accounts as Devin secrets; decide the release command and whether releases are automatic.

## Writing scenarios
- 3 to 8 `p0` scenarios covering the core journeys: first launch, sign-in (if any), the main create/edit/delete
  flow, navigation to every top-level section, settings. Add `p1` scenarios for secondary features with `paths`
  globs so they run only when that code changes.
- Steps a stranger can follow: exact button labels, exact input values, one action per step, starting from a
  stated state (fresh install, signed in).
- Expectations checkable by looking at the screen: what text, state or element must be visible. No "works
  correctly".
- Platform-specific gestures belong in the step ("swipe left on mobile, right-click on desktop") or in a scenario
  limited with `platforms = [...]`.

## References
- `references/stacks.md`: detection signals and per-stack `[platforms.*]` blocks.
- `assets/blueprints/`: flutter, react-native, apple-native, android-native, electron, tauri, compose-multiplatform.
- `assets/agents-snippet.md`: the conditional validation rule for the repository's `AGENTS.md` / `CLAUDE.md`.
- The `client-validation-devin` skill's `references/cli.md` and `references/troubleshooting.md`.
