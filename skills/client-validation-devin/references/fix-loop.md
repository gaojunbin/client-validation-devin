# Fix loop in detail

## 1. Read the round
1. `report.md` top: overall verdict, `Next:` line, per-platform table.
2. "Needs a human": stop here if present (see SKILL.md).
3. "Likely shared root causes": issues on several platforms that match by category and scenario or title.
4. Per platform: phases line, reasons, gating issues (with evidence paths), issues below the gate, spec feedback.
5. Open every evidence screenshot of a gating issue. Then open the remaining screenshots of the changed screens and
   look for defects the validator did not report. Report any you find to the human with the file path; fix them only
   when they are clearly caused by your change.

## 2. Classify each gating issue

| Signal | Likely cause | First move |
| - | - | - |
| Same issue on 2+ platforms | shared code (business logic, shared UI, layout constants) | fix once in shared code |
| One platform, `build` | platform toolchain, conditional compilation, missing platform dependency | read `log_excerpt`, reproduce the build flags locally if possible |
| One platform, `crash` | platform API misuse, permissions, lifecycle, threading | read the attached crash log; map frames to code |
| One platform, `layout` on the smallest device/size only | fixed sizes, missing scroll/flex, safe areas | make the layout adaptive; never special-case the device |
| Only `xl` text scale or a long locale | fixed heights, single-line labels, truncation | allow wrapping or growth; keep tap targets |
| Only dark theme | hard-coded colours | use theme tokens |
| `logic` | wrong behaviour | read repro steps; write or extend a unit test that fails first |
| `environment` category or verdict `blocked` | VM, blueprint, credentials, access | fix `.devin/blueprint.yaml`, secrets or config; `client-validation-devin env apply --wait` |

## 3. Fix rules
- Smallest change that fixes the root cause; no device-specific hacks.
- Add or update an automated test when the defect is testable without a GUI.
- Run the local fast checks again before committing.
- One commit per root cause is easiest to trace; mention the issue ids in the message.
- Never weaken a test, delete a scenario or lower `fail_on` to get green.

## 4. Re-run policy (automatic with `client-validation-devin run --rerun`)
1. Re-runs every default platform that is not green yet, in its previous session (warm caches). Validators verify the
   previous issues first and keep their ids; fixed ones appear under "Fixed since the previous round".
2. When all default platforms are green but some passed on older commits, `--rerun` runs those on HEAD: a fix for one
   platform can break another.
3. When every default platform passed on HEAD, `--rerun` says "Nothing to run" and you go to `client-validation-devin release`.
- `--fresh` forces new sessions (use it when a session looks confused or its VM state is suspect).
- `--platforms` narrows a round; use it only when the change cannot affect the other platforms.

## 5. Stuck and flaky
- An issue id or fingerprint present in three consecutive reports (it survived two fixes) makes the round exit 5.
- A validator reports an issue that its own screenshot contradicts: record it for the human and re-run that platform
  once with `--fresh`. If it repeats, escalate.
- Different results for the same commit across rounds: treat as flaky, escalate with both report paths.

## 6. Budget
Each round costs Devin usage on every platform it runs. Prefer fewer, well-checked fix rounds over many speculative
ones; batch all fixes from one report into the next round.
