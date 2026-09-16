"""Test Drive II (TD2EGA.EXE) SONGS.BIN / VOICES.BIN and effect streams -> WAV (PC speaker).

TD2 has two independent PC-speaker players, both run as routines of the timer interrupt
(06c9:61bf) at 1193182 / 0x2E9C = 99.9985 Hz (divisor 11932 passed by every installer call).

1. Music player 06c9:75ea (menus only; installed by main 0000:081a and 0267:1c3e).
   Started by song_play(songs, n) 06c9:758a, only if DS:5EFB == 3 (sound and music on).

   SONGS.BIN (loaded raw by 06c9:6d18 to seg:0000; all offsets are file offsets)
     +0      song table, 4 bytes per song number n (n = 1..3 used; entry 0 and 4 are zero):
               u16 list_off   pattern-list offset (0 = no song -> stops on first tick)
               u16 unused     copied to DS:65EF/65F3, never read
     list    3-byte entries: u16 pattern_off, u8 transpose (added to DS:65D5, always 0).
             pattern_off 0 stops the song.  Entries are consumed in order.
     pattern 2-byte events (op, arg):
               00 n      rest: tempo*n ticks, speaker gate off
               01..7F n  note op+transpose, length tempo*(n&0x7F) ticks. Articulation: off part =
                         length >> voice.shift (0 if shift==0 or n&0x80), on part = length - off;
                         on part 0 -> treated as rest of `off` ticks.  The gate goes off on the
                         (on)-th tick, so the tone sounds on-1 ticks and is silent off+1 ticks.
                         Divisor = DS:663B[note] (+ vibrato offset), arpeggio can change note.
               FF x      restart the song's pattern list from its first entry (songs loop forever)
               FE t      tempo = t (ticks per length unit; DS:65D3, initial 0x14)
               FD v      voice = VOICES[v] (32-byte records, first 28 bytes copied to DS:6609)
               FC x      end of pattern -> next pattern-list entry
               FB x      stop
               80..FA    stop
   VOICES.BIN is loaded right before SONGS.BIN into contiguous heap paragraphs.  The shipped file
   is 2 bytes (CR LF) = 1 paragraph, so voice 1 (offset 32) reads SONGS.BIN bytes 16..43
   (default --voices heap).  Voice record (offset: meaning):
     +0 u8 shift, +2 arp_init, +4 arp_reload, +6 arp_mask, +8 u8[8] arp_table (note offsets),
     +16 vib_delay, +18 vib_period, +20 s8 vib_dir (0 = triangle, else sawtooth reset),
     +22 vib_step, +24 s16 vib_min, +26 s16 vib_max (vibrato in divisor units).

2. Effect stream player 06c9:6269 (driving only; TD1-style byte code, see ../TestDrive1987):
     n (00..7F) dur:u16  note n (0 = rest) for dur+1 ticks, divisor DS:5F2E[n]; speaker cut when the
                         remaining count equals dur>>shift (shift 0 = legato), initial shift 3
     FE s | FD/FC/FB n:u16 loop start | FA/F9/F8 loop end | F7/F6/F5 break | FF (and 80..F4) end
   Driving streams are in the EXE (DS:1352 engine loop, DS:549F and DS:5494 noise bursts on the
   slot-0x58 divisor, which the driving tick 06c9:412c sets every tick from DS:32AE[counter&31]).

Usage: python tools/td2snd.py [--passes N] [--voices heap|exe|FILE] [--rate 44100] [--no-sfx]
"""
import argparse
import os
import struct
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIT = 1193182
TICK_HZ = PIT / 0x2E9C          # 99.9985 Hz (06c9:6059 / 601c with DX = 0x2E9C)
DG = 0x178F0                    # DGROUP image offset


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def s8(v):
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def load_image(exe):
    d = open(exe, 'rb').read()
    return d[struct.unpack_from('<H', d, 8)[0] * 16:]


