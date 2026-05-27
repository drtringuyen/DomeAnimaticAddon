"""
paint_guard.py — Invisible-layer warning dialog operators for the painting_cel module.

The depsgraph_update_post guard that previously ran on every update has been removed.
Invisible-layer detection is now triggered proactively from DOMEANIMATIC_OT_cel_set_active,
and LiveDomePreview redirect is handled by the _on_synch_mode_changed callback in
global_scene_shared_props.py.
"""

import bpy

from ... import vse_helpers
from ...global_scene_shared_props import gp


class DOMEANIMATIC_OT_cel_invisible_warning(bpy.types.Operator):
    """Dialog warning that the cel being activated is on an invisible layer."""
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
        g = gp(context)
        setattr(g, f"{self.slot.lower()}_visible", True)
        vse_helpers.tag_all_image_editors_redraw()
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_invisible_pick_other(bpy.types.Operator):
    """Dismiss the invisible-layer warning."""
    bl_idname = "domeanimatic.cel_invisible_pick_other"
    bl_label  = "Pick Another Layer"

    def execute(self, context):
        return {'FINISHED'}


CLASSES = [
    DOMEANIMATIC_OT_cel_invisible_warning,
    DOMEANIMATIC_OT_cel_invisible_turn_on,
    DOMEANIMATIC_OT_cel_invisible_pick_other,
]


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
