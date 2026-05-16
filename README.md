# aihook

**Pause a running Python script and let an AI agent inspect and manipulate its live state — without restarting.**

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)

---

## The problem

Some scripts are expensive to restart. A Selenium browser session takes 60 seconds to reach the
interesting state. An ML pipeline loads a 4 GB model before the first inference. A scraper
re-authenticates and paginates through 200 pages before getting to the data you care about.

When debugging these scripts, the standard loop — edit, restart, wait, observe — is brutal.
Each hypothesis costs a full restart.

## What aihook does

Drop one call into your script:

```python
from aihook import agent_hook
agent_hook()   # script pauses here; HTTP REPL starts
```

The script pauses at that line. An HTTP server starts on a free port. The calling frame's
variables are all live and accessible. An AI agent (or you) can then probe, manipulate, and
test fixes against the real running state:

```bash
aihook 'browser.find_by_css(".comment__replies")'
aihook -f snippet.py        # run a multi-line snippet, edit, repeat
aihook --exit               # resume the script
```

Each probe takes 2–5 seconds instead of 60.

---

## Real-world example

This is what a session looks like in practice. The script is a Selenium browser automation that
was failing silently on every "show replies" button click:

```bash
# Start the slow script in the background
python fetch_comments.py --url "https://example.com/article" > aihook-host.log 2>&1 &

# Wait for it to reach agent_hook() (cookie banner, scroll, 8 comments × 8s each)
until [ -f aihook-lock.yml ]; do sleep 3; done
# aihook: session found after 94.3s

# Probe the live DOM
aihook 'browser.find_by_css("[data-comment-id]")'
# -> []   ← the attribute does not exist

aihook 'browser.find_by_css("[id^=cid-]")'
# -> [<Element id="cid-4821">  ...  ]   ← found it

# Try the JS click that works despite the overlay
aihook -f snippet.py   # snippet tests execute_script("arguments[0].click()", btn)
# -> reply count went from 8 to 28

aihook --exit
```

Five probes. Zero restarts. A working script at the end.

---

## Install

```bash
pip install aihook
```

### Set up the AI agent skill

For Claude Code:
```bash
aihook --bootstrap --agent claude
```

For aider / aider-desk:
```bash
aihook --bootstrap --agent aider
```

This installs `SKILL.md` (the agent's instruction file for using aihook) and creates a
`learnings/` directory where agent-accumulated tips are stored across sessions.

---

## CLI reference

| Command | Description |
|---|---|
| `aihook '<code>'` | Execute code; single expressions auto-print their `repr()` |
| `aihook -f FILE` | Send contents of FILE (`-f -` reads from stdin) |
| `aihook --exit` | Shut down the session and let the script resume |
| `aihook --status` | Show whether a session is active (exits 0 if healthy) |
| `aihook --clean` | Remove a stale lock file |
| `aihook --wait N` | Wait up to N seconds for the lock file (default: 5s) |
| `aihook -p PORT` | Target a specific port (skips lock-file discovery) |
| `aihook --lockfile PATH` | Use a custom lock-file path |
| `aihook --bootstrap` | Install SKILL.md and create learnings directory |

Exit code is non-zero if the remote code raised an exception or wrote to stderr.

**Auto-print:** if the submitted code is a single expression, its `repr()` is printed
automatically. For multi-line snippets, use explicit `print()` — auto-print only applies to
single expressions.

---

## How it works

`agent_hook()` does three things:

1. Captures the calling frame's `globals` and `locals` into a shared namespace.
2. Starts a minimal HTTP server on a free port in `5001–5101` (configurable).
3. Writes `./aihook-lock.yml` containing `pid`, `port`, `cwd`, and `start_time`.

The CLI reads the lock file to find the port, POSTs code to `/execute`, and prints the
result. The server shuts down on `exit()`, the lock file is removed, and the host script
resumes.

The banner printed on startup includes the source file and line number where `agent_hook()`
was called — useful when a script has multiple hook points.

---

## One caveat: local variable write-back

Rebinding a **local** variable of the calling function from inside the REPL does **not**
write back to that function's fast-locals. This is the same limitation as `pdb`:

```python
# Inside my_function():
x = 1
agent_hook()
print(x)   # still prints 1 even if you did `x = 2` via aihook
```

**Mutating mutable objects works fine:**

```python
my_list.append(99)           # visible in the host afterwards
my_dict["key"] = "new"       # same
obj.attribute = "changed"    # same
```

When testing a fix, mutate containers or attributes rather than rebinding local names.

(Of course, this is documented for agents in [SKILL.md](src/aihook/SKILL.md).)

---

## Optional environment variables

| Variable | Effect |
|---|---|
| `AIHOOK_PORT=NNNN` | Force a specific port |
| `AIHOOK_PORT_RANGE=LO-HI` | Override the default `5001-5101` range |

---

## Development

```bash
git clone <repo-url>
cd aihook
pip install -e .
pytest
```

The learnings directory (created by `--bootstrap`) accumulates session tips in
`~/.local/share/aihook/learnings/` (Linux) or the platform equivalent. Add
`topic_<name>.md` files there to share domain-specific knowledge across agent sessions.
