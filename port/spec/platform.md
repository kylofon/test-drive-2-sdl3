# Platform layer (TD2EGA.EXE `06c9:5d00`–`06c9:cd9f`, segments `16a7`–`16eb`, `1748`, `1769`; CRT `13a3`/`13a8`)

Conventions: `port/RE_GUIDE.md`. `DS:xxxx` = image `0x178F0 + xxxx`. `CS:xxxx` = a variable in segment
`06c9` (image `0x6C90 + xxxx`); the hand-written assembly keeps its graphics state there. "far ptr" =
offset word then segment word. TD1 = Test Drive (1987), `../TestDrive1987/port/spec/platform.md`
(its section numbers are cited as "TD1 4.x"). Scratch material (disassembly listings, helper
scripts, font renders) is in `work/platform/`.

**Corrections to FORMATS.md / RE_GUIDE.md found here**

* Plane map (header bytes `+0C..+0F`): low nibble of `pm[k]` = colour planes fed by stored block k (as
  documented); `pm[0] >> 4` = planes **cleared**, `pm[1] >> 4` = planes **set** (inverted by XOR blits),
  `pm[3] >> 4` = padding after each block (TD1 semantics, unchanged). `pm[2] >> 4` is **not** a
  sprite-wide flag: in .PES files bit `k` (0x10, 0x20, 0x40, 0x80) marks stored block k as
  column-major; the loader converts each flagged block (06c9:c838). In .PCS files (TD2CGA loader) the
  nibble is a storage mode 1–3 (column-major, per-column interlaced, two column-major fields).
  `tools/td2res.py` now decodes all 5 310 sprite resources this way.
* `EC_4.PCS mtn2` is an ordinary 2bpp sprite with plane map `01 02 04 08` (common in .PCS) and 2
  trailing bytes; it is not a 16-colour sprite.
* The archive offset table is **not** relocated in TD2 (TD1 did): resource pointers are computed on
  demand (06c9:c701).
* `06c9:403b` is the driving tick run from the timer-interrupt routine list; the timer ISR proper is
  `06c9:61bf` (section 4.14).
* `06c9:780e` is TD1's `rand8`; `06c9:8582` and `06c9:c984` are two different line routines (only
  8582 honours the colour on RAM targets).
* The EGA palette is the standard 16-colour 200-line palette (DS:6848), not TD1's custom one.
* There is no page flipping and no retrace wait in TD2EGA.
* Packed files: 164 archives in total (154 two-pass `0x82`, 10 single-pass RLE `0x01`), not "164 + 10";
  the stage road files `<SCN>n.DAT` are packed too. The RLE u32 field is the number of input bytes the
  RLE passes consume. The game's unpacker matches `tools/td2res.py` byte for byte on all of them (5.3).
* Segment `13a3` is not CRT (DSI 8.8 sine/cosine/tangent helpers); `13a8:0000–03f7` is copy protection.
  There is no MSC `rand`; `rand8` (06c9:780e, table DS:66E8) is the only random generator.

## 1. Overview

The range holds the DSI assembly library (graphics, input, timer, sound, resources) plus a few small C
helpers and the Microsoft C 5.x runtime. Most of it is TD1's library, recompiled for far calls and
extended:

1. **Planar graphics** (sections 2.1, 4.1–4.5). A current "target" (13-word descriptor copied to
   CS:AF3A) is either the EGA screen (A000h, driven through the sequencer/GC registers) or an
   off-screen RAM buffer laid out like a sprite (`gfx_create_buffer`). On top: 24 sprite blitters
   (REPLACE/OR/AND/XOR × clipped/unclipped × hotspot/raw/own), rectangle fills, clears, two line
   routines, a pixel plot, 8×8 text, two dissolve fades, a VRAM scroll, screen grabs. TD1's blitter
   bugs are fixed (left-clip carry, EGA XOR edges); the EGA constant-plane quirk remains. The .PES
   loader converts column-major plane blocks once after unpacking (`06c9:c838`). Mode 0Dh with the
   standard 16-colour palette; no page flipping, no retrace wait.
2. **Input** (2.2, 4.6–4.12). TD2 installs its own INT 9 (key-down table + one-key buffer + own
   translation tables) and INT 16h handlers. Menus read keys through a function pointer
   (`DS:64DC`) that also turns joystick moves into Enter/arrow codes and runs a Ctrl-key hotkey table
   (Ctrl-J/K/P/Q/S/X). Driving reads **held** keys (`06c9:6620`) or the joystick (TD1's adaptive
   `joy_read`). Pause, exit and message boxes are drawn over a saved screen area (`16fc`); the
   joystick calibration screen is `1769:000e`.
3. **Timer and sound** (2.3, 4.13–4.16). PIT channel 0 runs at 1193182 / 0x2E9C = 99.9985 Hz for
   the whole run. The ISR `06c9:61bf` counts ticks (32-bit game ticks, 20 Hz "slow" ticks), chains
   the BIOS every 5 ticks, and calls up to 5 routines from a list. Menus put the new SONGS.BIN
   pattern player (`06c9:75ea`) in the list; driving puts TD1's byte-code effect player
   (`06c9:6269`) and the driving tick (`06c9:403b`, simulation) there. PC speaker only, in every
   build.
4. **Resources and memory** (2.4, 4.17–4.28). Files are loaded whole into named blocks of one big
   DOS memory area ("reservememory"): a low stack of in-use blocks (new blocks go right after the last
   one) and a high cache of released archives that a later load of the same name moves back down.
   `.PES` archives are unpacked in place (Huffman + RLE, FORMATS.md), UNFLIPped, and looked up by
   4-character name ("locateshape"); `.ESH` (none shipped) would be loaded raw.
   Fatal errors go through `16a7:0002` (text mode, keyboard and timer restore, `printf`, `abort()` → exit code 3).
5. **C runtime** (2.5), segment `13a8` (its first 0x3F8 bytes are copy protection; `13a3` is a small DSI trig helper, not CRT): identification only.

```
main 0000:07b3
 ├─ herc_init 5f64 | gfx_init_ega 90e8 (mode 0Dh, palette DS:6848)
 ├─ kbd_set_getkey_fn 6a17(getkey_menu 65c5) ─ hotkeys_install 16fc:0002 ─ kbd_install 6860 (INT 9, INT 16h)
 ├─ timer_install_div 6059(0x2E9C) ─ timer_add_routine 614c(music_tick 75ea) ─ gfx_video_hook 5d00
 ├─ load_raw_file 6d18("voices.bin"), ("songs.bin") ─ music_set_voices 75c8 ─ music_play 758a(songs, 1)
 ├─ gfx_create_buffer b0fe(320, 200, 0Fh) → DS:8CA2
 └─ exit: timer_restore 610a ─ kbd_restore 68c4 ─ video_shutdown 5fbc | gfx_shutdown 642e

screens (game_flow): select_target(buffer) ─ clear_clip 843e ─ blits ─ load .PES 1748:000e
                     ─ select_target(screen CS:AF54) ─ blit_copy / gfx_dissolve4 8cd8 / gfx_dissolve8 8f12
                     menu_key: getkey 69fe ─ [DS:64DC] getkey_menu 65c5 ─ INT 16h 69b7 ─ kbd_dispatch 6528 ─ hotkey
                                                                        └ joy_read 6686
driving (scene_render / simulation):
  stage init 06c9:3f40 ─ timer_install_drive 601c ─ add(sfx_tick 6269) ─ add(drive_tick 403b)
  stage runner 1b2c ─ sfx_set_loop 7946(DS:1352) … frames: select buffer DS:09B2 → blits → select screen → blit
INT 8 → timer_isr 61bf ─ [bios_chain 6230] ─ routine list: music_tick 75ea | sfx_tick 6269, drive_tick 403b ─ PIT ch2 / port 61h
        drive_tick → input_drive_bits 6620 (key_down[] | joy_read) ; getkey_drive 6601 ─ kbd_dispatch
INT 9  → kbd_int9_isr 6907 ─ key_down[] / kbd_last_key
load   → load_shapes 1748:000e ─ unpack_file 6d50 (rle 6b02 / huff 7c16) ─ reservememory 70a3("UNFLIP") ─ res_unflip_archive c838 ─ free 7490
         res_find 6e59 ("locateshape") / res_find_list 16eb:000a
fatal  → 16a7:0002 ─ gfx_shutdown 642e ─ kbd_restore 68c4 ─ timer_restore 610a ─ printf ─ abort
```

## 2. Function table

### 2.1 Graphics

| address | proposed name | signature | one-line purpose | confidence |
|---|---|---|---|---|
| 06c9:5d00 | gfx_video_hook | `void (void)` | Empty `retf`. TD2CGA has a palette restore here (3D8h=0Eh, 3D9h=30h). Called by main after timer setup, by the stage runner 06c9:1b2c and after the crash flash 06c9:3532 | verified |
| 06c9:5d9e | gfx_set_clip | `void (far Desc *d, s16 x0, s16 x1, s16 y0, s16 y1)` | Writes the clip into the descriptor; also into the live copy if `d->plane_seg[0]` equals the current one. No direct callers found | verified |
| 06c9:5dfb | gfx_set_clip_current | `void (s16 x0, s16 x1, s16 y0, s16 y1)` | Writes only the live copy CS:AF46..AF4C (byte columns, rows; x1/y1 exclusive) | verified |
| 06c9:5f64 | herc_init | `void (void)` | DS:5E6E=1, equipment bits 4–5 = 10b, INT 10h mode 4, 3BFh=3, 3B8h=2, 6845 from DS:5E70, clear B800h, 3B8h=8Ah | verified |
| 06c9:5fbc | video_shutdown | `void (void)` | DS:5E6E==0 → gfx_shutdown 06c9:642e; else Hercules text mode (DS:5E7C, INT 10h mode 7) | verified |
| 06c9:642e | gfx_shutdown | `void (void)` | clear_screen(0), equipment bits 4–5 = 01b, INT 10h AX=0003h, INT 10h AH=0Bh BX=0 | verified |
| 06c9:780e | rand8 | `u8 (void)` | Table PRNG DS:66E6/DS:66E8 (identical to TD1) | verified |
| 06c9:782c | gfx_free_buffer | `void (far Desc *d)` | Row pool CS:B269 −= (h+0x0D)*2, frees the buffer block via 06c9:7490 | verified |
| 06c9:78f8 | gfx_targets_save | `void (u16 *dst)` | Copies 26 words CS:AF3A (live copy + screen descriptor) to DS:dst | verified |
| 06c9:7918 | gfx_targets_restore | `void (u16 *src)` | Inverse of 78f8 | verified |
| 06c9:7d5e | gfx_select_target | `void (far Desc *d)` | Copies 13 words of the descriptor to CS:AF3A (no pointer kept) | verified |
| 06c9:7d7c / 7d9c / 7dbc | blit_and_clip_hot / _raw / _own | `void (u16 off, u16 seg [, s16 x, s16 y])` | Clipped AND blit; body 06c9:9189/91c1/91f3; RAM table CS:7DDC, EGA table CS:9572, GC func 08h, flags 1 | verified |
| 06c9:808a / 80aa / 80ca | blit_and_hot / _raw / _own | same | Unclipped AND; body 9c75/9cad/9cdf; RAM CS:80EA, EGA CS:9FAE | verified |
| 06c9:82d0 | rect_clear_plane | asm: ES:DI dst, DX n, SI rows, CX row skip, BX shift, AL edge flags | RAM constant-plane clear | verified |
| 06c9:8336 | rect_set_plane | same | RAM constant-plane set | verified |
| 06c9:839c | rect_xor_plane | same | RAM constant-plane invert | verified |
| 06c9:840a | gfx_clear_screen | `void (u8 colour)` | A000h, write mode 2, map mask 0Fh, 8000 bytes | verified |
| 06c9:843e | gfx_clear_clip | `void (u8 colour)` | Fills the current clip rectangle; EGA quirks of TD1 fixed | verified |
| 06c9:8582 | gfx_draw_line | `void (s16 x0, s16 y0, s16 x1, s16 y1, u8 colour)` | Clipped line, pixel = colour on RAM and screen targets | verified |
| 06c9:89a2 | gfx_fill_rect_clip | `void (s16 x, s16 y, s16 w, s16 h, u8 colour)` | Clips to the current clip (x in pixels = clip×8) then fill_rect body | verified |
| 06c9:8a0c | gfx_fill_rect | `void (s16 x, s16 y, s16 w, s16 h, u8 colour)` | Unclipped pixel rectangle; returns if w≤0 or h≤0 | verified |
| 06c9:8cd8 | gfx_dissolve4 | `void (u16 off, u16 seg, u8 phase)` | Screen-only dissolve, 4-phase mask table CS:8C84 (11 88 44 22) | verified |
| 06c9:8f12 | gfx_dissolve8 | `void (u16 off, u16 seg, u8 phase)` | Screen-only dissolve, 8-phase mask table CS:8EBA (TD1 0x768B) | verified |
| 06c9:90e8 | gfx_init_ega | `void (void)` | GC reset, clear_screen(0), equipment colour, INT 10h mode 0Dh, palette DS:6848 | verified |
| 06c9:916c / 91a4 / 91d6 | blit_copy_clip_hot / _raw / _own | same | Clipped REPLACE; RAM CS:9562, EGA CS:9572, func 00h, flags 3 | verified |
| 06c9:9c58 / 9c90 / 9cc2 | blit_copy_hot / _raw / _own | same | Unclipped REPLACE; RAM CS:9F9E, EGA CS:9FAE | verified |
| 06c9:a6d8 / a6f8 / a718 | blit_or_clip_hot / _raw / _own | same | Clipped OR; RAM CS:A738, EGA CS:9572, func 10h, flags 2 | verified |
| 06c9:a9d2 / a9f2 / aa12 | blit_or_hot / _raw / _own | same | Unclipped OR; RAM CS:AA32, EGA CS:9FAE | verified |
| 06c9:abfa | gfx_set_palette | `void (u16 ds_table)` | INT 10h AX=1002h, ES:DX = DS:table (17 bytes) | verified |
| 06c9:ac1c / ac40 / ac64 | grab_into_sprite_hot / _raw / _own | `void (u16 off, u16 seg [, s16 x, s16 y])` | Screen (A000h) → the sprite's stored planes; `_raw` also writes x,y into the header; `_own` uses x & ~7 | verified |
| 06c9:ad22 / ad8b / adf4 | rect_clear/set/xor_plane_ega | asm as 82d0 | EGA constant-plane helpers (read-modify-write; quirks, see 4.2) | verified |
| 06c9:ae62 | gfx_scroll_window | `void (s16 x, s16 y, s16 w_bytes, s16 h, s16 step, u16 soff, u16 sseg, s16 srow)` | Write-mode-1 VRAM scroll + one sprite row (caller 019e:009b) | verified |
| 06c9:b0fe | gfx_create_buffer | `far Desc *(u16 width_px, u16 h, u16 plane_mask)` | Off-screen planar buffer = sprite ("WINDOW" block), descriptor in CS row pool | verified |
| 06c9:ba3c | gfx_plot | `void (s16 x, s16 y, u8 colour)` | One pixel = colour (RAM: present planes; EGA: write mode 2 + bit mask) | verified |
| 06c9:bac8 / bae8 / bb08 | blit_xor_clip_hot / _raw / _own | same | Clipped XOR; RAM CS:BB28, EGA CS:BB38 (own table), func 18h, flags 4 | verified |
| 06c9:c132 / c152 / c172 | blit_xor_hot / _raw / _own | same | Unclipped XOR; RAM CS:C192, EGA CS:C1A2 | verified |
| 06c9:c784 | gfx_grab_screen | `void (s16 sx, s16 sy, s16 dx, s16 dy, s16 w_px, s16 h)` | Screen rectangle → current RAM target (x and w in pixels, >>3) | verified |
| 06c9:c838 | res_unflip_archive | `void (far arc, far tmp)` | After unpacking a .PES: converts every column-major plane block to row-major | verified |
| 06c9:c958 | draw_cursor_glyph | `void (s16 x, s16 y, u16 idx)` | XOR blit of CS glyph `idx` (0,1 thin underline CS:C910; ≥2 thick CS:C928) at x&~7 (text editor 16bb:000a) | verified |
| 06c9:c984 | gfx_draw_line_or | `void (s16 x0, s16 y0, s16 x1, s16 y1, u8 colour)` | TD1-style line: screen OR colour, RAM targets OR every present plane; used only by 1769:000e | verified |

### 2.2 Input, hotkeys, prompts, text

| address | proposed name | signature | one-line purpose | confidence |
|---|---|---|---|---|
| 06c9:645a | hotkey_joystick_on | hotkey handler (near, `retf`) | DS:6CFC=1; modal pause on; calibration screen `1769:000e` (Ctrl-J) | verified |
| 06c9:646f | hotkey_keyboard_on | hotkey handler | DS:6CFC=0; message "KEYBOARD ON" (Ctrl-K) | verified |
| 06c9:6488 | hotkey_sound_toggle | hotkey handler | toggle DS:5EFB bit0, "SOUND ON"/"SOUND OFF" (Ctrl-S); see sound spec | verified |
| 06c9:64c7 | hotkey_music_toggle | hotkey handler | toggle DS:5EFB bit1, "MUSIC ON"/"MUSIC OFF" (Ctrl-Q); see sound spec | verified |
| 06c9:6508 | hotkey_pause | hotkey handler | DS:5EFE=1; `16fc:0358` pause prompt; DS:5EFE=0 (Ctrl-P) | verified |
| 06c9:6518 | hotkey_exit | hotkey handler | DS:5EFE=1; `16fc:007c` exit prompt; DS:5EFE=0 (Ctrl-X) | verified |
| 06c9:6528 | kbd_dispatch | `u16 (u16 key)` | run hotkey handler for key → 0, else return key; re-entrancy guard DS:6252 | verified |
| 06c9:6585 | hotkey_set | `void (u16 key, u16 handler_off, u16 seg_unused)` | DS:6048[key] = handler (ASCII only; extended-key path is broken) | verified |
| 06c9:65b4 | getkey_raw_nb (dead) | `u16 (void)` | unreferenced copy of 6a03's tail (no function header) | verified |
| 06c9:65c5 | getkey_menu | `u16 (void)` | key via kbd_dispatch, else joystick edge → 0x0D / scan<<8 | verified |
| 06c9:6601 | getkey_drive | `u16 (void)` | typed key for the sim (with hotkeys); SS≠DS → peek only | verified |
| 06c9:6620 | input_drive_bits | `u16 (void)` | held-key direction/fire bits, else joy_read | verified |
| 06c9:6686 | joy_read | `u16 (void)` | port 201h read + adaptive calibration → bits (TD1 0xA12F) | verified |
| 06c9:680a | joy_calib_reset | `void (void)` | joystick on, xmin=ymin=0x50, xmax=ymax=0 | verified |
| 06c9:6828 | joy_dir_index | `u16 (u16 bits)` | DS:629E[bits&0xF] → 0 C,1 N,2 NE,3 E,4 SE,5 S,6 SW,7 W,8 NW | verified |
| 06c9:6839 | joy_analog_x (dead) | `s16 (void)` | ((x−xmin)·xscale >> 8) − 0x1F; no callers | verified |
| 06c9:684c | joy_analog_y (dead) | `s16 (void)` | same for y | verified |
| 06c9:6860 | kbd_install | `void (void)` | hook INT 9 → 6907 and INT 16h → 69b7 (once), clear key table | verified |
| 06c9:68c4 | kbd_restore | `void (void)` | restore INT 9 / INT 16h, clear BIOS shift bits 0040:0017 low nibble | verified |
| 06c9:6907 | kbd_int9_isr | INT 9 handler | port 60h → key-down table + translated last key; EOI | verified |
| 06c9:69b7 | kbd_int16_isr | INT 16h handler | AH=0 read&clear, AH=1 peek (ZF), AH=2 Shift state, else AX=0 | verified |
| 06c9:69f2 | key_is_down (dead) | `u8 (u16 scan)` | DS:62BA[scan]; no callers | verified |
| 06c9:69fe | getkey | `u16 (void)` | far call through DS:64DC | verified |
| 06c9:6a03 | getkey_raw | `u16 (void)` | INT 16h peek/read; ASCII → AH cleared; 0 if none | verified |
| 06c9:6a17 | kbd_set_getkey_fn | `void (u16 off, u16 seg)` | DS:64DC/64DE = far ptr | verified |
| 06c9:6a28 | kbd_get_getkey_fn | `far ptr (void)` | returns DS:64DC in DX:AX | verified |
| 06c9:6a30 | getkey_wait | `u16 (void)` | loop getkey until non-zero | verified |
| 06c9:6a3b | kbd_flush | `u16 (void)` | read INT 16h until empty; returns 0 | verified |
| 06c9:6a4a | getkey_until_deadline | `u16 (void)` | getkey until game ticks ≥ DS:6818 (u32), then 0 | verified |
| 06c9:6a6a | getkey_timeout | `u16 (u32 ticks)` | getkey for `ticks` game ticks, 0 on timeout | verified |
| 06c9:7a82 | gfx_set_text_colours | `void (u16 fg, u16 bg)` | DS:6820 = fg, DS:6822 = bg | verified |
| 06c9:7a93 | gfx_set_text_cursor (dead) | `void (u16 x, u16 y)` | DS:6826 = x, DS:6828 = y | verified |
| 06c9:7aa4 | text_state_save | `void (u16 *buf22)` | copy 11 words DS:6820..6835 | verified |
| 06c9:7abd | text_state_restore | `void (u16 *buf22)` | inverse | verified |
| 06c9:a530 | gfx_draw_text | `void (char *s, u16 x, u16 y)` | set cursor, fall into a54f | verified |
| 06c9:a547 | gfx_draw_text_at_cursor | `void (char *s)` | draw at DS:6826/6828 (no callers in TD2) | verified |
| 16aa:0002 | toupper_c | `int (char c)` | a–z → A–Z, sign-extended | verified |
| 16ab:000c (image 0x16ABC) | draw_text_centered | `void (char *s, u16 y)` | x = (s16)target_width/2 − strlen·4 → a530 | verified |
| 16af:0006 | draw_rect_outline | `void (x0, y0, x1, y1, colour)` | 4 × gfx_fill_rect 06c9:8a0c | verified |
| 16fc:0002 | hotkeys_install | `void (void)` | installs the six Ctrl hotkeys | verified |
| 16fc:007c | prompt_exit_to_dos | `void (void)` | "EXIT TO DOS (Y/N)" box; Y → restore and exit(0) | verified |
| 16fc:0220 | message_box | `void (char *s, u32 ticks)` | one-line bar at y=190 for `ticks` real-time ticks | verified |
| 16fc:0358 | prompt_pause | `void (void)` | "PAUSE - PRESS ANY KEY TO RESUME" box until a key | verified |
| 1769:000e | joy_calibrate_screen | `void (void)` | full-screen 3×3 calibration | verified |
| 06c9:16ce–1853 | (part of scene_render 06c9:0d13) sign_draw | inline | .SGN record → board, posts, FNT text | verified (format part) |

Note: the `16ab`, `16aa` "segments" in the index are not real segment boundaries; `16ab:000c` is the
same code as `16aa:001c` (image 0x16ABC). Use the image offset when in doubt.

### 2.3 Timer, sound, tick helpers

| address | proposed name | signature | one-line purpose | confidence |
|---|---|---|---|---|
| 06c9:5d1e | wait_key_paused | `void (void)` (near-callable body, no direct callers) | pause flag = 1, `getkey_wait()`, pause flag = 0 | verified |
| 06c9:601c | timer_install_drive | `void far (void)` | chain reload 5, BIOS chaining counts down 100 BIOS calls then stops (`5E95` left as it is), divisor 0x2E9C | verified |
| 06c9:603c | timer_install_menu | `void far (void)` | chain reload 5, chain forever, divisor 0x2E9C; no callers | verified |
| 06c9:6059 | timer_install_div | `void far (int div)` | reload = 0x10000/div, chain forever, divisor = div (called with 0x2E9C) | verified |
| 06c9:607a | timer_install_div_countdown | `void far (int div)` | reload = 0x10000/div, countdown 100, divisor = div; no callers | verified |
| 06c9:6099 | timer_install_common | (tail, DX = divisor) | clears the routine list, silences the speaker, hooks INT 8, programs PIT ch0 | verified |
| 06c9:610a | timer_restore | `void far (void)` | unhooks INT 8 if it is ours, PIT ch0 = 65536, speaker off | verified |
| 06c9:614c | timer_add_routine | `void far (void far (*fn)(void))` | appends to the 5-slot list; fatal "NO ROOM LEFT ON TIMER INTERRUPT ROUTINE LIST" | verified |
| 06c9:6180 | timer_remove_routine | `void far (void far (*fn)(void))` | removes the entry and shifts the rest down | verified |
| 06c9:61bf | timer_isr | `interrupt` | INT 8 handler (see 4.14) | verified |
| 06c9:6230 | timer_bios_chain | near, internal | countdown of BIOS calls, then calls the old INT 8 through the IVT | verified |
| 06c9:6269 | sfx_tick | `void far (void)` (timer routine) | effect/engine byte-code stream player | verified |
| 06c9:758a | music_play | `void far (u8 far *songs, int n)` | starts song n if DS:5EFB == 3 | verified |
| 06c9:75c8 | music_set_voices | `void far (u8 far *voices)` | DS:65F7:65F9 = voices | verified |
| 06c9:75d9 | music_set_6625 | `void far (u16 w6627, u16 w6625)` | writes DS:6625/6627 (never read); no callers | verified |
| 06c9:75ea | music_tick | `void far (void)` (timer routine) | SONGS.BIN player (4.16) | verified |
| 06c9:7934 | sound_off | `void far (void)` | bit0 clear, stream seg = 0; no callers | verified |
| 06c9:7940 | sound_on | `void far (void)` | bit0 set; no callers | verified |
| 06c9:7946 | sfx_set_loop | `void far (u8 far *s)` | sets the looping stream; starts it now if no one-shot is active | verified |
| 06c9:7971 | sfx_clear_loop | `void far (void)` | DS:5EFD = 0 | verified |
| 06c9:7977 | sfx_play | `void far (u8 far *s)` | starts a one-shot stream now (note count not reset) | verified |
| 06c9:798f | sfx_is_playing | `int far (void)` | returns DS:5EFC; no callers | verified |
| 06c9:7995 | sfx_stop | `void far (void)` | stream seg = 0; no callers | verified |
| 06c9:799c | sfx_play_if_enabled | `void far (u8 far *s)` | sfx_play only if DS:5EFB == 3; no callers | verified |
| 06c9:79bb | music_on | `void far (void)` | bit1 set; no callers | verified |
| 06c9:79c1 | music_off | `void far (void)` | bit1 clear (no stop); no callers | verified |
| 06c9:79c8 | ticks_get | `long far (void)` | DX:AX = DS:5E8C (cli/sti) | verified |
| 06c9:79d2 | ticks_since | `long far (long t)` | now − t; no callers | verified |
| 06c9:79ea | ticks_lap | `long far (void)` | now − DS:681C, DS:681C = now; no callers | verified |
| 06c9:7a07 | ticks_reset | `void far (void)` | DS:5E8C = 0; no callers | verified |
| 06c9:7a10 | deadline_set | `void far (long n)` | DS:6818 = now + n | verified |
| 06c9:7a27 | deadline_wait | `void far (void)` | busy-waits until now ≥ DS:6818 | verified |
| 06c9:7a3b | deadline_passed | `int far (void)` | 1 if now ≥ DS:6818 | verified |
| 06c9:7a55 | delay_ticks | `void far (long n)` | busy-waits n ticks | verified |
| 06c9:c63e | getkey_until_slow_deadline | `int far (void)` | getkey until key or slow ≥ DS:68D6 (buggy compare) | verified |
| 06c9:c65c | wait_key_slow | `int far (long n)` | getkey for up to n slow ticks; no callers | verified |
| 06c9:c692 | slow_ticks_get | `long far (void)` | DX:AX = DS:5E90 | verified |
| 06c9:c69c | slow_deadline_set | `void far (long n)` | DS:68D6 = slow + n | verified |
| 06c9:c6b3 | slow_deadline_wait | `void far (void)` | busy-waits (buggy compare); no callers | verified |
| 06c9:c6c5 | delay_slow | `void far (long n)` | busy-waits n slow ticks (buggy compare); used by `16fc:0220` and `1769:000e` | verified |
| 06c9:412c | drive_sound_update | near (driving tick, every tick) | slews rpm, writes DS:5F2E slots 0x55/0x56/0x58 (see simulation) | verified (sound part) |

