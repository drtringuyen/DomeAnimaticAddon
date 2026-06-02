"""
cel_store.py — Single source of truth for the cel layer system.

Defines CelLayer data structure + lookup tables shared by live_texture and
painting_cel modules. Neither module imports from the other — both import here.

NOTE: User originally placed CEL_Baked on channel 4, but channel 4 is already
CEL_B. Corrected to channel 1 — the baked VSE track that actually feeds
LiveDomePreview in BAKED sync mode. BAKED_LAYER is kept separate from LAYERS
so it never conflicts in BY_CHANNEL lookups.
"""

from dataclasses import dataclass
from typing import Optional
import bpy

try:
    import numpy as np
except ImportError:
    np = None


@dataclass(frozen=True)
class CelLayer:
    slot_id:        str           # 'BG' | 'CEL_A' | 'CEL_B' | 'CEL_Baked'
    vse_channel:    Optional[int] # VSE channel number; None = no direct VSE strip
    datablock_name: str           # Blender Image datablock name — do NOT rename,
                                  # changing breaks existing .blend files
    filename_label: str           # suffix used in PNG filenames
    z_order:        int           # GPU draw order: lower = drawn first (bottom)


# ── Live painting layers (the three cel slots) ────────────────────────────────

LAYERS: list[CelLayer] = [
    CelLayer('BG',    2, 'TransparentCel_BG',    'BG',    0),
    CelLayer('CEL_A', 3, 'TransparentCel_Cel_A', 'Cel_A', 1),
    CelLayer('CEL_B', 4, 'TransparentCel_Cel_B', 'Cel_B', 2),
]

# ── Baked composite layer ─────────────────────────────────────────────────────
# LiveDomePreview is synced from VSE channel 1 in BAKED mode.
# Used as a single-image performance fallback instead of compositing 3 layers.
# z_order -1 = drawn below everything else; shown exclusively in BAKED mode.

BAKED_LAYER = CelLayer('CEL_Baked', 1, 'LiveDomePreview', 'Baked', -1)

# ── Fast lookup tables ────────────────────────────────────────────────────────

BY_CHANNEL: dict[int, CelLayer]  = {l.vse_channel: l for l in LAYERS}
BY_SLOT:    dict[str, CelLayer]  = {l.slot_id:     l for l in LAYERS}
BY_SLOT['CEL_Baked'] = BAKED_LAYER
DRAW_ORDER: list[CelLayer]       = sorted(LAYERS, key=lambda l: l.z_order)

# cel channel numbers as a set — used for fast membership tests in VSE handlers
CEL_CHANNELS: set[int] = set(BY_CHANNEL.keys())   # {2, 3, 4}


# ── Image datablock helpers ───────────────────────────────────────────────────

def get_or_create_cel_image(slot_id: str,
                            width:   int = 960,
                            height:  int = 590) -> bpy.types.Image:
    """Return the Image datablock for a cel slot, creating it if absent.

    New datablocks are zero-filled (fully transparent) so they don't occlude
    layers below before a file is loaded.
    CEL_Baked delegates to get_or_create_live_image() (alpha=False).
    """
    if slot_id == 'CEL_Baked':
        return get_or_create_live_image(width, height)
    layer = BY_SLOT[slot_id]
    img   = bpy.data.images.get(layer.datablock_name)
    if img is None:
        img               = bpy.data.images.new(layer.datablock_name,
                                                width=width, height=height,
                                                alpha=True, float_buffer=False)
        img.alpha_mode    = 'STRAIGHT'
        img.use_fake_user = True
        if np is not None:
            buf = np.zeros(width * height * 4, dtype=np.float32)
            img.pixels.foreach_set(buf)
            img.update()
    return img


def get_cel_image(slot_id: str) -> Optional[bpy.types.Image]:
    """Return existing Image datablock or None."""
    layer = BY_SLOT.get(slot_id)
    return bpy.data.images.get(layer.datablock_name) if layer else None


def get_or_create_live_image(width: int = 960,
                             height: int = 590) -> bpy.types.Image:
    """Return the LiveDomePreview datablock, creating it if absent."""
    name = BAKED_LAYER.datablock_name
    img  = bpy.data.images.get(name)
    if img is None:
        img               = bpy.data.images.new(name, width=width, height=height,
                                                alpha=False, float_buffer=False)
        img.use_fake_user = True
    return img


def get_live_image() -> Optional[bpy.types.Image]:
    """Return LiveDomePreview or None."""
    return bpy.data.images.get(BAKED_LAYER.datablock_name)
