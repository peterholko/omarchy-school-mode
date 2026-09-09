"""Narrow, unprivileged adapter to the optional screen-time quiz service."""
import argparse
import json

from omarchy_kids.core import paths, proto


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('next')
    answer = sub.add_parser('answer')
    answer.add_argument('id')
    answer.add_argument('value', type=int)
    args = parser.parse_args()
    # No caller-selected user, password, grant, configuration, or reward amount.
    # The daemon resolves the account from Unix peer credentials.
    payload = {'scope': 'time', 'cmd': 'quiz.next', 'choices': 6}
    if args.action == 'answer':
        payload = {'scope': 'time', 'cmd': 'quiz.answer', 'id': args.id, 'answer': args.value}
    try:
        result = proto.request(paths.client_socket_candidates(), payload, timeout=5)
    except (OSError, proto.ProtocolError):
        result = {'ok': False, 'error': 'unavailable'}
    print(json.dumps(result))
    return 0 if result.get('ok') else 1
