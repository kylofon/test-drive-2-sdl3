# Porting rules — Test Drive II: The Duel → SDL3

Faithful reimplementation of **TD2EGA.EXE**. Behaviour, timing, integer arithmetic and visible quirks
must match the original. Specs: `../port/spec/*.md` (read `../port/RE_GUIDE.md` first) and
`../FORMATS.md`. Symbols: `../port/symbols.csv` → generated `src/symbols.h`
(`python ../tools/gen_symbols.py` from the repository root regenerates it after `merge_symbols.py`).
Ground truth when a spec is unclear: `python ../tools/x86dis.py ../work/TD2EGA_unp.exe dis SSSS:OOOO LEN`
(run from `td2port/`). The Test Drive (1987) port in `../../TestDrive1987/tdport` implements the same
assembly library and design and is a good model for code structure (not for addresses).

## Architecture

```
main.c        args, mem_load_exe(), host_init(), game_main()                                   (coordinator)
mem.h/.c      real-mode memory: TD2EGA.EXE image at segment 0x1000, DGROUP 0x278F, heap above     (coordinator)
host.h/.c     SDL3: window/present, 99.9985 Hz tick, raw XT scan codes, gamepad, speaker, files    (coordinator)
codeptr.h/.c  far code pointers stored in game data -> C functions                                 (coordinator)
symbols.h     generated DS_* / CS_* / FN_* constants                                               (coordinator)
platform/gfx.*      planar graphics: targets, buffers, blitters, fills, lines, plot, text, dissolves,
                    scroll, grabs, palette, video init/shutdown, frame composition            (graphics agent)
platform/res.*      memory manager, file loading, unpacker, UNFLIP, load_shapes, res_find, DOS helpers,
                    rand8, fatal, trig helpers of segment 13a3                                   (system agent)
platform/timer.*    timer ISR body, routine list, tick counters, delays / deadlines              (system agent)
platform/sound.*    effect stream player (sfx_tick) and SONGS.BIN music player (music_tick)      (system agent)
platform/input.*    INT 9 handler, key tables, getkey family, hotkeys, joystick, driving input,
                    pause / exit / message boxes (16fc), joystick calibration (1769)             (system agent)
game/game.h         cross-subsystem prototypes of the game code                                 (coordinator)
game/flow*.c        game_flow spec: main (game_main), screens, menus, results, scores           (flow agent)
game/scene*.c       scene_render spec: stage runner 06c9:1b2c, projection, drawing, cockpit     (scene agent)
game/sim*.c         simulation spec: driving tick 06c9:403b and everything it runs, 06b3:0008    (sim agent)
```

Only `host.c`, `mem.c`, `main.c` and `platform/res.c` (SDL_IOStream file access) include SDL. Game and platform code talks to the host through
`host.h`. Each module declares its API in its own header (`platform/gfx.h`, `game/flow.h`, ...).

## Memory model (`mem.h`)

* The original's data stays **in `mem[]` at its original address**. Every global, table, string, sprite
  pointer, the stage data image (DS:346A), the car `.BIN` (DS:23A6) and the heap blocks are read and
  written there: `DSW(DS_road_pos)`, `DSB(DS_opp_enabled)`, `ds_far(DS_page)`.
  Names come from `symbols.h`. For an offset without a name, write the raw offset with a comment:
  `DSW(0x1873) /* heading_acc */`. Never shadow game state in C variables that outlive a function.
* Code-segment variables of the assembly library (segment 06c9, e.g. the current target `CS:AF3A`)
  are `CSW(0xAF3A)` / `CSW(CS_gfx_cur)`. Other segments: `SEGW(0x16FC, off)`.
* **Pointers follow the original model (MSC medium model):** a near data pointer (`char *`, `int *` in
  the specs) is a DGROUP offset, passed as `u16` (`u16 name_ds`); a far pointer is a `FarPtr`
  `{off, seg}` passed by value. Sprites, archives, song streams and target descriptors are far
  pointers into `mem[]`. For string arguments that are DGROUP strings, use
  `(const char *)mp(DGROUP, off)` only inside the callee. Segment `0xA000` in a target means the EGA
  screen (graphics module only).
* Far code pointers stored in data (timer routine list, getkey pointer DS:64DC, handler tables) keep
  their relocated seg:off values in `mem[]`; map them with `codeptr.h`.
