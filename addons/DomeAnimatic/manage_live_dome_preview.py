import bpy
from bpy.app.handlers import persistent
from . import utils

# ── Try both naming conventions as fallback only ──────────────────────────────
DOME_MATERIAL_NAMES = ["Dome_Animatic", "Dome Animatic", "DomeAnimatic"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_dome_material():
    """
    Return the target material — reads from WindowManager (global, never
    changes on scene switch) then falls back to known name variants.
    """
    try:
        mat = bpy.data.window_managers[0].domeanimatic_target_material
        if mat is not None:
            return mat
    except Exception:
        pass
    for name in DOME_MATERIAL_NAMES:
        mat = bpy.data.materials.get(name)
        if mat is not None:
            return mat
    return None


def get_dome_material_name():
    mat = get_dome_material()
    return mat.name if mat else None


def find_live_texture_node(mat):
    """
    Find the Image Texture node in a material that references LiveDomePreview.
    Returns the node or None.
    """
    if mat is None or not mat.use_nodes:
        return None
    live_img = utils.get_live_image()
    if live_img is None:
        return None
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image == live_img:
            return node
    return None


def get_status():
    """
    Return a dict describing the current link status for display in the panel.
    Keys: live_exists, mat_name, mat_exists, node_linked, node_image_name
    """
    live_img  = utils.get_live_image()
    mat       = get_dome_material()
    mat_name  = get_dome_material_name()
    tex_node  = find_live_texture_node(mat) if mat else None

    # What image does the tex node currently point to?
    node_image_name = None
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                node_image_name = node.image.name if node.image else "Empty"
                break

    return {
        "live_exists":      live_img is not None,
        "live_name":        utils.LIVE_TEXTURE_NAME,
        "mat_name":         mat_name,
        "mat_exists":       mat is not None,
        "node_linked":      tex_node is not None,
        "node_image_name":  node_image_name,
    }


def relink_live_texture_to_material():
    """
    Find an existing Image Texture node in the Dome Animatic material
    and point it to LiveDomePreview. Does NOT modify shader graph structure.
    Returns (success, message).
    """
    live_img = utils.get_live_image()
    if live_img is None:
        msg = "LiveDomePreview not found."
        utils.log(f"[ManageLive] {msg}")
        return False, msg

    mat = get_dome_material()
    if mat is None:
        msg = f"Material not found. Tried: {', '.join(DOME_MATERIAL_NAMES)}"
        utils.log(f"[ManageLive] {msg}")
        return False, msg

    if not mat.use_nodes:
        msg = "Material has no node graph. Please enable 'Use Nodes' first."
        utils.log(f"[ManageLive] {msg}")
        return False, msg

    nodes = mat.node_tree.nodes

    # Find existing tex node pointing to live image
    tex_node = find_live_texture_node(mat)

    # If no node pointing to LiveDomePreview, find ANY Image Texture node
    if tex_node is None:
        existing_tex_nodes = [n for n in nodes if n.type == 'TEX_IMAGE']
        if existing_tex_nodes:
            tex_node = existing_tex_nodes[0]
        else:
            msg = "No Image Texture node found in material. Please add one manually."
            utils.log(f"[ManageLive] {msg}")
            return False, msg

    # ONLY change the image — never modify shader graph structure
    tex_node.image = live_img

    msg = f"Updated '{mat.name}' to use LiveDomePreview (shader structure preserved)."
    utils.log(f"[ManageLive] {msg}")
    return True, msg


def is_material_linked():
    mat = get_dome_material()
    return find_live_texture_node(mat) is not None


# ── Persistent handler ────────────────────────────────────────────────────────

@persistent
def relink_on_scene_change(scene, depsgraph=None):
    """Silently relink material only when on Dome Animatic scene."""
    try:
        # Only relink when the active scene is Dome Animatic
        if bpy.context.scene.name != "Dome Animatic":
            return
        if not is_material_linked():
            relink_live_texture_to_material()
    except Exception as e:
        utils.log(f"[ManageLive] relink_on_scene_change error: {e}")


# ── Operator ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_reload_live_dome_texture(bpy.types.Operator):
    bl_idname = "domeanimatic.reload_live_dome_texture"
    bl_label = "Reload LiveDomePreview"
    bl_description = "Reload LiveDomePreview and relink it to the Dome Animatic material"

    def execute(self, context):
        live_img = utils.get_live_image()
        if live_img is None:
            self.report({'ERROR'}, "LiveDomePreview not found. Run Prepare Live Dome Texture first.")
            return {'CANCELLED'}

        # Reload from disk if file-based
        if live_img.source == 'FILE' and live_img.filepath:
            live_img.reload()
            utils.log("[ManageLive] LiveDomePreview reloaded from disk.")

        # Relink material
        success, msg = relink_live_texture_to_material()
        if success:
            self.report({'INFO'}, msg)
        else:
            self.report({'WARNING'}, msg)

        return {'FINISHED'}


# ── UI draw (called by prepare_live_dome_texture.draw_ui) ─────────────────────

def draw_status(box, context):
    """Draw status labels only — material slot is in Synch VSE row."""
    status  = get_status()
    verbose = utils.show_labels(context)

    if verbose:
        col = box.column(align=True)
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
                img_info = f"→ {status['node_image_name']}" if status["node_image_name"] else "→ none"
                col.label(text=f"Linked: NO  {img_info}", icon='ERROR')
        else:
            col.label(text="No material set — pick one in Synch VSE row", icon='ERROR')

        box.separator(factor=0.3)


# ── Register ──────────────────────────────────────────────────────────────────

classes = [DOMEANIMATIC_OT_reload_live_dome_texture]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
