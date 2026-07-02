"""
module_manager.py — Dynamic module loader for DomeAnimatic.

Reads modules_config.json to determine which modules are enabled on startup.
Toggle operators in infos.py call load() / unload() at runtime and persist
the state back to modules_config.json.
"""

import importlib
import json
import os
import sys
import bpy

_PACKAGE    = __name__.rsplit(".", 1)[0]  # e.g. "addons.DomeAnimatic"
_CONFIG     = os.path.join(os.path.dirname(__file__), "modules_config.json")
_loaded: set[str] = set()

ALL_MODULES: list[dict] = [
    {"name": "live_texture",       "op": "domeanimatic.toggle_live_texture",       "icon": "TEXTURE"},
    {"name": "painting_cel",       "op": "domeanimatic.toggle_painting_cel",       "icon": "BRUSH_DATA"},
    {"name": "transition_vfx",     "op": "domeanimatic.toggle_transition_vfx",     "icon": "SEQUENCE_COLOR_06"},
    {"name": "extra_tools",        "op": "domeanimatic.toggle_extra_tools",         "icon": "TOOL_SETTINGS"},
]

_ALL_NAMES: set[str] = {m["name"] for m in ALL_MODULES}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _import_module(name: str):
    mod_path = f"{_PACKAGE}.modules.{name}"
    if mod_path in sys.modules:
        return sys.modules[mod_path]
    return importlib.import_module(mod_path)


def _read_config() -> dict:
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {n: {"enabled": True} for n in _ALL_NAMES}


def _write_config(config: dict) -> None:
    try:
        with open(_CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[ModuleManager] Could not write config: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def is_loaded(name: str) -> bool:
    return name in _loaded


def load(name: str) -> None:
    if name in _loaded:
        return
    try:
        mod = _import_module(name)
        mod.register()
        _loaded.add(name)
        print(f"[DomeAnimatic] Module '{name}' loaded.")
    except Exception as e:
        print(f"[DomeAnimatic] Error loading module '{name}': {e}")
        import traceback
        traceback.print_exc()


def unload(name: str) -> None:
    if name not in _loaded:
        return
    try:
        mod = _import_module(name)
        mod.unregister()
        _loaded.discard(name)
        print(f"[DomeAnimatic] Module '{name}' unloaded.")
    except Exception as e:
        print(f"[DomeAnimatic] Error unloading module '{name}': {e}")


def toggle(name: str) -> None:
    """Toggle a module on/off and persist the state to modules_config.json."""
    if is_loaded(name):
        unload(name)
        enabled = False
    else:
        load(name)
        enabled = True
    config = _read_config()
    config.setdefault(name, {})["enabled"] = enabled
    _write_config(config)


def load_all() -> None:
    config = _read_config()
    for m in ALL_MODULES:
        if config.get(m["name"], {}).get("enabled", True):
            load(m["name"])


def unload_all() -> None:
    for m in reversed(ALL_MODULES):
        unload(m["name"])
