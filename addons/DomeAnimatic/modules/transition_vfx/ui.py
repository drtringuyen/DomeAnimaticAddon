"""
ui.py — Transition VFX sub-panel (child of the main DomeAnimatic panel).
"""

import bpy

from ...global_scene_shared_props import gp, sp
from . import mix_node_sync


class DOMEANIMATIC_PT_transition_vfx(bpy.types.Panel):
    bl_label       = "Transition VFX"
    bl_idname      = "DOMEANIMATIC_PT_transition_vfx"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main"
    bl_order       = 3
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s      = sp()
        g      = gp(context)
        verbose = g.show_labels

        col = layout.column(align=True)

        # ── Color A (1st Mix Node) ─────────────────────────────────────────────
        col.label(text="Fade to Black (1st Mix Node)", icon='TRIA_RIGHT')
        strip_a = mix_node_sync.get_color_a_strip(context.scene)

        if strip_a is None:
            row = col.row()
            row.enabled = False
            row.label(text="Strip not found", icon='ERROR')
        else:
            row = col.row(align=True)
            row.operator("domeanimatic.refresh_color_a", text="", icon='FILE_REFRESH')
            split = row.split(factor=0.08, align=True)
            split.prop(s, "color_a_color", text="")
            split2 = split.split(factor=0.13, align=True)
            split2.prop(s, "color_a_strip_name", text="")
            split3 = split2.split(factor=0.91, align=True)
            split3.prop(s, "color_a_value", text="", slider=True)
            split3.operator("domeanimatic.keyframe_color_a", text="", icon='KEY_HLT')

            if verbose:
                info = col.row(align=True)
                info.enabled = False
                info.label(text=strip_a.name, icon='SEQUENCE')
                info.label(text=f"a:{strip_a.blend_alpha:.3f}", icon='IMAGE_ALPHA')

        col.separator(factor=0.5)

        # ── Color B (2nd Mix Node) ─────────────────────────────────────────────
        col.label(text="Fade to White (2nd Mix Node)", icon='TRIA_RIGHT')
        strip_b = mix_node_sync.get_color_b_strip(context.scene)

        if strip_b is None:
            row = col.row()
            row.enabled = False
            row.label(text="Strip not found", icon='ERROR')
        else:
            row = col.row(align=True)
            row.operator("domeanimatic.refresh_color_b", text="", icon='FILE_REFRESH')
            split = row.split(factor=0.08, align=True)
            split.prop(s, "color_b_color", text="")
            split2 = split.split(factor=0.13, align=True)
            split2.prop(s, "color_b_strip_name", text="")
            split3 = split2.split(factor=0.91, align=True)
            split3.prop(s, "color_b_value", text="", slider=True)
            split3.operator("domeanimatic.keyframe_color_b", text="", icon='KEY_HLT')

            if verbose:
                info = col.row(align=True)
                info.enabled = False
                info.label(text=strip_b.name, icon='SEQUENCE')
                info.label(text=f"a:{strip_b.blend_alpha:.3f}", icon='IMAGE_ALPHA')


CLASSES = [DOMEANIMATIC_PT_transition_vfx]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
