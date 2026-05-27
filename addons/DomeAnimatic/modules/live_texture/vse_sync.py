"""
vse_sync.py — Persistent frame-change handlers that sync VSE strips to live
image datablocks.

BAKED mode:      VSE channel 1  →  LiveDomePreview
CEL_LAYERS mode: VSE channels 2/3/4  →  TransparentCel_BG/Cel_A/Cel_B

_SyncState replaces the old module-level globals (_last_path, _handler_blocked),
making the state resettable without reloading the module.
"""

import bpy
import os
from bpy.app.handlers import persistent
from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp


# ── Handler state ─────────────────────────────────────────────────────────────

class _SyncState:
    last_path:       dict[int, str] = {1: "", 2: "", 3: "", 4: ""}
    handler_blocked: bool           = False


_s = _SyncState()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_path_into_image(datablock, abs_path: str) -> None:
    if datablock.packed_file is not None:
        datablock.unpack(method='USE_ORIGINAL')
    try:
        rel = bpy.path.relpath(abs_path)
    except ValueError:
        rel = abs_path
    datablock.filepath = rel
    datablock.source   = 'FILE'
    datablock.reload()


def _blank_cel_datablock(slot_id: str) -> None:
    """Zero-fill a cel datablock so it shows transparent when no strip is present."""
    try:
        import numpy as np
        cel_img = cel_store.get_or_create_cel_image(slot_id)
        if cel_img.size[0] == 0:
            return
        w, h = cel_img.size
        buf  = np.zeros(w * h * 4, dtype=np.float32)
        cel_img.pixels.foreach_set(buf)
        cel_img.update()
    except Exception:
        pass


def _apply_track_muting_by_mode(mode: str) -> None:
    """Mute/unmute VSE tracks to match the current sync mode."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return
    for strip in dome_scene.sequence_editor.strips_all:
        if strip.channel == 1:
            strip.mute = (mode == 'CEL_LAYERS')
        elif strip.channel in cel_store.CEL_CHANNELS:
            strip.mute = (mode == 'BAKED')


# ── Main frame-change handler ─────────────────────────────────────────────────

@persistent
def live_texture_sync_handler(scene, depsgraph=None):
    if _s.handler_blocked:
        return

    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return

    mode = gp().synch_mode
    if mode == 'OFF':
        return

    frame = dome_scene.frame_current

    if mode == 'BAKED':
        strip1 = vse_helpers.vse_get_strip_on_channel(dome_scene, 1, frame)
        if strip1:
            path1 = vse_helpers.resolve_strip_image_path(strip1, frame)
            if path1 and os.path.exists(path1) and path1 != _s.last_path[1]:
                _load_path_into_image(cel_store.get_or_create_live_image(), path1)
                _s.last_path[1] = path1
                vse_helpers.log(f"[LiveTexture] Ch1 -> LiveDomePreview: {os.path.basename(path1)}")
        return

    if mode == 'CEL_LAYERS':
        for ch, layer in cel_store.BY_CHANNEL.items():
            strip = vse_helpers.vse_get_strip_on_channel(dome_scene, ch, frame)
            if not strip:
                if _s.last_path[ch] != "":
                    _blank_cel_datablock(layer.slot_id)
                    _s.last_path[ch] = ""
                continue
            path = vse_helpers.resolve_strip_image_path(strip, frame)
            if not path or not os.path.exists(path) or path == _s.last_path[ch]:
                continue
            cel_img = cel_store.get_or_create_cel_image(layer.slot_id)
            _load_path_into_image(cel_img, path)
            _s.last_path[ch] = path
            vse_helpers.log(f"[LiveTexture] Ch{ch} ({layer.slot_id}) -> {os.path.basename(path)}")


# ── Scene-switch auto-pause/resume ────────────────────────────────────────────

@persistent
def scene_switch_handler(scene, depsgraph=None):
    try:
        current    = bpy.context.scene
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if current is None or dome_scene is None:
            return
        is_dome        = current.name == "Dome Animatic"
        handler_active = live_texture_sync_handler in bpy.app.handlers.frame_change_pre
        if is_dome and not handler_active:
            _register_frame_handler()
            _s.last_path = {1: "", 2: "", 3: "", 4: ""}
            dome_scene.domeanimatic.synch_active = True
        elif not is_dome and handler_active:
            _unregister_frame_handler()
    except Exception as e:
        vse_helpers.log(f"[LiveTexture] scene_switch_handler error: {e}")


# ── Handler registration helpers ──────────────────────────────────────────────

def _unregister_frame_handler() -> None:
    bpy.app.handlers.frame_change_pre[:] = [
        h for h in bpy.app.handlers.frame_change_pre
        if getattr(h, '__name__', '') != 'live_texture_sync_handler'
    ]


def _register_frame_handler() -> None:
    _unregister_frame_handler()
    bpy.app.handlers.frame_change_pre.append(live_texture_sync_handler)


# ── Public API used by live_texture_ops ──────────────────────────────────────

def block_handler() -> None:
    _s.handler_blocked = True


def unblock_handler() -> None:
    _s.handler_blocked = False
    _s.last_path       = {1: "", 2: "", 3: "", 4: ""}


def start_live_sync() -> None:
    _s.last_path = {1: "", 2: "", 3: "", 4: ""}
    live = cel_store.get_or_create_live_image()
    if live.packed_file is not None:
        live.unpack(method='USE_ORIGINAL')
    live.source = 'FILE'
    _register_frame_handler()


def stop_live_sync() -> None:
    _unregister_frame_handler()
    _s.last_path = {1: "", 2: "", 3: "", 4: ""}


def get_strip_on_channel(scene, channel: int, frame: int):
    """Convenience wrapper used by live_texture_ops."""
    return vse_helpers.vse_get_strip_on_channel(scene, channel, frame)


# ── Register ──────────────────────────────────────────────────────────────────

def register() -> None:
    if scene_switch_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(scene_switch_handler)


def unregister() -> None:
    stop_live_sync()
    if scene_switch_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(scene_switch_handler)
