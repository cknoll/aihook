"""
Command line interface for aihook.

Sends Python code to an active aihook session (started by ``agent_hook()``
in a host script) and prints the resulting stdout / stderr.
"""

import argparse
import json
import os
import socket as _socket
import sys
import time
from urllib import request as urlrequest
from urllib.error import URLError

import platformdirs
from importlib.resources import files as _resource_files

from . import core


AIDER_DESK_SKILL_DIR = os.path.expanduser("~/.aider-desk/skills/aihook")
CLAUDE_CODE_COMMANDS_DIR = os.path.expanduser("~/.claude/commands")


DEFAULT_WAIT_SECONDS = 180.0


def _port_is_listening(port, timeout=1.0):
    """Return True if 127.0.0.1:port is accepting connections."""
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", int(port)))
        s.close()
        return True
    except OSError:
        return False


def _resolve_port(args):
    """
    Resolve the target port according to the documented priority:
      1. --port
      2. --lockfile PATH
      3. ./aihook-lock.yml
    If no port is resolvable yet and a wait is configured, wait up to the
    configured number of seconds for the lock file to appear (and its pid to
    be alive and its port to be listening).
    """
    if args.port is not None:
        return args.port

    lockfile_path = args.lockfile or os.path.join(os.getcwd(), core.LOCKFILE_NAME)
    wait_seconds = args.wait if args.wait is not None else DEFAULT_WAIT_SECONDS

    start = time.monotonic()
    deadline = start + max(0.0, wait_seconds)
    first = True
    while True:
        if os.path.exists(lockfile_path):
            try:
                data = core.read_lockfile(lockfile_path)
            except Exception as e:
                if time.monotonic() >= deadline:
                    sys.stderr.write(f"aihook: could not parse lock file {lockfile_path}: {e}\n")
                    sys.exit(2)
                time.sleep(0.1)
                continue

            pid = data.get("pid")
            port = data.get("port")
            if pid and port and core._pid_alive(pid):
                if _port_is_listening(port):
                    elapsed = time.monotonic() - start
                    if elapsed >= 0.5:
                        sys.stderr.write(f"aihook: session found after {elapsed:.1f}s\n")
                    return int(port)
                # PID alive but port not responding — server may have crashed
                if time.monotonic() >= deadline:
                    sys.stderr.write(
                        f"aihook: pid {pid} is alive but port {port} is not responding.\n"
                        f"aihook: the server may have crashed. "
                        f"Run 'aihook --clean' to remove the lock file.\n"
                    )
                    sys.exit(2)
            else:
                # Stale lock file: wait a bit in case it is being rewritten.
                if time.monotonic() >= deadline:
                    sys.stderr.write(f"aihook: lock file {lockfile_path} is stale (pid {pid} not alive).\n")
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
    req = urlrequest.Request(url, data=data, method="POST", headers={"Content-Type": "text/plain"})
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


def _status_cmd(lockfile_path):
    """Report the status of the aihook session at lockfile_path."""
    if not os.path.exists(lockfile_path):
        print(f"aihook: no active session (no lock file at {lockfile_path})")
        sys.exit(0)

    try:
        data = core.read_lockfile(lockfile_path)
    except Exception as e:
        sys.stderr.write(f"aihook: corrupt lock file at {lockfile_path}: {e}\n")
        sys.exit(2)

    pid = data.get("pid")
    port = data.get("port")
    started = data.get("start_time", "unknown")
    tool = data.get("tool")

    if tool and tool != "aihook":
        sys.stderr.write(f"aihook: warning: lock file 'tool' field is {tool!r}, expected 'aihook'\n")

    if core.lockfile_is_stale(lockfile_path):
        sys.stderr.write(
            f"aihook: stale lock file at {lockfile_path} (pid {pid} not alive)\n"
            f"aihook: run 'aihook --clean' to remove it.\n"
        )
        sys.exit(1)

    if port and _port_is_listening(port):
        print(f"aihook: session active — pid={pid}, port={port}, started={started}")
        sys.exit(0)
    else:
        sys.stderr.write(
            f"aihook: pid {pid} is alive but port {port} is not responding.\n"
            f"aihook: the server may have crashed. Run 'aihook --clean' to remove the lock file.\n"
        )
        sys.exit(1)


