"""Parent CLI and the game's unprivileged transport; no passwords in argv."""
import argparse
import getpass
import json
import os
import sys
from ..core import paths, proto


def limit(value):
    if value == "unlimited":
        return None
    try:
        number = int(value)
        if str(number) != value or not 0 <= number <= 10000:
            raise ValueError()
        return number
    except ValueError:
        raise argparse.ArgumentTypeError("use 0–10000, or unlimited") from None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="omarchy kids pawberry",
        description="Play Pawberry, or configure parent daily practice limits.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "limits", "settings"):
        part = sub.add_parser(command)
        part.add_argument("--user", default=os.environ.get("SUDO_USER"))
        if command in ("limits", "settings"):
            part.add_argument("--addition", type=limit, default=argparse.SUPPRESS)
            part.add_argument("--subtraction", type=limit, default=argparse.SUPPRESS)
            part.add_argument("--multiplication", type=limit, default=argparse.SUPPRESS)
            part.add_argument("--password-stdin", action="store_true")
    sub.add_parser("request").add_argument("payload")
    args = parser.parse_args(argv)
    if args.command == "request":
        try:
            payload = json.loads(args.payload)
            if not isinstance(payload, dict) or payload.get("cmd") not in {"status", "begin", "complete"}:
                raise ValueError()
        except ValueError:
            parser.error("invalid game request")
    else:
        payload = {"cmd": "status", "user": args.user}
        if args.command in ("limits", "settings"):
            patch = {op: getattr(args, option) for option, op in
                     (("addition", "add"), ("subtraction", "subtract"), ("multiplication", "multiply")) if hasattr(args, option)}
            if not patch:
                parser.error("limits requires --addition, --subtraction or --multiplication")
            payload.update(cmd="limits.set", limits=patch)
            if os.geteuid() != 0:
                payload["password"] = sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Parent password: ")
    payload["scope"] = "pawberry"
    try:
        result = proto.request(paths.client_socket_candidates(), payload, timeout=25)
    except (OSError, proto.ProtocolError):
        result = {"ok": False, "error": "unavailable"}
    print(json.dumps(result))
    return 0 if result.get("ok") else 1
