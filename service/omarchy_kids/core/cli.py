"""The command line client. Prints JSON, because the widget reads it too.

The parent password is never an argument. /proc/<pid>/cmdline is world
readable, so it is read from stdin or asked for interactively; root, which is
`omarchy-kids time` after sudo has already asked, sends none.
"""

import argparse
import getpass
import json
import os
import sys

from . import paths, proto

SCOPE = "time"


def _fail(message, code=1):
    print(json.dumps({"ok": False, "error": message}))
    return code


def _ask_password(args):
    if os.geteuid() == 0:
        return ""
    if args.password_stdin or not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    return getpass.getpass("Parent password: ")


def _with_user(args, payload):
    if getattr(args, "user", None):
        payload["user"] = args.user
    return payload


def _request(args, payload, timeout=5):
    payload = dict(payload)
    payload["scope"] = SCOPE
    return proto.request(paths.client_socket_candidates(), _with_user(args, payload), timeout=max(timeout, 25) if payload.get("password") else timeout)


def _emit(payload, human=False):
    if human:
        print(_human(payload))
    else:
        print(json.dumps(payload))
    return 0 if payload.get("ok") else 1


def _clock(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _minutes(seconds):
    seconds = max(0, int(seconds))
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    if seconds < 60:
        return f"{seconds} s"
    return f"{seconds // 60} min {seconds % 60} s"


def _human(payload):
    if not payload.get("ok"):
        return f"error: {payload.get('error')}"
    if "day" in payload and isinstance(payload["day"], dict):
        return _human_day(payload)
    if "remaining_seconds" not in payload:
        if "mode" in payload and "mode_reason" in payload:
            reason = {"schedule": "school hours", "chosen": "chosen", "parent": "set by the parent", "free": "no school now"}.get(payload["mode_reason"], payload["mode_reason"])
            until = f" until {payload['school_until']}" if payload.get("school_until") else ""
            return f"{'School mode' if payload['mode'] == 'school' else 'Free time'} ({reason}{until})"
        return json.dumps(payload, indent=2)
    earn = payload.get("earn", {})
    lines = [
        f"Screen time for {payload['user']}, {payload['day']}: {payload['phase']}, "
        f"{'school mode' if payload.get('mode') == 'school' else 'free time'}",
        f"  left        {_minutes(payload['remaining_seconds'])}",
        f"  today       budget {_minutes(payload['budget_seconds'])}, "
        f"earned {_minutes(payload['earned_seconds'])}, "
        f"given {_minutes(payload['granted_seconds'])}, "
        f"used {_minutes(payload['spent_seconds'])}",
    ]
    if payload.get("lock_in_seconds") is not None:
        lines.append(f"  lock in     {payload['lock_in_seconds']} s")
    if earn.get("enabled"):
        lines.append(f"  earning     a set of {earn['questions_per_set']} questions at {earn['level']} "
                     f"earns {earn['set_minutes']} min ({_minutes(earn['seconds_per_correct'])} per right answer); "
                     f"{_minutes(earn['room_seconds'])} of {_minutes(earn['cap_seconds'])} still earnable today")
    else:
        lines.append("  earning     off")
    return "\n".join(lines)


def _human_day(payload):
    day = payload["day"]
    lines = [f"Screen time for {payload['user']}, {day.get('day')}",
             f"  budget {_minutes(day.get('budget_seconds', 0))}, earned {_minutes(day.get('earned_seconds', 0))} "
             f"(cap {payload.get('cap_minutes', 0)} min), given {_minutes(day.get('granted_seconds', 0))}, "
             f"used {_minutes(day.get('spent_seconds', 0))}, right answers {day.get('correct_answers', 0)}"]
    for entry in day.get("ledger", []):
        stamp = entry.get("t", 0)
        try:
            from datetime import datetime
            when = datetime.fromtimestamp(float(stamp)).strftime("%H:%M")
        except (ValueError, OverflowError, OSError):
            when = "??:??"
        kind = entry.get("kind")
        meta = entry.get("meta") or {}
        if kind == "earn":
            lines.append(f"  {when}  right   {meta.get('q', '')}  +{_minutes(entry.get('seconds', 0))}")
        elif kind == "miss":
            lines.append(f"  {when}  wrong   {meta.get('q', '')}  answered {meta.get('given')}, it was {meta.get('answer')}")
        elif kind == "grant":
            lines.append(f"  {when}  given   {_minutes(entry.get('seconds', 0))}")
        elif kind == "locked":
            lines.append(f"  {when}  locked  ({meta.get('reason', '')})")
        elif kind == "blocked":
            lines.append(f"  {when}  time up ({meta.get('reason', '')})")
        elif kind in ("pause", "resume"):
            lines.append(f"  {when}  {kind}")
    return "\n".join(lines)


def cmd_status(args):
    return _emit(_request(args, {"cmd": "status"}), args.human)


def cmd_ping(args):
    return _emit(_request(args, {"cmd": "ping"}), args.human)


def cmd_users(args):
    return _emit(_request(args, {"cmd": "users"}), args.human)


def cmd_users_set(args):
    return _emit(_request(args, {"cmd": "users.set", "user": args.name, "enabled": args.enabled}), args.human)


def cmd_history(args):
    return _emit(_request(args, {"cmd": "history", "days": args.days}), args.human)


def cmd_day(args):
    return _emit(_request(args, {"cmd": "day", "day": args.day}), args.human)


def cmd_watch(args):
    sock = proto.connect(paths.client_socket_candidates(), timeout=None)
    try:
        proto.write_line(sock, _with_user(args, {"cmd": "watch", "scope": SCOPE}))
        reader = proto.LineReader(sock)
        while True:
            payload = reader.read()
            if payload is None:
                return 0
            print(json.dumps(payload), flush=True)
    finally:
        sock.close()


def cmd_quiz(args):
    """One earning question, or practice in the terminal with --keep-going."""
    while True:
        response = _request(args, {"cmd": "quiz.next"})
        if not response.get("ok"):
            return _emit(response, args.human)
        question = response["question"]
        if not args.human:
            return _emit(response, False)
        try:
            given = input(f"{question['text']} = ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        verdict = _request(args, {"cmd": "quiz.answer", "id": question["id"], "answer": given})
        if verdict.get("error") == "too_fast":
            print(f"  too fast, wait another {verdict['wait_seconds']}s")
            continue
        if not verdict.get("ok"):
            print(f"  {verdict.get('error')}")
            continue
        if verdict["correct"]:
            print(f"  correct, +{_minutes(verdict['reward_seconds'])}   (left: {_minutes(verdict['remaining_seconds'])})")
        else:
            print(f"  wrong, it was {verdict['answer']}")
        if not args.keep_going:
            return 0


def cmd_mode(args):
    if not args.mode:
        return _emit(_request(args, {"cmd": "mode.get"}), args.human)
    payload = {"cmd": "mode.set", "mode": args.mode}
    # The panel asks before switching to free time. Always send its supplied
    # password with the first request so the daemon validates it, even if no
    # mode change is needed. Empty stdin still allows the kid to choose school.
    if os.geteuid() != 0 and args.password_stdin:
        password = _ask_password(args)
        if password:
            payload["password"] = password
    response = _request(args, payload)
    if response.get("error") == "parent_required" and os.geteuid() != 0:
        # Choosing free time is the parent's: ask, and try again. This also
        # covers auto when it would resolve to free time.
        if not args.password_stdin and sys.stdin.isatty():
            payload["password"] = _ask_password(args)
            response = _request(args, payload)
    return _emit(response, args.human)


def cmd_practice(args):
    # Practice grants no time and needs no privileged service. Keep it usable
    # when parents install Math but leave screen-time enforcement disabled.
    try:
        from omarchy_kids.screen_time.quiz import practice
        from omarchy_kids.screen_time.config import LEVELS
    except ModuleNotFoundError:
        return _emit({"ok": False, "error": "module_not_installed", "module": "time"}, args.human)
    if args.level not in LEVELS:
        return _emit({"ok": False, "error": "bad_level"}, args.human)
    return _emit({"ok": True, **practice(args.level)}, args.human)


def cmd_answer(args):
    return _emit(_request(args, {"cmd": "quiz.answer", "id": args.id, "answer": args.answer}), args.human)


def cmd_grant(args):
    return _emit(_request(args, {"cmd": "grant", "minutes": args.minutes, "password": _ask_password(args)}), args.human)


def cmd_pause(args):
    return _emit(_request(args, {"cmd": "pause", "value": args.value, "password": _ask_password(args)}), args.human)


def cmd_lock(args):
    return _emit(_request(args, {"cmd": "lock", "password": _ask_password(args)}), args.human)


def cmd_idle(args):
    return _emit(_request(args, {"cmd": "idle", "value": args.value}), args.human)


def cmd_demo(args):
    return _emit(_request(args, {"cmd": "demo", "value": args.value, "password": _ask_password(args)}), args.human)


def cmd_config_get(args):
    return _emit(_request(args, {"cmd": "config.get", "password": _ask_password(args)}), args.human)


def cmd_config_set(args):
    text = paths.read_regular(args.file) if args.file != "-" else sys.stdin.read()
    if not text:
        return _fail("could not read the config file")
    try:
        incoming = json.loads(text)
    except ValueError:
        return _fail("that file is not valid json")
    return _emit(_request(args, {"cmd": "config.set", "config": incoming, "password": _ask_password(args)}), args.human)


def cmd_config_patch(args):
    try:
        patch = json.loads(args.patch)
    except ValueError:
        return _fail("that is not valid json")
    if not isinstance(patch, dict):
        return _fail("the patch must be a json object")
    return _emit(_request(args, {"cmd": "config.patch", "patch": patch, "password": _ask_password(args)}), args.human)


def cmd_reflect(args):
    return _emit(_request(args, {"cmd": "reflect", "text": " ".join(args.words)}), args.human)


def cmd_forget(args):
    return _emit(_request(args, {"cmd": "reflect.forget", "t": args.t}), args.human)


def build_parser():
    parser = argparse.ArgumentParser(prog="omarchy-kids-controls-" + SCOPE + "-client", description="Community controls service client")
    parser.add_argument("--human", action="store_true", help="readable output instead of json")
    parser.add_argument("--password-stdin", action="store_true", help="read the parent password from stdin")
    parser.add_argument("--user", help="the account to act on (root only)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping").set_defaults(func=cmd_ping)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("watch").set_defaults(func=cmd_watch)

    users = sub.add_parser("users", help="the accounts the daemon manages (root)")
    users_sub = users.add_subparsers(dest="users_command")
    users.set_defaults(func=cmd_users)
    users_add = users_sub.add_parser("add")
    users_add.add_argument("name")
    users_add.set_defaults(func=cmd_users_set, enabled=True)
    users_remove = users_sub.add_parser("remove")
    users_remove.add_argument("name")
    users_remove.set_defaults(func=cmd_users_set, enabled=False)

    history = sub.add_parser("history")
    history.add_argument("--days", type=int, default=14)
    history.set_defaults(func=cmd_history)

    day = sub.add_parser("day", help="one day's ledger, today by default")
    day.add_argument("day", nargs="?", default=None)
    day.set_defaults(func=cmd_day)

    quiz = sub.add_parser("quiz", help="an earning question, or practice in the terminal")
    quiz.add_argument("--keep-going", action="store_true")
    quiz.set_defaults(func=cmd_quiz)

    mode = sub.add_parser("mode", help="school mode or free time: show, or set school, free, or auto")
    mode.add_argument("mode", nargs="?", choices=["school", "free", "auto"], default=None)
    mode.set_defaults(func=cmd_mode)

    practice = sub.add_parser("practice", help="a practice question with its answer")
    practice.add_argument("level", nargs="?", default="grade5")
    practice.set_defaults(func=cmd_practice)

    answer = sub.add_parser("answer")
    answer.add_argument("id")
    answer.add_argument("answer")
    answer.set_defaults(func=cmd_answer)

    grant = sub.add_parser("grant", help="give or take minutes (parent)")
    grant.add_argument("minutes", type=int)
    grant.set_defaults(func=cmd_grant)

    pause = sub.add_parser("pause")
    pause.set_defaults(func=cmd_pause, value=True)
    resume = sub.add_parser("resume")
    resume.set_defaults(func=cmd_pause, value=False)

    sub.add_parser("lock").set_defaults(func=cmd_lock)

    reflect = sub.add_parser("reflect", help="write a note about your own screen time")
    reflect.add_argument("words", nargs="+")
    reflect.set_defaults(func=cmd_reflect)

    forget = sub.add_parser("forget", help="take one of your own notes back")
    forget.add_argument("t", type=float, help="the note's timestamp, as status reports it")
    forget.set_defaults(func=cmd_forget)

    idle = sub.add_parser("idle", help="for the hypridle hook")
    idle.add_argument("value", choices=["on", "off"])
    idle.set_defaults(func=lambda a: cmd_idle_wrap(a))

    demo = sub.add_parser("demo")
    demo.add_argument("value", choices=["on", "off"])
    demo.set_defaults(func=lambda a: cmd_demo_wrap(a))

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("get").set_defaults(func=cmd_config_get)
    config_set = config_sub.add_parser("set")
    config_set.add_argument("file", help="a json file, or - for stdin")
    config_set.set_defaults(func=cmd_config_set)
    config_patch = config_sub.add_parser("patch", help="merge a partial change into the profile")
    config_patch.add_argument("patch", help="a json object, e.g. '{\"earn\": {\"enabled\": false}}'")
    config_patch.set_defaults(func=cmd_config_patch)

    return parser


def cmd_idle_wrap(args):
    args.value = args.value == "on"
    return cmd_idle(args)


def cmd_demo_wrap(args):
    args.value = args.value == "on"
    return cmd_demo(args)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except proto.ProtocolError as exc:
        return _fail(f"bad reply: {exc}")
    except OSError as exc:
        # Nothing listening, no permission on the socket, or a daemon that did
        # not answer in time: JSON either way, since the shell reads it.
        return _fail(f"no daemon: {exc}")
