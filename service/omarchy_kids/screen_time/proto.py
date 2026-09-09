"""Compatibility alias for shared parent runtime."""
import sys
from omarchy_kids.core import proto
sys.modules[__name__] = proto
