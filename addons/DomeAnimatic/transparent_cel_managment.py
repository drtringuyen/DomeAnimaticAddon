"""
transparent_cel_managment.py

Panel UI for the three-slot transparent cel system.
All slot data lives on WindowManager (survives scene switches).
Operators and GPU overlay live in transparent_cel.py.

Render stack (bottom → top):  BG (ch2) → CEL_A (ch3) → CEL_B (ch4)
UI order (top → bottom):      CEL_B → CEL_A → BG
"""

import bpy
import os
from . import transparent_cel
from . import utils


# ── Refresh cel folder operator ───────────────────────────────────────────────

class DOMEANIMATIC_OT_refresh_cel_folder(bpy.types.Operator):
    """Normalize the cel folder to a valid relative (or absolute) path and create it."""
    bl_idname = "domeanimatic.refresh_cel_folder"
    bl_label  = "Refresh Cel Folder Path"

    def execute(self, context):
        wm  = bpy.data.window_managers[0]
        raw = getattr(wm, "domeanimatic_cel_folder", "")
        try:
            abs_path = bpy.path.abspath(raw)
        except Exception:
            abs_path = raw
        os.makedirs(abs_path, exist_ok=True)
        if bpy.data.filepath:
            try:
                rel = bpy.path.relpath(abs_path)
                wm.domeanimatic_cel_folder = rel
                self.report({'INFO'}, f"Folder: {rel}")
                return {'FINISHED'}
            except ValueError:
                pass
        wm.domeanimatic_cel_folder = abs_path
        self.report({'INFO'}, f"Folder: {abs_path}")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    wm = bpy.data.window_managers[0]

    # ── Cel folder + status icon + refresh ───────────────────────────────────
    row = box.row(align=True)
    row.label(text="Cel Folder:", icon='FILE_FOLDER')

    # Status icon — checkmark if folder exists, error if not
    try:
        abs_folder = bpy.path.abspath(getattr(wm, "domeanimatic_cel_folder", ""))
        exists = os.path.isdir(abs_folder)
    except Exception:
        exists = False
    row.label(text="", icon='CHECKMARK' if exists else 'ERROR')

    folder_row = box.row(align=True)
    folder_row.prop(wm, "domeanimatic_cel_folder", text="")
    folder_row.operator("domeanimatic.refresh_cel_folder", text="", icon='FILE_REFRESH')

    box.separator(factor=0.4)

    # ── Three rows: top=CEL_B, middle=CEL_A, bottom=BG ───────────────────────
    col = box.column(align=False)
    for slot_id in reversed(transparent_cel.SLOT_ORDER):
        transparent_cel.draw_row(col, wm, slot_id)
        col.separator(factor=0.2)


# ── Register / Unregister ─────────────────────────────────────────────────────

classes = [DOMEANIMATIC_OT_refresh_cel_folder]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    transparent_cel.register()


def unregister():
    transparent_cel.unregister()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
