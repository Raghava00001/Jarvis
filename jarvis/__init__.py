# JARVIS V3
"""
One module identity for every JARVIS module.

The code historically imported the same files under two names (`core.alarm_system`
and `jarvis.core.alarm_system`), because both the project root and jarvis/ were on
sys.path. Python treats those as two different modules, which meant two state
managers, two alarm systems, two reminder managers and two hotkey registrations
in one running JARVIS.

All imports now use the `jarvis.` package. As a safety net, this finder makes any
remaining `core.X`, `gui.X` or `utils.X` import return the very same module
object as `jarvis.core.X` (etc.) instead of loading a second copy.
"""

import importlib
import importlib.abc
import importlib.util
import sys

_ALIASED = ("core", "gui", "utils")


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target):
        self._target = target

    def create_module(self, spec):
        return importlib.import_module(self._target)

    def exec_module(self, module):
        pass  # already executed under its canonical name


class _JarvisAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] not in _ALIASED:
            return None
        canonical = f"{__name__}.{fullname}"
        if importlib.util.find_spec(canonical) is None:
            return None
        spec = importlib.util.spec_from_loader(fullname, _AliasLoader(canonical),
                                               is_package=fullname in _ALIASED)
        return spec


# Console logging for every jarvis module (see logging_setup.py)
from jarvis.logging_setup import install as _install_logging

_install_logging()

if not any(isinstance(f, _JarvisAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _JarvisAliasFinder())
