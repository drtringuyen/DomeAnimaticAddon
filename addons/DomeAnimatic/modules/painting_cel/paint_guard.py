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
# Strip clicks do not reliably push a depsgraph update, so a cheap repeating
# timer polls the active strip as well; both paths share _check_active_strip(),
# which is idempotent via the _last_active_strip cache.

_last_active_strip = None
_TIMER_INTERVAL    = 0.25


def _slot_from_strip(se, strip):
    """Map an IMAGE strip to a cel slot. Filename pattern is authoritative
    (cel PNGs are addon-generated), channel name second, channel number last —
    strips occasionally get parked on foreign channels while editing."""
    for layer in cel_store.LAYERS:
        if f"_{layer.filename_label}_f_" in strip.name:
            return layer.slot_id
    try:
        ch_name = se.channels[strip.channel].name.upper()
    except Exception:
        ch_name = ""
    slot = {'CEL_BG': 'BG', 'BG': 'BG',
            'CEL_A': 'CEL_A', 'CEL_B': 'CEL_B'}.get(ch_name)
    if slot:
        return slot
    layer = cel_store.BY_CHANNEL.get(strip.channel)
    return layer.slot_id if layer else None


def _check_active_strip() -> None:
    """If the Dome Animatic VSE's active strip changed to a cel image strip,
    activate the matching cel slot (switches Image Editor + paint canvas)."""
    global _last_active_strip
    scene = bpy.data.scenes.get("Dome Animatic")
    if scene is None or scene.sequence_editor is None:
        return
    se    = scene.sequence_editor
    strip = se.active_strip
    key   = (strip.name, strip.channel) if strip else None
    if key == _last_active_strip:
        return
    _last_active_strip = key
    if strip is None or strip.type != 'IMAGE':
        return
    slot = _slot_from_strip(se, strip)
    if slot is None:
        return
    # Only follow selection while painting on cel layers
    try:
        ctx_scene = bpy.context.scene or scene
        if ctx_scene.domeanimatic.synch_mode != 'CEL_LAYERS':
            return
    except Exception:
        return
    g = gp()
    if g.active_cel != slot:
        g.active_cel = slot   # fires _on_active_cel_changed


@persistent
def _vse_active_strip_watch(scene, depsgraph):
    _check_active_strip()


def _vse_selection_timer():
    try:
        _check_active_strip()
    except Exception:
        pass
    return _TIMER_INTERVAL


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
    if not bpy.app.timers.is_registered(_vse_selection_timer):
        bpy.app.timers.register(_vse_selection_timer,
                                first_interval=_TIMER_INTERVAL, persistent=True)


def unregister() -> None:
    global _last_active_strip
    if _vse_active_strip_watch in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_vse_active_strip_watch)
    if bpy.app.timers.is_registered(_vse_selection_timer):
        try:
            bpy.app.timers.unregister(_vse_selection_timer)
        except Exception:
            pass
    _last_active_strip = None
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
