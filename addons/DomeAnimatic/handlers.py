import bpy


# ─── Preview Image ────────────────────────────────────────────────────────────

def create_preview_image(width=1920, height=1080):
    existing = bpy.data.images.get("DomeLivePreview")
    if existing:
        return existing
    img = bpy.data.images.new(
        name="DomeLivePreview",
        width=width,
        height=height,
        alpha=False,
        float_buffer=False
    )
    img.use_fake_user = True
    print("DomeLivePreview: image created")
    return img


def ensure_preview_exists():
    try:
        img = bpy.data.images.get("DomeLivePreview")
        if not img:
            img = create_preview_image()
        return img
    except AttributeError:
        print("DomeLivePreview: bpy.data not ready yet, skipping")
        return None


# ─── VSE Frame Change ─────────────────────────────────────────────────────────

def load_filepath_to_preview(filepath):
    import os
    if not os.path.isfile(filepath):
        print(f"DomeLivePreview: file not found: {filepath}")
        return
    preview = ensure_preview_exists()
    if not preview:
        return
    try:
        tmp = bpy.data.images.load(filepath, check_existing=False)
        tmp.pixels  # force load
        if len(tmp.pixels) != len(preview.pixels):
            preview.scale(tmp.size[0], tmp.size[1])
        preview.pixels.foreach_set(tmp.pixels[:])
        preview.update()
        bpy.data.images.remove(tmp)
    except Exception as e:
        print(f"DomeLivePreview: error loading image: {e}")


@bpy.app.handlers.persistent
def on_frame_change(scene, depsgraph):
    try:
        if not scene.sequence_editor:
            return
        frame = scene.frame_current
        for strip in scene.sequence_editor.sequences_all:
            if strip.type != 'IMAGE':
                continue
            if strip.frame_final_start <= frame < strip.frame_final_end:
                offset = frame - strip.frame_final_start
                index = min(offset, len(strip.elements) - 1)
                filepath = bpy.path.abspath(
                    strip.directory + strip.elements[index].filename
                )
                load_filepath_to_preview(filepath)
                return
    except Exception as e:
        print(f"DomeLivePreview: on_frame_change error: {e}")


# ─── Render Capture ───────────────────────────────────────────────────────────

def capture_from_render(scene):
    try:
        render_result = bpy.data.images.get("Render Result")
        if not render_result:
            print("DomeLivePreview: no Render Result found")
            return
        preview = ensure_preview_exists()
        if not preview:
            return
        rw = scene.render.resolution_x
        rh = scene.render.resolution_y
        if preview.size[0] != rw or preview.size[1] != rh:
            preview.scale(rw, rh)
        preview.pixels.foreach_set(render_result.pixels[:])
        preview.update()
        print("DomeLivePreview: captured from render result")
    except Exception as e:
        print(f"DomeLivePreview: capture_from_render error: {e}")


@bpy.app.handlers.persistent
def on_render_complete(scene):
    capture_from_render(scene)


@bpy.app.handlers.persistent
def on_load_post(filepath, *args):
    ensure_preview_exists()
    print("DomeLivePreview: ready after file load")


# ─── Register / Unregister ────────────────────────────────────────────────────

def register():
    if on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_load_post)
    if on_frame_change not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(on_frame_change)
    if on_render_complete not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(on_render_complete)
    print("DomeLivePreview: handlers registered")


def unregister():
    if on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_load_post)
    if on_frame_change in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(on_frame_change)
    if on_render_complete in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(on_render_complete)
    print("DomeLivePreview: handlers unregistered")