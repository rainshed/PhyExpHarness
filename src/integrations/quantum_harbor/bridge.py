"""Compatibility alias; implementation belongs to the execution kernel."""
import sys
from src.execution.adapters.quantum_harbor import bridge as _implementation
sys.modules[__name__] = _implementation
