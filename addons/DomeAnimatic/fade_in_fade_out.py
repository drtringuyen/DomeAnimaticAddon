import bpy
from bpy.app.handlers import persistent
from . import utils


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_fade_strip(scene):
    """Find the named color strip in Dome Animatic's VSE."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return None
    strip_name = scene.domeanimatic_fade_strip_name
    se = dome_scene.sequence_editor
    # Blender 5.x: strips (current meta level) or strips_all (all nested)
    return se.strips_all.get(strip_name)


def read_fade_value(scene):
    """
    Read the current blend_alpha of the fade strip at the current frame.
    Returns 0.0 if the strip is not found.
    """
    strip = get_fade_strip(scene)
    if strip is None:
        return 0.0
    return getattr(strip, 'blend_alpha', 0.0)


def read_fade_color(scene):
    """Read the color of the fade strip (COLOR strip has a .color property)."""
    strip = get_fade_strip(scene)
    if strip is None:
        return (0.0, 0.0, 0.0)
    if hasattr(strip, 'color'):
        return tuple(strip.color)
    return (0.0, 0.0, 0.0)


def set_fade_strip_color(scene, color):
    """Set the fade strip color and update the scene property."""
    strip = get_fade_strip(scene)
    if strip is None:
        return False
    if hasattr(strip, 'color'):
        strip.color = color
        scene.domeanimatic_fade_color = color
        return True
    return False


# ── Persistent handler: read fade value every frame ──────────────────────────

@persistent
def fade_sync_handler(scene, depsgraph=None):
    """
    Read the fade strip's blend_alpha at the current Dome Animatic frame
    and store it in domeanimatic_fade_value on the Dome Animatic scene.
    """
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return

    strip = get_fade_strip(dome_scene)
    if strip is None:
        return

    # Read evaluated blend_alpha (respects F-Curve/NLA)
    fade_val = getattr(strip, 'blend_alpha', 0.0)
    if dome_scene.domeanimatic_fade_value != fade_val:
        dome_scene.domeanimatic_fade_value = fade_val

    # Also sync color
    if hasattr(strip, 'color'):
        dome_scene.domeanimatic_fade_color = strip.color


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_set_fade_color(bpy.types.Operator):
    bl_idname      = "domeanimatic.set_fade_color"
    bl_label       = "Apply Fade Color"
    bl_description = "Set the fade strip's color to the chosen fade color"

    @classmethod
    def poll(cls, context):
        return get_fade_strip(context.scene) is not None

    def execute(self, context):
        color = tuple(context.scene.domeanimatic_fade_color)
        if set_fade_strip_color(context.scene, color):
            self.report({'INFO'}, f"Fade strip color set to {color}.")
        else:
            self.report({'WARNING'}, "Could not set fade strip color.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_keyframe_fade(bpy.types.Operator):
    bl_idname      = "domeanimatic.keyframe_fade"
    bl_label       = "Insert Fade Keyframe"
    bl_description = "Insert a keyframe on the fade strip's blend_alpha at current frame"

    @classmethod
    def poll(cls, context):
        return get_fade_strip(context.scene) is not None

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        strip      = get_fade_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, "Fade strip not found.")
            return {'CANCELLED'}

        frame = dome_scene.frame_current if dome_scene else context.scene.frame_current
        strip.blend_alpha = context.scene.domeanimatic_fade_value
        strip.keyframe_insert(data_path="blend_alpha", frame=frame)
        self.report({'INFO'}, f"Keyframe inserted at frame {frame}.")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    scene      = context.scene

    col = box.column(align=True)

    # ── Strip name picker ─────────────────────────────────────────────────────
    row = col.row(align=True)
    row.prop(scene, "domeanimatic_fade_strip_name", text="Strip")

    strip = get_fade_strip(scene)

    if strip is None:
        row2 = col.row()
        row2.enabled = False
        row2.label(text="Strip not found in Dome Animatic VSE", icon='ERROR')
        return

    col.separator(factor=0.3)

    # ── Current fade value (live read) ────────────────────────────────────────
    row = col.row(align=True)
    row.prop(scene, "domeanimatic_fade_value", text="Opacity", slider=True)
    row.operator("domeanimatic.keyframe_fade", text="", icon='KEY_HLT')

    col.separator(factor=0.3)

    # ── Fade color picker + apply ─────────────────────────────────────────────
    row = col.row(align=True)
    row.prop(scene, "domeanimatic_fade_color", text="")
    row.operator("domeanimatic.set_fade_color", text="Apply Color", icon='CHECKMARK')

    # ── Live strip info ───────────────────────────────────────────────────────
    if bpy.data.window_managers[0].domeanimatic_show_labels:
        info = col.column(align=True)
        info.enabled = False
        info.label(text=f"Strip: {strip.name}  type: {strip.type}", icon='SEQUENCE')
        info.label(text=f"blend_alpha: {strip.blend_alpha:.3f}", icon='IMAGE_ALPHA')
        if hasattr(strip, 'color'):
            c = strip.color
            info.label(text=f"color: ({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f})")
        if dome_scene:
            info.label(text=f"Dome frame: {dome_scene.frame_current}", icon='TIME')


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_set_fade_color,
    DOMEANIMATIC_OT_keyframe_fade,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if fade_sync_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(fade_sync_handler)


def unregister():
    if fade_sync_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(fade_sync_handler)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
