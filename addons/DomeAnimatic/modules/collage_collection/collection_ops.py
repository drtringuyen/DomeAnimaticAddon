"""
collection_ops.py — Scene creation and switching for collage_collection module.

Ported from prepare_collage_scene.py. Note: this module still uses Blender Scenes
as its collage unit. A future rework will migrate to Blender Collections.

Sync handler: sync_zoom_on_scene_change — carries camera_zoom across scene switches.
"""

import bpy
import os
from bpy.app.handlers import persistent

from ... import vse_helpers
from ...global_scene_shared_props import gp, sp


# ── Zoom sync handler ─────────────────────────────────────────────────────────

@persistent
def sync_zoom_on_scene_change(scene):
    try:
        g = gp()
        s = sp(scene)
        cam = scene.camera
        if cam and cam.data and cam.data.type == 'ORTHO':
            if s.camera_zoom != cam.data.ortho_scale:
                s['camera_zoom'] = cam.data.ortho_scale
            g.last_camera_zoom = cam.data.ortho_scale
        else:
            if s.camera_zoom != g.last_camera_zoom:
                s['camera_zoom'] = g.last_camera_zoom
    except Exception:
        pass


# ── Scene operators ───────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_prepare_collage_scene(bpy.types.Operator):
    bl_idname      = "domeanimatic.prepare_collage_scene"
    bl_label       = "Create Collage Scene"
    bl_description = "Create a new scene with image plane and orthographic camera from current VSE frame"

    @classmethod
    def description(cls, context, properties):
        name, filepath, strip, el = vse_helpers.get_dome_animatic_frame_info()
        if name:
            if name in bpy.data.scenes:
                return f"Scene '{name}' already exists"
            return f"Create collage scene: '{name}'"
        return "No image at current VSE frame"

    @classmethod
    def poll(cls, context):
        name, filepath, strip, el = vse_helpers.get_dome_animatic_frame_info()
        if not name:
            return False
        return name not in bpy.data.scenes

    def execute(self, context):
        g            = gp(context)
        camera_zoom  = g.last_camera_zoom

        name, filepath, strip, el = vse_helpers.get_dome_animatic_frame_info()
        scene_name = name

        if not scene_name:
            self.report({'ERROR'}, "No image found at Dome Animatic VSE playhead.")
            return {'CANCELLED'}
        if scene_name in bpy.data.scenes:
            self.report({'WARNING'}, f"Scene '{scene_name}' already exists.")
            return {'CANCELLED'}
        if not filepath or not os.path.exists(filepath):
            self.report({'ERROR'}, f"Image file not found: {filepath}")
            return {'CANCELLED'}

        # Block live sync during scene creation so it can't overwrite img
        _block_live_sync()

        img = bpy.data.images.load(filepath, check_existing=False)
        try:
            img.filepath = bpy.path.relpath(filepath)
        except ValueError:
            pass

        img_w, img_h = img.size[0], img.size[1]
        if img_w == 0 or img_h == 0:
            _unblock_live_sync()
            self.report({'ERROR'}, "Image has no pixel data.")
            return {'CANCELLED'}

        new_scene = bpy.data.scenes.new(name=scene_name)
        new_scene.render.resolution_x          = img_w
        new_scene.render.resolution_y          = img_h
        new_scene.render.resolution_percentage = 100

        context.window.scene = new_scene
        vse_helpers.switch_all_view3d_to_camera(context)

        aspect = img_w / img_h
        bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 0.0, 0.0))
        plane         = context.active_object
        plane.name    = scene_name
        plane.scale.x = aspect
        plane.scale.y = 1.0
        bpy.ops.object.transform_apply(scale=True)

        mat = bpy.data.materials.get(scene_name)
        if mat is None:
            mat = bpy.data.materials.new(name=scene_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        output         = nodes.new('ShaderNodeOutputMaterial')
        output.location = (200, 0)
        tex_node          = nodes.new('ShaderNodeTexImage')
        tex_node.image    = img
        tex_node.location = (-200, 0)
        links.new(tex_node.outputs['Color'], output.inputs['Surface'])

        if plane.data.materials:
            plane.data.materials[0] = mat
        else:
            plane.data.materials.append(mat)

        s = sp(new_scene)
        s.target_material = mat
        s.target_object   = plane
        s.target_image    = img

        _unblock_live_sync()

        cam_data             = bpy.data.cameras.new(name=f"{scene_name}.cam")
        cam_data.type        = 'ORTHO'
        cam_data.ortho_scale = camera_zoom
        cam_obj              = bpy.data.objects.new(name=f"{scene_name}.cam",
                                                    object_data=cam_data)
        new_scene.collection.objects.link(cam_obj)
        cam_obj.location       = (0.0, 0.0, 10.0)
        cam_obj.rotation_euler = (0.0, 0.0, 0.0)
        new_scene.camera       = cam_obj
        s['camera_zoom'] = camera_zoom

        vse_helpers.log(f"[CollageCollection] Created '{scene_name}' {img_w}x{img_h}")
        self.report({'INFO'}, f"Created '{scene_name}' at {img_w}x{img_h}.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_load_closest_scene(bpy.types.Operator):
    bl_idname      = "domeanimatic.load_closest_scene"
    bl_label       = "Load Closest"
    bl_description = "Switch to the scene whose name best matches the current VSE image"

    @classmethod
    def poll(cls, context):
        scene_name, _ = vse_helpers.get_current_scene_frame_info(context.scene)
        if not scene_name:
            return False
        closest, score = vse_helpers.find_closest_scene(scene_name)
        return closest is not None and score > 0

    def execute(self, context):
        scene_name, _  = vse_helpers.get_current_scene_frame_info(context.scene)
        closest, score = vse_helpers.find_closest_scene(scene_name)

        if not closest:
            self.report({'WARNING'}, "No matching scene found.")
            return {'CANCELLED'}
        target = bpy.data.scenes.get(closest)
        if not target:
            self.report({'ERROR'}, f"Scene '{closest}' not found.")
            return {'CANCELLED'}

        if context.scene.name == "Dome Animatic":
            vse_helpers.save_dome_view_state(context)
        context.window.scene = target
        vse_helpers.switch_all_view3d_to_camera(context)
        self.report({'INFO'}, f"Switched to '{closest}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_load_dome_animatic(bpy.types.Operator):
    bl_idname      = "domeanimatic.load_dome_animatic"
    bl_label       = "Load Dome Animatic"
    bl_description = "Switch to the Dome Animatic scene and reload LiveDomePreview"

    @classmethod
    def poll(cls, context):
        return "Dome Animatic" in bpy.data.scenes

    def execute(self, context):
        target = bpy.data.scenes.get("Dome Animatic")
        if not target:
            self.report({'ERROR'}, "Scene 'Dome Animatic' not found.")
            return {'CANCELLED'}
        context.window.scene = target
        vse_helpers.restore_dome_view_state(context)
        try:
            bpy.ops.domeanimatic.live_texture_reload()
        except Exception:
            pass
        self.report({'INFO'}, "Switched to 'Dome Animatic'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_switch_scene(bpy.types.Operator):
    bl_idname      = "domeanimatic.switch_scene"
    bl_label       = "Switch Scene"
    bl_description = "Switch to selected scene"

    scene_name: bpy.props.StringProperty()

    def execute(self, context):
        target = bpy.data.scenes.get(self.scene_name)
        if not target:
            self.report({'ERROR'}, f"Scene '{self.scene_name}' not found.")
            return {'CANCELLED'}
        context.window.scene = target
        self.report({'INFO'}, f"Switched to '{self.scene_name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_assign_target_image(bpy.types.Operator):
    bl_idname      = "domeanimatic.assign_target_image"
    bl_label       = "Assign Target Image"
    bl_description = "Assign target image to the first Image Texture node of target material"

    @classmethod
    def poll(cls, context):
        s = sp()
        return s.target_material is not None and s.target_image is not None

    def execute(self, context):
        s = sp()
        mat = s.target_material
        img = s.target_image
        if mat is None:
            self.report({'ERROR'}, "No target material set.")
            return {'CANCELLED'}
        if img is None:
            self.report({'ERROR'}, "No target image set.")
            return {'CANCELLED'}
        if not mat.use_nodes:
            self.report({'ERROR'}, f"Material '{mat.name}' has no nodes.")
            return {'CANCELLED'}
        tex_node = next((n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'), None)
        if tex_node is None:
            self.report({'ERROR'}, f"No Image Texture node in '{mat.name}'.")
            return {'CANCELLED'}
        tex_node.image = img
        self.report({'INFO'}, f"Assigned '{img.name}' to '{mat.name}'.")
        return {'FINISHED'}


# ── Live sync soft-dependency helpers ─────────────────────────────────────────

def _block_live_sync() -> None:
    try:
        from ..live_texture import vse_sync
        vse_sync.block_handler()
    except Exception:
        pass


def _unblock_live_sync() -> None:
    try:
        from ..live_texture import vse_sync
        vse_sync.unblock_handler()
    except Exception:
        pass


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [
    DOMEANIMATIC_OT_prepare_collage_scene,
    DOMEANIMATIC_OT_load_closest_scene,
    DOMEANIMATIC_OT_load_dome_animatic,
    DOMEANIMATIC_OT_switch_scene,
    DOMEANIMATIC_OT_assign_target_image,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if sync_zoom_on_scene_change not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_zoom_on_scene_change)


def unregister():
    if sync_zoom_on_scene_change in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_zoom_on_scene_change)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
