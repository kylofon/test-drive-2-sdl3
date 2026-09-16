"""Test Drive II road data decoder and schematic stage maps.

Files (Game/):  <SCN>n.DAT  packed (tools/td2res.py container), unpacked into DS:346A (at most
                            0x1E5E bytes, i.e. up to DS:52C7) by 0267:15e4 via 06c9:6d50 + 06c9:5d01.
                            The file is a memory image of that DGROUP block.
                <SCN>n.SGN  raw, optional; loaded into a far block (DS:940C/940E) by 06c9:6d18.
                SCENES.DAT  "CODE Long_Name stages" per line.

DAT layout (file offset = DS - 0x346A; everything little endian)  -- see port/spec/simulation.md
  0x000  char[20]   name of the stage scenery archive (<name>.PES/.PCS), NUL padded
  0x014  128 x 4    road records [flags, curve s8, pitch s8, object]; index = stream byte & 0x7F
  0x214  u8[12]     unused (zero in every file)
  0x220  u8[128]    roadside-object ring, type (0xFF = none); DS:368A
  0x2A0  s8[128]    roadside-object ring, side/lane (-7..7); DS:370A
  0x320  u16[10]    5 (word,word) pairs; the 2nd word of each is copied to DS:534A..5352 (scene_render)
  0x334  u16[4]     DS:379E..37A5, read by game_flow's results code (0267:0039)
  0x33C  zone[10]   {u16 start, u16 end, s16 a, s16 b}, zero-terminated; unit coordinates are
                    relative to DS:3B33 (= stream unit + 30); right-side hazard distance, linear a->b
  0x38C  u8[3]      initial state of the toggles DS:37F6 (median), 37F7, 37F8 (objects 0x18/0x17/0x19)
  0x38F  s8[20]     side/lane for placed objects 0x1C..0x2F (DS:37F9..380C = DS:37DD + code)
  0x3A3  u16        stream length in units (DS:380D)
  0x3A5  u16        finish unit (DS:380F) = length - 201 in every file
  0x3A7  u16        stream end, relative to DS:3B33 (DS:3811, fixed up by 06c9:3f40) = length + 30
  0x3A9  car[50]    oncoming traffic, 8 bytes {u16 type, u16 pos, u16 sub, s16 lateral}; type low
                    byte 0 ends the list; pos is per mille of the stage length (06c9:1e59)
  0x539  car[50]    same-direction traffic, same layout
  0x6C9  u8[30]     unused (DS:3B33..3B50)
  0x6E7  u8[len+71] road stream (DS:3B51..); bit 7 = wide road; the 71 bytes after the end are look-ahead padding

usage: python tools/td2road.py [GameDir] [OutDir]      -> OutDir/<SCN><n>.json, <SCN><n>.png
"""
import json
import math
import os
import struct
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from td2res import unpack  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'Game')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'work', 'roads')

DS_BASE = 0x346A
STREAM = 0x3B51 - DS_BASE          # 0x6E7
LOOKAHEAD = 0x47
UNITS_PER_MILE = 420               # 0267:0039 average speed = units*3600/42/tenths
HEADING_UNITS = 1024               # DS:5344 wraps at 0x400 in the backdrop scroll (06c9:0a21)

# DS:5491 region bits (cumulative XOR of record flags; bit 0 = stream bit 7).  Edge tests: 06c9:4b9a.
FLAG_NAMES = {0x01: 'wide', 0x02: 'right_barrier', 0x04: 'right_dropoff', 0x08: 'right_no_scenery',
              0x10: 'left_barrier', 0x20: 'left_dropoff', 0x40: 'left_no_scenery',
              0x80: 'narrow (edges +-400, tunnel/bridge)'}

