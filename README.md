# Test Drive II: The Duel — SDL3 port

Work in progress. The goal is a faithful C reimplementation of the EGA version of Accolade / Distinctive
Software's *Test Drive II: The Duel* (1989), running natively on SDL3, in the same way as the
[Test Drive (1987) port](https://github.com/kylofon/test-drive-sdl3). It will not be an emulator. The
original data is not redistributed, and you need to get it yourself (the port targets
*Test Drive II: The Collection*, which includes the Supercars / Muscle Cars and California / European
Challenge add-ons).

## Status

* Reverse engineering: executables unpacked and indexed, file formats decoded, specs for game flow,
  scene rendering, simulation and platform written (`port/spec/`).
* Port: the EGA version (`TD2EGA.EXE`) is implemented and runs; testing against the original is in
  progress. CGA / Hercules (`TD2CGA.EXE`) and Tandy (`TD2TDY.EXE`) are not ported yet.

## Requirements

* Your game files in a folder (by default `Game` under the working directory). The port needs
  `TD2EGA.EXE`, `CARS.DAT`, `SCENES.DAT`, `SONGS.BIN`, `VOICES.BIN`, the `*.PES` archives, the car
  `*.BIN` / `*.SS` files and the scenery `*.DAT` / `*.SGN` / `*.FNT` files. `select.dat` and the
  `*hisc.dat` high-score files are written to the same folder.
* CMake 3.24+, a C11 compiler and SDL 3.

## Build

From the repository root, in Git Bash or an MSYS2 MinGW64 shell:

```bash
export PATH="/c/msys64/mingw64/bin:$PATH"
cmake -S td2port -B td2port/build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release
cmake --build td2port/build
```

## Run

```bash
./td2port/build/td2port.exe --game-dir Game
```

| Option | Meaning |
|---|---|
| `--game-dir DIR` | Folder with the original game files (default `Game`) |
| `--scale N` | Initial window size as a multiple of 320×240 (default 3) |
| `--frame-rate FPS` | Emulated drawing speed of the original PC while driving (default 15, `0` = unpaced) |
| `--check` | Verify that `TD2EGA.EXE` loads, then exit without opening a window |

Alt+Enter toggles fullscreen. A connected gamepad acts as the joystick (Ctrl-J to calibrate / enable).

## Controls (from the original)

* Arrow keys / numeric keypad: steer, accelerate, brake; shifting as in the original.
* Esc: quit the current drive or menu.
* Ctrl-P pause, Ctrl-X exit to DOS, Ctrl-S sound, Ctrl-Q music, Ctrl-K keyboard, Ctrl-J joystick.

## Changes from original

* **Removed:** copy protection and all disk handling (disk prompts, `DISKID.DAT`, Play Disk
  creation; the Install menu icon does nothing).
* **Frame rate:** the driving view is drawn at an emulated 15 fps (`--frame-rate`); the simulation runs
  on the original's 100 Hz timer as before.
* **Joystick:** a gamepad replaces the analogue PC joystick.

## Layout

* `Game/` — your game files (not in the repository).
* `tools/` — reverse-engineering tools, see `FORMATS.md`.
* `port/` — function index, specs (`port/spec/`) and the guide for writing them (`port/RE_GUIDE.md`).
* `td2port/` — the SDL3 port; `td2port/PORTING.md` describes its architecture and rules.
* `FORMATS.md` — decoded file formats and executable layout.

## Support

https://buymeacoffee.com/krzysztofkania
