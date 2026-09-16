# Reverse-engineering guide for the SDL3 port

Shared conventions for everyone writing port specs. Target: **TD2EGA.EXE** (EGA build). The CGA,
Hercules and Tandy builds come later.

This is the second DSI game we port. The Test Drive (1987) port in `../TestDrive1987` (see its
`port/spec/*.md`, `FORMATS.md` and `tdport/`) documents the same assembly library and a very similar
game design. Use it as a reference, but always verify against TD2's code: the game code is new and was
rebuilt with a newer compiler.

## Files

| Path | What |
|---|---|
| `work/TD2EGA_unp.exe` | EXEPACK-unpacked MZ (`tools/unexepack.py`); image offsets exclude the MZ header |
| `port/decomp/td2ega_ds.c` | Ghidra decompilation of every indexed function, DGROUP globals renamed to DS offsets |
| `port/decomp/td2ega_globals_xref.txt` | For each DS global: which functions use it |
| `port/td2ega_functions.json` / `.csv` | Capstone index: extent, near/far, callers/callees, DS reads/writes, strings, ints, ports, jump tables |
| `port/td2ega_td1_matches.csv` | TD2 functions that match a named TD1 function (candidate names; short functions match loosely) |
| `tools/x86dis.py work/TD2EGA_unp.exe dis SSSS:OOOO LEN` | Ground-truth disassembly when the decompile looks wrong |
| `tools/td2res.py`, `work/sheets/` | Archive decoder and contact sheets of every sprite |
| `FORMATS.md` | Already-decoded file formats |
| `_ghidra/TD2.gpr` | Ghidra project (`_tools/ghidra_12.1.3_PUBLIC/ghidraRun.bat`, JDK in `_tools/jdk-21*`) |
| `Game/` | Original game files (Test Drive II: The Collection) |

## Addresses

* The program is **segmented** (MSC 5 medium model): 22 code segments, far calls between them
  (`call far` = `9A`, returns `retf`), near calls inside a segment (the linker turns same-segment far
  calls into `push cs; call near`).
* Write code addresses as **`SSSS:OOOO`** with the segment as stored in the file: `06c9:403b`.
  Image offset = SSSS×16 + OOOO (`0x0ACCB`). Ghidra loads the image at segment `1000`, so the same
  function is `FUN_16c9_403b` in Ghidra; `port/decomp/td2ega_ds.c` has names rewritten back to
  `FUN_06c9_403b` but its `entry` comments still show Ghidra's `16c9:403b`.
* **DGROUP** is segment `0x178F` (image `0x178F0`). `DS:xxxx` = image `0x178F0 + xxxx`. C code always
  runs with DS = DGROUP; assembly routines that load DS themselves are flagged `sets_ds` in the index.
* In `td2ega_ds.c` a global is written `<type>_DSxxxx` (`i_DS536C`) or `DS_xxxx`. Far pointers are
  common (`pbRam…` and `CONCAT22(seg, off)` pairs); write them as `far ptr DS:xxxx` (offset word, then
  segment word) in the specs.
* Ghidra's `CONCAT11`, `._1_1_` etc. are byte-level artifacts of 16-bit code: simplify when writing specs.
* The decompiler sometimes shows `in_stack_…`/`unaff_…` for register arguments of assembly routines;
  describe those arguments by register (`AX`, `ES:DI`) in the spec.

## Known so far (don't re-derive, cite FORMATS.md)

* Packed file format (Huffman + RLE) and the resource archive / sprite header. Open: the high-nibble
  plane-map flags, see FORMATS.md.
* Segment map and which code is where (FORMATS.md, "Executables").
* Shared assembly library: `port/td2ega_td1_matches.csv`, e.g. `06c9:8a0c gfx_fill_rect`,
  `06c9:8582`/`06c9:c984 gfx_draw_line`, `06c9:a530`/`a547` text drawing, `06c9:abfa gfx_set_palette`,
  `06c9:90e8 gfx_init_ega`, `06c9:5f64`/`5fbc` Hercules init/shutdown, `06c9:6686 joy_read`,
  `06c9:780e rand8`. Look up what TD1's version does in `../TestDrive1987/port/spec/platform.md`, then
  check what changed.
