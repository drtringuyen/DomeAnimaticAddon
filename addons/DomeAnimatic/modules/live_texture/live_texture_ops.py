"""
live_texture_ops.py — Operators for the live_texture module.

Covers:
  - Texture datablock creation / resize  (was prepare_live_dome_texture.py)
  - Material relink + status helpers     (was manage_live_dome_preview.py)
  - Sync mode toggle, start/stop        (was synch_VSE_to_LiveDomePreview.py)
  - Link Cel Nodes to material          (was synch_VSE_to_LiveDomePreview.py)
  - Debug node sockets                  (was synch_VSE_to_LiveDomePreview.py)
"""

import bpy
from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp, sp
from . import vse_sync


# ── Material link helpers ──────────────────────────────────────────────────────

def _find_live_texture_node(mat):
    if mat is None or not mat.use_nodes:
        return None
    live_img = cel_store.get_live_image()
    if live_img is None:
        return None
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image == live_img:
            return node
    return None


def get_link_status() -> dict:
    """Return status dict for display in the panel."""
    live_img = cel_store.get_live_image()
    mat      = sp().target_material
    tex_node = _find_live_texture_node(mat) if mat else None

    node_image_name = None
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                node_image_name = node.image.name if node.image else "Empty"
                break

    return {
        "live_exists":     live_img is not None,
        "live_name":       cel_store.BAKED_LAYER.datablock_name,
        "mat_name":        mat.name if mat else None,
        "mat_exists":      mat is not None,
        "node_linked":     tex_node is not None,
        "node_image_name": node_image_name,
    }


def _relink_live_texture_to_material():
    """Point an Image Texture node in the target material at LiveDomePreview.
    Returns (success, message)."""
    live_img = cel_store.get_live_image()
    if live_img is None:
        return False, "LiveDomePreview not found."

    mat = sp().target_material
    if mat is None:
        return False, "No target material set."
    if not mat.use_nodes:
        return False, f"Material '{mat.name}' has no node tree."

    nodes    = mat.node_tree.nodes
    tex_node = _find_live_texture_node(mat)

    if tex_node is None:
        existing = [n for n in nodes if n.type == 'TEX_IMAGE']
        if existing:
            tex_node = existing[0]
        else:
            return False, "No Image Texture node found. Please add one manually."

    tex_node.image = live_img
    msg = f"Updated '{mat.name}' to use {live_img.name}."
    vse_helpers.log(f"[LiveTexture] {msg}")
    return True, msg


# ── Operators ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_live_texture_prepare(bpy.types.Operator):
    bl_idname      = "domeanimatic.live_texture_prepare"
    bl_label       = "Prepare Live Dome Texture"
    bl_description = "Create or resize LiveDomePreview and auto-link cel nodes"

    def execute(self, context):
        g      = gp(context)
        s      = sp(context.scene)
        width  = max(1, int(s.tex_width  * s.tex_scale))
        height = max(1, int(s.tex_height * s.tex_scale))

        name = cel_store.BAKED_LAYER.datablock_name
        if name in bpy.data.images:
            img = bpy.data.images[name]
            if img.size[0] != width or img.size[1] != height:
                img.scale(width, height)
                self.report({'INFO'}, f"'{name}' resized to {width}x{height}.")
                vse_helpers.log(f"[LiveTexture] Resized {name} to {width}x{height}")
            else:
                self.report({'INFO'}, f"'{name}' already {width}x{height} — skipping.")
        else:
            img = bpy.data.images.new(name, width=width, height=height,
                                      alpha=False, float_buffer=False)
            img.colorspace_settings.name = 'sRGB'
            img.use_fake_user = True
            self.report({'INFO'}, f"'{name}' created at {width}x{height}.")
            vse_helpers.log(f"[LiveTexture] Created {name} at {width}x{height}")

        self._try_autolink(s)
        return {'FINISHED'}

    def _try_autolink(self, s):
        mat = s.target_material
        if mat is None:
            for candidate in ("Dome_Animatic", "Dome Animatic", "DomeAnimatic"):
                mat = bpy.data.materials.get(candidate)
                if mat:
                    s.target_material = mat
                    vse_helpers.log(f"[LiveTexture] Auto-found material: '{mat.name}'")
                    break
        if mat is None or not mat.use_nodes:
            return

        nodes = mat.node_tree.nodes

        live_img = cel_store.get_live_image()
        if live_img:
            node = nodes.get("Image Texture")
            if node and node.type == 'TEX_IMAGE':
                node.image = live_img

        POSITIONAL = [
            ("Image Texture.001", 'BG',    'bg'),
            ("Image Texture.002", 'CEL_A', 'cel_a'),
            ("Image Texture.003", 'CEL_B', 'cel_b'),
        ]
        for node_name, slot_id, prop_prefix in POSITIONAL:
            node = nodes.get(node_name)
            if node and node.type == 'TEX_IMAGE':
                cel_img = cel_store.get_or_create_cel_image(slot_id)
                node.image = cel_img
                setattr(s, f"{prop_prefix}_mat_image", cel_img)
                vse_helpers.log(f"[LiveTexture] Linked '{node_name}' → '{cel_img.name}'")


