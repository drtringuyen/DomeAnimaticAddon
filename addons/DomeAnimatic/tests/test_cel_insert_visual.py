"""
Visual test: insert full slots for BG, CEL_A, CEL_B and verify pixel state after each.

After each insert the test checks:
  - The inserted slot's datablock has real content (or is transparent for blank cels).
  - The OTHER slots that have no strip are correctly blanked (alpha=0, not stale opaque).

'Stale opaque' on a blank slot is the root cause of the original bug:
  empty channels kept previous opaque pixels, covering BG in the overlay + material.

Run via Blender MCP:
  exec(open(r'D:\\BlenderAddonDevelopment\\DomeAnimaticAddon\\addons\\DomeAnimatic\\tests\\test_cel_insert_visual.py').read())
"""

import bpy, os
import numpy as np

from DomeAnimatic import cel_store, vse_helpers
from DomeAnimatic.modules.painting_cel import image_io, cel_layer_ops
from DomeAnimatic.modules.live_texture import vse_sync


def _img_stats(name):
    img = bpy.data.images.get(name)
    if img is None or img.size[0] == 0:
        return {'exists': False}
    arr = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
    img.pixels.foreach_get(arr)
    rgba = arr.reshape(-1, 4)
    return {
        'exists':    True,
        'size':      list(img.size),
        'rgb_max':   round(float(rgba[:, :3].max()), 4),
        'alpha_max': round(float(rgba[:, 3].max()), 4),
        'source':    img.source,
    }


def _find_test_frame(dome):
    """Find a frame with a track-1 strip and no cel strips on ch2/3/4."""
    for frame in range(856, 960):  # known gap in cel strips, ch1 has content
        ch1 = vse_helpers.vse_get_strip_on_channel(dome, 1, frame, include_muted=True)
        ch2 = vse_helpers.vse_get_strip_on_channel(dome, 2, frame)
        ch3 = vse_helpers.vse_get_strip_on_channel(dome, 3, frame)
        ch4 = vse_helpers.vse_get_strip_on_channel(dome, 4, frame)
        if ch1 and not ch2 and not ch3 and not ch4:
            return frame
    return None


def _insert_slot(dome, slot_id, frame, w, h, track1_strip):
    """Mirror the cel_insert_full logic for testing."""
    channel = cel_store.BY_SLOT[slot_id].vse_channel
    folder  = image_io.ensure_cel_folder()
    fname   = image_io.cel_filename(slot_id, frame)
    path    = os.path.join(folder, fname)

    existing = vse_helpers.vse_get_strip_on_channel(dome, channel, frame)
    if existing:
        dome.sequence_editor.strips.remove(existing)

    if slot_id == 'BG' and track1_strip:
        image_io.copy_track1_to_png(track1_strip, frame, path, w, h)
    else:
        image_io.create_blank_png(path, w, h)

    bg = vse_helpers.vse_get_strip_on_channel(dome, 2, frame) or track1_strip
    start = bg.frame_final_start if bg else frame
    end   = bg.frame_final_end   if bg else frame + 100

    vse_helpers.vse_insert_image_strip(dome, channel, path, start, end)
    image_io.load_slot_from_vse(slot_id, w, h)
    cel_layer_ops.activate_slot(slot_id)

    # The fix: force sync so empty channels blank their stale content
    vse_sync._s.last_path = {1: "", 2: "", 3: "", 4: ""}
    vse_sync.live_texture_sync_handler(dome)

    for area in bpy.data.window_managers[0].windows[0].screen.areas:
        area.tag_redraw()


def _run():
    dome = bpy.data.scenes.get("Dome Animatic")
    assert dome is not None, "Dome Animatic scene not found"

    frame = _find_test_frame(dome)
    assert frame is not None, "Could not find a clean test frame"

    dome.frame_set(frame)
    w, h = image_io.get_reference_size()
    track1 = vse_helpers.vse_get_strip_on_channel(dome, 1, frame, include_muted=True)

    steps = []

    # ── Step 1: Insert BG only ─────────────────────────────────────────────────
    _insert_slot(dome, 'BG', frame, w, h, track1)
    step1 = {
        'step': '1_BG_only',
        'BG':    _img_stats('TransparentCel_BG'),
        'CEL_A': _img_stats('TransparentCel_Cel_A'),
        'CEL_B': _img_stats('TransparentCel_Cel_B'),
    }
    # BG should have content (rgb_max > 0), CEL_A/B should be transparent (alpha_max = 0)
    step1['PASS'] = (
        step1['BG']['rgb_max'] > 0 and
        step1['CEL_A']['alpha_max'] == 0 and
        step1['CEL_B']['alpha_max'] == 0
    )
    steps.append(step1)

    # ── Step 2: Insert CEL_A ───────────────────────────────────────────────────
    _insert_slot(dome, 'CEL_A', frame, w, h, track1)
    step2 = {
        'step': '2_BG_CelA',
        'BG':    _img_stats('TransparentCel_BG'),
        'CEL_A': _img_stats('TransparentCel_Cel_A'),
        'CEL_B': _img_stats('TransparentCel_Cel_B'),
    }
    # BG still has content, CEL_A is blank (alpha=0 from create_blank_png), CEL_B still transparent
    step2['PASS'] = (
        step2['BG']['rgb_max'] > 0 and
        step2['CEL_A']['alpha_max'] == 0 and
        step2['CEL_B']['alpha_max'] == 0
    )
    steps.append(step2)

    # ── Step 3: Insert CEL_B ───────────────────────────────────────────────────
    _insert_slot(dome, 'CEL_B', frame, w, h, track1)
    step3 = {
        'step': '3_BG_CelA_CelB',
        'BG':    _img_stats('TransparentCel_BG'),
        'CEL_A': _img_stats('TransparentCel_Cel_A'),
        'CEL_B': _img_stats('TransparentCel_Cel_B'),
    }
    step3['PASS'] = (
        step3['BG']['rgb_max'] > 0 and
        step3['CEL_A']['alpha_max'] == 0 and
        step3['CEL_B']['alpha_max'] == 0
    )
    steps.append(step3)

    all_pass = all(s['PASS'] for s in steps)
    return {'frame': frame, 'steps': steps, 'OVERALL': 'PASS' if all_pass else 'FAIL'}


result = _run()
print(f"\nOverall: {result['OVERALL']} (frame {result['frame']})")
for s in result['steps']:
    print(f"  {s['step']}: {'PASS' if s['PASS'] else 'FAIL'}")
    print(f"    BG    rgb_max={s['BG']['rgb_max']}  alpha_max={s['BG']['alpha_max']}")
    print(f"    CEL_A rgb_max={s['CEL_A']['rgb_max']}  alpha_max={s['CEL_A']['alpha_max']}")
    print(f"    CEL_B rgb_max={s['CEL_B']['rgb_max']}  alpha_max={s['CEL_B']['alpha_max']}")
