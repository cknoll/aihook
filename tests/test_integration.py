"""
Integration test: spawn the example host script, drive it through the CLI.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from urllib import request as urlrequest

from aihook import core


HERE = os.path.dirname(os.path.abspath(__file__))
HOST_SCRIPT_SRC = os.path.join(HERE, "the-test-script.py")


def _poll_lockfile(lockfile_path, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(lockfile_path):
            try:
                data = core.read_lockfile(lockfile_path)
            except Exception:
                time.sleep(0.1)
                continue
            if core._pid_alive(data.get("pid")):
                return data
        time.sleep(0.1)
    raise TimeoutError(f"lock file {lockfile_path} did not become valid in time")


def _send(port, command):
    url = f"http://127.0.0.1:{port}/execute?format=json"
    req = urlrequest.Request(
        url, data=command.encode("utf-8"), method="POST",
        headers={"Content-Type": "text/plain"},
    )
    with urlrequest.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir.name
        self.script = os.path.join(self.tmpdir, "host_script.py")
        shutil.copy(HOST_SCRIPT_SRC, self.script)
        self.lockfile = os.path.join(self.tmpdir, core.LOCKFILE_NAME)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_full_session(self):
        env = dict(os.environ)
        # Make sure subprocess uses line-buffered output for easier debugging.
        env["PYTHONUNBUFFERED"] = "1"

        proc = subprocess.Popen(
            [sys.executable, self.script],
            cwd=self.tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            data = _poll_lockfile(self.lockfile)
            port = int(data["port"])

            # 1. Read nested value (auto-print last expression).
            resp = _send(port, "complex_var['nested']['value']")
            self.assertEqual(resp["exception"], None)
            self.assertIn("42", resp["stdout"])

            # 2. Mutate the list (mutation of mutable object propagates back).
            resp = _send(port, "complex_var['nested']['items'].append(99)")
            self.assertEqual(resp["exception"], None)
            self.assertEqual(resp["stderr"], "")

            # 3. Exit the session via the CLI.
            cli_result = subprocess.run(
                [sys.executable, "-m", "aihook.cli", "--exit"],
                cwd=self.tmpdir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(cli_result.returncode, 0, msg=cli_result.stderr)

            stdout, _ = proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 0, msg=stdout.decode("utf-8", "replace"))

            # After mutation, final print in host script should include 99.
            final_output = stdout.decode("utf-8", "replace")
            self.assertIn("99", final_output)

            # Lock file must be gone after clean shutdown.
            self.assertFalse(os.path.exists(self.lockfile))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_multi_statement_execution(self):
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, self.script],
            cwd=self.tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            data = _poll_lockfile(self.lockfile)
            port = int(data["port"])
            cmd = "def foo():\n    return 42\n\nprint(foo())\n"
            resp = _send(port, cmd)
            self.assertEqual(resp["exception"], None)
            self.assertEqual(resp["stderr"], "")
            self.assertIn("42", resp["stdout"])
            # Exit session
            _send(port, "exit()")
            proc.wait(timeout=15)
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_def_alone(self):
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, self.script],
            cwd=self.tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            data = _poll_lockfile(self.lockfile)
            port = int(data["port"])
            # define function without calling
            resp = _send(port, "def foo():\n    return 42\n")
            self.assertEqual(resp["exception"], None)
            # verify function exists by calling it
            resp2 = _send(port, "foo()")
            self.assertEqual(resp2["exception"], None)
            self.assertIn("42", resp2["stdout"])
            _send(port, "exit()")
            proc.wait(timeout=15)
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_assignment_and_use(self):
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, self.script],
            cwd=self.tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            data = _poll_lockfile(self.lockfile)
            port = int(data["port"])
            cmd = "x = 7\nprint(x * 6)\n"
            resp = _send(port, cmd)
            self.assertEqual(resp["exception"], None)
            self.assertIn("42", resp["stdout"])
            _send(port, "exit()")
            proc.wait(timeout=15)
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_syntax_error_multi_statement(self):
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, self.script],
            cwd=self.tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            data = _poll_lockfile(self.lockfile)
            port = int(data["port"])
            # invalid syntax
            cmd = "def foo(\n"
            resp = _send(port, cmd)
            self.assertIsNotNone(resp["exception"], "Expected SyntaxError exception")
            # stderr may contain traceback
            _send(port, "exit()")
            proc.wait(timeout=15)
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_single_expression_unchanged(self):
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, self.script],
            cwd=self.tmpdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        try:
            data = _poll_lockfile(self.lockfile)
            port = int(data["port"])
            resp = _send(port, "1+2")
            self.assertEqual(resp["exception"], None)
            self.assertIn("3", resp["stdout"])
            _send(port, "exit()")
            proc.wait(timeout=15)
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
