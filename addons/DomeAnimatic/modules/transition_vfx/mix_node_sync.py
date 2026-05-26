"""
mix_node_sync.py — Mix node helpers and frame-change handler for transition_vfx.

Reads VSE color strip blend_alpha each frame and drives the two Mix nodes in
the target material's node tree (Factor + B-socket color).
Ported from fade_in_fade_out.py.
"""

import bpy
from bpy.app.handlers import persistent

from ... import vse_helpers
from ...global_scene_shared_props import gp, sp


# ── Strip finders ─────────────────────────────────────────────────────────────

def get_color_a_strip(scene):
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return None
    return dome_scene.sequence_editor.strips_all.get(sp(scene).color_a_strip_name)


def get_color_b_strip(scene):
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return None
    return dome_scene.sequence_editor.strips_all.get(sp(scene).color_b_strip_name)


# ── Mix node push helpers ─────────────────────────────────────────────────────

def _get_mix_nodes(scene):
    """Return list of Mix-type nodes from the scene's target material."""
    s   = sp(scene)
    mat = s.target_material
    if mat is None or not mat.use_nodes:
        return []
    return [n for n in mat.node_tree.nodes if n.type in ('MIX_RGB', 'MIX')]


def _set_factor(node, value: float) -> bool:
    try:
        node.inputs['Factor'].default_value = value
        return True
    except (KeyError, AttributeError):
        try:
            node.inputs[0].default_value = value
            return True
        except (IndexError, AttributeError):
            return False


def _set_b_color(node, color) -> bool:
    try:
        node.inputs['B'].default_value = (*color, 1.0)
        return True
    except (KeyError, AttributeError):
        try:
            node.inputs[2].default_value = (*color, 1.0)
            return True
        except (IndexError, AttributeError):
            return False


def push_color_a_to_mix(scene, value: float, color) -> bool:
    nodes = _get_mix_nodes(scene)
    if not nodes:
        return False
    _set_factor(nodes[0], value)
    _set_b_color(nodes[0], color)
    return True


def push_color_b_to_mix(scene, value: float, color) -> bool:
    nodes = _get_mix_nodes(scene)
    if len(nodes) < 2:
        return False
    _set_factor(nodes[1], value)
    _set_b_color(nodes[1], color)
    return True


# ── Frame-change handler ──────────────────────────────────────────────────────

@persistent
def color_sync_handler(scene, depsgraph=None):
    """
    frame_change_post — reads color strip blend_alpha from Dome Animatic VSE
    and drives Mix node Factor + B-socket in the target material.
    """
    try:
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return

        s = sp(dome_scene)

        strip_a = get_color_a_strip(dome_scene)
        if strip_a is not None:
            val_a = float(getattr(strip_a, 'blend_alpha', 0.0))
            if s.color_a_value != val_a:
                s.color_a_value = val_a
            color_a = s.color_a_color[:3]
            if hasattr(strip_a, 'color'):
                strip_a.color = color_a
            push_color_a_to_mix(dome_scene, val_a, color_a)

        strip_b = get_color_b_strip(dome_scene)
        if strip_b is not None:
            val_b = float(getattr(strip_b, 'blend_alpha', 0.0))
            if s.color_b_value != val_b:
                s.color_b_value = val_b
            color_b = s.color_b_color[:3]
            if hasattr(strip_b, 'color'):
                strip_b.color = color_b
            push_color_b_to_mix(dome_scene, val_b, color_b)

    except Exception as e:
        vse_helpers.log(f"[TransitionVFX] color_sync_handler error: {e}")


def register() -> None:
    if color_sync_handler not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(color_sync_handler)


def unregister() -> None:
    if color_sync_handler in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(color_sync_handler)
