import bpy
from bpy.app.handlers import persistent
from . import utils


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_color_a_strip(scene):
    """Find the named color A strip in Dome Animatic's VSE."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return None
    strip_name = scene.domeanimatic_color_a_strip_name
    se = dome_scene.sequence_editor
    # Blender 5.x: strips (current meta level) or strips_all (all nested)
    return se.strips_all.get(strip_name)


def read_color_a_value(scene):
    """
    Read the current blend_alpha of the color A strip at the current frame.
    Returns 0.0 if the strip is not found.
    """
    strip = get_color_a_strip(scene)
    if strip is None:
        return 0.0
    return getattr(strip, 'blend_alpha', 0.0)


def read_color_a_color(scene):
    """Read the color of the color A strip (COLOR strip has a .color property)."""
    strip = get_color_a_strip(scene)
    if strip is None:
        return (0.0, 0.0, 0.0)
    if hasattr(strip, 'color'):
        return tuple(strip.color)
    return (0.0, 0.0, 0.0)


def set_color_a_strip_color(scene, color):
    """Set the color A strip color and update the scene property."""
    strip = get_color_a_strip(scene)
    if strip is None:
        return False
    if hasattr(strip, 'color'):
        strip.color = color
        scene.domeanimatic_color_a_color = color
        return True
    return False


# ── Color B Strip Helpers ─────────────────────────────────────────────────────

def get_color_b_strip(scene):
    """Find the named color B strip in Dome Animatic's VSE."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return None
    strip_name = scene.domeanimatic_color_b_strip_name
    se = dome_scene.sequence_editor
    return se.strips_all.get(strip_name)


def read_color_b_value(scene):
    """
    Read the current blend_alpha of the color B strip at the current frame.
    Returns 0.0 if the strip is not found.
    """
    strip = get_color_b_strip(scene)
    if strip is None:
        return 0.0
    return getattr(strip, 'blend_alpha', 0.0)


def read_color_b_color(scene):
    """Read the color of the color B strip (COLOR strip has a .color property)."""
    strip = get_color_b_strip(scene)
    if strip is None:
        return (1.0, 1.0, 1.0)
    if hasattr(strip, 'color'):
        return tuple(strip.color)
    return (1.0, 1.0, 1.0)


def set_color_b_strip_color(scene, color):
    """Set the color B strip color and update the scene property."""
    strip = get_color_b_strip(scene)
    if strip is None:
        return False
    if hasattr(strip, 'color'):
        strip.color = color
        scene.domeanimatic_color_b_color = color
        return True
    return False


def push_color_a_to_mix_node_b(dome_scene, color_a):
    """
    Set the B socket (second input) color of the FIRST Mix node
    to the given color A. Returns True if successful.
    """
    current_scene = bpy.context.scene if bpy.context else None
    if current_scene is None:
        return False

    mat = current_scene.domeanimatic_target_material
    if mat is None or not mat.use_nodes:
        return False

    # Find the first Mix node
    mix_nodes = [n for n in mat.node_tree.nodes if n.type in ('MIX_RGB', 'MIX')]
    if not mix_nodes:
        return False

    mix_node = mix_nodes[0]

    # Set the B socket to color_a (B is socket 2, or by name)
    try:
        # Try by name first (Blender 5.1)
        mix_node.inputs['B'].default_value = (*color_a, 1.0)
        utils.log(f"[ColorA] ✅ Updated Mix node B color to {color_a}")
        return True
    except (KeyError, AttributeError):
        try:
            # Fallback: use index 2 for B socket
            mix_node.inputs[2].default_value = (*color_a, 1.0)
            return True
        except (IndexError, AttributeError):
            return False