class MusicPlayer:
    """Tick-exact model of 06c9:75ea.  mem = song segment bytes, dg = DGROUP bytearray."""

    def __init__(self, songs, voices_mem, dg):
        self.m = songs
        self.vm = voices_mem
        self.dg = dg                      # DGROUP copy (voice area DS:6609.., tables)
        self.tempo = struct.unpack_from('<H', dg, 0x65D3)[0]
        self.base_tr = struct.unpack_from('<H', dg, 0x65D5)[0]
        self.start = self.playing = 0
        self.tr = self.on = self.off = self.pat = self.lst = self.loop = 0
        self.note = self.div = self.arp_cnt = self.arp_idx = self.vib_cnt = 0
        self.vib_dir = self.vib_ofs = 0
        self.gate = False
        self.out = 0
        self.passes = 0

    # DGROUP accessors
    def b(self, o):
        return self.dg[o]

    def w(self, o):
        return struct.unpack_from('<H', self.dg, o)[0]

    def mb(self, o):
        return self.m[o] if o < len(self.m) else 0

    def mw(self, o):
        return self.mb(o) | self.mb(o + 1) << 8

    def play(self, n):                                   # 06c9:758a
        p = n * 4
        self.lst = self.loop = self.mw(p)
        self.start = self.playing = 1

    def stop(self):
        self.playing = self.start = 0
        self.gate = False

    def tick(self):
        if self.start:
            self.start = 0
            return self.next_pattern()
        if not self.playing:
            self.stop()
            return
        self.step()

    def next_pattern(self):                              # 761e
        si = self.lst
        if si == 0:
            return self.stop()
        self.pat = self.mw(si)
        self.tr = (self.mb(si + 2) + self.base_tr) & 0xFFFF
        self.lst = (self.lst + 3) & 0xFFFF
        return self.next_event()

    def next_event(self):                                # 7643
        for _ in range(100000):
            si = self.pat
            if si == 0:
                return self.stop()
            self.pat = (self.pat + 2) & 0xFFFF
            op = self.mb(si)
            arg = self.mb(si + 1)
            if op < 0x80:
                return self.note_event(op, arg)
            if s8(op) < -5:
                return self.stop()
            k = (-s8(op))
            if k == 1:                                   # FF: restart list
                self.passes += 1
                self.lst = self.loop
                return self.next_pattern()
            if k == 2:                                   # FE: tempo
                self.tempo = arg
            elif k == 3:                                 # FD: voice
                base = arg * 32
                rec = bytes(self.vm[base:base + 28]).ljust(28, b'\0')
                self.dg[0x6609:0x6609 + 28] = rec
            elif k == 4:                                 # FC: next pattern
                return self.next_pattern()
            else:                                        # FB: stop
                self.playing = self.start = 0
                self.lst = 0
                self.passes = 1 << 30
                return
        raise RuntimeError('event loop without time')

    def note_event(self, op, arg):
        al = self.tempo & 0xFF
        if op == 0:                                      # rest
            self.off = al * arg
            self.on = 0
            self.gate = False
            return self.off_part()
        ax = al * (arg & 0x7F)
        sh = self.b(0x6609)
        dx = 0 if (arg & 0x80) or sh == 0 else (ax >> sh if sh < 16 else 0)
        self.off = dx
        self.on = ax - dx
        if self.on == 0:
            self.gate = False
            return self.off_part()
        self.note = (op + self.tr) & 0xFFFF
        self.div = self.w(0x663B + 2 * self.note)
        self.out = self.div
        self.gate = True
        self.arp_cnt = self.w(0x660B)
        self.arp_idx = 0
        self.vib_ofs = 0
        self.vib_cnt = self.w(0x6619)
        d = self.b(0x661D)
        self.vib_dir = d if d else 1
        return self.step()

    def step(self):                                      # 7758
        if self.on:
            self.on -= 1
            if self.on:
                return self.effects()
            self.gate = False
            self.start = 0
            return
        return self.off_part()

    def off_part(self):                                  # 7771
        if self.off:
            self.off -= 1
            return
        return self.next_event()

    def effects(self):                                   # 7780
        if self.arp_cnt:
            self.arp_cnt -= 1
            if self.arp_cnt == 0:
                self.arp_cnt = self.w(0x660D)
                self.arp_idx = (self.arp_idx + 1) & 0xFFFF
                k = self.arp_idx & self.w(0x660F)
                n = (self.b(0x6611 + k) + self.note) & 0xFFFF
                self.div = self.w(0x663B + 2 * n)
        if self.vib_cnt:
            self.vib_cnt -= 1
        else:
            for _ in range(4):
                if s8(self.vib_dir) >= 0:
                    ax = s16(self.w(0x661F) + self.vib_ofs)
                    ok = not ax > s16(self.w(0x6623))
                else:
                    ax = s16(self.vib_ofs - self.w(0x661F))
                    ok = not ax < s16(self.w(0x6621))
                if ok:
                    break
                if self.b(0x661D) == 0:
                    self.vib_dir = (-s8(self.vib_dir)) & 0xFF
                    continue
                ax = 0
                break
            else:
                raise RuntimeError('vibrato bounce loop (hangs the original)')
            self.vib_ofs = ax
            self.vib_cnt = self.w(0x661B)
        self.out = (self.vib_ofs + self.div) & 0xFFFF


def run_song(pl, n, passes, max_ticks):
    pl.play(n)
    ticks = []
    while len(ticks) < max_ticks:
        pl.tick()
        ticks.append(pl.out if pl.gate else 0)
        if not pl.playing and not pl.start:
            break
        if pl.passes >= passes:
            break
    return ticks