* Fixed-width arithmetic: use `u8/s8/u16/s16/u32/s32` exactly as the original register widths; cast at
  every step where the original truncates. Signed right shift = `(s16)x >> n`. Emulate carries/borrows
  explicitly where the asm uses `adc/sbb/rcl/rcr`. The MSC long helpers are plain `s32/u32` operators.
* **Division** goes through `div32_16 / idiv32_16 / div16_8 / idiv16_8` for every DIV/IDIV the original
  performs; a divide error ends the program with R6003, as the MSC runtime does.
* Keep the original's buffer overruns and aliasing when a spec marks them as faithful quirks, but never
  read or write outside `mem[]`.

## Timing (`host.h`, `platform/timer.h`)

* The host calls the tick handler installed by `timer_init()` at exactly 99.9985 Hz from `host_pump()`.
  It is the body of the timer ISR 06c9:61bf: counters, then the routine list (menus: `music_tick`;
  driving: `sfx_tick`, then the driving tick `06c9:403b`).
* **Every busy-wait loop in the original must call `host_pump()` once per iteration** (delays,
  deadlines, key polls, prompts, "wait for fire"). Platform wait helpers already do; game code that
  loops on its own must too.
* The stage runner's per-frame loop calls `host_frame_begin()` once at the top of each iteration
  (emulated drawing speed, `--frame-rate`, default 15). Ticks (and therefore the simulation) only
  advance inside `host_pump()`, so the renderer always sees a consistent state.
* Screen output is composed from the EGA planes by the graphics module (installed with
  `host_set_frame_source`) and presented by the host when something changed. Effects the original ran
  unpaced (dissolves, the title morph, the car slide) call `host_present_now()` after each step and are
  paced as the specs recommend.

## Input

* `host_set_scan_handler()` delivers XT make/break codes in event order; the input module implements
  the INT 9 handler 06c9:6907 on top of it (key-down table, translation, one-key buffer). Key repeats
  arrive as make codes, like typematic.
* A connected gamepad is the joystick (`host_joy_read`).

## Dropped / replaced (mark with `/* PORT: ... */`)

* Copy protection (13a8:002e): `mem_load_exe` writes the "passed" bytes; game code implements the
  passed behaviour (DS:007C = 0, DS:5656 = 0, stage_run returns DS:5490, driving jumps as JNE).
* Disk handling: `ensure_disk` always succeeds, no DISKID / Play Disk / hard-disk checks, the install
  menu icon does nothing, `select.dat` is written with drive fields `0 0 0`. Files are looked up
  case-insensitively in the game directory (`host_game_path`), written files go there too.
* Stage `.DAT` images shorter than the fixed 0x1E5E-byte copy: the rest is zero-filled.
* Video mode / port I/O / interrupt vectors: see `../port/spec/platform.md` §6.

## Porting a function

1. One C function per original function, named as in `symbols.h` (`FN_<name>`), with a leading comment
   `/* 06c9:403b drive_tick — simulation.md §4.1 */`. Assembly routines with register arguments become C
   functions with explicit parameters/returns named after the registers they model
   (`u16 proj_x(s16 bx, s16 dx)`).
2. Follow the spec pseudocode; confirm against the disassembly wherever the spec says `likely`/`guess`,
   or where signedness, carries or evaluation order matter.
3. Mark deliberate deviations with `/* PORT: ... */`. Mark unresolved doubts with
   `/* TODO(verify): ... */` and list them in your report.
4. No `static` game state: state lives in `mem[]` (a `static` is fine for pure host-side caches).
5. Don't reformat or restructure files owned by another module. If you need a declaration that isn't
   in a shared header, add it to **your own** header, and list it in your report.

## Build and checks

From `td2port/` with MinGW on PATH (`export PATH="/c/msys64/mingw64/bin:$PATH"`):

```
cmake -S . -B build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Debug
cmake --build build
./build/td2port.exe --game-dir ../Game --check
```

While other modules are unfinished the link may fail with undefined references to their functions;
that is expected. Your own files must **compile without warnings**. Check a single file with
`gcc -std=c11 -Wall -Wextra -Wno-unused-parameter -fno-strict-aliasing -fsyntax-only -Isrc -I/c/msys64/mingw64/include src/<file>.c`.
You may write throwaway verification programs in your scratch area (e.g. compare a blit or the
unpacker against `../tools/td2res.py`). Do not create HTML pages. Do not launch the game window.
