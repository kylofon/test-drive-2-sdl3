# Test Drive II: The Duel — SDL3 port

A faithful C reimplementation of the EGA version of Accolade / Distinctive Software's
*Test Drive II: The Duel* (1989), running natively on SDL3, in the same way as the
[Test Drive (1987) port](https://github.com/kylofon/test-drive-sdl3). It is not an emulator. The original
data is not redistributed, and you need to get it yourself. The port targets *Test Drive II: The Collection*,
which includes the Supercars / Muscle Cars and California / European Challenge add-ons.

## Download

Windows x64 builds are on the [Releases](https://github.com/kylofon/test-drive-2-sdl3/releases) page. Unzip,
then run:

```bash
td2port.exe --game-dir "C:\path\to\your\Test Drive II files"
```

The zip contains `td2port.exe`, `SDL3.dll` and `libiconv-2.dll`. Keep the three files together.

## Status

* The EGA version (`TD2EGA.EXE`) is ported and playable with the cars and sceneries of the Collection.
  Please report any difference from the original in the issues.
* The CGA / Hercules (`TD2CGA.EXE`) and Tandy (`TD2TDY.EXE`) versions are not ported yet.

## Requirements

* Your game files in a folder (by default `Game` under the working directory). The port needs
  `TD2EGA.EXE`, `CARS.DAT`, `SCENES.DAT`, `SONGS.BIN`, `VOICES.BIN`, the `*.PES` archives, the car
  `*.BIN` / `*.SS` files and the scenery `*.DAT` / `*.SGN` / `*.FNT` files.
* The folder must be writable. The game saves the last car / scenery choice to `select.dat` and each
  scenery's high scores to `<scenery>hisc.dat` there, as the original did.
* To build: CMake 3.24+, a C11 compiler and SDL 3.

## Build

From the repository root, in Git Bash or an MSYS2 MinGW64 shell:

```bash
export PATH="/c/msys64/mingw64/bin:$PATH"
cmake -S td2port -B td2port/build -G Ninja -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release
cmake --build td2port/build
```

The build copies `SDL3.dll` next to `td2port.exe`. The MSYS2 `SDL3.dll` also needs `libiconv-2.dll` from
`C:\msys64\mingw64\bin`. To run the program outside the MSYS2 shell, copy that DLL next to it too.

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

Alt+Enter toggles fullscreen. The window keeps the 4:3 aspect of the original monitor.

## Controls (from the original)

* Arrow keys / numeric keypad: steer, accelerate, brake. Shifting works as in the original.
* Esc: quit the current drive or menu.
* Ctrl-P pause, Ctrl-X exit to DOS, Ctrl-S sound, Ctrl-Q music, Ctrl-K keyboard, Ctrl-J joystick.
* A connected gamepad acts as the joystick: left stick or D-pad, A = button 1, B = button 2. Press Ctrl-J to
  calibrate and enable it.

## Changes from original

* **Removed:** copy protection and all disk handling: disk prompts, `DISKID.DAT` and Play Disk
  creation. The Install menu icon does nothing.
* **Frame rate:** the driving view is drawn at an emulated 15 fps (`--frame-rate`). The simulation runs on
  the original's 100 Hz timer as before. Screen dissolves and other effects that the original ran at CPU
  speed are paced to the timer.
* **Joystick:** a gamepad replaces the analogue PC joystick.
* **Graphics:** EGA only. The `herc` command-line argument of the original is not supported.
* **Errors:** a missing or unreadable game file is reported in a message box. A `CARS.DAT` /
  `SCENES.DAT` without entries shows an error instead of exiting silently.
* **Robustness:** overlong car / scenery lists and corrupt `*hisc.dat` files are handled safely, where the
  original overwrote memory.

## Layout

* `Game/` — your game files (not in the repository).
* `tools/` — reverse-engineering tools, see `FORMATS.md`.
* `port/` — function index, specs (`port/spec/`) and the guide for writing them (`port/RE_GUIDE.md`).
* `td2port/` — the SDL3 port. `td2port/PORTING.md` describes its architecture and rules.
* `FORMATS.md` — decoded file formats and executable layout.

## License

The port and tools are MIT licensed (see `LICENSE`). *Test Drive II* is © Accolade / Distinctive Software.
Its files are not part of this repository or the releases.

## Support

https://buymeacoffee.com/krzysztofkania