def run_stream(b, pos, div, slot58=None, max_ticks=100 * 60):
    """06c9:6269 model; returns per-tick divisor list (0 = silent)."""
    shift = 3
    cnt = [0, 0, 0]
    start = [0, 0, 0]
    endp = [0, 0, 0]
    out = []
    t = 0
    while len(out) < max_ticks:
        op = b[pos]
        if op < 0x80:
            dur = struct.unpack_from('<H', b, pos + 1)[0]
            pos += 3
            cut = (dur >> shift) if (op and shift) else 0
            for i in range(dur + 1):
                if op == 0 or (cut and i > dur - cut):
                    out.append(0)
                else:
                    d = div[op] if op != 0x58 or slot58 is None else slot58(t - 1)
                    out.append(d)
            t += dur + 1
            continue
        k = (-s8(op)) & 0xFF
        if k == 2:
            shift = b[pos + 1]
            pos += 2
        elif 3 <= k <= 5:
            i = k - 3
            cnt[i] = s16(struct.unpack_from('<H', b, pos + 1)[0])
            pos += 3
            start[i] = pos
        elif 6 <= k <= 8:
            i = k - 6
            cnt[i] -= 1
            if cnt[i] < 0:
                pos += 1
            else:
                endp[i] = pos
                pos = start[i]
        elif 9 <= k <= 11:
            i = k - 9
            pos = endp[i] if cnt[i] == 0 else pos + 1
        else:
            break                                         # FF / 80..F4: end
    return out


def render(ticks, rate):
    """Per-tick divisor list -> int16 PCM.  Phase restarts when the gate turns on."""
    chunks = []
    phase = 0.0
    acc = 0.0
    prev = 0
    spt = rate / TICK_HZ
    for d in ticks:
        acc += spt
        n = int(acc)
        acc -= n
        if not d:
            chunks.append(np.zeros(n))
            prev = 0
            continue
        if not prev:
            phase = 0.0
        f = PIT / d
        ph = phase + np.arange(n) * f / rate
        chunks.append(np.where((ph % 1.0) < 0.5, 1.0, -1.0))
        phase = (phase + n * f / rate) % 1.0
        prev = d
    s = np.concatenate(chunks) if chunks else np.zeros(1)
    return (s * 9000).astype('<i2')


def write_wav(path, pcm, rate):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--songs', default=os.path.join(ROOT, 'Game', 'SONGS.BIN'))
    ap.add_argument('--voices', default='heap',
                    help="'heap' (shipped VOICES.BIN followed by SONGS.BIN in memory, as the game "
                         "sees it), 'exe' (voice record = DS:6609 default from the EXE), or a file")
    ap.add_argument('--exe', default=os.path.join(ROOT, 'work', 'TD2EGA_unp.exe'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'sound'))
    ap.add_argument('--passes', type=int, default=1, help='song repetitions to render (songs loop via FF)')
    ap.add_argument('--rate', type=int, default=44100)
    ap.add_argument('--no-sfx', action='store_true')
    a = ap.parse_args()

    img = load_image(a.exe)
    songs = open(a.songs, 'rb').read()
    vfile = os.path.join(os.path.dirname(a.songs), 'VOICES.BIN')
    if a.voices == 'heap':
        v = open(vfile, 'rb').read()
        paras = len(v) // 16 + (1 if len(v) & 15 else 0)
        vmem = v.ljust(paras * 16, b'\0') + songs
    elif a.voices == 'exe':
        vmem = b'\0' * 32 * 8
        rec = img[DG + 0x6609:DG + 0x6609 + 28]
        vmem = b''.join(rec.ljust(32, b'\0') for _ in range(8))
    else:
        vmem = open(a.voices, 'rb').read()
    os.makedirs(a.out, exist_ok=True)

    # the song table ends where the first pattern list starts
    first = min(o for o in struct.unpack_from('<%dH' % (len(songs) // 2), songs, 0)[:32:2] if o)
    for song in range(first // 4):
        if struct.unpack_from('<H', songs, song * 4)[0] == 0:
            continue
        dg = bytearray(img[DG:DG + 0x10000])
        pl = MusicPlayer(songs, vmem, dg)
        ticks = run_song(pl, song, a.passes, int(TICK_HZ * 600))
        pcm = render(ticks, a.rate)
        path = os.path.join(a.out, 'song%d.wav' % song)
        write_wav(path, pcm, a.rate)
        on = [d for d in ticks if d]
        print('song %d: %d ticks = %.2f s, %s, divisors %d..%d -> %s' % (
            song, len(ticks), len(ticks) / TICK_HZ,
            'loops (FF)' if pl.passes < (1 << 30) else 'ends (FB)',
            min(on), max(on), path))

    if a.no_sfx:
        return
    dgb = img[DG:DG + 0x10000]
    div = struct.unpack_from('<93H', dgb, 0x5F2E)
    noise = struct.unpack_from('<32H', dgb, 0x32AE)
    for name, off in (('sfx_549f', 0x549F), ('sfx_5494', 0x5494)):
        ticks = run_stream(dgb, off, div, slot58=lambda t: noise[t & 31])
        pcm = render(ticks, a.rate)
        path = os.path.join(a.out, name + '.wav')
        write_wav(path, pcm, a.rate)
        print('%s: %d ticks = %.2f s -> %s' % (name, len(ticks), len(ticks) / TICK_HZ, path))


if __name__ == '__main__':
    main()
