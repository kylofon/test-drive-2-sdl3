"""Test Drive II car data dumper.

Game/<CAR>.BIN   0x34F (847) bytes copied to DS:23A6 by 0267:15e4 (06c9:6d18 load + 06c9:5d01 copy).
                 CAMA.BIN is 896 bytes; its last 49 bytes are disk junk and are never copied.
Game/<CAR>O.BIN  0x20 bytes copied to DS:5616 (only when the computer opponent is enabled, DS:843E).
Game/CARS.DAT    "CODE Long_Name" per line.

"sim" = read by the simulation code 06c9:4000-5cff (port/spec/simulation.md, verified);
"render" = read by scene_render code (address given, meaning from a quick look only).

usage: python tools/td2car.py [GameDir] [OutDir]      -> OutDir/<CAR>.json + summary table
"""
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'Game')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'work', 'cars')

CAR_SIZE = 0x34F
BASE = 0x23A6


def u16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def u16s(b, o, n):
    return list(struct.unpack_from('<%dH' % n, b, o))


def field(off, value, use, note):
    return {'off': '0x%03X' % off, 'ds': 'DS:%04X' % (BASE + off), 'value': value, 'use': use, 'note': note}


def decode(b):
    f = {}
    f['num_gears'] = field(0x000, b[0], 'sim 06c9:4281',
                           'byte; highest selectable gear (sequential shifting and auto upshift); +001 unused')
    f['rpm_max'] = field(0x002, u16(b, 2), 'sim 06c9:4639, render 06c9:3cef',
                         'rpm above this blows the engine at once (run_state 3); rpm is clamped to it')
    f['rpm_redline'] = field(0x004, u16(b, 4), 'sim 06c9:4639, 06c9:4281',
                             'at or above: over-rev counter +1/tick, 30 ticks = blown engine; demo upshift point')
    f['rpm_upshift'] = field(0x006, u16(b, 6), 'sim 06c9:4281', 'automatic transmission upshift (rpm >=)')
    f['rpm_downshift'] = field(0x008, u16(b, 8), 'sim 06c9:4281',
                               'automatic/demo downshift (rpm <=, gear > 1)')
    f['unk_00A'] = field(0x00A, u16(b, 0x0A), 'none found', '')
    grip = struct.unpack_from('<I', b, 0x0C)[0]
    f['grip'] = field(0x00C, grip, 'sim 06c9:4674, 06c9:4a2e',
                      'u32; skid when |steer| > grip / speed_mph^2; low word = suspension damage limit')
    f['unk_010'] = field(0x010, u16(b, 0x10), 'none found', '')
    f['gear_ratio'] = field(0x012, u16s(b, 0x12, 7), 'sim 06c9:43c3',
                            'index = gear (0 neutral, never loaded); rpm = ratio * speed >> 16, min 800')
    knobs = [u16s(b, 0x20 + 4 * i, 2) for i in range(16)]
    f['knob_xy'] = field(0x020, knobs, 'sim 06c9:4281, 06c9:43c3; render 06c9:38f2',
                         '16 (x,y): 0-6 = gear positions (sequential shifting), 7-15 = gate slots; '
                         'entry 0 = neutral (its y is the neutral row of the knob animation)')
    f['gate_slot'] = field(0x060, list(b[0x60:0x69]), 'sim 06c9:4281',
                           'gate shifting (O key): joystick direction 0-8 -> knob index - 7')
    f['gate_gear'] = field(0x069, list(b[0x69:0x72]), 'sim 06c9:4281',
                           'gate shifting: joystick direction 0-8 -> gear engaged')
    f['engine_toughness'] = field(0x072, b[0x72], 'sim 06c9:4a2e, 06c9:4441',
                                  'byte; engine damage limit (run_state 5), and clutch-drop check')
    f['torque'] = field(0x073, list(b[0x73:0xC4]), 'sim 06c9:44ea',
                        '81 bytes, index = min(rpm/128, 80); accel = torque*ratio_hi >> 5 (8.8 mph/tick) '
                        '- drag; entry 80 is also the low byte of +0C3')
    f['clock_y'] = field(0x0C3, u16(b, 0xC3), 'render 06c9:391f', 'roof clock digit y (from a quick look)')
    f['clock_x'] = field(0x0C5, u16s(b, 0xC5, 7), 'render 06c9:391f', 'roof clock digit x positions')
    f['render_0D3'] = field(0x0D3, b[0xD3:0x14D].hex(), 'render 06c9:3c3a, 06c9:2477',
                            'steering-wheel frame positions and other cockpit data (see scene_render)')
    f['gauge_flags'] = field(0x14D, u16(b, 0x14D), 'render 06c9:3cef, 06c9:37d0',
                             'bits 1/2/4/8 select gauge styles (see scene_render)')
    f['render_14F'] = field(0x14F, b[0x14F:0x34F].hex(), 'render 06c9:3cef, 3ed7, 2542, 268a, 1f99',
                            'gauge geometry: +175/+177 and +249/+24B pivots, +179 and +24F needle tables, '
                            'digital dash data (see scene_render)')
    return f


