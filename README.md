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
* Port: not started.

## Layout

* `Game/` — your game files (not in the repository).
* `tools/` — reverse-engineering tools, see `FORMATS.md`.
* `port/` — function index, specs (`port/spec/`) and the guide for writing them (`port/RE_GUIDE.md`).
* `FORMATS.md` — decoded file formats and executable layout.

## Support

https://buymeacoffee.com/krzysztofkania