def push_color_b_to_mix_node_b(dome_scene, color_b):
    """
    Set the B socket (second input) color of the SECOND Mix node
    to the given color B. Returns True if successful.
    """
    current_scene = bpy.context.scene if bpy.context else None
    if current_scene is None:
        return False

    mat = current_scene.domeanimatic_target_material
    if mat is None or not mat.use_nodes:
        return False

    # Find the second Mix node
    mix_nodes = [n for n in mat.node_tree.nodes if n.type in ('MIX_RGB', 'MIX')]
    if len(mix_nodes) < 2:
        return False

    mix_node = mix_nodes[1]

    # Set the B socket to color_b
    try:
        mix_node.inputs['B'].default_value = (*color_b, 1.0)
        utils.log(f"[ColorB] ✅ Updated Mix node B color to {color_b}")
        return True
    except (KeyError, AttributeError):
        try:
            mix_node.inputs[2].default_value = (*color_b, 1.0)
            return True
        except (IndexError, AttributeError):
            return False


def push_color_a_value_to_mix_node(dome_scene, color_a_value):
    """
    Find the Mix node in the target material and set its Factor input
    to the given color A value. Returns True if successful.
    """
    # Get the target material (from collage scene, not dome scene)
    # The target material is stored in the current scene, not dome scene
    current_scene = bpy.context.scene if bpy.context else None
    if current_scene is None:
        utils.log("[ColorA] ❌ No current scene context")
        return False

    mat = current_scene.domeanimatic_target_material
    if mat is None:
        utils.log("[ColorA] ⚠️  No target material set in scene")
        return False

    if not mat.use_nodes:
        utils.log(f"[ColorA] ⚠️  Material '{mat.name}' has no node graph")
        return False

    # Find the Mix node
    mix_node = None
    for node in mat.node_tree.nodes:
        if node.type == 'MIX_RGB' or node.type == 'MIX':
            mix_node = node
            utils.log(f"[ColorA] Found Mix node: {node.name} (type: {node.type})")
            break

    if mix_node is None:
        utils.log(f"[ColorA] ❌ No Mix node found in material '{mat.name}'")
        utils.log(f"[ColorA] Available nodes: {[n.name + '(' + n.type + ')' for n in mat.node_tree.nodes]}")
        return False

    # Set the Factor input to color_a_value
    try:
        # Blender 5.1 uses 'Factor' socket
        mix_node.inputs['Factor'].default_value = color_a_value
        utils.log(f"[ColorA] ✅ Updated Mix node Factor to {color_a_value:.3f}")
        return True
    except (KeyError, AttributeError) as e:
        # Fallback for older versions that use index 0
        try:
            mix_node.inputs[0].default_value = color_a_value
            utils.log(f"[ColorA] ✅ Updated Mix node inputs[0] to {color_a_value:.3f}")
            return True
        except (IndexError, AttributeError) as e2:
            utils.log(f"[ColorA] ❌ Could not set Factor: {e}, {e2}")
            return False


def push_color_b_value_to_mix_node(dome_scene, color_b_value):
    """
    Find the SECOND Mix node in the target material and set its Factor input
    to the given color B value (for color B). Returns True if successful.
    """
    current_scene = bpy.context.scene if bpy.context else None
    if current_scene is None:
        utils.log("[ColorB] ❌ No current scene context")
        return False

    mat = current_scene.domeanimatic_target_material
    if mat is None:
        utils.log("[ColorB] ⚠️  No target material set in scene")
        return False

    if not mat.use_nodes:
        utils.log(f"[ColorB] ⚠️  Material '{mat.name}' has no node graph")
        return False

    # Find all Mix nodes and get the second one
    mix_nodes = [n for n in mat.node_tree.nodes if n.type in ('MIX_RGB', 'MIX')]

    if len(mix_nodes) < 2:
        utils.log(f"[ColorB] ⚠️  Need at least 2 Mix nodes, found {len(mix_nodes)}")
        return False

    # Use the second Mix node (index 1)
    mix_node = mix_nodes[1]
    utils.log(f"[ColorB] Found Mix node (color B): {mix_node.name} (type: {mix_node.type})")

    # Set the Factor input to color_b_value
    try:
        mix_node.inputs['Factor'].default_value = color_b_value
        utils.log(f"[ColorB] ✅ Updated Mix node Factor to {color_b_value:.3f}")
        return True
    except (KeyError, AttributeError) as e:
        try:
            mix_node.inputs[0].default_value = color_b_value
            utils.log(f"[ColorB] ✅ Updated Mix node inputs[0] to {color_b_value:.3f}")
            return True
        except (IndexError, AttributeError) as e2:
            utils.log(f"[ColorB] ❌ Could not set Factor: {e}, {e2}")
            return False


