# Lasso Transform — Architecture & Maintenance Guide

Photoshop-style lasso for the active cel layer, driven from the **Image Editor**
(default hotkey **L**). Draw a polygon lasso, then move / rotate / scale the
selected pixels as a floating GPU-textured quad — fully live, with **no**
`image.pixels` writes until you commit. The commit is a single vectorized numpy
pass.

As of the 2026-07 refactor the feature is split across **three files** so that
GPU drawing, pixel math, and the modal state machine each live on their own and
can be changed (or tested) independently.

```
modules/painting_cel/
├── lasso_transform_ops.py   # THE OPERATOR — state machine, modal dispatch, commit paths
├── lasso_draw.py            # GPU PREVIEW — draw handler + all on-screen drawing
└── lasso_raster.py          # PIXEL MATH — pure numpy helpers + the affine bake
```

Import direction (no cycles):

```
lasso_transform_ops  ──▶  lasso_draw     (registers itself, drives the handler)
        │
        └──────────────▶  lasso_raster   (reads/writes pixels, rasterizes, bakes)
```

`lasso_draw` and `lasso_raster` never import the operator. `lasso_draw` reaches
the running operator only through the reference the operator hands it via
`set_active_op()`.

---

## 1. Responsibilities — what lives where

### `lasso_raster.py` — pure pixel math (no bpy/operator state)

Every function takes explicit arguments and returns numpy arrays or a
`GPUTexture`. Nothing here reads global state, so it is unit-testable in
isolation (see `tests/`).

| Function | Purpose |
|---|---|
| `read_pixels(img)` | Whole image → `(h, w, 4)` float32 via `foreach_get`. |
| `write_pixels(img, buf)` | `(h, w, 4)` float32 → image, then `img.update()`. |
| `rasterize_polygon(points_px, bx0, by0, bw, bh)` | Even-odd point-in-polygon → `(bh, bw)` bool mask, tested at pixel centers. |
| `make_texture(buf_hw4)` | Upload an `(h, w, 4)` float32 buffer as a straight-alpha `GPUTexture` (RGBA16F). |
| `composite_float(dest_buf, patch, corners, tx, ty, angle, scale, bx0, by0)` | **The bake.** Inverse-affine bilinear sample of `patch`, alpha-over into `dest_buf` (premultiplied), mutated in place. |

> Only `read_pixels` / `write_pixels` touch a datablock, and only at commit
> time. Everything during interaction is textures + accumulator floats.

### `lasso_draw.py` — GPU preview + handler lifecycle

Owns the single `SpaceImageEditor` `POST_PIXEL` draw handler and the reference
to the currently running operator (one at a time). No pixels are written here —
this is pure preview.

**Lifecycle helpers the operator calls:**

| Function | When the operator calls it |
|---|---|
| `set_active_op(op)` / `clear_active_op()` | invoke / cleanup — register & release the running instance. |
| `get_active_op()` | invoke — guard against a second concurrent run. |
| `ensure_handler()` / `remove_handler()` | invoke / cleanup + `unregister()` — add & remove the draw handler. |

**Drawing (all read state off the passed `op`):**

- `_draw_lasso()` — the registered handler; bails unless the current space is an
  Image Editor WINDOW region, then dispatches to the three below.
- `_draw_composite()` — redraws the full cel stack with the CUT **hole**
  substituted on the active layer and the floating cut-out injected at its
  destination layer's depth. Draws an opaque backdrop first so a CUT hole reads
  as truly transparent over the editor's native drawing + `gpu_overlay`.
- `_draw_outline()` — the lasso polygon: live rubber-band + first-point handle in
  DRAW, the transformed selection boundary while floating.
- `_draw_status()` — top banner with the per-state key hints (`_STATUS_TEXT`).
- Shader getters `_get_image_shader()` / `_get_line_shader()` pick the first
  builtin that exists across Blender versions (`IMAGE_COLOR`→`IMAGE`,
  `POLYLINE_UNIFORM_COLOR`→`UNIFORM_COLOR`).

### `lasso_transform_ops.py` — the operator

`DOMEANIMATIC_OT_lasso_transform` — the modal state machine, coordinate helpers,
affine accumulator, and the commit paths (the only place pixels are written).
Also owns the keymap registration (**L** in the Image editor).

---

## 2. The floating transform (the core idea)

The selection is never re-rasterized while you drag it. Instead the operator
accumulates a single 2D affine and applies it two ways:

```
p' = scale · R(angle) · p + (tx, ty)
```

- **Preview:** the `patch` texture is drawn as a quad whose corners are the
  transformed bbox corners (`_transformed_bbox_corners`). GPU does the sampling.
- **Commit:** `lasso_raster.composite_float` walks *destination* pixels and
  samples the patch through the **inverse** affine (bilinear, premultiplied),
  so there is exactly one resample regardless of how many G/R/S moves you made.

Accumulator lives in four operator attributes: `_angle`, `_scale`, `_tx`,
`_ty`. `_sel_center` (mask centroid) is the pivot for rotate/scale and is itself
carried through the affine so the pivot tracks the piece.

---

## 3. State machine

```
        invoke
          │
          ▼
        DRAW ──(≥3 pts, close/Enter/double-click)──▶ FLOAT_IDLE
          │                                            │  ▲
        Esc/RMB-empty                                  │  │ LMB/Enter accept
          ▼                                     G/R/S  │  │ RMB/Esc revert
      CANCELLED                                        ▼  │
                                              GRAB / ROTATE / SCALE
```

`modal()` dispatches by `self._state` to one of three handlers:

