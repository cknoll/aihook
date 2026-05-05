---
name: aihook
description: "Pause a running Python script and explore or manipulate its live namespace over HTTP from an AI coding agent. Use for debugging hard-to-reproduce runtime state, inspecting real (not mocked) objects, and trying fixes against the live process before editing source files. Includes a CLI (aihook) with lock-file-based session discovery."
version: "0.1.2"
---



# aihook — Agentic REPL Skill

Pause a running Python script and explore / manipulate its live namespace
over HTTP. Designed to be driven by an AI coding agent.

## When to use

- Debugging hard-to-reproduce runtime state.
- Exploring real (not mocked) objects: shapes, keys, attributes.
- Trying fixes against the live process before editing source files.

## Install the hook in the host script

```python
from aihook import agent_hook
agent_hook()
```

Calling `agent_hook()` with no arguments uses the caller's globals and
locals (locals override globals on name collision). It starts an HTTP REPL
bound to `127.0.0.1` on a free port in `5001-5101` and blocks until
`exit()` is sent.

## Canonical agent workflow

1. Start the host script **in the background** with output redirected to a
   log file:
   ```bash
   python path/to/host_script.py > aihook-host.log 2>&1 &
   ```
   **Do not run the host script in the foreground.** It will not return
   until `exit()` is sent, which would block the agent's shell turn.

2. Interact with the paused script. The CLI automatically waits up to 5s
   for `./aihook-lock.yml` to appear and resolves the port from it, so no
   explicit wait step is needed:
   ```bash
   aihook 'complex_var["nested"]["value"]'
   aihook -f snippet.py
   ```
   Use `-f FILE` to reuse complex testing snippets after editing the host
   code — rerun the same file after each change. If the host script takes
   longer than 5s to reach `agent_hook()`, override the timeout:
   ```bash
   aihook --wait 30 'x'
   ```

3. End the session:
   ```bash
   aihook --exit
   ```

**Iterative probe loop.** For anything beyond short snippets (1-5 lines),
keep a `snippet.py` next to the host script and rerun it after each edit:
```
# edit snippet.py
aihook -f snippet.py
# observe, edit snippet.py again, repeat
```
This is the primary workflow; the single-expression form is for quick
probes only.

## CLI reference

- `aihook '<code>'` — send code to the active session.
- `aihook -f FILE` — send the contents of FILE as the command.
- `aihook -` — read code from stdin (also the default when stdin is piped).
- `aihook --exit` — send `exit()` to shut the session down.
- `aihook -p PORT` — target a specific port (skips lock-file discovery).
- `aihook --lockfile PATH` — use a custom lock-file path.
- `aihook --wait SECONDS` — how long to wait for the lock file (default 5s).

Exit code is non-zero if the remote code raised or wrote to stderr.

`-f FILE` is opened by the CLI process (agent side), so relative paths
resolve against the **agent's** current working directory, not the host
script's. Use an absolute path (e.g. `-f "$PWD/snippet.py"`) if you are
not certain the cwds match, or if your shell tool chains `cd` commands
unreliably.

## Auto-print last expression

If the submitted command parses as a single expression, its `repr()` is
printed automatically (unless the value is `None`). You don't need to wrap
probes in `print(...)`.

```
aihook 'complex_var["nested"]'
# -> {'value': 42, 'items': [1, 2, 3, 4]}
```

Statements (assignments, `def`, `for`, ...) and multi-statement blocks behave as in a normal REPL. Single expressions auto-print their `repr()`; multi-statement code executes fully, with output from explicit `print()` calls or error tracebacks.

## Session discovery

On startup, the host writes `./aihook-lock.yml` in its current working
directory, containing `pid`, `port`, `cwd`, `start_time`, `script`. The
file is removed on clean shutdown.

**Assumption: at most one aihook process per working directory.** If a
second host script is started in the same cwd while another is active, it
will refuse to start and point you to the existing lock file. Stale lock
files (pid no longer alive) are overwritten automatically.

Lock-file discovery does **not** walk up parent directories — `aihook`
only looks at `./aihook-lock.yml` in the invoking shell's exact cwd.
Run `aihook` from the same directory as the host script.

If the host process is killed uncleanly (e.g. `SIGKILL`, OOM), the lock
file may remain. A subsequent `agent_hook()` call in the same cwd will
detect this automatically (pid not alive) and overwrite it. To clean up
manually, just `rm ./aihook-lock.yml`.

## CPython caveat: local-variable write-back

Rebinding a **local** variable of the calling function from inside the
REPL does *not* write back to that function's fast-locals. This is the
same limitation as `pdb`:

```python
# In host_script.py inside my_function():
#     x = 1
#     agent_hook()
#     print(x)   # will still print 1, even if you did `x = 2` via aihook
```

**Mutating mutable objects works as expected:**

```python
complex_var["nested"]["items"].append(99)   # visible in the host afterwards
```

Prefer mutation for testing fixes. To change a simple local, mutate a
container, a module-level global, or an object attribute instead.

## Environment variables

- `AIHOOK_PORT=NNNN` — force a specific port.
- `AIHOOK_PORT_RANGE=LO-HI` — override the default `5001-5101` range.

## Agent-specific learnings library

For niche, agent-specific topics (e.g., specific Python package quirks, custom workflow tips) that are too detailed for this main skill file, refer to the `learnings` directory.

The `learnings` directory is managed by `aihook` and stored in your platform's user data directory (e.g., `~/.local/share/aihook/learnings` on Linux, `~/Library/Application Support/aihook/learnings` on macOS, `C:\Users\<User>\AppData\Local\aihook\learnings` on Windows). It is created when you run `aihook --bootstrap`.

The directory contains markdown files named `topic_<name>.md` (e.g., `topic_numpy.md`) covering independent topics relevant to multiple agent sessions. Default files (like `README.md`) are copied from the aihook package; user-added topic files are never overwritten.

Add your own topic files to this directory as your agents accumulate learnings.
