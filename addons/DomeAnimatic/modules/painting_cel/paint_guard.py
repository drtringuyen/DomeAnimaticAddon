"""
paint_guard.py — Invisible-layer guard for the painting_cel module.

Fires a depsgraph_update_post handler that detects when a user is painting on
a hidden cel. Shows a dialog to turn the layer on or pick another.
"""

import bpy
from bpy.app.handlers import persistent

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp


_warning_shown = False


@persistent
def invisible_layer_check(scene, depsgraph=None):
    """
    depsgraph_update_post — warns if Image Editor is in PAINT mode
    and the active cel is invisible.
    """
    global _warning_shown
    if _warning_shown:
        return
    try:
        g           = gp()
        active_slot = g.active_cel
        slot_key    = active_slot.lower()
        if getattr(g, f"{slot_key}_visible", True):
            return

        cel_img = cel_store.get_cel_image(active_slot)

        for window in bpy.data.window_managers[0].windows:
            for area in window.screen.areas:
                if area.type != 'IMAGE_EDITOR':
                    continue
                for space in area.spaces:
                    if space.type != 'IMAGE_EDITOR':
                        continue
                    if space.mode != 'PAINT':
                        continue
                    if space.image != cel_img:
                        continue
                    _warning_shown = True
                    bpy.ops.domeanimatic.cel_invisible_warning('INVOKE_DEFAULT')
                    return
    except Exception:
        pass


class DOMEANIMATIC_OT_cel_invisible_warning(bpy.types.Operator):
    """Dialog warning that painting is happening on an invisible layer."""
    bl_idname  = "domeanimatic.cel_invisible_warning"
    bl_label   = "Invisible Layer Warning"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        active = gp(context).active_cel
        col    = self.layout.column(align=True)
        col.label(text=f"You are painting on an invisible layer ({active}).", icon='ERROR')
        col.separator()
        col.label(text="Choose an action:")
        op = col.operator("domeanimatic.cel_invisible_turn_on",
                          text="A  — Turn On This Layer")
        op.slot = active
        col.operator("domeanimatic.cel_invisible_pick_other",
                     text="B  — Pick Another Layer (close)")

    def execute(self, context):
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_invisible_turn_on(bpy.types.Operator):
    """Turn on visibility of a cel slot (called from warning dialog)."""
    bl_idname = "domeanimatic.cel_invisible_turn_on"
    bl_label  = "Turn On Layer"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        global _warning_shown
        g = gp(context)
        setattr(g, f"{self.slot.lower()}_visible", True)
        _warning_shown = False
        vse_helpers.tag_all_image_editors_redraw()
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_invisible_pick_other(bpy.types.Operator):
    """Dismiss the invisible-layer warning."""
    bl_idname = "domeanimatic.cel_invisible_pick_other"
    bl_label  = "Pick Another Layer"

    def execute(self, context):
        global _warning_shown
        _warning_shown = False
        return {'FINISHED'}


CLASSES = [
    DOMEANIMATIC_OT_cel_invisible_warning,
    DOMEANIMATIC_OT_cel_invisible_turn_on,
    DOMEANIMATIC_OT_cel_invisible_pick_other,
]


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if invisible_layer_check not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(invisible_layer_check)


def unregister() -> None:
    if invisible_layer_check in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(invisible_layer_check)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