### 2.4 Resources, memory manager, DOS helpers, CRT

| address | proposed name | signature | one-line purpose | confidence |
|---|---|---|---|---|
| 06c9:5d01 | far_memcpy | `void (u16 soff, u16 sseg, u16 doff, u16 dseg, u16 n)` | `rep movsb` between far buffers (n==0 copies nothing) | verified |
| 06c9:5d2e | make_tick_id | `char *(void)` | int 1Ah/00 tick count masked into 4 high-bit bytes at DS:52C2, returns DS:52C2 | verified |
| 06c9:5d4e | dos_num_drives | `int (void)` | AH=19h then AH=0Eh with the current drive: returns the number of logical drives | verified |
| 06c9:5d5b | set_file_hidden | `int (char *name)` | AX=4301h CX=2. Returns 1 on error, 0 on success | verified |
| 06c9:5d74 | bios_floppy_count | `int (void)` | int 11h: ((equip>>6)&3)+1, but at least 2 | verified |
| 06c9:5d83 | bios_ticks | `u16 (void)` | Low word of 0040:006C | verified |
| 06c9:5d8d | bios_ticks_since | `u16 (u16 t0)` | `0040:006C − t0` (16-bit) | verified |
| 06c9:5e1c | file_paras | `u16 (char *name)` | File size in paragraphs, rounded up (16-bit). Fatal "%s FILE ERROR" if open fails | verified |
| 06c9:5e8a | unpacked_paras | `u16 (char *name)` | Reads 4 bytes and returns the u24 at +1 in paragraphs, rounded up. Fatal on open error or short read | verified |
| 06c9:5ef4 | find_first | `char *(char *spec)` | AH=4Eh attr 6, DTA DS:5DEE. Returns DS:5D88 = directory part of spec + found name, or 0 | verified |
| 06c9:5f4e | find_next | `char *(void)` | AH=4Fh, same result buffer | verified |
| 06c9:6aa2 | load_file_at | `far ptr (char *name, u16 off, u16 seg)` | Reads the whole file in 0x4000-byte chunks to seg:off. Fatal "%s FILE ERROR\r" | verified |
| 06c9:6b02 | rle_decode | `far ptr (in_off, in_seg, out_off, out_seg, u16 total_paras)` | Type-1 pass. Returns out_seg:0000, **not** a length | verified |
| 06c9:6b97 | rle_run_pass | near, frame of 6b02 | Run pass (escape table lookup) | verified |
| 06c9:6c6e | rle_seq_pass | near, frame of 6b02 | Sequence pass. Returns DX:AX = output length | verified |
| 06c9:6d18 | load_raw_file | `far ptr (char *name)` | Cache check, then reserve file_paras and load the file unchanged | verified |
| 06c9:6d50 | unpack_file | `far ptr (char *name)` | Cache check, reserve, load, 1..k passes. "%s INVALID PACK TYPE" | verified |
| 06c9:6e4e | res_find_opt | `far ptr (far ptr arc, char *name4)` | res_find that returns 0:0 when the name is missing | verified |
| 06c9:6e59 | res_find | `far ptr (far ptr arc, char *name4)` | "locateshape": 4-char lookup, normalized far ptr. Fatal if missing | verified |
| 06c9:6f1e | mem_init | `void (u16 top_seg)` | First call: DOS block from 100 paras up to top_seg. Every call: clears all records | verified |
| 06c9:6f86 | mem_init_default | `void (void)` | `mem_init(0xA000)`. Called from main | verified |
| 06c9:6f93 | mem_init_reserve | `void (u16 paras)` | mem_init(0xA000), then lowers the heap top by `paras`. No callers found | verified |
| 06c9:6fb2 | mem_gap | `u16 (void)` | cache start − end of the low stack (paras). No callers found | verified |
| 06c9:6fc4 | mem_low_used | `u16 (void)` | end of the low stack − heap base. No callers found | verified |
| 06c9:6fd6 | mem_free_total | `u16 (void)` | heap top − end of the low stack (free space if the whole cache were dropped). Caller 0432:04f1 | verified |
| 06c9:6fe8 | far_copy_down | `void (u16 src_seg, u16 dst_seg, u16 paras)` | Forward paragraph copy in 64 KB chunks (dst < src) | verified |
| 06c9:7030 | far_move_up | `void (u16 src_seg, u16 dst_seg, u16 paras)` | Backward paragraph copy (memmove for dst > src) | verified |
| 06c9:7083 | path_basename | `char *(char *path)` | Pointer after the last `:` or `\` | verified |
| 06c9:70a3 | mem_reserve | `far ptr (char *name, u16 paras)` | "reservememory": push a block on the low stack, evicting cache entries | verified |
| 06c9:7147 | cache_compact | `void (void)` | Packs the kept (flag bit 0) cache blocks against the heap top | verified |
| 06c9:71b4 | mem_reclaim_cached | `far ptr (char *name)` | If `name` is cached, move it to the low stack and return it, else 0:0 | verified |
| 06c9:7273 | mem_is_cached | `int (char *name)` | 1 if `name` is in the cache region | verified |
| 06c9:72c6 | mem_release_cache_old | `far ptr (far ptr blk)` | Frees a low block and, if it fits, caches it at the **bottom** of the cache (evicted first) | verified |
| 06c9:736b | mem_release_cache | `far ptr (far ptr blk)` | Frees a low block and caches it at the **top** (shifts the cache down; evicted last) | verified |
| 06c9:7490 | mem_free | `void (far ptr blk)` | Frees a low block (no caching) | verified |
| 06c9:74d4 | mem_size | `u16 (far ptr blk)` | Block size in paragraphs. No callers found | verified |
| 06c9:7501 | mem_slide_down | `far ptr (far ptr blk)` | Moves a block down onto the previous in-use block. No callers found | verified |
| 06c9:7866 | write_file_or_die | `int (char *name, u16 off, u16 seg, u32 len)` | Create and write in 0x4000 chunks. Fatal "%s FILE ERROR" (hisc.dat) | verified |
| 06c9:7874 | write_file | same | Same, errors ignored, always returns 0 (0432:04f1) | verified |
| 06c9:7c16 | huff_decode | `u32 (in_off, in_seg, out_off, out_seg, u16 total_paras)` | Type-2 pass. Returns the u24 size from its header | verified |
| 06c9:c701 | res_by_index | `far ptr (far ptr arc, u16 k)` | Normalized far ptr of resource k | verified |
| 13a3:0006 | cos_deg8 | `s16 (AL=deg)` | 8.8 cosine: sin(deg+90) (8-bit add, unsigned index) – **not CRT** | verified |
| 13a3:0012 | sin_deg8 | `s16 (AL=s8 deg)` | 8.8 sine from the 0..90° table DS:54AA (256 = 1.0) – **not CRT** | verified |
| 13a3:0038 | tan_deg8 | `s16 (AL=s8 deg)` | 8.8 tangent from table DS:5560 (tan 45° = 256) – **not CRT** | verified |
| 13a8:002e | copy_protection_check | far | Floppy check (int 13h, track 39), self-modifying. **Not CRT**. See 4.12 | likely |
| 16a7:0002 | fatal | `void (char *fmt, …)` | gfx_shutdown, kbd_restore, timer_restore, printf(fmt + 4 words), abort | verified |
| 16b8:0000 | find_nth_file | `char *(char *spec, int n)` | find_first, then find_next n−1 times. 0 if there are fewer matches | verified |
| 16bb:000a | edit_text_line | `int (char *buf, int maxlen, int x, int y, u32 timeout)` | One-line text editor (high-score name). Returns the exit key or 0 on timeout | verified |
| 16bb:02a8 | input_text_line | same args | Fills buf with maxlen spaces, then edit_text_line | verified |
| 16bb:02e6 | edit_cursor_xor | far (near-called) | Draws the cursor at DS:8A88 + DS:8A9C·8 if DS:920E | verified |
| 16eb:000a | res_find_list | `void (far ptr arc, char *names, far ptr *out)` | res_find for each 4-char name until NUL | verified |
| 16eb:004c | res_find_list_opt | same | Same with res_find_opt | verified |
| 16eb:008e / 00d0 | (duplicates) | same | Byte-identical copies of 000a / 004c. No callers | verified |
| 1748:000e | load_shapes | `far ptr (char *name)` | Extension search (.PES/.ESH), cache, unpack + UNFLIP or raw load | verified |
| 1748:016a | shapes_paras | `u16 (char *name)` | Same extension search (disk only). .PES → unpacked_paras, else file_paras. No callers found | verified |
### 2.5 Microsoft C runtime (segments 13a3, 13a8)

Segment `13a8` (0x2FF0 bytes, ends at 16a7:0000) is the CRT, except `13a8:0000–03f7`, which is the copy
protection. Segment `13a3` (0x50 bytes) is **not** CRT (DSI 8.8 trig helpers). Entry point (MZ CS:IP) =
`13a8:03f8`. Functions the game calls: `strcat strcpy strcmp stricmp strlen memset sprintf sscanf printf
fprintf fscanf fopen fclose itoa unlink _dos_getdrive filelength exit` and the long helpers. Replace all
with host libc (`stricmp` → `SDL_strcasecmp`). No `rand/srand`, `malloc` only inside the CRT, and no
`getch/kbhit/int86`.

| address | name | confidence |
|---|---|---|
| 13a8:0000–002d | protection data | likely |
| 13a8:002e–03f7 | copy_protection_check + helpers (007e, 0163, 0189, 03d3, 03ec), sector buffers 01b2–03d1 | likely |
| 13a8:03f8 | _astart (entry) | verified |
| 13a8:04a3 | _amsg_exit (inside _astart) | likely |
| 13a8:04be | _cinit (DOS version, INT 0 hook, `;C_FILE_INFO`, isatty flags) | verified |
| 13a8:0582 | exit | verified |
| 13a8:0599 | _exit (terminators, _nullcheck, close handles 5–19, INT 21h 4Ch) | verified |
| 13a8:05e0 | _ctermsub (restore INT 0) | verified |
| 13a8:060d | _initterm | verified |
| 13a8:0620 | _FF_MSGBANNER | verified |
| 13a8:0644 | _stack overflow (R6000) | likely |
| 13a8:064a | _chkstk | verified |
| 13a8:066e | _nullcheck (R6001) | verified |
| 13a8:0694 | _setargv | likely |
| 13a8:0826 | _setenvp | likely |
| 13a8:088c | _NMSG_TEXT (table DS:82C4) | verified |
| 13a8:08b7 | _NMSG_WRITE | verified |
| 13a8:08e2 | _myalloc / startup heap grow (INT 21h 4Ah) + _dosret helpers 0924/0937 | guess |
| 13a8:094a | _dosmaperr | likely |
| 13a8:0978 | fclose | verified |
| 13a8:0a3a | flushall | likely |
| 13a8:0a6e | fopen | verified |
| 13a8:0a9c | fprintf | verified |
| 13a8:0ae0 | fscanf | verified |
| 13a8:0b00 | printf | verified |
| 13a8:0b42 | _filbuf | likely |
| 13a8:0be8 | _getbuf | likely |
| 13a8:0c4e | _flsbuf | likely |
| 13a8:0df0 | _freebuf | likely |
| 13a8:0e20 | _openfile | likely |
| 13a8:0f16 | _stbuf | likely |
| 13a8:0fc4 | _ftbuf | likely |
| 13a8:105c | fflush | likely |
| 13a8:10c6 | _input (scanf engine) | verified |
| 13a8:146a–192b | _input helpers (number, string, _inc 18b0, _whiteout 18d6, width 190e) | likely |
| 13a8:192c | _output (printf engine) | verified |
| 13a8:1c00 | _output: integer conversion | likely |
| 13a8:1d3a | _output: %s/%c ("(null)") | likely |
| 13a8:1e2c | _output: floating point (through _cfltcvt vectors DS:6F3C–6F4C) | likely |
| 13a8:1ed0 / 1f14 / 1f74 / 1fde | _outc / _outpad / _outbuf / _outfield | likely |
| 13a8:20ae / 20c6 / 20f0 / 2170 | _outsign / _outprefix (0x) / _getnum ('*') / _flagcheck ("+- #") | likely |
| 13a8:219a | _getstream | verified |
| 13a8:21d6 | ungetc | likely |
| 13a8:223e | close | verified |
| 13a8:225e | lseek | verified |
| 13a8:22d8 | open (+ umask helper 246b) | verified |
| 13a8:247c | read (_read, text mode) | verified |
| 13a8:2558 | write (_write, text mode LF→CRLF, helper 2600) | verified |
| 13a8:2682 | stackavail | likely |
| 13a8:2696 | free (_nfree) | likely |
| 13a8:26a8 | malloc (_nmalloc) | likely |
| 13a8:26f1 / 27d4 / 280e / 2830 | _nmalloc search / grow / expand / brk helper | guess |
| 13a8:2852 | _brkctl (+ 28c0) | likely |
| 13a8:2916 | strcat | verified |
| 13a8:2956 | strcpy | verified |
| 13a8:2988 | strcmp | verified |
| 13a8:29b4 | strlen | verified |
| 13a8:29d0 | itoa | verified |
| 13a8:29ec | ultoa (or ltoa, shared body 2bb0) | likely |
| 13a8:29f6 | abort | verified |
| 13a8:2a18 | isatty | verified |
| 13a8:2a3c | sprintf | verified |
| 13a8:2a96 | sscanf | verified |
| 13a8:2ad8 | filelength | verified |
| 13a8:2b40 | stricmp (strcmpi) – case-insensitive | verified |
| 13a8:2b82 | memset | verified |
| 13a8:2c1c | raise | likely |
| 13a8:2cb4 | signal | likely |
| 13a8:2d57 | _sigentry lookup | likely |
| 13a8:2da7–2e1f | floating-point / signal dispatch helpers | guess |
| 13a8:2e20 | unlink (remove) | verified |
| 13a8:2e2e | _dos_getdrive | verified |
| 13a8:2e42 | _aFldiv | verified |
| 13a8:2ee8 | _aFlmul | verified |
| 13a8:2f1c | _aFlrem | likely |
| 13a8:2fc4 | _aFlshl | verified |
| 13a8:2fd0 | _aFNalshl (long <<= n through a pointer) | likely |

Non-standard items: 13a3 (trig, not CRT), 13a8:002e–03f7 (protection), and the absence of rand/srand.

## 3. Globals table

`CS:xxxx` rows are variables in segment 06c9.

### 3.1 Graphics

| DS offset | proposed name | type/size | meaning | written by | read by |
|---|---|---|---|---|---|
| CS:AF3A | gfx_cur | u16[13] | live copy of the selected target descriptor | gfx | gfx |
| CS:AF3C | gfx_cur_planes | u16[4] | plane segments of the live target (A000h = screen) | gfx | gfx |
| CS:AF44 | gfx_cur_rowtab | u16 | near CS ptr to the row table | gfx | gfx |
| CS:AF46 | gfx_cur_clip | s16[4] | clip x0 x1 (bytes) y0 y1 | gfx | gfx |
| CS:AF4E | gfx_cur_stride | u16 | bytes per row | gfx | gfx |
| CS:AF50 | gfx_cur_pad | u16 | plane block padding | gfx | gfx |
| CS:AF52 | gfx_cur_width | u16 | width in pixels | gfx | gfx |
| CS:AF54 | gfx_screen_desc | u16[13] | screen descriptor (A000h x4; rowtab CS:AF6E; 40x200; width 320) | gfx | gfx |
| CS:AF6E | gfx_screen_rows | u16[200] | y*40 | gfx | gfx |
| CS:B269 | gfx_rowpool_top | u16 | next free byte of the descriptor pool (init CS:B26B; limit CS:BA3B) | gfx | gfx |
| CS:B26B | gfx_rowpool | u8[2000] | descriptor + row table pool | gfx | gfx |
| CS:82C8 | rect_edge_mask | u8[8] | 00 80 C0 E0 F0 F8 FC FE | gfx | gfx |
| CS:857A | line_bit_tab | u8[8] | 80 40 20 10 08 04 02 01 (8582) | gfx | gfx |
| CS:8C78 | dissolve4_row_order | u8[12] | 0B 05 08 02 0A 04 07 01 09 03 06 00 | gfx | gfx |
| CS:8C84 | dissolve4_masks | u8[4] | 11 88 44 22 | gfx | gfx |
| CS:8EAE | dissolve8_row_order | u8[12] | same as CS:8C78 | gfx | gfx |
| CS:8EBA | dissolve8_masks | u8[8] | 01 08 40 02 10 80 04 20 | gfx | gfx |
| CS:9144 | bit_index_tab | u8[16] | lowest set bit index | gfx | gfx |
| CS:9154 | bit_value_tab | u8[16] | lowest set bit value | gfx | gfx |
| CS:9164 | bit_clear_tab | u8[4] | 0E 0D 0B 07 | gfx | gfx |
| CS:9168 | plane_mask_tab | u8[4] | 01 02 04 08 | gfx | gfx |
| CS:9562 | blit_copy_clip_ram_tab | u16[8] | RAM REPLACE clipped shift routines | gfx | gfx |
| CS:9572 | blit_clip_ega_tab | u16[8] | EGA clipped shift routines (REPLACE/OR/AND) | gfx | gfx |
| CS:9F9E | blit_copy_ram_tab | u16[8] | RAM REPLACE unclipped | gfx | gfx |
| CS:9FAE | blit_ega_tab | u16[8] | EGA unclipped (REPLACE/OR/AND) | gfx | gfx |
| CS:7DDC | blit_and_clip_ram_tab | u16[8] | RAM AND clipped | gfx | gfx |
| CS:80EA | blit_and_ram_tab | u16[8] | RAM AND unclipped | gfx | gfx |
| CS:A738 | blit_or_clip_ram_tab | u16[8] | RAM OR clipped | gfx | gfx |
| CS:AA32 | blit_or_ram_tab | u16[8] | RAM OR unclipped | gfx | gfx |
| CS:AC0C | grab_readmap_tab | u8[16] | lowest set bit index | gfx | gfx |
| CS:BB28 | blit_xor_clip_ram_tab | u16[8] | RAM XOR clipped | gfx | gfx |
| CS:BB38 | blit_xor_clip_ega_tab | u16[8] | EGA XOR clipped | gfx | gfx |
| CS:C192 | blit_xor_ram_tab | u16[8] | RAM XOR unclipped | gfx | gfx |
| CS:C1A2 | blit_xor_ega_tab | u16[8] | EGA XOR unclipped | gfx | gfx |
| CS:C8FE | cursor_glyph_tab | u16[9] | C910 C910 C928 ... | gfx | gfx |
| CS:C910 | glyph_cursor_thin | sprite | 1x8 bottom row set | gfx | gfx |
| CS:C928 | glyph_cursor_thick | sprite | 1x8 two bottom rows set | gfx | gfx |
| CS:C97C | line_or_bit_tab | u8[8] | 80 40 .. 01 (c984) | gfx | gfx |
| DS:5E6E | herc_mode | u8 | 1 after herc_init | gfx | gfx |
| DS:5E70 | herc_crtc_gfx | u8[12] | 38 28 2D 0A 7F 06 64 70 02 02 06 07 | gfx | gfx |
| DS:5E7C | herc_crtc_text | u8[12] | 61 50 52 0F 19 06 19 19 02 0D 0B 0C | gfx | gfx |
| DS:66E6 | rand8_idx | u16 | rand8 index | gfx | gfx |
| DS:66E8 | rand8_tab | u8[256] | rand8 table | gfx | gfx |
| DS:6838 | fill_left_mask | u8[8] | FF 7F 3F 1F 0F 07 03 01 | gfx | gfx |
| DS:6840 | fill_right_mask | u8[8] | 80 C0 E0 F0 F8 FC FE FF | gfx | gfx |
| DS:6848 | pal_game | u8[17] | 00 01 02 03 04 05 06 07 10 11 12 13 14 15 16 17 00 | gfx | gfx |
| DS:68CE | plot_bit_tab | u8[8] | 80 40 20 10 08 04 02 01 | gfx | gfx |
| DS:8CA2 | page_buf_desc | far ptr | 320x200x4 page buffer (game_flow) | gfx | gfx |
| DS:09B2 | drive_buf_desc | far ptr | 320x92x4 driving view buffer (scene_render) | gfx | gfx |
| DS:2E08 | pal_normal | u8[17] | scene_render copy of the game palette | gfx | gfx |
| DS:2E10 | pal_flash | u8[17] | 10..17 00..07 00 (crash flash) | gfx | gfx |

### 3.2 Input, hotkeys, text

| DS offset | proposed name | type/size | meaning | written by | read by |
|---|---|---|---|---|---|
| DS:6016–603C | str_music_on … str_keyboard_on | char[] | "MUSIC ON", "MUSIC OFF", "SOUND ON", "SOUND OFF", "KEYBOARD ON" | – | hotkeys |
| DS:6048 | hotkey_table | u16[0x105] | near handler offsets in 06c9; [ascii&0x7F] or [0x80+min(scan,0x84)]; all 0 initially | 6585 | 6528 |
| DS:6252 | hotkey_busy | u8 | re-entrancy guard for 6528 | 6528 | 6528 |
| DS:6254 | joy_menu_keys | u16[16] | bits → 0, 4800, 5000, 0, 4D00, 4900, 5100, 0, 4B00, 4700, 4F00, 0,0,0,0,0 | – | 65c5 |
| DS:6274 | joy_menu_last | u16 | last joystick menu code (edge detect) | 65c5 | 65c5 |
| DS:627C / 627E | joy_x / joy_y | u16 | last raw counts (0x50 if no edge seen) | 6686 | 6686, 6839, 684c |
| DS:6280 | joy_port_pre | u8 | port 201h sample before the one-shots | 6686 | 6686 |
| DS:6281 | joy_result | u8 | result being built | 6686 | 6686 |
| DS:6282 / 6284 | joy_xmin / joy_xmax | s16 | calibration (init 0x50 / 0) | 6686, 680a | 6686 |
| DS:6286 / 6288 | joy_xover_min / joy_xover_cnt | s16 / u16 | spike filter (init 0 / 0) | 6686 | 6686 |
| DS:628A / 628C | joy_xlo / joy_xhi | s16 | 25 % / 75 % thresholds | 6686 | 6686 |
| DS:628E / 6290 | joy_ymin / joy_ymax | u16 / s16 | as x (min compare unsigned) | 6686, 680a | 6686 |
| DS:6292 / 6294 | joy_yover_min / joy_yover_cnt | s16 / u16 | spike filter | 6686 | 6686 |
| DS:6296 / 6298 | joy_ylo / joy_yhi | u16 | thresholds (unsigned compares) | 6686 | 6686 |
| DS:629A / 629C | joy_xscale / joy_yscale | u16 | 0x4000 / (max−min) when range > 0 | 6686 | 6839, 684c (dead) |
| DS:629E | joy_dir_map | u8[16] | 00 01 05 00 03 02 04 03 07 08 06 07 00 01 05 00 | – | 6828 |
| DS:62AE | old_int9 | far ptr | saved INT 9 vector (0 = not installed) | 6860 | 68c4 |
| DS:62B2 | old_int16 | far ptr | saved INT 16h vector | 6860 | 68c4 |
| DS:62B6 | kbd_last_key | u16 | one-key buffer (AH scan/ext code, AL ASCII) | 6907, 69b7 | 69b7 |
| DS:62B8 | kbd_last_scan | u16 | last make scan (0 if ≥ 0x5A); never read | 6907 | – |
| DS:62BA | key_down | u8[0x5A] | 1 while the XT scan code is held | 6860, 6907 | 6620, 6907, 69b7, 69f2 |
| DS:6314 | kbd_xlat_normal | u8[0x5B] | scan → ASCII, or 0x80\|ext code | – | 6907 |
| DS:636F | kbd_xlat_shift | u8[0x5B] | used while LShift or RShift is held | – | 6907 |
| DS:63CA | kbd_xlat_caps | u8[0x5B] | used while the Caps Lock **key is held** | – | 6907 |
| DS:6425 | kbd_xlat_ctrl | u8[0x5B] | used while Ctrl is held | – | 6907 |
| DS:6480 | kbd_xlat_alt | u8[0x5B] | used while Alt is held (highest priority) | – | 6907 |
| DS:64DC | getkey_fn | far ptr | init 06c9:6a03; main sets 06c9:65c5; prompts swap to 6a03 temporarily | 6a17 | 69fe, 6a28 |
| DS:5BC2 | font8_table | u16[220] | near ptrs (DGROUP) to 8-byte glyphs, 0x20–0x8B non-zero; 0xDC+ runs into the string at DS:5D7A | – | a54f |
| DS:585A | font8_glyphs | u8[108×8] | glyph bitmaps, MSB = leftmost | – | a54f |
| DS:6820 | text_fg | u16 | default 3 | 7a82, 7abd | a54f |
| DS:6822 | text_bg | u16 | default 0 | 7a82, 7abd | a54f |
| DS:6824 | text_margin_x | u16 | x after CR/LF, 0 | 7abd | a54f |
| DS:6826 / 6828 | text_x / text_y | u16 | pen position (pixels) | a530, 7a93, a54f | a54f |
| DS:682A | text_unused | u16 | 1, never read | – | – |
| DS:682C | text_glyph_h | u16 | 8 | – | a54f |
| DS:682E | text_font | far ptr | DS:5BC2 (segment word 0x178F is ignored) | – | a54f |
| DS:6832 / 6834 | text_adv_x / text_adv_y | u16 | 8 / 8 | – | a54f |
| DS:6836 | text_enabled | u16 | 1; text is drawn only if == 1 (not in the 7aa4 save block) | – | a54f |
| DS:685A | str_exit_to_dos | char[] | "EXIT TO DOS (Y/N)" | – | 16fc:007c |
| DS:686C | str_pause | char[] | "PAUSE - PRESS ANY KEY TO RESUME" | – | 16fc:0358 |
| DS:6C6E–6CD6 | calib strings | char[] | 4 lines of the calibration screen | – | 1769 |
| DS:6CFC | joy_enabled | u8 (1769 writes a word) | joystick used by joy_read | 645a, 646f, 680a, 1769 | 6686 |
| DS:6CFE | joy_calibrated | u16 (bit0 tested) | set by the calibration screen, cleared when it is cancelled | 1769 | 6686 |
| DS:6D00 / 6D12 | calib_sq_x / calib_sq_y | u16[9] | x 134,134,174,174,174,134,94,94,94 / y 103,73,73,103,133,133,133,103,73 | – | 1769 |
| DS:82B8, DS:82BA | gfx_cseg | u16 | 0x06C9 (segment for CS:AFxx descriptor reads) | – | 16ab:000c, 1769 |
| DS:842E | scn_font | far ptr | loaded `<SCN>.FNT` (only the segment word DS:8430 is used, offset assumed 0) | 0267:1c2b | 06c9:17b4 |
| DS:940C | scn_signs | far ptr | loaded `<SCN><n>.SGN` (segment DS:940E used) | 0267:1be1 | 06c9:16a6 |
| DS:52E4–533D | sign_rec | u16[0x2D] | working copy of one .SGN record (see §5.9) | 06c9:16d9 | 06c9:16e1–1853 |
| DS:52E0, 52E2 | sign_line_x0 / sign_screen_x | u16 | post width then line start (font units) / board left x | 06c9:1715, 173d, 1792 | sign code |

### 3.3 Timer and sound

(DS offsets without the `DS:` prefix.)

| DS offset | name | type/size | meaning | written by | read by |
|---|---|---|---|---|---|
| 5E88 | old_int8 | far ptr (off, seg) | previous INT 8 vector | 6099 | 610a, 6230 |
| 5E8C | tick_count | u32 | ticks since install; stops while paused | 61bf, 7a07 | 79c8, 79d2, 79ea |
| 5E90 | slow_count | u32 | +1 each chain period (every 5 ticks = 20 Hz), also while paused | 61bf | c692 |
| 5E94 | chain_countdown_on | u8 | 1 = stop BIOS chaining after `chain_budget` calls | 601c, 603c, 6059, 607a, 6230 | 6230 |
| 5E95 | chain_enable | u8 | call the BIOS INT 8 each chain period | 603c, 6059, 6230 | 61bf |
| 5E96 | chain_budget | s16 | remaining BIOS calls (100 at install) | 601c, 607a, 6230 | 6230 |
| 5E98 | chain_reload | s16 | ticks per chain period (5) | 601c, 603c, 6059, 607a | 61bf |
| 5E9A | chain_count | s16 | countdown to next chain period | same, 61bf | 61bf |
| 5E9C | prof_index | u16 | index into 5E9E (always 0) | 6099 | 61bf |
| 5E9E | prof_counts | u16[40] | per-index tick counters (only [0] counts); never read | 6099, 61bf | – |
| 5EEE | sfx_seg | u16 | current stream segment, 0 = none | 6269 (loop restart 6312, clear when sound off), 6488, 64c7, 7934, 7946, 7977, 7995, 799c | 6269 |
| 5EF0 | sfx_off | u16 | current stream offset | 6269, 7946, 7977, 799c | 6269 |
| 5EF2 | sfx_loop_seg | u16 | looping stream segment | 7946 | 6269 |
| 5EF4 | sfx_loop_off | u16 | looping stream offset | 7946 | 6269 |
| 5EF6 | sfx_note_left | u16 | remaining ticks of the current event | 6269 | 6269 |
| 5EF8 | sfx_note_cut | u16 | cut point (`dur >> shift`, 0 = legato) | 6269 | 6269 |
| 5EFA | sfx_shift | u8 | articulation shift, initial 3 | 6269 (FE) | 6269 |
| 5EFB | snd_enable | u8 | bit0 sound, bit1 music; initial 3 | 6488, 64c7, 7934, 7940, 79bb, 79c1 | 6269, 758a, 75ea, 799c |
| 5EFC | snd_busy | u8 | one-shot effect active (sfx) / song playing (music) — shared | 6269, 6488, 64c7, 758a, 75ea, 7977, 799c | 6269, 75ea, 7946, 798f |
| 5EFD | sfx_loop_set | u8 | a looping stream is set | 7946, 7971 | 6269 |
| 5EFE | timer_paused | u8 | 1 = ISR skips counters and routines, speaker off | 5d1e, 645a, 6508, 6518 | 61bf |
| 5F00 | sfx_loop_cnt | s16[3] | loop counters (FD/FC/FB) | 6269 | 6269 |
| 5F06 | sfx_loop_start | u16[3] | loop body start offsets | 6269 | 6269 |
| 5F0C | sfx_loop_end | u16[3] | offsets of the FA/F9/F8 bytes (for the break opcodes) | 6269 | 6269 |
| 5F12 | timer_routines | far ptr[6] | 5 routines + terminator (list ends at the first entry with segment 0) | 6099, 614c, 6180 | 61bf |
| 5F2A | – | 4 bytes | unused (0) | – | – |
| 5F2E | sfx_div | u16[93] | PIT divisors for stream notes 0..92; slots 0x55–0x58 are live engine/effect tones | 06c9:1e41.., 06c9:412c | 6269 |
| 5FE8 | – | strings | "NO ROOM LEFT…", "MUSIC ON" 6016, "MUSIC OFF" 601F, "SOUND ON" 6029, "SOUND OFF" 6032, "KEYBOARD ON" 603C | – | – |
| 65D0 | – | u16 = 0x000D | not referenced (checked by displacement scan) | – | – |
| 65D2 | mus_start | u8 | start request (set by music_play) | 758a, 75ea | 75ea |
| 65D3 | mus_tempo | u16 (low byte used) | ticks per length unit, initial 0x14 | 75ea (FE) | 75ea |
| 65D5 | mus_transpose_base | u16 = 0 | added to each pattern's transpose; never written | – | 75ea |
| 65D9 | mus_transpose | u16 | current pattern transpose | 75ea | 75ea |
| 65E1 | mus_on_left | u16 | tone ticks left | 75ea | 75ea |
| 65E5 | mus_off_left | u16 | silent ticks left | 75ea | 75ea |
| 65E9 | mus_pat | u16 | offset of next pattern event | 75ea | 75ea |
| 65ED | mus_list | u16 | offset of next pattern-list entry (0 = stopped) | 758a, 75ea | 75ea |
| 65EF | mus_list2 | u16 | song entry word 2 (never read; cleared by FB) | 758a, 75ea | – |
| 65F1 | mus_list_loop | u16 | first pattern-list entry of the song (FF target) | 758a | 75ea |
| 65F3 | mus_list2_loop | u16 | song entry word 2 copy, never read | 758a | – |
| 65F5 | mus_seg | u16 | SONGS.BIN segment | 758a | 75ea |
| 65F7 | mus_voices | far ptr (seg, off) | VOICES.BIN (note: segment word first) | 75c8 | 75ea |
| 65FB | mus_note | u16 | note index incl. transpose | 75ea | 75ea |
| 65FD | mus_div | u16 | base divisor (arpeggio changes it) | 75ea | 75ea |
| 65FF | mus_arp_cnt | u16 | arpeggio countdown (0 = off) | 75ea | 75ea |
| 6601 | mus_arp_idx | u16 | arpeggio step | 75ea | 75ea |
| 6603 | mus_vib_cnt | u16 | vibrato countdown | 75ea | 75ea |
| 6605 | mus_vib_dir | s8 | vibrato direction | 75ea | 75ea |
| 6607 | mus_vib_ofs | s16 | divisor offset | 75ea | 75ea |
| 6609 | mus_voice | 28 bytes | current voice record (layout in 5.6); EXE default `03 00 0000 0100 0300 00 04 07 0c 00 00 00 00 0000 0100 00 00 6400 ff9c 0064` | 75ea (FD) | 75ea |
| 6625 | – | u16×2 | written by 75d9 only | 75d9 | – |
| 663B | mus_div_table | u16[85] | PIT divisors for music notes 0..84 (= DS:5F2E[0..84] initial) | – | 75ea |
| 6818 | deadline | u32 | tick deadline | 7a10 | 7a27, 7a3b, 6a4a |
| 681C | lap_start | u32 | ticks_lap reference | 79ea | 79ea |
| 68D6 | slow_deadline | u32 | slow-tick deadline | c69c | c63e, c6b3 |
| 1352 | stream_engine | bytes | `FE 00 · 55 0003 · 56 0001 · FF` (6-tick loop) | – | 7946 via 1b4e |
| 549F | stream_noise_long | bytes | `FE 00 · FD 0032 · 58 0001 · FA · FF` (51×2 = 102 ticks) | – | 3532, 3643 |
| 5494 | stream_noise_short | bytes | `FE 00 · FD 000A · 58 0001 · FA · FF` (11×2 = 22 ticks) | – | 4a2e |
| 32AE | noise_div | u16[32] | slot 0x58 values, index DS:336A & 31 (DS:336A += 1 every tick) | – | 412c |
| 30E8 | engine_div | u16[] | slot 0x55 = [(rpm_disp >> 5) & ~1] (2·i Hz, i<10 → 0xFFFF) | – | 412c |
| 8640 | songs_ptr | far ptr | loaded SONGS.BIN | main | 0267 callers of 758a |
| 942A | voices_ptr | far ptr | loaded VOICES.BIN | main | main |

### 3.4 Resources and memory

| DS offset | proposed name | type/size | meaning | written by | read by |
|---|---|---|---|---|---|
| DS:52C2 | g_tick_id | char[4] | Result of make_tick_id | 5d2e | 0000:0477 |
| DS:5D7A | s_file_error1 | char[] | "%s FILE ERROR" | – | 5e1c, 5e8a |
| DS:5D88 | g_find_path | char[100] | find_first result: directory part of the spec + name | 5ef4, 5f4e | callers |
| DS:5DEC | g_find_name_ptr | near ptr | Where the file name goes in DS:5D88 | 5ef4 | 5ef4, 5f4e |
| DS:5DEE | g_dta | 43 bytes | DOS DTA used by find_first/next (name at DS:5E0C) | DOS | 5ef4, 5f4e |
| DS:5E8C | g_ticks32 | u32 | Timer tick counter (timer spec) | ISR, 7a07 | 79c8, 79d2, 79ea |
| DS:5EEE..5EF4, 5EFB..5EFE | sound flags / pointers | – | See sound spec (5EFB bit0 = sound, bit1 = music) | 79xx | ISR |
| DS:64DC | – | far ptr | Read by 6a28 (keyboard spec) | – | 6a28 |
| DS:64E0 | s_file_error2 | char[] | "%s FILE ERROR\r" | – | 6aa2 |
| DS:6503 | s_bad_pack | char[] | "%s INVALID PACK TYPE\r" | – | 6d50 |
| DS:651A | s_locateshape | char[] | "locateshape - %-4.4s SHAPE OR SOUND NOT FOUND\r" | – | 6e59 |
| DS:654A / 6574 | s_reserve_* | char[] | "reservememory - OUT OF MEMORY LOADING %s\r" / "… OUT OF MEMORY BLOCKS LOADING %s\r" | – | 70a3 |
| DS:65A5 | s_block_not_found | char[] | "memory manager - BLOCK NOT FOUND at SEG= %x\r" | – | 72c6, 736b, 7490, 74d4, 7501 |
| DS:66E6 | g_rand_idx | u16 | rand8 index, initially 0 | 780e | 780e |
| DS:66E8 | g_rand_tab | u8[256] | rand8 state, initial contents are in the EXE (image 0x1DFD8) | 780e | 780e |
| DS:6808 | s_file_error3 | char[] | "%s FILE ERROR\r" | – | 7866 |
| DS:6818 | g_timeout | u32 | Deadline for 7a27/7a3b | 7a10 | 7a27, 7a3b |
| DS:681C | g_ticks_last | u32 | Last value for ticks32_delta | 79ea | 79ea |
| DS:688C / 6891 / 6896 | s_ext_pes, s_ext_esh, s_empty | char[] | ".PES", ".ESH", "" | – | via DS:68A4 |
| DS:6897 | s_pes_cmp | char[] | ".PES" (compared with stricmp) | – | 1748:000e |
| DS:689C | s_unflip | char[] | "UNFLIP" (block name of the scratch buffer) | – | 1748:000e |
| DS:68A4 | g_shape_ext | near ptr[3] | {DS:688C, DS:6891, DS:6896}, ends at the empty string | – | 1748:000e, 1748:016a |
| DS:68AA | s_pes_cmp2 | char[] | ".PES" | – | 1748:016a |
| DS:68B0 | s_window | char[] | "WINDOW" (block name of off-screen buffers) | – | 06c9:b0fe |
| DS:68DA | g_heap_top | u16 seg | End of the heap. 0 = mem_init not run yet | 6f1e, 6f93 | 6f1e |
| DS:68DC | g_heap_base | u16 seg | Start of the heap (DOS block) | 6f1e | – |
| DS:68DE / 68E0 | g_mem_cs / g_mem_ds | u16 | CS and DS saved by mem_init. Never read | 6f1e | – |
| DS:68E2 | g_mem_rec | MemRec[50] (0x384 bytes) | Record table (4.24). [0] = bottom sentinel (flags 2), [49] = DS:6C54 top sentinel (flags 1). Names start as 12 spaces | 70a3, 71b4, 7147, 72c6, 736b, 7490, 7501, 6f1e | same + 7273, 74d4 |
| DS:6C66 | g_mem_first | near ptr | = DS:68E2 (constant) | – | all |
| DS:6C68 | g_mem_low | near ptr | Top record of the in-use stack (initially DS:68E2) | 6f1e, 70a3, 71b4, 72c6, 736b, 7490, 7501 | all |
| DS:6C6A | g_mem_cache | near ptr | First (lowest) record of the cache region (initially DS:6C54) | 6f1e, 70a3, 71b4, 7147, 72c6, 736b | all |
| DS:6C6C | g_mem_last | near ptr | = DS:6C54 (constant) | – | all |
| DS:8A88 / 8A8A | g_edit_x / g_edit_y | s16 | Text editor position | 16bb:000a | 16bb:02e6 |
| DS:8A9C | g_edit_pos | s16 | Cursor index | 16bb:000a | 16bb:02e6 |
| DS:8CA0 | g_edit_cursor_h | s16 | Cursor height: 1, or 8 in insert mode | 16bb:000a | 16bb:02e6 |
| DS:920E | g_edit_cursor_on | s16 | Cursor blink state | 16bb:000a, 02e6 | 16bb:02e6 |
| CS(06c9):7AD6 | huff_off | u16[16] | Huffman symbol-index bias per code length (code-segment data) | 7c16 | 7c16 |
| CS(06c9):7AF6 | huff_lim | u16[16] | Huffman limit per code length | 7c16 | 7c16 |
| CS(06c9):7B16 | huff_alpha | u8[256] | Huffman alphabet | 7c16 | 7c16 |
| CS(06c9):B269 | g_rowtab_ptr | u16 | Row-table pool pointer (limit 0xBA3B, "OUT OF ROW TABLE SPACE") | b0fe, 782c | b0fe |

## 4. Pseudocode

### 4.1 Planar model and draw targets

The model is TD1's (see `../TestDrive1987/port/spec/platform.md` 4.1). The descriptor has one more word:

```c
typedef struct {            /* 13 words + row table; lives in the CS row pool CS:B26B..CS:BA3A     */
    u16 hdr_off;            /* +00 0: (hdr_off, plane_seg[0]) = far ptr to the 16-byte sprite header */
    u16 plane_seg[4];       /* +02..+08 plane k segment, 0 = absent (writes skipped); A000h = screen  */
    u16 rowtab;             /* +0A near ptr (CS) to the row table: row y -> byte offset in a plane   */
    s16 clip_x0, clip_x1;   /* +0C,+0E clip columns in BYTES (8-pixel cells), x1 exclusive            */
    s16 clip_y0, clip_y1;   /* +10,+12 clip rows, y1 exclusive                                        */
    u16 stride;             /* +14 bytes per row (40 for 320 px)                                      */
    u16 pad;                /* +16 padding bytes after each plane block (0..15)                       */
    u16 width_px;           /* +18 NEW in TD2: width in pixels (320 for the screen); written only       */
    u16 row[h];             /* +1A row table                                                          */
} Desc;
```

* Live copy of the selected target: 13 words at **CS:AF3A** (planes CS:AF3C.., rowtab CS:AF44, clip
  CS:AF46/48/4A/4C, stride CS:AF4E, pad CS:AF50, width CS:AF52). Screen descriptor at **CS:AF54**
  (planes A000h ×4, rowtab CS:AF6E = `y*40`, 200 rows, clip 0,40,0,200, stride 40, width 320). Both are
  initialised to the screen.
* `gfx_select_target` (7d5e) copies 13 words; TD2 keeps no pointer to the selected descriptor.
  `gfx_set_clip_current` (5dfb, 7 callers) writes only the live copy; `gfx_set_clip` (5d9e) writes a
  descriptor and the live copy when the plane-0 segments match.
* `gfx_targets_save/restore` (78f8/7918) copy the 26 words CS:AF3A..AF6D (live copy and screen
  descriptor) to/from a caller buffer: used around the message boxes and the calibration screen.
* Every primitive tests `plane_seg[0] == 0xA000` for the EGA register path; otherwise the RAM path.

**No page flipping.** TD2EGA never touches the CRTC (no 3D4h, no 3DAh, no INT 10h AH=05h). Frames are
composed in RAM buffers and copied to A000h with blits or dissolves. Buffers created by the game
(`gfx_create_buffer(width_px, h, planes)`):

| call site | size | planes | stored in | use (from the callers; game_flow / scene_render to confirm) |
|---|---|---|---|---|
| 0000:088d, 0267:17e6 | 320×200 | 0Fh | DS:8CA2 | full-screen page buffer (title, showroom, results) |
| 0000:00be, 0000:01de | 320×40 | 0Fh | local | message-line save |
| 0267:01b8 / 0267:0e40 | 320×56 / 320×200 | 0Fh | local | gas station / results |
| 06c9:000e | 320×92 | 0Fh | DS:09B2 | driving view (scene_render) |
| 06c9:1eee | 80×17 | AX | DS:2A20 | (scene_render) |
| 06c9:5cc9 | sprite size (w*8 × h) | 0Fh | local | (simulation/scene) |
| 16fc:008e/00a8, 0232/024c, 036a/0384 | 160×24, 320×10, 320×24 (two each) | 0Fh | local | screen save under pause / message / exit boxes |
| 1769:004b | 320×200 | 0Fh | local | calibration screen save |

Port: `Target { u8 *plane[4]; int stride, h; clip; }` exactly as in TD1's port; the screen is a Target
with 4 planes of 40×200. Present by combining planes into 4-bit indices through the 16-entry palette.

### 4.2 Sprite blitters

24 entry points = 8 operation families × 3 position modes, all sharing two bodies (clipped
06c9:9189/91c1/91f3, unclipped 06c9:9c75/9cad/9cdf). Each stub fills four frame locals:
`[bp-40h]` RAM shift-routine table, `[bp-4Ah]` EGA shift-routine table, `[bp-42h]` GC function value,
`[bp-41h]` flags.

| entries hot / raw / own | clip | op | GC func (3CEh idx 3) | flags | RAM table | EGA table |
|---|---|---|---|---|---|---|
| 916c / 91a4 / 91d6 | yes | REPLACE | 00h | 3 | CS:9562 | CS:9572 |
| a6d8 / a6f8 / a718 | yes | OR | 10h | 2 | CS:A738 | CS:9572 |
| 7d7c / 7d9c / 7dbc | yes | AND | 08h | 1 | CS:7DDC | CS:9572 |
| bac8 / bae8 / bb08 | yes | XOR | 18h | 4 | CS:BB28 | CS:BB38 |
| 9c58 / 9c90 / 9cc2 | no | REPLACE | 00h | 3 | CS:9F9E | CS:9FAE |
| a9d2 / a9f2 / aa12 | no | OR | 10h | 2 | CS:AA32 | CS:9FAE |
| 808a / 80aa / 80ca | no | AND | 08h | 1 | CS:80EA | CS:9FAE |
| c132 / c152 / c172 | no | XOR | 18h | 4 | CS:C192 | CS:C1A2 |

Each table holds 8 routines indexed by `shift = px & 7`. Position modes, args `(u16 spr_off, u16 spr_seg
[, s16 x, s16 y])`:
* **hot**: `px = x - hdr.hot_x; py = y - hdr.hot_y`
* **raw**: `px = x; py = y`
* **own**: `px = hdr.x; py = hdr.y` (**TD1 masked x with ~3; TD2 does not**).

Semantics are TD1's pseudocode (`blit()` in TD1 spec 4.2) with these corrections:

```c
/* plane map (header +0C..+0F) */
blocksize = (u8)h * (u8)w + (pm[3] >> 4);          /* mul byte ptr [si]: 8-bit multiply        */
/* stored-plane list: k = 0.. while (pm[k] & 0x0F); each bit b of pm[k]&0x0F whose target plane is
   present becomes a destination (plane b <- block k).  RAM path: stop scanning after the byte that
   brings the destination count to >= 4; processes destinations last-to-first.  EGA path: up to 4
   bytes, first-to-last.                                                                          */
