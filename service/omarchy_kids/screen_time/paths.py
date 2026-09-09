"""Compatibility alias for shared parent runtime."""
import sys
from omarchy_kids.core import paths
sys.modules[__name__] = paths