class DOMEANIMATIC_OT_live_texture_reload(bpy.types.Operator):
    bl_idname      = "domeanimatic.live_texture_reload"
    bl_label       = "Reload LiveDomePreview"
    bl_description = "Reload LiveDomePreview from disk and relink to material"

    def execute(self, context):
        live_img = cel_store.get_live_image()
        if live_img is None:
            self.report({'ERROR'}, "LiveDomePreview not found. Run Prepare first.")
            return {'CANCELLED'}

        if live_img.source == 'FILE' and live_img.filepath:
            live_img.reload()

        success, msg = _relink_live_texture_to_material()
        self.report({'INFO'} if success else {'WARNING'}, msg)
        return {'FINISHED'}


class DOMEANIMATIC_OT_set_synch_mode(bpy.types.Operator):
    bl_idname = "domeanimatic.set_synch_mode"
    bl_label  = "Set Sync Mode"

    mode: bpy.props.StringProperty()  # 'BAKED' | 'CEL_LAYERS' | 'OFF'

    def execute(self, context):
        s = sp(context.scene)
        s.synch_mode = self.mode

        socket = 'Cels' if self.mode == 'CEL_LAYERS' else 'Baked'
        _set_menu_switch(s, socket)
        vse_sync._apply_track_muting_by_mode(self.mode)
        return {'FINISHED'}


