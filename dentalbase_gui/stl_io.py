"""Binary-STL helpers for the GUI. Pure Python: no Qt, no backend imports."""
import os
import struct

HEADER = 80
TRI_BYTES = 50


def check_binary_stl(path):
    """Return (ok, message). A file is accepted only if it is a *binary* STL: 84-byte header+count and exactly
    count*50 bytes of triangles. (ASCII STLs, truncated files and other formats are rejected.)"""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            head = f.read(HEADER + 4)
        if size < HEADER + 4:
            if head[:5].lower() == b'solid':
                return False, 'looks like an ASCII STL (only binary STL is supported)'
            return False, 'file too small to be a binary STL'
        n = struct.unpack('<I', head[HEADER:HEADER + 4])[0]
        if n == 0:
            return False, 'STL contains no triangles'
        if size != HEADER + 4 + n * TRI_BYTES:
            if head[:5].lower() == b'solid':
                return False, 'looks like an ASCII STL (only binary STL is supported)'
            return False, 'not a valid binary STL (size does not match triangle count)'
        return True, f'{n:,} triangles'
    except OSError as e:
        return False, f'cannot read file: {e}'


def is_stl_name(path):
    return os.path.splitext(path)[1].lower() == '.stl'


def output_path(path):
    """scan.stl -> scan_output.stl in the same directory."""
    root, _ = os.path.splitext(path)
    return root + '_output.stl'


def guess_role(path):
    """'upper' / 'lower' / 'single' from the file name."""
    n = os.path.basename(path).lower()
    up = any(k in n for k in ('upper', 'maxill', 'maxila'))
    lo = any(k in n for k in ('lower', 'mandib'))
    if up and not lo:
        return 'upper'
    if lo and not up:
        return 'lower'
    return 'single'