/* constant planes, done first over the visible rectangle:
     flags & 1 (REPLACE, AND):  pm[0] >> 4 bits -> rect_op(CLEAR)
     flags & 6 (REPLACE, OR):   pm[1] >> 4 bits -> rect_op(SET)
     flags & 4 (XOR):           pm[1] >> 4 bits -> rect_op(XOR)                                  */
edge = 3;                 /* bit0 = right edge visible (write the spill byte),
                             bit1 = left edge visible (seed carry from the destination)           */
/* clipped vertical/horizontal clipping exactly as TD1 (right edge touching clip_x1 counts as
   clipped: edge &= ~1; left clip: edge &= ~2, source starts at +left_skip; nv == 0 allowed)     */
```

Shift routines (RAM and EGA), per row, `n = shift`, `s` = source, `d` = destination:
* `n == 0`: `d[i] = OP(d[i], s[i])` for `i < vis_w`.
* `n > 0`: `out[i] = (s[i] >> n) | carry; carry = (u8)(s[i] << (8-n))`.
  * initial carry, left edge visible: REPLACE `d[0] & ~(0xFF >> n)`; AND `~(0xFF >> n)` (0x80, 0xC0, …);
    OR and XOR 0. EGA REPLACE/OR/AND: `d[0] & ~(0xFF>>n)` (the hardware op makes it equivalent);
    **EGA XOR: 0** (dedicated TD2 routines).
  * initial carry, left edge clipped: `(u8)(s[-1] << (8-n))` in **every** RAM and EGA routine
    (**TD1's RAM OR/AND/XOR bug `s[-1] >> n` is fixed**).
  * after the row, if edge bit0: byte `vis_w` gets the carry: REPLACE `d = (d & (0xFF>>n)) | carry`;
    OR `d |= carry`; AND `d &= carry | (0xFF>>n)`; XOR `d ^= carry` (**EGA XOR now writes the bare
    carry, so the TD1 screen-XOR edge bug is gone**).
  * RAM XOR with `vis_w == 0` (sprite fully left of the clip except the spill pixels): the spill byte
    is XORed with AH, which is 0 there, so nothing is drawn (REPLACE/OR/AND draw the spill pixels).
* Row advance: destination `+= stride - vis_w` (**EGA path now uses the descriptor stride**, TD1
  hard-coded 40), source `+= w - vis_w`.

`rect_op(plane, dst, n, rows, shift, OP, edge)` — RAM 82d0 / 8336 / 839c, table CS:82C8
`00 80 C0 E0 F0 F8 FC FE` (`m` = destination pixels left of the sprite):
```c
if (shift == 0) { OP n whole bytes per row; row advance stride - n; return; }
keep_l = m;  keep_r = ~m;                    /* CLEAR: AND masks; SET/XOR: OR/XOR masks inverted */
if (!(edge & 2)) first byte fully inside the clip -> whole-byte OP;
if (!(edge & 1)) { last byte is the clip column: whole-byte OP; one byte fewer, row skip + 1; }
/* then: first byte (partial), n-1 (or n-2) whole bytes, last byte (partial); n==1/2 special cases */
```
Pixel result = OP over `[8*col+shift, 8*(col+n)+shift)` intersected with the clip.

EGA helpers ad22 / ad8b / adf4 (read map and map mask set by the caller, GC function = the blit's op):
* ignore the edge flags (both partial bytes are always written, even outside the clip);
* `shift == 0`: whole bytes `0x00` / `0xFF` / `0xFF` written — correct under the GC function
  (REPLACE/AND clear, REPLACE/OR set, XOR invert);
* `shift != 0`, `n >= 2`: the **middle bytes are read and written back unchanged** (clear/set) or written
  as `d ^ 0xFF` (xor) — with GC function XOR the hardware then produces `0xFF`; the partial bytes are
  pre-combined (`d & keep`, `d | ~keep`, `d ^ ~keep`), so XOR partial bytes also come out wrong.
  Same code as TD1 (100 % match). Only visible for sprites with pm[0]/pm[1] high nibbles blitted
  directly to the screen with `x & 7 != 0`. Port: implement the RAM semantics; see Open questions.

### 4.3 Loader fix-up of column-major planes (06c9:c838)

Called by the .PES loader 1748:000e right after 06c9:6d50 unpacked the archive, with a temporary
0x1F6-paragraph block reserved as "UNFLIP" (freed afterwards via 06c9:7490).

```c
void res_unflip_archive(far u8 *arc, far u8 *tmp)
{
    u16 n = rd16(arc + 4);                        /* resource count */
    for (u16 i = 0; i < n; i++) {                 /* dec/jg: n >= 1 assumed */
        u8 far *s = res_ptr(arc, i);              /* 06c9:c701: base + 6 + 8n + off[i], normalised */
        if (s[0x0F] & 0xF0) continue;             /* padded (runtime-style) sprite: skip           */
        u8 flags = s[0x0E] >> 4;                  /* pm[2] high nibble                              */
        if (!flags) continue;
        u16 w = rd16(s), h = rd16(s + 2);
        u16 size = w * h;                         /* 16-bit mul */
        u8 far *blk = s + 0x10;
        for (int k = 0; k < 4; k++, blk += size) {    /* always 4 blocks, no check against the list */
            if (!(flags >> k & 1)) continue;
            u8 far *o = tmp;
            for (u16 r = 0; r < h; r++)
                for (u16 c = 0; c < w; c++)
                    *o++ = blk[r + c * h];        /* column c = w-th block of h bytes */
            memcpy(blk, tmp, size);
        }
    }
}
```
* The flags are not cleared, so the fix-up must run exactly once per load (the archive cache ensures
  that). Shipped data never flags a block beyond the stored-plane list.
* Resource name ending irrelevant; resources that are not sprites (none in shipped .PES) would be
  corrupted if byte 0x0E had a high nibble.
* TD2TDY has the same routine (image 0x10B53); TD2CGA's version (image 0x10DA0) treats the nibble as a
  storage **mode** of the single 2bpp block (see File formats).

Port: do this conversion in the resource loader (or offline) and treat every sprite as row-major.

### 4.4 Other primitives

**gfx_fill_rect (8a0c)(x, y, w, h, colour)** — TD1 0x4941 plus `if (w <= 0 || h <= 0) return;`; EGA
path row advance uses the descriptor stride. RAM: per present plane k set/clear the pixel mask
`[x, x+w) × [y, y+h)` according to `colour >> k & 1` (tables CS:8A0C-area masks as TD1
`FF 7F … 01` / `80 C0 … FF`). EGA: write mode 2, map mask 0Fh, bit mask per partial byte, restores bit
mask FFh and mode 0. No clipping.

**gfx_fill_rect_clip (89a2)** — same arguments; clips against `[clip_x0*8, clip_x1*8) ×
[clip_y0, clip_y1)` (signed), returns when the width or height becomes ≤ 0, then continues in 8a0c.

**gfx_clear_screen (840a)(colour)** — A000h, write mode 2, map mask 0Fh (TD2 sets it explicitly),
8000 bytes = colour, mode 0. Ignores the selected target.

**gfx_clear_clip (843e)(colour)** — fills the live clip rectangle (byte columns × rows):
```c
int rows = clip_y1 - clip_y0, cols = clip_x1 - clip_x0;
u16 off = row[clip_y0] + clip_x0;
if (screen) {                                 /* write mode 2, map mask 0Fh (TD1 left it inherited) */
    if (cols == 40) memset(A000+off, colour, (u8)40 * (u8)rows);  /* mul dl: correct up to 255 rows */
    else for (each row) memset(A000+off+row*stride.., colour, cols); /* TD1's first-row-only bug fixed */
    write mode 0;
} else if (cols == stride) {                  /* rep stosw, count = (stride*rows) >> 1, + odd byte  */
    for k in 0..3 if (plane[k]) memset(plane[k]+off, (colour>>k&1) ? 0xFF : 0, stride*rows);
} else
    for k in 0..3 if (plane[k]) for (each row) memset(.., (colour>>k&1)?0xFF:0, cols), advance stride;
