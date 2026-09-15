"""An unprivileged transport for game requests; identity comes from the socket."""
import argparse
import json
from . import paths, proto


def main(scope, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['request'])
    parser.add_argument('payload')
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.payload)
        if not isinstance(payload, dict) or payload.get('cmd') not in ('status', 'begin', 'complete'):
            raise ValueError()
    except ValueError:
        parser.error('invalid game request')
    payload.pop('user', None)
    payload.pop('password', None)
    payload['scope'] = scope
    try:
        result = proto.request(paths.client_socket_candidates(), payload, timeout=8)
    except (OSError, proto.ProtocolError):
        result = {'ok': False, 'error': 'unavailable'}
    print(json.dumps(result))
    return 0 if result.get('ok') else 1
