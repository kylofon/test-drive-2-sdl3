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
| `CARS.DAT` | Installed cars: `CODE Long_Name` per line (10 cars in the Collection) |
| `SCENES.DAT` | Installed scenery disks: `CODE Name_With_Underscores stages` (`CCC` 7, `ec_` 6, `TDS2` 6) |
| `DISKID.DAT` | Disk identity for the disk-swap check (dropped by the port) |
| `<CAR>.BIN` (847 bytes), `<CAR>O.BIN` (32 bytes), `<CAR>.SS` | Car data, opponent data (unverified), showroom animation list |
| `<CAR>DASH`, `<CAR>REAR`, `<CAR>ROAD`, `<CAR>ST` | Cockpit, rear view, the car as seen on the road, showroom/spec sheet |
| `<SCN>.FNT`, `<SCN>n.DAT`, `<SCN>n.SGN` | Per-scenery font and per-stage road / sign data (not decoded yet) |
| `<SCN>CAR1-3`, `<SCN>ICON`, `<SCN>n` | Per-scenery traffic, selection icon and stage scenery archives |
| `SONGS.BIN`, `VOICES.BIN` | Music (not decoded yet) |
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
* All 164 multi-pass and 10 single-pass archives decode to exactly the stored size.

## Resource archive (Verified)

The decoded data has the TD1 layout:

```
u32  total_size
u16  count
count × char[4]  names
count × u32      offsets, relative to the end of this table (not in name order)
...  resource data
```

5 310 of the 5 311 resources in the Collection are sprites. The exception is `EC_4.PCS` `mtn2`, which
carries a 16-colour plane map.

### Sprite resource

```
u16 width_in_bytes, u16 height, u16 hot_x, u16 hot_y, s16 x, s16 y, u8 planemap[4]
pixel data
```

* 4-colour (`.PCS`): `height × width` bytes, 2 bits/pixel (Verified).
* 16-colour (`.PES`): one `height × width` block per stored plane, 1 bit/pixel. A plane-map byte with a
  non-zero low nibble is a stored plane, and the nibble lists the colour planes it is written to
  (Verified: block count matches the size of every sprite).
* `planemap[2]` bit `0x10` (both formats): the pixels are stored **column by column**, `width` columns of
  `height` bytes (Verified visually: title, spec sheets, cockpits).
* Open: the other high-nibble bits (`planemap[0]`/`[1]` `0xF0`, `planemap[2]` `0x20`, `0x40`). Some
  sprites (`<CAR>DASH` `dash` top rows, `<CAR>ST` `carS`) still render with noise, so at least one of
  them changes how the pixels are stored. Sprite masks come as separate resources (`carM`/`carS`,
  `hdcM`/`hdcr`).
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
