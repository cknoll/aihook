# aihook — Improvement Plan

Derived from a real first-time agent session and a follow-up Q&A with the testing agent.

Items are ordered by value / cost ratio. Each item lists the affected
file(s), the concrete change, and an acceptance test.

---

## 1. Fix multi-statement execution (HIGH priority, highest value)

### Problem

Snippets with more than one top-level statement fail with a confusing
`SyntaxError`. Reproducer (confirmed by the testing agent):

```python
# /tmp/aihook_probe.py
def foo():
    return 42

print(foo())
```

```
$ aihook -f /tmp/aihook_probe.py
  File "<console>", line 4
    print(foo())
    ^^^^^
SyntaxError: invalid syntax
```

### Root cause

`AgenticREPL.execute_command` in `src/aihook/core.py` first tries
`compile(command, "<agent>", "eval")`. On `SyntaxError` it falls back to
`self.console.push(command)`. `InteractiveConsole.push` is **line-oriented**:
it mimics a human typing at a `>>>` prompt, splitting on newlines and
feeding lines one at a time through `compile_command`. It cannot execute a
whole multi-line source string in one call the way `exec(compile(..., "exec"))`
can — hence the spurious error on the second top-level statement.

### Fix

In `src/aihook/core.py`, replace the `else` branch of `execute_command`
(the `self.console.push(command)` call) with a direct `exec` of the
compiled module:

```python
else:
    code_obj = compile(command, "<agent>", "exec")
    exec(code_obj, self.namespace)
```

Keep the expression-first path unchanged (single expressions still
auto-print their `repr`). Drop the now-unused `self.console` attribute
(and the `import code` + `self.console = code.InteractiveConsole(...)` in
`__init__`) unless we find another use for it — leaner is better.

Rationale: the `InteractiveConsole` machinery was only needed for the
interactive line-by-line prompt semantics, which we do not want. Agents
send complete, already-edited source fragments; `exec` is the right tool.

### Acceptance tests

Add to `tests/test_integration.py`:

1. Multi-statement block executes and produces the expected stdout:
   ```python
   cmd = "def foo():\n    return 42\n\nprint(foo())\n"
   # expect stdout == "42\n", stderr == "", exit 0
   ```
2. `def` alone (no trailing call) defines the function in the namespace
   (verify by a follow-up `aihook 'foo()'`).
3. Assignment + use in one snippet:
   ```python
   cmd = "x = 7\nprint(x * 6)\n"
   # expect stdout == "42\n"
   ```
4. Genuine `SyntaxError` in a multi-statement block still reports cleanly
   (non-zero exit, traceback on stderr).
5. Single-expression path unchanged: `aihook '1+2'` still auto-prints `3`.

---

## 2. Print a startup hint about the fast-locals caveat (LOW priority, low cost)

### Problem

The CPython caveat (rebinding locals of the calling function does not
propagate back) is documented but remains a trap. Not discoverable at
runtime.

### Fix

In `AgenticREPL.run`, after the existing banner lines (the
`AIHOOK AgenticREPL:` / `AIHOOK_PORT=` block) in `src/aihook/core.py`,
print one concise stderr hint:

```python
sys.stderr.write(
    "AIHOOK: note: rebinding a local variable of the calling function "
    "does not propagate back (CPython fast-locals; same as pdb). "
    "Mutate containers / attributes instead. See SKILL.md.\n"
)
sys.stderr.flush()
```

Keep the banner itself on stdout unchanged (agents grep for `AIHOOK_PORT=`
there). The hint goes to stderr so it doesn't pollute machine-parseable
output.

### Acceptance test

Integration test asserts the hint substring appears in the host process's
combined log.

---

## 3. Documentation updates in `src/aihook/SKILL.md` (LOW priority, zero risk)

Three small additions:

### 3a. Promote the iterative `-f FILE` loop as the canonical workflow

In the "Canonical agent workflow" section, add an explicit bullet framing
the dominant debugging pattern:

> **Iterative probe loop.** For anything beyond a one-liner, keep a
> `snippet.py` next to the host script and rerun it after each edit:
> ```
> # edit snippet.py
> aihook -f snippet.py
> # observe, edit snippet.py again, repeat
> ```
> This is the primary workflow; the single-expression form is for quick
> probes only.

### 3b. Document `-f FILE` path resolution

Add a note under the CLI reference:

> `-f FILE` is opened by the CLI process (agent side), so relative paths
> resolve against the **agent's** current working directory, not the host
> script's. Use an absolute path (e.g. `-f "$PWD/snippet.py"`) if you are
> not certain the cwds match, or if your shell tool chains `cd` commands
> unreliably.

### 3c. Document lock-file discovery scope and manual cleanup

Extend the "Session discovery" section with:

> Lock-file discovery does **not** walk up parent directories — `aihook`
> only looks at `./aihook-lock.yml` in the invoking shell's exact cwd.
> Run `aihook` from the same directory as the host script.
>
> If the host process is killed uncleanly (e.g. `SIGKILL`, OOM), the lock
> file may remain. A subsequent `agent_hook()` call in the same cwd will
> detect this automatically (pid not alive) and overwrite it. To clean up
> manually, just `rm ./aihook-lock.yml`.

---

## 4. Nice-to-haves (deferred, consider after items 1-3 land)

These are not worth doing now but are recorded for future consideration:

- **`--echo` / `--verbose` flag** that always prints the last value (or
  `None`) regardless of statement vs. expression. Low value once item 1
  lands, because the agent can just wrap in `print(...)` in a multi-line
  block.
- **Resolve `-f FILE` relative to `lockfile["cwd"]`** when a relative path
  is given and the file is not found locally. Rejected for now: the CLI
  may run on a different machine than the host, and the current behavior
  is consistent with every other Unix tool that reads files.
- **Walk up parents for lock-file discovery.** Rejected for now: breaks
  the "one aihook per cwd" invariant and invites cross-project confusion.

---

## Out of scope / non-issues confirmed by Q&A

- Banner reaches agents via log file reliably (Q4a).
- `--wait 5` default is a good middle ground (Q4b).
- Exit-code semantics are correct (Q4c). The `REPL: Exiting` message is
  written to **stdout**, not stderr, so there is no spurious stderr on
  successful `--exit` — the testing agent's suspicion was unfounded.
- `aihook --exit` shutdown + lock-file cleanup work reliably (Q4d).

---

## Implementation order

1. Item 1 (exec fix + tests) — single commit.
2. Item 3 (docs) — single commit, can precede or follow item 1.
3. Item 2 (startup hint) — single commit.

Each item is independently mergeable. Item 1 is the only one with
behavioural risk; its test suite additions are mandatory.
