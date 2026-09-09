"""Compatibility alias for shared parent runtime."""
import sys
from omarchy_kids.core import clock
sys.modules[__name__] = clock
