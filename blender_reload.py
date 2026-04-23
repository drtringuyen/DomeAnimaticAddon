import importlib
import sys
import bpy

# Copy this to Blender's text editor and RUN to reload script every time

# Step 1 — Remove all DomeAnimatic modules from cache
mods_to_remove = [key for key in sys.modules if "DomeAnimatic" in key]
for mod in mods_to_remove:
    del sys.modules[mod]
    print(f"✓ Removed from cache: {mod}")

# Step 2 — Disable addon
try:
    bpy.ops.preferences.addon_disable(module="DomeAnimatic")
    print("✓ Disabled")
except:
    pass

# Step 3 — Re-enable addon (forces fresh import)
bpy.ops.preferences.addon_enable(module="DomeAnimatic")
print("✓ Enabled")

print("\n✓ DomeAnimatic reloaded successfully!")