OBJECTS = {
    0x00: 'none',
    0x0A: 'gas_station_zone (stop here: run_state 1, or 9 if too far left)',
    0x0B: 'none (no sim effect)',
    0x0C: 'past_station_zone (stopping gives run_state 4, out of gas)',
    0x15: 'parked_police (radar trap 80 units ahead)',
    0x16: 'police_roadblock (60 units ahead, only above 50 mph)',
    0x17: 'toggle DS:37F7',
    0x18: 'toggle DS:37F6 (median: left lane objects/traffic move out on wide road)',
    0x19: 'toggle DS:37F8 (backdrop layer)',
    0x1A: 'roadside density += 0x10',
    0x1B: 'roadside density -= 0x10',
}


def s8(v):
    return v - 256 if v >= 128 else v


def object_name(o):
    if o in OBJECTS:
        return OBJECTS[o]
    if 1 <= o <= 9:
        return 'sign %d (posts at +-400 / +-800)' % o
    if 0x0D <= o <= 0x14:
        return 'road obstacle %d (%s lane, x=%+d)' % (o, 'left' if o & 1 else 'right', -200 if o & 1 else 200)
    if 0x1C <= o <= 0x2F:
        return 'placed roadside object type %d (sign/billboard %d)' % ((o - 0x16) * 5, o - 0x1C)
    return 'unused code 0x%02x (handler 0x499a range)' % o if o >= 0x30 else 'code 0x%02x' % o


def decode_sgn(b):
    offs = struct.unpack_from('<20H', b, 0)
    signs = []
    for i, o in enumerate(offs):
        if not o:
            signs.append(None)
            continue
        hdr = struct.unpack_from('<13H', b, o)
        end = b.index(b'\0', o + 26)
        signs.append({'index': i, 'offset': o, 'width': hdr[0], 'height': hdr[1],
                      'header_words': list(hdr), 'text': b[o + 26:end].decode('latin-1')})
    return {'offsets': list(offs), 'signs': signs}