def _clean_cmd(lockfile_path):
    """Remove a stale lock file. Refuse if the session is active."""
    if not os.path.exists(lockfile_path):
        print(f"aihook: nothing to clean (no lock file at {lockfile_path})")
        sys.exit(0)

    try:
        data = core.read_lockfile(lockfile_path)
        corrupt = False
    except Exception:
        data = {}
        corrupt = True

    if not corrupt and not core.lockfile_is_stale(lockfile_path):
        pid = data.get("pid")
        port = data.get("port")
        sys.stderr.write(
            f"aihook: refusing to remove lock file for active session "
            f"(pid={pid}, port={port}).\n"
            f"aihook: use 'aihook --exit' to stop the session first.\n"
        )
        sys.exit(1)

    pid = data.get("pid")
    core.remove_lockfile(lockfile_path)
    if corrupt:
        print(f"aihook: removed corrupt lock file {lockfile_path}")
    else:
        print(f"aihook: removed stale lock file {lockfile_path} (pid {pid} was not alive)")
    sys.exit(0)


def _read_command(args):
    """Determine the command source."""
    if args.exit:
        return "exit()"

    if args.file:
        if args.file == "-":
            return sys.stdin.read()
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
        add_help=False,  # We'll add custom help
    )
    parser.add_argument(
        "cmd",
        nargs="?",
        help="Python code to execute. Use '-' to read from stdin.",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=None,
        help="Target port. Overrides lock-file discovery.",
    )
    parser.add_argument(
        "-f",
        "--file",
        default=None,
        help="Read code from FILE and send it. Useful for reusing snippets.",
    )
    parser.add_argument(
        "--exit",
        action="store_true",
        help="Send exit() to shut down the session.",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=None,
        help=f"Seconds to wait for a lock file to appear (default: {DEFAULT_WAIT_SECONDS}s).",
    )
    parser.add_argument(
        "--lockfile",
        default=None,
        help="Path to the lock file (default: ./aihook-lock.yml).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show status of the current aihook session and exit.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove a stale lock file and exit. Refuses if a session is active.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help=(
            f"Install SKILL.md for the target agent (see --agent) and create the learnings "
            f"directory, then exit. aider-desk: {AIDER_DESK_SKILL_DIR}/SKILL.md. "
            f"Claude: {CLAUDE_CODE_COMMANDS_DIR}/aihook.md."
        ),
    )
    parser.add_argument(
        "--agent",
        default="aider",
        choices=["aider", "claude", "all"],
        help="Target agent for --bootstrap skill installation (default: aider).",
    )
    parser.add_argument(
        "--allow-overwrite-SKILL.md",
        dest="allow_overwrite_SKILL_md",
        action="store_true",
        help="With --bootstrap: overwrite an existing skill file at the destination.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show the version and exit.",
    )
    parser.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="Show this help message and exit.",
    )
    return parser


def _load_skill_content():
    """Return the packaged SKILL.md text, or exit with an error."""
    try:
        source = _resource_files("aihook").joinpath("SKILL.md")
        return source.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as e:
        sys.stderr.write(f"aihook: could not locate packaged SKILL.md: {e}\n")
        sys.exit(1)


def _install_skill_aider(allow_overwrite):
    dest_skill = os.path.join(AIDER_DESK_SKILL_DIR, "SKILL.md")
    if os.path.exists(dest_skill) and not allow_overwrite:
        sys.stderr.write(
            f"aihook: {dest_skill} already exists.\n"
            f"aihook: pass --allow-overwrite-SKILL.md to replace it.\n"
        )
        sys.exit(1)
    skill_content = _load_skill_content()
    os.makedirs(AIDER_DESK_SKILL_DIR, exist_ok=True)
    with open(dest_skill, "w", encoding="utf-8") as f:
        f.write(skill_content)
    print(f"aihook: wrote {dest_skill}")


