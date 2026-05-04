# aihook Improvement — Implementation Plan

This file is the prompt for a *new* aider session. In that session, implement
the changes described below in the `aihook` package. Treat this document as the
authoritative spec; if something is ambiguous, ask before coding.

## Goal

Turn `aihook` into a smooth, low-boilerplate skill that an aider agent can use
to pause a running Python script and interactively explore/manipulate its
namespace via HTTP.

## Files in scope

- `src/aihook/core.py` — server + `agent_hook()`
- `src/aihook/cli.py` — new CLI `aihook`
- `src/aihook/__init__.py` — re-exports
- `pyproject.toml` — register the `aihook` console script (if not already)
- `SKILL.md` — new, top-level skill documentation
- `tests/the-test-script.py` — update to new argument-less API
- `tool-description.md` — can be removed or replaced by `SKILL.md`
- tests under `tests/` — add an integration test

## Feature list

### 1. Argument-less `agent_hook()`

- Signature: `def agent_hook(namespace=None, port=None): ...`
- When `namespace is None`, use `inspect.currentframe().f_back` to build a
  namespace from the caller's `f_globals` and `f_locals` (locals override
  globals on key collision).
- Document the CPython limitation in SKILL.md: rebinding a *local* name inside the REPL
  does **not** write back to the caller's local variable (fast locals). Mutating
  mutable objects does work. Same limitation as `pdb`.

### 2. Dynamic port allocation

- Default port range: 5001–5101, overridable via env var `AIHOOK_PORT_RANGE`
  (format `"5001-5101"`) or explicit `port=` argument / `AIHOOK_PORT`.
- Pick the first free port by trying to bind; skip busy ones.
- Print **two** lines on startup:
  - Human-readable: `AIHOOK AgenticREPL: HTTP server running on http://127.0.0.1:<port>/execute`
  - Machine-parseable: `AIHOOK_PORT=<port>`
- Immediately call `sys.stdout.flush()` after these banner lines. Add a
  short comment explaining why: when the host script's stdout is a pipe
  (e.g. an agent runner that captures output), Python uses block buffering
  and the banner would otherwise not be visible to streaming consumers
  until much later. The lock file is the authoritative discovery channel,
  but a promptly-flushed banner helps humans and streaming agents.
- Bind to `127.0.0.1` only.

### 3. Session discovery

- On startup (i.e. when `agent_hook()` is called), write a YAML lock file `./aihook-lock.yml` in the current
  working directory (i.e. the cwd of the host script). The file contains:
  - A leading comment line, e.g.:
    `# This file (created: {timestamp}) coordinates the client-server connection`
    `# for the aihook skill. It is safe to delete if no aihook-enabled process`
    `# is currently running in this directory.`
  - Keys: `pid`, `port`, `cwd`, `start_time`, `script` (best-effort from
    `sys.argv[0]`).
- Before creating the lock file, check whether one already exists in the cwd:
  - If it exists and its `pid` is still alive, the host script must exit
    immediately with a clear error message explaining that another aihook
    session is active in this directory and pointing to the lock file.
  - If it exists but the pid is stale, overwrite it (and log a note).
- Remove the lock file on clean shutdown and via `atexit`.
- Primary discovery mechanism for the CLI: read `./aihook-lock.yml` from the
  current working directory. The CLI also accepts `--lockfile PATH` to point
  at an explicit lock file location.
- Assumption: at most one aihook process per working directory.
- Use PyYAML for reading/writing; add it to `requirements.txt`.

### 4. CLI `aihook`

Implement in `src/aihook/cli.py` using `argparse`. Options:

- Port resolution order (first match wins):
  1. explicit `-p/--port PORT`
  2. `--lockfile PATH` → read `port` from that YAML file
  3. `./aihook-lock.yml` in the current working directory (also: see `--lockfile` option below). Note: if this file does not exists `aihook` should wait for either 5s (default) or the time specified by `--wait`.
  If none of these yield a port, error out with a helpful message.

- `aihook '<code>'` — send code to the active session (port resolved as
  above; this also holds for the following commands).
- `aihook '<code>'` — target a specific port.
- `aihook -f FILE` — send contents of FILE as the command. →
  document in SKILL.md that this allows agents to reuse testing code snippets
  (e.g. after changing the "host"-code).
- `aihook -` or piping via stdin — read code from stdin when no
  positional arg is given and stdin is not a TTY.
- `aihook --wait SECONDS` — block until a valid lock file
  appears (and its pid is alive). Exit
  non-zero on timeout. Can be combined with a command, reading from stdin or from a file: first wait, then send. If this is not specified `aihook` should wait for 5s (default for `.aihook-lock.yml` to appear, see above)
