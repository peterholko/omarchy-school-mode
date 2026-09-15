"""Fixed entry points for the root-owned controls runtime and local clients."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
role, *args = sys.argv[1:]
sys.argv = [sys.argv[0], *args]
if role == 'daemon':
    if os.geteuid() != 0:
        raise SystemExit('the controls service must run as root')
    for name in ('SCREEN_TIME_ROOT', 'SCREEN_TIME_LOCK_COMMAND', 'SCREEN_TIME_TEST_PASSWORD'):
        os.environ.pop(name, None)
    from omarchy_kids.core.daemon import main as daemon_main
    from omarchy_kids.core.storage import read_json
    marker = read_json(Path('/etc/omarchy-kids-controls/installation.json'), {})
    modules = marker.get('modules', [])
    if not modules:
        raise SystemExit('no installed modules; rerun the reviewed game setup')
    def main():
        return daemon_main(modules=modules)
elif role == 'pawberry':
    from omarchy_kids.pawberry.client import main
elif role == 'grove':
    from omarchy_kids.core.game_client import main as game_main
    def main():
        return game_main('grove')
elif role == 'typing':
    from omarchy_kids.core.game_client import main as game_main
    def main():
        return game_main('typing')
elif role == 'school-pam':
    from omarchy_kids.school_mode.pam_helper import main
elif role == 'school-websites':
    from omarchy_kids.school_mode.websites_native import main
elif role in {'school', 'time'}:
    from omarchy_kids.core import cli
    cli.SCOPE = role
    main = cli.main
else:
    raise SystemExit('unknown controls role')
raise SystemExit(main())
