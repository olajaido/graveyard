---
name: install-blocker-hook
description: Install the Graveyard dead-install blocker hook into the project's .kiro/hooks folder. Use when setting up Graveyard, or when the dead-install-blocker hook is missing.
---

# Install the dead-install blocker hook

A power cannot register a hook by itself, so the hook ships as a template in this skill. Copy it into the project once, with the user's consent.

## Steps

1. Check whether `.kiro/hooks/dead-install-blocker.json` exists. If it does, stop and tell the user it is already installed. Never overwrite an existing file.
2. If it does not exist, ask the user whether to install it.
3. On yes, read `references/dead-install-blocker.json` and write its content, unchanged, to `.kiro/hooks/dead-install-blocker.json`.
4. Tell the user to start a new session, because hooks activate at session start.

## What to tell the user

- Before any shell command, the hook checks whether it installs packages with npm, pnpm, yarn, pip, uv or poetry.
- It blocks the command only when it can show that a package is Dead or Cursed. The reason appears in the tool result.
- It fails open: if the check cannot run, times out, or the command is not recognised, the command goes ahead.
- It needs `uvx` on the PATH. The first run builds the package and can be slow.
- It runs nothing from the packages and installs nothing itself.
