# DomeAnimatic — Performance Diagnosis (2026-07-07)

> **STATUS: FIXES APPLIED + VERIFIED (same day).** Measured after optimization,
> same scene, same machine:
>
> | Metric | Before | After |
> |---|---|---|
> | Full window redraw (median, warm) | **68.5 ms (~15 fps)** | **17.5 ms (~57 fps)** |
> | Painting Cel panel helpers / redraw | 14.6 ms | 0.003 ms (2 s TTL cache) |
> | `_check_gap_paint` watcher tick | 0.54 ms | 0.003 ms (frame+TTL cache) |
> | `_count_unused_cel_files` (uncached) | 10.96 ms | 1.02 ms (per-element resolve) |
> | `live_texture_sync_handler` /frame | ~1.6–2 ms of scans | 0.85 ms total (one-pass scan) |
>
> Key insight found during implementation: the **sidebar panel draw** (drawn in
> both the Image Editor and the 3D View) was the largest addon-side share of
> the 68 ms redraw — `glob` + `os.listdir` + per-frame path resolution on every
> redraw. Fixes: one-pass channel scan (`vse_get_strips_on_channels`), TTL
> caches in ui.py, per-element (not per-frame) file resolution, cached
> unit-quad GPU batches drawn via `gpu.matrix`, and deferred gap-paint strip
> creation (immediate at stroke end via depsgraph, 1 s debounce from the
> timer — never mid-stroke). Behavior verified live: strip-lookup parity over
> 654 frames (0 mismatches), overlay renders with no exceptions, gap-paint
> auto-create + stroke adoption intact.
>
> Item G below (workspace layout) still applies on weak hardware.

Measured live in the user's Blender 5.1 "Dome Animatic" scene via MCP, on the
*fast* dev machine. Numbers scale up (worse) on a weaker CPU + RTX 3060.

Scene scale that drives everything below:
- VSE `strips_all` = **474** strips (252 IMAGE, 218 SOUND, plus text/color/meta)
- Cel images = **2260 × 1480** RGBA float (~53 MB each in RAM, ×3 layers)
- Workspace open at once: **2 Sequencer editors**, **2 3D viewports**, 1 image
  editor, 1 node editor, 2 properties, 2 outliners, 1 info.

---

## TL;DR — ranked root causes

| # | Cause | Measured | Regression? | Impact on weak HW |
|---|---|---|---|---|
| 1 | **Full-window native redraw of the heavy workspace** | **~68 ms / redraw (~15 fps) on the fast machine** | No (scene/layout) | Dominant. Scales to 150–250 ms on a 3060 + weak CPU |
| 2 | `live_texture_sync_handler` frame-change scan | **3.7 ms / frame** during playback/scrub | Partly (touched recently) | 3.7ms × every frame of playback, ×2–3 on weak CPU |
| 3 | `_check_gap_paint` — no change-cache, full O(474) scan ×3 | 0.54 ms, **4×/sec on timer + every depsgraph fire** | **Yes (new this session)** | Constant idle churn; compounds under redraw pressure |
| 4 | `vse_get_strip_on_channel` is O(all 474 strips) | iterates 218 sounds etc. every call | Pre-existing, now called more | Multiplies #2 and #3 |
| 5 | Gap-paint auto-create fires `save_datablock_to_png` **from the 0.25 s timer** | ~6 ms pixel copy + disk write | **Yes (new)** | Visible hitch mid-stroke when drawing on an empty frame |
| 6 | `batch_for_shader` rebuilt every overlay redraw | overlay total 0.2–0.4 ms | Pre-existing | Minor |

