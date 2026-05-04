"""
Command line interface for aihook.

Sends Python code to an active aihook session (started by ``agent_hook()``
in a host script) and prints the resulting stdout / stderr.
"""

import argparse
import json
import os
import sys
import time
from urllib import request as urlrequest
from urllib.error import URLError

from . import core


DEFAULT_WAIT_SECONDS = 5.0


def _resolve_port(args):
    """
    Resolve the target port according to the documented priority:
      1. --port
      2. --lockfile PATH
      3. ./aihook-lock.yml
    If no port is resolvable yet and a wait is configured, wait up to the
    configured number of seconds for the lock file to appear (and its pid to
    be alive).
    """
    if args.port is not None:
        return args.port

    lockfile_path = args.lockfile or os.path.join(os.getcwd(), core.LOCKFILE_NAME)
    wait_seconds = args.wait if args.wait is not None else DEFAULT_WAIT_SECONDS

    deadline = time.monotonic() + max(0.0, wait_seconds)
    first = True
    while True:
        if os.path.exists(lockfile_path):
            try:
                data = core.read_lockfile(lockfile_path)
            except Exception as e:
                if time.monotonic() >= deadline:
                    sys.stderr.write(
                        f"aihook: could not parse lock file {lockfile_path}: {e}\n"
                    )
                    sys.exit(2)
                time.sleep(0.1)
                continue

            pid = data.get("pid")
            port = data.get("port")
            if pid and port and core._pid_alive(pid):
                return int(port)

            # Stale: wait a bit in case it is being rewritten.
            if time.monotonic() >= deadline:
                sys.stderr.write(
                    f"aihook: lock file {lockfile_path} is stale (pid {pid} not alive).\n"
                )
                sys.exit(2)

        if time.monotonic() >= deadline:
            sys.stderr.write(
                f"aihook: no active session found.\n"
                f"aihook: expected lock file at {lockfile_path}.\n"
                f"aihook: hint: start the host script (see SKILL.md) or use --wait.\n"
            )
            sys.exit(2)

        if first:
            first = False
        time.sleep(0.1)


def _send(port, command, timeout=30.0):
    """POST ``command`` to the /execute endpoint, request JSON response."""
    url = f"http://127.0.0.1:{port}/execute?format=json"
    data = command.encode("utf-8")
    req = urlrequest.Request(url, data=data, method="POST",
                             headers={"Content-Type": "text/plain"})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except URLError as e:
        sys.stderr.write(f"aihook: cannot reach session on port {port}: {e}\n")
        sys.exit(2)

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Fallback: treat as plain text on stdout.
        return {"stdout": body, "stderr": "", "result_repr": None, "exception": None}


def _read_command(args):
    """Determine the command source."""
    if args.exit:
        return "exit()"

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()

    if args.cmd == "-" or (args.cmd is None and not sys.stdin.isatty()):
        return sys.stdin.read()

    if args.cmd is None:
        return None

    return args.cmd


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="aihook",
        description="Send Python code to a running aihook REPL session.",
    )
    parser.add_argument(
        "cmd", nargs="?",
        help="Python code to execute. Use '-' to read from stdin.",
    )
    parser.add_argument(
        "-p", "--port", type=int, default=None,
        help="Target port. Overrides lock-file discovery.",
    )
    parser.add_argument(
        "-f", "--file", default=None,
        help="Read code from FILE and send it. Useful for reusing snippets.",
    )
    parser.add_argument(
        "--exit", action="store_true",
        help="Send exit() to shut down the session.",
    )
    parser.add_argument(
        "--wait", type=float, default=None,
        help=f"Seconds to wait for a lock file to appear (default: {DEFAULT_WAIT_SECONDS}s).",
    )
    parser.add_argument(
        "--lockfile", default=None,
        help="Path to the lock file (default: ./aihook-lock.yml).",
    )
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    command = _read_command(args)
    if command is None:
        parser.error("no command given (pass a positional arg, -f FILE, stdin, or --exit)")

    port = _resolve_port(args)
    result = _send(port, command)

    stdout = result.get("stdout", "") or ""
    stderr = result.get("stderr", "") or ""
    exception = result.get("exception")

    if stdout:
        sys.stdout.write(stdout)
        if not stdout.endswith("\n"):
            sys.stdout.write("\n")
    if stderr:
        sys.stderr.write(stderr)
        if not stderr.endswith("\n"):
            sys.stderr.write("\n")

    if exception or stderr:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
