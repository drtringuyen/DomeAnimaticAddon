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
from ...global_scene_shared_props import gp, sp


# ── Handler state ─────────────────────────────────────────────────────────────

class _SyncState:
    last_path:       dict[int, str] = {1: "", 2: "", 3: "", 4: ""}
    handler_blocked: bool           = False
    _was_playing:    bool           = False   # play-state tracking for res switching
    painting_baked:  bool           = False   # True while user is painting on CEL_Baked


_s = _SyncState()


# ── Resolution helpers ────────────────────────────────────────────────────────

def _preview_size() -> tuple[int, int]:
    try:
        dome = bpy.data.scenes.get("Dome Animatic")
        sc = dome.domeanimatic if dome else bpy.context.scene.domeanimatic
        w = (int(sc.tex_width  * sc.tex_scale) // 10) * 10 or max(1, int(sc.tex_width  * sc.tex_scale))
        h = (int(sc.tex_height * sc.tex_scale) // 10) * 10 or max(1, int(sc.tex_height * sc.tex_scale))
        return max(1, w), max(1, h)
    except Exception:
        return 960, 590


def _reference_size() -> tuple[int, int]:
    try:
        from ..painting_cel.image_io import get_reference_size
        return get_reference_size()
    except Exception:
        return 960, 590


def _all_datablocks() -> list:
    imgs = []
    live = cel_store.get_live_image()
    if live:
        imgs.append(live)
    for layer in cel_store.LAYERS:
        img = bpy.data.images.get(layer.datablock_name)
        if img:
            imgs.append(img)
    return imgs


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

    # synch_mode is on Scene props (saved in .blend) — read from dome_scene
    mode = dome_scene.domeanimatic.synch_mode
    if mode == 'OFF':
        return

    # ── Play-start detection (task 7) ─────────────────────────────────────────
    try:
        is_playing = bpy.context.screen.is_animation_playing
    except Exception:
        is_playing = False

    if is_playing and not _s._was_playing:
        pw, ph = _preview_size()
        cel_auto_save = getattr(dome_scene.domeanimatic, 'cel_auto_save', False)
        if cel_auto_save:
            # Only save channels that currently have a strip (last_path != "").
            # Channels in a gap have blank pixels — must not overwrite the previous strip's file.
            for ch, layer in cel_store.BY_CHANNEL.items():
                if _s.last_path[ch] == "":
                    continue
                img = bpy.data.images.get(layer.datablock_name)
                if img and img.is_dirty and img.filepath_raw:
                    try:
                        img.save()
                    except Exception:
                        pass
        for img in _all_datablocks():
            if img.size[0] != pw or img.size[1] != ph:
                img.scale(pw, ph)
        _s._was_playing = True

    frame = dome_scene.frame_current
    cel_auto_save = getattr(dome_scene.domeanimatic, 'cel_auto_save', False)

    if mode == 'BAKED':
        strip1 = vse_helpers.vse_get_strip_on_channel(dome_scene, 1, frame)
        if strip1:
            path1 = vse_helpers.resolve_strip_image_path(strip1, frame)
            if path1 and os.path.exists(path1) and path1 != _s.last_path[1]:
                if not is_playing and cel_auto_save and _s.last_path[1] != "":
                    live_img_save = cel_store.get_or_create_live_image()
                    if live_img_save.is_dirty and live_img_save.filepath_raw:
                        try:
                            live_img_save.save()
                        except Exception:
                            pass
                _s.painting_baked = False
                _load_path_into_image(cel_store.get_or_create_live_image(), path1)
                _s.last_path[1] = path1
                vse_helpers.log(f"[LiveTexture] Ch1 -> LiveDomePreview: {os.path.basename(path1)}")
        return

    if mode == 'CEL_LAYERS':
        for ch, layer in cel_store.BY_CHANNEL.items():
            strip = vse_helpers.vse_get_strip_on_channel(dome_scene, ch, frame)
            if not strip:
                if _s.last_path[ch] != "":
                    if not is_playing and cel_auto_save:
                        img_gap = bpy.data.images.get(layer.datablock_name)
                        if img_gap and img_gap.is_dirty and img_gap.filepath_raw:
                            try:
                                img_gap.save()
                            except Exception:
                                pass
                    _blank_cel_datablock(layer.slot_id)
                    _s.last_path[ch] = ""
                continue
            path = vse_helpers.resolve_strip_image_path(strip, frame)
            if not path or not os.path.exists(path) or path == _s.last_path[ch]:
                continue
            # Guard: only save when the channel was previously on a real strip (_s.last_path[ch] != "").
            # A channel coming out of a gap has blank pixels — must not overwrite the old PNG.
            if not is_playing and cel_auto_save and _s.last_path[ch] != "":
                cel_img_old = bpy.data.images.get(
                    cel_store.BY_CHANNEL[ch].datablock_name)
                if cel_img_old and cel_img_old.is_dirty and cel_img_old.filepath_raw:
                    try:
                        cel_img_old.save()
                    except Exception:
                        pass
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

        # ── Play-stop detection (task 8) ──────────────────────────────────────
        try:
            is_playing = bpy.context.screen.is_animation_playing
        except Exception:
            is_playing = False

        if _s._was_playing and not is_playing:
            rw, rh = _reference_size()
            for img in _all_datablocks():
                raw = img.filepath_raw
                if raw and os.path.exists(bpy.path.abspath(raw)):
                    img.reload()
                elif img.size[0] != rw or img.size[1] != rh:
                    img.scale(rw, rh)
            _s._was_playing = False

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


# ── Load-post restore ────────────────────────────────────────────────────────

@persistent
def load_post_handler(filepath):
    """After file open: re-register the frame handler if synch was active,
    and re-derive cel node image links from the material node tree."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return
    scene_props = dome_scene.domeanimatic
    _s.last_path = {1: "", 2: "", 3: "", 4: ""}

    if scene_props.synch_active:
        _register_frame_handler()
        vse_helpers.log("[LiveTexture] load_post: re-registered frame handler (synch was active)")

    # Re-derive *_mat_image pointers from the material node tree so they
    # don't stay None when the scene is reopened.
    mat = scene_props.target_material
    if mat is None or not mat.use_nodes:
        return
    SLOT_MAP = {
        'BG':    ('bg',    ['BG',    'Image Texture.001']),
        'CEL_A': ('cel_a', ['Cel_A', 'Image Texture.002']),
        'CEL_B': ('cel_b', ['Cel_B', 'Image Texture.003']),
    }
    for slot_id, (prop_prefix, node_names) in SLOT_MAP.items():
        if getattr(scene_props, f"{prop_prefix}_mat_image") is not None:
            continue  # already set
        for node_name in node_names:
            node = mat.node_tree.nodes.get(node_name)
            if node and node.type == 'TEX_IMAGE' and node.image:
                setattr(scene_props, f"{prop_prefix}_mat_image", node.image)
                vse_helpers.log(f"[LiveTexture] load_post: restored {prop_prefix}_mat_image → '{node.image.name}'")
                break


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
    _s.handler_blocked  = False
    _s.painting_baked   = False
    _s.last_path        = {1: "", 2: "", 3: "", 4: ""}


def start_live_sync() -> None:
    _s.painting_baked = False
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
    if load_post_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_post_handler)


def unregister() -> None:
    stop_live_sync()
    if scene_switch_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(scene_switch_handler)
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)
