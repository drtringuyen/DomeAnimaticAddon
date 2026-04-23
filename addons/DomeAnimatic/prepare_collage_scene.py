import bpy
import os
from bpy.app.handlers import persistent
from . import utils, synch_VSE_to_LiveDomePreview as synch


# ── Update callback ───────────────────────────────────────────────────────────

def update_camera_zoom(self, context):
    cam = context.scene.camera
    if cam and cam.data.type == 'ORTHO':
        cam.data.ortho_scale = self.camera_zoom
    context.window_manager.domeanimatic_last_camera_zoom = self.camera_zoom


# ── Handler ───────────────────────────────────────────────────────────────────

@persistent
def sync_zoom_on_scene_change(scene):
    try:
        wm   = bpy.context.window_manager
        last = wm.domeanimatic_last_camera_zoom

        settings = scene.domeanimatic_collage_settings
        cam      = scene.camera

        if cam and cam.data.type == 'ORTHO':
            if settings.camera_zoom != cam.data.ortho_scale:
                settings['camera_zoom'] = cam.data.ortho_scale
            wm.domeanimatic_last_camera_zoom = cam.data.ortho_scale
        else:
            if settings.camera_zoom != last:
                settings['camera_zoom'] = last
    except Exception:
        pass


# ── Properties ────────────────────────────────────────────────────────────────

