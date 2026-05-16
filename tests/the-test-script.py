import subprocess

from aihook.core import agent_hook


def my_function():
    # Complex variables
    complex_var = {
        "name": "test_data",
        "nested": {"value": 42, "items": [1, 2, 3, 4]},
        "metadata": {"created": "2026-05-04", "version": 1.0},
    }
    print("Before hook: complex_var =", complex_var)
    # Call the agent hook (no arguments: caller's namespace is used).
    agent_hook()
    print("After hook: complex_var =", complex_var)


if __name__ == "__main__":
    my_function()
    # Wait for agent process to finish
    print("Main: Script finished.")
