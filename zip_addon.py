import shutil
import os
import zipfile

ADDON_NAME = "DomeAnimatic"
PROJECT_ROOT = os.path.dirname(__file__)
SRC_FOLDER = os.path.join(os.path.dirname(__file__), "addons", "DomeAnimatic")
OUTPUT_ZIP = os.path.join(PROJECT_ROOT, ADDON_NAME + ".zip")

EXCLUDE_DIRS = {"__pycache__", ".idea", ".git"}
EXCLUDE_EXTS = {".pyc", ".pyo"}

# Step 1 — Remove old zip if exists
if os.path.exists(OUTPUT_ZIP):
    os.remove(OUTPUT_ZIP)
    print("✓ Removed old zip")

# Step 2 — Walk entire source tree recursively
with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
    for dirpath, dirnames, filenames in os.walk(SRC_FOLDER):
        # Skip excluded directories in-place so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

        for filename in filenames:
            if os.path.splitext(filename)[1] in EXCLUDE_EXTS:
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, os.path.dirname(SRC_FOLDER))
            zf.write(full_path, arcname=rel_path)
            print(f"  + {rel_path}")

print(f"\n✓ Created: {OUTPUT_ZIP}")
print(f"\n🎉 Done! Install in Blender via:")
print("   Edit → Preferences → Add-ons → Install → pick DomeAnimatic.zip")