def decode_dat(d):
    name = d[:20].split(b'\0')[0].decode('latin-1')
    recs = [{'flags': d[0x14 + 4 * i], 'curve': s8(d[0x15 + 4 * i]), 'pitch': s8(d[0x16 + 4 * i]),
             'object': d[0x17 + 4 * i]} for i in range(128)]
    length, finish, end = struct.unpack_from('<3H', d, 0x3A3)
    zones = []
    for i in range(10):
        z = struct.unpack_from('<2H2h', d, 0x33C + 8 * i)
        if not z[0]:
            break
        zones.append({'start_unit': z[0] - 30, 'end_unit': z[1] - 30, 'a': z[2], 'b': z[3]})

    def traffic(base):
        out = []
        for i in range(50):
            t, p, s, lat = struct.unpack_from('<3Hh', d, base + 8 * i)
            if t & 0xFF == 0:
                break
            out.append({'type': t, 'per_mille': p, 'unit': p * length // 1000, 'sub': s, 'lateral': lat})
        return out
    stream = d[STREAM:STREAM + length + LOOKAHEAD]
    return {
        'scenery_archive': name,
        'records': recs,
        'unused_214': d[0x214:0x220].hex(),
        'roadside_ring_type': list(d[0x220:0x2A0]),
        'roadside_ring_side': [s8(x) for x in d[0x2A0:0x320]],
        'scene_words_320': list(struct.unpack_from('<10H', d, 0x320)),
        'results_words_334': list(struct.unpack_from('<4H', d, 0x334)),
        'right_zones': zones,
        'toggles_37f6_37f7_37f8': list(d[0x38C:0x38F]),
        'placed_object_side': {('0x%02x' % (0x1C + i)): s8(d[0x38F + i]) for i in range(20)},
        'length_units': length, 'finish_unit': finish, 'end_rel_3b33': end,
        'length_miles': round(length / UNITS_PER_MILE, 2),
        'oncoming': traffic(0x3A9), 'same_direction': traffic(0x539),
        'stream': list(stream),
    }


def walk(road):
    """Per-unit state as the simulation sees it (06c9:4674 unit loop)."""
    recs = road['records']
    flags = 0
    heading = 0          # DS:5344 units (1/1024 turn)
    x = y = 0.0
    pts = []
    for u, b in enumerate(road['stream'][:road['length_units']]):
        r = recs[b & 0x7F]
        flags = ((flags & 0xFE) | (b >> 7)) ^ r['flags']
        heading += r['curve'] >> 1
        a = math.radians(heading * 360.0 / HEADING_UNITS)
        x += math.sin(a)
        y -= math.cos(a)
        pts.append({'unit': u, 'byte': b, 'wide': b >> 7, 'rec': b & 0x7F, 'flags': flags,
                    'curve': r['curve'], 'pitch': r['pitch'], 'object': r['object'],
                    'heading': heading, 'x': x, 'y': y})
    return pts


def regions(pts, bit):
    out, start = [], None
    for p in pts:
        on = bool(p['flags'] & bit)
        if on and start is None:
            start = p['unit']
        if not on and start is not None:
            out.append([start, p['unit'] - 1])
            start = None
    if start is not None:
        out.append([start, pts[-1]['unit']])
    return out


def render(road, pts, sgn, title, path):
    W, H, MH = 900, 700, 200
    img = Image.new('RGB', (W, H + MH), (250, 250, 245))
    dr = ImageDraw.Draw(img)
    xs = [p['x'] for p in pts]
    ys = [p['y'] for p in pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sc = min((W - 60) / max(1, maxx - minx), (H - 80) / max(1, maxy - miny))
    ox = 30 - minx * sc + ((W - 60) - (maxx - minx) * sc) / 2
    oy = 50 - miny * sc + ((H - 80) - (maxy - miny) * sc) / 2

    def P(p):
        return (ox + p['x'] * sc, oy + p['y'] * sc)
    for a, b in zip(pts, pts[1:]):
        col = (60, 60, 60)
        if a['flags'] & 0x80:
            col = (120, 60, 160)
        elif a['wide']:
            col = (40, 110, 200)
        if a['flags'] & 0x24:
            col = (200, 120, 30)
        wdt = 4 if a['wide'] else 2
        dr.line([P(a), P(b)], fill=col, width=wdt)
    fin = road['finish_unit']
    for p in pts:
        o = p['object']
        cx, cy = P(p)
        if o == 0x0A:
            dr.rectangle([cx - 6, cy - 6, cx + 6, cy + 6], outline=(0, 150, 0), width=2)
            dr.text((cx + 8, cy - 6), 'GAS', fill=(0, 120, 0))
        elif o in (0x15, 0x16):
            dr.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(30, 30, 220) if o == 0x15 else (220, 30, 30))
        elif 0x1C <= o <= 0x2F:
            s = sgn and sgn['signs'][o - 0x1C]
            if s:
                dr.text((cx + 5, cy), s['text'].split('\n')[0][:18], fill=(150, 40, 40))
        elif 0x0D <= o <= 0x14:
            dr.point((cx, cy), fill=(200, 0, 0))
    s0 = P(pts[0])
    dr.ellipse([s0[0] - 6, s0[1] - 6, s0[0] + 6, s0[1] + 6], fill=(0, 0, 0))
    dr.text((s0[0] + 8, s0[1] + 4), 'START', fill=(0, 0, 0))
    if fin < len(pts):
        f = P(pts[fin])
        dr.line([f[0] - 8, f[1], f[0] + 8, f[1]], fill=(0, 0, 0), width=3)
        dr.text((f[0] + 8, f[1] + 4), 'FINISH %d' % fin, fill=(0, 0, 0))
    dr.text((10, 8), '%s  %s  %d units (%.2f mi), finish %d, heading %+.0f deg net' % (
        title, road['scenery_archive'], road['length_units'], road['length_units'] / UNITS_PER_MILE,
        fin, pts[-1]['heading'] * 360.0 / HEADING_UNITS), fill=(0, 0, 0))
    dr.text((10, 24), 'grey road, blue wide, purple flag 0x80, orange drop-offs; green GAS; '
                      'blue dot parked cop 0x15, red dot roadblock 0x16; red text = .SGN billboard. '
                      'Schematic (heading from DS:5344).', fill=(80, 80, 80))
    # profile strip: vertical curvature (pitch) and horizontal curvature (curve) per unit.
    # Pitch is a curvature (the renderer adds -pitch/2 to an 8.8-degree slope per row, 06c9:2211)
    # and is not balanced in the data, so no absolute elevation is drawn.
    top = H + 30
    mid1, mid2 = top + 45, top + 130
    n = len(pts)
    dr.text((30, top - 22), 'pitch per unit (green, +-64) and curve per unit (blue, +-16); '
                            'green lines = gas station zone, black = finish', fill=(0, 0, 0))
    dr.line([30, mid1, W - 30, mid1], fill=(200, 200, 200))
    dr.line([30, mid2, W - 30, mid2], fill=(200, 200, 200))
    for p in pts:
        px = 30 + p['unit'] * (W - 60) / max(1, n - 1)
        if p['pitch']:
            dr.line([px, mid1, px, mid1 - p['pitch'] * 40 / 64], fill=(30, 140, 30))
        if p['curve']:
            dr.line([px, mid2, px, mid2 - p['curve'] * 40 / 16], fill=(40, 90, 200))
        if p['object'] == 0x0A:
            dr.line([px, top, px, top + MH - 30], fill=(0, 160, 0))
    fx = 30 + fin * (W - 60) / max(1, n - 1)
    dr.line([fx, top, fx, top + MH - 30], fill=(0, 0, 0))
    img.save(path)


def main():
    os.makedirs(OUT, exist_ok=True)
    lines = open(os.path.join(GAME, 'SCENES.DAT'), 'rb').read().split(b'\x1a')[0].decode('latin-1').split()
    scenes = [(lines[i].upper(), lines[i + 1], int(lines[i + 2])) for i in range(0, len(lines) - 2, 3)]
    summary = []
    for code, longname, nst in scenes:
        for n in range(nst):
            base = os.path.join(GAME, '%s%d' % (code, n))
            if not os.path.exists(base + '.DAT'):
                continue
            raw = unpack(open(base + '.DAT', 'rb').read())
            road = decode_dat(raw)
            road['scenery'] = code
            road['scenery_name'] = longname
            road['stage'] = n
            road['file_unpacked_size'] = len(raw)
            sgn = None
            if os.path.exists(base + '.SGN'):
                sgn = decode_sgn(open(base + '.SGN', 'rb').read())
            road['sgn'] = sgn
            pts = walk(road)
            road['regions'] = {FLAG_NAMES[b]: regions(pts, b) for b in FLAG_NAMES}
            road['wide_units'] = sum(p['wide'] for p in pts)
            road['objects'] = [{'unit': p['unit'], 'code': p['object'], 'what': object_name(p['object'])}
                               for p in pts if p['object']]
            road['net_heading_deg'] = round(pts[-1]['heading'] * 360.0 / HEADING_UNITS, 1)
            stem = '%s%d' % (code, n)
            with open(os.path.join(OUT, stem + '.json'), 'w') as f:
                json.dump(road, f, indent=1)
            render(road, pts, sgn, stem, os.path.join(OUT, stem + '.png'))
            summary.append((stem, road['scenery_archive'], road['length_units'], road['finish_unit'],
                            road['length_miles'], len(road['oncoming']), len(road['same_direction']),
                            len(road['right_zones']), road['wide_units'], road['net_heading_deg'],
                            'yes' if sgn else 'no'))
    fmt = '%-7s %-9s %6s %6s %6s %4s %5s %5s %5s %8s %4s'
    print(fmt % ('stage', 'archive', 'units', 'finish', 'miles', 'onc', 'same', 'zones', 'wide', 'heading', 'sgn'))
    for r in summary:
        print(fmt % r)
    print('written to', OUT)


if __name__ == '__main__':
    main()
