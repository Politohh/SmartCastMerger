"""
automerge.py

Drag-and-drop replacement workflow for ModelMerger.exe.

Drop your body + head (+ any other) .cast files onto AutoMerge.bat.
This script will:
  1. Run ModelMerger.exe on the dropped files (the actual merge: bones, meshes, skeleton).
  2. Auto-detect the merged .cast file it produced.
  3. Run the texture/material repair (fix_merged_cast logic) on it, using the
     dropped files as the source of truth for texture paths.
  4. Save the final, ready-to-import file next to your source files as
     "<basename>_MERGED_FIXED.cast".

First run: it'll try to auto-detect ModelMerger.exe (same folder, parent folder,
Documents/Downloads); if it can't find it, it'll ask you once for the path and
remember it in automerge_config.ini next to this program.
"""
import os
import sys
import time
import subprocess
import configparser
from pathlib import Path


def get_app_dir():
    """Directory the exe (or script, if run unfrozen) lives in."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = get_app_dir()
CONFIG_PATH = APP_DIR / "automerge_config.ini"

sys.path.insert(0, str(APP_DIR))
from fix_merged_cast import fix_merged_file


def load_configured_path():
    if CONFIG_PATH.exists():
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_PATH)
        p = cfg.get("paths", "modelmerger_exe", fallback=None)
        if p and Path(p).exists():
            return Path(p)
    return None


def save_configured_path(path):
    cfg = configparser.ConfigParser()
    cfg["paths"] = {"modelmerger_exe": str(path)}
    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)


def auto_detect_modelmerger():
    """Look for ModelMerger.exe in a handful of likely spots before giving up."""
    candidates = [
        APP_DIR / "ModelMerger.exe",
        APP_DIR.parent / "ModelMerger.exe",
    ]
    for c in candidates:
        if c.exists():
            return c

    # Shallow search a few levels under common folders (fast, avoids scanning whole drives)
    search_roots = [APP_DIR, APP_DIR.parent, Path.home() / "Documents", Path.home() / "Downloads"]
    for root in search_roots:
        if not root.exists():
            continue
        try:
            for depth_glob in ("ModelMerger.exe", "*/ModelMerger.exe", "*/*/ModelMerger.exe"):
                for match in root.glob(depth_glob):
                    return match
        except OSError:
            continue
    return None


def get_modelmerger_exe():
    p = load_configured_path()
    if p:
        return p

    print("Looking for ModelMerger.exe...")
    p = auto_detect_modelmerger()
    if p:
        print(f"Found: {p}")
        save_configured_path(p)
        return p

    print("Couldn't find ModelMerger.exe automatically.")
    while True:
        answer = input("Paste the full path to ModelMerger.exe: ").strip().strip('"')
        if Path(answer).exists():
            save_configured_path(answer)
            return Path(answer)
        print("That path doesn't exist, try again.")


def find_cast_files_recent(search_dirs, since_time, exclude_paths):
    """Find .cast files modified after since_time, excluding the given paths."""
    exclude = {str(Path(p).resolve()) for p in exclude_paths}
    candidates = []
    for d in search_dirs:
        d = Path(d)
        if not d.exists():
            continue
        for f in d.rglob("*.cast"):
            try:
                if str(f.resolve()) in exclude:
                    continue
                if f.stat().st_mtime >= since_time:
                    candidates.append(f)
            except OSError:
                continue
    return candidates


def run_model_merger(input_files):
    exe_path = get_modelmerger_exe()
    if not exe_path or not exe_path.exists():
        print(f"ERROR: ModelMerger.exe not found at: {exe_path}")
        print(f"Delete {CONFIG_PATH.name} next to this program and run it again to re-detect.")
        sys.exit(1)

    start_time = time.time()

    print(f"Running ModelMerger.exe on {len(input_files)} file(s)...")
    result = subprocess.run(
        [str(exe_path)] + [str(f) for f in input_files],
        cwd=str(exe_path.parent),
        input="\n",          # auto-dismiss ModelMerger.exe's "Press Enter to exit" prompt
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(result.stdout)
    if result.returncode != 0:
        print("ModelMerger.exe stderr:", result.stderr)

    # Search likely output locations for the newly created merged file
    search_dirs = [
        exe_path.parent,                              # next to the exe
        exe_path.parent / "Merged Models",             # public-build default output folder
        Path(input_files[0]).resolve().parent,         # next to the source files
    ]

    candidates = find_cast_files_recent(search_dirs, start_time, input_files)

    if not candidates:
        print("ERROR: Could not find the merged .cast file ModelMerger.exe produced.")
        print("Check the folders it writes to and adjust automerge.py's search_dirs if needed.")
        sys.exit(1)

    # Pick the most recently modified candidate
    merged_file = max(candidates, key=lambda f: f.stat().st_mtime)
    print(f"Found merged output: {merged_file}")
    return merged_file


def main():
    input_files = sys.argv[1:]

    if len(input_files) < 2:
        print("Usage: drag and drop 2+ .cast files (e.g. body + head) onto AutoMerge.bat")
        time.sleep(4)
        sys.exit(1)

    for f in input_files:
        if not Path(f).exists():
            print(f"ERROR: file not found: {f}")
            sys.exit(1)

    merged_file = run_model_merger(input_files)

    first_source = Path(input_files[0])
    output_name = first_source.stem.replace("_LOD0", "") + "_MERGED_FIXED.cast"
    output_path = first_source.parent / output_name

    print("Repairing textures/materials on the merged file...")
    fix_merged_file(str(merged_file), [str(f) for f in input_files], str(output_path))

    print(f"\nDone! Ready-to-import file:\n  {output_path}")
    print("Closing in 3 seconds...")
    time.sleep(3)


if __name__ == "__main__":
    main()
