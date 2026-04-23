import bpy


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    ts          = context.tool_settings
    image_paint = ts.image_paint

    if image_paint is None:
        return

    col = box.column(align=True)

    # Palette picker — lets user create or assign a palette
    col.template_ID(image_paint, "palette", new="palette.new")

    # Palette swatches — only drawn when a palette is assigned
    if image_paint.palette:
        col.template_palette(image_paint, "palette", color=True)


# ── Register ──────────────────────────────────────────────────────────────────

def register():
    pass

def unregister():
    pass
