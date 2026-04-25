# DomeAnimatic Blender Addon — Project Documentation
Version 1.4.0 — Blender 5.1

---

## 1. Dev Setup

- **Dev source:** `D:\BlenderAddonDevelopment\DomeAnimaticAddon\`
- **Installed:** `C:\Users\Reynard\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\DomeAnimatic\`

### Reload in Blender
```python
import sys
for key in [k for k in sys.modules if 'DomeAnimatic' in k]:
    del sys.modules[key]
import addon_utils
addon_utils.disable("DomeAnimatic", default_set=False)
addon_utils.enable("DomeAnimatic", default_set=False)
```

---

## 2. File Structure

```
DomeAnimatic/
├── __init__.py                     # Entry point v1.4.0
├── utils.py                        # All shared helpers (see §4)
├── properties.py                   # All bpy.props (see §5)
│
├── manage_live_dome_preview.py     # LiveDomePreview ↔ material relink, Reload op
├── prepare_live_dome_texture.py    # Texture size/scale, Prepare button
│                                   # Auto-links material + cel nodes on prepare
│
├── synch_VSE_to_LiveDomePreview.py # VSE sync — 3-way mode (BAKED/CEL_LAYERS/OFF)
│                                   # BAKED: ch1 → LiveDomePreview, mutes ch2/3/4
│                                   # CEL_LAYERS: ch2/3/4 → cel datablocks,
│                                   #             mutes ch1
│                                   # Menu Switch node: inputs[0].default_value
│                                   #   = 'Baked' or 'Cels'
│                                   # UI: centered "Synch VSE as:" label row +
│                                   #   Baked Frame | Unbaked Cels | ▶/⏹ | 🔄
│                                   # Collapsible material section (default closed)
│                                   # Ops: set_synch_mode, synch_vse,
│                                   #   stop_synch_vse, link_cel_nodes,
│                                   #   debug_node_sockets, clear_console
│
├── capture_current_frame.py        # Save Current Frame, Switch Dome/Collage,
│                                   # Capture from View
├── frame_snap_shot.py              # PURE UI: Frame Snap Shot panel layout
│
├── collage_texture.py              # Render to LiveDomePreview operator
├── prepare_collage_scene.py        # Create/Load/Switch collage scenes
│
├── collage_manipulation.py         # Face ops + layer_move_up/down
│
├── fade_in_fade_out.py             # Color A+B VSE strips → Mix node Factor
│
├── color_palette.py                # PURE UI: Color Palette (Image Editor only)
│                                   # (renamed from drawing_assistant.py)
│
├── transparent_cel.py              # THREE-SLOT CEL LAYER SYSTEM
│                                   #
│                                   # Slots: BG=ch2, CEL_A=ch3, CEL_B=ch4
│                                   # Datablocks: TransparentCel_BG/Cel_A/Cel_B
│                                   #   use_fake_user=True, zero-filled on create
│                                   #
│                                   # Stem: always from ch1 (Baked) strip,
│                                   #   strips _BG/_Cel_A/_Cel_B/_f_NNNNN suffixes
│                                   # Naming: <stem>_<BG|Cel_A|Cel_B>_f_<05d>.png
│                                   #
│                                   # GPU overlay: POST_PIXEL BG→A→B stack
│                                   # Invisible warning: depsgraph_update_post
│                                   #   → invoke_props_dialog (Option B)
│                                   #
│                                   # Insert FULL (all slots):
│                                   #   invoke: popup if strip exists at playhead
│                                   #   BG: copy track-1 pixels, track-1 range
│                                   #   Cel_A/B: blank PNG, cel channel's own
│                                   #     strip range (fallback: track-1 range)
│                                   #   Removes existing strip before inserting
│                                   #   Only new strip selected after insert
│                                   #
│                                   # Insert CUT (Cel_A/B only, BG greyed out):
│                                   #   invoke: popup if strip exists at playhead
│                                   #   finds strip LEFT of current on cel channel
│                                   #   copies its image (or blank if none)
│                                   #   cuts current strip at playhead
│                                   #   Only right-half strip selected after cut
│                                   #
│                                   # Delete: invoke popup → remove only the strip
│                                   #   at playhead on cel's channel
│                                   #
│                                   # Clear: invoke popup → zero pixels of active
│                                   #   cel datablock, strip at playhead selected
│                                   #
│                                   # All action ops (Full/Cut/Clear/Delete/Save):
│                                   #   set that row as active cel after execution
│                                   #   Visibility toggle does NOT set active
│                                   #
│                                   # _activate_slot() helper: sets WM active_cel
│                                   #   and switches Image Editor to that datablock
│                                   #
│                                   # draw_row(): eye | label:nearest-file |
│                                   #   opacity | InsertFull(RENDER_RESULT for BG,
│                                   #   TRACKING_FORWARDS_SINGLE for Cel_A/B) |
│                                   #   InsertCut(disabled for BG) |
│                                   #   Clear | Delete | Save(blue when dirty)
│                                   # Active row highlighted as box
│
├── transparent_cel_managment.py    # CEL PANEL UI
│                                   # Folder row: label + status icon + field +
│                                   #   refresh button (no resolved path label)
│                                   # No unsaved warning banner
│                                   # 3 rows: CEL_B(top), CEL_A, BG(bottom)
│
└── panels.py                       # Pure panel wiring
│                                   # View Info: Dev toggle + Console Toggle
│                                   #   + Clear Console + Debug Node Info
```

### Files to DELETE from disk
`handlers.py`, `operators.py`, `layer_management.py`,
`transparent_cel_fixes.py`, `drawing_assistant.py`

### Panel order (sidebar)
1. View Info
2. Live Dome Texture
3. Frame Snap Shot
4. Transparent Cel (Image Editor only)
5. Fade In / Fade Out
6. Collage

---

## 3. Architecture Rules

- `panels.py` only wires panels — zero operators
- `frame_snap_shot.py` owns Frame Snap Shot UI layout
- Operators in source files, UI references by `bl_idname`
- `WindowManager` props survive scene switches; `Scene` props are per-scene
- VSE sync: track 1 in BAKED (mutes ch2/3/4); tracks 2/3/4 in CEL_LAYERS (mutes ch1)
- Cel datablocks permanent, `use_fake_user=True`, zero-filled on creation
- `_handler_blocked` wraps all renders and scene creation
- VSE strip helpers in `utils.py`
- Debug buttons go in View Info panel row
- All cel action operators call `_activate_slot()` — visibility toggle does not

---

## 4. utils.py Public API

### Image
- `get_live_image()`, `get_or_create_live_image(w, h)`

### VSE — general
- `get_active_strip_at_frame(scene, frame)` — highest channel
- `resolve_strip_image_path(strip, frame)`
- `get_dome_animatic_frame_info()` → (stem, filepath, strip, el)
- `get_current_scene_frame_info(scene)`

### VSE — cel operations
- `vse_get_strip_on_channel(scene, channel, frame, include_muted=False)`
- `vse_get_strip_left_of(scene, channel, strip)` → strip immediately left
- `vse_get_channel_end_frame(scene, channel)`
- `vse_get_channel_start_frame(scene, channel)`
- `vse_insert_image_strip(scene, channel, abs_filepath, frame_start, frame_end)`
  → deselects all, inserts, selects only new strip, sets active_strip
- `vse_cut_strip_at_frame(scene, channel, frame, new_abs_filepath)`
  → trims left half, calls vse_insert_image_strip for right half

### Viewport / Image Editor
- `set_image_editor_image(context, image)`
- `tag_all_image_editors_redraw()`
- `save_dome_view_state(context)` / `restore_dome_view_state(context)`
- `switch_all_view3d_to_camera(context)`
- `restore_image_editor_to_live(context)`

---

## 5. Properties Reference

### WindowManager (global, survives scene switch)
| Property | Default | Purpose |
|---|---|---|
| `domeanimatic_show_labels` | False | Dev info toggle |
| `domeanimatic_target_material` | — | Dome Animatic material |
| `domeanimatic_synch_mode` | 'OFF' | BAKED / CEL_LAYERS / OFF |
| `domeanimatic_mat_nodes_expanded` | False | Material section collapsed |
| `domeanimatic_cel_folder` | `"//transparent-cels-paintings"` | Cel PNG folder |
| `domeanimatic_active_cel` | 'CEL_A' | BG / CEL_A / CEL_B |
| `domeanimatic_last_camera_zoom` | 3.055 | Camera zoom across scenes |
| `domeanimatic_{bg\|cel_a\|cel_b}_visible` | True | Layer eye |
| `domeanimatic_{bg\|cel_a\|cel_b}_opacity` | 1.0 | Layer opacity |
| `domeanimatic_{bg\|cel_a\|cel_b}_filepath` | "" | PNG path on disk |
| `domeanimatic_{bg\|cel_a\|cel_b}_mat_image` | — | Material tex node image |

### Scene (per-scene)
`domeanimatic_synch_active`, `domeanimatic_target_object/material/image`,
`domeanimatic_layer_spacing`, `domeanimatic_delete_color`,
`domeanimatic_color_a/b_value/strip_name/color`,
`domeanimatic_collage/manual_scene_expanded/layer_expanded`

---

## 6. Cel System Reference

| Slot | VSE Channel | Datablock | File label |
|---|---|---|---|
| BG | 2 | `TransparentCel_BG` | `BG` |
| CEL_A | 3 | `TransparentCel_Cel_A` | `Cel_A` |
| CEL_B | 4 | `TransparentCel_Cel_B` | `Cel_B` |

**Naming:** `<stem>_<BG|Cel_A|Cel_B>_f_<frame:05d>.png`
Stem = ch1 strip filename, stripped of `_BG/_Cel_A/_Cel_B/_f_NNNNN` suffixes.

**Material node mapping (Dome_Animatic):**
- `Image Texture` → LiveDomePreview
- `Image Texture.001` → TransparentCel_BG
- `Image Texture.002` → TransparentCel_Cel_A
- `Image Texture.003` → TransparentCel_Cel_B
- `Menu Switch` → `inputs[0].default_value` = `'Baked'` or `'Cels'`

**Auto-link:** Hitting "Prepare Live Dome Texture" auto-finds the material
and links all four Image Texture nodes + sets WM pointers.

---

## 7. Session Starter Prompt

> I'm continuing development of **DomeAnimatic**, a Blender 5.1 addon.
> Uploading all current `.py` files — please read them before answering.
>
> **Setup:** PyCharm at `D:\BlenderAddonDevelopment\DomeAnimaticAddon\`,
> deployed to `C:\Users\Reynard\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\DomeAnimatic\`.
>
> **Architecture rules:**
> - `panels.py` only wires panels — no operators
> - `frame_snap_shot.py` owns Frame Snap Shot UI layout
> - Operators in source files, UI by `bl_idname`
> - `WindowManager` props survive scene switches; `Scene` props are per-scene
> - VSE sync: ch1 in BAKED (mutes ch2/3/4); ch2/3/4 in CEL_LAYERS (mutes ch1)
> - Cel datablocks permanent, `use_fake_user=True`, zero-filled on creation
> - Cel stem always from ch1, never from cel channel filenames
> - All cel action ops call `_activate_slot()` after execution
> - `vse_insert_image_strip` deselects all then selects only the new strip
> - `_handler_blocked` wraps all renders and scene creation
> - VSE helpers in `utils.py`; debug buttons in View Info panel
> - Delete from disk: `handlers.py`, `operators.py`, `layer_management.py`,
>   `transparent_cel_fixes.py`, `drawing_assistant.py`