- `aihook --exit` — send `exit()` to a session.
- `aihook --lockfile PATH` — use the given lock file instead of the one in
  cwd. Waiting logic applies nevertheless.
- Exit code: non-zero if the executed code produced stderr output or raised.

Implementation note: use `urllib.request` (stdlib) rather than shelling out to
`curl`, to avoid a runtime dependency.

### 5. Auto-print last expression

In `AgenticREPL.execute_command`, if the submitted command parses as a single
expression (try `compile(src, '<agent>', 'eval')`), evaluate it and print
`repr(result)` (unless result is `None`). Otherwise fall back to the current
`InteractiveConsole.push` behavior for statements. This saves the agent from
wrapping everything in `print(...)`.

### 6. Structured output (optional, keep simple)

Note: this feature can be implemented later omit for now.

Keep the response body as plain text by default (back-compat with curl).
Add `?format=json` query param support returning
`{"stdout": "...", "stderr": "...", "result_repr": "...", "exception": null|"..."}`.
The CLI uses the JSON form internally so it can set a correct exit code and
separate stderr.

### 7. `SKILL.md`

Create at repo root. Structure:

- Name, one-line description.
- **When to use**: debugging, exploring live state, trying fixes against real
  runtime objects.
- **How to install the hook** in the host script:
  ```python
  from aihook import agent_hook; agent_hook()
  ```
- **Canonical agent workflow**:
  1. Start the host script in the background with output redirected to a
     log file, e.g.:
     ```bash
     python path/to/host_script.py > aihook-host.log 2>&1 &
     ```
  2. (TODO-AIDER: This rework (merge 2 and 3?) as waiting for 5s is now default) Wait for the server to be ready and discover the port:
     ```bash
     aihook --wait
     ```
     This blocks until `./aihook-lock.yml` appears (default timeout 5s).
     Read the `port` field from that file (or let the CLI resolve it
     automatically).
  3. Interact using the discovered port:
     ```bash
     aihook 'x'
     aihook -f snippet.py
     ```
     Document `-f FILE` as the recommended way to reuse complex testing snippets
     after editing the host code.
  4. End the session:
     ```bash
     aihook --exit
     ```
- Warn explicitly: **do not run the host script in the foreground** — it
  will not return until `exit()` is sent, blocking the agent's shell turn.
- Assumption: at most one aihook process per working directory. If a second
  host script is started in the same cwd while another is active, it will
  refuse to start.
- Document the locals-write-back limitation (CPython fast locals: rebinding
  a local name inside the REPL does not propagate back to the caller;
  mutating mutable objects does).
- Keep it concise; agents will read it verbatim.

### 8. Alias

disregarded. We do not want aliases.

### 9. Graceful shutdown

- Handle `KeyboardInterrupt` in `run()` to shut the server down cleanly and
  remove the session file.
- Register `atexit` cleanup.

### 10. Tests

Add `tests/test_integration.py`:

- Spawn `tests/the-test-script.py` as a subprocess (in a temporary cwd so
  the lock file doesn't collide with anything).
- Use `aihook --wait` (or poll for `./aihook-lock.yml`) to discover the
  port, rather than parsing the subprocess's stdout.
- Use the CLI (via `subprocess.run([sys.executable, "-m", "aihook.cli", ...])`
  or by importing the client function directly) to:
  - read a nested value,
  - mutate a list,
  - call `exit()` (via `aihook --exit`).
- Assert subprocess exits 0 and final stdout reflects the mutation.
- Assert that `./aihook-lock.yml` is removed after shutdown.

Also add a unit test for the lock-file helpers (write/read/stale-pid
detection) that fakes a lock file in a tmp dir.

## Non-goals (for this iteration)

- Authentication / TLS.
- Remote (non-localhost) usage.
- Multi-client concurrency within a single session.

## Deliverables checklist

- [ ] `agent_hook()` works with no arguments.
- [ ] Dynamic port in range 5001–5101, printed as `AIHOOK_PORT=<n>`,
      followed by `sys.stdout.flush()`.
- [ ] `./aihook-lock.yml` written on startup (with explanatory comment)
      and removed on shutdown / via `atexit`.
- [ ] Host script refuses to start if a live lock file already exists in cwd.
- [ ] `aihook` CLI with `-p`, `-f`, `--exit`, `--wait SECONDS`,
      `--lockfile`, stdin support.
- [ ] Auto-print last expression.
- [ ] `SKILL.md` at repo root documenting the canonical workflow.
- [ ] Integration test passes via `pytest`.
- [ ] `tests/the-test-script.py` updated to `agent_hook()` (no argument).
- [ ] Old `tool-description.md` removed or reduced to a pointer to `SKILL.md`.
