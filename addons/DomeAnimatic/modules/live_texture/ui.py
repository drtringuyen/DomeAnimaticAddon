"""
ui.py — Live Texture sub-panel (child of the main DomeAnimatic panel).
"""

import bpy
from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp, sp
from . import live_texture_ops


# ── Helpers ───────────────────────────────────────────────────────────────────

def _draw_link_status(box):
    status = live_texture_ops.get_link_status()
    col    = box.column(align=True)
    col.enabled = False

    if status["live_exists"]:
        col.label(text=f"{status['live_name']}: exists", icon='CHECKMARK')
    else:
        col.label(text=f"{status['live_name']}: not found", icon='ERROR')

    if status["mat_exists"]:
        col.label(text=f"Material: {status['mat_name']}", icon='MATERIAL')
        if status["node_linked"]:
            col.label(text="Linked: OK", icon='CHECKMARK')
        else:
            extra = f" → {status['node_image_name']}" if status["node_image_name"] else ""
            col.label(text=f"Linked: NO{extra}", icon='ERROR')
    else:
        col.label(text="No material set — pick one in Material section", icon='ERROR')

    box.separator(factor=0.3)


# ── Shared draw function ──────────────────────────────────────────────────────

def _draw_live_texture(self, context):
    layout = self.layout
    g      = gp(context)
    verbose = g.show_labels

    # ── Prepare / Reload row ───────────────────────────────────────────────
    prepare_box = layout.box()
    if verbose:
        name = cel_store.BAKED_LAYER.datablock_name
        col  = prepare_box.column(align=True)
        col.enabled = False
        if name in bpy.data.images:
            img = bpy.data.images[name]
            col.label(text=f"{name} exists", icon='CHECKMARK')
            col.label(text=f"Size: {img.size[0]}x{img.size[1]}")
        else:
            col.label(text=f"{name} not found", icon='ERROR')
        prepare_box.separator(factor=0.3)

    row = prepare_box.row(align=True)
    row.prop(g, "tex_width")
    row.prop(g, "tex_height")
    prepare_box.prop(g, "tex_scale", slider=True)

    if verbose:
        import math
        final_w = max(1, int(g.tex_width  * g.tex_scale))
        final_h = max(1, int(g.tex_height * g.tex_scale))
        col = prepare_box.column()
        col.enabled = False
        col.label(text=f"Final: {final_w}x{final_h}", icon='FIXED_SIZE')

    prepare_box.separator(factor=0.3)

    btn_row = prepare_box.row(align=True)
    btn_row.scale_y = 1.5
    btn_row.operator("domeanimatic.live_texture_prepare",
                     text="Prepare Live Dome Texture", icon='IMAGE_DATA')
    btn_row.operator("domeanimatic.live_texture_reload",
                     text="", icon='FILE_REFRESH')

    if verbose:
        _draw_link_status(prepare_box)

    # ── Synch VSE row ──────────────────────────────────────────────────────
    synch_box = layout.box()
    is_active = sp().synch_active

    if verbose:
        col = synch_box.column(align=True)
        col.enabled = False
        col.label(
            text="Live sync active" if is_active else "Live sync inactive",
            icon='RADIOBUT_ON' if is_active else 'RADIOBUT_OFF',
        )
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene and dome_scene.sequence_editor:
            frame = dome_scene.frame_current
            for ch, label in ((1, "Baked"), (2, "BG"), (3, "Cel_A"), (4, "Cel_B")):
                s = vse_helpers.vse_get_strip_on_channel(dome_scene, ch, frame)
                col.label(
                    text=f"Ch{ch} ({label}): {s.name}" if s else f"Ch{ch} ({label}): empty",
                    icon='STRIP_COLOR_01' if s else 'INFO',
                )
        synch_box.separator(factor=0.3)

    label_row = synch_box.row()
    label_row.alignment = 'CENTER'
    label_row.label(text="Synch VSE as:", icon='SEQ_SPLITVIEW')

    cur_mode = g.synch_mode
    mode_row = synch_box.row(align=True)
    mode_row.scale_y = 1.4

    op = mode_row.operator("domeanimatic.set_synch_mode",
                           text="Baked Frame", icon='OUTLINER_OB_IMAGE',
                           depress=(cur_mode == 'BAKED'))
    op.mode = 'BAKED'

    op = mode_row.operator("domeanimatic.set_synch_mode",
                           text="Unbaked Cels", icon='RENDERLAYERS',
                           depress=(cur_mode == 'CEL_LAYERS'))
    op.mode = 'CEL_LAYERS'

    if not is_active:
        mode_row.operator("domeanimatic.live_texture_start_synch",
                          text="", icon='PLAY')
    else:
        mode_row.operator("domeanimatic.live_texture_stop_synch",
                          text="", icon='SNAP_FACE')

    mode_row.operator("domeanimatic.live_texture_start_synch",
                      text="", icon='FILE_REFRESH')

    # ── Material nodes — collapsible ───────────────────────────────────────
    mat_box    = layout.box()
    mat_header = mat_box.row()
    mat_header.prop(
        g, "mat_nodes_expanded",
        icon='TRIA_DOWN' if g.mat_nodes_expanded else 'TRIA_RIGHT',
        icon_only=True, emboss=False,
    )
    mat_header.label(text="Dome Animatic Material", icon='MATERIAL')

    if g.mat_nodes_expanded:
        col = mat_box.column(align=True)
        col.prop(g, "target_material", text="")
        col.separator(factor=0.3)
        col.label(text="Material Tex Node Images:", icon='NODE_TEXTURE')
        for slot, label in (("bg", "BG  "), ("cel_a", "Cel A"), ("cel_b", "Cel B")):
            row = col.row(align=True)
            row.label(text=label)
            row.prop(g, f"{slot}_mat_image", text="")
        col.separator(factor=0.3)
        col.operator("domeanimatic.link_cel_nodes",
                     text="Link Cel Nodes to Material", icon='LINKED')

        if verbose:
            mat_box.operator("domeanimatic.debug_node_sockets",
                             text="Debug Node Sockets", icon='CONSOLE')


# ── Panel classes ─────────────────────────────────────────────────────────────

class DOMEANIMATIC_PT_live_texture(bpy.types.Panel):
    bl_label       = "Live Texture"
    bl_idname      = "DOMEANIMATIC_PT_live_texture"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main"
    bl_order       = 0
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_live_texture


class DOMEANIMATIC_PT_live_texture_ie(bpy.types.Panel):
    bl_label       = "Live Texture"
    bl_idname      = "DOMEANIMATIC_PT_live_texture_ie"
    bl_space_type  = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main_ie"
    bl_order       = 0
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_live_texture


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [DOMEANIMATIC_PT_live_texture, DOMEANIMATIC_PT_live_texture_ie]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
