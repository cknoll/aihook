---
name: aihook
description: "Pause a running Python script and explore or manipulate its live namespace over HTTP from an AI coding agent. Use for debugging hard-to-reproduce runtime state, inspecting real (not mocked) objects, and trying fixes against the live process before editing source files. Includes a CLI (aihook) with lock-file-based session discovery."
version: "0.1.7"
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
   `aihook-host.log` is the recommended name for the log file. If you need
   multiple log files append a number, e.g. `aihook-host1.log` etc.

2.
   - Interact with the paused script. The CLI waits up to 180s by default
   for `./aihook-lock.yml` to appear, validates that the process is alive and
   the port is responding, then resolves the port automatically:
      ```bash
      aihook 'complex_var["nested"]["value"]'
      aihook -f snippet.py
      ```
   - Use `-f FILE` to reuse complex testing snippets after editing the host
   code — rerun the same file after each change. `aihook-snippet.py` is the
   recommended name. If you need multiple snippets append a number, e.g.
   `aihook-snippet1.py` etc.

   - If 180s is not enough (rare), override with `--wait`:
      ```bash
      aihook --wait 600 'x'
      ```
   - When the session is found, the CLI prints how long it waited. If the
   timeout expires without finding a healthy session, it exits with a clear
   error — check the host script's log file for crashes.

4. End the session:
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
- `aihook -f -` — same, but read the file from stdin.
- `aihook -` — read code from stdin (also the default when stdin is piped).
- `aihook --vars` — list all names in the session namespace with their types. Useful as a first probe to discover what's in scope.
- `aihook --fresh '<code>'` — run code in a copy of the namespace; changes do not affect the host's live state. Safe for exploratory mutations.
- `aihook --exit` — send `exit()` to shut the session down.
- `aihook --status` — show whether a session is active, stale, or absent (exits 0 if healthy).
- `aihook --clean` — remove a stale lock file; refuses if the session is active.
- `aihook -p PORT` — target a specific port (skips lock-file discovery).
- `aihook --lockfile PATH` — use a custom lock-file path.
- `aihook --wait SECONDS` — how long to wait for a healthy session (default 180s). Increase
  for unusually slow startup; if it times out, check the host script's log for crashes.

Exit code is non-zero if the remote code raised or wrote to stderr.

`-f FILE` is opened by the CLI process (agent side), so relative paths
resolve against the **agent's** current working directory, not the host
script's. Use an absolute path (e.g. `-f "$PWD/snippet.py"`) if you are
not certain the cwds match, or if your shell tool chains `cd` commands
unreliably.

## Auto-print last expression

The REPL auto-prints the last expression of any command (unless the value is
`None`). You don't need to wrap probes in `print(...)`.

Single expression:
```
aihook 'complex_var["nested"]'
# -> {'value': 42, 'items': [1, 2, 3, 4]}
```

Multi-line snippet ending in an expression (Jupyter-style):
```python
# snippet.py
import json
json.dumps(complex_var, indent=2)
# -> '{\n  "nested": ...\n}'
```

Statements that are **not** expressions (`=`, `def`, `for`, `return`, etc.)
do not produce output unless you add explicit `print()` calls:
```python
# snippet.py — for loop needs explicit print
for k, v in data.items():
    print(k, v)
```

## Session discovery

On startup, the host writes `./aihook-lock.yml` in its current working
directory, containing `pid`, `port`, `cwd`, `start_time`, `script`,
`version`. The file is removed on clean shutdown. The banner also prints the source file and
line number where `agent_hook()` was called, which is useful when a script
has multiple hook points.

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

## Diagnosing a missing session

If `aihook --status` reports no active session (or `--wait` times out),
the host script likely crashed before or inside `agent_hook()`. Read the
log file you redirected output to when launching the host:

```bash
cat aihook-host.log
```

This will show any Python traceback from the host process. There is no
other signal — aihook does not write a crash breadcrumb file.

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
