# DomeAnimatic Blender Addon — Project Documentation

## 1. Project Overview

DomeAnimatic is a Blender 5.1 addon for managing a dome animatic workflow. It syncs a VSE timeline to a live dome preview texture, manages collage scenes, and provides tools for image painting and face manipulation.

---

## 2. PyCharm + Blender Development Setup

### File Locations
- **Dev source:** `D:\BlenderAddonDevelopment\DomeAnimaticAddon\`
- **Installed addon:** `C:\Users\Reynard\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\DomeAnimatic\`
- **Blender script dir:** Set `D:\BlenderAddonDevelopment\DomeAnimaticAddon` in Blender Preferences → File Paths → Script Directories

### Workflow
1. Edit files in PyCharm at the dev source path
2. Run `install.py` from PyCharm to copy files to the addon path
3. In Blender's Scripting editor, run:
```python
import importlib, sys
for key in [k for k in sys.modules if 'DomeAnimatic' in k]:
    del sys.modules[key]
import addon_utils
addon_utils.disable("DomeAnimatic", default_set=False)
addon_utils.enable("DomeAnimatic", default_set=False)
```
4. This reloads all modules without restarting Blender

---

## 3. File Structure & Responsibilities

```
DomeAnimatic/
├── __init__.py                     # Entry point — import order & register/unregister
├── utils.py                        # Shared helpers: VSE reading, image helpers,
│                                   # viewport utils, view state save/restore,
│                                   # material assignment, path helpers
├── properties.py                   # All bpy.props registrations on Scene/WindowManager
│
├── manage_live_dome_preview.py     # LiveDomePreview ↔ Dome_Animatic material relink
│                                   # Reload operator, status draw_status()
├── prepare_live_dome_texture.py    # Texture size/scale settings, Prepare button
│
├── synch_VSE_to_LiveDomePreview.py # VSE frame-change handler → LiveDomePreview reload
│                                   # Playhead sync across all scenes (depsgraph)
│                                   # block_handler()/unblock_handler() for render safety
│
├── capture_current_frame.py        # Save Current Frame operator (file dialog)
│                                   # Switch Dome/Collage operator
│                                   # Capture from View operator
│                                   # draw_ui() → delegates to frame_snap_shot.py
│
├── frame_snap_shot.py              # PURE UI: wires all Frame Snap Shot panel layout
│                                   # Save row + Handle Selected row
│                                   # No operators — only layout code
│
├── collage_texture.py              # Render to LiveDomePreview operator
│                                   # (renders scene silently, writes pixels)
│
├── prepare_collage_scene.py        # Create Collage Scene operator
│                                   # Load Closest / Load Dome Animatic operators
│                                   # Camera zoom sync, scene list UI
│
├── collage_manipulation.py         # Mesh face operators:
│                                   #   mark_face, duplicate_as_object,
│                                   #   content_aware_delete, content_aware_cut,
│                                   #   cut_fill_black (fill with DELETE material),
│                                   #   recover_face
│                                   # ensure_delete_material() helper
│                                   # draw_ui() for Layer Management panel
│
├── layer_management.py             # layer_duplicate, layer_cut (image paint layers)
│                                   # layer_move_up/down (Z-axis object movement)
│                                   # draw_ui() calls collage_manipulation.draw_ui()
│
├── fade_in_fade_out.py             # Reads blend_alpha from named VSE color strip
│                                   # Pushes value to Mix node Factor in target material
│                                   # set_fade_color, keyframe_fade operators
│
├── drawing_assistant.py            # PURE UI: Color Palette via template_palette
│                                   # Only shown in Image Editor
│
└── panels.py                       # Registers all Blender panels (pure wiring)
```

### Panel Order (Blender sidebar)
1. **View Info** — Show Development Infos toggle
2. **Live Dome Texture** — Prepare texture + Reload + Synch VSE
3. **Frame Snap Shot** — Save Current Frame + Handle Selected row + Color Palette (Image Editor only)
4. **Layer Management** — Layer Spacing + face manipulation operators
5. **Fade In / Fade Out** — Strip opacity reader → Mix node driver
6. **Collage** — Render to LiveDomePreview + collage scene management

---

## 4. Key Architecture Decisions

### Properties Location
- `WindowManager` — persists across scene switches: `show_labels`, `target_material` (for LiveDomePreview relink), `last_camera_zoom`
- `Scene` — per-scene: `synch_active`, `target_object`, `target_material` (collage), `target_image`, `layer_spacing`, `delete_color`, `fade_value`, `fade_strip_name`, `fade_color`

### Handler Architecture
- `frame_change_pre` → `dome_live_preview_handler` — reloads LiveDomePreview image from VSE
- `frame_change_post` → `dome_playhead_sync_handler` — syncs all scene playheads to Dome Animatic
- `depsgraph_update_post` → `dome_scene_change_handler` — auto pause/resume VSE sync on scene switch
- `depsgraph_update_post` → `fade_sync_handler` — reads blend_alpha, pushes to Mix node Factor
- `_handler_blocked` flag — prevents handlers firing during renders/scene creation

### UI Architecture
- `panels.py` only registers panels and calls `draw_ui()` from functional files
- `frame_snap_shot.py` is the single source of truth for Frame Snap Shot layout
- `collage_manipulation.py` owns all face operator UI
- Operators stay in their own files — UI files only reference `bl_idname` strings

### LiveDomePreview Image
- Always recreated with `bpy.data.images.new()` after collage renders (never `source='FILE'` after pixel write)
- `manage_live_dome_preview.py` relinking is manual-only (no auto-relink handler to avoid hijacking other materials)
- `show_labels` reads from `bpy.data.window_managers[0]` directly (not `context.window_manager`) for reliability across editors

### Blender 5.1 API Notes
- VSE strips: `sequence_editor.strips` (top level), `sequence_editor.strips_all` (all nested)
- No `unified_paint_settings` — use `brush.size` / `brush.strength` directly
- Operator properties cannot start with `_` (rename `_original_filepath` → `original_filepath`)
- `bpy.ops.mesh.merge_vertices` → use `bpy.ops.mesh.remove_doubles`
- Mix node inputs: use `.get('Factor')` or index 0, B color by name `'B'` or search by type

---

## 5. Starting a New Session with Existing Files

**Yes — if you upload all `.py` files to a new chat, Claude will recognize the full context.**

### Recommended prompt to start a new session:

---

> I'm continuing development of **DomeAnimatic**, a Blender 5.1 addon. I'm uploading all current `.py` files. Please read them all before answering.
>
> **Setup:** PyCharm at `D:\BlenderAddonDevelopment\DomeAnimaticAddon\`, deployed to `C:\Users\[user]\AppData\Roaming\Blender Foundation\Blender\5.1\scripts\addons\DomeAnimatic\`. Reload in Blender by clearing `sys.modules` and calling `addon_utils.disable/enable`.
>
> **Architecture rules to maintain:**
> - `panels.py` only wires panels — no operators
> - `frame_snap_shot.py` owns Frame Snap Shot UI layout
> - Operators stay in their source files, UI files reference them by `bl_idname`
> - All properties on `WindowManager` that must survive scene switches
> - `bpy.data.window_managers[0]` for `show_labels` (not `context.window_manager`)
> - VSE API: `sequence_editor.strips` / `strips_all`
> - No handler auto-relinking materials — manual only via Reload button
> - `_handler_blocked` flag wraps all renders and scene creation
>
> Please [describe your task here].

---

## 6. Quick Reference: Common Patterns

### Add a new operator
1. Create class in relevant `.py` file
2. Add to `classes = [...]` list in that file
3. Register in that file's `register()`
4. Add button in the relevant UI file (e.g. `frame_snap_shot.py`)

### Add a new property
1. Add to `properties.py` `register()` on `Scene` or `WindowManager`
2. Add `del` in `properties.py` `unregister()`
3. Reference as `context.scene.domeanimatic_xxx` or `bpy.data.window_managers[0].domeanimatic_xxx`

### Add a new panel
1. Add editor list to `panels.py`
2. Write `draw_xxx_panel` function
3. Loop to create panel classes with `type()`
4. Import the draw module at top of `panels.py`