# ── Persistent handler: read fade value every frame ──────────────────────────

@persistent
def color_sync_handler(scene, depsgraph=None):
    """
    Read the color A and color B strip's blend_alpha at the current Dome Animatic frame,
    store them in domeanimatic_color_a/b_value, and DRIVE the Mix node's Factor.
    """
    try:
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return

        strip = get_color_a_strip(dome_scene)
        if strip is None:
            utils.log("[ColorA] ⚠️  Color A strip not found")
            return

        # Read evaluated blend_alpha (respects F-Curve/NLA)
        color_a_val = getattr(strip, 'blend_alpha', 0.0)
        if dome_scene.domeanimatic_color_a_value != color_a_val:
            dome_scene.domeanimatic_color_a_value = color_a_val
            utils.log(f"[ColorA] Handler fired → color_a_value = {color_a_val:.3f}, strip = {strip.name}")

        # ✅ SYNC COLOR: Addon color → VSE strip + Mix node B socket
        # The addon color is the source of truth now
        color_a = dome_scene.domeanimatic_color_a_color[:3]

        # Push addon color to VSE strip
        if hasattr(strip, 'color'):
            strip.color = color_a

        # ✅ PUSH the color A value to the Mix node's Factor input
        push_color_a_value_to_mix_node(dome_scene, color_a_val)

        # ✅ PUSH the color A to the Mix node's B socket (auto-sync)
        push_color_a_to_mix_node_b(dome_scene, color_a)

        # ── Handle Color B Strip ──────────────────────────────────────────────
        strip_b = get_color_b_strip(dome_scene)
        if strip_b is not None:
            color_b_val = getattr(strip_b, 'blend_alpha', 0.0)
            if dome_scene.domeanimatic_color_b_value != color_b_val:
                dome_scene.domeanimatic_color_b_value = color_b_val
                utils.log(f"[ColorB] Handler fired → color_b_value = {color_b_val:.3f}, strip = {strip_b.name}")

            # ✅ SYNC COLOR: Addon color → VSE strip + Mix node B socket
            # The addon color is the source of truth now
            color_b = dome_scene.domeanimatic_color_b_color[:3]

            # Push addon color to VSE strip
            if hasattr(strip_b, 'color'):
                strip_b.color = color_b

            # ✅ PUSH the color B value to the second Mix node's Factor input
            push_color_b_value_to_mix_node(dome_scene, color_b_val)

            # ✅ PUSH the color B to the second Mix node's B socket (auto-sync)
            push_color_b_to_mix_node_b(dome_scene, color_b)

    except Exception as e:
        utils.log(f"[ColorSync] ❌ Handler error: {e}")


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_set_color_a(bpy.types.Operator):
    bl_idname      = "domeanimatic.set_color_a"
    bl_label       = "Apply Color A"
    bl_description = "Set the color A strip's color to the chosen color A"

    @classmethod
    def poll(cls, context):
        return get_color_a_strip(context.scene) is not None

    def execute(self, context):
        color = tuple(context.scene.domeanimatic_color_a_color)
        if set_color_a_strip_color(context.scene, color):
            self.report({'INFO'}, f"Color A strip color set to {color}.")
        else:
            self.report({'WARNING'}, "Could not set color A strip color.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_keyframe_color_a(bpy.types.Operator):
    bl_idname      = "domeanimatic.keyframe_color_a"
    bl_label       = "Insert Color A Keyframe"
    bl_description = "Insert a keyframe on the color A strip's blend_alpha at current frame"

    @classmethod
    def poll(cls, context):
        return get_color_a_strip(context.scene) is not None

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        strip      = get_color_a_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, "Color A strip not found.")
            return {'CANCELLED'}

        frame = dome_scene.frame_current if dome_scene else context.scene.frame_current
        strip.blend_alpha = context.scene.domeanimatic_color_a_value
        strip.keyframe_insert(data_path="blend_alpha", frame=frame)
        self.report({'INFO'}, f"Keyframe inserted at frame {frame}.")
        return {'FINISHED'}


