from . import mix_node_sync, fade_color_ops, ui


def register():
    mix_node_sync.register()
    fade_color_ops.register()
    ui.register()


def unregister():
    ui.unregister()
    fade_color_ops.unregister()
    mix_node_sync.unregister()
