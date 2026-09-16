"""Test Drive II resource tools.

Container (*.PES = 16-colour, *.PCS = 4-colour, also other packed files)
  u8 type, u24 unpacked size, then the pass payload.
    type 1: RLE        u32 packed length, u8 escape count (bit 7 set = no sequence pass),
                       escape codes; then the RLE stream.
    type 2: Huffman    u8 max code length n, n x u8 codes per length, alphabet (sum of counts);
                       canonical codes (shortest first, increasing), bitstream LSB-first per byte.
    type 0x80|k: k passes, each a complete type-1/2 stream; the output of one is the input of
                       the next (in practice 0x82: Huffman then RLE).
  RLE escapes (escape i = the i-th escape code, 1-based):
    sequence pass (unless flag): esc 2 ... esc 2 n  -> the bytes in between, n times
    run pass: esc 1 n v -> v n times; esc 3 nn(u16) v -> v nn times; esc k v (other) -> v k-1 times
All archives decode to exactly the stored size (verified on every shipped .PES / .PCS).

Decoded archive: u32 total, u16 count, count x char[4] names, count x u32 offsets (relative to the
end of the table, not sorted), data.
Sprite: 16-byte header u16 width_bytes, height, hot_x, hot_y, s16 x, y, u8 planemap[4].
  Plane map (TD2EGA blitter 06c9:916c family, loader fix-up 06c9:c838, verified):
    low nibble of pm[k]    stored plane k is written to these colour planes (list ends at the first
                           pm[k] with low nibble 0)
    pm[0] >> 4             colour planes cleared over the sprite rectangle (REPLACE / AND blits)
    pm[1] >> 4             colour planes set (REPLACE / OR blits) or inverted (XOR blits)
    pm[2] >> 4             16-colour: bit k set = stored block k is column-major (w columns of h bytes);
                           the .PES loader converts every flagged block to row-major once after
                           unpacking (06c9:c838, "UNFLIP"); skipped when pm[3] >> 4 != 0.
                           4-colour (TD2CGA loader, image 0x10DA0): a mode, 1 = column-major,
                           2 = column-major with each column holding its even rows then its odd rows,
                           3 = even rows as a w x ceil(h/2) column-major block, then odd rows as a
                           w x floor(h/2) column-major block; >= 4 is rejected.
    pm[3] >> 4             padding bytes after each stored block (0 in all shipped files)
  4-colour: rows of 2bpp pixels (width_bytes x 4 pixels); the CGA blitter ignores the plane map
  except for the storage mode.
  16-colour: one block of rows per stored plane (1 bpp). Colour bits that no stored plane and no
  pm[0]/pm[1] nibble mentions are left untouched by the game; they render as 0 here.

usage: td2res.py info FILE
       td2res.py export FILE OUTDIR
       td2res.py unpack FILE OUT       (raw decoded bytes)
"""
import os, struct, sys
import numpy as np

# TD2CGA: INT 10h mode 4, then (main, via the 06cf:5d00-slot hook) port 3D8h = 0Eh (colour burst off ->
# cyan/red/white palette on RGB monitors) and 3D9h = 30h (intensity): black, light cyan, light red, white.
CGA_PAL = [(0, 0, 0), (85, 255, 255), (255, 85, 85), (255, 255, 255)]
# TD2EGA palette (06c9:90e8 loads DS:6848 with INT 10h AX=1002h, mode 0Dh):
# registers 00 01 02 03 04 05 06 07 10 11 12 13 14 15 16 17, overscan 00 = the standard 16 colours.
EGA_PAL = [(0, 0, 0), (0, 0, 170), (0, 170, 0), (0, 170, 170), (170, 0, 0), (170, 0, 170),
           (170, 85, 0), (170, 170, 170), (85, 85, 85), (85, 85, 255), (85, 255, 85),
           (85, 255, 255), (255, 85, 85), (255, 85, 255), (255, 255, 85), (255, 255, 255)]


def _u24(b, o):
    return b[o] | b[o + 1] << 8 | b[o + 2] << 16


def unhuff(b, o, size):
    n = b[o]
    counts = b[o + 1:o + 1 + n]
    o += 1 + n
    alpha = b[o:o + sum(counts)]
    o += sum(counts)
    table, code, k = {}, 0, 0
    for length, c in enumerate(counts, 1):
        for _ in range(c):
            table[(length, code)] = alpha[k]
            k += 1
            code += 1
        code <<= 1
    out = bytearray()
    cur = length = 0
    bp = o * 8
    while len(out) < size:
        cur = cur << 1 | (b[bp >> 3] >> (bp & 7)) & 1
        bp += 1
        length += 1
        sym = table.get((length, cur))
        if sym is not None:
            out.append(sym)
            cur = length = 0
        elif length > n:
            raise ValueError('invalid Huffman code at bit %d' % bp)
    return bytes(out)


def unrle(b, o, size):
    o += 4                          # packed length
    ec = b[o]
    esc = b[o + 1:o + 1 + (ec & 0x7F)]
    data = b[o + 1 + (ec & 0x7F):]
    look = {c: i + 1 for i, c in enumerate(esc)}
    if not ec & 0x80:
        out, i, seq = bytearray(), 0, esc[1]
        while i < len(data):
            c = data[i]
            i += 1
            if c == seq:
                j = data.index(seq, i)
                out += data[i:j] * data[j + 1]
                i = j + 2
            else:
                out.append(c)
        data = bytes(out)
    out, i = bytearray(), 0
    while len(out) < size:
        c = data[i]
        k = look.get(c, 0)
        if k == 0:
            out.append(c)
            i += 1
        elif k == 1:
            out += bytes([data[i + 2]]) * data[i + 1]
            i += 3
        elif k == 3:
            out += bytes([data[i + 3]]) * (data[i + 1] | data[i + 2] << 8)
            i += 4
        else:
            out += bytes([data[i + 1]]) * (k - 1)
            i += 2
    if len(out) != size:
        raise ValueError('RLE output %d, expected %d' % (len(out), size))
    return bytes(out)