def decode_opp(b):
    acc = u16s(b, 0, 16)
    return {'accel_by_speed_band': acc,
            'note': 'DS:5616, index = (speed >> 11) & 0x1E (8 mph bands); accel = (entry * DS:5358 >> 16) >> 1 '
                    '- drag[speed_hi>>2], 8.8 mph per tick (06c9:50a1); 0 = no more acceleration'}


def main():
    raw = open(os.path.join(GAME, 'CARS.DAT'), 'rb').read().split(b'\x1a')[0].decode('latin-1')
    cars = [l.split() for l in raw.splitlines() if l.strip()]
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for code, longname in cars:
        path = os.path.join(GAME, code.upper() + '.BIN')
        if not os.path.exists(path):
            continue
        full = open(path, 'rb').read()
        b = full[:CAR_SIZE]
        f = decode(b)
        opath = os.path.join(GAME, code.upper() + 'O.BIN')
        opp = decode_opp(open(opath, 'rb').read()) if os.path.exists(opath) else None
        doc = {'code': code, 'name': longname.replace('_', ' '), 'file_size': len(full),
               'ignored_tail': full[CAR_SIZE:].hex() if len(full) > CAR_SIZE else '',
               'fields': f, 'opponent': opp}
        with open(os.path.join(OUT, code.upper() + '.json'), 'w') as fp:
            json.dump(doc, fp, indent=1)
        g = f['num_gears']['value']
        ratios = f['gear_ratio']['value']
        tq = f['torque']['value']
        pk = max(range(len(tq)), key=lambda i: tq[i])
        top = ratios[g] if 0 < g < 7 else 0
        vmax = (f['rpm_redline']['value'] * 65536 // top) >> 8 if top else 0
        rows.append((code, len(full), g, f['rpm_max']['value'], f['rpm_redline']['value'],
                     f['rpm_upshift']['value'], f['rpm_downshift']['value'], f['grip']['value'],
                     f['engine_toughness']['value'], ' '.join('%5d' % r for r in ratios[1:g + 1]),
                     vmax, '%d@%d' % (tq[pk], pk * 128), f['gauge_flags']['value']))
    fmt = '%-5s %4s %2s %6s %6s %6s %6s %9s %4s  %-29s %5s %9s %4s'
    print(fmt % ('car', 'size', 'g', 'rpmMax', 'redl', 'up', 'down', 'grip', 'eng', 'ratios 1..N',
                 'vmax*', 'peakTq', 'dash'))
    for r in rows:
        print(fmt % r)
    print('* vmax = mph at the redline in top gear, ignoring drag.')
    print('JSON written to', OUT)


if __name__ == '__main__':
    main()
