"""
fix_merged_cast.py

Repairs the "all materials share one broken empty-string texture hash" bug
produced by ModelMerger.exe when merging .cast models (Cast support added
by echo000's fork). The bug: LoadCastModel() only copies the material Name,
never resolves/copies the actual texture (albedo/normal/extra0/extra1) file
references, so every material ends up with an FNV1a64("") hash and an
empty path.

This script rebuilds the correct 'file' nodes and material texture
properties by pulling the real texture paths from the original source
.cast files (matched by material name), and writes a corrected .cast file.

Usage:
    python fix_merged_cast.py <merged.cast> <source1.cast> [<source2.cast> ...] -o <output.cast>
"""
import argparse
import sys
from cast_parser import load_cast, walk, save_cast, make_string_prop, make_int64_prop, fnv1a64, CastNode


def build_material_texture_map(path):
    """Returns {material_name: {slot_property_name: real_path}} for a source cast file."""
    roots = load_cast(path)
    file_by_hash = {}
    for r in roots:
        for _, n in walk(r, filter_types={'file'}):
            p = n.properties.get('p')
            if p and p.data:
                file_by_hash[n.hash] = p.data

    mat_map = {}
    for r in roots:
        for _, m in walk(r, filter_types={'matl'}):
            name = m.properties['n'].data
            slots = {}
            for pname, prop in m.properties.items():
                if pname in ('n', 't'):
                    continue
                h = prop.data
                if h in file_by_hash:
                    slots[pname] = file_by_hash[h]
            mat_map[name] = slots
    return mat_map


def fix_merged_file(merged_path, source_paths, output_path):
    # 1. Build combined material -> {slot: path} map from all source files
    combined_map = {}
    for sp in source_paths:
        m = build_material_texture_map(sp)
        for name, slots in m.items():
            if name not in combined_map:
                combined_map[name] = slots
            else:
                combined_map[name].update(slots)

    print(f"Loaded texture data for {len(combined_map)} materials from {len(source_paths)} source file(s).")

    # 2. Load the merged (broken) file
    roots = load_cast(merged_path)

    path_to_hash = {}   # dedupe identical texture paths -> single hash/file node
    hash_to_filenode = {}
    fixed_count = 0
    missing = []

    for r in roots:
        # Find the 'modl' node(s)
        for _, modl in walk(r, filter_types={'modl'}):
            for _, mat in walk(modl, filter_types={'matl'}):
                name = mat.properties['n'].data
                slots = combined_map.get(name)
                if not slots:
                    missing.append(name)
                    continue

                # Drop all old (broken) file-node children and texture properties,
                # keep 'n' and 't' properties intact
                mat.children = [c for c in mat.children if c.identifier != 'file']
                mat.properties = {k: v for k, v in mat.properties.items() if k in ('n', 't')}

                for slot_name, real_path in slots.items():
                    if real_path in path_to_hash:
                        h = path_to_hash[real_path]
                    else:
                        h = fnv1a64(real_path)
                        # avoid accidental collision with existing hash
                        while h in hash_to_filenode:
                            h = (h + 1) % (2**64)
                        path_to_hash[real_path] = h

                        file_node = CastNode('file', h)
                        file_node.properties['p'] = make_string_prop('p', real_path)
                        hash_to_filenode[h] = file_node

                    # file nodes are children of the matl node (matching original Cast convention)
                    mat.children.append(hash_to_filenode[h])
                    mat.properties[slot_name] = make_int64_prop(slot_name, h)

                fixed_count += 1

    save_cast(output_path, roots)

    print(f"Fixed {fixed_count} materials.")
    print(f"Wrote {len(hash_to_filenode)} correct file/texture nodes.")
    if missing:
        print(f"WARNING: no source texture data found for {len(missing)} material(s): {missing}")
    print(f"Saved repaired file to: {output_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Repair broken textures in a ModelMerger-merged .cast file")
    parser.add_argument('merged', help="Path to the broken merged .cast file")
    parser.add_argument('sources', nargs='+', help="Path(s) to the original source .cast files")
    parser.add_argument('-o', '--output', required=True, help="Output path for the repaired .cast file")
    args = parser.parse_args()

    fix_merged_file(args.merged, args.sources, args.output)