def _install_skill_claude(allow_overwrite):
    dest_skill = os.path.join(CLAUDE_CODE_COMMANDS_DIR, "aihook.md")
    if os.path.exists(dest_skill) and not allow_overwrite:
        sys.stderr.write(
            f"aihook: {dest_skill} already exists.\n"
            f"aihook: pass --allow-overwrite-SKILL.md to replace it.\n"
        )
        sys.exit(1)
    skill_content = _load_skill_content()
    os.makedirs(CLAUDE_CODE_COMMANDS_DIR, exist_ok=True)
    with open(dest_skill, "w", encoding="utf-8") as f:
        f.write(skill_content)
    print(f"aihook: wrote {dest_skill}")


def _setup_learnings():
    try:
        aihook_data_dir = platformdirs.user_data_dir("aihook")
    except Exception as e:
        sys.stderr.write(f"aihook: could not determine user data directory: {e}\n")
        sys.exit(1)
    learnings_dest = os.path.join(aihook_data_dir, "learnings")
    os.makedirs(learnings_dest, exist_ok=True)
    print(f"aihook: learnings directory at {learnings_dest}")

    try:
        pkg_learnings = _resource_files("aihook").joinpath("learnings")
        for item in pkg_learnings.iterdir():
            if item.is_file():
                dest_file = os.path.join(learnings_dest, item.name)
                if os.path.exists(dest_file):
                    sys.stderr.write(f"aihook: warning: {dest_file} already exists, skipping.\n")
                    continue
                try:
                    content = item.read_text(encoding="utf-8")
                except Exception as e:
                    sys.stderr.write(f"aihook: could not read packaged learnings file {item.name}: {e}\n")
                    continue
                with open(dest_file, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"aihook: wrote {dest_file}")
    except (FileNotFoundError, ModuleNotFoundError) as e:
        sys.stderr.write(f"aihook: no default learnings found in package: {e}\n")
    except Exception as e:
        sys.stderr.write(f"aihook: error processing learnings: {e}\n")


def _bootstrap(allow_overwrite_skillmd, agent):
    if agent in ("aider", "all"):
        _install_skill_aider(allow_overwrite_skillmd)
    if agent in ("claude", "all"):
        _install_skill_claude(allow_overwrite_skillmd)
    _setup_learnings()
    print("aihook: bootstrap complete.")
    sys.exit(0)


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.help:
        parser.print_help()
        installed = []
        aider_skill = os.path.join(AIDER_DESK_SKILL_DIR, "SKILL.md")
        if os.path.exists(aider_skill):
            installed.append(f"  SKILL.md (aider-desk):  {aider_skill}")
        claude_skill = os.path.join(CLAUDE_CODE_COMMANDS_DIR, "aihook.md")
        if os.path.exists(claude_skill):
            installed.append(f"  aihook.md (claude): {claude_skill}")
        try:
            learnings_dir = os.path.join(platformdirs.user_data_dir("aihook"), "learnings")
        except Exception:
            learnings_dir = None
        if learnings_dir and os.path.exists(learnings_dir):
            installed.append(f"  Learnings dir:     {learnings_dir}")
        if installed:
            print("\nInstalled files/directories:")
            for line in installed:
                print(line)
        sys.exit(0)

    if args.version:
        from .release import __version__

        print(f"aihook {__version__}")
        sys.exit(0)

    if args.status:
        lockfile_path = args.lockfile or os.path.join(os.getcwd(), core.LOCKFILE_NAME)
        _status_cmd(lockfile_path)

    if args.clean:
        lockfile_path = args.lockfile or os.path.join(os.getcwd(), core.LOCKFILE_NAME)
        _clean_cmd(lockfile_path)

    if args.bootstrap:
        _bootstrap(args.allow_overwrite_SKILL_md, args.agent)

    if args.agent != "aider":
        parser.error("--agent only makes sense with --bootstrap")
    if args.allow_overwrite_SKILL_md:
        parser.error("--allow-overwrite-SKILL.md only makes sense with --bootstrap")

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
