# Graveyard Power for Kiro

Checks whether an npm or PyPI package is abandoned, deprecated or has an unfixable vulnerability before it is added to a project, and blocks installs of packages that are provably dead.

The Power has three parts:

- An MCP server, `graveyard`, with two read-only tools: `autopsy_package` and `autopsy_project`.
- Requirements: `autopsy_project` needs `syft` on `PATH` (it runs Syft to read the project); `autopsy_package` does not. See the note under `mcp.json` below.
- Three skills: `check-before-adding-dependency`, `reading-a-verdict` and `install-blocker-hook`.
- A hook template, carried by the `install-blocker-hook` skill, that blocks an install command naming a package Graveyard can show is Dead or Cursed.

The Power uses the Agent Plugins format. There is no `POWER.md`: according to the [Install powers](https://kiro.dev/docs/powers/installation/) page, `plugin.json` alone suffices for the installer.

> **Pin placeholder.** Until the release commit exists, `mcp.json` and the hook template contain the placeholder `<COMMIT_SHA>` in the `uvx --from` source. Replace it with the 40-character commit SHA of the release before relying on either.

## 1. Install the Power

### Clone and import from a folder (documented path)

```sh
git clone https://github.com/olajaido/graveyard.git
```

In Kiro, open the Powers panel and choose *Import power from a folder*, then select the `powers/graveyard` folder of the clone. This is the path described in the Install powers page.

### Import from GitHub (sub-folder URL not documented)

Kiro also offers *Import power from GitHub*. The Install powers page does not document a URL that points at a sub-folder of a repository, and `powers/graveyard` is a sub-folder. Whether that import works for this Power has not been verified. If it does not, use the clone and folder import above.

## 2. Approve `GITHUB_TOKEN` (optional)

`mcp.json` passes three environment variables to the server as references: `${GITHUB_TOKEN}`, `${GRAVEYARD_CONTACT}` and `${GRAVEYARD_MCP_ROOT}`. No value is stored in the Power. All three are optional.

- `GITHUB_TOKEN` gives the autopsy access to GitHub repository data (issue counts and similar signals). Without it the tools and the hook still run, with less evidence (see Limits).
- A value of the form `${NAME}` that was not expanded is treated as absent, not as an invalid token.
- Approve the variable in Kiro when asked. How Kiro behaves when a `${VAR}` reference is not approved is not documented and was not measured.
- The token is never printed, logged or returned by the CLI or the MCP server.

### Notes on `mcp.json`
`mcp.json` is plain JSON and cannot carry comments, so its notes are here:
- `autopsy_project(path)` runs Syft and fails with a tool error if `syft` is not on `PATH` of the server process. A GUI-launched Kiro may not inherit your shell `PATH`. `autopsy_package(purl)` needs no Syft.
- The server advertises no prompts or resources (empty lists), only the two tools.
- `<COMMIT_SHA>` in `args` must be replaced by the release commit SHA.

## 3. Install the hook through the skill

The hook is not installed automatically. Ask the agent to set it up (for example "set up the Graveyard install blocker"). The `install-blocker-hook` skill then:

1. checks whether `.kiro/hooks/dead-install-blocker.json` exists;
2. if it does not, asks you;
3. on your yes, writes the content of `skills/install-blocker-hook/references/dead-install-blocker.json` to `.kiro/hooks/dead-install-blocker.json`;
4. never overwrites an existing file;
5. tells you to start a new session, because hooks activate at session start.

You can also copy the template to `.kiro/hooks/dead-install-blocker.json` yourself.

The hook is a `PreToolUse` hook with matcher `shell` and `timeout` 20. Its command runs `graveyard check-install` through `uvx` at the pinned commit and turns every exit status other than exactly 2 into 0.

## 4. Check that it works (dry run)

The dry run needs no hook and no Kiro session. With the package installed (see section 6), or from a checkout:

```sh
graveyard check-install "npm install request"
echo $?
```

Expected: exit status `2`, with a block message on stderr naming `request`. This works without a token: the `request` verdict rests on a declared-dead signal, which does not need GitHub data.

Through `uvx`, with the same pinned source the hook uses:

```sh
uvx --from "graveyard-backend @ git+https://github.com/olajaido/graveyard.git@<COMMIT_SHA>#subdirectory=backend" graveyard check-install "npm install request"
echo $?
```

Quote the whole requirement: it contains spaces and `#`.

A command that is not an install, for example `ls`, prints nothing and exits 0.

The dry run checks the command, not that Kiro delivers it. To check that the hook is live in a session, ask the agent to run `npm install request` and see that the call is intercepted.

## 5. Exit codes

`graveyard check-install` is separate from `graveyard autopsy` and has its own table.

| Code | Meaning |
|---|---|
| 0 | Allow. Nothing to check, nothing that qualifies for a block, or the check could not be completed. A one-line note may be printed on stdout. |
| 2 | Block. At least one package qualifies. The reason is on stderr. |

No other code is ever returned. A usage error also exits 0, with a one-line note.

## 6. Limits

### Spelling of the `uvx` source

The `uvx --from "graveyard-backend[mcp] @ git+…#subdirectory=backend" graveyard-mcp` spelling (server) and the `graveyard-backend @ git+…` spelling without the extra (hook) were confirmed with uv 0.11.8 against the local checkout, using both `file://` and `git+file://` sources. The `git+https://github.com/…` form itself was verified only through `git+file`; it has not been fetched from GitHub because no pinned commit has been pushed yet.

### Token

Without `GITHUB_TOKEN`, GitHub-derived signals are missing. A package whose verdict depends on them is reported as unverified and is not gated (the note reads like `<name>@<version> unverified (no GitHub data), not gated`). Packages declared dead by their registry, and packages that are Cursed by age, can still be blocked without a token. The hook may also run without a token even if your shell has one: a GUI-launched IDE need not inherit the shell environment (not documented).

### Windows

The hook command is POSIX `sh`. Windows is not supported.

### Build-dependent payload delivery

The hook field names (`tool_input.command` for the command, the envelope's `cwd`) and the fact that exit 2 blocks the call were measured only on Kiro 1.4.86 (spike KP-S1, [`docs/SPIKES.md`](../../docs/SPIKES.md)). Third-party reports describe other builds that behave differently, for example one that sent no stdin to the hook. Other builds have not been covered. On a build that sends nothing usable, the hook receives no command and allows: the failure is silent. The MCP tools and the skills still work.

### The stdout note is best effort

A note printed on stdout at exit 0 may or may not reach the agent; whether it does was not measured. The block reason goes to stderr. In KP-S1 a stderr line from an exit-2 hook did reach the model. Do not rely on the stdout note.

### Latest-version approximation and the range rule

For a package given without an exact version (no version, `latest`, a range), the check runs against the registry's latest version. For no specifier, `latest`, `*`, or a lone `>=V`/`>V`, that is the version the package manager installs. For other ranges (`^2`, `~=1.4`, `<2`) the installed version may differ from the latest. So a range is blocked only when the package is **declared dead**. A range target that is Cursed or Dead by score is not blocked, and the note says `range not checked against <version>`.

### Redirections

From the first unquoted redirection operator (`>`, `>>`, `<`, `>&`, `&>`, `2>&1`) to the end of the segment, tokens are dropped. A package written after a redirection is missed.

### `-r` requirements files and their confinement

For `pip install -r`, `python -m pip install -r`, `uv pip install -r` and `uv add -r` (and the long forms), the hook reads the named file, subject to these rules:

- At most 5 files per command.
- The base directory is the payload's `cwd` when it is an existing absolute directory, else the process working directory. A relative path is joined to it; an absolute path is accepted only if it resolves inside it. Symlinks are followed and the result must still be inside the base.
- The target must be a regular file (not a directory, device or FIFO) of at most 1 MiB. It is opened read-only.
- A path starting with `~` or containing `$`, `*`, `?`, `[`, NUL or `://` is not opened.
- Only lines pinned with `==` or `===` become targets. Unpinned lines, URL or path lines, and nested `-r` / `-c` lines are not followed and are counted in the note. File content is never printed.
- A file that fails any rule contributes no target and is noted as not read.

`-r` does not apply to npm, pnpm, yarn or poetry.

### Fail open

A failed or incomplete check cannot be told from a safe one. A block means "known dead"; an allow is no guarantee of "healthy". The hook is a guard rail. An agent can evade it with a form the parser skips, for example `bash -c '…'`, a URL or path, an unsupported option, or a package after a redirection. The skills ask the agent not to. Every internal failure, timeout, missing `uvx` or crash exits 0, never anything but 0 or 2. A run that finds nothing to check exits 0 without output and without a network request.

### First `uvx` run and `uv tool install`

The first `uvx` run builds the package and may take longer than one hook call. What Kiro does with a run that exceeds the hook `timeout` is not documented and was not measured. To avoid the cost on every call, install the tool once at the same pin and change the hook `command` to use the installed executable:

The `uv tool install` spelling below follows the same requirement string as the `uvx --from` form; it was not run in T12.1.

```sh
uv tool install "graveyard-backend @ git+https://github.com/olajaido/graveyard.git@<COMMIT_SHA>#subdirectory=backend"
```

Then set the hook `command` in `.kiro/hooks/dead-install-blocker.json` to keep the same guard but call `graveyard check-install` directly:

```sh
if command -v graveyard >/dev/null 2>&1; then graveyard check-install; s=$?; [ "$s" -eq 2 ] && exit 2; fi; exit 0
```
