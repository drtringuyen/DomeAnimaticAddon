"""
collection_ops.py — Collage creation, solo/unsolo, and switching.

Each collage is a tagged Collection inside the single "Dome Animatic" scene.
Switching between collages solos the target collection via LayerCollection.exclude
rather than switching scenes.
"""

import bpy
import os

from ... import vse_helpers
from ...global_scene_shared_props import gp, sp


# ── Layer-collection tree traversal ───────────────────────────────────────────

def _find_layer_collection(layer_coll, name: str):
    if layer_coll.collection.name == name:
        return layer_coll
    for child in layer_coll.children:
        result = _find_layer_collection(child, name)
        if result:
            return result
    return None


# ── Collage collection helpers ─────────────────────────────────────────────────

def get_collage_collections():
    result = []
    for c in bpy.data.collections:
        try:
            if c.domeanimatic.is_collage:
                result.append(c)
        except AttributeError:
            pass
    return result


# ── Solo / unsolo ─────────────────────────────────────────────────────────────

def solo_collage(context, name: str) -> None:
    g = gp(context)

    # Capture overview state only when leaving overview mode
    if not g.active_collage:
        if context.scene.camera:
            g.dome_camera_name = context.scene.camera.name
        vse_helpers.save_dome_view_state(context)

    # Exclude every collage collection except the target
    vl = context.view_layer
    for coll in get_collage_collections():
        lc = _find_layer_collection(vl.layer_collection, coll.name)
        if lc:
            lc.exclude = (coll.name != name)

    # Switch scene camera to the collage camera and sync the zoom slider
    target_coll = bpy.data.collections.get(name)
    if target_coll:
        cam_obj = next((o for o in target_coll.objects if o.type == 'CAMERA'), None)
        if cam_obj:
            context.scene.camera = cam_obj
            # Set camera_zoom on scene props so the UI slider matches the camera
            sp().camera_zoom = cam_obj.data.ortho_scale

    vse_helpers.switch_all_view3d_to_camera(context)
    g.active_collage = name


