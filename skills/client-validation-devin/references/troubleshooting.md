# Troubleshooting

| Symptom | Cause | Fix |
| - | - | - |
| `DEVIN_API_KEY is not set` | no credential | Human: app.devin.ai > Settings > Devin API > PATs > create; `export DEVIN_API_KEY=cog_...` or put it in `~/.config/client-validation-devin/env` |
| `must be a v3 credential starting with cog_` | legacy `apk_` key | create a PAT or service-user key |
| HTTP 401 | expired or revoked key | new key |
| HTTP 403 on sessions | the key's role lacks session permissions, or the plan has no API access | Member/Admin role; Pro or higher plan |
| `could not resolve the organization` | principal without an org | set `DEVIN_ORG_ID` (top of Settings > Devin API) |
| HTTP 400 mentioning `platform` | VM label not offered to this org | `client-validation-devin doctor --probe-platforms`; fix `[platforms.*].vm`. Windows: request access from Cognition, or run a Windows Outpost (`devin worker start --outpost=<name>` on a Windows machine with Chrome) and set `vm = "<outpost name>"` |
| platform stays `pending` | rate limit or concurrent-session cap | wait keeps retrying; lower `[run].max_parallel` or run fewer platforms |
| `session suspended: out_of_quota` (or credits, limits) | Devin usage exhausted | human tops up on-demand credits or waits for the quota window |
| `still waiting_for_approval` | the session needs approval in the Devin UI | human approves once; consider disabling approval requirements for API sessions |
| `git push --dry-run failed` | no push rights to origin, or protected `client-validation-devin/*` | grant push rights or switch `[delivery].mode = "bundle"` |
| push fails with "Repository not found" on an HTTPS remote (e.g. after `gh repo clone`) | git has no HTTPS credentials; this machine pushes over SSH | `git remote set-url origin git@github.com:<owner>/<repo>.git` |
| snapshot build "succeeded" but sessions redo installs | a warm-up step failed and only printed a warning | `client-validation-devin env logs`; fix `.devin/blueprint.yaml`; `env apply --wait` |
| `repository access` fails in doctor | repo not connected to Devin | human connects the Git host and grants the repo (Settings > Integrations) |
| validator `blocked`: toolchain missing | no blueprint or an outdated snapshot | write `.devin/blueprint.yaml`, `client-validation-devin env apply --wait` |
| validator `blocked`: emulator/simulator will not boot | VM image issue | re-run once with `--fresh`; if it repeats, fix the blueprint (x86_64 image, AVD name) |
| report says `no final report for this round` | validator ran out of time or ignored the protocol | read `transcript.md`; raise `[run].timeout_minutes` or trim the layout matrix |
| `Missing evidence files` | validator named files it did not attach | ask it via `client-validation-devin message`, or re-run |
| bundle mode: build fails on assets | LFS objects or submodules are not in bundles | use push mode |
| Codex: network errors | sandbox blocks network | approve the escalation or enable network access for the workspace sandbox |
