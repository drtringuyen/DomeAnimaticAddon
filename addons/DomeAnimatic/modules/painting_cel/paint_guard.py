"""
paint_guard.py — Invisible-layer warning dialog operators for the painting_cel
module, plus the VSE-selection → active-cel watcher.

The depsgraph_update_post guard that previously ran on every update has been removed.
Invisible-layer detection is now triggered proactively from DOMEANIMATIC_OT_cel_set_active,
and LiveDomePreview redirect is handled by the _on_synch_mode_changed callback in
global_scene_shared_props.py.

The watcher below is a new, cheap depsgraph handler: when the active strip in
the Dome Animatic VSE changes to a strip on a cel channel (2/3/4), the matching
cel slot becomes active (which switches the Image Editor / paint canvas via
_on_active_cel_changed).
"""

import bpy
from bpy.app.handlers import persistent

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp


# ── VSE active strip → active cel slot ────────────────────────────────────────

_last_active_strip = None


@persistent
def _vse_active_strip_watch(scene, depsgraph):
    """Selecting a strip on a cel channel in the VSE activates that cel slot."""
    global _last_active_strip
    if scene.name != "Dome Animatic":
        return
    se = scene.sequence_editor
    if se is None:
        return
    strip = se.active_strip
    key   = (strip.name, strip.channel) if strip else None
    if key == _last_active_strip:
        return
    _last_active_strip = key
    if strip is None or strip.type != 'IMAGE':
        return

    layer = cel_store.BY_CHANNEL.get(strip.channel)
    if layer is None:
        return
    # Only follow selection while painting on cel layers
    try:
        ctx_scene = bpy.context.scene or scene
        if ctx_scene.domeanimatic.synch_mode != 'CEL_LAYERS':
            return
    except Exception:
        return
    g = gp()
    if g.active_cel != layer.slot_id:
        g.active_cel = layer.slot_id   # fires _on_active_cel_changed


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
    if _vse_active_strip_watch not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_vse_active_strip_watch)


def unregister() -> None:
    global _last_active_strip
    if _vse_active_strip_watch in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_vse_active_strip_watch)
    _last_active_strip = None
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