```

**gfx_draw_line (8582)(x0, y0, x1, y1, colour)** — TD1 0x85D5 with fixes:
* horizontal/vertical lines go through `gfx_fill_rect` (clipped first) as in TD1;
* y-major skip phase advances x by the real step (TD1's constant −15.0003 typo fixed);
* RAM plot: for every present plane k: `d &= ~bit; if (colour >> k & 1) d |= bit` → pixel = colour
  (TD1 ORed the bit into every plane);
* EGA plot: write mode 2, map mask 0Fh, bit mask = pixel bit, write colour; GC function is not set
  (normally 00h) → pixel = colour. On exit it restores mode 0 **and leaves the bit mask at 00h**
  (as TD1): later write-mode-0 blits to the screen are no-ops until `gfx_fill_rect`, `gfx_plot` or
  `gfx_init_ega` rewrites FFh.

**gfx_draw_line_or (c984)** — the TD1 routine with only the y-major step fix: EGA plot uses GC function
10h (OR) → pixel |= colour, then restores function 0, mode 0, bit mask 00h (the last instruction runs
into 13a3:0000, which begins with `00` → `mov al, 0; out dx, al`); RAM plot ORs the bit into every
present plane. Only caller: calibration screen 1769:000e.

**gfx_plot (ba3c)(x, y, colour)** — `off = row[y] + (x >> 3)`, `bit = DS:68CE[x & 7]`
(`80 40 … 01`). Screen: map mask FFh, bit mask = bit, write mode 2, write colour, bit mask FFh, mode 0.
RAM: per present plane set/clear the bit by `colour >> k & 1`. Callers 06c9:37d0, 06c9:3ab8.

**Dissolves** — `gfx_dissolve8` (8f12) is TD1's 0x768B unchanged (row order CS:8EAE
`0B 05 08 02 0A 04 07 01 09 03 06 00`, masks CS:8EBA `01 08 40 02 10 80 04 20`, one pixel per byte,
`phase` incremented per row, buggy "clear/set" entries). `gfx_dissolve4` (8cd8) is identical except
the mask table CS:8C84 `11 88 44 22` indexed by `phase & 3` (two pixels per byte, a 4-step fade).
Both draw at byte column `hdr.x` (not `>> 3`) and row `hdr.y` using the live target's row table and
the EGA registers (screen only). Only caller: 0000:0000 (game_flow).

**gfx_scroll_window (ae62)(x, y, w, h, step, soff, sseg, srow)** — TD1 0x91CF with `x` in pixels
(`>> 3`): write mode 1, map mask 0Fh, `dst = row[y] + x>>3`; for `h` rows copy `w` bytes from
`dst + step` to `dst`, then `dst += step`. Mode 0. If `sseg != 0`: for each stored plane k (until a
zero low nibble, at most 4) map mask = `pm[k] & 0x0F`, copy `w` bytes of sprite row `srow` (source
`0x10 + (u8)srow * (u8)w + k*blocksize`; assumes sprite width = `w`) to `dst`. Caller 019e:009b
(credits scroller).

**gfx_grab_screen (c784)(sx, sy, dx, dy, w, h)** — `sx`, `dx`, `w` in pixels (`>> 3`); for each
present plane of the live target: read map = plane, copy `h` rows of `w>>3` bytes from A000h
(`screen_row[sy] + sx>>3`, stride 40) to `row[dy] + dx>>3` (stride = live stride). Callers: 16fc
message boxes, 1769 calibration (save the screen before drawing over it).

**grab_into_sprite (ac1c/ac40/ac64)(spr [, x, y])** — screen → sprite: for k = 0..3, if
`pm[k] & 0x0F`: read map = lowest set bit (table CS:AC0C), copy `h` rows × `w` bytes from A000h at
`row[py] + px>>3` (live row table and stride) into block k; the destination pointer advances by
`pad` after each block. `_raw` (ac40) stores x, y in the header first (+8, +0A). Caller of `_raw`:
0000:0090, 0000:01b0, 06c9:3c3a.

**draw_cursor_glyph (c958)(x, y, idx)** — `blit_xor_hot(CS:[C8FE + 2*idx], x & ~7, y)`. Glyphs are
1×8 byte sprites with pm `0F 00 00 00`: CS:C910 = bottom row set (thin underline, idx 0/1),
CS:C928 = two bottom rows (idx ≥ 2, insert-mode cursor). XOR twice erases.

**gfx_create_buffer (b0fe)(width_px, h, planes)**:
```c
u16 w = width_px >> 3;
u16 size = w * h;  u16 pad = (-size) & 0x0F;  u16 blk = size + pad;
u32 total = 0x10 + blk * popcount(planes & 0x0F);   /* 24-bit carry in BH */
u16 paras = (total >> 4) + 1;
u16 seg = reservememory("WINDOW", paras);          /* 06c9:70a3, returns DX:AX */
hdr = { w, h, 0, 0, 0, 0, pm = present plane bits packed low-to-high (1,2,4,8), pm[3] |= pad << 4 };
Desc *d = CS:[B269];
if (d + (h + 0x0D) * 2 >= 0xBA3B) fatal("OUT OF ROW TABLE SPACE");   /* 16a7:0002 */
CS:[B269] = d + (h + 0x0D) * 2;
d->hdr_off = 0;
for (i = 0, s = seg; k < 4; k++) d->plane_seg[k] = (planes >> k & 1) ? (s += (i++ ? blk >> 4 : 0)) : 0;
     /* plane k segment = seg + i*(blk>>4) for the i-th present plane; data at seg:0010 + row[y] */
d->rowtab = d + 0x1A; d->clip = { 0, w, 0, h }; d->stride = w; d->pad = pad; d->width_px = width_px;
for (y = 0; y < h; y++) d->row[y] = 0x10 + y * w;
return MK_FP(CS, d);
```
**gfx_free_buffer (782c)(desc)** — `CS:[B269] -= (hdr->h + 0x0D) * 2` (must be the most recent buffer),
then frees the block `plane_seg[0]:0` through the memory manager 06c9:7490.

### 4.5 Video mode, palette, other adapters

* **gfx_init_ega (90e8)**: GC mode (5) = 0, enable set/reset (1) = 0, bit mask (8) = FFh, function (3) = 0;
  `gfx_clear_screen(0)`; BIOS 0040:0010 bits 4–5 = 01b; INT 10h AX=000Dh; INT 10h AX=1002h ES:DX = DS:6848.
* **The game palette** DS:6848 (17 bytes): `00 01 02 03 04 05 06 07 10 11 12 13 14 15 16 17`, overscan
  `00`. In the 200-line mode 0Dh the attribute value's bit 4 is the intensity, so these are the standard
  16 colours: black, blue, green, cyan, red, magenta, brown, light grey, dark grey, light blue,
  light green, light cyan, light red, light magenta, yellow, white
  (RGB 000000 0000AA 00AA00 00AAAA AA0000 AA00AA AA5500 AAAAAA 555555 5555FF 55FF55 55FFFF FF5555
  FF55FF FFFF55 FFFFFF). Nothing writes the table.
* **Crash flash** (scene_render 06c9:3532): 7 frames alternating `gfx_set_palette(DS:2E08)` (same
  values as DS:6848) and `DS:2E10` = `10 11 12 13 14 15 16 17 00 01 … 07 00` (dark/bright halves
  swapped), ending with DS:2E08, then `gfx_video_hook()`. These are the only palette changes.
* **gfx_shutdown (642e)**: `gfx_clear_screen(0)`, equipment bits = 01b, INT 10h AX=0003h, INT 10h AH=0Bh
  BX=0 (black border).
* **Hercules** (main: `strcmp(argv[?], "herc")` DS:7187 → `herc_init` instead of `gfx_init_ega`):
  herc_init 5f64 (DS:5E6E = 1; equipment bits = 10b; INT 10h AX=0004h; 3BFh = 03h; 3B8h = 02h; 6845 at
  3B4h from DS:5E70 `38 28 2D 0A 7F 06 64 70 02 02 06 07`; clear B800h, 16 KB words; 3B8h = 8Ah).
  video_shutdown 5fbc: if DS:5E6E == 0 → gfx_shutdown; else equipment = 11b, 3BFh = 03h, 3B8h = 20h,
  6845 from DS:5E7C `61 50 52 0F 19 06 19 19 02 0D 0B 0C`, clear B800h, 3B8h = 28h, INT 10h AX=0007h.
  The drawing code has no Hercules path: all primitives still write A000h planes. DUEL.EXE starts
  Hercules through `td2cga.exe herc`, so this is dead in TD2EGA. Not needed for the port.
* **CGA / Tandy** code: none in TD2EGA (separate builds). The only cross-build hook is
  `gfx_video_hook` 5d00 (EGA/Tandy: `retf`; CGA: 3D8h = 0Eh, 3D9h = 30h, i.e. palette cyan/red/white,
  bright; the CGA crash flash toggles 3D9h between 30h and 00h).

### 4.6 Keyboard hardware layer

```c
void kbd_install(void) {                         /* 06c9:6860 */
    u8 m = inb(0x21); outb(0x21, m | 3);         /* mask IRQ0 + IRQ1 while patching */
    if (ivt[9].off != 0x6907) {                  /* only the offset is compared */
        old_int9  = ivt[9];  ivt[9]  = 06c9:6907;
        old_int16 = ivt[0x16]; ivt[0x16] = 06c9:69b7;
    }
    outb(0x21, m);
    memset(key_down, 0, 0x5A);
}

void kbd_restore(void) {                         /* 06c9:68c4 */
    u8 m = inb(0x21); outb(0x21, m | 3);
    if (old_int9.off != 0) {                     /* offset word only */
        ivt[9] = old_int9; ivt[0x16] = old_int16;
        bios_0040_0017 &= 0xF0;                  /* forget shift/ctrl/alt held during the game */
    }
    outb(0x21, m);
}

void interrupt kbd_int9_isr(void) {              /* 06c9:6907 */
    sti();
    u8 sc = inb(0x60);
    u8 p = inb(0x61); outb(0x61, p | 0x80); outb(0x61, p);    /* XT keyboard acknowledge */
    if (sc & 0x80) {                             /* break code (also E0/E1 prefixes) */
        u16 i = sc & 0x7F; if (i >= 0x5A) i = 0;
        key_down[i] = 0;
    } else {
        u16 i = sc; if (i >= 0x5A) i = 0;
        kbd_last_scan = i;
        key_down[i] = 1;
        u8 e;
        if      (key_down[0x38] & 1)                       e = kbd_xlat_alt  [i];
        else if (key_down[0x1D] & 1)                       e = kbd_xlat_ctrl [i];
        else if ((key_down[0x2A] & 1) || (key_down[0x36] & 1)) e = kbd_xlat_shift[i];
        else if (key_down[0x3A] & 1)                       e = kbd_xlat_caps [i];
        else                                               e = kbd_xlat_normal[i];
        if (!(e & 0x80)) kbd_last_key = e;                 /* ASCII, AH = 0 (e == 0 clears the key!) */
        else kbd_last_key = ((e >= 0x85) ? (e & 0x7F) : e) << 8;   /* extended: AL = 0 */
    }
    outb(0x20, 0x20);                            /* EOI; no BIOS chaining */
}

void interrupt kbd_int16_isr(void) {             /* 06c9:69b7 (AX in/out, flags on AH=1) */
    switch (AH) {
    case 0: cli(); AX = kbd_last_key; kbd_last_key = 0; iret;     /* does NOT block */
    case 1: AX = kbd_last_key; sti(); ZF = (AX == 0); retf 2;     /* peek; keeps caller's IF=1 */
    case 2: AX = key_down[0x2A] | key_down[0x36]; iret;           /* AH = 0x02 | … : AL only meaningful */
    default: AX = 0; iret;
    }
}
```
Notes: `case 2` computes `AL = key_down[LShift] | key_down[RShift]` and leaves AH = 2. Nothing in TD2
uses AH=2. E0-prefixed keys (grey arrows, grey Enter, right Ctrl/Alt) arrive as their plain scan codes
(the E0 byte itself just clears `key_down[0]`), so they behave like the keypad keys.

### 4.7 getkey family

```c
u16 getkey_raw(void) {                           /* 06c9:6a03 */
    if (!kbd_peek()) return 0;                   /* INT 16h AH=1 */
    u16 k = kbd_read();                          /* INT 16h AH=0 */
    return (k & 0xFF) ? (k & 0xFF) : k;          /* ASCII -> AH=0, extended -> scan<<8 */
}
u16 getkey_menu(void) {                          /* 06c9:65c5 */
    if (kbd_peek()) return kbd_dispatch(kbd_read());           /* full word, not stripped */
    u16 j = joy_read(), r;
    r = (j & 0x30) ? 0x000D : joy_menu_keys[j & 0x0F];
    if (r == joy_menu_last) return 0;
    joy_menu_last = r; return r;
}
u16 getkey_drive(void) {                         /* 06c9:6601, called once per sim step */
    if (!kbd_peek()) return 0;
    if (SS != DS) return AX_from_peek;           /* inside a foreign stack: key NOT consumed, no hotkeys */
    return kbd_dispatch(kbd_read());
}
u16 kbd_dispatch(u16 key) {                      /* 06c9:6528 */
    cli(); if (hotkey_busy) { sti(); return key; } hotkey_busy = 1; sti();
    u16 idx;
    if (key & 0xFF) idx = key & 0x7F;            /* note: 0x80-0xFF ASCII alias 0x00-0x7F */
    else { idx = key >> 8; if ((s16)idx > 0x84) idx = 0x84; idx += 0x80; }
    u16 h = hotkey_table[idx];
    if (h) { h(); hotkey_busy = 0; return 0; }   /* near call into 06c9, handler ends with retf */
    hotkey_busy = 0; return key;
}
void hotkey_set(u16 key, u16 off) {              /* 06c9:6585 */
    if (key & 0xFF) { if ((s16)key <= 0x7F) hotkey_table[key] = off; return; }
    /* extended key: bug - loads hotkey_table[0x80+0x82] into BX and returns, nothing is written */
}
u16 getkey(void)      { return getkey_fn(); }                       /* 69fe */
u16 getkey_wait(void) { u16 k; do k = getkey(); while (!k); return k; }   /* 6a30 */
u16 kbd_flush(void)   { while (kbd_peek()) kbd_read(); return 0; }  /* 6a3b (no hotkeys) */
u16 getkey_until_deadline(void) {                /* 6a4a, proper 32-bit unsigned compare */
    for (;;) { u16 k = getkey(); if (k) return k; if (ticks_get() >= deadline) return 0; }
}
u16 getkey_timeout(u32 n) {                      /* 6a6a */
    u32 end = ticks_get() + n;
    for (;;) { u16 k = getkey(); if (k) return k; if (ticks_get() >= end) return 0; }
}
u16 getkey_until_slow_deadline(void) {             /* c63e: compare is "hi < dhi || lo < dlo" */
    for (;;) { u16 k = getkey(); if (k) return k;
               u32 t = slow_ticks_get();
               if ((u16)(t >> 16) < (u16)(slow_deadline >> 16)) continue;
               if ((u16)t < (u16)slow_deadline) continue;          /* bug: ignores hi > dhi */
               return 0; }
}
void delay_slow(u32 n) {                           /* c6c5, same buggy compare as c63e */
    u32 end = slow_ticks_get() + n;
    for (;;) { u32 t = slow_ticks_get();
               if ((u16)(t >> 16) < (u16)(end >> 16)) continue;
               if ((u16)t < (u16)end) continue;
               return; }
}
```
The buggy compare only matters when `end` crosses a 0x10000 boundary (it then waits up to 65536
more ticks until the low word catches up). The port can use a plain `t >= end`; note it as a quirk.

### 4.8 Driving input

```c
u16 input_drive_bits(void) {                     /* 06c9:6620 */
    u16 r = 0;
    if (key_down[0x39]) r |= 0x10;               /* Space  -> fire (button A) */
    if (key_down[0x1C]) r |= 0x20;               /* Enter  -> button B */
    if (key_down[0x47]) r |= 0x09;               /* Home   -> up+left */
    if (key_down[0x48]) r |= 0x01;               /* Up */
    if (key_down[0x49]) r |= 0x05;               /* PgUp   -> up+right */
    if (key_down[0x4D]) r |= 0x04;               /* Right */
    if (key_down[0x51]) r |= 0x06;               /* PgDn   -> down+right */
    if (key_down[0x50]) r |= 0x02;               /* Down */
    if (key_down[0x4F]) r |= 0x0A;               /* End    -> down+left */
    if (key_down[0x4B]) r |= 0x08;               /* Left */
    if (r == 0) r = joy_read();                  /* joystick only when no such key is held */
    return r;
}
u16 joy_dir_index(u16 bits) { return joy_dir_map[bits & 0x0F]; }   /* 06c9:6828 */
```
Sim use (`06c9:420a`, simulation spec): `raw = input_drive_bits(); DS:33B1 = raw;
dir = joy_dir_index(raw); if (!DS:90A8) dir |= raw & 0x30; DS:33B0 = dir;` then
`k = getkey_drive()` → `06c9:44a6` compares **AL only** against the table DS:33D6
(`1B 6F 4F 64 44`): ESC → DS:5490 = 0xFF (quit), `o`/`O` → toggle DS:33AF (unless DS:90A8),
`d`/`D` → toggle DS:2F58. Opposite keys held together OR their bits (Up+Down = 3 → index 0, Left+Right
= 0x0C → 0).

### 4.9 Joystick

```c
u16 joy_read(void) {                             /* 06c9:6686 */
    if (!joy_enabled || !(joy_calibrated & 1)) return 0;
    joy_result = 0;
    u8 pre = inb(0x201); joy_port_pre = pre;
    u8 wait = 3; joy_x = 0x50; joy_y = 0x50;
    u16 cx = 0;
    cli(); outb(0x201, pre); /* 4 x nop */
    for (;;) {
        u8 b = (inb(0x201) & wait) ^ wait;       /* axes whose one-shot has ended */
        if (!b) { if (++cx < 4000) continue; break; }          /* 0xFA0, CPU-speed dependent */
        if (b & 1) { joy_x = cx; wait &= 2; if (!wait) break; if (!(b & 2)) continue; }
        joy_y = cx; wait &= 1; if (!wait) break;               /* (b & 2) here */
        /* no ++cx on an iteration that caught an edge */
    }
    sti();
    /* ---- X: all compares signed ---- */
    s16 x = joy_x;
    if (x < joy_xmin) {
        joy_xmin = x;
    recalc_x: {
        s16 range = joy_xmax - joy_xmin;
        if (range > 0) joy_xscale = 0x4000 / (u16)range;       /* 32/16 unsigned div, DX = 0 */
        u16 h = (u16)range >> 1, q = h >> 1;
        joy_xhi = joy_xmin + h + q; joy_xlo = joy_xhi - 2 * q; }
        x = joy_x;
        goto reset_x;
    } else if (x > joy_xmax) {
        if (--joy_xover_cnt == 0) { joy_xmax = joy_xover_min; goto recalc_x; }
        if (x < joy_xover_min) joy_xover_min = x;
        goto cmp_x;
    }
reset_x:
    joy_xover_cnt = 8; joy_xover_min = 20000;    /* 0x4E20 */
cmp_x:
    if (x < joy_xlo) joy_result |= 8;            /* left  */
    else if (x >= joy_xhi) joy_result |= 4;      /* right */
    /* ---- Y: min and threshold compares UNSIGNED, max / over_min compares signed ---- */
    u16 y = joy_y;
    if (y < (u16)joy_ymin) { joy_ymin = y; recalc_y: /* same as X with y vars, joy_yscale */ ;
                             y = joy_y; goto reset_y; }
    else if ((s16)y > joy_ymax) {
        if (--joy_yover_cnt == 0) { joy_ymax = joy_yover_min; goto recalc_y; }
        if ((s16)y < joy_yover_min) joy_yover_min = y;
        goto cmp_y;
    }
reset_y:
    joy_yover_cnt = 8; joy_yover_min = 20000;
cmp_y:
    if (y < (u16)joy_ylo) joy_result |= 1;       /* up   */
    else if (y >= (u16)joy_yhi) joy_result |= 2; /* down */
    joy_result |= ((inb(0x201) & joy_port_pre) & 0x30) ^ 0x30;   /* buttons, active low, either sample */
    return joy_result;                           /* AH = 0 */
}

