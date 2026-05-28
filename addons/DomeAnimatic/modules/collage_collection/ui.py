"""
ui.py — Collage Collection sub-panel (child of the main DomeAnimatic panel).
"""

import bpy

from ... import vse_helpers
from ...global_scene_shared_props import gp, sp
from . import collection_ops


def _draw_collage_collection(self, context):
        layout      = self.layout
        s           = sp()
        g           = gp(context)
        verbose     = g.show_labels
        is_overview = g.active_collage == ""

        # Collect all tagged collage collections once — used in multiple places
        collage_colls = collection_ops.get_collage_collections()
        no_collages   = len(collage_colls) == 0

        # ── Verbose info ───────────────────────────────────────────────────────
        if verbose:
            scene_name, filepath = vse_helpers.get_current_scene_frame_info(context.scene)
            closest, score = vse_helpers.find_closest_collage(scene_name) if scene_name else (None, 0)
            info_col = layout.column(align=True)
            info_col.enabled = False
            if closest:
                info_col.label(text=f"Closest: {closest}", icon='OUTLINER_COLLECTION')
            else:
                info_col.label(text="No matching collage found", icon='INFO')
            if scene_name:
                coll = bpy.data.collections.get(scene_name)
                if coll and coll.domeanimatic.is_collage:
                    info_col.label(text=f"'{scene_name}' already exists", icon='INFO')
                else:
                    info_col.label(text=f"New collage: {scene_name}", icon='ADD')
            else:
                info_col.label(text="No image at current frame", icon='ERROR')
            layout.separator(factor=0.3)

        # ── Load buttons ───────────────────────────────────────────────────────
        row      = layout.row(align=True)
        load_row = row.row(align=True)
        load_row.enabled = not no_collages
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
        active_coll = bpy.data.collections.get(g.active_collage)
        if active_coll:
            cd = active_coll.domeanimatic
            slots_row.prop(cd, "target_object",   text="", icon='OBJECT_DATA')
            slots_row.prop(cd, "target_material", text="", icon='MATERIAL')
            slots_row.prop(cd, "target_image",    text="", icon='IMAGE_DATA')
            slots_row.operator("domeanimatic.assign_target_image", text="", icon='FILE_REFRESH')
        else:
            slots_row.enabled = False
            slots_row.label(text="No active collage", icon='INFO')

        # ── Create Collage ─────────────────────────────────────────────────────
        col = layout.column()
        col.scale_y = 1.5
        col.operator("domeanimatic.prepare_collage_scene",
                     text="Create Collage", icon='SCULPTMODE_HLT')

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
        row2.enabled = not is_overview
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

        # ── Collage list — collapsible ─────────────────────────────────────────
        sub_box = layout.box()
        sub_row = sub_box.row()
        sub_row.prop(
            s, "manual_scene_expanded",
            icon='TRIA_DOWN' if s.manual_scene_expanded else 'TRIA_RIGHT',
            icon_only=True, emboss=False,
        )
        sub_row.label(text="Collage List", icon='OUTLINER_COLLECTION')
        if s.manual_scene_expanded:
            for coll in collage_colls:
                row = sub_box.row(align=True)
                if coll.name == g.active_collage:
                    row.enabled = False
                    row.label(text=coll.name, icon='OUTLINER_COLLECTION')
                else:
                    op = sub_box.operator("domeanimatic.switch_scene",
                                          text=coll.name, icon='OUTLINER_COLLECTION')
                    op.scene_name = coll.name


class DOMEANIMATIC_PT_collage_collection(bpy.types.Panel):
    bl_label       = "Collage Collection"
    bl_idname      = "DOMEANIMATIC_PT_collage_collection"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main"
    bl_order       = 2
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_collage_collection


class DOMEANIMATIC_PT_collage_collection_ie(bpy.types.Panel):
    bl_label       = "Collage Collection"
    bl_idname      = "DOMEANIMATIC_PT_collage_collection_ie"
    bl_space_type  = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main_ie"
    bl_order       = 2
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_collage_collection


CLASSES = [DOMEANIMATIC_PT_collage_collection, DOMEANIMATIC_PT_collage_collection_ie]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