# ── Color B Operators ─────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_set_color_b(bpy.types.Operator):
    bl_idname      = "domeanimatic.set_color_b"
    bl_label       = "Apply Color B"
    bl_description = "Set the color B strip's color to the chosen color B"

    @classmethod
    def poll(cls, context):
        return get_color_b_strip(context.scene) is not None

    def execute(self, context):
        color = tuple(context.scene.domeanimatic_color_b_color)
        if set_color_b_strip_color(context.scene, color):
            self.report({'INFO'}, f"Color B strip color set to {color}.")
        else:
            self.report({'WARNING'}, "Could not set color B strip color.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_keyframe_color_b(bpy.types.Operator):
    bl_idname      = "domeanimatic.keyframe_color_b"
    bl_label       = "Insert Color B Keyframe"
    bl_description = "Insert a keyframe on the color B strip's blend_alpha at current frame"

    @classmethod
    def poll(cls, context):
        return get_color_b_strip(context.scene) is not None

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        strip      = get_color_b_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, "Color B strip not found.")
            return {'CANCELLED'}

        frame = dome_scene.frame_current if dome_scene else context.scene.frame_current
        strip.blend_alpha = context.scene.domeanimatic_color_b_value
        strip.keyframe_insert(data_path="blend_alpha", frame=frame)
        self.report({'INFO'}, f"Keyframe inserted at frame {frame}.")
        return {'FINISHED'}


# ── Refresh Operators (Validate + Sync Colors) ────────────────────────────────

class DOMEANIMATIC_OT_refresh_color_a(bpy.types.Operator):
    bl_idname      = "domeanimatic.refresh_color_a"
    bl_label       = "Refresh Color A"
    bl_description = "Validate binding and sync color to Mix node (Color A)"

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}

        # 1. Check strip exists
        strip = get_color_a_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, f"Strip '{context.scene.domeanimatic_color_a_strip_name}' not found in Dome Animatic VSE.")
            return {'CANCELLED'}

        # 2. Sync color to VSE strip
        color_a = context.scene.domeanimatic_color_a_color[:3]
        strip.color = color_a

        # 3. Sync color to Mix node B socket (1st Mix node)
        if push_color_a_to_mix_node_b(dome_scene, color_a):
            self.report({'INFO'}, f"✅ Color A: Strip '{strip.name}' + Mix node synced")
            utils.log(f"[ColorA] ✅ Refresh: Updated '{strip.name}' color to Mix node")
        else:
            self.report({'WARNING'}, f"Strip synced, but could not update Mix node (check material binding)")
            utils.log(f"[ColorA] ⚠️  Refresh: Strip synced but Mix node update failed")

        return {'FINISHED'}