void joy_calib_reset(void) {                     /* 06c9:680a */
    joy_enabled = 1; joy_xmin = 0x50; joy_xmax = 0; joy_ymin = 0x50; joy_ymax = 0;
    /* over counters / over_min are NOT reset */
}
s16 joy_analog_x(void) { return (s16)((u16)(((u32)(u16)(joy_x - joy_xmin) * joy_xscale) >> 8) - 0x1F); } /* dead */
```
Calibration model as TD1: min follows the smallest sample at once, max moves only after 8
consecutive samples above it (then takes the smallest of them), thresholds at 25 % / 75 %.
Quirk: the over-counters start at **0** (data) and `joy_calib_reset` does not touch them, so the first
above-max sample decrements 0 → 0xFFFF; max can then only move after 65 535 more above-max samples
unless an in-range or below-min sample resets the counter to 8 first. Since max starts at 0, a sample
is "in range" only after max has moved, so in practice the first sweep of the stick towards a smaller
count than 0x50 (or a lower-than-min sample) is what resets the counter. The port should keep the
logic but may initialise the counters to 8 (recommended, it removes a startup dead zone).

### 4.10 Hotkeys and prompts

```c
void hotkeys_install(void) {                     /* 16fc:0002 */
    hotkey_set(0x0A, 0x645A);   /* Ctrl-J */
    hotkey_set(0x0B, 0x646F);   /* Ctrl-K */
    hotkey_set(0x10, 0x6508);   /* Ctrl-P */
    hotkey_set(0x11, 0x64C7);   /* Ctrl-Q */
    hotkey_set(0x13, 0x6488);   /* Ctrl-S */
    hotkey_set(0x18, 0x6518);   /* Ctrl-X */
}
void hotkey_joystick_on(void)  { joy_enabled = 1; timer_paused = 1; joy_calibrate_screen(); timer_paused = 0; }
void hotkey_keyboard_on(void)  { joy_enabled = 0; message_box("KEYBOARD ON", 8); }
void hotkey_sound_toggle(void) {
    if (!(snd_enable & 1)) { snd_enable |= 1; message_box("SOUND ON", 8); }
    else { snd_enable &= 2; DS_5EEE = 0; DS_5EFC = 0; message_box("SOUND OFF", 8); }
}
void hotkey_music_toggle(void) {
    if (!(snd_enable & 2)) { snd_enable |= 2; message_box("MUSIC ON", 8); }
    else { snd_enable &= 1; DS_5EEE = 0; DS_5EFC = 0; message_box("MUSIC OFF", 8); }
}
void hotkey_pause(void) { timer_paused = 1; prompt_pause();        timer_paused = 0; }
void hotkey_exit(void)  { timer_paused = 1; prompt_exit_to_dos();  timer_paused = 0; }
```
`message_box` is **not** wrapped in timer_paused: the game keeps running (the sim tick fires
while the box is up, and `delay_slow` waits 8 real-time ticks). The messages are shown and removed
before the handler returns, so they appear only for the delay.

The three boxes share one pattern (all three verified):

```c
void box_common(u16 sx, u16 sy, u16 w, u16 h, draw_fn draw) {
    far ptr save = gfx_create_buffer(w, h, 0x0F);    /* 06c9:b0fe(w, h, planes) */
    far ptr canvas = gfx_create_buffer(w, h, 0x0F);
    u16 gstate[26]; u16 tstate[11];
    gfx_targets_save(gstate);  text_state_save(tstate);
    gfx_select_target(save);   gfx_grab_screen(sx, sy, 0, 0, w, h);    /* 06c9:c784 */
    gfx_select_target(canvas); gfx_clear_clip(0);                    /* 06c9:843e(0) */
    gfx_set_text_colours(15, 0);
    draw(canvas);
    gfx_select_target(SCREEN /* 06c9:af54 */);
    blit_copy_raw(canvas, sx, sy);                             /* 06c9:9c90(spr, x, y) */
    WAIT;
    blit_copy_raw(save, sx, sy);
    text_state_restore(tstate); gfx_targets_restore(gstate);
    gfx_free_buffer(canvas); gfx_free_buffer(save);                     /* 06c9:782c, most recent first */
}
```

| prompt | sx, sy, w, h | draw | WAIT |
|---|---|---|---|
| `prompt_pause` 16fc:0358 | 0, 0x58, 0x140, 0x18 | `draw_rect_outline(4,4,0x13C,0x14, 4)`; `draw_text_centered("PAUSE - PRESS ANY KEY TO RESUME", 8)` | `fn = get(); set(getkey_raw); do k = getkey_wait(); while (!k); set(fn);` |
| `prompt_exit_to_dos` 16fc:007c | 0x50, 0x58, 0xA0, 0x18 | `draw_rect_outline(4,4,0x9B,0x14, 4)`; `draw_text_centered("EXIT TO DOS (Y/N)", 9)` | `fn = get(); set(getkey_raw); k = getkey_wait(); if (toupper_c(k) == 'Y') { kbd_restore(); timer_restore() /*06c9:610a*/; gfx_shutdown(); exit(0); } set(fn);` |
| `message_box(s, n)` 16fc:0220 | 0, 0xBE, 0x140, 0x0A | `draw_text_centered(s, 1)` (no frame) | `delay_slow(n)` (callers pass 8) |

`draw_text_centered` measures against the **current target** width (`CS:AF52`), i.e. the canvas
(320 or 160 px), so the text is centred inside the box. Only keyboard keys end the pause (joystick
buttons do not, because `getkey_raw` never reads the joystick). The exit prompt's `toupper_c` takes the
low byte, so `y`/`Y` quit; an extended key (AL=0) is "no".

```c
void draw_rect_outline(s16 x0, s16 y0, s16 x1, s16 y1, u16 c) {   /* 16af:0006 */
    s16 w = x1 - x0 + 1, h = y1 - y0;
    if (w > 0) { gfx_fill_rect(x0, y0, w, 1, c); gfx_fill_rect(x0, y1, w, 1, c); }
    if (h > 0) { gfx_fill_rect(x0, y0, 1, h, c); gfx_fill_rect(x1, y0, 1, h, c); }
}
void draw_text_centered(char *s, u16 y) {        /* image 0x16ABC */
    s16 wid = CS_AF52;                           /* current target width */
    gfx_draw_text(s, (s16)(wid / 2) - (s16)(strlen(s) << 2), y);   /* cwd; sub; sar = signed /2 */
}
int toupper_c(int c) { s8 b = c; if (b >= 'a' && b <= 'z') b -= 0x20; return b; }  /* 16aa:0002 */
```

### 4.11 Joystick calibration screen (1769:000e)

```c
void joy_calibrate_screen(void) {
    joy_calibrated = 1;                          /* word write */
    if (input_drive_bits() & 0x10) {             /* Space held or button A -> cancel */
        joy_enabled = 0; joy_calibrated = 0;     /* both word writes */
        kbd_flush(); return;
    }
    gfx_targets_save(gs); text_state_save(ts);
    far ptr save = gfx_create_buffer(0x140, 0xC8, 0x0F);
    gfx_select_target(save); gfx_grab_screen(0, 0, 0, 0, 0x140, 0xC8);
    gfx_clear_screen(0);                         /* 06c9:840a */
    gfx_select_target(SCREEN);
    gfx_set_clip_current(0, SCREEN_desc.w /*CS:AF68*/, 0, 0xC8);           /* 06c9:5dfb(x0,x1,y0,y1) */
    gfx_set_text_colours(15, 0);
    draw_text_centered(" Calibrate your joystick by using it ", 0x23);
    draw_text_centered(" to move the joystick position indicator ", 0x2D);
    draw_text_centered(" below, to all squares ", 0x37);
    draw_text_centered(" Press joystick button when complete ", 0xB9);
    gfx_draw_line(0x82, 0x46, 0x82, 0xA0, 15);   /* 06c9:c984(x0,y0,x1,y1,c): verticals x=130,170 */
    gfx_draw_line(0xAA, 0x46, 0xAA, 0xA0, 15);
    gfx_draw_line(0x5A, 0x64, 0xD2, 0x64, 15);   /* horizontals y=100,130, x 90..210 */
    gfx_draw_line(0x5A, 0x82, 0xD2, 0x82, 15);
    s16 prev = -1;
    joy_calib_reset();                           /* 1769:0171, once */
    for (;;) {                                   /* loop target 1769:0176 */
        if (getkey_raw()) break;                 /* any key ends */
        u16 j = joy_read();
        if (j & 0x30) break;                     /* either button ends */
        u16 d = joy_dir_index(j);
        if (d == prev) continue;
        for (int i = 0; i < 9; i++) gfx_fill_rect(calib_sq_x[i], calib_sq_y[i], 0x20, 0x18, 0);
        gfx_fill_rect(calib_sq_x[d], calib_sq_y[d], 0x20, 0x18, 4);
        prev = d;
    }
    blit_copy_own(save);                           /* 06c9:9cc2: at the sprite's own x,y (0,0) */
    gfx_free_buffer(save);
    text_state_restore(ts); gfx_targets_restore(gs);
    delay_slow(4);
    kbd_flush();
}
```
The calibration starts from scratch every time the screen is shown (`joy_calib_reset` before the
loop); the player sweeps the stick so min/max converge (see 4.9). Only the square changes are drawn.
The calibration is not skipped when already done: Ctrl-J shows the screen every time.

### 4.12 Text drawing (06c9:a530 / a547)

Identical to TD1 0x4BD0/0x4BE7 (`TestDrive1987/tdport/src/platform/gfx.c` `text_render`), with the
state block at DS:6820 (fg 6820, bg 6822, margin 6824, x 6826, y 6828, glyph_h 682C, table 682E,
adv_x 6832, adv_y 6834, enabled 6836) and the current-target descriptor at CS:AF3A (plane segments
CS:AF3C–AF42, row table pointer CS:AF44, stride CS:AF4E; screen when plane 0 segment == 0xA000):

```c
void gfx_draw_text(const u8 *s, u16 x, u16 y) { text_x = x; text_y = y; text_render(s); }
static void text_render(const u8 *s) {           /* 06c9:a54f */
    u8 eq = 0;
    if (plane_seg[0] == 0xA000) { eq = ~(fg ^ bg); gc(1, eq); gc(0, fg & bg); }
    if (text_enabled == 1) for (u8 ch; (ch = *s) != 0; s++) {
        u16 g = DGROUP_W(ch * 2 + text_font_off);            /* table has 220 entries, see 3 */
        if (g == 0) { if (ch == 0x0D || ch == 0x0A) { text_x = text_margin_x; text_y += text_adv_y; } continue; }
        u16 pos = (text_x >> 3) + row_table[text_y];          /* byte-aligned, no clipping */
        /* RAM target: per present plane k: fg_k==bg_k -> fill 0x00/0xFF; else glyph or ~glyph;
           EGA: map mask fg|eq write glyph, then if (fg^bg)&bg: map mask bg|eq write ~glyph   */
        ...;
        text_x += text_adv_x;
    }
    gc(1, 0);
}
```
Opaque 8×8 cells, x rounded down to a multiple of 8, CR/LF only when their table entry is 0 (it is).
Characters ≥ 0x8C have a 0 entry up to 0xDB (skipped, no advance); 0xDC–0xE2 would read pointers out
of the string "%s FILE ERROR" at DS:5D7A (never used by the game's strings).

Built-in font (DS:5BC2 table, glyphs DS:585A + 8·(c−0x20), rows top→bottom, MSB = left):
85 glyphs are byte-identical to TD1's `font8x8.json`. Differences: `3C <`, `5B [`, `5C \`,
`5D ]`, `5E ^`, 0x60 (backquote), `7B {`, 0x7C (bar) are proper characters in TD2 (TD1 had icons there);
`7D }`, `7E ~`, `7F` (house/triangle) and 0x80–0x8B are new. TD1's icons 91–94 now live at
0x87 (91), 0x88 (92), 0x89 = 0x80 (93), 0x8A (94). Full table (see
`work/platform/fonts/builtin_8x8.png`):

| glyphs | | | | | |
|---|---|---|---|---|---|
| 20 0000000000000000 | 21 3078783030003000 | 22 6C6C6C0000000000 | 23 6C6CFE6CFE6C6C00 | 24 307CC0780CF83000 | 25 00C6CC183066C600 |
| 26 386C3876DCCC7600 | 27 6060C00000000000 | 28 1830606060301800 | 29 6030181818306000 | 2A 00663CFF3C660000 | 2B 003030FC30300000 |
| 2C 0000000000303060 | 2D 000000FC00000000 | 2E 0000000000303000 | 2F 060C183060C08000 | 30 7CC6C6C6C6C67C00 | 31 307030303030FC00 |
| 32 78CC0C3860CCFC00 | 33 78CC0C380CCC7800 | 34 1C3C6CCCFE0C1E00 | 35 FCC0F80C0CCC7800 | 36 3860C0F8CCCC7800 | 37 FCCC0C1830303000 |
| 38 78CCCC78CCCC7800 | 39 78CCCC7C0C187000 | 3A 0030300000303000 | 3B 0030300000303060 | 3C 183060C060301800 | 3D 0000FC0000FC0000 |
| 3E 6030180C18306000 | 3F 78CC0C1830003000 | 40 7CC6DEDEDEC07800 | 41 3078CCCCFCCCCC00 | 42 FC66667C6666FC00 | 43 3C66C0C0C0663C00 |
| 44 F86C6666666CF800 | 45 FE6268786862FE00 | 46 FE6268786860F000 | 47 3C66C0C0CE663E00 | 48 CCCCCCFCCCCCCC00 | 49 7830303030307800 |
| 4A 1E0C0C0CCCCC7800 | 4B E6666C786C66E600 | 4C F06060606266FE00 | 4D C6EEFEFED6C6C600 | 4E C6E6F6DECEC6C600 | 4F 386CC6C6C66C3800 |
| 50 FC66667C6060F000 | 51 78CCCCCCDC781C00 | 52 FC66667C6C66E600 | 53 78CCE0701CCC7800 | 54 FCB4303030307800 | 55 CCCCCCCCCCCCFC00 |
| 56 CCCCCCCCCC783000 | 57 C6C6C6D6FEEEC600 | 58 C6C66C38386CC600 | 59 CCCCCC7830307800 | 5A FEC68C183266FE00 | 5B 7860606060607800 |
| 5C C06030180C060200 | 5D 7818181818187800 | 5E 10386CC600000000 | 5F 00000000000000FF | 60 3030180000000000 | 61 0000780C7CCC7600 |
| 62 E060607C6666DC00 | 63 000078CCC0CC7800 | 64 1C0C0C7CCCCC7600 | 65 000078CCFCC07800 | 66 386C60F06060F000 | 67 000076CCCC7C0CF8 |
| 68 E0606C766666E600 | 69 3000703030307800 | 6A 0C000C0C0CCCCC78 | 6B E060666C786CE600 | 6C 7030303030307800 | 6D 0000CCFEFED6C600 |
| 6E 0000F8CCCCCCCC00 | 6F 000078CCCCCC7800 | 70 0000DC66667C60F0 | 71 000076CCCC7C0C1E | 72 0000DC766660F000 | 73 00007CC0780CF800 |
| 74 10307C3030341800 | 75 0000CCCCCCCC7600 | 76 0000CCCCCC783000 | 77 0000C6D6FEFE6C00 | 78 0000C66C386CC600 | 79 0000CCCCCC7C0CF8 |
| 7A 0000FC983064FC00 | 7B 1C3030E030301C00 | 7C 1818180018181800 | 7D E030301C3030E000 | 7E 76DC000000000000 | 7F 0010386CC6C6FE00 |
| 80 0002044850200000 | 81 183060FE60301800 | 82 30180CFE0C183000 | 83 10387CD610101000 | 84 101010D67C381000 | 85 000000FF00000000 |
| 86 1010101010101010 | 87 0824929224080000 | 88 7C669292C67C0000 | 89 0002044850200000 | 8A 002060FEFE602000 | 8B 00000000000000FF |

### 4.13 Timer install / restore / routine list

```c
#define PIT_HZ 1193182
#define TIMER_DIV 0x2E9C                 /* 11932 → 99.9985 Hz; every caller uses this value */

void timer_install_drive(void) {         /* 601c */
    chain_reload = chain_count = 5; chain_budget = 100; chain_countdown_on = 1;
    /* chain_enable NOT touched: stays 1 after menus → BIOS gets 100 more calls (5 s), then stops */
    timer_install_common(TIMER_DIV);
}
void timer_install_menu(void) {          /* 603c, dead */
    chain_reload = chain_count = 5; chain_countdown_on = 0; chain_enable = 1;
    timer_install_common(TIMER_DIV);
}
void timer_install_div(int div) {        /* 6059: main 0000:0816, 0267:1c3a with 0x2E9C */
    chain_reload = chain_count = (s16)(0x10000L / div);   /* idiv, DX:AX = 0x00010000 → 5 */
    chain_countdown_on = 0; chain_enable = 1;
    timer_install_common(div);
}
void timer_install_div_countdown(int div) {  /* 607a, dead; chain_enable untouched */
    chain_reload = chain_count = (s16)(0x10000L / div);
    chain_budget = 100; chain_countdown_on = 1;
    timer_install_common(div);
}
static void timer_install_common(u16 div) {  /* 6099 */
    cli(); timer_routines[0] = NULL; sti();  /* off and seg words = 0 → list empty */
    outb(0x61, inb(0x61) & 0xFC);            /* speaker off */
    outb(0x43, 0xB6);                         /* ch2 lo/hi mode 3; ch0 mode is not reprogrammed */
    outb(0x21, inb(0x21) | 0x03);             /* mask IRQ0/1 */
    prof_index = 0; memset(prof_counts, 0, 40 * 2);
    cli();
    if (IVT[8].off != 0x61BF) old_int8.off = IVT[8].off;
    if (IVT[8].seg != CS) { old_int8.seg = IVT[8].seg; IVT[8] = CS:0x61BF; }
    outb(0x21, inb(0x21) & 0xFC);             /* unmask IRQ0/1 */
    sti();
    outb(0x40, div & 0xFF); outb(0x40, div >> 8);
}
void timer_restore(void) {                    /* 610a: exit, fatal (16a7:0002), 16fc:007c */
    if (IVT[8].seg != CS || IVT[8].off != 0x61BF) return;
    outb(0x21, inb(0x21) | 3); cli(); IVT[8] = old_int8; outb(0x21, inb(0x21) & 0xFC); sti();
    outb(0x40, 0); outb(0x40, 0);             /* 18.2 Hz */
    outb(0x61, inb(0x61) & 0xFC);
}
void timer_add_routine(farfn fn) {            /* 614c */
    int i;
    for (i = 0; i < 5; i++) if (timer_routines[i].seg == 0) break;
    if (i == 5) fatal("NO ROOM LEFT ON TIMER INTERRUPT ROUTINE LIST\r");   /* 16a7:0002, no return */
    timer_routines[i].off = fn.off; timer_routines[i].seg = 0; timer_routines[i].seg = fn.seg;
    timer_routines[i + 1].seg = 0;            /* i+1 ≤ 5: slot 5 is the terminator */
}
void timer_remove_routine(farfn fn) {         /* 6180 */
    int i;
    for (i = 0; i < 5; i++) if (timer_routines[i].off == fn.off && timer_routines[i].seg == fn.seg) break;
    if (i == 5) return;
    cli();
    for (; i < 4; i++) timer_routines[i] = timer_routines[i + 1];
    timer_routines[4].off = timer_routines[4].seg = 0;
    sti();
}
```

### 4.14 ISR

```c
void interrupt timer_isr(void) {              /* 61bf */
    cli(); push all;
    outb(0x20, 0x20);                         /* EOI first */
    DS = DGROUP; sti();                       /* runs with interrupts enabled */
    if (--chain_count <= 0) {                 /* signed */
        slow_count++;                         /* u32 */
        chain_count = chain_reload;
        if (chain_enable) timer_bios_chain();
    }
    if (timer_paused) { outb(0x61, inb(0x61) & 0xFC); goto out; }
    prof_counts[prof_index / 2]++;            /* word at 5E9E + prof_index */
    tick_count++;                             /* u32 */
    for (i = 0; timer_routines[i].seg != 0; i++) { cli(); timer_routines[i](); }
out:
    pop all; iret;
}
static void timer_bios_chain(void) {          /* 6230 */
    if (chain_countdown_on && --chain_budget <= 0) { chain_countdown_on = 0; chain_enable = 0; }
    IVT[8] = old_int8; int86(8); IVT[8] = CS:0x61BF;   /* this call still happens */
}
```

### 4.15 Effect stream player (`sfx_tick`, 06c9:6269) and its API

```c
void far sfx_tick(void) {
    if (!(snd_enable & 1)) { snd_busy = 0; sfx_seg = 0; sfx_note_left = 0; spk_off(); return; }
    if (sfx_note_left) {
        u16 old = sfx_note_left--;
        if (old == sfx_note_cut) spk_off();
        return;
    }
    for (;;) {
        if (sfx_seg == 0) goto end;
        u8 *p = MK_FP(sfx_seg, sfx_off);
        s8 op = p[0];
        if (op >= 0) {
            sfx_note_left = rd16(p + 1); sfx_off += 3;
            if (op == 0) { sfx_note_cut = 0; spk_off(); return; }
            sfx_note_cut = sfx_shift ? sfx_note_left >> sfx_shift : 0;
            u16 d = sfx_div[op];                                /* DS:5F2E[op]; op ≤ 0x7F reads past 92 */
            outb(0x42, d & 0xFF); outb(0x42, d >> 8);
            outb(0x61, inb(0x61) | 3);
            return;
        }
        unsigned k = (u8)-op;
        if (k > 0x0B) goto end;                                 /* 80..F4 behave as FF (range check, TD1 had none) */
        switch (k) {                                            /* CS:6334 */
        case 1: goto end;                                       /* FF */
        case 2: sfx_shift = p[1]; sfx_off += 2; break;          /* FE s */
        case 3: case 4: case 5:                                 /* FD/FC/FB n16 */
            sfx_loop_cnt[k-3] = rd16(p + 1); sfx_off += 3; sfx_loop_start[k-3] = sfx_off; break;
        case 6: case 7: case 8:                                 /* FA/F9/F8 */
            if (--sfx_loop_cnt[k-6] < 0) sfx_off += 1;          /* js */
            else { sfx_loop_end[k-6] = sfx_off; sfx_off = sfx_loop_start[k-6]; }
            break;
        case 9: case 10: case 11:                               /* F7/F6/F5 */
            if (sfx_loop_cnt[k-9] == 0) sfx_off = sfx_loop_end[k-9]; else sfx_off += 1;
            break;
        }
        continue;
    end:                                                        /* 62fd */
        snd_busy = 0;
        if (sfx_loop_set) { sfx_off = sfx_loop_off; sfx_seg = sfx_loop_seg; continue; }
        sfx_note_left = 0; spk_off(); return;                   /* pointer stays on the FF: re-hit every tick */
    }
}
static void spk_off(void) { outb(0x61, inb(0x61) & 0xFC); }

void sfx_set_loop(u8 far *s) { cli(); sfx_loop = s; sfx_loop_set = 1; if (!snd_busy) sfx_cur = s; sti(); } /* 7946 */
void sfx_clear_loop(void)    { sfx_loop_set = 0; }                                                      /* 7971 */
void sfx_play(u8 far *s)     { cli(); sfx_cur = s; snd_busy = 1; sti(); }                               /* 7977 */
int  sfx_is_playing(void)    { return snd_busy; }                                                       /* 798f */
void sfx_stop(void)          { sfx_seg = 0; }                                                           /* 7995 */
void sfx_play_if_enabled(u8 far *s) { if (snd_enable == 3) sfx_play(s); }                               /* 799c */
void sound_off(void) { snd_enable &= 2; sfx_seg = 0; }   /* 7934 */
void sound_on(void)  { snd_enable |= 1; }                /* 7940 */
void music_on(void)  { snd_enable |= 2; }                /* 79bb */
void music_off(void) { snd_enable &= 1; }                /* 79c1 */
```

Event timing is identical to TD1: a note with duration d lasts **d+1 ticks**. With cut c = d>>shift ≠ 0 it sounds
d+1−c ticks and is silent for c ticks; c = 0 means legato. `sfx_play` and `sfx_set_loop` do not reset `sfx_note_left`, so the note
that is sounding finishes first. When a one-shot ends, the loop stream restarts from its start. The loop stream loops forever.
The stale-`loop_end` bug of the break opcodes is still there.

Driving use (details in the simulation spec):
* `06c9:1b4e` `sfx_set_loop(DS:1352)`: engine loop, 4 ticks of slot 0x55 + 2 ticks of slot 0x56, shift 0.
* `06c9:1e41` (stage init `06c9:1e31`): slots 0x55, 0x56, 0x57 = 0xFFFF.
* `06c9:412c` (called at the start of `06c9:403b`, every tick, after `sfx_tick` in the list order): `DS:336A++`,
  slot 0x58 = `DS:32AE[DS:336A & 31]`. Rpm display `DS:332A` slews ±0x60 toward `DS:332C`, and slot 0x55 = `DS:30E8[(DS:332A >> 5) & 0xFFFE]`.
  Slot 0x56: if `DS:3374 != 0`: when `DS:942E & 8`, a sweep of `DS:3350` by ±2 per tick between 0x5DC and 0x708
  (direction `DS:335C`, likely the siren); otherwise 0x7D0 or 0x5DC depending on `DS:3346 & 4` (two-tone, toggling every 40 ticks).
  If `DS:3374 == 0`: when `DS:33BC`, 0x384; otherwise on the tick before a sim step (`DS:3368 == 1`), 0x474 while
  the countdown `DS:33B2` runs, else 0xFFFF; after that, `DS:336F != 0` forces 0x8E8 (TD1: tyre squeal).
  The simulation spec should name these triggers. Slot 0x57 is only set to 0xFFFF (stage init), and no stream uses it.
* `06c9:3532` and `06c9:3643`: `sfx_play(DS:549F)`, a 102-tick noise burst (likely crash). `06c9:4a2e`: `sfx_play(DS:5494)`, a 22-tick burst.
* `06c9:1b9b`, `06c9:1bd7`: `sfx_clear_loop()` at the stage end. `06c9:1beb` `timer_install_drive()` then drops `sfx_tick` from the list,
  and the next `timer_install_div` silences the speaker.

### 4.16 Music player (`music_tick`, 06c9:75ea)

```c
void music_play(u8 far *songs, int n) {          /* 758a */
    if (snd_enable != 3) return;
    u16 *e = songs + n * 4;
    cli();
    mus_seg = FP_SEG(songs);                     /* offsets below are used with this segment; FP_OFF(songs) must be 0 */
    mus_list = mus_list_loop = e[0];
    mus_list2 = mus_list2_loop = e[1];
    mus_start = 1; snd_busy = 1;
    sti();
}
void music_set_voices(u8 far *v) { mus_voices = v; }   /* 75c8 */

#define MB(o) (*(u8 *)MK_FP(mus_seg, o))
void far music_tick(void) {
    if (snd_enable != 3) goto stop;
    if (mus_start) {
        mus_start = 0;
        outb(0x61, inb(0x61) | 2);              /* speaker data on; notes switch only the gate (bit0) */
        goto next_pattern;
    }
    if (!snd_busy) goto stop;
    goto step;

next_pattern:                                   /* 761e */
    if (mus_list == 0) goto stop;
    mus_pat = MW(mus_list);
    mus_transpose = MB(mus_list + 2) + mus_transpose_base;
    mus_list += 3;
next_event:                                     /* 7643 */
    for (;;) {
        u16 si = mus_pat;
        if (si == 0) goto stop;
        mus_pat += 2;
        s8 op = MB(si); u8 arg = MB(si + 1);
        if (op >= 0) break;                     /* note or rest */
        if (op < -5) goto stop;                 /* 80..FA */
        switch (-op) {                          /* CS:766C */
        case 1: mus_list = mus_list_loop; goto next_pattern;          /* FF */
        case 2: mus_tempo = arg; continue;                            /* FE */
        case 3: memcpy(&DS:6609, mus_voices + arg * 32, 28); continue;/* FD, 14 words */
        case 4: goto next_pattern;                                    /* FC */
        case 5: snd_busy = 0; mus_start = 0; mus_list = 0; mus_list2 = 0; return;  /* FB: speaker left as is */
        }
    }
    /* note / rest */
    if (op == 0) {
        mus_off_left = (u8)mus_tempo * arg;    /* mul byte: AL * arg */
        mus_on_left = 0;
        goto gate_off_then_off_part;
    } else {
        u16 len = (u8)mus_tempo * (arg & 0x7F);
        u16 off = ((arg & 0x80) || voice.shift == 0) ? 0 : len >> voice.shift;  /* shr dx,cl */
        mus_off_left = off;
        mus_on_left = len - off;
        if (mus_on_left == 0) goto gate_off_then_off_part;
        mus_note = op + mus_transpose;
        mus_div = mus_div_table[mus_note];      /* DS:663B, no range check */
        outb(0x42, mus_div & 0xFF); outb(0x42, mus_div >> 8);
        outb(0x61, inb(0x61) | 1);              /* gate on */
        mus_arp_cnt = voice.arp_init;
        mus_arp_idx = 0; mus_vib_ofs = 0;
        mus_vib_cnt = voice.vib_delay;
        mus_vib_dir = voice.vib_dir ? voice.vib_dir : 1;
        /* fall into step */
    }
step:                                           /* 7758 */
    if (mus_on_left != 0) {
        if (--mus_on_left != 0) goto effects;
        outb(0x61, inb(0x61) & 0xFE);           /* gate off */
        mus_start = 0;
        return;
    }
off_part:                                       /* 7771 */
    if (mus_off_left != 0) { mus_off_left--; return; }
    goto next_event;

gate_off_then_off_part:                         /* 76e3 */
    outb(0x61, inb(0x61) & 0xFE);
    goto off_part;

effects:                                        /* 7780 */
    if (mus_arp_cnt != 0 && --mus_arp_cnt == 0) {
        mus_arp_cnt = voice.arp_reload;
        mus_arp_idx++;
        u8 d = DS:[0x6611 + (mus_arp_idx & voice.arp_mask)];   /* arp_table, mask may index past it */
        mus_div = mus_div_table[d + mus_note];
    }
    if (mus_vib_cnt != 0) { mus_vib_cnt--; goto out; }
    for (;;) {                                  /* 77c2 */
        s16 v;
        if (mus_vib_dir >= 0) { v = mus_vib_ofs + voice.vib_step; if (v > voice.vib_max) goto bounce; }
        else                  { v = mus_vib_ofs - voice.vib_step; if (v < voice.vib_min) goto bounce; }
        mus_vib_ofs = v; break;
    bounce:                                     /* 77fc */
        if (voice.vib_dir == 0) { mus_vib_dir = -mus_vib_dir; continue; }   /* triangle; hangs if both limits fail */
        mus_vib_ofs = 0; break;                                             /* sawtooth */
    }
    mus_vib_cnt = voice.vib_period;
out:
    { u16 d = mus_vib_ofs + mus_div; outb(0x42, d & 0xFF); outb(0x42, d >> 8); }
    return;

stop:                                           /* 7602 */
    snd_busy = 0; mus_start = 0;
    outb(0x61, inb(0x61) & 0xFC);
}
```

Timing of one event (tempo t, length unit n): the next event is fetched exactly **t·n ticks** later.
A rest is silent for t·n ticks. For a note with on = t·n − off: the gate is on at the fetch tick and goes off on the
on-th following tick, so the tone sounds **on − 1** tick intervals and is silent **off + 1**. A note with on == 1 is a click.
Length 0 is skipped in the same tick. The effects run on the fetch tick too.
Neither `music_play` nor the FF restart resets tempo or voice: they persist in DGROUP (initial tempo 0x14 and the
EXE voice). Every shipped pattern starts with FD (and song starts with FE), so this does not matter for the shipped data.

Helpers used below: `MK_FP(seg,off)`, `FP_SEG`, `FP_OFF`, `rd16/rd32` (little-endian), `normalize(p)`:
`if (off > 0x8000) { off -= 0x8000; seg += 0x800; }`. Paragraph rounding in this code is always
`paras(x) = (u16)(x >> 4) + ((x & 0xF) != 0)`.

### 4.17 Small DOS / BIOS helpers

```c
char *make_tick_id(void)                                  /* 06c9:5d2e */
{
    u16 cx, dx; bios_get_ticks(&cx, &dx);                 /* int 1Ah AH=0 (also clears the midnight flag) */
    g_tick_id_w0 = (cx & 0x3F3F) | 0x8080;                /* DS:52C2 */
    g_tick_id_w1 = (dx & 0x3F3F) | 0x8080;                /* DS:52C4 */
    return (char *)0x52C2;                                /* 4 bytes, NOT NUL-terminated */
}
int  dos_num_drives(void) { u8 d = dos_getdrive(); return dos_setdrive(d); }  /* 06c9:5d4e: AL of AH=0Eh, AH=0 */
int  set_file_hidden(char *n) { return dos_chmod_set(n, 2) ? 1 : 0; }        /* 06c9:5d5b: AX=4301h CX=2 */
int  bios_floppy_count(void)                              /* 06c9:5d74 */
{   int n = (bios_equipment() & 0xC0) >> 6;  if (n == 0) n = 1;  return n + 1; }   /* 0,1 -> 2; 2 -> 3; 3 -> 4 */
u16  bios_ticks(void) { return *(u16 far *)MK_FP(0x40, 0x6C); }            /* 06c9:5d83 */
u16  bios_ticks_since(u16 t0) { return bios_ticks() - t0; }               /* 06c9:5d8d */

u16 file_paras(const char *name)                          /* 06c9:5e1c */
{
    int fd;
    if (dos_open(name, 0, &fd)) fatal("%s FILE ERROR", name);   /* DS:5D7A, no \r */
    u32 size = dos_lseek(fd, 0, SEEK_END);
    dos_lseek(fd, 0, SEEK_SET);
    dos_close(fd);
    return paras(size);                                   /* 16-bit result */
}

u16 unpacked_paras(const char *name)                      /* 06c9:5e8a (same error path) */
{
    int fd; u8 h[4];
    if (dos_open(name, 0, &fd)) fatal("%s FILE ERROR", name);
    if (dos_read(fd, h, 4) != 4) { dos_close(fd); fatal("%s FILE ERROR", name); }
    dos_close(fd);
    u32 size = h[1] | h[2] << 8 | (u32)h[3] << 16;       /* the type byte is ignored */
    return paras(size);
}

char *find_first(const char *spec)                        /* 06c9:5ef4 */
{
    dos_setdta(DS:5DEE);
    if (dos_findfirst(spec, 6 /* hidden+system */)) return NULL;
    /* copy spec to DS:5D88 (at most 0x57 chars incl. NUL); remember the position after the last ':' or '\' */
    char *d = g_find_path, *namepos = g_find_path; const char *s = spec;
    for (int i = 0; i < 0x57; i++) { char c = *d++ = *s++; if (!c) break; if (c == ':' || c == '\\') namepos = d; }
    memcpy(namepos, g_dta.name /* DS:5E0C */, 13);
    return g_find_path;
}
char *find_next(void)                                     /* 06c9:5f4e */
{   dos_setdta(DS:5DEE); if (dos_findnext()) return NULL; memcpy(g_find_name_ptr, DS:5E0C, 13); return g_find_path; }

