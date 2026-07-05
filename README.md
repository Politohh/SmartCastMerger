# SmartCastMerger

Drag-and-drop `.cast` merger that doesn't break your materials.

A thin wrapper around [Scobalula/ModelMerger](https://github.com/Scobalula/ModelMerger) (as extended with Cast support by [echo000/ModelMerger](https://github.com/echo000/ModelMerger)) that automatically repairs a material/texture bug introduced when merging `.cast` models, so the merged output imports into Unreal Engine with working textures and auto-shading — no manual re-import workaround needed.

---

## The problem

When merging two Call of Duty `.cast` models (e.g. a body + a head) with `ModelMerger.exe`, the resulting merged `.cast` file loads fine geometrically (bones, meshes, skeleton are all correctly combined), but **every material's textures are broken**. Importing the merged file into Unreal Engine via [o-Astral-o/UECast](https://github.com/o-Astral-o/UECast) produces materials with no textures assigned — auto-shading falls back to default/placeholder maps (black diffuse, flat normal, etc.) on every single material, regardless of which source model it came from.

The usual workaround was to re-import the original (unmerged) body and head `.cast` files separately afterward, just to let their materials "override" the broken ones and restore textures. That works, but it defeats half the point of merging in the first place, and it's an annoying manual step every time.

## Root cause

Traced by disassembling the .NET IL of `PhilLibX.dll` and `ModelMerger.exe`, and cross-referencing against the [echo000/ModelMerger](https://github.com/echo000/ModelMerger) source (which added `.cast` support on top of the original SEModel-only tool):

1. **`LoadCastModel()` in `Program.cs` only copies the material name:**

   ```csharp
   foreach (var material in Model.Materials())
   {
       var mat = new Model.Material(material.Name());
       model.Materials.Add(mat);
   }
   ```

   It never reads the material's texture slots (`albedo`, `normal`, `extra0`, `extra1`, etc.) or resolves them to actual file paths. `Model.Material`'s internal `Images` dictionary — the thing `PhilLibX.dll`'s export code (`Model.ProcessTexture`) reads from when writing the merged `.cast` back out — is left completely empty.

2. **At export time, `ProcessTexture` computes a texture hash from whatever path it finds** (or doesn't find) in `Images`:

   ```csharp
   string path = material.GetImage("DiffuseMap"); // empty, since Images was never populated
   ulong hash = FNV1a.Calculate64(path, FNV1a.OffsetBasis64);
   ```

   `FNV1a64("")` is mathematically just the offset basis itself, unchanged: `14695981039346656037`. Since every material hits this same empty-string case, **every texture slot on every material ends up pointing at the exact same hash, with an empty path** — confirmed by parsing the merged `.cast`'s binary `file` nodes directly and finding this exact value repeated everywhere `p` (path) was blank.

This is a load-side bug, not a merge-logic bug — the actual material-list merging (`if not already present, add`) is fine. It's specifically the Cast material loader that never got wired up to populate texture data, unlike whatever loads SEModel-side data (which never had it either, incidentally — same root issue, just never surfaced there).

## The fix

`fix_merged_cast.py` (built on a small custom `.cast` binary reader/writer, `cast_parser.py`, since no Python library exists for the format):

1. Parses the **original, unmerged** source `.cast` files (body, head, ...) and builds a map of `material name → {texture slot: real file path}`, resolved directly from each source file's own valid `file` node hash → path table.
2. Parses the merged (broken) `.cast` output from `ModelMerger.exe`.
3. For each material in the merged file, matches it back to its original by name, drops the broken texture properties/hash, and rebuilds correct `file` nodes with fresh, deterministic hashes (`FNV1a64` of the real path) and the actual texture path.
4. **Important structural detail:** `file` nodes must be re-attached as children of their owning `matl` node (matching the original Cast convention used by every other exporter) — not as children of the parent `modl` node. Attaching them in the wrong place produces a `.cast` that still parses fine and still has "correct" hash values, but is invisible to importers that only traverse `file` nodes scoped under each material, which is exactly what caused a first attempt at this fix to still fail silently in Unreal (materials with correct hashes, still zero textures imported).
5. Writes out a repaired `.cast` file, ready to import directly.

## The automation

`automerge.py` + `AutoMerge.bat` (or a compiled `AutoMerge.exe` via PyInstaller) chain the whole thing into a single drag-and-drop step:

1. Drop your source `.cast` files (body, head, ...) onto `AutoMerge.bat`.
2. It runs `ModelMerger.exe` on them (auto-answering its "press Enter to exit" prompt so it doesn't hang waiting for input).
3. It auto-detects whichever `.cast` file `ModelMerger.exe` just produced.
4. It runs the texture repair from step above, using your original dropped files as the source of truth.
5. Out comes `<name>_MERGED_FIXED.cast`, ready to import into Unreal with working materials and auto-shading — no separate re-import step required.

`ModelMerger.exe`'s location is auto-detected on first run (checked next to the tool, in the parent folder, and in `Documents`/`Downloads`) and cached in `automerge_config.ini`, so nothing needs to be hardcoded or recompiled if your setup differs.

## Usage

```
AutoMerge.bat body.cast head.cast
```
(or just drag both files onto it)

First run only: if `ModelMerger.exe` can't be found automatically, you'll be asked once for its path.

## Building a standalone .exe

```
pip install pyinstaller
python -m PyInstaller --onefile --console --icon=AutoMerge.ico --name AutoMerge automerge.py
```

## Known limitations

- Materials are matched between the merged file and the source files **by exact name**. If a source model's material name changes between files, it won't be matched and will be left as-is (a warning is printed listing anything that couldn't be repaired).
- This only repairs material/texture references. It doesn't re-validate or alter meshes, bones, or skeleton data — if `ModelMerger.exe` has other bugs unrelated to textures, this tool won't catch them.
- The `extra0`/`extra1` → gloss/specular slot convention is inferred from observed CoD exporter output, not from a formal spec; verify it matches your exporter if you rely on those specific slots.

## Credits

- [Scobalula](https://github.com/Scobalula) — original `ModelMerger` and `PhilLibX`.
- [echo000](https://github.com/echo000) — fork of `ModelMerger` adding `.cast` support.
- [o-Astral-o](https://github.com/o-Astral-o) — `UECast`, the Unreal Engine `.cast` importer and auto-shading plugin this tool's output is designed to work with.
