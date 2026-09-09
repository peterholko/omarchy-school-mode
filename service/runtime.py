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
    from omarchy_kids.core.daemon import main
elif role == 'grove':
    from omarchy_kids.number_grove.rewards import main
elif role in {'school', 'time'}:
    from omarchy_kids.core import cli
    cli.SCOPE = role
    main = cli.main
else:
    raise SystemExit('unknown controls role')
raise SystemExit(main())