char *find_nth_file(const char *spec, int n)              /* 16b8:0000 */
{   char *r = find_first(spec); for (int i = 1; i < n && r; i++) r = find_next(); return r; }
```

### 4.18 File loading and writing

```c
far ptr load_file_at(const char *name, u16 off, u16 seg)  /* 06c9:6aa2 */
{
    int fd;
    if (dos_open(name, 0, &fd)) goto err;
    for (u16 s = seg;; s += 0x400) {
        int n;
        if (dos_read(fd, MK_FP(s, off), 0x4000, &n)) goto err;     /* the handle is not closed on error */
        if (n != 0x4000) break;
    }
    dos_close(fd);
    return MK_FP(seg, off);                               /* no size limit: reads until EOF */
err:
    fatal("%s FILE ERROR\r", name);                       /* DS:64E0 */
}

far ptr load_raw_file(const char *name)                   /* 06c9:6d18 */
{
    far ptr p = mem_reclaim_cached(name);
    if (FP_SEG(p)) return p;                              /* only DX is tested */
    u16 n = file_paras(name);
    p = mem_reserve(name, n);
    return load_file_at(name, FP_OFF(p), FP_SEG(p));
}

int write_file(const char *name, u16 off, u16 seg, u32 len, int quiet)   /* 06c9:7866 quiet=0, 06c9:7874 quiet=1 */
{
    /* quiet is stored at [bp-0Ah] BEFORE "sub sp,4": an interrupt in between can overwrite it */
    int fd;
    if (dos_creat(name, 0, &fd)) goto err;
    while (len) {
        u16 n = 0x4000;
        if (len < 0x4000) { n = (u16)len; len = 0; } else len -= 0x4000;
        if (dos_write(fd, MK_FP(seg, off), n)) goto err;  /* short writes (disk full) are not detected */
        seg += 0x400;
    }
    goto done;
err:
    if (!quiet) fatal("%s FILE ERROR\r", name);           /* DS:6808 */
done:
    dos_close(fd);                                        /* NB: also after a failed creat (stale handle) */
    return 0;
}
```

### 4.19 Unpacker

```c
far ptr unpack_file(const char *name)                     /* 06c9:6d50 */
{
    far ptr p = mem_reclaim_cached(name);
    if (FP_SEG(p)) return p;
    u16 total = unpacked_paras(name) + 1;                 /* one spare paragraph */
    far ptr blk = mem_reserve(name, total);               /* offset is always 0 */
    u16 fparas = file_paras(name);
    u8 huge *in = load_file_at(name, FP_OFF(blk), total - fparas + FP_SEG(blk));  /* file at the END of the block */
    int passes = 1;
    if (in[0] & 0x80) { passes = in[0] & 0x7F; in += 4; }   /* the outer u24 is used only for the block size */
    for (;;) {
        u8 t = in[0];                                     /* never tested for 0x80 again: no nested multi-pass */
        if ((s8)(t - 1) < 0 || (s8)(t - 1) >= 2)
            fatal("%s INVALID PACK TYPE\r", name);        /* DS:6503 */
        u32 r = (t == 1) ? rle_decode (in, blk, total)    /* jump table CS:6E2E = {06c9:6b02, 06c9:7c16} */
                         : huff_decode(in, blk, total);
        if (--passes <= 0)
            return (far ptr)r;                            /* RLE: blk.seg:0000. Huffman: its SIZE (latent bug) */
        u16 n = paras(r);                                 /* r is taken as a length: pass k<last must be Huffman */
        u16 nseg = total - n + FP_SEG(blk);
        far_move_up(FP_SEG(blk), nseg, n);
        in = MK_FP(nseg, 0);
    }
}

static u16 huff_off[16], huff_lim[16];                    /* CS:7AD6, CS:7AF6 */
static u8  huff_alpha[256];                               /* CS:7B16 */

u32 huff_decode(u8 huge *in, far ptr blk, u16 total)      /* 06c9:7c16 */
{
    u16 lo = rd16(in + 1);
    s16 hi = in[3];
    u32 result = (u32)in[3] << 16 | lo;
    u8  nb = in[4];
    int n  = nb & 0x7F;                                   /* longest code; the tables only have 16 entries */
    in += 5;
    u16 idx = 0, code = 0, lim = 0;
    for (int i = 0; i < n; i++) {
        code <<= 1;
        huff_off[i] = idx - code;                         /* 16-bit */
        u8 c = *in++;
        code += c;  idx += c;
        if (c) lim = code;
        huff_lim[i] = lim;                                /* a length with no codes keeps the previous limit */
    }
    memcpy(huff_alpha, in, idx);  in += idx;              /* idx > 256 would overwrite code */
    u8 huge *out = blk;                                   /* uses blk's offset (RLE uses 0) */
    u8 bits = 1, cur = 0, prev = 0;
    for (;;) {
        u16 v = 0; int len = 0;
        for (;;) {
            if (--bits == 0) { cur = *in++; bits = 8; }   /* in: offset wrap to 0 -> seg += 0x1000 */
            v = (u16)(v << 1) | (cur & 1);  cur >>= 1;    /* LSB first */
            if (v < huff_lim[len]) break;                 /* unsigned; no check against n or 16 */
            len++;
        }
        u8 s = huff_alpha[(u16)(v + huff_off[len])];
        if (nb & 0x80) { s += prev; prev = s; }           /* delta mode, not used by shipped files */
        *out++ = s;                                       /* out: offset wrap to 0 -> seg += 0x1000 */
        if (--lo != 0) continue;
        if (--hi >= 0) continue;                          /* signed */
        break;                                            /* size with lo==0 decodes 0x10000 extra bytes */
    }
    return result;                                        /* header value, not the measured length */
}

u32 rle_decode(u8 huge *in, far ptr blk, u16 total)       /* 06c9:6b02 */
{
    /* The u24 at in+1 is copied to locals but never used. */
    u8 hdr[16];  memcpy(hdr, in + 4, 16);                 /* u32 plen, u8 ec, 11 escape bytes */
    u32 count = rd32(hdr);
    u8  ec = hdr[4];
    u8 huge *src = in + 9 + (ec & 0x7F);
    if (ec <= 0x80) {                                     /* unsigned; ec == 0x80 still runs the pass */
        count = rle_seq_pass(src, FP_SEG(blk), count, hdr[6] /* escape #2 */, ec);
        u16 n = paras(count);
        u16 nseg = total - n + FP_SEG(blk);
        far_move_up(FP_SEG(blk), nseg, n);                /* sequence output goes to the end of the block */
        src = MK_FP(nseg, 0);
    }
    u8 tab[256] = {0};
    for (int i = 0; i < (ec & 0x7F); i++)                 /* > 11 escapes reads past hdr (stack garbage) */
        tab[hdr[5 + i]] = i + 1;                          /* a later duplicate wins */
    rle_run_pass(src, MK_FP(FP_SEG(blk), 0), count, tab);
    return (u32)FP_SEG(blk) << 16;                        /* DX:AX = blk.seg:0000 */
}

u32 rle_seq_pass(u8 huge *src, u16 oseg, u32 count, u8 seq, u8 ec)   /* 06c9:6c6e */
{
    if (ec == 1) return 0x10000 | size_hi;                /* returns stale AX/DX: DX = ec&0x7F = 1, AX = in[3] */
    u16 L = (u16)count, H = (u16)(count >> 16);
    u8 huge *out = MK_FP(oseg, 0);
    for (;;) {
        normalize(src); normalize(out);
        u8 c = *src++;
        if (c != seq) {
            *out++ = c;
            if (--L != 0) continue;
            if (H == 0) break;
            H--;  continue;                               /* L==0 then means 0x10000 (see 5.3) */
        }
        u16 body = FP_OFF(out);                           /* no normalization inside the body */
        while ((c = *src++) != seq) {
            *out++ = c;
            if (--L == 0) H--;                            /* no end test here */
        }
        u8 n = *src++;
        u16 len = FP_OFF(out) - body;
        u8 k = n - 1;
        do { memcpy(out, MK_FP(FP_SEG(out), body), len); out += len; } while (--k != 0);
                                                          /* total = n copies; n==1 -> 257, n==0 -> 256 */
        u32 c32 = ((u32)H << 16 | L) - 3;                 /* esc body esc n = body + 3 input bytes */
        H = c32 >> 16;  L = (u16)c32;
        if (c32 == 0) break;
    }
    return (u32)(FP_SEG(out) - oseg) * 16 + FP_OFF(out);
}

void rle_run_pass(u8 huge *src, u8 huge *out, u32 count, const u8 tab[256])   /* 06c9:6b97 */
{
    u16 L = (u16)count, H = (u16)(count >> 16);
    for (;;) {
        normalize(src); normalize(out);
        u8 c = *src++;
        u8 k = tab[c];
        if (k == 0) {
            *out++ = c;
            if (--L != 0) continue;
            if (H == 0) return;
            H--;  continue;
        }
        u16 n; u8 v, used;
        if      (k == 1) { n = src[0];                v = src[1]; src += 2; used = 3; }
        else if (k == 3) { n = src[0] | src[1] << 8;  v = src[2]; src += 3; used = 4; }
        else             { n = k - 1;                 v = src[0]; src += 1; used = 2; }
        memset(out, v, n);  out += n;                     /* rep stosb: n > 0x7FFF can wrap DI */
        u32 c32 = ((u32)H << 16 | L) - used;
        H = c32 >> 16;  L = (u16)c32;
        if (c32 == 0) return;                             /* exact zero only; an overshoot runs on */
    }
}
```

The RLE output length is not checked against the header. The run pass stops when it has read exactly
`count` input bytes (the u32 field, or the sequence-pass output length).

### 4.20 Resource lookup

```c
far ptr res_find(far ptr arc, char *name, int must_exist)  /* 06c9:6e59 (1), 06c9:6e4e (0) */
{
    for (int i = 0; i < 4; i++)                           /* pads the CALLER's string in place */
        if (name[i] == 0) { for (; i < 4; i++) name[i] = ' '; break; }
    u8 far *a = arc;
    s16 k = rd16(a + 4);
    u16 e = FP_OFF(arc) + 6;
    for (;;) {                                            /* dec/jge: count+1 entries, one past the name table */
        int j = 0;
        while (j < 4 && a[e + j] == (u8)name[j]) j++;     /* case-sensitive */
        if (j == 4 || (a[e + j] == 0 && name[j] == ' ')) goto found;   /* rest not compared after a NUL/space pair */
        e += 4;
        if (--k < 0) break;
    }
    if (must_exist) { fatal("locateshape - %-4.4s SHAPE OR SOUND NOT FOUND\r", name); int20h(); }
    return MK_FP(0, 0);
found:;
    u16 cnt = rd16(a + 4);
    u16 hdr = cnt * 8 + 6;                                /* 16-bit */
    u32 lin = ((u32)FP_SEG(arc) << 4) + hdr + rd32(a + e + cnt * 4);  /* FP_OFF(arc) is ignored (always 0) */
    return MK_FP((u16)(lin >> 4), (u16)(lin & 0xF));      /* normalized: offset 0..15 */
}

far ptr res_by_index(far ptr arc, u16 k)                  /* 06c9:c701 */
{
    u16 cnt = rd16(arc + 4);
    u32 off = rd32(MK_FP(FP_SEG(arc), k * 4 + cnt * 4 + 6));   /* FP_OFF(arc) not added; no range check */
    u32 lin = ((u32)FP_SEG(arc) << 4) + (u16)(cnt * 8 + 6) + off;
    return MK_FP((u16)(lin >> 4), (u16)(lin & 0xF));
}

void res_find_list(far ptr arc, char *names, far ptr *out, int must_exist)   /* 16eb:000a (1), 16eb:004c (0) */
{   for (int i = 0; *names; names += 4) out[i++] = res_find(arc, names, must_exist); }
    /* a short last name gets its terminating NUL overwritten with a space by res_find */
```

Port: compare 4-char names after normalising NUL to space, case-sensitively, without modifying the
caller's string. Keep "first match wins".

### 4.21 load_shapes

```c
far ptr load_shapes(const char *name)                     /* 1748:000e */
{
    char buf[100], ext[6];
    strcpy(buf, name);
    char *dot = buf;  while (*dot && *dot != '.') dot++;
    far ptr p;
    if (*dot == 0) {
        for (int i = 0; *g_shape_ext[i]; i++) {           /* ".PES", ".ESH" */
            strcpy(dot, g_shape_ext[i]);
            p = mem_reclaim_cached(buf);
            if (p) return p;                              /* already unflipped when first loaded */
        }
        for (int i = 0; *g_shape_ext[i]; i++) {
            strcpy(dot, g_shape_ext[i]);
            if (find_first(buf)) break;                   /* if nothing is found, buf keeps ".ESH" -> fatal later */
        }
    } else {
        p = mem_reclaim_cached(buf);
        if (p) return p;
    }
    strcpy(ext, dot);
    if (stricmp(ext, ".PES") == 0) {                      /* 13a8:2b40 is case-insensitive */
        p = unpack_file(buf);
        far ptr tmp = mem_reserve("UNFLIP", 0x1F6);       /* 8032 bytes of scratch */
        unflip_archive(p, tmp);
        mem_free(tmp);
    } else {
        p = load_raw_file(buf);                           /* .ESH: stored unpacked AND already row-major */
    }
    return p;
}

u16 shapes_paras(const char *name)                        /* 1748:016a: same search, disk only */
{   /* ... */ return stricmp(ext, ".PES") == 0 ? unpacked_paras(buf) : file_paras(buf); }
```

Callers pass lower-case base names ("testdrv2", "accolade", "gamediff", …). `songs.bin`/`voices.bin` are
loaded with `load_raw_file`. The stage road files `<SCN>n.dat` are loaded with `unpack_file` directly
(`0267:15e4`: name built with "%s%c%s", then `far_memcpy(p, DS:1E5E, 0x346A)` and `mem_release_cache`).
The unpacked stage files are only 3180–6285 bytes, so that copy reads past the end of the decoded data.

### 4.22 UNFLIP

```c
void unflip_archive(far ptr arc, far ptr scratch)         /* 06c9:c838 */
{
    s16 left = rd16(arc + 4);
    u16 k = 0;
    do {
        u8 far *r = res_by_index(arc, k);
        if ((r[15] & 0xF0) == 0) {                        /* planemap[3] high nibble must be 0 */
            u8 flags = r[14] >> 4;                        /* planemap[2] high nibble */
            if (flags) {
                u16 w = rd16(r), h = rd16(r + 2);
                u16 sz = w * h;                           /* 16-bit */
                u16 blk = 16;                             /* 16-bit offsets inside r's segment */
                for (int b = 0; b < 4; b++, blk += sz) {  /* always 4 block positions */
                    if (!((flags >> b) & 1)) continue;
                    u8 far *d = scratch;
                    for (u16 y = 0; y < h; y++)
                        for (u16 x = 0; x < w; x++)
                            *d++ = r[blk + y + x * h];    /* stored column by column */
                    memcpy(r + blk, scratch, sz);         /* now row by row */
                }
                /* the flag bits are NOT cleared */
            }
        }
        k++;
    } while (--left > 0);                                 /* count 0 still visits resource 0 */
}
```

**What this means for sprite decoding (answers the FORMATS.md open question in part):**

* `planemap[2] & 0xF0` is a **per-stored-block** flag set, not a whole-sprite flag.
  Bit `0x10` → block 0, `0x20` → block 1, `0x40` → block 2, `0x80` → block 3. Block *b* is the *b*-th
  `w×h` block after the 16-byte header (the order of the stored planes). If its bit is set, that block
  is stored column-major (`w` columns of `h` bytes), otherwise row-major.
* The loader converts the flagged blocks to row-major right after unpacking. The renderer therefore
  always sees row-major data, and the flag bits are left in the header (their meaning at draw time,
  if any, belongs to the graphics spec).
* Resources with `planemap[3] & 0xF0 != 0` are skipped. No shipped sprite has these bits set (0 of 2684
  PES sprites). `gfx_create_buffer` (06c9:b0fe) stores the plane padding (0..15) there for `WINDOW`
  buffers, so the bits probably mean "not a stored sprite".
* Only `.PES` is UNFLIPped. `.PCS` files are not processed by TD2EGA. The CGA/Tandy builds probably use
  their own extension check (not checked).
* Data check: the flags never name a block beyond the stored block count. For blocks where the
  per-block flag differs from bit 0x10, an image-smoothness test prefers the per-block reading 487:153.
  So `td2res.py plane_rows` (which applies bit 0x10 to all blocks) reads at least one block in the wrong
  order in 478 of the 2 684 PES sprites (those where a block's bit differs from bit 0x10 and w, h > 1).
  This likely explains the noisy `dash`/`carS` renders in FORMATS.md.

### 4.23 fatal

```c
void fatal(const char *fmt, ...)                          /* 16a7:0002 */
{
    gfx_shutdown();       /* 06c9:642e: text mode */
    kbd_restore();        /* 06c9:68c4: mask IRQ0/1, restore int 09h/16h from DS:62AE..62B4, clear 0040:0017 low nibble */
    timer_restore();      /* 06c9:610a */
    printf(fmt, a1, a2, a3, a4);   /* 5 stack words passed through */
    abort();              /* 13a8:29f6: "\nAbnormal program termination\n", raise(SIGABRT), _exit(3) */
}
```
Some callers have `int 20h` after the call (unreachable). Port: `SDL_ShowSimpleMessageBox` plus a log
line, then `exit(3)`.

### 4.24 Memory manager

```c
typedef struct {            /* 18 bytes */
    char name[12];          /* +00 basename, copied 12 bytes (bytes after the NUL too) */
    u16  paras;             /* +0C */
    u16  seg;               /* +0E */
    u16  flags;             /* +10: 0 = free, 2 = in use (low stack), bit0 = cached (1) */
} MemRec;                   /* DS:68E2[50]; [0] bottom sentinel (flags 2), [49] = DS:6C54 top sentinel (flags 1) */
#define FIRST g_mem_rec                                   /* DS:6C66 */
#define LAST  (g_mem_rec + 49)                            /* DS:6C6C */
MemRec *g_low;    /* DS:6C68 */      MemRec *g_cache;     /* DS:6C6A */

void mem_init(u16 top)                                    /* 06c9:6f1e (6f86: top = 0xA000) */
{
    if (g_heap_top == 0) {
        u16 base = dos_alloc(0x64);                       /* AH=48h, not checked */
        FIRST->seg = g_heap_base = base;
        u16 want = top - base;
        dos_setblock(base, &want);  dos_setblock(base, &want);   /* 2nd call with the max returned by the 1st */
        LAST->seg = g_heap_top = base + want;
    }
    g_cache = LAST;  g_low = FIRST;
    for (MemRec *r = FIRST + 1; r != LAST; r++) r->flags = 0;
}
void mem_init_reserve(u16 n) { mem_init(0xA000); LAST->seg -= n; g_heap_top -= n; }   /* 06c9:6f93 */
u16 mem_gap(void)        { return g_cache->seg - g_low->seg - g_low->paras; }        /* 06c9:6fb2 */
u16 mem_low_used(void)   { return g_low->seg + g_low->paras - FIRST->seg; }          /* 06c9:6fc4 */
u16 mem_free_total(void) { return LAST->seg - g_low->seg - g_low->paras; }           /* 06c9:6fd6 */

far ptr mem_reserve(const char *name, u16 paras)          /* 06c9:70a3 */
{
    u16 seg = g_low->seg + g_low->paras;
    MemRec *r = g_low + 1;
    if (g_cache <= r) {                                   /* record table full: drop the lowest cache record */
        if (g_cache == LAST) fatal("reservememory - OUT OF MEMORY BLOCKS LOADING %s\r", name);
        g_cache++;                                        /* its record is overwritten below */
    }
    g_low = r;
    memcpy(r->name, path_basename(name), 12);
    r->seg = seg;  r->paras = paras;  r->flags = 2;
    if ((u16)(seg + paras) > g_cache->seg)                /* evict cached blocks we now overlap */
        while ((u16)(g_low->seg + g_low->paras) > g_cache->seg) {
            if (g_cache == LAST) fatal("reservememory - OUT OF MEMORY LOADING %s\r", name);
            g_cache->flags = 0;
            g_cache++;
        }
    return MK_FP(seg, 0);
}

static int name_match(const char *key, const MemRec *r)  /* shared by 71b4 and 7273 */
{
    for (int j = 0; j < 12; j++) {
        char c = key[j];
        if (c == 0) return r->name[j] == '.' || r->name[j] == 0;   /* "FOO" matches "FOO.PES" */
        if (r->name[j] != c) return 0;                    /* case-sensitive */
    }
    return 1;
}

far ptr mem_reclaim_cached(const char *name)              /* 06c9:71b4 */
{
    const char *key = path_basename(name);
    MemRec *s = g_cache;
    do {
        if (s->flags == 0) return MK_FP(0, 0);            /* stops at the first free record */
        if (name_match(key, s)) goto found;
        s++;
    } while (s < LAST);                                   /* LAST is compared only when the cache is empty */
    return MK_FP(0, 0);
found:;
    MemRec *d = g_low + 1;
    u16 dst = g_low->seg + g_low->paras;
    g_low = d;
    u16 src = s->seg, n = s->paras;
    s->flags = 0;
    d->seg = dst;  d->paras = n;  d->flags = 2;  memcpy(d->name, s->name, 12);
    if (d == g_cache) g_cache++;
    far_copy_down(src, dst, n);
    while ((u16)(g_low->seg + g_low->paras) > g_cache->seg) {   /* no LAST check here */
        g_cache->flags = 0;
        g_cache++;
    }
    cache_compact();
    return MK_FP(d->seg, 0);
}

int mem_is_cached(const char *name)                       /* 06c9:7273: same search, no move */

void cache_compact(void)                                  /* 06c9:7147 */
{
    MemRec *s = LAST, *d = LAST;
    u16 hole = 0;
    while (s >= g_cache) {
        if (!(s->flags & 1)) { hole += s->paras; s--; continue; }   /* dropped (a 0-size record breaks this) */
        if (hole) {                                       /* move s up under the record above d */
            u16 n = s->paras, nseg = (d + 1)->seg - n;
            d->paras = n;  d->seg = nseg;  d->flags = s->flags;  s->flags = 0;
            memcpy(d->name, s->name, 12);
            far_move_up(s->seg, nseg, n);
        }
        d--;  s--;
    }
    g_cache = d + 1;
}

static MemRec *mem_find_low(u16 seg)                      /* inlined in 72c6/736b/7490/74d4/7501 */
{
    for (MemRec *r = g_low; r != FIRST; r--) if (r->seg == seg) return r;
    fatal("memory manager - BLOCK NOT FOUND at SEG= %x\r", seg);
}
static void pop_low(MemRec *r)
{   if (r == g_low) { do r--; while (r->flags == 0); g_low = r; } }

far ptr mem_release_cache_old(far ptr blk)                /* 06c9:72c6 */
{
    MemRec *r = mem_find_low(FP_SEG(blk));
    u16 nseg = 0;
    r->flags = 0;
    if (r == g_low || (u16)(g_cache->seg - g_low->seg - g_low->paras) >= r->paras) {
        MemRec *c = g_cache - 1;                          /* not checked against g_low */
        nseg = g_cache->seg - r->paras;
        g_cache = c;
        c->seg = nseg;  c->paras = r->paras;  c->flags = 1;  memcpy(c->name, r->name, 12);
        far_move_up(r->seg, nseg, r->paras);
    }
    pop_low(r);
    return MK_FP(nseg, FP_OFF(blk));                      /* 0:off if it was only freed */
}

far ptr mem_release_cache(far ptr blk)                    /* 06c9:736b */
{
    MemRec *r = mem_find_low(FP_SEG(blk));
    u16 nseg = 0;
    r->flags = 0;
    if (r == g_low || (u16)(LAST->seg - g_low->seg - g_low->paras) > r->paras) {
        u16 lowend = g_low->seg + g_low->paras;           /* g_low not popped yet */
        int moved = 0;
        MemRec *d;
        for (d = g_cache; d != LAST; d++) {               /* shift every cached block down by r->paras */
            if (lowend > (u16)(d->seg - r->paras)) continue;   /* would hit the low stack: left in place */
            MemRec *b = d - 1;
            if (b == g_low) continue;
            if (!moved) { g_cache = b; moved = 1; }
            b->flags = d->flags;  b->paras = d->paras;  b->seg = d->seg - r->paras;
            memcpy(b->name, d->name, 12);
            far_copy_down(d->seg, b->seg, d->paras);
        }
        d = LAST - 1;                                     /* new block on top of the cache */
        if (!moved) g_cache = d;
        d->paras = r->paras;  d->seg = nseg = LAST->seg - r->paras;  d->flags = 1;
        memcpy(d->name, r->name, 12);
        far_move_up(r->seg, nseg, r->paras);
    }
    pop_low(r);
    return MK_FP(nseg, FP_OFF(blk));
}
/* Records that were "left in place" can be overwritten (record and data) by the shift or by the new top
   block, while another such record stays registered over corrupted data. See 9. */

void mem_free(far ptr blk)                                /* 06c9:7490 */
{   MemRec *r = mem_find_low(FP_SEG(blk)); r->flags = 0; pop_low(r); }

u16 mem_size(far ptr blk)                                 /* 06c9:74d4 */
{   return mem_find_low(FP_SEG(blk))->paras; }

far ptr mem_slide_down(far ptr blk)                       /* 06c9:7501 */
{
    MemRec *r = mem_find_low(FP_SEG(blk)), *d = r - 1;
    if (d->flags != 0) return MK_FP(r->seg, 0);
    do d--; while (d->flags == 0);
    u16 dst = d->seg + d->paras;
    r->flags = 0;
    d++;
    if (r == g_low) g_low = d;
    d->seg = dst;  d->paras = r->paras;  d->flags = 2;  memcpy(d->name, r->name, 12);
    far_copy_down(r->seg, dst, r->paras);
    return MK_FP(dst, 0);
}

void far_copy_down(u16 src, u16 dst, u16 n)               /* 06c9:6fe8: forward, 0x1000-paragraph chunks */
{   memmove_forward(MK_FP(dst,0), MK_FP(src,0), (u32)n * 16); }
void far_move_up(u16 src, u16 dst, u16 n)                 /* 06c9:7030: from the top down, 0x1000-paragraph chunks */
{   memmove_backward(MK_FP(dst,0), MK_FP(src,0), (u32)n * 16); }