def unpack(b):
    t = b[0]
    if t & 0x80:
        data = b[4:]
        for _ in range(t & 0x7F):
            data = unpack(data)
        if len(data) != _u24(b, 1):
            raise ValueError('multi-pass size mismatch')
        return data
    if t == 1:
        return unrle(b, 4, _u24(b, 1))
    if t == 2:
        return unhuff(b, 4, _u24(b, 1))
    raise ValueError('unknown pack type %d' % t)


def load_archive(path):
    raw = unpack(open(path, 'rb').read())
    total, count = struct.unpack_from('<IH', raw, 0)
    names = [raw[6 + 4 * k:10 + 4 * k].rstrip(b'\0').decode('latin-1') for k in range(count)]
    base = 6 + 8 * count
    offs = struct.unpack_from('<%dI' % count, raw, 6 + 4 * count)
    order = sorted(range(count), key=lambda k: offs[k])
    ends = {}
    for n, k in enumerate(order):
        ends[k] = offs[order[n + 1]] if n + 1 < len(order) else len(raw) - base
    res = [(names[k], raw[base + offs[k]:base + ends[k]]) for k in range(count)]
    ega = path.upper().endswith('.PES')
    return raw, total, res, ega


def sprite_info(blob, ega):
    if len(blob) < 16:
        return None
    w, h, hx, hy, x, y = struct.unpack_from('<4H2h', blob, 0)
    pmap = blob[12:16]
    planes = []
    if ega:
        for b in pmap:
            if not b & 0x0F:
                break
            planes.append(b & 0x0F)
    pad = pmap[3] >> 4
    nblk = len(planes) if ega else 1
    size = 16 + (w * h + pad) * nblk
    # EC_4.PCS mtn2 (the only exception) has 2 trailing bytes after its 2bpp block.
    if not w or not h or not (len(blob) == size or (not ega and size < len(blob) < size + 4)):
        return None
    return dict(w=w, h=h, hx=hx, hy=hy, x=x, y=y, planes=planes, pmap=pmap.hex(), pad=pad)


def _unflip_ega(px, w, h):
    """06c9:c838: column-major block (w columns of h bytes) -> h x w rows."""
    return px.reshape(w, h).T


def _unflip_cga(px, w, h, mode):
    """TD2CGA loader (image 0x10DA0) storage modes 1..3 -> h x w rows."""
    out = np.zeros((h, w), np.uint8)
    if mode == 1:
        return px.reshape(w, h).T
    if mode == 2:                       # each column: even rows, then odd rows
        col = px.reshape(w, h)
        ne = (h + 1) // 2
        out[0::2] = col[:, :ne].T
        out[1::2] = col[:, ne:].T
        return out
    if mode == 3:                       # even-row field, then odd-row field, both column-major
        ne, no = (h + 1) // 2, h // 2
        out[0::2] = px[:w * ne].reshape(w, ne).T
        out[1::2] = px[w * ne:w * ne + w * no].reshape(w, no).T
        return out
    raise ValueError('bad 4-colour storage mode %d' % mode)


def plane_rows(blob, info, k, ega=True):
    """Stored plane k as a height x width_bytes array, row-major."""
    w, h = info['w'], info['h']
    px = np.frombuffer(blob, np.uint8, offset=16 + k * (w * h + info['pad']), count=w * h)
    pm = blob[12:16]
    flags = pm[2] >> 4 if not pm[3] & 0xF0 else 0
    if ega:
        return _unflip_ega(px, w, h) if flags >> k & 1 else px.reshape(h, w)
    return _unflip_cga(px, w, h, flags) if flags else px.reshape(h, w)


def render(blob, info, ega):
    from PIL import Image
    w, h = info['w'], info['h']
    if not ega:
        bits = np.unpackbits(plane_rows(blob, info, 0, False), axis=1).reshape(h, w * 4, 2)
        return Image.fromarray(np.array(CGA_PAL, np.uint8)[bits[:, :, 0] * 2 + bits[:, :, 1]])
    # REPLACE blit onto colour 0: pm[0] high nibble clears (already 0), pm[1] high nibble sets.
    stored = 0
    for mask in info['planes']:
        stored |= mask
    idx = np.full((h, w * 8), (blob[13] >> 4) & ~stored & 0x0F, np.uint8)
    for k, mask in enumerate(info['planes']):
        idx |= np.unpackbits(plane_rows(blob, info, k), axis=1) * mask
    return Image.fromarray(np.array(EGA_PAL, np.uint8)[idx])


def main():
    cmd, path = sys.argv[1], sys.argv[2]
    if cmd == 'unpack':
        open(sys.argv[3], 'wb').write(unpack(open(path, 'rb').read()))
        return
    raw, total, res, ega = load_archive(path)
    print('%s: decoded %d, total field %d, %d resources' % (os.path.basename(path), len(raw), total, len(res)))
    outdir = sys.argv[3] if cmd == 'export' else None
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    for name, blob in res:
        info = sprite_info(blob, ega)
        if cmd == 'info':
            print('  %-5s len=%5d %s' % (name, len(blob), info or blob[:16].hex(' ')))
        if outdir:
            safe = name.replace('\0', '_').replace('!', '_') or '_'
            open(os.path.join(outdir, safe + '.bin'), 'wb').write(blob)
            if info:
                render(blob, info, ega).save(os.path.join(outdir, safe + '.png'))


if __name__ == '__main__':
    main()
