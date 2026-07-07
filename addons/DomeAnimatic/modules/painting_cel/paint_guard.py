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

import time

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


# ── Paint on an empty frame → auto-create the VSE strip ──────────────────────
# Photoshop/Toon Boom behavior: drawing on an empty slot creates the cel.
#
# The signal: when a cel channel has no strip at the playhead, its datablock
# is a clean GENERATED transparent image (vse_sync._blank_cel_datablock — no
# pixel write, so is_dirty is False). Brush strokes write pixels, so
# "is_dirty while in a gap" can ONLY mean the user painted there. The new
# strip then adopts the datablock's pixels (ensure_strip_for_slot with
# adopt_datablock=True) so the triggering stroke is kept.
#
# A FILE-source datablock in a gap is stale content from before an addon
# reload / file open (the blank never ran) — it gets normalized to the clean
# blank so the previous strip's drawing neither shows nor gets adopted.
#
# PERFORMANCE (2026-07-07): the strip list is large (~470 strips), so the
# 3-channel scan is cached per (frame) with a short TTL — the 0.25 s timer and
# depsgraph fires between rescans cost only a few RNA reads. Strip creation
# (PNG save + reload) is deferred: immediate on a depsgraph fire (= a stroke
# just ended) but debounced on timer ticks, so it never lands mid-stroke.

_GAP_SCAN_TTL   = 0.5   # s — rescan strips at most twice per second
_ADOPT_DEBOUNCE = 1.0   # s — timer path waits this long after first dirty

_gap_cache = {"frame": None, "scan_t": 0.0, "gap_layers": ()}
_gap_pending = {"slot": None, "t": 0.0}


def _invalidate_gap_cache() -> None:
    _gap_cache["frame"] = None
    _gap_pending["slot"] = None


def _check_gap_paint(from_depsgraph: bool = False) -> None:
    scene = bpy.data.scenes.get("Dome Animatic")
    if scene is None or scene.sequence_editor is None:
        return
    try:
        ctx_scene = bpy.context.scene or scene
        if ctx_scene.domeanimatic.synch_mode != 'CEL_LAYERS':
            return
    except Exception:
        return
    try:
        from ..live_texture import vse_sync
    except Exception:
        return

    frame = scene.frame_current
    now   = time.monotonic()

    # ── Rescan (one pass, all 3 channels) only on frame change / TTL expiry ──
    if _gap_cache["frame"] != frame or now - _gap_cache["scan_t"] > _GAP_SCAN_TTL:
        strips = vse_helpers.vse_get_strips_on_channels(
            scene, cel_store.CEL_CHANNELS, frame, include_muted=True)
        gap_layers = tuple(l for l in cel_store.LAYERS
                           if strips.get(l.vse_channel) is None)
        _gap_cache["frame"]      = frame
        _gap_cache["scan_t"]     = now
        _gap_cache["gap_layers"] = gap_layers

        for layer in gap_layers:
            img = cel_store.get_cel_image(layer.slot_id)
            if (img is not None and img.size[0]
                    and img.source != 'GENERATED'):
                # Stale pixels of a previous strip on an empty frame — blank.
                vse_sync._blank_cel_datablock(layer.slot_id)
                vse_sync._s.last_path[layer.vse_channel] = ""
                vse_helpers.tag_all_image_editors_redraw()

    gap_layers = _gap_cache["gap_layers"]
    if not gap_layers:
        return

    active_slot = gp().active_cel
    layer = next((l for l in gap_layers if l.slot_id == active_slot), None)
    if layer is None:
        _gap_pending["slot"] = None
        return
    img = cel_store.get_cel_image(active_slot)
    if (img is None or img.size[0] == 0
            or img.source != 'GENERATED' or not img.is_dirty):
        _gap_pending["slot"] = None
        return

    # User painted on an empty frame. Create the strip now if a stroke just
    # ended (depsgraph fire) or the dirty state has settled (timer debounce) —
    # never do the PNG save + reload in the middle of a stroke.
    if _gap_pending["slot"] != active_slot:
        _gap_pending["slot"] = active_slot
        _gap_pending["t"]    = now
        if not from_depsgraph:
            return
    elif not from_depsgraph and now - _gap_pending["t"] < _ADOPT_DEBOUNCE:
        return

    _gap_pending["slot"] = None
    from . import cel_layer_ops
    new_strip, created = cel_layer_ops.ensure_strip_for_slot(
        active_slot, adopt_datablock=True)
    _invalidate_gap_cache()
    if created and new_strip is not None:
        vse_helpers.log(
            f"[PaintGuard] {active_slot}: painted on empty frame "
            f"{frame} — auto-created strip '{new_strip.name}'")


@persistent
def _vse_active_strip_watch(scene, depsgraph):
    _check_active_strip()
    try:
        _check_gap_paint(from_depsgraph=True)
    except Exception:
        pass


def _vse_selection_timer():
    try:
        _check_active_strip()
        _check_gap_paint()
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
    _invalidate_gap_cache()
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