void gfx_free_buffer(Buffer far **h)                      /* 06c9:782c */
{
    Buffer far *b = *h;                                   /* word at +2 = height */
    g_rowtab_ptr -= (b->h + 13) * 2;                      /* CS:B269 (TD1: +12) */
    mem_free(*h);
}
```

Usage pattern in the game: `p = load_shapes(x); … use p …; mem_release_cache(p)` (or `…_old(p)` for
screens that are unlikely to be needed again: title, Accolade, DSI, credits). The far pointer is
invalid after the release. `gfx_create_buffer` (06c9:b0fe, graphics spec) calls
`mem_reserve("WINDOW", ((((w/8)·h + pad)·planes + 16) >> 4) + 1)` and writes a sprite-like 16-byte
header at `seg:0` (planemap low nibbles from the plane mask, `planemap[3] |= pad << 4`). The buffers
are freed with `gfx_free_buffer`, and allocation/free is LIFO in practice.

### 4.25 Text-line editor (16bb, identification level)

`edit_text_line(buf, maxlen, x, y, timeout)`: pads `buf` with spaces up to `maxlen` (NUL at `buf[maxlen]`),
draws it, and sets a blinking 1-pixel cursor (8 pixels in insert mode). If `timeout != 0` it uses
`timeout_set`/`timeout_expired`, and a timeout returns 0. Keys: Enter 0x0D, Esc 0x1B, Tab 0x09, Up 0x4800,
Down 0x5000 → return the key. Right/Left/Home/End move the cursor. Ins toggles insert. Del deletes at the
cursor. Backspace deletes before it. 0x20..0x7A are inserted or typed over (lower case is kept). The high-score
code (game_flow, `0645:0271`) calls `input_text_line`.

### 4.26 rand8

```c
u8 rand8(void)                                            /* 06c9:780e */
{
    u8 i = (u8)--g_rand_idx;                              /* DS:66E6, starts at 0 */
    u8 v = g_rand_tab[i];                                 /* DS:66E8[256], initial bytes from the EXE */
    v = (u8)(v << 1) | (v < 0x80);                        /* cmp al,80h; rcl al,1 */
    g_rand_tab[i] = v;
    return v;
}
```
**TD2 has no MSC `rand`/`srand`.** The constants 0x343FD / 0x269EC3 do not occur in the image, and no
CRT function matches. `rand8` is the only generator. The port must copy the 256-byte table (image
0x1DFD8) and keep `g_rand_idx` as u16 (only its low byte is used).

### 4.27 Timer helpers (identification; the timer spec owns the ISR)

`ticks32()` reads the ISR's 32-bit counter DS:5E8C with interrupts off. `timeout_set(t)` sets
deadline = now + t. `timeout_wait()` busy-waits until now ≥ deadline. `timeout_expired()` returns 1 once
now ≥ deadline. `delay_ticks(t)` busy-waits t ticks. `ticks32_delta()` returns now − last, then sets last = now.

### 4.28 Copy protection in 13a8 (brief, dropped by the port)

`13a8:002e` (called from main `0000:07b3` and `0432:14db/19d8/1d44`) sets INT 4 and reads floppy sectors
(CX=2707h/2708h: track 39, sectors 7/8, through a patched `int` opcode at 13a8:03d9), then compares the
data. It is self-modifying. It first writes "sabotage" values (`13a8:0163`): `06c9:424a`=0x76,
`06c9:4275`=0x76, `06c9:42ad`=0x77 (conditional-jump opcodes jbe/jbe/ja in the driving code),
`06c9:1bf7`=0xF8 (clc) and `DS:5656`=0x63. On success it writes `06c9:1bf7`=0xCB (retf) and `DS:5656`=0.
The three jump opcodes are copied from byte `13a8:03d2` (0x75 = jne in the file). The static file
already contains the sabotage values. **The simulation/scene specs must use the "pass" values**
(open question 7).

## 5. File formats

### 5.1 Sprite resources in .PES / .PCS: the plane-map bytes (Verified)

Header (FORMATS.md): `u16 w_bytes, u16 h, u16 hot_x, u16 hot_y, s16 x, s16 y, u8 pm[4]`, data at +0x10.

| bits | 16-colour (.PES, TD2EGA/TD2TDY) | 4-colour (.PCS, TD2CGA) |
|---|---|---|
| `pm[k] & 0x0F` | stored block k is written to these colour planes; the list ends at the first `pm[k]` with low nibble 0 | not used by the CGA blitter (image 0xE98E copies the 2bpp block as is); values mirror the EGA maps (`01 02 04 08` is common) |
| `pm[0] >> 4` | colour planes **cleared** over the sprite rectangle (REPLACE, AND blits) | ignored |
| `pm[1] >> 4` | colour planes **set** (REPLACE, OR) or **inverted** (XOR) | ignored |
| `pm[2] >> 4` | bit k (`0x10 << k`): stored block k is **column-major** (w columns of h bytes); converted to row-major by the loader (06c9:c838) | storage **mode** of the single block: 1 column-major; 2 column-major, each column holding its even rows (`ceil(h/2)`) then its odd rows; 3 even rows as a `w × ceil(h/2)` column-major block followed by odd rows as a `w × floor(h/2)` column-major block; ≥ 4 rejected (loader returns 1) |
| `pm[3] >> 4` | padding bytes after each block (set by `gfx_create_buffer`; 0 in all files); a sprite with a non-zero value is skipped by the fix-up | the CGA fix-up also skips it |

* Block size = `w * h + (pm[3] >> 4)`; 16-colour sprites have one block per stored plane, 4-colour
  sprites one block of 2bpp bytes (`w * 4` pixels per row).
* Statistics over the Collection (`tools/td2res.py`): in .PES every combination of block-count and
  flags occurs (e.g. `dash` `01 02 74 08` = blocks 0–2 column-major, block 3 row-major; `carS`
  `01 02 D4 08` = blocks 0, 2, 3); no flag ever points past the stored blocks. In .PCS mode 1 occurs
  1 530 times, mode 2 75 times (e.g. `ACCOLADE copy`), mode 3 32 times (e.g. `CCCFRISC SM01`).
* No shipped sprite repeats a colour bit in the stored list or both clears and sets a plane.
* `EC_4.PCS mtn2` is a plain 2bpp sprite (98×17, `01 02 04 08`) followed by 2 extra bytes.
* Examples: `07 80 00 00` → pixels 8 or 15; `87 00 00 00` → 0 or 7 (REPLACE); `f0 00 00 00` → black
  box; `0f 00 10 00` → one column-major block to all planes (masks `carM`, `gnab`).
* Rendering a sprite on its own (as `tools/td2res.py` does): start from colour 0, apply `pm[1] >> 4`
  on the bits not written by a stored block, then OR each stored block's bits into its planes.

Palette for the tools: TD2EGA uses the standard 16 colours (4.5). TD2CGA runs with 3D8h = 0Eh and
3D9h = 30h, i.e. black, light cyan, light red, white (its crash flash toggles the intensity bit).

### 5.2 How the game reads a packed file (differences from FORMATS.md in bold)

```
u8  type      1 = RLE, 2 = Huffman, 0x80|k = k passes (any other value: "INVALID PACK TYPE")
u24 size      outer header: only used to size the block (paras(size) + 1)
—— multi-pass: k inner streams follow, each starting with its own type byte and u24 ——
Huffman:  u8 n (bit 7 = delta mode), n × u8 counts, alphabet, LSB-first bitstream.
          The inner u24 is the number of symbols to decode (and the length the next pass uses).
RLE:      u32 count — number of input bytes the RLE (or sequence) pass consumes (verified: equals the
          stream length after the escape table in all 164 archives + 19 packed stage files)
          u8 ec — ec & 0x7F escapes (at most 11 handled correctly); sequence pass when ec <= 0x80
          escapes; data. The inner u24 is ignored. The output is not length-checked.
```

* A pass other than the last must be Huffman, and the last pass should be RLE (see 4.19).
* Multi-pass nesting (a `0x8x` type inside a pass) is not supported.
* Shipped files: 154 × `0x82`, 10 × `0x01` (European Challenge `.PCS`). FORMATS.md's "164 multi-pass and
  10 single-pass" should read "164 files: 154 multi-pass (0x82) and 10 single-pass (0x01)".
* Also packed (0x82): the stage road files `CCC0-6.DAT`, `EC_0-5.DAT`, `TDS20-25.DAT`. The game decodes
  them to exactly the same bytes as `td2res.unpack`. `.SGN`, `.BIN`, `.SS`, `.FNT`, `SONGS.BIN` and
  `VOICES.BIN` are raw.

### 5.3 Unpacker comparison with `tools/td2res.py`

Emulation result (`work/platform/emu_unpack.py`): **all 164 archives and all 19 packed stage files decode
to byte-identical output**. None of the edge cases below occur in the shipped data: no RLE stream ≥ 64 KB,
no Huffman size with a zero low word, no delta flag, max code length 10–14, no ec 0x01/0x80, no
sequence counts 0/1, no empty sequence bodies, no esc3 run > 0x7FFF, no pass output larger than the block,
and no output overtaking unread input.

Differences, for a port that must accept arbitrary data or for td2res documentation:

| # | Aspect | Game | td2res.py |
|---|---|---|---|
| 1 | Bit order / code construction | LSB-first, canonical, per-length limit table | same (equivalent for valid streams) |
| 2 | Huffman `n` bit 7 | **delta mode**: out = sym + previous out (mod 256) | not handled (n would be ≥ 128) |
| 3 | Invalid / too long code | never detected, reads past the tables (max 16 lengths) | raises when length > n |
| 4 | Huffman end | decodes `size` symbols. **If size & 0xFFFF == 0, decodes 0x10000 more** | `size` symbols |
| 5 | Huffman alphabet > 256 or n > 16 | overwrites code-segment data | fine |
| 6 | RLE u32 field | **the loop counter**: the run/sequence pass stops after exactly this many input bytes | skipped |
| 7 | RLE end | input-count driven. Output length is not checked, and the RLE inner u24 is ignored | output-size driven (`while len(out) < size`), then checks the size |
| 8 | Sequence pass condition | runs if `ec <= 0x80` (0x80 with 0 escapes still runs, using data[1] as the escape) | runs if `!(ec & 0x80)` |
| 9 | `ec == 1` (no 2nd escape) | sequence pass is entered and returns garbage length 0x10000+size_hi → block overrun | uses `esc[1]` → IndexError |
| 10 | Sequence repeat count n | total copies = n for n ≥ 2, **257 for n = 1, 256 for n = 0** | n (0 → body removed) |
| 11 | Sequence end marker search | streaming, no normalization inside a body | `data.index(seq, i)` over the whole rest |
| 12 | 32-bit counters | literal decrement and "count −= 2/3/4" use different borrow rules. If a literal leaves the low word at 0 with a non-zero high word, the next escape token under-counts by 0x10000 (early stop, or a runaway if the high word becomes 0) | n/a |
| 13 | Counter overshoot | only an exact 0 stops, so a token crossing the end runs on until memory ends | n/a |
| 14 | Escape table | at most 11 escapes are copied, more read stack bytes. Duplicate escapes: the later one wins | all escapes. Later one wins (same) |
| 15 | esc3 length > 0x7FFF, sequence body > ~0x7FFF | DI can wrap within the segment (corrupts output) | fine |
| 16 | Multi-pass | k passes, no nesting. Intermediate result moved to the block end. The outer u24 is not compared with the result | recursive (nesting allowed). Final length must equal the outer u24 |
| 17 | Type check | only 1 and 2 are valid inside the loop | 1, 2, or 0x80\|k anywhere |
| 18 | Return value | RLE last: pointer. **Huffman last: the size is returned as a pointer** (single type-2 file is unusable) | n/a |
| 19 | Memory | block = paras(outer size)+1. The packed file must fit (file_paras ≤ total, not checked). The Huffman output grows from the block start towards the packed data at the end | n/a |

Recommendation for the port: use td2res's algorithm (output-size driven), but take the RLE u32 as the
input length and keep the per-pass order. Asserting the game's exact-count behaviour is unnecessary for
shipped data.

### 5.4 Archive and sprite in memory

As FORMATS.md, plus:
* The block starts at offset 0. The offset table stays as u32 file offsets (no relocation).
* After loading a `.PES`, every sprite block is row-major (4.22). `planemap[2]` bits 4–7 are per-block
  "was column-major" flags. `planemap[3]` bits 4–7 are a skip flag (padding count in WINDOW buffers).
* `.ESH` = the same archive layout, stored **unpacked and already row-major** (no UNFLIP). The EGA
  build looks for it after `.PES`, but no `.ESH` files ship.

### 5.5 SONGS.BIN (618 bytes, loaded raw at seg:0000; all offsets are file offsets)

| offset | size | field |
|---|---|---|
| 0 | 4·N | song table, entry n = `u16 list_off, u16 unused`; N = first list offset / 4 = 5; entries 0 and 4 are 0 |
| list_off | 3 each | `u16 pattern_off, u8 transpose`; played in order; `pattern_off` 0 stops |
| pattern | 2 each | events `op, arg` (table below) |

| op | arg | meaning |
|---|---|---|
| 00 | n | rest, tempo·n ticks |
| 01–7F | n | note `op + transpose` (index into DS:663B), length tempo·(n & 0x7F); bit 7 of n = legato (no off part) |
| FF | – | restart the song's pattern list (all songs end with a list entry pointing to pattern 0x1D0 = `FF 00`) |
| FE | t | tempo (ticks per unit) |
| FD | v | select voice v (`VOICES + v·32`, 28 bytes) |
| FC | – | end of pattern |
| FB | – | stop song |
| 80–FA | – | stop song |

Shipped songs (1 pass; they loop):

| n | list | patterns / transpose | tempo | length | used at |
|---|---|---|---|---|---|
| 1 | 0x14 | 27 entries, transpose 5, last → FF | 7 | 6049 ticks = 60.5 s | main startup (title and menus); `0267:113d`, `0267:17f5` (back to menus) |
| 2 | 0x68 | 0x1D2, 0x1E2, 0x1F0 ×2 transpose 31, → FF | 8 | 1025 ticks = 10.25 s | `0267:0f2c`, frame 7 of the 19-frame ending animation |
| 3 | 0x77 | 0x1F6, 0x214, 0x230, 0x24C transpose 19, → FF | 6 | 865 ticks = 8.65 s | `0267:0cc0`, start of the ending sequence (`DS:9258` ≠ 0) |

Bytes 0x266–0x269 (`FC 00 FB 00`) after the last pattern are never reached. Used notes (with transpose) are 16..64, well inside the table.

### 5.6 VOICES.BIN (2 bytes: `0D 0A`)

The format is an array of 32-byte voice records, of which the player copies the first 28 bytes into DS:6609:

| off | size | field |
|---|---|---|
| 0 | u8 | shift (off part = length >> shift; 0 = legato) |
| 1 | u8 | unused |
| 2 | u16 | arp_init (first arpeggio step after this many ticks; 0 = no arpeggio) |
| 4 | u16 | arp_reload |
| 6 | u16 | arp_mask (index mask for the table) |
| 8 | u8[8] | arp_table (note offsets) |
| 16 | u16 | vib_delay (ticks before the first vibrato step) |
| 18 | u16 | vib_period (ticks between steps) |
| 20 | s8 | vib_dir (0: triangle starting upward; ≠0: initial direction, reset to 0 at the limit) |
| 21 | u8 | unused |
| 22 | u16 | vib_step (divisor units) |
| 24 | s16 | vib_min |
| 26 | s16 | vib_max |
| 28 | 4 | not copied |

The shipped file holds no voice. The loader (`06c9:5e1c`) sizes it as 1 paragraph, and `reservememory`
(`06c9:70a3`) places the next block, SONGS.BIN, directly after it. So `FD 01` (the only voice used) reads **SONGS.BIN bytes
16–43**: shift 0 (all notes legato), arp_init 0 (no arpeggio), vib_delay 0xAC, vib_period 0x5605, vib_dir 1, vib_step
0x156, vib_min 0x7805, vib_max 0x0501. Effect: after **172 ticks** of a note the divisor rises by 342 once (the pitch drops, about 3.3
semitones on song 1's final note, which is 224 ticks long; song 2's and 3's notes are shorter, so they never bend).
The EXE's default record at DS:6609 (shift 3, major-chord arpeggio table 0,4,7,12 but arp_init 0, triangle vibrato ±100
per tick) looks like the intended template. The renderer supports `--voices heap` (default, as the game plays) and `--voices exe`.

### 5.7 Divisor tables

`DS:663B` (music, 85 entries) = `DS:5F2E[0..84]` (effects, 93 entries). Entry 0 is 0. f = 1193182 / d. Note n ≈ MIDI n + 14
(n=1 D#0 19.49 Hz, n=55 A4 441.1 Hz, about +4 cents sharp). n = 82..92 are all 0x0238 (2100.7 Hz). In the effects table, slots 85..88 are
overwritten while driving.

```
 n: 00-0B  0000 ef1e e1a7 d509 c90f bdcf b321 a909 9f93 96a1 8e27 8631
 n: 0C-17  7ea9 7787 70d3 6a7e 6487 5ee3 598c 5484 4fc6 4b4d 4714 4319
 n: 18-23  3f55 3bc4 386a 353f 3244 2f71 2cc6 2a42 27e3 25a7 238a 218c
 n: 24-2F  1faa 1de2 1c35 1aa0 1922 17b9 1663 1521 13f2 12d3 11d6 10c6
 n: 30-3B  0fd5 0ef1 0e1a 0d50 0c91 0bdc 0b32 0a91 09f9 096a 08e2 0863
 n: 3C-47  07eb 0779 070d 06a8 0648 05ee 0599 0548 04fc 04b4 0471 0432
 n: 48-53  03f5 03bd 0387 0354 0324 02f7 02cc 02a4 027e 025b 0238 0238
 n: 54-5C  0238 0238 0238 0238 0238 0238 0238 0238 0238      (5F2E only from 55)
```

### 5.8 `<SCN>.FNT` — scenery vector font (Verified: code 06c9:17b4–184d, rendered all three files)

Loaded whole by `0267:15e4` (`strcpy+strcat(scenery_code, ".fnt")`, `06c9:6d18`) into DS:842E/8430
and freed at the end of the stage. Only the **segment** word is used; the data is addressed from
offset 0.

| Offset | Type | Meaning |
|---|---|---|
| 0x00 | u16[64] | glyph offset (from file start) for char `0x20 + i`; 0 = no glyph |
| … | records | glyph data: repeated `u8 x0, u8 y0, u8 x1, u8 y1` line segments |
| after last record | `FF` (`FF`) | end of glyph: the renderer tests only the **first byte** of each record for 0xFF; the files always store `FF FF` |

* Coordinates are unsigned bytes in font units, origin at the top-left of the character cell, y down.
  The shipped glyphs span 0..33 (0x21) in both axes.
* Every record is an independent line (no pen-up/pen-down state); polylines are stored as chains
  of segments.
* `CCC.FNT` and `EC_.FNT` are identical (1012 bytes): digits `0–9` and `A–Z`. `TDS2.FNT` (386 bytes)
  has only `A C D G I L N P R T U X Y` (the letters its one sign file needs). No lowercase and no
  punctuation in any file; space (index 0) is 0 = advance only.
* Index = `(u8)ch − 0x20`, computed in 16 bits and doubled without a range check: characters
  < 0x20 (other than the terminator/newline, see below) or ≥ 0x60 read outside the table.
* PNGs: `work/platform/fonts/CCC_fnt.png`, `EC__fnt.png`, `TDS2_fnt.png`; signs rendered with
  their .SGN records: `sign_<SCN><n>.png` (script `work/platform/fonts/render_fonts.py`).

### 5.9 `.SGN` record as used by the sign renderer (06c9:16a2–1853; owner: scene_render)

`<SCN><n>.SGN` = `u16` offset table (index `(sign_code − 0x1E) / 5`, sign codes ≥ 0x1E from the
road-object table), each record 0x2D words copied to DS:52E4:

| Off | DS | Field | CCC1 example |
|---|---|---|---|
| 0x00 | 52E4 | board width W0 (font units, scaled) | 384 |
| 0x02 | 52E6 | board height H0 (scaled) | 130 |
| 0x04 | 52E8 | character advance x (font units) | 43 |
| 0x06 | 52EA | line advance y (font units) | 55 |
| 0x08 | 52EC | text line colour (passed to draw_line) | 0xFFFF |
| 0x0A | 52EE | not read here | 0xFFFF |
| 0x0C | 52F0 | board colour/pattern (06c9:89a2) | 0x2222 |
| 0x0E | 52F2 | not read here | 0xAAAA |
| 0x10 | 52F4 | post colour/pattern | 0 |
| 0x12 | 52F6 | not read here | 0 |
| 0x14 | 52F8 | text origin x (font units) | 20 |
| 0x16 | 52FA | text origin y (font units) | 20 |
| 0x18 | 52FC | post height P0 (scaled) | 65 |
| 0x1A | 52FE | text, NUL-terminated, 0x0A = new line (≤ 64 bytes) | "TREES OF\nMYSTERY" |

```c
/* S(v) = scale by the object's projection factor di = objslot[0x610] (0x200 = 1:1) */
static u16 S(u16 v, u16 di) { u32 p = (u32)v * di; return (u16)(p >> 8) >> 1; }

void sign_draw(u16 di, ...) {                    /* 06c9:16e1 .. 1853 */
    u16 W = S(W0, di), H = S(H0, di), P = S(P0, di), pw = di >> 4;
    s16 side = (s16)(s8)objside[bx] * (s16)di >> 3;          /* imul low word, sar 3 */
    s16 X = (side > 0 ? right_edge[slot] : left_edge[slot]) + side - (W >> 1);
    s16 ground = ground_y[slot];
    fill(X, ground - P - H, W, H, board_col);                /* 06c9:89a2(x,y,w,h,col) */
    fill(X + W - pw, ground - P, pw, P, post_col);
    fill(X, ground - P, pw, P, post_col);
    s16 top = ground - P - H;                                /* stored in DS:52E6 */
    u16 cx = text_x0, cy = text_y0, line_x = text_x0;
    for (const u8 *p = text; ; p++) {
        u8 ch = *p;
        if (ch < 0x0A) break;                                 /* NUL (or 1..9) ends */
        if (ch == 0x0A) { cx = line_x; cy += adv_y; continue; }
        u16 g = font_w[(u16)(ch - 0x20) * 2];
        if (g) for (const u8 *r = font + g; r[0] != 0xFF; r += 4) {
            u16 x0 = S(r[0] + cx, di) + X,   y0 = S(r[1] + cy, di) + top;
            u16 x1 = S(r[2] + cx, di) + X,   y1 = S(r[3] + cy, di) + top;
            gfx_draw_line(x0, y0, x1, y1, text_col);          /* 06c9:8582 */
        }
        cx += adv_x;
    }
}
```
(The byte `+ cx` is done in 16 bits before scaling; the character position is in font units.)
The text is drawn only when `DS:940E != 0` (signs loaded) and the sign code ≥ 0x1E; codes < 0x50
with a sprite use the sprite path at 06c9:1655 instead (scene_render).

### 5.10 Key tables

#### Codes produced by the INT 9 translation (`kbd_last_key`)

Hex = ASCII byte (AH = 0); 4-digit hex = extended code (AL = 0); `0` = no key (a make code with a 0
entry **erases a pending key**). Scan codes not listed (1D Ctrl, 2A/36 Shift, 38 Alt, 3A Caps,
45/46 Num/Scroll Lock, 54–59 incl. F11/F12, and ≥ 0x5A which index entry 0) give 0 in every table.
Table priority: Alt > Ctrl > Shift (either) > Caps Lock key held > normal. Notable: the keypad always
gives navigation codes; Caps acts only while held; Tab gives 0x0F00 with Shift/Caps/Alt; Alt-F1–F10
give 0x7800–0x8100 (BIOS Alt-digit codes); Ctrl-[ = 0x1B = ESC, Ctrl-M = Enter, Ctrl-H = Backspace,
Ctrl-I = Tab; Ctrl-2 gives 0 (no key); KP `*` only in the normal table.

| sc | normal | shift | caps (held) | ctrl | alt |
|---|---|---|---|---|---|
| 01 | 1B | 1B | 1B | 1B | 1B |
| 02 | `1` | `!` | `1` | `!` | `!` |
| 03 | `2` | `@` | `2` | 0 | `@` |
| 04 | `3` | `#` | `3` | `#` | `#` |
| 05 | `4` | `$` | `4` | `$` | `$` |
| 06 | `5` | `%` | `5` | `%` | `%` |
| 07 | `6` | `^` | `6` | 1E | `^` |
| 08 | `7` | `&` | `7` | `&` | `&` |
| 09 | `8` | `*` | `8` | `*` | `*` |
| 0A | `9` | `(` | `9` | `(` | `(` |
| 0B | `0` | `)` | `0` | `)` | `)` |
| 0C | `-` | `_` | `-` | 1F | `_` |
| 0D | `=` | `+` | `=` | `+` | `+` |
| 0E | 08 | 08 | 08 | 7F | 08 |
| 0F | 09 | 0F00 | 0F00 | 09 | 0F00 |
| 10 | `q` | `Q` | `Q` | 11 | `Q` |
| 11 | `w` | `W` | `W` | 17 | `W` |
| 12 | `e` | `E` | `E` | 05 | `E` |
| 13 | `r` | `R` | `R` | 12 | `R` |
| 14 | `t` | `T` | `T` | 14 | `T` |
| 15 | `y` | `Y` | `Y` | 19 | `Y` |
| 16 | `u` | `U` | `U` | 15 | `U` |
| 17 | `i` | `I` | `I` | 09 | `I` |
| 18 | `o` | `O` | `O` | 0F | `O` |
| 19 | `p` | `P` | `P` | 10 | `P` |
| 1A | `[` | `{` | `[` | 1B | `{` |
| 1B | `]` | `}` | `]` | 1D | `}` |
| 1C | 0D | 0D | 0D | 0D | 0D |
| 1E | `a` | `A` | `A` | 01 | `A` |
| 1F | `s` | `S` | `S` | 13 | `S` |
| 20 | `d` | `D` | `D` | 04 | `D` |
| 21 | `f` | `F` | `F` | 06 | `F` |
| 22 | `g` | `G` | `G` | 07 | `G` |
| 23 | `h` | `H` | `H` | 08 | `H` |
| 24 | `j` | `J` | `J` | 0A | `J` |
| 25 | `k` | `K` | `K` | 0B | `K` |
| 26 | `l` | `L` | `L` | 0C | `L` |
| 27 | `;` | `:` | `;` | `;` | `:` |
| 28 | `'` | `"` | `'` | `,` | `"` |
| 29 | 60 (backquote) | `~` | 60 | 60 | `~` |
| 2B | 5C (backslash) | 7C (bar) | 5C | 1C | 7C |
| 2C | `z` | `Z` | `Z` | 1A | `Z` |
| 2D | `x` | `X` | `X` | 18 | `X` |
| 2E | `c` | `C` | `C` | 03 | `C` |
| 2F | `v` | `V` | `V` | 16 | `V` |
| 30 | `b` | `B` | `B` | 02 | `B` |
| 31 | `n` | `N` | `N` | 0E | `N` |
| 32 | `m` | `M` | `M` | 0D | `M` |
| 33 | `,` | `<` | `,` | `<` | `<` |
| 34 | `.` | `>` | `.` | `>` | `>` |
| 35 | `/` | `?` | `/` | `?` | `?` |
| 37 | `*` | 0 | 0 | 0 | 0 |
| 39 | 20 | 20 | 20 | 20 | 20 |
| 3B | 3B00 | 5400 | 5400 | 5E00 | 7800 |
| 3C | 3C00 | 5500 | 5500 | 5F00 | 7900 |
| 3D | 3D00 | 5600 | 5600 | 6000 | 7A00 |
| 3E | 3E00 | 5700 | 5700 | 6100 | 7B00 |
| 3F | 3F00 | 5800 | 5800 | 6200 | 7C00 |
| 40 | 4000 | 5900 | 5900 | 6300 | 7D00 |
| 41 | 4100 | 5A00 | 5A00 | 6400 | 7E00 |
| 42 | 4200 | 5B00 | 5B00 | 6500 | 7F00 |
| 43 | 4300 | 5C00 | 5C00 | 6600 | 8000 |
| 44 | 4400 | 5D00 | 5D00 | 6700 | 8100 |
| 47 | 4700 | 4700 | 4700 | 4700 | 4700 |
| 48 | 4800 | 4800 | 4800 | 4800 | 4800 |
| 49 | 4900 | 4900 | 4900 | 4900 | 4900 |
| 4A | `-` | `-` | `-` | `-` | `-` |
| 4B | 4B00 | 4B00 | 4B00 | 4B00 | 4B00 |
| 4C | 4C00 | 4C00 | 4C00 | 4C00 | 4C00 |
| 4D | 4D00 | 4D00 | 4D00 | 4D00 | 4D00 |
| 4E | `+` | `+` | `+` | `+` | `+` |
| 4F | 4F00 | 4F00 | 4F00 | 4F00 | 4F00 |
| 50 | 5000 | 5000 | 5000 | 5000 | 5000 |
| 51 | 5100 | 5100 | 5100 | 5100 | 5100 |
| 52 | 5200 | 5200 | 5200 | 5200 | 5200 |
| 53 | 5300 | 5300 | 5300 | 5300 | 5300 |

#### Hotkeys (active wherever `getkey_menu` or `getkey_drive` reads a key)

