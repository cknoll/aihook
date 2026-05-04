"""
Core implementation of the aihook agent hook / HTTP REPL.
"""

import atexit
import code
import errno
import inspect
import io
import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import yaml

from .release import __version__

LOCKFILE_NAME = "aihook-lock.yml"
DEFAULT_PORT_RANGE = (5001, 5101)


# ---------------------------------------------------------------------------
# Lock file helpers
# ---------------------------------------------------------------------------

def _pid_alive(pid):
    """Return True if a process with ``pid`` is still running."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as e:
        if e.errno == errno.ESRCH:
            return False
        # EPERM means the process exists but we cannot signal it.
        if e.errno == errno.EPERM:
            return True
        return False
    return True


def read_lockfile(path):
    """Read and parse a lock file. Returns a dict or raises."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid lock file content in {path}")
    return data


def write_lockfile(path, pid, port, cwd, script):
    """Write a lock file with an explanatory header comment."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    header = (
        f"# This file (created: {timestamp}) coordinates the client-server connection\n"
        f"# for the aihook skill. It is safe to delete if no aihook-enabled process\n"
        f"# is currently running in this directory.\n"
    )
    payload = {
        "pid": int(pid),
        "port": int(port),
        "cwd": str(cwd),
        "start_time": timestamp,
        "script": str(script) if script is not None else "",
    }
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=True)


def remove_lockfile(path):
    """Remove a lock file if it exists; ignore errors."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def lockfile_is_stale(path):
    """Return True if lock file exists but its pid is not alive."""
    try:
        data = read_lockfile(path)
    except Exception:
        # Corrupt file counts as stale.
        return True
    return not _pid_alive(data.get("pid"))


# ---------------------------------------------------------------------------
# Port selection
# ---------------------------------------------------------------------------

def _parse_port_range(spec):
    try:
        lo, hi = spec.split("-", 1)
        return int(lo), int(hi)
    except Exception:
        raise ValueError(f"Invalid port range spec: {spec!r}")


def _try_bind(host, port):
    """Try to bind (host, port). Return a bound socket on success, else None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
        return s
    except OSError:
        s.close()
        return None


def find_free_port(explicit_port=None):
    """
    Find a free port.

    Priority:
      1. ``explicit_port`` argument
      2. env ``AIHOOK_PORT``
      3. env ``AIHOOK_PORT_RANGE`` or default range 5001-5101
    Returns (port, pre_bound_socket). The socket is closed before HTTPServer
    binds on the same port; we only use it to probe availability.
    """
    host = "127.0.0.1"

    if explicit_port is None:
        env_port = os.environ.get("AIHOOK_PORT")
        if env_port:
            explicit_port = int(env_port)

    if explicit_port is not None:
        s = _try_bind(host, explicit_port)
        if s is None:
            raise OSError(f"Requested port {explicit_port} is not available.")
        s.close()
        return explicit_port

    range_spec = os.environ.get("AIHOOK_PORT_RANGE")
    if range_spec:
        lo, hi = _parse_port_range(range_spec)
    else:
        lo, hi = DEFAULT_PORT_RANGE

    for port in range(lo, hi + 1):
        s = _try_bind(host, port)
        if s is not None:
            s.close()
            return port

    raise OSError(f"No free port found in range {lo}-{hi}.")


# ---------------------------------------------------------------------------
# HTTP server + REPL
# ---------------------------------------------------------------------------

class ReusableHTTPServer(HTTPServer):
    """HTTP server that allows address reuse to avoid port conflicts on restart."""
    allow_reuse_address = True


class AgenticREPL:
    def __init__(self, namespace, port=None, lockfile_path=None):
        self.namespace = namespace
        self.console = code.InteractiveConsole(namespace)
        self.stdout_buffer = io.StringIO()
        self.stderr_buffer = io.StringIO()
        self.server = None
        self.running = False
        self.port = port
        self.lockfile_path = lockfile_path
        self._cleanup_done = False

    # -- execution ---------------------------------------------------------

    def execute_command(self, command):
        """
        Execute ``command`` in the managed namespace.

        Returns a dict with keys: stdout, stderr, result_repr, exception.
        """
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = self.stdout_buffer
        sys.stderr = self.stderr_buffer

        result_repr = None
        exception_str = None

        try:
            # Try to compile as a single expression first; if that succeeds,
            # eval it and capture repr(result). This saves agents from wrapping
            # every probe in print(...).
            try:
                code_obj = compile(command, "<agent>", "eval")
                is_expr = True
            except SyntaxError:
                code_obj = None
                is_expr = False

            try:
                if is_expr:
                    result = eval(code_obj, self.namespace)
                    if result is not None:
                        result_repr = repr(result)
                        print(result_repr)
                else:
                    # Statement(s): delegate to InteractiveConsole for proper
                    # handling of multi-line input / compile errors.
                    self.console.push(command)
            except SystemExit:
                raise
            except BaseException as e:
                import traceback
                exception_str = "".join(
                    traceback.format_exception(type(e), e, e.__traceback__)
                )
                print(exception_str, file=sys.stderr, end="")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        stdout_output = self.stdout_buffer.getvalue()
        stderr_output = self.stderr_buffer.getvalue()
        self.stdout_buffer.seek(0)
        self.stdout_buffer.truncate(0)
        self.stderr_buffer.seek(0)
        self.stderr_buffer.truncate(0)

        return {
            "stdout": stdout_output,
            "stderr": stderr_output,
            "result_repr": result_repr,
            "exception": exception_str,
        }

    # -- lifecycle ---------------------------------------------------------

    def _cleanup(self):
        if self._cleanup_done:
            return
        self._cleanup_done = True
        if self.lockfile_path:
            remove_lockfile(self.lockfile_path)

    def run(self):
        self.running = True
        repl_instance = self

        class REPLRequestHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path != "/execute":
                    self.send_response(404)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"404 Not Found: Only /execute endpoint is supported")
                    return

                query = parse_qs(parsed.query or "")
                fmt = (query.get("format", ["text"])[0] or "text").lower()

                content_length = int(self.headers.get("Content-Length", 0))
                if content_length == 0:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"400 Bad Request: No command provided")
                    return

                body = self.rfile.read(content_length).decode("utf-8")
                command = body.strip()

                if command == "exit()":
                    self.send_response(200)
                    if fmt == "json":
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "stdout": "REPL: Exiting\n",
                            "stderr": "",
                            "result_repr": None,
                            "exception": None,
                        }).encode("utf-8"))
                    else:
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"REPL: Exiting\n")
                    repl_instance.running = False
                    threading.Thread(target=repl_instance.server.shutdown).start()
                    return

                result = repl_instance.execute_command(command)
                self.send_response(200)
                if fmt == "json":
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode("utf-8"))
                else:
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    payload = result["stdout"] + result["stderr"]
                    self.wfile.write(payload.encode("utf-8"))

            def log_message(self, format, *args):
                pass

        try:
            self.server = ReusableHTTPServer(("127.0.0.1", self.port), REPLRequestHandler)
        except OSError as e:
            print(f"AIHOOK: error starting HTTP server on port {self.port}: {e}")
            self._cleanup()
            sys.exit(1)

        # Banner. The second line is machine-parseable (AIHOOK_PORT=<port>).
        # We call sys.stdout.flush() immediately afterwards because when the
        # host script's stdout is a pipe (e.g. an agent runner that captures
        # output), Python switches to block buffering and the banner would
        # otherwise not reach streaming consumers until much later. The lock
        # file is the authoritative discovery channel, but a promptly-flushed
        # banner helps humans and streaming agents.
        print(f"AIHOOK AgenticREPL: HTTP server running on http://127.0.0.1:{self.port}/execute")
        print(f"AIHOOK_PORT={self.port}")
        sys.stdout.flush()

        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            print("AIHOOK: KeyboardInterrupt, shutting down.")
        finally:
            try:
                self.server.server_close()
            except Exception:
                pass
            self._cleanup()
            print("AIHOOK: Server stopped.")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _build_caller_namespace():
    """Build namespace from caller's f_globals and f_locals (locals override)."""
    frame = inspect.currentframe()
    # Walk back: _build_caller_namespace -> agent_hook -> user
    caller = frame.f_back.f_back
    ns = dict(caller.f_globals)
    ns.update(caller.f_locals)
    return ns


