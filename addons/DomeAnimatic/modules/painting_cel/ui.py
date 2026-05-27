"""
ui.py — Painting Cel sub-panel (child of the main DomeAnimatic panel).
"""

import bpy
import os

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp
from . import image_io


def _count_unused_cel_files() -> int:
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    folder     = image_io.cel_folder_abs()
    if not os.path.isdir(folder):
        return 0
    referenced = set()
    if dome_scene and dome_scene.sequence_editor:
        for strip in dome_scene.sequence_editor.strips_all:
            if strip.type == 'IMAGE' and strip.channel in cel_store.CEL_CHANNELS:
                for frame in range(int(strip.frame_final_start),
                                   int(strip.frame_final_end)):
                    p = vse_helpers.resolve_strip_image_path(strip, frame)
                    if p:
                        referenced.add(os.path.normpath(p))
    count = 0
    for fname in os.listdir(folder):
        if not fname.lower().endswith('.png'):
            continue
        if ('_BG_f_' not in fname and '_Cel_A_f_' not in fname
                and '_Cel_B_f_' not in fname):
            continue
        if os.path.normpath(os.path.join(folder, fname)) not in referenced:
            count += 1
    return count


def draw_row(layout, g, slot_id: str) -> None:
    """
    One cel row.
    Layout: [👁] [label | filepath] [opacity] [Full] [Cut] [Clear] [Delete] [Save]
    """
    slot_key  = slot_id.lower()
    layer     = cel_store.BY_SLOT[slot_id]
    channel   = layer.vse_channel
    is_active = g.active_cel == slot_id
    visible   = getattr(g, f"{slot_key}_visible", True)

    dome_scene = bpy.data.scenes.get("Dome Animatic")
    frame      = image_io.dome_frame()
    has_strip  = (dome_scene is not None and
                  vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame) is not None)

    if has_strip:
        filepath = getattr(g, f"{slot_key}_filepath", "")
        found_path, _ = image_io.find_closest_cel_file(slot_id)
        display = (os.path.splitext(os.path.basename(filepath))[0] if filepath else
                   (os.path.splitext(os.path.basename(found_path))[0] if found_path else "empty"))
    else:
        display = "empty"

    img_name  = layer.datablock_name
    is_dirty  = has_strip and getattr(bpy.data.images.get(img_name), 'is_dirty', False)

    container = layout.box() if is_active else layout
    if is_dirty:
        container.alert = True
    row = container.row(align=True)
    row.scale_y = 1.3

    # Eye toggle
    eye_op = row.operator("domeanimatic.cel_toggle_visible", text="",
                           icon='HIDE_OFF' if visible else 'HIDE_ON', depress=visible)
    eye_op.slot = slot_id

    # Label / select
    sel_op = row.operator("domeanimatic.cel_set_active",
                           text=f"{layer.filename_label}: {display}", depress=is_active)
    sel_op.slot = slot_id

    # Opacity slider
    row.prop(g, f"{slot_key}_opacity", text="", slider=True)

    # Insert Full
    full_icon = 'RENDER_RESULT' if slot_id == 'BG' else 'CENTER_ONLY'
    op = row.operator("domeanimatic.cel_insert_full", text="", icon=full_icon)
    op.slot = slot_id

    # Insert Cut (disabled for BG)
    cut_sub = row.row(align=True)
    cut_sub.enabled = (slot_id != 'BG')
    op = cut_sub.operator("domeanimatic.cel_insert_cut", text="",
                           icon='TRACKING_FORWARDS_SINGLE')
    op.slot = slot_id

    # Clear
    clear_sub = row.row(align=True)
    clear_sub.enabled = has_strip
    op = clear_sub.operator("domeanimatic.cel_clear", text="", icon='TEXTURE')
    op.slot = slot_id

    # Delete
    del_sub = row.row(align=True)
    del_sub.enabled = has_strip
    op = del_sub.operator("domeanimatic.cel_delete", text="", icon='TRASH')
    op.slot = slot_id

    # Save (blue when dirty)
    save_sub = row.row(align=True)
    save_sub.enabled = has_strip and is_dirty
    op = save_sub.operator("domeanimatic.cel_save", text="", icon='FILE_TICK',
                            depress=is_dirty)
    op.slot = slot_id


def _draw_painting_cel(self, context):
    layout = self.layout
    g      = gp(context)

    # ── Cel folder + dome object ────────────────────────────────────────────
    folder_box = layout.box()
    row = folder_box.row(align=True)
    row.label(text="Cel Folder:", icon='FILE_FOLDER')
    try:
        abs_folder = bpy.path.abspath(g.cel_folder)
        exists = os.path.isdir(abs_folder)
    except Exception:
        exists = False
    row.label(text="", icon='CHECKMARK' if exists else 'ERROR')

    folder_row = folder_box.row(align=True)
    folder_row.prop(g, "cel_folder", text="")
    folder_row.operator("domeanimatic.refresh_cel_folder", text="", icon='FILE_REFRESH')

    dome_row = folder_box.row(align=True)
    dome_row.label(text="Dome Object:")
    dome_row.prop(g, "dome_object", text="")

    layout.separator(factor=0.4)

    mode = g.synch_mode

    if mode == 'CEL_LAYERS':
        # ── Three cel rows: CEL_B (top) → CEL_A → BG (bottom) ───────────
        col = layout.column(align=False)
        for slot_id in reversed([layer.slot_id for layer in cel_store.DRAW_ORDER]):
            draw_row(col, g, slot_id)
            col.separator(factor=0.2)

        # ── Purge unused ─────────────────────────────────────────────────
        layout.separator(factor=0.3)
        unused_count = _count_unused_cel_files()
        purge_row    = layout.row()
        purge_row.enabled = unused_count > 0
        purge_row.operator(
            "domeanimatic.cel_purge_unused",
            text=f"Purge Unused ({unused_count})",
            icon='TRASH',
        )

    elif mode == 'BAKED':
        row = layout.row()
        row.scale_y = 1.3
        row.operator("domeanimatic.cel_show_baked",
                     text="Baked: LiveDomePreview", icon='IMAGE_DATA')

    else:  # 'OFF'
        layout.label(text="Enable sync to activate painting", icon='INFO')


class DOMEANIMATIC_PT_painting_cel(bpy.types.Panel):
    bl_label       = "Painting Cel"
    bl_idname      = "DOMEANIMATIC_PT_painting_cel"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main"
    bl_order       = 1
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_painting_cel


class DOMEANIMATIC_PT_painting_cel_ie(bpy.types.Panel):
    bl_label       = "Painting Cel"
    bl_idname      = "DOMEANIMATIC_PT_painting_cel_ie"
    bl_space_type  = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main_ie"
    bl_order       = 1
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_painting_cel


CLASSES = [DOMEANIMATIC_PT_painting_cel, DOMEANIMATIC_PT_painting_cel_ie]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
