import os
import sys
import tempfile
import unittest

import yaml

from aihook import core
from aihook.cli import VARS_COMMAND


class TestCore(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir.name
        self.lockfile = os.path.join(self.tmpdir, core.LOCKFILE_NAME)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_010_write_and_read_lockfile(self):
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050, cwd=self.tmpdir, script="test.py")
        self.assertTrue(os.path.exists(self.lockfile))

        # First line must be the explanatory header comment.
        with open(self.lockfile, "r", encoding="utf-8") as f:
            first_line = f.readline()
        self.assertTrue(first_line.startswith("# This file"))

        data = core.read_lockfile(self.lockfile)
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(data["port"], 5050)
        self.assertEqual(data["cwd"], self.tmpdir)
        self.assertEqual(data["script"], "test.py")
        self.assertIn("start_time", data)
        self.assertEqual(data["tool"], "aihook")
        # proc_starttime is present on Linux where /proc is available
        if os.path.exists("/proc"):
            self.assertIn("proc_starttime", data)
            self.assertIsInstance(data["proc_starttime"], int)

    def test_020_remove_lockfile_idempotent(self):
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050, cwd=self.tmpdir, script="x")
        core.remove_lockfile(self.lockfile)
        self.assertFalse(os.path.exists(self.lockfile))
        # Calling again must not raise.
        core.remove_lockfile(self.lockfile)

    def test_030_stale_pid_detection(self):
        # Live pid: our own.
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050, cwd=self.tmpdir, script="x")
        self.assertFalse(core.lockfile_is_stale(self.lockfile))

        # Almost certainly-dead pid.
        core.write_lockfile(self.lockfile, pid=2**30, port=5050, cwd=self.tmpdir, script="x")
        self.assertTrue(core.lockfile_is_stale(self.lockfile))

    def test_040_pid_alive_helpers(self):
        self.assertTrue(core._pid_alive(os.getpid()))
        self.assertFalse(core._pid_alive(2**30))
        self.assertFalse(core._pid_alive(None))
        self.assertFalse(core._pid_alive(0))

    def test_050_parse_port_range(self):
        self.assertEqual(core._parse_port_range("5001-5101"), (5001, 5101))
        with self.assertRaises(ValueError):
            core._parse_port_range("not-a-range")

    @unittest.skipUnless(os.path.exists("/proc"), "requires /proc filesystem")
    def test_060_pid_reuse_detection(self):
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050, cwd=self.tmpdir, script="x")
        data = core.read_lockfile(self.lockfile)
        self.assertIn("proc_starttime", data)

        # Tamper with proc_starttime to simulate PID reuse
        data["proc_starttime"] = data["proc_starttime"] + 999999
        with open(self.lockfile, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        self.assertTrue(
            core.lockfile_is_stale(self.lockfile),
            "should detect PID reuse via mismatched proc_starttime",
        )

    @unittest.skipUnless(os.path.exists("/proc"), "requires /proc filesystem")
    def test_061_proc_starttime_consistent(self):
        pid = os.getpid()
        st1 = core._proc_starttime_jiffies(pid)
        st2 = core._proc_starttime_jiffies(pid)
        self.assertIsNotNone(st1)
        self.assertEqual(st1, st2)
        self.assertIsNone(core._proc_starttime_jiffies(2**30))


class TestExecuteCommand(unittest.TestCase):
    def setUp(self):
        self.repl = core.AgenticREPL(namespace={})

    def test_100_runtime_exception_captured(self):
        result = self.repl.execute_command("1/0")
        self.assertIsNotNone(result["exception"])
        self.assertIn("ZeroDivisionError", result["exception"])
        self.assertEqual(result["stdout"], "")

    def test_101_none_result_not_printed(self):
        result = self.repl.execute_command("None")
        self.assertIsNone(result["result_repr"])
        self.assertEqual(result["stdout"], "")

    def test_103_multiline_last_expr_auto_print(self):
        ns = {"x": 21}
        repl = core.AgenticREPL(namespace=ns)
        result = repl.execute_command("y = x * 2\ny")
        self.assertIsNone(result["exception"])
        self.assertIn("42", result["stdout"])
        self.assertEqual(ns["y"], 42)

    def test_104_multiline_no_trailing_expr_silent(self):
        repl = core.AgenticREPL(namespace={})
        result = repl.execute_command("x = 42\ny = x + 1")
        self.assertIsNone(result["exception"])
        self.assertEqual(result["stdout"], "")

    def test_105_multiline_last_expr_none_not_printed(self):
        repl = core.AgenticREPL(namespace={})
        result = repl.execute_command("x = [3, 1, 2]\nx.sort()")
        self.assertIsNone(result["exception"])
        self.assertEqual(result["stdout"], "")

    def test_108_vars_command_lists_names_with_types(self):
        ns = {"my_list": [1, 2], "my_int": 7}
        repl = core.AgenticREPL(namespace=ns)
        result = repl.execute_command(VARS_COMMAND)
        self.assertIsNone(result["exception"])
        self.assertIn("my_list", result["stdout"])
        self.assertIn("list", result["stdout"])
        self.assertIn("my_int", result["stdout"])
        self.assertIn("int", result["stdout"])

    def test_106_fresh_does_not_mutate_namespace(self):
        ns = {"x": 10}
        repl = core.AgenticREPL(namespace=ns)
        result = repl.execute_command("x = 99", fresh=True)
        self.assertIsNone(result["exception"])
        self.assertEqual(ns["x"], 10, "--fresh must not mutate the real namespace")

    def test_107_non_fresh_mutates_namespace(self):
        ns = {"x": 10}
        repl = core.AgenticREPL(namespace=ns)
        result = repl.execute_command("x = 99", fresh=False)
        self.assertIsNone(result["exception"])
        self.assertEqual(ns["x"], 99, "normal mode must mutate the real namespace")

    @unittest.skipIf(sys.version_info >= (3, 12), "f-string backslash restriction lifted in 3.12")
    def test_102_fstring_backslash_hint(self):
        # In Python < 3.12, backslashes inside f-string expressions are a SyntaxError.
        cmd = r"""f"{ '\n'.join(['a', 'b']) }" """
        result = self.repl.execute_command(cmd)
        self.assertIsNotNone(result["exception"])
        self.assertIn("aihook hint", result["exception"])
        self.assertIn("-f FILE", result["exception"])
