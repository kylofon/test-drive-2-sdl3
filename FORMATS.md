# Test Drive II: The Duel (1989, DSI/Accolade) — file formats & internals

Everything marked **Verified** was checked against the disassembly or by exact round-trips on every
shipped file. Everything else is marked as unverified or still open.

## Tools (run from the repository root, Python 3.12 + Pillow + numpy + capstone)

| Script | Purpose |
|---|---|
| `tools/unexepack.py IN.EXE OUT.EXE` | Unpacks Microsoft EXEPACK (all three game EXEs are packed) |
| `tools/x86dis.py EXE find HEX` / `dis SSSS:OOOO LEN` | Byte search / 16-bit disassembly |
| `tools/td2index.py EXE port/td2ega [gaps]` | Segment map and function index (`port/td2ega_functions.json/.csv`, Ghidra starts) |
| `tools/td1match.py ../TestDrive1987` | Candidate names for functions shared with Test Drive (1987) |
| `tools/td2res.py info\|export\|unpack FILE [OUT]` | Decodes packed files and `.PES`/`.PCS` archives, exports sprites as `.bin` + `.png` |
| `tools/sheet.py Game work/sheets` | One labelled contact sheet per archive |
| `tools/ghidra/DecompileAll.java`, `postprocess.py` | Headless Ghidra decompile → `port/decomp/td2ega_ds.c` |

## Files

| Files | What |
|---|---|
| `DUEL.EXE` | Launcher (960 bytes): menu 1 CGA/Tandy 4 colours → `td2cga.exe`, 2 Tandy 16 colours → `td2tdy.exe`, 3 EGA → `td2ega.exe`, 4 Hercules → `td2cga.exe herc`, Esc = DOS |
| `TD2EGA.EXE`, `TD2CGA.EXE`, `TD2TDY.EXE` | The game, one build per graphics adapter |
| `*.PES` / `*.PCS` | Resource archives, 16-colour / 4-colour versions of the same names |
| `CARS.DAT` | Installed cars: `CODE Long_Name` per line (12 cars in the Collection) |
| `SCENES.DAT` | Installed scenery disks: `CODE Name_With_Underscores stages` (`CCC` 7, `ec_` 6, `TDS2` 6) |
| `DISKID.DAT` | Disk identity for the disk-swap check (dropped by the port) |
| `<CAR>.BIN` (847 bytes), `<CAR>O.BIN` (32 bytes), `<CAR>.SS` | Car data, opponent data (unverified), showroom animation list |
| `<CAR>DASH`, `<CAR>REAR`, `<CAR>ROAD`, `<CAR>ST` | Cockpit, rear view, the car as seen on the road, showroom/spec sheet |
| `<SCN>.FNT`, `<SCN>n.DAT`, `<SCN>n.SGN` | Vector font for road-sign text (see `port/spec/platform.md`); per-stage road data (packed) and sign data |
| `<SCN>CAR1-3`, `<SCN>ICON`, `<SCN>n` | Per-scenery traffic, selection icon and stage scenery archives |
| `SONGS.BIN`, `VOICES.BIN` | Menu music and voice records (`tools/td2snd.py` → `work/sound/`; see `port/spec/platform.md`) |
| `hisc.dat`, `select.dat` | Written by the game: high scores and the current car/scenery selection |

## Executables (Verified)

* All three builds are EXEPACK-packed. Unpacked: TD2EGA 110 272 → 130 240 bytes, TD2CGA 100 000 →
  119 872, TD2TDY 99 712 → 119 744.
* Microsoft C 5.x (runtime "Copyright (c) 1987"), medium model: 22 code segments reached by far calls
  (about 1 650 relocations), one DGROUP. The DSI assembly library from Test Drive (1987) is linked in
  largely unchanged; the game code is new.
* DGROUP: TD2EGA `178F`, TD2CGA `151D`, TD2TDY `1505`, found from the startup code
  (`mov di, DGROUP`). DS:x = image offset DGROUP×16 + x.
* Addresses in this repository are `SSSS:OOOO` with the segment as stored in the file; image offset =
  SSSS×16 + OOOO; Ghidra (loaded at 1000:0000) shows segment SSSS+1000.

TD2EGA segment map (`tools/td2index.py`):

