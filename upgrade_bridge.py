#!/usr/bin/env python3
"""Retired one-off updater. Intentionally performs no reads or writes."""
import sys


def main():
    print('The one-off updater has been retired. No files were changed.\n'
          'Download and review a fresh checkout, keep your private configuration separate,\n'
          'and follow docs/UPGRADING.md. This script cannot install or upgrade the bridge.',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
