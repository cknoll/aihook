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
- Document the CPython limitation: rebinding a *local* name inside the REPL
  does **not** write back to the caller's local variable (fast locals). Mutating
  mutable objects does work. Same limitation as `pdb`.

### 2. Dynamic port allocation

- Default port range: 5001–5101, overridable via env var `AIHOOK_PORT_RANGE`
  (format `"5001-5101"`) or explicit `port=` argument / `AIHOOK_PORT`.
- Pick the first free port by trying to bind; skip busy ones.
- Print **two** lines on startup:
  - Human-readable: `AgenticREPL: HTTP server running on http://127.0.0.1:<port>/execute`
  - Machine-parseable: `AIHOOK_PORT=<port>`
- Bind to `127.0.0.1` only.

### 3. Session discovery

- On startup, write a small JSON file to `~/.cache/aihook/<pid>.json`
  containing: `pid`, `port`, `cwd`, `start_time`, `script` (best-effort from
  `sys.argv[0]`).
- Remove that file on clean shutdown (and best-effort via `atexit`).
- Provide helper `aihook._sessions.list_sessions()` that returns active
  sessions (filter out stale entries whose pid no longer exists).

### 4. CLI `aihook`

Implement in `src/aihook/cli.py` using `argparse`. Subcommands / options:

- `aihook '<code>'` — send code to the (single) active session. Error if
  zero or >1 sessions found and `-p` not given.
- `aihook -p PORT '<code>'` — target a specific port.
- `aihook -f FILE` — send contents of FILE as the command.
- `aihook -` or piping via stdin — read code from stdin when no positional
  arg is given and stdin is not a TTY.
- `aihook --list` — list active sessions (pid, port, cwd, script).
- `aihook --exit [-p PORT]` — send `exit()` to a session.
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
- **How to use (90% case)**: a single code snippet
  ```python
  from aihook import agent_hook; agent_hook()
  ```
  and the CLI usage: `aihook 'print(x)'`, `aihook --list`, `aihook --exit`.
- Document the locals-write-back limitation.
- Show raw `curl` fallback for environments without the CLI.
- Keep it concise; agents will read it verbatim.

### 8. Alias

Export `set_trace = agent_hook` from `aihook/__init__.py` for users who prefer
the `pdb` idiom. Also export `agent_hook`.

### 9. Graceful shutdown

- Handle `KeyboardInterrupt` in `run()` to shut the server down cleanly and
  remove the session file.
- Register `atexit` cleanup.

### 10. Tests

Add `tests/test_integration.py`:

- Spawn `tests/the-test-script.py` as a subprocess.
- Read stdout until the `AIHOOK_PORT=` line appears; parse port.
- Use the CLI (via `subprocess.run([sys.executable, "-m", "aihook.cli", ...])`
  or by importing the client function directly) to:
  - read a nested value,
  - mutate a list,
  - call `exit()`.
- Assert subprocess exits 0 and final stdout reflects the mutation.

Also add a unit test for `list_sessions()` that fakes a session file.

## Non-goals (for this iteration)

- Authentication / TLS.
- Remote (non-localhost) usage.
- Multi-client concurrency within a single session.

## Deliverables checklist

- [ ] `agent_hook()` works with no arguments.
- [ ] Dynamic port in range 5001–5101, printed as `AIHOOK_PORT=<n>`.
- [ ] Session file in `~/.cache/aihook/`.
- [ ] `aihook` CLI with `-p`, `-f`, `--list`, `--exit`, stdin support.
- [ ] Auto-print last expression.
- [ ] `SKILL.md` at repo root.
- [ ] `set_trace` alias exported.
- [ ] Integration test passes via `pytest`.
- [ ] `tests/the-test-script.py` updated to `agent_hook()` (no argument).
- [ ] Old `tool-description.md` removed or reduced to a pointer to `SKILL.md`.
