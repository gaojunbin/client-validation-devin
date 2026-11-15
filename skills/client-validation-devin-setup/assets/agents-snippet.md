## Client validation on Devin (only where it is set up)

This repository can be validated on Devin cloud VMs (macOS, Windows, iOS Simulator, Android emulator,
Linux) with the `client-validation-devin` skill. Whether that is required depends on the machine you run
on, not on the person: some contributors have no Devin account, and their changes are verified by hand.

After any change that can affect what a client app does or shows:

1. Run `client-validation-devin available --online` from the repository.
2. Exit code 0: cloud validation is required before you report the work as done. Follow the
   `client-validation-devin` skill: commit, run it with `--focus` written as the acceptance test of the
   request (what changed, the steps to exercise it, the expected result), fix what the report finds,
   re-run until every platform passes, and give the result with the report path.
3. Command not found or a non-zero exit: this machine is not set up for cloud validation, and that is
   fine. Do not install the tool, ask for keys or wait for it. Finish the work and give a manual check
   list instead: the platforms to open, the steps for each changed flow, and what to look at (smallest and
   largest window or device, dark mode, every interface language, crashes). Say that the change was not
   validated on Devin.
4. If validation was required but could not finish (key rejected, Devin quota used up, environment
   blocked), say why and fall back to the manual check list of step 3.
