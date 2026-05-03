"""
This file is optional. It serves to configure pytest. In particular it offers the option to use the ipydex
excepthook. This is a mechanism which opens an interactive ipython shell in the context where an exception
occurs.

This might be very helpful for debugging. However, as this can confuse unprepared users and als is not
helpful e.g. during continuous intergration runs it is deactivated by default. To activate set the
appropriate environment variable to "True" via `export PYTEST_IPS=True`.

If you do not need this feature, you can savely delete this file.
"""

import os
import pytest

# use `export PYTEST_IPS=True` to activate this

if os.getenv("PYTEST_IPS") == "True":
    import ipydex

    def pytest_runtest_setup(item):
        print("This invocation of pytest is customized")

    def pytest_exception_interact(node, call, report):
        ipydex.ips_excepthook(call.excinfo.type, call.excinfo.value, call.excinfo.tb, leave_ut=True)