**The single biggest lag (#1) is NOT the addon's Python** — proven below. But the
addon *amplifies* it (#2–#5) by doing avoidable CPU work on a background timer,
on every frame change, and by forcing full redraws more often than needed.

---

## Evidence

### The addon's draw code is not the redraw cost
`wm.redraw_timer(DRAW_WIN_SWAP)`, median of 15:
```
WITH  addon overlay handler : 68.5 ms
WITHOUT addon overlay handler: 68.1 ms   ← removing it changes nothing
```
Instrumented overlay draw callback: **0.207 ms/redraw**. `gpu.texture.from_image`
is GPU-cached → **~0.000 ms** (re-uploads only when the image is dirtied).
→ The ~68 ms is Blender natively drawing 2 Sequencer editors (474 strips) + 2
viewports. **This is the primary lag and it is workspace/scene-driven.**

### Painting does not spam depsgraph (so the depsgraph handler is not the paint hot path)
A full 40-sample `paint.image_paint` stroke fired `depsgraph_update_post`
**once**. Raw `image.pixels.foreach_set(); update()` fired it **zero** times.
→ `_check_gap_paint` in the depsgraph handler runs ~once per stroke, not per dab.

### Frame-change handler cost
`live_texture_sync_handler` = **3.73 ms / frame**, dominated by 3×
`vse_get_strip_on_channel` (each a full 474-strip scan). Fires on **every frame**
during playback/scrub — the core "paint across frames" workflow.

### `_check_gap_paint` does full work unconditionally
No `(frame, active_slot)` cache (unlike `_check_active_strip`, which early-outs
via `_last_active_strip`). Every 0.25 s timer tick **and** every depsgraph fire
it runs 3× O(474) `vse_get_strip_on_channel` + 3× `get_cel_image` +
`img.source`/`is_dirty` reads. ≈ 24 full-list touches/sec at idle.

---

## Fix list for Fable 5 (highest ROI first)

### A. Cut the O(474) strip scans — `vse_helpers.vse_get_strip_on_channel` (vse_helpers.py:91)
It loops all `strips_all` (incl. 218 sound strips) on every call.
- Filter by type/channel up front, or build a **per-channel index dict**
  `{channel: [image strips sorted by frame]}` cached and invalidated on strip
  add/remove. Bisect for the strip containing `frame`.
- This single change speeds up #2, #3, #4 together.

### B. Add a change-cache to `_check_gap_paint` — paint_guard.py:95
Short-circuit when `(frame, active_slot)` is unchanged AND the active cel's
`is_dirty` pointer hasn't flipped. Model it on `_check_active_strip`'s
`_last_active_strip` guard. Skip the whole scan when
`synch_mode != 'CEL_LAYERS'` (already partly done) and when the Dome scene
isn't the active scene.

### C. Don't do disk/pixel work from the timer — paint_guard.py:129–136
Gap-paint currently can call `ensure_strip_for_slot(adopt_datablock=True)` →
`image_io.save_datablock_to_png` (~6 ms foreach_get/set of 13 M floats + scale +
PNG save) straight from the 0.25 s timer, i.e. potentially **mid-stroke**.
- Detect the paint intent but **defer** the heavy create to stroke-end / an idle
  tick, or run it once and debounce. Never save-to-disk from the polling timer.

### D. Throttle the polling timer — paint_guard.py:148 / `_TIMER_INTERVAL`
0.25 s → the timer runs `_check_active_strip` + `_check_gap_paint` forever.
- Raise interval (e.g. 0.5 s), and/or replace the strip-selection polling with
  `bpy.msgbus` on `SequenceEditor.active_strip` (the 0.25 s timer was already
  flagged as a workaround in the refactor notes).

### E. Reduce forced full redraws — `vse_helpers.tag_all_image_editors_redraw` (vse_helpers.py:333)
26 call sites; each forces the ~68 ms redraw of every image editor in every
window. Audit hot callers (opacity/visibility update callbacks in
global_scene_shared_props.py, `_check_gap_paint` stale branch) and:
- Tag only the affected area, not all editors in all windows.
- Coalesce redundant tags (don't tag inside a per-channel loop).

### F. Overlay micro-opts — gpu_overlay.py:56, 145 (low priority)
- Cache the `batch_for_shader` geometry (it's a static full-image quad); only
  the region-space verts change → rebuild verts, reuse the batch/shader.
- Skip drawing layers whose opacity is 0 or that aren't visible (already partly
  done for visibility).

### G. Workspace guidance (not code — biggest real-world win for the user)
The 68 ms/redraw is largely the **two 474-strip Sequencer editors + two
viewports** redrawing together. On weak HW, recommend a painting workspace with
**one** VSE and **one** viewport, and collapse the timeline while painting. This
alone likely restores interactivity more than any code change.

---

## What is NOT the problem (ruled out by measurement)
- The GPU overlay Python (0.2 ms).
- `gpu.texture.from_image` (cached, ~0 ms).
- GENERATED-vs-FILE blank images (identical upload cost; GENERATED made
  frame-change *cheaper* by removing a 6 ms numpy fill).
- depsgraph handler firing per brush dab (it fires ~1×/stroke).
