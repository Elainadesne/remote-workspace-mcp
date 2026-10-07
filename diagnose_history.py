#!/usr/bin/env python3
"""Check one explicitly allowlisted history page, without printing its content."""
import argparse
import json
import sys

from bridge.config import load_config
from bridge.files import BridgeError
from bridge.server import Bridge


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Operator-owned bridge JSON configuration')
    parser.add_argument('--project', required=True, help='Configured project alias')
    parser.add_argument('--thread-id', required=True, help='An already allowlisted thread ID or import alias')
    args = parser.parse_args(argv)
    try:
        bridge = Bridge(load_config(args.config))
        page = bridge.call('read_thread', {'project': args.project, 'thread_id': args.thread_id})
    except (BridgeError, OSError, ValueError, RecursionError) as error:
        detail = str(error) if isinstance(error, BridgeError) else 'Check local permissions and reviewed import format'
        print(f'Diagnostic failed: {detail}', file=sys.stderr)
        return 1
    # Never print thread IDs, paths, cursor values, upstream errors or conversation text.
    print(json.dumps({'ok': True, 'source': page['source'],
                      'public_messages': len(page['messages']),
                      'has_more': page.get('has_more', False)}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