class DOMEANIMATIC_OT_live_texture_start_synch(bpy.types.Operator):
    bl_idname      = "domeanimatic.live_texture_start_synch"
    bl_label       = "Start Synch"
    bl_description = "Start VSE → texture sync in the selected mode"

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None or not dome_scene.sequence_editor:
            self.report({'ERROR'}, "No Sequence Editor in 'Dome Animatic'.")
            return {'CANCELLED'}

        vse_sync.start_live_sync()
        vse_sync.live_texture_sync_handler(dome_scene)
        s = sp(context.scene)
        s.synch_active = True

        socket = 'Cels' if s.synch_mode == 'CEL_LAYERS' else 'Baked'
        _set_menu_switch(s, socket)

        self.report({'INFO'}, f"VSE sync started — mode: {s.synch_mode}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_live_texture_stop_synch(bpy.types.Operator):
    bl_idname      = "domeanimatic.live_texture_stop_synch"
    bl_label       = "Stop Synch"
    bl_description = "Stop VSE → texture sync"

    def execute(self, context):
        vse_sync.stop_live_sync()
        s = sp(context.scene)
        s.synch_active = False
        s.synch_mode   = 'OFF'
        _set_menu_switch(s, 'Baked')
        self.report({'INFO'}, "VSE sync stopped.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_link_cel_nodes(bpy.types.Operator):
    bl_idname      = "domeanimatic.link_cel_nodes"
    bl_label       = "Link Cel Nodes"
    bl_description = (
        "Assign TransparentCel BG/Cel_A/Cel_B datablocks to Image Texture nodes "
        "named 'BG', 'Cel_A', 'Cel_B' in the target material"
    )

    def execute(self, context):
        s   = sp(context.scene)
        mat = s.target_material
        if mat is None:
            self.report({'ERROR'}, "No target material set.")
            return {'CANCELLED'}
        if not mat.use_nodes:
            self.report({'ERROR'}, f"Material '{mat.name}' has no node tree.")
            return {'CANCELLED'}

        nodes     = mat.node_tree.nodes
        tex_lower = {n.name.lower(): n for n in nodes if n.type == 'TEX_IMAGE'}

        NAMED = {
            'BG':    ('BG',    'bg'),
            'Cel_A': ('CEL_A', 'cel_a'),
            'Cel_B': ('CEL_B', 'cel_b'),
        }
        POSITIONAL = [
            ('Image Texture.001', 'BG',    'bg'),
            ('Image Texture.002', 'CEL_A', 'cel_a'),
            ('Image Texture.003', 'CEL_B', 'cel_b'),
        ]

        linked, missing = [], []

        for node_name, (slot_id, prop_prefix) in NAMED.items():
            node = nodes.get(node_name) or tex_lower.get(node_name.lower())
            if node and node.type == 'TEX_IMAGE':
                cel_img    = cel_store.get_or_create_cel_image(slot_id)
                node.image = cel_img
                setattr(s, f"{prop_prefix}_mat_image", cel_img)
                linked.append(node.name)
                vse_helpers.log(f"[LinkCelNodes] '{node.name}' → '{cel_img.name}'")
            else:
                missing.append(node_name)

        linked_slots = {NAMED[nm][0] for nm in NAMED if nm not in missing}

        for node_name, slot_id, prop_prefix in POSITIONAL:
            if slot_id in linked_slots:
                continue
            node = nodes.get(node_name)
            if node and node.type == 'TEX_IMAGE':
                cel_img    = cel_store.get_or_create_cel_image(slot_id)
                node.image = cel_img
                setattr(s, f"{prop_prefix}_mat_image", cel_img)
                linked.append(node.name)
                linked_slots.add(slot_id)
                missing = [m for m in missing if NAMED.get(m, ('', ''))[0] != slot_id]
                vse_helpers.log(f"[LinkCelNodes] Positional '{node.name}' → '{cel_img.name}'")

        if missing:
            self.report({'WARNING'}, f"Linked: {linked}. Missing: {missing}")
        else:
            self.report({'INFO'}, f"All cel nodes linked: {linked}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_debug_node_sockets(bpy.types.Operator):
    bl_idname      = "domeanimatic.debug_node_sockets"
    bl_label       = "Debug: Print Node Sockets"
    bl_description = "Print material node tree to console"

    def execute(self, context):
        mat = sp(context.scene).target_material
        if mat is None or not mat.use_nodes:
            self.report({'ERROR'}, "No material set or no node tree.")
            return {'CANCELLED'}
        print(f"\n{'='*60}")
        print(f"Material: '{mat.name}' — node tree:")
        for node in mat.node_tree.nodes:
            print(f"  NODE '{node.name}'  type={node.type}")
            for i, inp in enumerate(node.inputs):
                val = getattr(inp, 'default_value', '<no default>')
                print(f"    IN  [{i}] '{inp.name}'  type={inp.type}  val={val}")
            for i, out in enumerate(node.outputs):
                print(f"    OUT [{i}] '{out.name}'  type={out.type}")
        print(f"{'='*60}\n")
        self.report({'INFO'}, "Node info printed to console.")
        return {'FINISHED'}


# ── Internal helper ────────────────────────────────────────────────────────────

def _resolve_target_material(s):
    """Return target_material from scene props, auto-detecting and storing it when unset."""
    mat = s.target_material
    if mat is not None:
        return mat
    # try common names
    for name in ("Dome_Animatic", "Dome Animatic", "DomeAnimatic"):
        mat = bpy.data.materials.get(name)
        if mat:
            s.target_material = mat
            vse_helpers.log(f"[LiveTexture] Auto-detected material: '{mat.name}'")
            return mat
    # fall back: find any material with a Menu Switch node
    for mat in bpy.data.materials:
        if mat.use_nodes and mat.node_tree.nodes.get("Menu Switch"):
            s.target_material = mat
            vse_helpers.log(f"[LiveTexture] Auto-detected material via Menu Switch: '{mat.name}'")
            return mat
    return None


def _set_menu_switch(s, socket_name: str) -> None:
    mat = _resolve_target_material(s)
    if mat is None or not mat.use_nodes:
        return
    node = mat.node_tree.nodes.get("Menu Switch")
    if node is None:
        return
    try:
        node.inputs[0].default_value = socket_name
    except Exception as e:
        vse_helpers.log(f"[LiveTexture] Menu Switch error: {e}")


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [
    DOMEANIMATIC_OT_live_texture_prepare,
    DOMEANIMATIC_OT_live_texture_reload,
    DOMEANIMATIC_OT_set_synch_mode,
    DOMEANIMATIC_OT_live_texture_start_synch,
    DOMEANIMATIC_OT_live_texture_stop_synch,
    DOMEANIMATIC_OT_link_cel_nodes,
    DOMEANIMATIC_OT_debug_node_sockets,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
