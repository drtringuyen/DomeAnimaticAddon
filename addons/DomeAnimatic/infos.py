"""
infos.py — Infos panel operators.

Standard 5 operators (Build / Reload / Debug / Console / Clear) + one toggle
operator per module. Toggle operators call module_manager.toggle() and are
shown as blue/grey buttons in the Infos panel when debug_mode is ON.
"""

import bpy
import datetime
import sys

from . import module_manager
from .global_scene_shared_props import gp

BUILD_TIME = datetime.datetime.now().strftime("%d/%m/%y %H:%M")


# ── Standard 5 operators ──────────────────────────────────────────────────────

class DOMEANIMATIC_OT_Build(bpy.types.Operator):
    bl_idname = "domeanimatic.build_info"
    bl_label  = BUILD_TIME

    def execute(self, context):
        self.report({'INFO'}, f"DomeAnimatic — built {BUILD_TIME}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_Reload(bpy.types.Operator):
    """In-place reload: disable → purge sys.modules → enable."""
    bl_idname      = "domeanimatic.reload_addon"
    bl_label       = "Reload Addon"
    bl_description = "Reload the addon in-place without running install.py"

    def execute(self, context):
        addon_name = __name__.split(".")[0]
        try:
            bpy.ops.preferences.addon_disable(module=addon_name)
            keys = [k for k in sys.modules if k.startswith(addon_name)]
            for k in keys:
                del sys.modules[k]
            bpy.ops.preferences.addon_enable(module=addon_name)
            self.report({'INFO'}, "Addon reloaded.")
        except Exception as e:
            self.report({'ERROR'}, f"Reload failed: {e}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_ToggleDebug(bpy.types.Operator):
    bl_idname = "domeanimatic.toggle_debug"
    bl_label  = "Debug"

    def execute(self, context):
        g = gp(context)
        g.show_labels = not g.show_labels
        return {'FINISHED'}


class DOMEANIMATIC_OT_ToggleConsole(bpy.types.Operator):
    bl_idname = "domeanimatic.toggle_console"
    bl_label  = "Console"

    def execute(self, context):
        bpy.ops.wm.console_toggle()
        return {'FINISHED'}


class DOMEANIMATIC_OT_ClearConsole(bpy.types.Operator):
    bl_idname = "domeanimatic.clear_console"
    bl_label  = "Clear Console"

    def execute(self, context):
        print("\n" * 60)
        print("=" * 60)
        print("  Console cleared")
        print("=" * 60)
        return {'FINISHED'}


# ── Module toggle operators ───────────────────────────────────────────────────

def _make_toggle(mod_name: str, label: str) -> type:
    def execute(self, context):
        module_manager.toggle(mod_name)
        return {'FINISHED'}
    return type(
        f"DOMEANIMATIC_OT_Toggle_{mod_name}",
        (bpy.types.Operator,),
        {
            "bl_idname":      f"domeanimatic.toggle_{mod_name}",
            "bl_label":       label,
            "bl_description": f"Toggle the {label} module on/off",
            "execute":        execute,
        },
    )


TOGGLE_CLASSES = [
    _make_toggle("live_texture",       "Live Texture"),
    _make_toggle("painting_cel",       "Painting Cel"),
    _make_toggle("collage_collection", "Collage Collection"),
    _make_toggle("transition_vfx",     "Transition VFX"),
    _make_toggle("extra_tools",        "Extra Tools"),
]

INFOS_CLASSES = [
    DOMEANIMATIC_OT_Build,
    DOMEANIMATIC_OT_Reload,
    DOMEANIMATIC_OT_ToggleDebug,
    DOMEANIMATIC_OT_ToggleConsole,
    DOMEANIMATIC_OT_ClearConsole,
    *TOGGLE_CLASSES,
]


def register():
    for cls in INFOS_CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(INFOS_CLASSES):
        bpy.utils.unregister_class(cls)