| State | Handler | Key actions |
|---|---|---|
| `DRAW` | `_modal_draw` | LMB add point · click-near-P0 / double-click / Enter close · RMB undo point (or cancel if empty) · Esc cancel · clicks outside the region pass through |
| `FLOAT_IDLE` | `_modal_idle` | drag inside selection = move · click outside = commit+finish · `G`/`R`/`S` sub-modes · `Shift+D` stamp-duplicate · `Ctrl+J`/`Ctrl+X` dup/cut→above (switches active layer) · `Ctrl+C` copy to clipboard · `Ctrl+V` commit + paste clipboard · `L` commit + new lasso · `X` delete · Enter apply · Esc drop · **everything else passes through** |
| `GRAB`/`ROTATE`/`SCALE` | `_modal_submode` | mouse move updates the affine · release (drag-grab) / LMB / Enter accept · RMB/Esc revert to the pre-submode snapshot (`_snap`) |

`MIDDLEMOUSE` / wheel always `PASS_THROUGH` so pan/zoom stay alive.

**Photoshop / Toon Boom retargeting (2026-07-06):** in `FLOAT_IDLE` unhandled
events (and all hotkeys while the mouse is outside the invoking region) are
`PASS_THROUGH`, so the timeline, VSE, and layer panel stay usable while the
selection floats. `_sync_context()` watches for frame/layer changes:

- Dest is always **the active cel at the current frame** — `_bake_current`
  calls `cel_layer_ops.ensure_strip_for_slot()` which auto-creates the PNG +
  VSE strip when the target slot has none at the playhead (and saves the
  freshly created file right after the bake).
- `_source_mode` ∈ {`CUT`, `COPY`} with `_hole_live`: the CUT hole stays
  virtual (GPU-only, Esc restores) while `_src_is_intact()` — i.e. the source
  slot's datablock still shows the source strip file. Once the user scrubs
  away, `_commit_cut_to_file()` burns the hole into the source PNG and the
  float becomes a pure COPY. `Shift+D` bakes once then flips to `COPY` so
  repeated stamps don't re-cut.
- **Clipboard:** module-level `_CLIPBOARD` (patch/mask/points/affine) survives
  across runs. `Ctrl+C` snapshots the float; `Ctrl+V` in the Image Editor
  keymap invokes the operator with `paste=True`, starting directly in
  `FLOAT_IDLE` with the clipboard content (paste-in-place).

**Related, in `cel_layer_ops.py`:** `DOMEANIMATIC_OT_cel_duplicate_up` /
`_next` — Toon Boom-style drawing duplication (buttons in the Painting Cel
panel). Both save a **new** PNG from the active slot's datablock so the copy
never shares pixels with the original strip: *Up* inserts it on the layer
above (same range), *Next* inserts it right after the current strip on the
same channel and jumps the playhead there.

---

## 4. Commit paths (the only `image.pixels` writes)

All three funnel through `read_pixels` / `write_pixels` / `composite_float`:

- `_delete_selection` (X) — `read → _apply_hole → write`, finish.
- `_bake_current` — shared by Enter and Shift+D. Reads active (and dest, if
  UPPER), punches the hole when `CUT`, composites the float into dest, writes
  back only the buffers that changed.
- `_confirm` (Enter) — `_bake_current` then cleanup + report.

`_apply_hole` zeroes alpha inside the mask on the *original* (untransformed)
footprint — that's why the hole always matches where the selection came from,
independent of where you dragged it.

---

## 5. Common maintenance tasks — where to look

| I want to… | File · symbol |
|---|---|
| Change a hotkey or the close/double-click thresholds | `lasso_transform_ops.py` · `register()`, `CLOSE_THRESHOLD_PX`, `DBL_CLICK_DIST_PX` |
| Add/adjust an interaction key | `_modal_idle` (floating) or `_modal_draw` (drawing) |
| Change how the preview looks (colors, banner, outline) | `lasso_draw.py` · `_draw_outline` / `_draw_status` / `_STATUS_TEXT` |
| Fix compositing / edge quality of the bake | `lasso_raster.py` · `composite_float` |
| Change selection rasterization (e.g. antialiasing) | `lasso_raster.py` · `rasterize_polygon` (+ mask consumers) |
| Add a new floating operation (e.g. flip) | new `_enter_submode` branch + `_modal_submode` case; affine only, no new pixel code |
| Change layer retargeting / auto strip creation | `_dup_to_upper`, `_bake_current`, `cel_layer_ops.ensure_strip_for_slot` |
| Change cut-commit rules on scrub-away | `_sync_context`, `_src_is_intact`, `_commit_cut_to_file` |
| Change clipboard behavior | `_CLIPBOARD`, `_copy_to_clipboard`, `_adopt_clipboard`, `paste` property + Ctrl+V keymap |

---

## 6. Invariants & gotchas

- **One instance at a time.** `invoke` refuses to start if
  `lasso_draw.get_active_op()` is not `None`. The handler and the active-op
  reference are always cleared together in `_cleanup` / `unregister`.
- **RGBA only.** `invoke` rejects non-4-channel images — cut needs a real alpha.
- **Region math uses the WINDOW region**, captured at invoke, because the
  operator can be launched from the sidebar; `event.mouse_region_*` would be
  relative to the panel. See `_mouse_px` / `_px_to_region`.
- **Adding a new module-level file here?** Add it to
  `modules/painting_cel/__init__.py`'s import line so Blender's in-place reload
  (`del sys.modules[...]`) purges it. `lasso_raster` / `lasso_draw` have no
  `register()`; only `lasso_transform_ops.register()` is called.
- **`composite_float` mutates `dest_buf` in place** and returns `None` — callers
  pass a buffer they already own from `read_pixels`.

---

*Last updated: 2026-07-06 (float retargeting + clipboard + duplicate ops).*
