import bpy
from . import (
    prepare_live_dome_texture,
    synch_VSE_to_LiveDomePreview,
    capture_current_frame,
    collage_texture,
    prepare_collage_scene,
    drawing_assistant,
    layer_management,
    fade_in_fade_out,
)

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

LAYER_EDITORS = [
    ("DOMEANIMATIC_PT_layer_VIEW3D", "VIEW_3D"),
    ("DOMEANIMATIC_PT_layer_VSE",    "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_layer_IMAGE",  "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_layer_NODE",   "NODE_EDITOR"),
]

COLLAGE_EDITORS = [
    ("DOMEANIMATIC_PT_collage_VIEW3D", "VIEW_3D"),
    ("DOMEANIMATIC_PT_collage_VSE",    "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_collage_IMAGE",  "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_collage_NODE",   "NODE_EDITOR"),
]


# ── Panel 1: View Info ────────────────────────────────────────────────────────

def draw_view_info_panel(self, context):
    box = self.layout.box()
    box.prop(
        bpy.data.window_managers[0],
        "domeanimatic_show_labels",
        text="Show Development Infos",
        toggle=True,
    )


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
            drawing_assistant.draw_ui(palette_box, context)
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


FADE_EDITORS = [
    ("DOMEANIMATIC_PT_fade_VIEW3D", "VIEW_3D"),
    ("DOMEANIMATIC_PT_fade_VSE",    "SEQUENCE_EDITOR"),
    ("DOMEANIMATIC_PT_fade_IMAGE",  "IMAGE_EDITOR"),
    ("DOMEANIMATIC_PT_fade_NODE",   "NODE_EDITOR"),
]


# ── Panel 4: Layer Management ─────────────────────────────────────────────────

def draw_layer_panel(self, context):
    box = self.layout.box()
    layer_management.draw_ui(box, context)


for _idname, _space in LAYER_EDITORS:
    panel_classes.append(type(_idname, (bpy.types.Panel,), {
        "bl_label":       "Layer Management",
        "bl_idname":      _idname,
        "bl_space_type":  _space,
        "bl_region_type": "UI",
        "bl_category":    "DomeAnimatic",
        "bl_options":     {'DEFAULT_CLOSED'},
        "draw":           draw_layer_panel,
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
    for cls in panel_classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(panel_classes):
        bpy.utils.unregister_class(cls)