| key | code | action |
|---|---|---|
| Ctrl-J | 0x0A | joystick on + calibration screen (every time) |
| Ctrl-K | 0x0B | joystick off, "KEYBOARD ON" |
| Ctrl-P | 0x10 | pause box until a key |
| Ctrl-Q | 0x11 | toggle music, "MUSIC ON/OFF" |
| Ctrl-S | 0x13 | toggle sound, "SOUND ON/OFF" |
| Ctrl-X | 0x18 | "EXIT TO DOS (Y/N)" |

Because `kbd_dispatch` indexes with `AL & 0x7F`, no other ASCII key aliases these (the tables never
produce bytes ≥ 0x80). Plain `P` no longer pauses (TD1 did).

#### Joystick-derived codes

| input | `input_drive_bits` / `joy_read` | `getkey_menu` |
|---|---|---|
| up / down / right / left | 1 / 2 / 4 / 8 | 0x4800 / 0x5000 / 0x4D00 / 0x4B00 |
| up+right / down+right | 5 / 6 | 0x4900 / 0x5100 |
| up+left / down+left | 9 / 0x0A | 0x4700 / 0x4F00 |
| button A / B | 0x10 / 0x20 | 0x000D (either) |
| centre | 0 | 0 (and repeated codes give 0: edge-triggered) |

Direction index (`joy_dir_index`): 0 C, 1 N, 2 NE, 3 E, 4 SE, 5 S, 6 SW, 7 W, 8 NW.

#### Keys checked by game code (from the platform side; details in simulation / game_flow)

| code | where | meaning |
|---|---|---|
| AL = 0x1B | 06c9:44a6 | ESC during driving → DS:5490 = 0xFF |
| AL = `d`/`D` | 06c9:44a6 | toggle DS:2F58 |
| AL = `o`/`O` | 06c9:44a6 | toggle DS:33AF (not when DS:90A8) |
| held arrows etc., Space, Enter | 06c9:6620 | steering / pedals / fire bits |
| `Y`/`y` | 16fc:007c | quit to DOS |
| any key | 16fc:0358 | resume |
| getkey results in menus | game_flow | 0x0D, 0x1B, 0x4800/0x5000/0x4B00/0x4D00, ASCII for name entry, 0 = timeout |

## 6. Hardware / DOS dependencies and SDL3 replacements

| Original | Where | SDL3 / portable replacement |
|---|---|---|
| EGA planar memory A000h, 4 planes × 8000 bytes | all gfx | 4 `u8` plane arrays of 40×200 (plus slack, unclipped blits write one byte past a row end); present by combining the planes into a 320×200 index image through the 16-entry palette into an `SDL_Texture` (streaming XRGB8888); `SDL_SetRenderLogicalPresentation(320, 200 or 240, LETTERBOX)` |
| Sequencer 3C4h idx 2 (map mask); GC 3CEh idx 0/1 (set/reset), 3 (function 00/08/10/18h), 4 (read map), 5 (write mode 0/1/2), 8 (bit mask) | blitters, fills, text, lines, plot, dissolves, scroll, grabs | software ops on the plane arrays (REPLACE/AND/OR/XOR per plane). Emulate the EGA path only where it differs (constant-plane quirk 4.2, bit-mask leak after `gfx_draw_line`) |
| Off-screen buffers (segments from `reservememory("WINDOW")`) | `gfx_create_buffer` | same plane model, absent planes = NULL |
| INT 10h AX=000Dh / 0003h, AH=0Bh | 90e8, 642e | create / destroy the window and renderer |
| INT 10h AX=1002h | 90e8, abfa | 16-entry RGB palette (4.5); the crash flash swaps to DS:2E10 |
| BIOS 0040:0010 equipment bits | 90e8, 642e, 5f64, 5fbc | drop |
| Hercules 3B4h/3B8h/3BFh, B800h | 5f64, 5fbc | drop |
| No CRTC start address, no 3DAh wait | – | present after each copy to the screen or once per main-loop iteration (VSync) |
| INT 9 hook, port 60h, port 61h bit 7 ack, PIC 21h mask, EOI | 6860, 68c4, 6907 | `SDL_EVENT_KEY_DOWN` / `KEY_UP` → XT scan code (table below) → `kbd_make(sc)` / `kbd_break(sc)` implementing 6907 exactly (key_down[], translation, one-key buffer). Key-repeat events call `kbd_make` again (typematic make codes did the same) |
| INT 16h hook (AH 0/1/2) | 69b7, all `int 16h` | plain functions `kbd_read()` (read+clear), `kbd_peek()` |
| BIOS 0040:0017 shift bits | 68c4 | drop |
| IVT writes 0:24, 0:58 | 6860, 68c4 | drop |
| Port 201h one-shots + buttons | 6686 | `SDL_Gamepad` (or `SDL_Joystick`): left stick / D-pad → bits (x < −16384 → 8, x ≥ 16384 → 4, y < −16384 → 1, y ≥ 16384 → 2), South → 0x10, East → 0x20. `joy_enabled`/`joy_calibrated` still gate it (Ctrl-J/Ctrl-K). Faithful mode: synthesise counts (e.g. 0x50 + axis·k) and run the adaptive logic |
| Busy-wait loops on tick counters | 6a30, 6a4a, 6a6a, 7a27, 7a55, c63e, c6c5, 16fc prompts, 1769 loop | each iteration must pump SDL events, run due timer ticks and present; implement as "run the main-loop step until condition" |
| `exit(0)` after text mode | 16fc:007c | `SDL_Quit(); exit(0)` (or return to the launcher) |
| INT 10h mode 3 | 642e | destroy window |
| EGA GC/sequencer writes in text render | a54f | software planar write, as TD1 port |
| INT 8 vector swap (IVT 0:20), port 0x21 mask, port 0x20 EOI | timer ISR | none: a 99.9985 Hz tick accumulator (`SDL_GetTicksNS`) in the main loop, or in the audio callback for sample-exact music. Run the routine list per tick; `timer_paused` skips it |
| `int 8` chain to BIOS | keep DOS clock/floppy motor | drop (keep `slow_count` += 1 every 5 ticks) |
| PIT ch0 (0x40) divisor 0x2E9C / restore 0 | tick rate | constant `TICK_HZ = 1193182.0 / 11932` |
| PIT ch2 (0x43 = 0xB6, 0x42 lo/hi) + port 0x61 bits 0 (gate) and 1 (speaker data) | tone | a speaker state `{divisor, gate, data}` written by the players; an `SDL_AudioStream` (`SDL_OpenAudioDeviceStream`, S16/F32 mono 44.1/48 kHz) callback produces a square wave at 1193182/divisor when gate && data, else 0 (the real speaker sits at a DC level; output silence). Restart the phase when the gate rises. Optionally apply a new divisor at the next half-cycle (mode 3) |
| INT 16h (AH=0/1) | keys in getkey/flush | SDL key events queue |
| DOS 3Dh/42h/3Fh | loading SONGS.BIN/VOICES.BIN | `SDL_LoadFile`; reproduce voice 1 = SONGS.BIN[16..43] (or embed the 28 bytes) |
| busy-wait loops (7a27, 7a55, 6a4a, 6a6a, c63e, c6c5) | delays | loop that pumps events, presents, and advances ticks until the deadline; never spin the CPU |
| 5e1c, 5e8a, 6aa2, 7866/7874 | INT 21h 3Ch/3Dh/3Eh/3Fh/40h/42h | `SDL_IOFromFile` / `SDL_ReadIO` / `SDL_WriteIO` / `SDL_GetIOSize`. Case-insensitive file lookup (DOS names) |
| 5ef4/5f4e, 16b8, 1748 | INT 21h 1Ah/4Eh/4Fh (attr 6) | `SDL_GlobDirectory` or a directory scan, case-insensitive |
| 5d4e, 5d74 | INT 21h 19h/0Eh, INT 11h | Only for disk-swap code: drop (return 1 drive / 2 floppies if needed) |
| 5d5b | INT 21h 4301h (hidden) | Drop (Play Disk creation) |
| 5d2e | INT 1Ah 00h | `SDL_GetTicks()`-derived value (only for DISKID code) |
| 5d83/5d8d | BIOS 0040:006C | `SDL_GetTicks() * 182 / 10000` if still needed (disk code only) |
| 6f1e | INT 21h 48h/4Ah | One `malloc`, or replace the whole manager (below) |
| 16a7:0002 | text mode, IRQ mask, vectors, printf, abort | `SDL_ShowSimpleMessageBox` + `SDL_Log` + `exit(3)` |
| 68c4 (via fatal) | ports 21h, 0040:0017, INT 09h/16h vectors | Nothing (keyboard spec) |
| 75ea, 758a | ports 42h/61h | Sound spec (SDL audio stream) |
| 13a8:002e | INT 13h, INT 4, code patching | Drop, apply the "pass" state |
| huge pointers | segment arithmetic, 64 KB copies | Flat `uint8_t *` |

XT scan codes the game can see (set 1, the port must generate these):

| key | sc | key | sc | key | sc |
|---|---|---|---|---|---|
| Esc | 01 | 1…9, 0 | 02…0B | − = | 0C 0D |
| Backspace | 0E | Tab | 0F | Q W E R T Y U I O P | 10…19 |
| [ ] | 1A 1B | Enter / KP Enter | 1C | Ctrl (L/R) | 1D |
| A S D F G H J K L | 1E…26 | ; ' ` | 27 28 29 | LShift | 2A |
| \ | 2B | Z X C V B N M | 2C…32 | , . / (KP /) | 33 34 35 |
| RShift | 36 | KP * | 37 | Alt (L/R) | 38 |
| Space | 39 | Caps Lock | 3A | F1…F10 | 3B…44 |
| Num Lock / Scroll Lock | 45 46 | Home / KP7 | 47 | Up / KP8 | 48 |
| PgUp / KP9 | 49 | KP − | 4A | Left / KP4 | 4B |
| KP5 | 4C | Right / KP6 | 4D | KP + | 4E |
| End / KP1 | 4F | Down / KP2 | 50 | PgDn / KP3 | 51 |
| Ins / KP0 | 52 | Del / KP . | 53 | F11, F12 | 57 58 (translate to 0) |

Keep ticks consistent between sound and simulation. Both players and the driving tick must run in the same order within a tick
(the list order: `sfx_tick`, then `drive_tick`), so a slot divisor written by the drive tick is picked up at the next fetch.

**Memory manager in the port.** Replace it with a name-keyed cache: `load_shapes(name)` returns a decoded
(unflipped) archive `{uint8_t *data; size_t size;}`, reusing a cached copy when present.
`mem_release_cache*` marks it releasable and `mem_free` deletes it. Eviction order (LRU from the bottom
of the cache) only matters if memory is limited, so the port can simply keep everything. Pointers are
stable in the port, which is safe because the game never uses a pointer after releasing it (checked at
0267:15e4 and the title code). `WINDOW` buffers become ordinary allocations. `mem_free_total()`
(0432:04f1, Play Disk) can return a large constant.

## 7. Timing

### Timer and sound

* **Tick = 1193182 / 11932 = 99.9985 Hz** in every mode. TD1 used 11927.
* Per tick (not paused): `tick_count++`, then the routines in order.
  * menus: `music_tick` (at most one event fetch, any number of control opcodes) [+ `0143:019e` in the showroom];
  * driving: `sfx_tick`, then `06c9:403b`, which calls `06c9:412c` every tick (engine slews ±0x60 and slot updates) and runs the rest
    of the simulation every 10 ticks (DS:3368 reload 10 → 10 Hz; see simulation).
* Every 5 ticks (20.0 Hz), also while paused: `slow_count++`. The BIOS is called each time, except in driving, where it is called
  only for the first 100 periods after the install that follows the menus (`601c` keeps `chain_enable`). After `06c9:1beb`
  it is not called at all until the next `6059`.
* While paused (Ctrl-P, Ctrl-X, Ctrl-J, `5d1e`), nothing but `slow_count` advances, and the speaker is forced off every tick.
  Song and simulation state freeze. `message_box` waits with `delay_slow`, which still works while paused.
* Status messages (sound/music/keyboard toggles) block for 8 slow ticks = 40 ticks = 0.4 s. In driving, the timer
  routines keep running during that wait.
* Tick helpers use u32 counters. `deadline_*`/`delay_ticks`/`getkey_timeout` compare correctly (unsigned 32-bit,
  `jb`/`ja`/`jb`). The slow-clock helpers `c63e`, `c6b3`, `c6c5` have no `ja` after the high-word compare (`cmp dx,hi; jb; cmp ax,lo; jb`),
  so a deadline whose low word is above the current low word keeps waiting after the high word has passed. This only matters
  across a 65536-slow-tick (≈ 55 min) boundary. Port: compare as u32.
* The music tempo is in ticks, so music speed does not depend on the CPU. Songs: 60.5 s, 10.25 s, 8.65 s per loop.

### Input and prompts

* INT 9 runs asynchronously; the one-key buffer means only the **last** make code between two polls
  survives (a modifier press clears it). The port should push the key state change from each SDL
  event immediately, in event order, before running the logic step.
* Driving: `input_drive_bits` and `getkey_drive` are called from the sim step (`06c9:420a`, simulation
  spec); held-key state is sampled there.
* `tick_count` (DS:5E8C) stops while `timer_paused` is set (Ctrl-J/P/X); `slow_count` (DS:5E90) always
  runs; the message box delay (8) and the calibration exit delay (4) use `slow_count`. Rates: see the
  timer section (DS:5E98 divider).
* joy_read's timeout (4000 loop iterations) and the calibration are CPU-speed dependent; SDL_Gamepad
  removes both.
* All prompt loops are busy loops; the port must keep presenting/pumping events inside them.

### Graphics

* Nothing in the graphics layer is timed; frames are presented whenever the game copies a buffer to the screen. The dissolves are paced by their callers (game_flow).

### Resources

Nothing in this scope runs per frame, except the sound tick 75ea (sound spec) and `rand8` (called from
the simulation and scene code). `timeout_*`/`delay_ticks` busy-wait on the ISR tick counter
(DS:5E8C), and the port should replace them with `SDL_Delay` or loops that pump events.

## 8. Differences from Test Drive (1987)

### 8.1 Graphics

| Area | TD1 | TD2 |
|---|---|---|
| Descriptor | 12 words, live copy CS:5A64 + pointer CS:5A60 | 13 words (+`width_px`), live copy CS:AF3A, no pointer; screen CS:AF54; pool CS:B26B (same 2000 bytes) |
| Buffer creation | `(w_bytes, h, planes)` | `(width_px, h, planes)`, memory from `reservememory("WINDOW")` |
| Blit "own" position | `x & ~3` | `x` unmasked |
| RAM clipped OR/AND/XOR, shift 1–3 | left-clip carry `s[-1] >> n` (bug) | `s[-1] << (8-n)` (fixed) |
| EGA XOR blits | shared routines, partial edge bytes wrong | dedicated tables CS:BB38 / CS:C1A2, correct |
| EGA row advance | hard-coded 40 | descriptor stride |
| EGA constant-plane helpers | quirks | unchanged (same code) |
| `gfx_clear_clip` EGA | map mask inherited, `imul dl`, first-row-only bug | map mask 0Fh, `mul dl`, all rows |
| `gfx_fill_rect` | no size check | returns on w ≤ 0 or h ≤ 0; new clipped variant 89a2 |
| Lines | one routine, x −15.0003 skip typo, RAM colour ignored | 8582: typo fixed, pixel = colour on RAM and screen; c984: typo fixed, TD1 OR behaviour; both still leave the EGA bit mask at 0 |
| New primitives | – | `gfx_plot` ba3c, `gfx_dissolve4` 8cd8, cursor glyph c958, `gfx_set_clip_current` 5dfb, target save/restore of 26 words |
| `grab_screen` | byte coordinates | pixel x / width (`>> 3`) |
| `grab_into_sprite_raw` | – | also writes x, y into the header |
| Palette | custom DS:00CC after the identity table | standard 16-colour table DS:6848 only; crash flash swaps intensity halves |
| Sprite storage | row-major | per-block column-major flag, fixed up at load (c838) |
| Hercules | init/shutdown only | same, plus the 5E6E flag and a combined shutdown 5fbc |

Reusable as is from `../TestDrive1987/tdport/src/platform/gfx.c`: the planar Target model, the blit core
(drop the TD1 bugs), fill/clear, text, dissolve (add the 4-phase mask table), scroll, grab.

### 8.2 Input, hotkeys, text

| Area | TD1 | TD2 |
|---|---|---|
| Keyboard | BIOS INT 16h, typed keys only | own INT 9 + INT 16h: key-down table, one-key buffer, own translation tables (Caps only while held, keypad always navigation) |
| Driving input | last buffered key → direction (0x5C24) | **held** keys (6620); digit keys, `a`/`z` no longer steer |
| getkey | mode table DS:6422 (0/2/4) | function pointer DS:64DC (6a03 raw / 65c5 menu) |
| Hotkeys | hard-coded switch, Ctrl-J/K/P/Q/S, `p` pause | table-driven (DS:6048), Ctrl-J/K/P/Q/S/X; Q/S toggle music/sound with a message box; Ctrl-X exit prompt; pause shows a box |
| Pause | getkey_wait with modal flag | box drawn over the screen, keyboard only |
| joy_read | timeout 300, one enable flag | timeout 4000, enable + calibrated flags, analog scale (unused) |
| Calibration | text + grid, fire on entry cancels | same idea, full-screen save/clear, 4 text lines, grid lines 0x5A–0xD2 × 0x46–0xA0, calibration reset on entry, any key or button ends, delay_slow(4) + flush |
| Text | 0x4BD0, DS:690E block, font DS:6E2C | same code, DS:6820 block, font DS:5BC2, 0x20–0x8B, several glyphs changed |
| Centred text | x = 0xA0 − len·4 | x = target_width/2 − len·4 |
| Deadline helpers | 16-bit DS:650C/650E | 32-bit game ticks (DS:5E8C/6818) and real-time ticks (DS:5E90/68D6) |
| Scenery fonts | none | `.FNT` vector fonts for road signs |

Reusable from the TD1 port as is: `text_render` (change offsets/table), `joy_read` core, the plane
text write. New code: scan-code keyboard layer, hotkey table, prompts, FNT sign text.

### 8.3 Timer and sound

* **Effect player** (`sfx_tick`) is TD1's `snd_fetch`, with these changes:
  * It is a list routine, not inlined in the ISR.
  * Its state is split across bytes (`snd_enable` bit0 = TD1 flag bit2; `snd_busy` = one-shot active; `sfx_loop_set` = TD1 bit1). "No stream" is segment 0.
  * Opcodes 0x80–0xF4 are range-checked and act like FF.
  * Pause is handled in the ISR, which skips the whole routine and silences the speaker (TD1 did the same inside the player).
  * Sound off clears the stream and `note_left` every tick. Turning sound back on while driving restarts the engine loop
    cleanly (TD1 resumed at a stale pointer).
  * Opcode semantics, event lengths (d+1), the initial shift 3 and the loop/break bug are unchanged. Table address DS:5F2E (TD1 DS:6452). The same slots (0x55 engine, 0x56) plus the new slot 0x58 (noise).
  * The engine loop stream bytes are identical. Rpm slew is ±0x60 per tick (TD1 ±0x40). TD1's radar beep (slot 0x57) has no counterpart; TD2's one-shots are noise bursts on slot 0x58.
* **Music**: TD1 played TDSND.SND one-shot streams through the same player. TD2 has a separate pattern player with voices
  (arpeggio/vibrato) and a divisor table copy, used only in menus. SONGS.BIN has no name table (songs are numbered).
* **Timer**: TD2 has a routine list (5 entries), 32-bit tick counters (no 16-bit wrap bug), a pause flag, a 20 Hz slow counter,
  and a BIOS-chain countdown. The divisor is 0x2E9C (TD1 0x2E97). The install/restore logic is otherwise the same: EOI first, ch0 mode not
  reprogrammed, the same unhook checks.
* **Sound/music toggles** (Ctrl-S/Ctrl-Q) show a status message. They are bound through the key dispatcher, not hardcoded.
* TD1's `timer_install_div` computes the reload the same way (0x10000 / div).
* No other sound devices in any TD2 build: the only sound ports are 0x42/0x43/0x61 (EGA index). The TDY build has no `out 0xC0`
  (SN76496) either. `VOICES.BIN` is not a device file.

### 8.4 Resources, memory, CRT

| Topic | TD1 | TD2 |
|---|---|---|
| Packed files | `Pckd` container, methods 2/3/4/8 (stored, RLE90, Huffman tree, LZW) through CRT `open/read` and `malloc` | New DSI format (Huffman canonical + two-pass RLE, multi-pass) decoded **in place in the target block** with raw INT 21h. No malloc |
| Offset table | relocated into far pointers after loading | left as u32. res_find computes the pointer each time |
| Cache | 30 slots `{name[12], paras, seg}`, LIFO eviction, only low end | 50 records `{name[12], paras, seg, flags}`, low in-use stack + high LRU cache with moves and compaction |
| High end | 8 buffer slots (`buf_alloc`) | none: WINDOW buffers are ordinary low-stack blocks named "WINDOW" |
| Sprite storage | row-major | column-major blocks are converted by UNFLIP at load time |
| Extension handling | fixed names | `.PES` then `.ESH` search. `.ESH` loaded raw |
| res_find / res_find_list / draw_text_centered / draw_rect_outline / fatal | – | same logic. `res_find_opt` variant added. draw_text_centered uses a screen-width variable instead of 0xA0. fatal also restores the keyboard |
| gfx_free_buffer | `(h + 12) * 2` row words | `(h + 13) * 2` |
| rand | MSC rand/srand (bit-exact LCG) | **no MSC rand**. The DSI `rand8` table generator is the only RNG |
| CRT | MSC 4.x | MSC 5.x (1987 copyright, `_cinit` with `;C_FILE_INFO`, `_FF_MSGBANNER`, `stricmp`, `signal/raise`) |

TD1's `res.c` can be reused for the lookup semantics. Its loader and cache must be rewritten.

## 9. Open questions

### 9.1 Graphics


1. **EGA constant-plane quirk** (4.2): sprites whose pm[0]/pm[1] high nibble is non-zero, blitted
   **directly to the screen** with `x & 7 != 0`, keep their middle bytes unchanged (clear/set) or get
   wrong XOR results. scene_render/game_flow should list such screen blits (TD2 draws most frames into
   RAM buffers, where the RAM path is correct).
2. **Bit-mask leak**: after an EGA diagonal line (`gfx_draw_line` or `gfx_draw_line_or`), write-mode-0
   screen blits do nothing until `gfx_fill_rect`, `gfx_plot` or `gfx_init_ega` runs. Callers that
   draw lines on the screen: check 00c0:0004, 010c:000e (title/credits) and the scene_render callers
   (0d01, 0d13, 1ad6, 34dc, 3532, 37d0, 3cef).
3. RAM XOR blit with `vis_w == 0` draws nothing (other ops draw the spill pixels): cosmetic.
4. `gfx_set_clip` (5d9e) and `grab_into_sprite_hot/own` have no callers found (maybe dead).
5. The CGA storage mode ≥ 4 makes the CGA fix-up return 1 without processing the remaining
   resources; what its caller does with it belongs to the CGA build spec.

### 9.2 Input, hotkeys, text

1. `DS:5E98` / real-time tick rate and who installs the ISR list — timer section.
2. `06c9:89a2` colour argument for signs is a word pattern (0x2222, 0xAAAA): dither format — graphics /
   scene_render. Record fields 0x0A/0x0E/0x12 are not read by the EGA sign code (other adapters or the
   mirror view?).
3. `gfx_create_buffer` (06c9:b0fe) now takes the width in pixels (0x140) — confirm in the graphics section;
   `CS:AF52` is taken to be the target width in pixels and `CS:AF68` (screen descriptor + 0x14) the
   stride used as clip x1.
4. `getkey_drive` when `SS != DS` returns the peeked key without consuming it; this only happens if the
   driving tick interrupts code running on a foreign stack (BIOS/DOS). The port can ignore it.
5. Joystick over-counter initial value 0 (see 4.9): confirm on real hardware / DOSBox how long the
   max side takes to converge on the first calibration; the port should use SDL_Gamepad thresholds.
6. `16bb:000a` (calls c63e, c69c, 7a3b, a530) is outside this scope; probably a timed text screen
   (game_flow).
7. `06c9:75c8` / `75d9` set far pointers read by the sound driver (`06c9:7695`): named here only.

### 9.3 Timer and sound

1. **VOICES.BIN content**: is the 2-byte file what shipped in 1989, or a Collection-era placeholder? The heap-adjacency
   result (voice 1 = SONGS.BIN[16..43]) depends on `reservememory` allocating the blocks contiguously and on nothing
   being allocated between the two loads, or the blocks being moved by the compaction in `06c9:7147`. Resource spec to confirm (likely).
   Checking in DOSBox would settle it (listen for the 1.72 s bend on the last note of song 1).
2. `0143:019e` timer routine (showroom): game_flow spec.
3. Meaning of the slot-0x56 sources in `06c9:412c` (DS:3374, DS:33BC, DS:336F, DS:33B2, DS:942E & 8, DS:3346 & 4) and of the
   two noise-burst triggers `06c9:3532` / `06c9:3643` / `06c9:4a2e`: simulation spec.
4. `DS:65D0` = 0x000D and `DS:6625`/`75d9`: purpose unknown (unreferenced / write-only).
5. `06c9:5d1e` has no direct far/near callers (maybe a handler table entry); `06c9:603c`, `607a`, `798f`, `7995`, `799c`, `79bb`,
   `79c1`, `7934`, `7940`, `79d2`, `79ea`, `7a07`, `c65c`, `c6b3` have no callers found by the byte scan
   (`work/platform/snd_xref.py`).
6. `shr dx, cl` with shift ≥ 16 differs between 8086 (not masked) and 286+ (masked to 5 bits). No data uses it.

### 9.4 Resources, memory, CRT

1. `planemap[2]` bits 4–7 stay set after UNFLIP. Does the renderer test them? Also, what are the
   `planemap[0]/[1]` high-nibble bits (graphics spec)? **Answered (4.18, 5.1): no blitter tests pm[2]'s
   high nibble; pm[0] >> 4 = planes cleared, pm[1] >> 4 = planes set / inverted.**
2. `planemap[3] & 0xF0` skip: only confirmed for WINDOW buffers. Does any other code create in-memory
   "sprites" that pass through UNFLIP?
3. CGA/Tandy builds: which extension triggers UNFLIP for `.PCS`? `td2res` applies bit 0x10 to `.PCS` too.
   Check whether `.PCS` has per-block semantics (only 1 block, so bit 0x10 is enough) and whether the
   CGA loader UNFLIPs at all. **Answered (5.2): TD2CGA has its own fix-up (image 0x10DA0) that treats
   pm[2] >> 4 as a storage mode 1–3 (column-major, per-column interlaced, two column-major fields);
   `tools/td2res.py` now implements it.**
4. `0267:15e4` copies 0x346A bytes from a 3–6 KB decoded stage file. Does the simulation read past the
   real data (then the port needs the same trailing bytes = rest of the heap block/next block)?
5. `mem_release_cache` "left in place" path (4.24) can leave a registered cache record over overwritten
   data. It is harmless if the game never releases a block larger than the free gap. Not proven.
6. `cache_compact` misbehaves with 0-paragraph records (empty file loaded with `load_raw_file`). No such
   file ships.
7. Copy protection "pass" state: is byte `13a8:03d2` (0x75 in the file) changed during the check, i.e.
   what are the correct opcodes at 06c9:424a/4275/42ad? Is DS:5656=0 and 06c9:1bf7=0xCB the whole
   "pass" state? (simulation/scene owners)
8. `13a3:0006` cos: `add al,90` with an unsigned index and a signed `jle` fold only works for deg+90 ≤
   127. Callers' ranges should be checked (simulation/scene).
9. Sound entry points 7934/7940/798f/7995/799c/79bb/79c1 and 74d4/7501/6f93/6fb2/6fc4/79d2 have no direct
   callers. They may be reached through tables (keyboard option handlers 6488/64c7?).
