"""Compatibility alias for the shared client."""
import sys
from omarchy_kids.core import cli
sys.modules[__name__] = cli
