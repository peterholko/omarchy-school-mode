"""Compatibility alias for shared parent runtime."""
import sys
from omarchy_kids.core import session
sys.modules[__name__] = session
