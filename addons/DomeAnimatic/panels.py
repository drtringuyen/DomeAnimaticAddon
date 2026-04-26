import bpy
import datetime
from . import (
    prepare_live_dome_texture,
    synch_VSE_to_LiveDomePreview,
    capture_current_frame,
    collage_texture,
    prepare_collage_scene,
    color_palette,
    transparent_cel_managment,
    fade_in_fade_out,
)

# Stamped at import time — updates on every addon reload
ADDON_BUILD_TIME = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

VIEW_INFO_EDITORS = [
    ("DOMEANIMATIC_PT_view_info_VIEW3D",  "VIEW_3D"),
    ("DOMEANIMATIC_PT_view_info_VSE",     "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_view_info_IMAGE",   "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_view_info_NODE",    "NODE_EDITOR"),
]

DOME_EDITORS = [
    ("DOMEANIMATIC_PT_main_VIEW3D", "VIEW_3D"),
    ("DOMEANIMATIC_PT_main_VSE",    "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_main_IMAGE",  "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_main_NODE",   "NODE_EDITOR"),
]

SNAPSHOT_EDITORS = [
    ("DOMEANIMATIC_PT_snapshot_VIEW3D", "VIEW_3D"),
    ("DOMEANIMATIC_PT_snapshot_VSE",    "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_snapshot_IMAGE",  "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_snapshot_NODE",   "NODE_EDITOR"),
]

FADE_EDITORS = [
    ("DOMEANIMATIC_PT_fade_VIEW3D", "VIEW_3D"),
    ("DOMEANIMATIC_PT_fade_VSE",    "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_fade_IMAGE",  "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_fade_NODE",   "NODE_EDITOR"),
]

COLLAGE_EDITORS = [
    ("DOMEANIMATIC_PT_collage_VIEW3D", "VIEW_3D"),
    ("DOMEANIMATIC_PT_collage_VSE",    "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_collage_IMAGE",  "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_collage_NODE",   "NODE_EDITOR"),
]


# ── Decorative build-time stamp operator (no-op) ──────────────────────────────

class DOMEANIMATIC_OT_build_stamp(bpy.types.Operator):
    """Shows when the addon was last loaded — click does nothing."""
    bl_idname = "domeanimatic.build_stamp"
    bl_label  = "Build Stamp"

    def execute(self, context):
        return {'FINISHED'}


# ── Panel 1: View Info ────────────────────────────────────────────────────────

def draw_view_info_panel(self, context):
    box = self.layout.box()
    wm  = bpy.data.window_managers[0]

    # Row 1: build timestamp — greyed-out decorative box
    row_time = box.row(align=True)
    row_time.enabled = False
    row_time.operator(
        "domeanimatic.build_stamp",
        text=f"Built:  {ADDON_BUILD_TIME}",
        icon='TIME',
    )

    # Row 2: dev toggle + console + clear + debug — no separator
    row = box.row(align=True)
    row.prop(wm, "domeanimatic_show_labels",
             text="Show Development Infos", toggle=True)
    row.operator("wm.console_toggle",               text="", icon='CONSOLE')
    row.operator("domeanimatic.clear_console",      text="", icon='TRASH')
    row.operator("domeanimatic.debug_node_sockets", text="", icon='INFO')


panel_classes = []

for _idname, _space in VIEW_INFO_EDITORS:
    panel_classes.append(type(_idname, (bpy.types.Panel,), {
        "bl_label":       "View Info",
        "bl_idname":      _idname,
        "bl_space_type":  _space,
        "bl_region_type": "UI",
        "bl_category":    "DomeAnimatic",
        "draw":           draw_view_info_panel,
    }))


# ── Panel 2: Live Dome Texture ────────────────────────────────────────────────

def draw_main_panel(self, context):
    box = self.layout.box()
    prepare_live_dome_texture.draw_ui(box, context)
    synch_VSE_to_LiveDomePreview.draw_ui(box, context)

for _idname, _space in DOME_EDITORS:
    panel_classes.append(type(_idname, (bpy.types.Panel,), {
        "bl_label":       "Live Dome Texture",
        "bl_idname":      _idname,
        "bl_space_type":  _space,
        "bl_region_type": "UI",
        "bl_category":    "DomeAnimatic",
        "draw":           draw_main_panel,
    }))


# ── Panel 3: Frame Snap Shot ──────────────────────────────────────────────────

def make_snapshot_draw(space_type):
    def draw_snapshot_panel(self, context):
        box = self.layout.box()
        capture_current_frame.draw_ui(box, context, space_type=space_type)
        if space_type == 'IMAGE_EDITOR':
            palette_box = self.layout.box()
            color_palette.draw_ui(palette_box, context)
    return draw_snapshot_panel

for _idname, _space in SNAPSHOT_EDITORS:
    panel_classes.append(type(_idname, (bpy.types.Panel,), {
        "bl_label":       "Frame Snap Shot",
        "bl_idname":      _idname,
        "bl_space_type":  _space,
        "bl_region_type": "UI",
        "bl_category":    "DomeAnimatic",
        "bl_options":     {'DEFAULT_CLOSED'},
        "draw":           make_snapshot_draw(_space),
    }))


# ── Panel 4: Transparent Cel (Image Editor only) ──────────────────────────────

def draw_transparent_cel_panel(self, context):
    box = self.layout.box()
    transparent_cel_managment.draw_ui(box, context)

panel_classes.append(type("DOMEANIMATIC_PT_transparent_cel_IMAGE", (bpy.types.Panel,), {
    "bl_label":       "Transparent Cel",
    "bl_idname":      "DOMEANIMATIC_PT_transparent_cel_IMAGE",
    "bl_space_type":  "IMAGE_EDITOR",
    "bl_region_type": "UI",
    "bl_category":    "DomeAnimatic",
    "bl_options":     {'DEFAULT_CLOSED'},
    "draw":           draw_transparent_cel_panel,
}))


# ── Panel 5: Fade In / Fade Out ───────────────────────────────────────────────

def draw_fade_panel(self, context):
    box = self.layout.box()
    fade_in_fade_out.draw_ui(box, context)

for _idname, _space in FADE_EDITORS:
    panel_classes.append(type(_idname, (bpy.types.Panel,), {
        "bl_label":       "Fade In / Fade Out",
        "bl_idname":      _idname,
        "bl_space_type":  _space,
        "bl_region_type": "UI",
        "bl_category":    "DomeAnimatic",
        "bl_options":     {'DEFAULT_CLOSED'},
        "draw":           draw_fade_panel,
    }))


# ── Panel 6: Collage ──────────────────────────────────────────────────────────

def draw_collage_panel(self, context):
    box = self.layout.box()
    collage_texture.draw_ui(box, context)
    box.separator(factor=0.3)
    prepare_collage_scene.draw_ui(box, context)

for _idname, _space in COLLAGE_EDITORS:
    panel_classes.append(type(_idname, (bpy.types.Panel,), {
        "bl_label":       "Collage",
        "bl_idname":      _idname,
        "bl_space_type":  _space,
        "bl_region_type": "UI",
        "bl_category":    "DomeAnimatic",
        "bl_options":     {'DEFAULT_CLOSED'},
        "draw":           draw_collage_panel,
    }))


# ── Register ──────────────────────────────────────────────────────────────────

def register():
    bpy.utils.register_class(DOMEANIMATIC_OT_build_stamp)
    for cls in panel_classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(panel_classes):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(DOMEANIMATIC_OT_build_stamp)