* Strings: `06c9:6d50` "INVALID PACK TYPE" (unpacker), `06c9:6e59` `locateshape`,
  `06c9:70a3` `reservememory`, `06c9:72c6`… memory manager, `06c9:b0fe` "OUT OF ROW TABLE SPACE".
* `06c9:403b` loads DGROUP itself and has no callers: most likely the driving timer tick (as TD1's
  `sim_timer_isr`). `06c9:1b2c` (called from `0267:15e4`) looks like the stage runner.
* The disk-swap / `DISKID.DAT` / Play Disk code (`0000:0297`–`0000:0651`, parts of `0432`) is dropped
  by the port: document it briefly only.

## Subsystem split

| Spec file | Code | Scope |
|---|---|---|
| `game_flow` | segments `0000`–`06b3`; `16fc` (pause / exit prompt) | `main`, startup and resource loading, title / Accolade / DSI screens and credits, car and scenery selection, showroom and spec sheet (`.SS` animation), options and difficulty screens, `CARS.DAT` / `SCENES.DAT` / `select.dat`, stage results, gas station, record messages, high scores (`hisc.dat`), ending, "Exit to DOS", disk handling (briefly) |
| `scene_render` | `06c9:0000`–`06c9:3fff` | stage runner `06c9:1b2c` and its per-frame loop, road and scenery projection and drawing (front view and mirror view), road-side objects, signs, traffic / opponent / police drawing and scaling, cockpit, gauges, HUD and messages, page flipping |
| `simulation` | `06c9:4000`–`06c9:5cff` | driving tick `06c9:403b` and everything it runs: input → steering / throttle / brake / gears, engine, speed, damage and crashes, road look-ahead and object spawning, traffic, the opponent car (the duel), police, fuel, time and score counters, sound triggers; car `.BIN` / `O.BIN` and road `.DAT` / `.SGN` data as used by the simulation |
| `platform` | `06c9:5d00`–`06c9:cd9f`, `16a7`–`16eb`, `1748`, `1769`, CRT `13a3` / `13a8` | graphics primitives and planar blitters, sprite plane maps, video mode / palette (read the game's EGA palette), Hercules / CGA / Tandy branches, text and fonts (`.FNT`), timer ISR and its routine list, keyboard and joystick (calibration screen `1769`), sound and music driver (`SONGS.BIN`, `VOICES.BIN`), unpacker, resource and memory manager (`.PES` / `.ESH` loading, `UNFLIP`, `WINDOW`), DOS file wrappers; MS C runtime (just identify library functions) |

Ranges are approximate. If a function clearly belongs to another subsystem, list it in your table with
a "see `<spec>`" note instead of analysing it in depth. When you depend on another subsystem's function,
use its address and a descriptive name, and note it under Open questions if unsure.

## Deliverable format (one file per subsystem: `port/spec/<subsystem>.md`)

1. **Overview** – what the subsystem does, in a few paragraphs, with a call graph of its main functions.
2. **Function table** – `address | proposed name | signature | one-line purpose | confidence`.
   Confidence: `verified` (checked against disassembly/data), `likely`, `guess`.
3. **Globals table** – `DS offset | proposed name | type/size | meaning | written by | read by`.
4. **Pseudocode** – clean C for every non-trivial function, faithful to the original arithmetic
   (integer widths, signedness, shifts, overflow, `long` arithmetic helpers). Keep original constants in
   hex with a comment.
5. **File formats** – every data file the subsystem reads or writes, with field tables (these are
   merged into `FORMATS.md`).
6. **Hardware/DOS dependencies** – each interrupt, port, BIOS call, direct video memory access, with the
   SDL3 replacement.
7. **Timing** – what runs per frame vs per timer tick, tick rates, and anything frame-rate dependent.
8. **Differences from Test Drive (1987)** – where TD1's port can be reused as is, and what changed.
9. **Open questions** – what couldn't be resolved.

Also write `port/spec/<subsystem>_symbols.csv` with `kind,address,name,type,notes`
(`kind` = `func` or `global`; addresses as `06c9:403b` for functions and `DS:536C` for globals), so the
symbol sets can be merged into one table and applied back to Ghidra.
