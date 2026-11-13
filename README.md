# Graveyard

Dependabot upgrades what's alive. Graveyard deals with what's dead.

Graveyard checks whether npm and PyPI packages are abandoned, deprecated or have an unfixable vulnerability.

## Kiro Power

The `powers/graveyard` folder is a Kiro Power in the Agent Plugins format. It adds:

- an MCP server, `graveyard`, with two read-only tools: `autopsy_package` and `autopsy_project`;
- skills, including `install-blocker-hook`, which carries a hook template that blocks an install command naming a package Graveyard can show is Dead or Cursed.

To install it:

```sh
git clone https://github.com/olajaido/graveyard.git
```

In Kiro, open the Powers panel, choose Add Custom Power, then *Import power from a folder* and select `powers/graveyard` in the clone.

The hook is not installed automatically: ask the agent to set it up through the `install-blocker-hook` skill. The hook fails open, so a failed or incomplete check allows the command.

See [`powers/graveyard/README.md`](powers/graveyard/README.md) for the full install steps, the dry-run check, exit codes and limits.