| Segment | Size | Contents |
|---|---|---|
| `0000` | 3072 | `main`, disk-swap and `DISKID.DAT` checks, "Exit to DOS" |
| `00c0`, `010c` | 1216, 880 | title and Accolade screens, credits |
| `0143`, `019e` | 1456, 3216 | car/scenery selection, showroom and spec sheet, options, difficulty |
| `0267` | 7344 | gas station and stage results, record messages |
| `0432` | 8496 | `CARS.DAT` / `SCENES.DAT` / `select.dat`, Play Disk creation |
| `0645` | 1760 | high scores (`hisc.dat`) |
| `06b3` | 352 | (small) |
| `06c9` | 52640 | driving game (0000–5CFF, C and assembly) and the DSI assembly platform library (5D00–CD9F): graphics, text, timer, keyboard, joystick, resource and memory manager |
| `13a3`, `13a8` | 80, 12272 | Microsoft C runtime |
| `16a7`–`1769` | small | assembly helpers: resource list search, pause / exit prompt, `.PES` loader, joystick calibration |

## Packed files (Verified)

Every `.PES` and `.PCS` file is packed (the TD1 `Pckd`/ARC container is gone). The same scheme was used
later by DSI's *Stunts*.

```
u8   type          1 = RLE, 2 = Huffman, 0x80|k = k passes
u24  unpacked size
...  payload
```

* **Multi-pass** (`0x80|k`): the payload is k complete packed streams; each pass decodes the output of the
  previous one. All shipped files are `0x82` (Huffman, then RLE) except the European Challenge `.PCS`
  files, which are a single RLE pass.
* **Huffman** (type 2): `u8 n` (longest code), `n × u8` number of codes of each length, then the alphabet
  (sum of the counts). Codes are canonical: shortest first, increasing, shifted left when the length
  grows. The bitstream is read **LSB first** within each byte.
* **RLE** (type 1): `u32 packed length`, `u8 escape count` (bit 7 set = no sequence pass), then the
  escape codes. Escape *k* (1-based position in the list):
  * sequence pass, run first unless bit 7 is set: `esc2 bytes… esc2 n` repeats the bytes between the
    two `esc2` n times;
  * run pass: `esc1 n v` = `v` × n, `esc3 lo hi v` = `v` × (hi·256+lo), any other `esc_k v` = `v` × (k−1).
* All 164 archives (154 two-pass, 10 single-pass) and the 19 packed stage files (`<SCN>n.DAT`) decode to
  exactly the stored size, byte-identical to an emulation of the game's unpacker (`06c9:6d50`).

## Resource archive (Verified)

The decoded data has the TD1 layout:

```
u32  total_size
u16  count
count × char[4]  names
count × u32      offsets, relative to the end of this table (not in name order)
...  resource data
```

All 5 311 resources in the Collection are sprites (`EC_4.PCS` `mtn2` has 2 stray bytes at the end).

### Sprite resource

```
u16 width_in_bytes, u16 height, u16 hot_x, u16 hot_y, s16 x, s16 y, u8 planemap[4]
pixel data
```

* 4-colour (`.PCS`): `height × width` bytes, 2 bits/pixel (Verified).
* 16-colour (`.PES`): one `height × width` block per stored plane, 1 bit/pixel. A plane-map byte with a
  non-zero low nibble is a stored plane, and the nibble lists the colour planes it is written to
  (Verified: block count matches the size of every sprite).
* `planemap[0] >> 4`: planes cleared over the sprite rectangle; `planemap[1] >> 4`: planes set (or
  inverted by XOR blits); `planemap[3] >> 4`: padding bytes after each block (as in TD1). The list of
  stored planes ends at the first zero low nibble.
* `.PES`: `planemap[2] >> 4` is a per-block flag: bit `0x10 << k` means block k is stored **column by
  column** (`width` columns of `height` bytes). The loader (`1748:000e` → `06c9:c838`, "UNFLIP")
  converts flagged blocks to rows once; blitters never see the flags.
* `.PCS`: TD2EGA doesn't convert them. TD2CGA reads the `planemap[2]` high nibble as a storage mode:
  1 = column-major; 2 = column-major, each column its even rows then its odd rows; 3 = all even rows
  as one column-major block, then all odd rows. The rest of the plane map is ignored.
* Details and blitter semantics: `port/spec/platform.md`. All 5 310 sprites render cleanly with
  `tools/td2res.py`.
* Resource names ending in `M` are masks. `!PAT` (European Challenge) is a 16×1 pattern.

### Archive contents (from the contact sheets)

