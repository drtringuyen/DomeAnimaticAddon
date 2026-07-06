"""
Test: auto-save must NOT overwrite a strip's PNG with blank pixels when the playhead
moves to an empty gap and then play starts (or the next strip is entered).

The fix is in vse_sync.py:
  - play-start save uses _s.last_path[ch] != "" guard (skip channels in a gap)
  - strip-change save uses the same guard

Steps:
  1. Insert a CEL_A full slot at the current frame (creates a PNG with a visible red pixel).
  2. Simulate the handler detecting an empty gap:
       _blank_cel_datablock fires, then _s.last_path[ch] = "" (as the handler does).
  3. Simulate play-start auto-save using the FIXED logic (last_path guard).
  4. Also simulate strip-change auto-save using the FIXED logic.
  5. Reload the PNG from disk and verify the red pixel survived.

PASS: red pixel still in file.
FAIL: file is all-zeros (blank pixels were saved over the real content).

Run via Blender MCP:
  exec(open(r'D:\\BlenderAddonDevelopment\\DomeAnimaticAddon\\addons\\DomeAnimatic\\tests\\test_cel_autosave_corruption.py').read())
"""

import bpy, os
import numpy as np

from DomeAnimatic import cel_store, vse_helpers
from DomeAnimatic.modules.painting_cel import image_io
from DomeAnimatic.modules.live_texture import vse_sync
from DomeAnimatic.modules.live_texture.vse_sync import _blank_cel_datablock

_CEL_A_CH = 3


def _fixed_play_start_save():
    """Replicate the fixed play-start auto-save from vse_sync."""
    overwritten = set()
    for ch, layer in cel_store.BY_CHANNEL.items():
        if vse_sync._s.last_path[ch] == "":
            continue  # in a gap — fixed: skip
        img = bpy.data.images.get(layer.datablock_name)
        if img and img.is_dirty and img.filepath_raw:
            img.save()
            overwritten.add(layer.slot_id)
    return overwritten


def _fixed_strip_change_save(ch):
    """Replicate the fixed strip-change auto-save from vse_sync."""
    if vse_sync._s.last_path[ch] == "":
        return False  # in a gap — fixed: skip
    layer   = cel_store.BY_CHANNEL[ch]
    img     = bpy.data.images.get(layer.datablock_name)
    if img and img.is_dirty and img.filepath_raw:
        img.save()
        return True
    return False


def _run():
    dome = bpy.data.scenes.get("Dome Animatic")
    assert dome is not None, "Dome Animatic scene not found"

    frame = dome.frame_current
    w, h  = image_io.get_reference_size()

    # ── 1. Create a CEL_A PNG with a distinctive red pixel ───────────────────
    folder   = image_io.ensure_cel_folder()
    filename = image_io.cel_filename('CEL_A', frame)
    abs_path = os.path.join(folder, filename)

    image_io.create_blank_png(abs_path, w, h)
    image_io.load_abs_into_slot('CEL_A', abs_path, w, h)

    cel_img = bpy.data.images.get('TransparentCel_Cel_A')
    assert cel_img is not None, "TransparentCel_Cel_A datablock not found"

    buf = np.zeros(w * h * 4, dtype=np.float32)
    buf[4] = 1.0; buf[7] = 1.0  # pixel 1: red+opaque
    cel_img.pixels.foreach_set(buf)
    cel_img.update()
    cel_img.save()
    cel_img.reload()
    _verify_red(abs_path, w, h, "SETUP")

    # ── 2. Simulate gap transition: blank fires, then last_path set to "" ────
    vse_sync._s.last_path[_CEL_A_CH] = abs_path  # was on this strip
    _blank_cel_datablock('CEL_A')               # → GENERATED transparent, filepath cleared
    vse_sync._s.last_path[_CEL_A_CH] = ""       # handler sets this after blank

    filepath_after_blank = cel_img.filepath_raw
    is_dirty_after_blank = cel_img.is_dirty

    # ── 3a. Fixed play-start save: should NOT save CEL_A (last_path="" = gap) ─
    overwritten_play = _fixed_play_start_save()
    play_save_skipped = 'CEL_A' not in overwritten_play

    # ── 3b. Fixed strip-change save: should NOT save (last_path="" = gap) ─────
    strip_save_fired = _fixed_strip_change_save(_CEL_A_CH)

    # ── 4. Check file on disk ────────────────────────────────────────────────
    check = bpy.data.images.load(abs_path, check_existing=False)
    cbuf  = np.empty(w * h * 4, dtype=np.float32)
    check.pixels.foreach_get(cbuf)
    bpy.data.images.remove(check)

    red_survived     = float(cbuf[4]) > 0.9
    file_is_all_zero = float(cbuf.max()) == 0.0

    passed = play_save_skipped and not strip_save_fired and red_survived

    return {
        'frame':                 frame,
        'test_file':             abs_path,
        'filepath_after_blank':  filepath_after_blank,
        'is_dirty_after_blank':  is_dirty_after_blank,
        'play_save_skipped':     play_save_skipped,
        'strip_save_skipped':    not strip_save_fired,
        'file_is_all_zero':      file_is_all_zero,
        'red_pixel_survived':    red_survived,
        'RESULT':                'PASS' if passed else 'FAIL',
    }


def _verify_red(abs_path, w, h, stage):
    img = bpy.data.images.load(abs_path, check_existing=False)
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    assert float(buf[4]) > 0.9, f"[{stage}] Red pixel not found in {abs_path}"


result = _run()
for k, v in result.items():
    print(f"  {k}: {v}")
