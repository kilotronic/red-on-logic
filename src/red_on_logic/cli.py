"""Command line entry point."""

import sys


def main(argv: list[str] | None = None) -> int:
    del argv
    print("red-on-logic: not built yet", file=sys.stderr)
    return 2


def entry() -> None:
    sys.exit(main())
