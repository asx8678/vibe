from __future__ import annotations

import sys

# Kept intentionally tiny: the `vibe` console script lands here and hands the
# whole invocation to the Rust TUI without importing the Python stack.


def main() -> None:
    from vibe.cli._rust import exec_rust_cli

    exec_rust_cli(sys.argv[1:])
