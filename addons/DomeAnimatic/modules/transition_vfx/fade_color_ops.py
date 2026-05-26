"""
fade_color_ops.py — Operators for transition_vfx module.

Keyframe insertion and manual color refresh for the two color VSE strips
(fade-to-black / fade-to-white).
"""

import bpy

from ...global_scene_shared_props import sp
from . import mix_node_sync


class DOMEANIMATIC_OT_keyframe_color_a(bpy.types.Operator):
    bl_idname      = "domeanimatic.keyframe_color_a"
    bl_label       = "Insert Color A Keyframe"
    bl_description = "Insert a keyframe on the color A strip's blend_alpha at current frame"

    @classmethod
    def poll(cls, context):
        return mix_node_sync.get_color_a_strip(context.scene) is not None

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        strip      = mix_node_sync.get_color_a_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, "Color A strip not found.")
            return {'CANCELLED'}
        frame = dome_scene.frame_current if dome_scene else context.scene.frame_current
        strip.blend_alpha = sp().color_a_value
        strip.keyframe_insert(data_path="blend_alpha", frame=frame)
        self.report({'INFO'}, f"Keyframe inserted at frame {frame}.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_keyframe_color_b(bpy.types.Operator):
    bl_idname      = "domeanimatic.keyframe_color_b"
    bl_label       = "Insert Color B Keyframe"
    bl_description = "Insert a keyframe on the color B strip's blend_alpha at current frame"

    @classmethod
    def poll(cls, context):
        return mix_node_sync.get_color_b_strip(context.scene) is not None

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        strip      = mix_node_sync.get_color_b_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, "Color B strip not found.")
            return {'CANCELLED'}
        frame = dome_scene.frame_current if dome_scene else context.scene.frame_current
        strip.blend_alpha = sp().color_b_value
        strip.keyframe_insert(data_path="blend_alpha", frame=frame)
        self.report({'INFO'}, f"Keyframe inserted at frame {frame}.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_refresh_color_a(bpy.types.Operator):
    bl_idname      = "domeanimatic.refresh_color_a"
    bl_label       = "Refresh Color A"
    bl_description = "Sync color A to VSE strip and Mix node B-socket"

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}
        strip = mix_node_sync.get_color_a_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, f"Strip '{sp().color_a_strip_name}' not found.")
            return {'CANCELLED'}
        color_a = sp().color_a_color[:3]
        if hasattr(strip, 'color'):
            strip.color = color_a
        if mix_node_sync.push_color_a_to_mix(dome_scene, sp().color_a_value, color_a):
            self.report({'INFO'}, f"Color A: '{strip.name}' + Mix node synced.")
        else:
            self.report({'WARNING'}, "Strip synced — Mix node not found.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_refresh_color_b(bpy.types.Operator):
    bl_idname      = "domeanimatic.refresh_color_b"
    bl_label       = "Refresh Color B"
    bl_description = "Sync color B to VSE strip and Mix node B-socket"

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}
        strip = mix_node_sync.get_color_b_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, f"Strip '{sp().color_b_strip_name}' not found.")
            return {'CANCELLED'}
        color_b = sp().color_b_color[:3]
        if hasattr(strip, 'color'):
            strip.color = color_b
        if mix_node_sync.push_color_b_to_mix(dome_scene, sp().color_b_value, color_b):
            self.report({'INFO'}, f"Color B: '{strip.name}' + Mix node synced.")
        else:
            self.report({'WARNING'}, "Strip synced — Mix node not found.")
        return {'FINISHED'}


CLASSES = [
    DOMEANIMATIC_OT_keyframe_color_a,
    DOMEANIMATIC_OT_keyframe_color_b,
    DOMEANIMATIC_OT_refresh_color_a,
    DOMEANIMATIC_OT_refresh_color_b,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
