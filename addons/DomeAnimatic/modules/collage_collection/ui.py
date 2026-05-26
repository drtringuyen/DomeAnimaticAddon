"""
ui.py — Collage Collection sub-panel (child of the main DomeAnimatic panel).
"""

import bpy
import os

from ... import vse_helpers
from ...global_scene_shared_props import gp, sp


class DOMEANIMATIC_PT_collage_collection(bpy.types.Panel):
    bl_label       = "Collage Collection"
    bl_idname      = "DOMEANIMATIC_PT_collage_collection"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main"
    bl_order       = 2
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout  = self.layout
        s       = sp()
        g       = gp(context)
        verbose = g.show_labels
        is_dome = context.scene.name == "Dome Animatic"

        # ── Verbose info ───────────────────────────────────────────────────────
        if verbose:
            scene_name, filepath = vse_helpers.get_current_scene_frame_info(context.scene)
            closest, score = vse_helpers.find_closest_scene(scene_name) if scene_name else (None, 0)
            info_col = layout.column(align=True)
            info_col.enabled = False
            if closest:
                info_col.label(text=f"Closest: {closest}", icon='SCENE_DATA')
            else:
                info_col.label(text="No matching scene found", icon='INFO')
            if scene_name:
                if scene_name in bpy.data.scenes:
                    info_col.label(text=f"'{scene_name}' already exists", icon='INFO')
                else:
                    info_col.label(text=f"New scene: {scene_name}", icon='ADD')
            else:
                info_col.label(text="No image at current frame", icon='ERROR')
            layout.separator(factor=0.3)

        # ── Load buttons ───────────────────────────────────────────────────────
        only_dome = len(bpy.data.scenes) <= 1
        row = layout.row(align=True)
        load_row = row.row(align=True)
        load_row.enabled = not only_dome
        load_row.operator("domeanimatic.load_closest_scene",
                          text="Nearest Collage", icon='FILE_REFRESH')
        row.operator("domeanimatic.load_dome_animatic",
                     text="Load Dome Animatic", icon='SEQUENCE')

        # ── Camera zoom ────────────────────────────────────────────────────────
        row = layout.row(align=True)
        row.label(text="", icon='CAMERA_DATA')
        row.prop(s, "camera_zoom", text="Camera Zoom")

        # ── Object / Material / Image slots ────────────────────────────────────
        slots_row = layout.row(align=True)
        slots_row.enabled = not is_dome
        slots_row.prop(s, "target_object",   text="", icon='OBJECT_DATA')
        slots_row.prop(s, "target_material", text="", icon='MATERIAL')
        slots_row.prop(s, "target_image",    text="", icon='IMAGE_DATA')
        slots_row.operator("domeanimatic.assign_target_image", text="", icon='FILE_REFRESH')

        # ── Create Collage Scene ───────────────────────────────────────────────
        col = layout.column()
        col.scale_y = 1.5
        col.operator("domeanimatic.prepare_collage_scene",
                     text="Create Collage Scene", icon='SCULPTMODE_HLT')

        # ── Save / capture row ─────────────────────────────────────────────────
        layout.separator(factor=0.3)
        row = layout.row(align=True)
        row.scale_y = 2.0
        row.operator("domeanimatic.capture_current_frame",
                     text="Save Current Frame", icon='FILE_TICK')
        row.operator("domeanimatic.switch_dome_collage", text="", icon='ARROW_LEFTRIGHT')
        row.operator("domeanimatic.capture_from_view",   text="", icon='RESTRICT_RENDER_OFF')
        row.operator("domeanimatic.prepare_collage_scene", text="", icon='OUTLINER_DATA_GP_LAYER')

        # ── Handle Selected + layer move ───────────────────────────────────────
        row2 = layout.row(align=True)
        row2.scale_y = 1.5
        row2.enabled = not is_dome
        row2.operator("domeanimatic.recover_face",        text="", icon='RECOVER_LAST')
        row2.label(text="Handle Selected", icon='GREASEPENCIL_LAYER_GROUP')
        sub = row2.row(align=True)
        sub.scale_x = 0.4
        sub.prop(s, "delete_color", text="")
        row2.operator("domeanimatic.duplicate_as_object", text="", icon='SELECT_DIFFERENCE')
        row2.operator("domeanimatic.cut_fill_black",      text="", icon='SELECT_INTERSECT')
        col2 = row2.column(align=True)
        col2.scale_y = 0.5
        col2.operator("domeanimatic.layer_move_up",   text="", icon='TRIA_UP')
        col2.operator("domeanimatic.layer_move_down", text="", icon='TRIA_DOWN')

        # ── Layer settings ─────────────────────────────────────────────────────
        layout.separator(factor=0.3)
        lay_box    = layout.box()
        lay_header = lay_box.row()
        lay_header.prop(
            s, "layer_expanded",
            icon='TRIA_DOWN' if s.layer_expanded else 'TRIA_RIGHT',
            icon_only=True, emboss=False,
        )
        lay_header.label(text="Layer Settings", icon='RENDERLAYERS')
        if s.layer_expanded:
            lay_box.prop(s, "layer_spacing")
            lay_box.prop(s, "delete_color")

        # ── Scene list — collapsible ───────────────────────────────────────────
        sub_box = layout.box()
        sub_row = sub_box.row()
        sub_row.prop(
            s, "manual_scene_expanded",
            icon='TRIA_DOWN' if s.manual_scene_expanded else 'TRIA_RIGHT',
            icon_only=True, emboss=False,
        )
        sub_row.label(text="Scene List", icon='SCENE_DATA')
        if s.manual_scene_expanded:
            for scene in bpy.data.scenes:
                row = sub_box.row(align=True)
                if scene.name == context.scene.name:
                    row.enabled = False
                    row.label(text=scene.name, icon='SCENE_DATA')
                else:
                    op = sub_box.operator("domeanimatic.switch_scene",
                                          text=scene.name, icon='SCENE_DATA')
                    op.scene_name = scene.name


CLASSES = [DOMEANIMATIC_PT_collage_collection]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
