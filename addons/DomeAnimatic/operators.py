import bpy
from . import utils


class DOME_OT_build(bpy.types.Operator):
    bl_idname = "dome.build"
    bl_label = "Build Animatic"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        utils.do_something()
        return {'FINISHED'}


class DOME_OT_silent_render(bpy.types.Operator):
    bl_idname = "dome.silent_render"
    bl_label = "Capture Render to Preview"
    bl_description = "Silently renders current frame into DomeLivePreview"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        original_display = scene.render.display_mode
        scene.render.display_mode = 'NONE'
        bpy.ops.render.render(write_still=False)
        scene.render.display_mode = original_display
        from . import handlers
        handlers.capture_from_render(scene)
        self.report({'INFO'}, "DomeLivePreview: render captured")
        return {'FINISHED'}


classes = (DOME_OT_build, DOME_OT_silent_render)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)