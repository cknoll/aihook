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

## CLI reference

- `aihook '<code>'` — send code to the active session.
- `aihook -f FILE` — send the contents of FILE as the command.
- `aihook -` — read code from stdin (also the default when stdin is piped).
- `aihook --exit` — send `exit()` to shut the session down.
- `aihook -p PORT` — target a specific port (skips lock-file discovery).
- `aihook --lockfile PATH` — use a custom lock-file path.
- `aihook --wait SECONDS` — how long to wait for the lock file (default 5s).

Exit code is non-zero if the remote code raised or wrote to stderr.

## Auto-print last expression

If the submitted command parses as a single expression, its `repr()` is
printed automatically (unless the value is `None`). You don't need to wrap
probes in `print(...)`.

```
aihook 'complex_var["nested"]'
# -> {'value': 42, 'items': [1, 2, 3, 4]}
```

Statements (assignments, `def`, `for`, ...) behave as in a normal REPL.

## Session discovery

On startup, the host writes `./aihook-lock.yml` in its current working
directory, containing `pid`, `port`, `cwd`, `start_time`, `script`. The
file is removed on clean shutdown.

**Assumption: at most one aihook process per working directory.** If a
second host script is started in the same cwd while another is active, it
will refuse to start and point you to the existing lock file. Stale lock
files (pid no longer alive) are overwritten automatically.

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

## Non-goals

- Authentication / TLS.
- Remote (non-localhost) usage.
- Multi-client concurrency in a single session.