def agent_hook(namespace=None, port=None):
    """
    Pause the host script and start an HTTP REPL bound to ``namespace``.

    If ``namespace`` is None, a namespace is built from the caller's globals
    and locals (locals override globals on key collision).

    CPython caveat: rebinding a *local* name of the calling function inside
    the REPL does not write back to that function's fast-locals. Mutating
    mutable objects (lists, dicts, attributes) works as expected. This is
    the same limitation as ``pdb``.
    """
    if namespace is None:
        namespace = _build_caller_namespace()

    cwd = os.getcwd()
    lockfile_path = os.path.join(cwd, LOCKFILE_NAME)

    # Refuse to start if a live lock file already exists in cwd.
    if os.path.exists(lockfile_path):
        try:
            existing = read_lockfile(lockfile_path)
        except Exception:
            existing = None

        if existing is not None and _pid_alive(existing.get("pid")):
            sys.stderr.write(
                f"AIHOOK: another aihook session appears to be active in this "
                f"directory (pid={existing.get('pid')}, port={existing.get('port')}).\n"
                f"AIHOOK: lock file: {lockfile_path}\n"
                f"AIHOOK: refusing to start a second session.\n"
            )
            sys.stderr.flush()
            sys.exit(1)
        else:
            sys.stderr.write(
                f"AIHOOK: stale lock file at {lockfile_path}, overwriting.\n"
            )
            sys.stderr.flush()

    chosen_port = find_free_port(explicit_port=port)
    script = sys.argv[0] if sys.argv else ""
    write_lockfile(lockfile_path, os.getpid(), chosen_port, cwd, script)

    repl = AgenticREPL(namespace, port=chosen_port, lockfile_path=lockfile_path)

    # Ensure the lock file is removed even on abrupt termination.
    atexit.register(repl._cleanup)

    def _signal_cleanup(signum, frame):
        repl._cleanup()
        # Re-raise default behavior: exit.
        sys.exit(128 + signum)

    try:
        signal.signal(signal.SIGTERM, _signal_cleanup)
    except (ValueError, OSError):
        # signal.signal only works in main thread; ignore otherwise.
        pass

    repl.run()
