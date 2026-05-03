import unittest

# useful for debugging
# from ipydex import IPS, activate_ips_on_exception
# activate_ips_on_exception()
# see also https://github.com/cknoll/ipydex?tab=readme-ov-file#ipydex-usage-in-unittests-using-pytest

# the following requires the package to be properly installed in your environment
# import aihook


class TestCore(unittest.TestCase):
    def setUp(self):
        # put generic setup code here
        pass

    # recommendation: number your tests to achieve predictable ordering
    def test_010_core(self):
        pass