def unsolo_collage(context) -> None:
    g = gp(context)

    # Un-exclude all collage collections
    vl = context.view_layer
    for coll in get_collage_collections():
        lc = _find_layer_collection(vl.layer_collection, coll.name)
        if lc:
            lc.exclude = False

    # Restore the dome camera
    if g.dome_camera_name:
        dome_cam = bpy.data.objects.get(g.dome_camera_name)
        if dome_cam:
            context.scene.camera = dome_cam

    vse_helpers.restore_dome_view_state(context)
    g.active_collage = ""


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


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_prepare_collage_scene(bpy.types.Operator):
    bl_idname      = "domeanimatic.prepare_collage_scene"
    bl_label       = "Create Collage"
    bl_description = "Create a new collage collection from current VSE frame"

    @classmethod
    def description(cls, context, properties):
        name, filepath, strip, el = vse_helpers.get_dome_animatic_frame_info()
        if name:
            coll = bpy.data.collections.get(name)
            if coll and coll.domeanimatic.is_collage:
                return f"Collage '{name}' already exists"
            return f"Create collage: '{name}'"
        return "No image at current VSE frame"

    @classmethod
    def poll(cls, context):
        name, filepath, strip, el = vse_helpers.get_dome_animatic_frame_info()
        if not name:
            return False
        coll = bpy.data.collections.get(name)
        return coll is None or not coll.domeanimatic.is_collage

    def execute(self, context):
        g = gp(context)
        name, filepath, strip, el = vse_helpers.get_dome_animatic_frame_info()
        coll_name = name

        if not coll_name:
            self.report({'ERROR'}, "No image found at Dome Animatic VSE playhead.")
            return {'CANCELLED'}
        existing = bpy.data.collections.get(coll_name)
        if existing and existing.domeanimatic.is_collage:
            self.report({'WARNING'}, f"Collage '{coll_name}' already exists.")
            return {'CANCELLED'}
        if not filepath or not os.path.exists(filepath):
            self.report({'ERROR'}, f"Image file not found: {filepath}")
            return {'CANCELLED'}

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

        # Create the collection and tag it
        coll = bpy.data.collections.new(name=coll_name)
        context.scene.collection.children.link(coll)
        coll.domeanimatic.is_collage = True

        # Add image plane (goes to the active/root collection first)
        aspect = img_w / img_h
        bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 0.0, 0.0))
        plane         = context.active_object
        plane.name    = coll_name
        plane.scale.x = aspect
        plane.scale.y = 1.0
        bpy.ops.object.transform_apply(scale=True)

        # Move plane into the collage collection (out of wherever Blender put it)
        for src in list(plane.users_collection):
            src.objects.unlink(plane)
        coll.objects.link(plane)

        mat = bpy.data.materials.get(coll_name)
        if mat is None:
            mat = bpy.data.materials.new(name=coll_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        output            = nodes.new('ShaderNodeOutputMaterial')
        output.location   = (200, 0)
        tex_node          = nodes.new('ShaderNodeTexImage')
        tex_node.image    = img
        tex_node.location = (-200, 0)
        links.new(tex_node.outputs['Color'], output.inputs['Surface'])

        if plane.data.materials:
            plane.data.materials[0] = mat
        else:
            plane.data.materials.append(mat)

        coll.domeanimatic.target_material = mat
        coll.domeanimatic.target_object   = plane
        coll.domeanimatic.target_image    = img

        _unblock_live_sync()

        # Create ortho camera directly into the collage collection
        cam_data             = bpy.data.cameras.new(name=f"{coll_name}.cam")
        cam_data.type        = 'ORTHO'
        cam_data.ortho_scale = g.last_camera_zoom
        cam_obj              = bpy.data.objects.new(name=f"{coll_name}.cam",
                                                    object_data=cam_data)
        coll.objects.link(cam_obj)
        cam_obj.location       = (0.0, 0.0, 10.0)
        cam_obj.rotation_euler = (0.0, 0.0, 0.0)

        solo_collage(context, coll_name)

        vse_helpers.log(f"[CollageCollection] Created '{coll_name}' {img_w}x{img_h}")
        self.report({'INFO'}, f"Created collage '{coll_name}' at {img_w}x{img_h}.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_load_closest_scene(bpy.types.Operator):
    bl_idname      = "domeanimatic.load_closest_scene"
    bl_label       = "Load Closest"
    bl_description = "Solo the collage whose name best matches the current VSE image"

    @classmethod
    def poll(cls, context):
        scene_name, _ = vse_helpers.get_current_scene_frame_info(context.scene)
        if not scene_name:
            return False
        closest, score = vse_helpers.find_closest_collage(scene_name)
        return closest is not None and score > 0

    def execute(self, context):
        scene_name, _ = vse_helpers.get_current_scene_frame_info(context.scene)
        closest, score = vse_helpers.find_closest_collage(scene_name)

        if not closest:
            self.report({'WARNING'}, "No matching collage found.")
            return {'CANCELLED'}

        solo_collage(context, closest)
        self.report({'INFO'}, f"Switched to '{closest}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_load_dome_animatic(bpy.types.Operator):
    bl_idname      = "domeanimatic.load_dome_animatic"
    bl_label       = "Load Dome Animatic"
    bl_description = "Return to overview mode and reload LiveDomePreview"

    @classmethod
    def poll(cls, context):
        return gp(context).active_collage != ""

    def execute(self, context):
        unsolo_collage(context)
        try:
            bpy.ops.domeanimatic.live_texture_reload()
        except Exception:
            pass
        self.report({'INFO'}, "Returned to overview.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_switch_scene(bpy.types.Operator):
    bl_idname      = "domeanimatic.switch_scene"
    bl_label       = "Switch Scene"
    bl_description = "Switch to selected collage"

    scene_name: bpy.props.StringProperty()

    def execute(self, context):
        coll = bpy.data.collections.get(self.scene_name)
        if not coll or not coll.domeanimatic.is_collage:
            self.report({'ERROR'}, f"Collage '{self.scene_name}' not found.")
            return {'CANCELLED'}
        solo_collage(context, self.scene_name)
        self.report({'INFO'}, f"Switched to '{self.scene_name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_assign_target_image(bpy.types.Operator):
    bl_idname      = "domeanimatic.assign_target_image"
    bl_label       = "Assign Target Image"
    bl_description = "Assign target image to the first Image Texture node of target material"

    @classmethod
    def poll(cls, context):
        coll = bpy.data.collections.get(gp(context).active_collage)
        if not coll:
            return False
        cd = coll.domeanimatic
        return cd.target_material is not None and cd.target_image is not None

    def execute(self, context):
        coll = bpy.data.collections.get(gp(context).active_collage)
        if not coll:
            self.report({'ERROR'}, "No active collage.")
            return {'CANCELLED'}
        cd  = coll.domeanimatic
        mat = cd.target_material
        img = cd.target_image
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


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
