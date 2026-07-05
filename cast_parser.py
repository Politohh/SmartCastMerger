import struct

class CastProperty:
    def __init__(self, identifier, name, data):
        self.identifier = identifier
        self.name = name
        self.data = data
    def __repr__(self):
        return f"<Prop {self.name}:{self.identifier}={self.data}>"

class CastNode:
    def __init__(self, identifier, hash_):
        self.identifier = identifier
        self.hash = hash_
        self.properties = {}
        self.children = []
        self.parent = None
    def child_of_type(self, t):
        return [c for c in self.children if c.identifier == t]
    def __repr__(self):
        return f"<Node {self.identifier} hash={self.hash} props={list(self.properties.keys())} children={len(self.children)}>"

TYPE_SIZES = {
    'b\x00': 1, 'h\x00': 2, 'i\x00': 4, 'l\x00': 8,
    'f\x00': 4, 'd\x00': 8,
    '2v': 8, '3v': 12, '4v': 16,
    's\x00': None,
}

def read_property(f):
    identifier = f.read(2).decode('ascii')
    name_size = struct.unpack('<H', f.read(2))[0]
    array_length = struct.unpack('<I', f.read(4))[0]
    name = f.read(name_size).decode('utf-8')
    if identifier == 's\x00':
        # array_length = number of strings (always 1); string itself is null-terminated
        chars = bytearray()
        while True:
            b = f.read(1)
            if b == b'\x00' or b == b'':
                break
            chars += b
        data = chars.decode('utf-8', errors='replace')
    else:
        size = TYPE_SIZES[identifier]
        fmt_map = {'b\x00':'B','h\x00':'H','i\x00':'I','l\x00':'Q','f\x00':'f','d\x00':'d'}
        values = []
        for _ in range(array_length):
            if identifier in ('2v','3v','4v'):
                n = int(identifier[0])
                v = struct.unpack('<%df'%n, f.read(4*n))
                values.append(v)
            else:
                v = struct.unpack('<'+fmt_map[identifier], f.read(size))[0]
                values.append(v)
        data = values if array_length != 1 else values[0]
    return CastProperty(identifier, name, data)

def read_node(f):
    identifier = f.read(4).decode('ascii')
    node_size = struct.unpack('<I', f.read(4))[0]
    node_hash = struct.unpack('<Q', f.read(8))[0]
    prop_count = struct.unpack('<I', f.read(4))[0]
    child_count = struct.unpack('<I', f.read(4))[0]
    node = CastNode(identifier, node_hash)
    for _ in range(prop_count):
        p = read_property(f)
        node.properties[p.name] = p
    for _ in range(child_count):
        c = read_node(f)
        c.parent = node
        node.children.append(c)
    return node

def load_cast(path):
    with open(path, 'rb') as f:
        magic = f.read(4)
        assert magic == b'cast'
        version = struct.unpack('<I', f.read(4))[0]
        root_nodes = struct.unpack('<I', f.read(4))[0]
        flags = struct.unpack('<I', f.read(4))[0]
        roots = []
        for _ in range(root_nodes):
            roots.append(read_node(f))
        return roots

def write_property(prop):
    identifier = prop.identifier
    name_bytes = prop.name.encode('utf-8')
    out = bytearray()
    out += identifier.encode('ascii')
    out += struct.pack('<H', len(name_bytes))
    if identifier == 's\x00':
        out += struct.pack('<I', 1)  # array_length = 1 string
        out += name_bytes
        out += prop.data.encode('utf-8') + b'\x00'
    else:
        fmt_map = {'b\x00':'B','h\x00':'H','i\x00':'I','l\x00':'Q','f\x00':'f','d\x00':'d'}
        data = prop.data
        # normalize to list
        if identifier in ('2v','3v','4v'):
            values = data if isinstance(data, list) else [data]
            out += struct.pack('<I', len(values))
            out += name_bytes
            n = int(identifier[0])
            for v in values:
                out += struct.pack('<%df' % n, *v)
        else:
            values = data if isinstance(data, list) else [data]
            out += struct.pack('<I', len(values))
            out += name_bytes
            for v in values:
                out += struct.pack('<' + fmt_map[identifier], v)
    return bytes(out)

def write_node(node):
    body = bytearray()
    prop_bytes_list = [write_property(p) for p in node.properties.values()]
    child_bytes_list = [write_node(c) for c in node.children]

    body += node.identifier.encode('ascii')
    # placeholder for size, filled after we know total length
    size_placeholder_pos = len(body)
    body += b'\x00\x00\x00\x00'
    body += struct.pack('<Q', node.hash)
    body += struct.pack('<I', len(prop_bytes_list))
    body += struct.pack('<I', len(child_bytes_list))
    for pb in prop_bytes_list:
        body += pb
    for cb in child_bytes_list:
        body += cb

    node_size = len(body)  # includes id+size+hash+propcount+childcount+props+children
    body[size_placeholder_pos:size_placeholder_pos+4] = struct.pack('<I', node_size)
    return bytes(body)

def save_cast(path, roots, version=1, flags=0):
    with open(path, 'wb') as f:
        f.write(b'cast')
        f.write(struct.pack('<I', version))
        f.write(struct.pack('<I', len(roots)))
        f.write(struct.pack('<I', flags))
        for r in roots:
            f.write(write_node(r))

def make_string_prop(name, value):
    return CastProperty('s\x00', name, value)

def make_int64_prop(name, value):
    return CastProperty('l\x00', name, value)

def fnv1a64(s):
    h = 14695981039346656037
    prime = 1099511628211
    for b in s.encode('utf-8'):
        h ^= b
        h = (h * prime) % (2**64)
    return h

def walk(node, depth=0, filter_types=None):
    results = []
    if filter_types is None or node.identifier in filter_types:
        results.append((depth, node))
    for c in node.children:
        results.extend(walk(c, depth+1, filter_types))
    return results