class DOMEANIMATIC_OT_refresh_color_b(bpy.types.Operator):
    bl_idname      = "domeanimatic.refresh_color_b"
    bl_label       = "Refresh Color B"
    bl_description = "Validate binding and sync color to Mix node (Color B)"

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}

        # 1. Check strip exists
        strip = get_color_b_strip(context.scene)
        if strip is None:
            self.report({'ERROR'}, f"Strip '{context.scene.domeanimatic_color_b_strip_name}' not found in Dome Animatic VSE.")
            return {'CANCELLED'}

        # 2. Sync color to VSE strip
        color_b = context.scene.domeanimatic_color_b_color[:3]
        strip.color = color_b

        # 3. Sync color to Mix node B socket (2nd Mix node)
        if push_color_b_to_mix_node_b(dome_scene, color_b):
            self.report({'INFO'}, f"✅ Color B: Strip '{strip.name}' + Mix node synced")
            utils.log(f"[ColorB] ✅ Refresh: Updated '{strip.name}' color to Mix node")
        else:
            self.report({'WARNING'}, f"Strip synced, but could not update Mix node (check material binding)")
            utils.log(f"[ColorB] ⚠️  Refresh: Strip synced but Mix node update failed")

        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    scene      = context.scene

    col = box.column(align=True)

    # ── COLOR A (FIRST MIX NODE) ──────────────────────────────────────────────
    col.label(text="Fade to Black (1st Mix Node + VSE strip)", icon='TRIA_RIGHT')
    strip = get_color_a_strip(scene)

    if strip is None:
        row = col.row()
        row.enabled = False
        row.label(text="Strip not found", icon='ERROR')
    else:
        # ── Single ROW: [Refresh] [Color↓] [Strip] [Opacity━━━━━━━━━━━] [Key] ────
        row = col.row(align=True)
        row.operator("domeanimatic.refresh_color_a", text="", icon='FILE_REFRESH')

        # Color (narrower: 8% of row)
        split_color = row.split(factor=0.08, align=True)
        split_color.prop(scene, "domeanimatic_color_a_color", text="")

        # Strip (normal: ~12% of remaining)
        split_strip = split_color.split(factor=0.13, align=True)
        split_strip.prop(scene, "domeanimatic_color_a_strip_name", text="")

        # Opacity (stretched: ~91% of remaining to fill space)
        split_opacity = split_strip.split(factor=0.91, align=True)
        split_opacity.prop(scene, "domeanimatic_color_a_value", text="", slider=True)

        # Key button
        split_opacity.operator("domeanimatic.keyframe_color_a", text="", icon='KEY_HLT')

        # ── Live strip info (debug only) ──────────────────────────────────────
        if bpy.data.window_managers[0].domeanimatic_show_labels:
            info = col.row(align=True)
            info.enabled = False
            info.label(text=f"{strip.name}", icon='SEQUENCE')
            info.label(text=f"α:{strip.blend_alpha:.3f}", icon='IMAGE_ALPHA')

    col.separator(factor=0.5)

    # ── COLOR B (SECOND MIX NODE) ─────────────────────────────────────────────
    col.label(text="Fade to White (2nd Mix Node + VSE strip)", icon='TRIA_RIGHT')
    strip_b = get_color_b_strip(scene)

    if strip_b is None:
        row = col.row()
        row.enabled = False
        row.label(text="Strip not found", icon='ERROR')
    else:
        # ── Single ROW: [Refresh] [Color↓] [Strip] [Opacity━━━━━━━━━━━] [Key] ────
        row = col.row(align=True)
        row.operator("domeanimatic.refresh_color_b", text="", icon='FILE_REFRESH')

        # Color (narrower: 8% of row)
        split_color = row.split(factor=0.08, align=True)
        split_color.prop(scene, "domeanimatic_color_b_color", text="")

        # Strip (normal: ~12% of remaining)
        split_strip = split_color.split(factor=0.13, align=True)
        split_strip.prop(scene, "domeanimatic_color_b_strip_name", text="")

        # Opacity (stretched: ~91% of remaining to fill space)
        split_opacity = split_strip.split(factor=0.91, align=True)
        split_opacity.prop(scene, "domeanimatic_color_b_value", text="", slider=True)

        # Key button
        split_opacity.operator("domeanimatic.keyframe_color_b", text="", icon='KEY_HLT')

        # ── Live color B strip info (debug only) ───────────────────────────────
        if bpy.data.window_managers[0].domeanimatic_show_labels:
            info = col.row(align=True)
            info.enabled = False
            info.label(text=f"{strip_b.name}", icon='SEQUENCE')
            info.label(text=f"α:{strip_b.blend_alpha:.3f}", icon='IMAGE_ALPHA')


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_keyframe_color_a,
    DOMEANIMATIC_OT_keyframe_color_b,
    DOMEANIMATIC_OT_refresh_color_a,
    DOMEANIMATIC_OT_refresh_color_b,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if color_sync_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(color_sync_handler)


def unregister():
    if color_sync_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(color_sync_handler)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
