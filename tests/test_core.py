import os
import tempfile
import unittest

import yaml

from aihook import core


class TestCore(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir.name
        self.lockfile = os.path.join(self.tmpdir, core.LOCKFILE_NAME)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_010_write_and_read_lockfile(self):
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050,
                            cwd=self.tmpdir, script="test.py")
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
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050,
                            cwd=self.tmpdir, script="x")
        core.remove_lockfile(self.lockfile)
        self.assertFalse(os.path.exists(self.lockfile))
        # Calling again must not raise.
        core.remove_lockfile(self.lockfile)

    def test_030_stale_pid_detection(self):
        # Live pid: our own.
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050,
                            cwd=self.tmpdir, script="x")
        self.assertFalse(core.lockfile_is_stale(self.lockfile))

        # Almost certainly-dead pid.
        core.write_lockfile(self.lockfile, pid=2**30, port=5050,
                            cwd=self.tmpdir, script="x")
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
        core.write_lockfile(self.lockfile, pid=os.getpid(), port=5050,
                            cwd=self.tmpdir, script="x")
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
        self.assertIsNone(core._proc_starttime_jiffies(2 ** 30))