class DOMEANIMATIC_PG_collage_settings(bpy.types.PropertyGroup):
    camera_zoom: bpy.props.FloatProperty(
        name="Camera Zoom",
        description="Orthographic scale carried over between scenes",
        default=3.055,
        min=0.01,
        max=1000.0,
        step=10,
        precision=3,
        update=update_camera_zoom,
    )


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_prepare_collage_scene(bpy.types.Operator):
    bl_idname = "domeanimatic.prepare_collage_scene"
    bl_label = "Create Collage Scene"
    bl_description = "Create a new scene with image plane and orthographic camera from current VSE frame"

    @classmethod
    def description(cls, context, properties):
        name, filepath, strip, el = utils.get_dome_animatic_frame_info()
        if name:
            if name in bpy.data.scenes:
                return f"Scene '{name}' already exists"
            return f"Create collage scene: '{name}'"
        return "No image at current VSE frame"

    @classmethod
    def poll(cls, context):
        name, filepath, strip, el = utils.get_dome_animatic_frame_info()
        if not name:
            return False
        if name in bpy.data.scenes:
            return False
        return True

    def execute(self, context):
        original_scene = context.scene
        camera_zoom    = context.window_manager.domeanimatic_last_camera_zoom

        # Always read image from Dome Animatic VSE playhead
        name, filepath, strip, el = utils.get_dome_animatic_frame_info()
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

        # Block VSE handler so it can't overwrite img during creation
        synch.block_handler()

        # ── 1. Load image directly from filepath ──────────────────────────────
        img = bpy.data.images.load(filepath, check_existing=False)
        # Store as relative path so the blend file stays portable
        try:
            img.filepath = bpy.path.relpath(filepath)
        except ValueError:
            pass  # Different drive — keep absolute
        # If a duplicate was loaded, find the one matching the filepath
        img_w = img.size[0]
        img_h = img.size[1]

        if img_w == 0 or img_h == 0:
            self.report({'ERROR'}, "Image has no pixel data.")
            return {'CANCELLED'}

        # ── 2. Create new scene ───────────────────────────────────────────────
        new_scene = bpy.data.scenes.new(name=scene_name)

        # ── 3. Set output resolution ──────────────────────────────────────────
        new_scene.render.resolution_x          = img_w
        new_scene.render.resolution_y          = img_h
        new_scene.render.resolution_percentage = 100

        # ── 4. Switch to new scene ────────────────────────────────────────────
        context.window.scene = new_scene
        utils.switch_all_view3d_to_camera(context)

        # ── 5. Create image plane ─────────────────────────────────────────────
        aspect        = img_w / img_h
        bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 0.0, 0.0))
        plane         = context.active_object
        plane.name    = scene_name
        plane.scale.x = aspect
        plane.scale.y = 1.0
        bpy.ops.object.transform_apply(scale=True)

        # ── 6. Create or reuse material ───────────────────────────────────────
        mat = bpy.data.materials.get(scene_name)
        if mat is None:
            mat = bpy.data.materials.new(name=scene_name)

        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Always clear and rebuild — removes default Principled BSDF
        nodes.clear()

        output          = nodes.new('ShaderNodeOutputMaterial')
        output.location = (200, 0)

        tex_node          = nodes.new('ShaderNodeTexImage')
        tex_node.image    = img
        tex_node.location = (-200, 0)

        links.new(tex_node.outputs['Color'], output.inputs['Surface'])

        if plane.data.materials:
            plane.data.materials[0] = mat
        else:
            plane.data.materials.append(mat)

        # Set scene target pointers for easy access
        new_scene.domeanimatic_target_material = mat
        new_scene.domeanimatic_target_object   = plane
        new_scene.domeanimatic_target_image    = img

        # Unblock handler now that material is fully set
        synch.unblock_handler()

        # ── 7. Create orthographic camera ─────────────────────────────────────
        cam_data             = bpy.data.cameras.new(name=f"{scene_name}.cam")
        cam_data.type        = 'ORTHO'
        cam_data.ortho_scale = camera_zoom

        cam_obj                = bpy.data.objects.new(name=f"{scene_name}.cam", object_data=cam_data)
        new_scene.collection.objects.link(cam_obj)
        cam_obj.location       = (0.0, 0.0, 10.0)
        cam_obj.rotation_euler = (0.0, 0.0, 0.0)
        new_scene.camera       = cam_obj

        new_scene.domeanimatic_collage_settings['camera_zoom'] = camera_zoom

        utils.log(f"[CollageScene] Created '{scene_name}' at {img_w}x{img_h} zoom {camera_zoom}")
        self.report({'INFO'}, f"Created '{scene_name}' at {img_w}x{img_h} — zoom {camera_zoom}.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_load_closest_scene(bpy.types.Operator):
    bl_idname = "domeanimatic.load_closest_scene"
    bl_label = "Load Closest"
    bl_description = "Switch to the scene whose name best matches the current VSE image"

    @classmethod
    def poll(cls, context):
        scene_name, _ = utils.get_current_scene_frame_info(context.scene)
        if not scene_name:
            return False
        closest, score = utils.find_closest_scene(scene_name)
        return closest is not None and score > 0

    def execute(self, context):
        scene_name, _  = utils.get_current_scene_frame_info(context.scene)
        closest, score = utils.find_closest_scene(scene_name)

        if not closest:
            self.report({'WARNING'}, "No matching scene found.")
            return {'CANCELLED'}

        target = bpy.data.scenes.get(closest)
        if not target:
            self.report({'ERROR'}, f"Scene '{closest}' not found.")
            return {'CANCELLED'}

        # Save view if leaving Dome Animatic
        if context.scene.name == "Dome Animatic":
            utils.save_dome_view_state(context)

        context.window.scene = target
        utils.switch_all_view3d_to_camera(context)

        utils.log(f"[LoadClosest] Switched to '{closest}'")
        self.report({'INFO'}, f"Switched to '{closest}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_load_dome_animatic(bpy.types.Operator):
    bl_idname = "domeanimatic.load_dome_animatic"
    bl_label = "Load Dome Animatic"
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
        utils.log("[LoadDomeAnimatic] Switched to 'Dome Animatic'")

        # Restore saved view state
        utils.restore_dome_view_state(context)

        # Trigger reload of LiveDomePreview after switching
        bpy.ops.domeanimatic.reload_live_dome_texture()

        self.report({'INFO'}, "Switched to 'Dome Animatic' — LiveDomePreview reloaded.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_switch_scene(bpy.types.Operator):
    bl_idname = "domeanimatic.switch_scene"
    bl_label = "Switch Scene"
    bl_description = "Switch to selected scene"

    scene_name: bpy.props.StringProperty()

    def execute(self, context):
        target = bpy.data.scenes.get(self.scene_name)
        if not target:
            self.report({'ERROR'}, f"Scene '{self.scene_name}' not found.")
            return {'CANCELLED'}
        context.window.scene = target
        utils.log(f"[SwitchScene] Switched to '{self.scene_name}'")
        self.report({'INFO'}, f"Switched to '{self.scene_name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_assign_target_image(bpy.types.Operator):
    bl_idname = "domeanimatic.assign_target_image"
    bl_label = "Assign Target Image"
    bl_description = (
        "Assign the target image to the first Image Texture node "
        "of the target material (not LiveDomePreview)"
    )

    @classmethod
    def poll(cls, context):
        return (
            context.scene.domeanimatic_target_material is not None
            and context.scene.domeanimatic_target_image is not None
        )

    def execute(self, context):
        mat = context.scene.domeanimatic_target_material
        img = context.scene.domeanimatic_target_image

        if mat is None:
            self.report({'ERROR'}, "No target material set.")
            return {'CANCELLED'}

        if img is None:
            self.report({'ERROR'}, "No target image set.")
            return {'CANCELLED'}

        if not mat.use_nodes:
            self.report({'ERROR'}, f"Material '{mat.name}' has no nodes.")
            return {'CANCELLED'}

        # Find the first Image Texture node
        tex_node = next(
            (n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'),
            None
        )

        if tex_node is None:
            self.report({'ERROR'}, f"No Image Texture node found in '{mat.name}'.")
            return {'CANCELLED'}

        tex_node.image = img
        utils.log(f"[AssignTargetImage] '{img.name}' → '{mat.name}'")
        self.report({'INFO'}, f"Assigned '{img.name}' to '{mat.name}'.")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    scene      = context.scene
    settings   = scene.domeanimatic_collage_settings
    scene_name, filepath = utils.get_current_scene_frame_info(scene)

    verbose = utils.show_labels(context)

    if verbose:
        # ── Info texts (greyed out) ───────────────────────────────────────────
        closest, score = utils.find_closest_scene(scene_name) if scene_name else (None, 0)

        info_col = box.column(align=True)
        info_col.enabled = False

        if closest:
            info_col.label(text=f"Closest: {closest}", icon='SCENE_DATA')
        else:
            info_col.label(text="No matching scene found", icon='INFO')

        if scene_name:
            if scene_name in bpy.data.scenes:
                info_col.label(text=f"'{scene_name}' already exists", icon='INFO')
            else:
                info_col.label(text=f"New scene: {scene_name}", icon='ADD')
        else:
            info_col.label(text="No image at current frame", icon='ERROR')

    # ── Load buttons ──────────────────────────────────────────────────────────
    is_dome      = scene.name == "Dome Animatic"
    # Grey out Load Closest if the only scene is Dome Animatic
    only_dome    = len(bpy.data.scenes) <= 1

    row = box.row(align=True)
    load_closest_row = row.row(align=True)
    load_closest_row.enabled = not only_dome
    load_closest_row.operator("domeanimatic.load_closest_scene", text="Nearest Collage", icon='FILE_REFRESH')
    row.operator("domeanimatic.load_dome_animatic", text="Load Dome Animatic", icon='SEQUENCE')

    # ── Camera Zoom ───────────────────────────────────────────────────────────
    row = box.row(align=True)
    row.label(text="", icon='CAMERA_DATA')
    row.prop(settings, "camera_zoom", text="Camera Zoom")

    # ── Object / Material / Image slots + reload — grey out on Dome Animatic ──
    slots_row = box.row(align=True)
    slots_row.enabled = not is_dome
    slots_row.prop(scene, "domeanimatic_target_object",   text="", icon='OBJECT_DATA')
    slots_row.prop(scene, "domeanimatic_target_material", text="", icon='MATERIAL')
    slots_row.prop(scene, "domeanimatic_target_image",    text="", icon='IMAGE_DATA')
    slots_row.operator(
        "domeanimatic.assign_target_image",
        text="",
        icon='FILE_REFRESH',
    )

    # ── Create Collage Scene ──────────────────────────────────────────────────
    col = box.column()
    col.scale_y = 1.5
    col.operator(
        "domeanimatic.prepare_collage_scene",
        text="Create Collage Scene",
        icon='SCULPTMODE_HLT',
    )

    # ── Scene List (collapsible) ──────────────────────────────────────────────
    sub_box = box.box()
    sub_row = sub_box.row()
    sub_row.prop(
        scene,
        "domeanimatic_manual_scene_expanded",
        icon='TRIA_DOWN' if scene.domeanimatic_manual_scene_expanded else 'TRIA_RIGHT',
        icon_only=True,
        emboss=False,
    )
    sub_row.label(text="Scene List", icon='SCENE_DATA')

    if scene.domeanimatic_manual_scene_expanded:
        for s in bpy.data.scenes:
            row = sub_box.row(align=True)
            if s.name == context.scene.name:
                row.enabled = False
                row.label(text=s.name, icon='SCENE_DATA')
            else:
                op = sub_box.operator("domeanimatic.switch_scene", text=s.name, icon='SCENE_DATA')
                op.scene_name = s.name


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_PG_collage_settings,
    DOMEANIMATIC_OT_prepare_collage_scene,
    DOMEANIMATIC_OT_load_closest_scene,
    DOMEANIMATIC_OT_load_dome_animatic,
    DOMEANIMATIC_OT_switch_scene,
    DOMEANIMATIC_OT_assign_target_image,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.domeanimatic_collage_settings = bpy.props.PointerProperty(
        type=DOMEANIMATIC_PG_collage_settings
    )

    if sync_zoom_on_scene_change not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_zoom_on_scene_change)

def unregister():
    if sync_zoom_on_scene_change in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_zoom_on_scene_change)

    del bpy.types.Scene.domeanimatic_collage_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