| Archive | Contents |
|---|---|
| `TESTDRV2`, `ACCOLADE`, `DSITITLE` | title ("The Duel", "Test Drive II"), publisher and developer logos |
| `<CAR>ST` | showroom: car side view and mask, wheel frames, window animation, logo, spec sheet `stat` |
| `<CAR>DASH` | cockpit: `dash`, `inst`, `roof` with the mileage display, steering wheel `whl1/3`, gear gate `gbox`, knobs, mirror, radar-detector lights, hood `hdcr`/`hdcM`, digits |
| `<CAR>REAR` | the car from behind, large and small (`logL`, `logS`) |
| `<CAR>ROAD` | the car on the road (opponent): 8 directions × 5 sizes, brake lights |
| `ROAD` | game over, gas-station sign, signs, road objects |
| `COP` | police car frames and light bars |
| `ENDGAME` | ending screens |
| `GAMEOPT`, `GAMEDIFF` | options screen (clock, computer car, scenery, instruments) and difficulty screen |
| `GASSTUFF` | gas station |
| `<SCN>n` | stage scenery: horizon (`hg`, `lg`, `md`, `sm` + distances), lines, rocks, etc. |
| `<SCN>CAR1-3` | traffic cars (front/rear × 8 sizes) |

## Car files (`tools/td2car.py` → `work/cars/<CAR>.json`; details in `port/spec/simulation.md` §5)

* `<CAR>.BIN`: 0x34F bytes copied to DS:23A6 when a stage starts (`0267:15e4`). Gear count, rpm limits
  (max, redline, up/downshift), a 32-bit grip constant, 7 gear ratios, 16 knob positions, a 9+9-byte
  shift gate, engine strength (+072), an 81-entry torque curve (+073); from +0C3 cockpit and gauge
  layout (needle / bar / digits per gauge, used by `scene_render`). `CAMA.BIN` has 49 extra bytes that
  the game never reads.
* `<CAR>O.BIN`: 16 opponent acceleration values by 8-mph speed band, loaded to DS:5616 only when the
  computer car is on. The police car uses a built-in copy of the F40 table.
* `<CAR>.SS`: text, `total_frames standing_frames ticks_per_frame`, then the 4-character window-frame
  sprite names run together (`port/spec/game_flow.md` §5).

## Stage files (`tools/td2road.py` → `work/roads/<STAGE>.json/.png`)

* `<SCN>n.DAT`: packed (same scheme as the archives); the unpacked data is a memory image of
  DS:346A–52C7 (the game copies a fixed 0x1E5E bytes, so shorter files leave the rest as it was — the
  port zero-fills). It holds the scenery archive name (first 20 bytes), a 128-entry road record table
  `[flags, curve, pitch, object]`, road-side object rings, right-side zones, colours and style flags,
  the stage length and finish unit, up to 50 pre-placed traffic cars per direction (positions in
  per-mille of the stage), then the road byte stream (bit 7 = wide road, low 7 bits = record index).
  One road unit = 256 sub-units ≈ 12.6 ft; results count 420 units per mile.
  Simulation fields: `port/spec/simulation.md` §5.3; drawing fields: `port/spec/scene_render.md` §5.
* `<SCN>n.SGN` (raw, optional; only `TDS20.SGN` in the base game): 20 billboard records with their text,
  drawn with the scenery's `.FNT` vector font.
* `<SCN>.FNT`: 64 u16 offsets (character − 0x20), then 4-byte line segments per glyph, each glyph ending
  with `FF FF` (`port/spec/platform.md`).

## Written files (`port/spec/game_flow.md` §5)

* `select.dat`: `%d %d %d %s %s %s` = drive of an extra car disk, drive of an extra scenery disk, drive
  of the play disk, your car, opponent car, scenery. Defaults `0 0 0 F40 P959 TDS2`.
* `<SCN>hisc.dat` (`TDS2hisc.dat`, `CCChisc.dat`, `ec_hisc.dat`): 340-byte dump of DS:90B8 — top-6 table
  (score, car code, name), per-stage records (best time and its average speed, best score, best
  cumulative time and score), 32-bit additive checksum. A missing file or bad checksum clears the table.

## Sound (`tools/td2snd.py` → `work/sound/`; `port/spec/platform.md`)

* PC speaker only (all builds). Timer 1193182 / 0x2E9C ≈ 100 Hz.
* `SONGS.BIN`: song table (4-byte entries) → lists of 3-byte entries (pattern offset + transpose) →
  2-byte events: `00` rest, `01–7F` note (length bit 7 = legato), `FF` restart, `FE` tempo, `FD` voice,
  `FC` next pattern, `FB`/`80–FA` stop.
* `VOICES.BIN`: 32-byte voice records. The shipped file is only CR LF; since it is loaded right before
  `SONGS.BIN`, voice 1 reads `SONGS.BIN` bytes 16–43 (all notes legato; song 1's last note bends down).
* Driving sounds use TD1's effect player, run from the timer routine list next to the driving tick.
