# scene_render — Test Drive II: The Duel, TD2EGA.EXE, code `06c9:0000`–`06c9:3fff`

Porting spec for the stage runner, per-frame scene composition, road projection (front view and
rear-view mirror), scenery sets (sky, mountains, clouds, cliffs, tunnels, road-side objects, text
signs), traffic / opponent / police drawing, cockpit, gauges, HUD and message boxes.
Conventions follow `port/RE_GUIDE.md` (`SSSS:OOOO` addresses, `DS:xxxx` globals in DGROUP 178F).

Everything below was read from the disassembly (`tools/x86dis.py work/TD2EGA_unp.exe dis …`); the
Ghidra output of `06c9:1b2c` is unusable after its jump table and most routines here are
hand-written assembly with register arguments. Confidence is **verified** unless stated.
Scratch files: `work/scene/` (`ds.py` reads DGROUP data, `fd.sh` dumps a function,
`f_0d13.txt` / `f_2958.txt` full listings of the two big drawers).

-----------------------------------------------------------------------------------------------

## 1. Overview

### 1.1 Screen layout and draw targets

| Area | Screen rows | How it is drawn |
|---|---|---|
| Roof, dashboard, instrument face, gear gate, steering wheel | whole screen, drawn once at stage start (`dash`, `roof`) | directly on screen (target = VRAM descriptor `CS:AF54`) |
| Progress line | row 0 | black line + pixels, directly on screen |
| Front view | rows 19–110 (320×92) | RAM buffer **main** (`DS:09B2` descriptor, sprite `DS:09B6`, own pos (0, 0x13)) |
| Mirror | buffer rows 8–24 at x 240–319 → screen rows 27–43 | RAM buffer **mirror** 80×17 (`DS:2A20`, sprite `DS:2A24`, own pos (0xF0, 8)), composited into **main** |
| Instrument cluster | position of `inst` | RAM buffer **inst** (`DS:2F68`), copied when dirty |
| Gear gate | position of `gbox` | RAM buffer **gbox** (`DS:2F60`), copied when dirty |

All buffers are 4-plane (16 colours, plane map `01 02 04 08`), created by `06c9:b0fe`
(`create_buffer(w_px, h, planes=0x0F)`), coordinates start at 0 in every buffer (no origin
offset). The front view is fully redrawn every frame and copied to the screen with one
unclipped replace blit of the buffer sprite at its own position (0, 19). **There is no CRTC
page flipping, no retrace wait and no dirty-rectangle logic for the road view** (same as TD1).

### 1.2 What a frame looks like (composition order, `06c9:1b2c` loop)

1. `0201` snapshot of the simulation state for the front view (+ object list).
2. `2089` snapshot for the mirror.
3. `00aa` front projection: 60 rows (`0338`), scanline spans (`05f8`), cut-line fix-ups (`0746`),
   span clamp (`088e`).
4. `00e7` front drawing into **main**: sky / mountains / clouds (`0919`), ground scanlines
   (`0b0d`), tunnel walls (`0bb8`), then all road markings and objects far→near (`0d13`);
   or the "falling off the road" scroll (`DS:33D4`).
5. `1f71` mirror projection: 25 rows behind (`21c3`, `2477`, `2542`, `088e`).
6. `1f99` mirror drawing into **mirror** (`26d8`, `284f`, `28f9`, `2958`), then copy of the
   mirror sprite into **main** at (240, 8).
7. `391f` HUD: into **main**: `mirr` AND mask (mirror frame) and the police ticket; then on
   the screen: radar detector, progress dots, distance and time digits.
8. `0094` present: copy **main** to the screen.
9. `3b95` gear gate, `3cef` instrument cluster, `3c3a` steering wheel and wheel marker (screen).
10. exit test `DS:5490` (driving result, written by the simulation).

The simulation (steering, speed, road position, traffic, opponent, police) runs in the timer
routine `06c9:403b` (simulation spec), installed by `06c9:3f40`. The render loop is free-running.

### 1.3 Call graph

```
0267:15e4 (game_flow: loads ROAD, COP, <car>DASH, <car>.BIN, <opp>ROAD, <opp>O.BIN, <scn>n.DAT,
           <scn>CAR1-3, the DAT-named scenery archive, <scn>n.SGN, <scn>.FNT)
 └─ 06c9:1b2c run_stage ─────────────────────────────────────────────────────────────────────
     ├─ 1e59 prepare_traffic_lists (DAT permille → road pointers, density thinning)
     ├─ 1c8f stage_load ─┬─ 0002 main_view_load (create main buffer, 0704 / 080e handles)
     │                   ├─ 1ee2 mirror_load (create mirror buffer, 27be / 28c8 handles)
     │                   ├─ 16eb:004c / 16eb:000a res_find_list ×6 (1db2, 20f2, 1a72, 1af2, 1b72, 1bf2, 1c72)
     │                   ├─ 37d0 cockpit_load (2fac / 3010 handles, inst & gbox buffers, draw dash+roof)
     │                   └─ 3f40 sim_stage_init (sim; installs timer routines 6269, 403b)
     ├─ 5d00 gfx_video_hook (retf unless patched)
     ├─ per life: 1e31 life_reset ─ 3ff9 sim_life_reset, 38f2 cockpit_reset
     │            5ada (sim), 7946(DS:1352) start engine sound
     ├─ loop: 0201 2089 00aa 00e7 1f71 1f99 391f 0094 3b95 3cef 3c3a   until DS:5490 != 0
     └─ result dispatch (jump table DS:2302):
          1 → 374f "Fill 'er up..."                        → exit
          2 → 3532 crash_sequence        ─┐
          3 → 3643 engine_smoke_sequence  │ then lives (DS:8424) -= 1:
          4 → 36e0 "You missed the gas station" (+8658) │   0 → game over (GOVR/govr, 3f0d), result 0
          5..8 → 371f/372b/3737/3743 damage messages    │   else 375f "Lives left" / "last life";
          9 → 3713 "Too far left to reach pump." (+8658)┘   result 4 or 9 → exit, else next life
          <0 → exit (abort)
        exit: store distances (5374/5376), time (942e), stop sound, free buffers
              (1f60, 0083, 38d4), 601c (timer), return (s8)DS:5490
```

-----------------------------------------------------------------------------------------------

## 2. Function table

### 2.1 Functions in this range

| address | proposed name | signature | purpose | confidence |
|---|---|---|---|---|
| 06c9:0002 | main_view_load | `far void(void)` | Create main buffer 320×92 (own pos 0,19); load sky/cliff/mountain/cloud handles `DS:0704` (scenery archive) and opponent road-car handles `DS:080E` (opponent archive); clear 0700, 133A, 09BC | verified |
| 06c9:0083 | main_view_free | `far void(void)` | free_buffer(DS:09B2) | verified |
| 06c9:0094 | present_main_view | `far void(void)` | select screen; copy_own(main sprite) | verified |
| 06c9:00aa | project_front | `far void(void)` | 5348=320; 0338; 05f8; 0746; clamp_spans(12CE, 92) | verified |
| 06c9:00c9 | (debug) present_and_wait | – | present, select main, wait key; unreferenced | verified |
| 06c9:00e4 | (branch trampoline) | – | `jmp 01fd`, target of short jumps in 00e7 | verified |
| 06c9:00e7 | draw_front | `far void(void)` | Select main, cache plane segments, draw sky/ground/tunnel/objects or falling scroll | verified |
| 06c9:0201 | snapshot_front | `far void(void)` | Reset per-frame front state, copy sim state, build traffic draw list | verified |
| 06c9:0338 | project_front_rows | near, no args | 60-row projection: centre, edges, y, cut lines, tunnel rows | verified |
| 06c9:05f8 | build_spans_front | near | Per-scanline edge arrays from visible rows | verified |
| 06c9:06c3 | interp_span | near, stack `(a, b, dst)`, `CX`=n, `DX`=dy, `ret 6` | Bresenham fill of n words from a toward b (self-modifying inc/dec) | verified |
| 06c9:0746 | fix_cut_lines_front | near | Clamp cliff / drop-off cut x values, tunnel defaults, tunnel edge x | verified |
| 06c9:088e | clamp_spans | near, `AX`=first scanline, `BP`=end | Clamp the 5 span arrays to [0, DS:5348] | verified |
| 06c9:08cb | clamp_edge_front | near, `AX`=x, `SI`=row·2 → `AX` | Clamp an edge against screen / cliff cut lines | verified |
| 06c9:0919 | draw_sky_front | near | Sky rectangle(s), tunnel mouth, mountains, clouds | verified |
| 06c9:0b0d | draw_ground_front | near | Scanline fill: verges, shoulders, road, ground, far band, drop-offs | verified |
| 06c9:0bb8 | draw_tunnel_walls_front | near | Horizontal lines for tunnel side walls / floor | verified |
| 06c9:0c17 | span_fill_to | near, `AX`=end x, `BX`=colour, `DI`=row ptr | Fill current scanline to end x (4 planes); may skip rest of row via `[0702]` | verified |
| 06c9:0d01 | hline | near, `DX`=x0, `AX`=x1, `DI`=y, `BX`=colour | draw_line(x0,y,x1,y,colour) if x0 < x1 | verified |
| 06c9:0d13 | draw_front_objects | near | Far→near: centre/lane marks, cliffs, cliff decorations, tunnel mouths, tunnel lights, road objects (signs, lines, finish, hazards), scenery, text signs, poles, traffic, opponent, police | verified |
| 06c9:1a37 | – | – | Not a function: bytes inside 0d13 (index artefact, "caller" 8f12 is bogus) | verified |
| 06c9:1ad6 | tunnel_rib_front | near, `SI`=row·2 | White frame (2 or 3 lines) at a tunnel row | verified |
| 06c9:1b2c | run_stage | `far int(void)` → AX = (s8)DS:5490 | Stage runner, frame loop, result dispatch | verified |
| 06c9:1c8f | stage_load | `far void(void)` | Stage variables, colours, all sprite handle tables, cockpit, sim init | verified |
| 06c9:1e31 | life_reset | `far void(void)` | 3ff9; 52CC=0xA0; 5490=0; 5FD8/5FDA/5FDC=-1; 38f2 | verified |
| 06c9:1e59 | prepare_traffic_lists | `far void(void)` | Convert DAT traffic lists to road pointers, randomly drop entries | verified |
| 06c9:1ee2 | mirror_load | `far void(void)` | Create mirror buffer 80×17 (own pos 240,8); handles 27BE (scenery) / 28C8 (opponent); 2C96=0, 2A2A=0 | verified |
| 06c9:1f60 | mirror_free | `far void(void)` | free_buffer(DS:2A20) | verified |
| 06c9:1f71 | project_mirror | `far void(void)` | 5348=80; 21c3; 2477; 2542; clamp_spans(2C2A, 17) | verified |
| 06c9:1f90 | (debug) wait_key | – | unreferenced | verified |
| 06c9:1f96 | (branch trampoline) | – | `jmp 2070` | verified |
| 06c9:1f99 | draw_mirror | `far void(void)` | Mirror version of 00e7, then composite mirror into main | verified |
| 06c9:2089 | snapshot_mirror | `far void(void)` | Mirror version of 0201 | verified |
| 06c9:21c3 | project_mirror_rows | near | 25-row projection behind the car | verified |
| 06c9:2477 | build_spans_mirror | near | Mirror version of 05f8 (same span arrays) | verified |
| 06c9:2542 | fix_cut_lines_mirror | near | Mirror version of 0746 | verified |
| 06c9:268a | clamp_edge_mirror | near | Mirror version of 08cb | verified |
| 06c9:26d8 | draw_sky_mirror | near | Mirror version of 0919 (no clouds) | verified |
| 06c9:284f | draw_ground_mirror | near | Mirror version of 0b0d | verified |
| 06c9:28f9 | draw_tunnel_walls_mirror | near | Mirror version of 0bb8 | verified |
| 06c9:2958 | draw_mirror_objects | near | Mirror version of 0d13 (differences §4.11), ends with composite | verified |
| 06c9:34dc | tunnel_rib_mirror | near | Mirror version of 1ad6 | verified |
| 06c9:3532 | crash_sequence | `far void(void)` | Crash sound, redraw, hood damage, 7 windscreen-crack steps with palette flash | verified |
| 06c9:3643 | engine_smoke_sequence | `far void(void)` | Sound, 10 smoke animation steps on screen | verified |
| 06c9:36e0 | msg_missed_gas | `far void(void)` | 3-line message, falls into 362f | verified |
| 06c9:3713 | msg_too_far_left | `far` | "Too far left to reach pump." (+DS:8658) | verified |
| 06c9:371f | msg_engine_dead | `far` | "Engine has lost all power..." (+DS:536C) | verified |
| 06c9:372b | msg_suspension_dead | `far` | "Suspension completely gone..." (+536C) | verified |
| 06c9:3737 | msg_steering_dead | `far` | "Steering completely shot..." (+536C) | verified |
| 06c9:3743 | msg_too_much_damage | `far` | "Car took too much damage..." (+536C) | verified |
| 06c9:374f | msg_fill_er_up | `far` | "Fill 'er up..." unless last stage (DS:9410) | verified |
| 06c9:375f | msg_lives_left | `far` | "Lives left: N" / "Careful, it's your last life!" | verified |
| 06c9:3788 | message_box | near | Select screen, text colours (15,0), black box 30,30 261×51, frame | verified |
| 06c9:362f | message_wait (tail) | – | delay 30 ticks; 3f0d | verified |
| 06c9:37d0 | cockpit_load | `far void(void)` | Dash handles, digit handles, inst/gbox buffers, draw dash+roof, progress line | verified |
| 06c9:38d4 | cockpit_free | `far void(void)` | free gbox and inst buffers | verified |
| 06c9:38f2 | cockpit_reset | `far void(void)` | Per-life cockpit state, knob position from car BIN | verified |
| 06c9:391f | draw_hud | `far void(void)` | Mirror mask + ticket into main; radar, progress dots, distance/time on screen | verified |
| 06c9:3a5f | draw_radar_detector | near | `rad0`/`rad1-5` when DS:3346 bit 2, else `radb` | verified |
| 06c9:3a91 | draw_progress_dots | near | 3 dots on screen row 0 (player, opponent, police) | verified |
| 06c9:3ab8 | progress_dot | near, `SI`=road ptr, `BX`=slot·2, `DX`=colour | Move one dot | verified |
| 06c9:3af9 | draw_ticket | near | Ticket sprite + 3-digit amount when police state 4–6 | verified |
| 06c9:3b95 | draw_gear_gate | `far void(void)` | Gear gate open/close and knob (TD1 0x351A) | verified |
| 06c9:3c3a | draw_steering | `far void(void)` | Wheel pose XOR toggles, wheel marker with save-under | verified |
| 06c9:3cef | draw_instruments | `far void(void)` | Cluster: needles, bars or digits per car BIN flags | verified |
| 06c9:3ea4 | draw_number3 | near, `AX`=value, `SI`=slot·2 | Up to 3 digits (leading zeros suppressed, slots still consumed) | verified |
| 06c9:3ed7 | draw_inst_digit | near, `AL`=digit, `SI` | OR `dgt` at (car[0x165+SI], car[0x163]), SI+=2 | verified |
| 06c9:3efc | select_main_view | `far void(void)` | select_target(DS:09B2) | verified |
| 06c9:3f0d | wait_after_message | `far void(void)` | Drain keys, delay 40, then (not demo) flush and wait ≤1800 ticks or key | verified |
| 06c9:3f40 | sim_stage_init | `far void(void)` | Simulation spec: resets, road checksum (DS:33BD), fixes DS:3811, timer 601c, adds timer routines 6269 and 403b | verified (see simulation) |
| 06c9:3ff9 | sim_life_reset | `far void(void)` | Simulation spec: zeroes sim state, 33CA=250, 5490=0, calls 5427 | verified (see simulation) |

### 2.2 Library / other-subsystem functions called (TD2 addresses)

TD2's blitter family differs from TD1: every entry sets `[bp-40h]` RAM table, `[bp-4Ah]` EGA table,
`[bp-42h]` GC function and `[bp-41h]` flags, then jumps to a mode entry. Body `06c9:9205` is
**clipped** (tests the clip rectangle CS:AF46..AF4C), body `06c9:9CDF` is **unclipped**.
Position modes as in TD1: *hot* = x−hot_x, y−hot_y; *raw* = x, y; *own* = header x, y.

| addr | name used here | args | notes |
|---|---|---|---|
| 06c9:5c98 | select_screen | – | select_target(CS:AF54) |
| 06c9:5ca6 | create_buffer_like | `(far sprite)` → DX:AX desc, CX:BX sprite | buffer w·8 × h, 4 planes, copies sprite x,y |
| 06c9:5d00 | gfx_video_hook | – | patchable hook, `retf` by default (platform) |
| 06c9:601c | timer_install_drive | – | PIT divisor 0x2E9C (99.9985 Hz), see platform |
| 06c9:614c | timer_add_routine | `(far fn)` | 5-slot list DS:5F12; platform |
| 06c9:69fe | poll_key | → AX | via `[DS:64DC]` |
| 06c9:6a3b | flush_keys | – | INT 16h |
| 06c9:6a6a | wait_ticks_or_key | `(u32 n)` | |
| 06c9:780e | rand8 | → AL | |
| 06c9:782c | free_buffer | `(far desc)` | |
| 06c9:7946 | sound_start_loop | `(far data)` | engine sound (DS:1352) |
| 06c9:7971 | sound_stop | – | |
| 06c9:7977 | sound_play | `(far data)` | crash sound DS:549F |
| 06c9:79c8 | get_ticks | → DX:AX | DS:5E8C |
| 06c9:7a10 / 7a27 / 7a55 | set_deadline(n) / wait_deadline() / delay(n) | u32 ticks | |
| 06c9:7a82 | set_text_colours | `(fg, bg)` | |
| 06c9:7d5e | select_target | `(off, seg)` | copies 13 words to CS:AF3A; seg is **CS** for created buffers |
| 06c9:7d7c / 7dbc | and_clip_hot / and_clip_own | | |
| 06c9:808a / 80ca | and_hot / and_own | | unclipped |
| 06c9:843e | fill_clip | `(colour)` | fills current clip rect |
| 06c9:8582 | draw_line | `(x0,y0,x1,y1,colour)` | colour 0xFFFF = 15 |
| 06c9:89a2 | fill_rect_clip | `(x,y,w,h,colour)` | clips to target clip, falls into 8a0c; only the low nibble of colour is used (EGA) |
| 06c9:8a0c | fill_rect | `(x,y,w,h,colour)` | unclipped |
| 06c9:916c / 91a4 | copy_clip_hot / copy_clip_raw | | |
| 06c9:9c90 / 9cc2 | copy_raw / copy_own | | unclipped |
| 06c9:a6d8 / a6f8 / a718 | or_clip_hot / or_clip_raw / or_clip_own | | |
| 06c9:a9d2 / a9f2 / aa12 | or_hot / or_raw / or_own | | unclipped |
| 06c9:abfa | set_palette | `(ds_off)` | INT 10h AX=1002h |
| 06c9:ac40 | grab_into_sprite_raw | `(far sprite, x, y)` | also writes x,y into the header |
| 06c9:b0fe | create_buffer | `(w_px, h, plane_mask)` → DX:AX desc | descriptor in CS pool: +0 sprite off, +2..+8 plane segs, +0A row table, +0C..+12 clip x0,x1 (bytes), y0,y1, +14 stride |
| 06c9:ba3c | plot | `(x, y, colour)` | |
| 06c9:bac8 | xor_clip_hot | | |
| 06c9:c152 / c172 | xor_raw / xor_own | | unclipped |
| 13a3:0038 | tan256 | `AL`=signed degrees → AX | `DS:5560[|a|]`, negated for a<0 (§4.0) |
| 13a8:2a3c | sprintf | | CRT |
| 16ab:000c | print_centered | `(str, y)` | |
| 16af:0006 | draw_frame | `(x0,y0,x1,y1,colour)` | |
| 16eb:000a / 004c | res_find_list / res_find_list_opt | `(far archive, names, table)` | 4-char names; `_opt` stores 0 for missing resources (6e4e), the other aborts (6e59 `locateshape`) |
| 06c9:3f40, 3ff9, 5427, 5ada, 403b, 6269 | simulation | | see simulation spec |
| 13a8:0189 | (copy protection, CRT seg) | | writes `retf` (CB) at 06c9:1BF7; the unpatched byte is `clc` followed by code that overwrites the INT 21h vector — see §5 |

-----------------------------------------------------------------------------------------------

## 3. Globals

Types: `u8 s8 u16 s16`; "far" = offset word then segment word. `[i]` arrays are word arrays
indexed by row `i` (address `base + 2i`), "bytes" arrays store a byte at `base + 2i`.

### 3.1 Inputs from other subsystems (read here)

| DS | name | type | meaning | written by | read by |
|---|---|---|---|---|---|
| 346A | dat_image | 0x1E5E bytes | `<scn>n.DAT` unpacked here (§5.1) | game_flow 0267:15e4 | everywhere |
| 347E | dat_records | 128×4 | road records {r0 flags, r1 curve s8, r2 pitch s8, r3 object} | DAT | 0338, 21c3 |
| 368A | dat_scenery_type | s8×128 | scenery type per unit phase (−1 none) | DAT | 0d13, 2958 |
| 370A | dat_scenery_offset | s8×128 | lateral offset (×W/8) | DAT | 0d13, 2958 |
| 378C..379C | dat_colours | u16 | copied to 534A..5352 | DAT | 1c8f |
| 37A6 | dat_band_table | 8-byte entries {start, end, v0, v1}, 0-terminated | far-right ground band width (§4.2) | DAT | 0338, 21c3 |
| 37F6 | dat_wide_left | u8 | lane widening also moves the left edge; draw left lane line | DAT | 0338, 21c3, 0d13, 2958 |
| 37F7 | dat_tunnel_style | u8 | ≠0: "open" tunnel style (grey sides, no sky/cliff cut logic) | DAT | many |
| 37F8 | dat_no_mountains | u8 | ≠0: no mountains/clouds | DAT | 0919, 26d8 |
| 380D | dat_road_units | u16 | road length (units), wrap for distances | DAT | 0201, 2089, 1e59, 1c8f |
| 380F | dat_stage_length | u16 | stage distance (→ 5342, progress line) | DAT | 1c8f, 37d0, 1b2c |
| 3811 | dat_ptr_fix | u16 | += 0x3B33 at init (sim) | DAT | sim |
| 3813 / 39A3 | traffic_list_l / _r | 50×8 bytes | {u8 type, u8 ?, u16 pos_hi, u16 pos_lo, s16 lateral} after 1e59 | 1e59 | 0201, 2089, sim |
| 3B51 | road_bytes | u8… | road stream (bit 7 = wide road, low 7 = record) | DAT | 0338, 21c3 |
| 23A6 | car_bin | 0x34F | `<car>.BIN` (§5.4) | game_flow | 3cef, 3c3a, 391f, 38f2 |
| 52C8 / 52CA | player_pos_lo / _hi | u16 | 32-bit road position, hi = pointer into DS road bytes | 1c8f, sim | 0201, 2089, 3a91, 1b2c |
| 52CC | player_lateral | s16 | init 0xA0 per life | 1e31, sim | 0201 (neg), 2089 (−x/2) |
| 52CF | speed_mph | u8 (hi byte of 52CE) | shown speed | sim | 3cef |
| 52D0 / 52D2 / 52D4 | opp_pos_lo / _hi / opp_lateral | | opponent; 52D2 = 0 when no opponent | 1c8f, sim | 0201, 2089, 3a91 |
| 52D8 / 52DA / 52DC | cop_pos_lo / _hi / cop_lateral | | police | sim | same |
| 332C | rpm | u16 | engine rpm | sim | 3cef |
| 3346 | radar_flags | u16 | bit 2 radar lit; bits 2–3 parked-cop frame | sim | 3a5f, 0d13, 2958 |
| 3348 | radar_level | u16 | 0..5 → rad0, rad5..rad1 | sim | 3a5f |
| 3355 | ticket_amount | u8 | 3-digit number on ticket | sim | 3af9 |
| 3372 / 3373 / 3375 | opp_brake / cop_brake / opp_alt_set | u8 | sprite variants | sim | 0201, 2089 |
| 3379 | opponent_enabled | u8 | = DS:843E | 3f40 | 0d13, 2958 |
| 33B7 / 33B8 | cop_state / cop_active | u8 | 4–6 ticket shown, ≥7 parked cop drawn | sim | 0201, 2089, 3af9 |
| 33CE / 33D4 | fall_scroll / fall_mode | u16 / u8 | off-road fall animation (1 left, 2 right, 4 water) | sim | 00e7, 1f99 |
| 533E | unit_counter | u16 | +1 per road unit (dash / pole phase) | sim | 0201, 2089 |
| 5342 | distance_left | s16 | init stage length | 1c8f, sim | 391f |
| 5344 / 5346 | mountain_scroll / cloud_scroll | u16 | horizontal scroll accumulators | sim, 1c8f/3f40 | 0919, 26d8 |
| 5490 | drive_result | s8 | 0 driving; 1..9 see §4.14; <0 abort | sim | 1b2c |
| 5491 | start_flags | u8 | r0 state at the car (inside tunnel = bit 7…) | 1c8f (0), sim | 0201, 2089, 0d13, 2958 |
| 2F46 / 2F48 | steer / heading | s16 | wheel angle; car heading vs road (deg·256) | sim | 3c3a / 0201, 2089, 0919, 26d8 |
| 2F4C / 2F4E | knob_x / knob_y | s16 | gear knob position in gbox buffer | 38f2, sim | 3b95 |
| 2F58 | gate_visible | u8 | 1 = gear gate shown | sim (input) | 3b95 |
| 2F59 | gate_close_delay | u8 | frames (init 10) | 38f2, 3b95 | 3b95 |
| 2F5A / 2F5B / 2F5C | redraw_gate / redraw_inst / redraw_hud | u8 | dirty flags | 38f2, sim | 3b95 / 3cef / 391f |
| 942E | time_seconds | u16 | elapsed time (mm = /60) | sim, 1b2c | 391f, 0d13, 2958 (bit 0 = light bar blink) |
| 8424 | lives | u16 | | game_flow, 1b2c | 1b2c, 375f |
| 8A9A | demo_mode | u16 | | game_flow | 3f0d |
| 843E | opponent_selected | u16/u8 | | game_flow | 1c8f, 3f40 |
| 9410 | last_stage | u16 | 1 on the scenery's last stage | game_flow | 374f, 0d13, 2958 |
| 920C | traffic_setting | u8 | density (1A70 = −value) | game_flow | 1e59 |
| 02E4 | difficulty | u16 | index into sim tables 2316..238E | game_flow | 1c8f |
| 8A76/8A7C/8A84/8A8E/8A92/8A96 | archives CAR1, CAR2, CAR3, ROAD, DASH, COP | far | | game_flow | 1c8f, 37d0 |
| 9228 / 9260 | archive opponent ROAD / scenery (name from DAT+0) | far | 0 when absent | game_flow | 0002, 1ee2, 1c8f |
| 940E | sgn_segment | u16 | `<scn>n.SGN` loaded at seg:0 (0 if none) | game_flow | 0d13, 2958 |
| 8430 | fnt_segment | u16 | `<scn>.FNT` | game_flow | 0d13 |
| 09B0 / 2A1E | start_height_front / _mirror | s16 | static 80 / 80 (never written) | – | 0201 / 2089 |

### 3.2 Front-view state (owned here)

| DS | name | type | meaning |
|---|---|---|---|
| 0700 | wide_toggle_ptr | u16 | road address where bit 7 of the road byte last changed (front walk) |
| 0702 | row_skip_target | u16 | 0x0B7B (front) / 0x28BD (mirror): where 0c17 jumps when a scanline is full |
| 073C | draw_list | 8-byte entries {dist·2, type, lateral, –} | traffic within 60 units ahead |
| 0804 | draw_list_len | u16 | bytes |
| 0806 / 0808 | opp_row2 / opp_lat | u16 / s16 | opponent distance·2 and lateral |
| 080A / 080C | cop_row2 / cop_lat | | police |
| 09AC / 09AD / 09AE | r_opp_brake / r_cop_brake / r_opp_alt | u8 | snapshots |
| 09B2 / 09B6 / 09BA | main_desc / main_sprite / main_rowtab | far / far / u16 (CS) | |
| 09BE / 09C0 | span_bit / span_x | u16 | 0c17 cursor |
| 09C4 / 0A7C / 0B34 / 0BEC / 0CA4 / 0D5C | span_ol / span_l / span_r / span_or / span_band / span_flags | s16 ×92 | per scanline (shared with the mirror) |
| 0E14 / 0E8C / 0F04 / 0F7C / 0FF4 | row_ol / row_l / row_cx / row_r / row_or | s16 ×60 | per row |
| 106C | row_sy | s16 ×60 | screen y |
| 10E4 | row_clip | s16 ×60 | min(sy) of rows 0..i (clip bottom for objects of row i); [0] forced to 92 |
| 115C | row_flags | bytes | bit0 = wide road, other bits = r0; odd byte (115D+2i) = r3 object |
| 11D4 | row_state | bytes | r0 XOR state after row i |
| 124C | row_band | s16 ×60 | right band boundary x (default 0xA00) |
| 12C4 / 12C6 / 12C8 | lat_acc / height_acc / heading_acc | s16 | integrators |
| 12CA / 12CC | walk_ptr / walk_sub | u16 | |
| 12CE | top_sy | s16 | min sy (init 92) |
| 12D0 / 12D2 / 12D4 / 12D6 / 12D8 | right_cut_x / left_sky_x / tunnel_in_sy / tunnel_in_r / tunnel_out_l | s16 | see §4.2 (12D0, 12D2 init 320; 12D4 init 92) |
| 1304 | tmp | u16 | |
| 1306 | unit_phase | u16 | = 533E |
| 1308 | pitch_acc | s16 | |
| 130A / 130C | left_cut_x / right_sky_x | s16 | init 0 |
| 130E / 1310 / 1312 / 1314 / 1316 | left_cut_row / right_cut_row / left_sky_row / right_sky_row / top_row | u16 (row·2) | |
| 1318 / 131A | tunnel_in_row / tunnel_out_row | u16 | |
| 131C / 131E / 1320 / 1322 / 1324 | tunnel_out_sy / tunnel_in_top / tunnel_out_top / tunnel_ceiling / tunnel_ceiling_row | s16 | |
| 1326 / 1328 | tunnel_in_l / tunnel_out_r | s16 | clamped edges |
| 132A / 132C | left_sky_sy2 / right_sky_sy2 | u16 | sy·2 of the drop-off rows |
| 132E / 1330 / 1332 | obj_size / scale4 / scale5 | u16 | per row: min(W>>3,31); ((s>>1)&0xFC); (min(s,16)&0xFC) |
| 1336 / 1338 | rec_w0 / rec_w1 | u16 | current record (r0|r1<<8, r2|r3<<8) |
| 133A | prev_road_byte | u8 | |
| 133B / 133C | r0_state / r0_any | u8 | XOR / OR of r0 over the rows (init DS:5491) |
| 133D | dash_phase | u8 | per-row unit counter |
| 133E / 133F | left_cut_state / right_cut_state | u8 | r0_state at the cut row |
| 1340 / 1341 | r_cop_active / r_cop_state | u8 | |
| 5348 | view_width | u16 | 320 front / 80 mirror |
| 5420..5426 | plane_seg[4] | u16 | cached plane segments of the current buffer |
| 534A / 534C / 534E / 5350 / 5352 | col_left / col_right / col_shoulder / col_sky / col_far | u16 | from DAT |
| 52E0..533D | sign_work | 45 words | copy of the current SGN entry (§4.10) |

### 3.3 Mirror state

Scalars are the front ones + **0x195C** (12C4→2C20 … 1341→2C9D; also 1326→2C82, 1328→2C84,
132A→2C86, 132C→2C88, 132E→2C8A, 1330→2C8C, 1332→2C8E, 133D→2C99). Per-row arrays (25 rows):
row_ol 2A2C, row_l 2A5E, row_cx 2A90, row_r 2AC2, row_or 2AF4, row_sy 2B26, row_clip 2B58,
row_flags 2B8A, row_state 2BBC, row_band 2BEE. Span arrays are shared with the front view.
Draw list 27F6 (len 28BE), opponent 28C0/28C2, police 28C4/28C6, `2A1C` opp_alt, buffer
`2A20` desc / `2A24` sprite / `2A28` rowtab, `2C96` prev road byte, `2C62` = 533E−1.

### 3.4 Cockpit / HUD state

| DS | name | meaning |
|---|---|---|
| 2F46..2F4E | see §3.1 | |
| 2F50 / 2F52 / 2F54 | dot_x[3] | last progress dot x (init −1) |
| 2F56, 2F57 | – | per-life zero / one (unused here) |
| 2F5E | wheel_pose | 0 right, 2 centre, 4 left (init 2) |
| 2F60 / 2F64 | gbox_desc / gbox_sprite | far |
| 2F68 / 2F6C | inst_desc / inst_sprite | far |
| 2F70 / 2F72, 2F74 / 2F76 | gbox x,y / inst x,y | (stored, unused) |
| 2F78 / 2F7A | marker_save_x / _y | |
| 2F7C | marker_save_sprite | static header 2 bytes × 4 rows, 4 planes |
| 30E2 | gate_prev | |
| 30E3 | marker_saved | (holds the marker y byte, ≠0 = saved) |

### 3.5 Sprite handle tables (4-byte far pointers)

| table | archive | names (index: name) |
|---|---|---|
| 0704 (14, opt) | scenery | 0 rcfA 1 rcfa 2 rcfB 3 rcfb 4 lcfA 5 lcfa 6 lcfB 7 lcfb 8 mtn0 9 mtn1 10 mtn2 11 clo1 12 clo2 13 clo3 |
| 080E (40, opt) | opponent `<opp>ROAD` | 0–7 rcr0–7, 8–15 rc0M–rc7M, 16–23 rac0–7, 24–31 ra0M–ra7M, 32–39 brk0–7 |
| 1A72 / 1AF2 / 1B72 / 1BF2 (32 each) | CAR1 / CAR2 / CAR3 / **COP** | 0–7 fc0M–fc7M, 8–15 fcr0–7, 16–23 rc0M–7M, 24–31 rcr0–7 |
| 1C72 (80) | COP | 0–7 CLR0–7, 8–15 brk0–7, 16–47 CP0a CP0b CP0a CP0b, CP1c CP1a CP1b CP1d … CP7d, 48–79 same lower case `cp…` |
| 1DB2 (208, opt) | scenery | 0–79 sm0x sm1x md0x md1x lg0x lg1x hg0x…hg9x (16 types × 5 sizes), 80–159 same upper case, 160–171 rcka-d wed0-3 linA-D, 172–183 RCKA-D WED0-3 LINA-D, 184–195 rcka-d wedA-D lin1-4, 196–207 RCKA-D WEDA-D LIN1-4 |
| 20F2 (132) | ROAD | 0–3 pal0-3, 4–7 pol0-3, 8–43 sign masks (9 types × 4 sizes, `sa30 …`), 44–79 sign images (`sp30 …`), 80–83 pst0-3, 84–87 rcka-d, 88–91 oil0-3, 92–95 gra0-3, 96–99 pot0-3, 100 govr, 101 GOVR, 102–111 dgt0-9, 112–116 GST0-4, 117–121 gst0-4, 122–124 SMK0-2, 125–130 smk0-5, 131 tick |
| 27BE (11, opt) | scenery | rcfC rcfc rcfD rcfd lcfC lcfc lcfD lcfd rmt0 rmt1 rmt2 |
| 28C8 (32) | opponent | 0–7 fcr0 fcr1 fcr2 fcr3 fcr3×4, 8–15 fc0M..fc3M fc3M×4, 16–23 fac0..3 fac3×4, 24–31 fa0M..3M ×4 |
| 2FAC (25, opt) | `<car>DASH` | dash, dot, dota, gbo0, gbox, gnob, gnab, inl1, inl2, inl3, inst, mirr, time, rad0, rad5, rad4, rad3, rad2, rad1, radb, roof, whl1, whl3, hdcr, hdcM |
| 3010 (12, opt) | `<car>DASH` (only when car[0x14D] ≠ 1) | dgt0–dgt9, spdo, tach |

Full name tables: strings at DS:08B2, 08EB, 135C, 13DD, 171E, 192F, 296C, 2999, 304C, 30B1.

-----------------------------------------------------------------------------------------------

## 4. Pseudocode

Conventions: 16-bit wrapping arithmetic; `sar` arithmetic shift; `(s8)` sign-extends a byte.
`mulhi(a, s)` = signed high word: `a >= 0 ? ((u32)a*s)>>16 : -(((u32)(-a)*s)>>16)`.
`mid16(p)` = `(u16)((u32)p >> 8)` (the `mov al,ah; mov ah,dl` idiom on a DX:AX product).
Fill calls are `fill(x, y, w, h, colour)` = `06c9:89a2`. Blits are written
`and_ch(h, x, y)` (clipped hotspot AND) etc.; `T[k]` = handle k of table T (§3.5).
Row index `i` = SI/2.

### 4.0 Tables (DGROUP, static)

| DS | name | formula / content |
|---|---|---|
| 0520 | xs_front[60] | `195256/(i+4)` (0xBEAE, 0x988B, …, 0x0C1B) |
| 0598 | ys_front[60] | `140672/(i+4)` (0x8960 … 0x08B9) |
| 0610 | w_front[60] | `1200/(i+4)` (300, 240, 200, 171, …, 19) |
| 0688 | carscale_front[60] | 7,7,6,6,5,5,5,4,4,4,4, 3×8, 2×16, 1×21, 0×4 |
| 26F6 | xs_mirror[25] | `106416/(i+6)` (0x4548 … 0x0DDB) |
| 2728 | ys_mirror[25] | `57324/(i+6)` (0x2552 … 0x0777) |
| 275A | w_mirror[25] | `360/(i+6)` (60, 51, 45, …, 12) |
| 278C | carscale_mirror[25] | 3,3, 2×6, 1×8, 0×9 |
| 5560 | tan256[128] | `round(tan(k°)·256)` for k 0..89, [90] = 32767, then **other data** for k 91..127 (reachable when the pitch accumulator exceeds ±90°: copy 128 words from the EXE) |
| 5428/5438/5448/5458 | colour_plane0..3[16] | byte 0xFF if bit k of the colour index is set |
| 5468 | mask_from_bit[8] | 0xFF >> k |
| 5488 | pixel_mask[8] | 0x80 >> k |
| 098C | cliff_deco_pattern[16] | u16 `type + (count << 8)`: 0000 0403 0102 0001 0A03 0000 0103 0302 0F03 0001 0000 0603 0702 0001 0902 0203 |
| 12DA / 2C36 | object jump tables | object 1–9 signs, 10 & 12 cross line, 11 stage end, 13–20 hazards |
| 5378 | finish_letters | 20 segments {x0,y0,x1,y1} spelling FINISH, −1 terminated (§4.9) |
| 2E08 / 2E10 | palettes | normal `00..07 10..17 00`, flashed `10..17 00..07 00` |
| 2C9E / 2E22 | crack line sets | 7 pointers / 7 counts (11,12,11,15,14,11,13); each line = 2 words {x/2, y}, §4.13 |
| 2302 | result jump table | §1.3 |

### 4.1 Stage runner (06c9:1b2c)

```c
int run_stage(void) {
    prepare_traffic_lists();          // 1e59
    stage_load();                     // 1c8f
    gfx_video_hook();                      // 5d00
new_life:
    life_reset();                     // 1e31
    sim_5ada();
    sound_start_loop(DS:1352);
    do {
        snapshot_front(); snapshot_mirror();
        project_front(); draw_front();
        project_mirror(); draw_mirror();
        draw_hud(); present_main_view();
        draw_gear_gate(); draw_instruments(); draw_steering();
    } while (drive_result == 0);
    b_336B = 0;
    if (drive_result > 0) {
        sound_stop();
        switch (drive_result) {           // table DS:2302
        case 1: msg_fill_er_up(); goto finish;
        case 2: crash_sequence(); break;
        case 3: engine_smoke_sequence(); break;
        case 4: w_8658++; msg_missed_gas(); break;
        case 5: msg_engine_dead(); break;   case 6: msg_suspension_dead(); break;
        case 7: msg_steering_dead(); break; case 8: msg_too_much_damage(); break;
        case 9: msg_too_far_left(); break;
        }
        if (--lives == 0) {
            select_screen();
            and_own(ROAD[101] /*GOVR*/); or_own(ROAD[100] /*govr*/);
            wait_after_message();
            drive_result = 0;
            goto finish;
        }
        msg_lives_left();
        if (drive_result == 4 || drive_result == 9) goto finish;
        goto new_life;
    }
finish:
    u16 lim = dat_stage_length - 11;
    w_5374 = min_u(player_pos_hi - 0x3B51, lim);   // unsigned compare
    w_5376 = min_u(opp_pos_hi   - 0x3B51, lim);
    time_seconds = w_331E;
    sound_stop(); mirror_free(); main_view_free(); cockpit_free(); timer_install_drive();
    return (s8)drive_result;   // 06c9:1BF7 must be `retf` (see §5)
}
```

Case 1 skips the life decrement. Cases 4 and 9 cost a life and end the stage.

### 4.2 Stage loading (1c8f, 0002, 1ee2, 37d0, 1e59, 1e31, 38f2)

```c
void stage_load(void) {                         // 1c8f
    mountain_scroll = 0; start_flags = 0;
    distance_left = dat_stage_length; w_5340 = dat_road_units; w_3320 = dat_road_units - 10;
    col_left = W(DAT+0x322); col_right = W(DAT+0x326); col_shoulder = W(DAT+0x32A);
    col_sky  = W(DAT+0x32E); col_far   = W(DAT+0x332);
    player_pos_hi = 0x3B51; opp_pos_hi = opponent_selected ? 0x3B51 : 0;
    player_pos_lo = opp_pos_lo = 0;
    main_view_load(); mirror_load();
    res_find_list_opt(scenery_arc, "sm00…LIN4", DS:1DB2);
    res_find_list(road_arc, "pal0…tick", DS:20F2);
    res_find_list(car1_arc, "fc0M…rcr7", DS:1A72);
    res_find_list(car2_arc, …, DS:1AF2); res_find_list(car3_arc, …, DS:1B72);
    res_find_list(cop_arc,  …, DS:1BF2); res_find_list(cop_arc, "CLR0…cp7d", DS:1C72);
    cockpit_load();
    opp_lateral = -200; w_52D6 = 0;              // 0xC8 is written first, then 0xFF38
    // difficulty tables (simulation-owned values)
    k = difficulty*2;  w_5358=T232E[k]; w_3318=T2316[k]; w_535A=T2346[k]; w_535C=T235E[k]; w_535E=T2376[k]; w_5360=T238E[k];
    k = min(k+6, 0x16); w_5362=T232E[k]; w_331A=T2316[k]; w_5364=T2346[k]; w_5366=T235E[k]; w_5368=T2376[k]; w_536A=T238E[k];
    w_536C = w_536E = w_5370 = 0; w_8658 = 0;
    sim_stage_init();                            // 3f40
}

void main_view_load(void) {                      // 0002
    main_desc = create_buffer(320, 92, 0x0F);
    main_rowtab = desc->rowtab; main_sprite = desc->sprite;
    main_sprite->x = 0; main_sprite->y = 0x13;
    res_find_list_opt(scenery_arc, "rcfA…clo3", DS:0704);
    res_find_list_opt(opp_road_arc, "rcr0…brk7", DS:080E);
    wide_toggle_ptr = 0; prev_road_byte = 0; w_09BC = 0;
}
void mirror_load(void) {                         // 1ee2
    mirror_desc = create_buffer(80, 17, 0x0F);   // DS:2A20, rowtab 2A28, sprite 2A24
    mirror_sprite->x = 0xF0; mirror_sprite->y = 8;
    res_find_list_opt(scenery_arc, "rcfC…rmt2", DS:27BE);
    res_find_list_opt(opp_road_arc, "fcr0…fa3M", DS:28C8);
    b_2C96 = 0; w_2A2A = 0;
}

void cockpit_load(void) {                        // 37d0
    res_find_list_opt(dash_arc, "dash…hdcM", DS:2FAC);
    marker_saved = 0; wheel_pose = 2;
    if (car[0x14D] != 1) res_find_list_opt(dash_arc, "dgt0…tach", DS:3010);
    inst_xy = (DASH.inst->x, ->y); inst_buf = create_buffer_like(DASH.inst);   // 2F68 / 2F6C
    gbox_xy = (DASH.gbox->x, ->y); gbox_buf = create_buffer_like(DASH.gbox);   // 2F60 / 2F64
    select_screen();
    copy_own(DASH.dash); copy_own(DASH.roof);
    draw_line(0, 0, 319, 0, 0);                        // progress line
    plot(dat_stage_length >> 5, 0, 15);                // stage-end marker
    dot_x[0] = dot_x[1] = dot_x[2] = -1;
}

void prepare_traffic_lists(void) {               // 1e59 (runs once per stage)
    u8 thr = -traffic_setting;                   // DS:1A70
    for (list = 3813, then 39A3) {
        si = 0;
        while (list[si].type != 0) {
            if (si > 16 && rand8() <= thr) {     // unsigned; first 3 entries always kept
                memmove(&list[si], &list[si+8], 0x190 - (si+8));
                continue;                        // re-test the same slot
            }
            list[si].pos_hi = (u16)((u32)list[si].pos_hi * dat_road_units / 1000) + 0x3B51;
            if (list == 3813) list[si].lateral = -200;
            else { list[si].lateral = 200; list[si].type += 4; }   // rear views
            if ((si += 8) >= 0x190) break;
        }
        count(list) = si;                        // DS:5354 / DS:5356 (bytes)
    }
}

void life_reset(void) {                          // 1e31
    sim_life_reset();                            // 3ff9
    player_lateral = 0xA0; drive_result = 0;
    w_5FD8 = w_5FDA = w_5FDC = 0xFFFF;
    cockpit_reset();                             // 38f2
}
void cockpit_reset(void) {                       // 38f2
    b_2F56 = 0; steer = heading = w_2F4A = 0;
    b_2F57 = 1; redraw_gate = redraw_inst = redraw_hud = 1; gate_close_delay = 10;
    knob_x = car[0x20]; knob_y = car[0x22];
}
```

### 4.3 Front snapshot (0201)

```c
void snapshot_front(void) {
    memset(DS:1308, 0, 17 words);                  // 1308..1329
    right_cut_x = left_sky_x = tunnel_in_r = 320;  // 12D0, 12D2, 12D6
    top_sy = tunnel_in_sy = 92;                    // 12CE, 12D4
    r0_state = r0_any = left_cut_state = right_cut_state = start_flags;
    unit_phase = unit_counter;
    heading_acc = heading;
    walk_ptr = player_pos_hi + 1; walk_sub = player_pos_lo;
    lat_acc = -player_lateral;
    r_opp_brake = b_3372; r_cop_brake = b_3373; r_opp_alt = b_3375;
    height_acc = start_height_front;               // DS:09B0 = 80
    u32 me = ((u32)walk_ptr << 16) | walk_sub;
    di = 0;
    for (list in {3813 (len 5354), 39A3 (len 5356)}) for (e in list) {
        u32 d = (((u32)e.pos_hi << 16) | e.pos_lo) - me;
        s16 hi = d >> 16; if (hi < 0) hi += dat_road_units;
        if ((u16)hi > 60) continue;
        draw_list[di] = { hi*2, e.type_word, e.lateral }; di += 8;
    }
    draw_list_len = di;
    opp_row2 = dist_hi(opp) * 2  (same wrap, no range test); opp_lat = opp_lateral;
    cop_row2 = dist_hi(cop) * 2;                              cop_lat = cop_lateral;
    r_cop_active = cop_active; r_cop_state = cop_state;
}
```

`e.type_word` is the word at entry +0 (low byte = type 1..8). A row matches when
`dist·2 == row·2`; there is no sub-unit test (unlike TD1).

The mirror snapshot `2089` is identical except: memset 2C64..2C85; widths 80, heights 17;
`2C62 = unit_counter − 1`; `heading_acc = −heading`; `walk_ptr = player_pos_hi` (no +1);
`lat_acc = −(player_lateral sar 1)`; `r_opp_alt(2A1C) = b_3375` (no brake snapshots);
`height_acc = DS:2A1E (80)`; distance = `−hi(obj − me)` (only the high word is negated), `+ road_units`
if negative, kept when `≤ 25`; list at 27F6 / 28BE; opponent 28C0/28C2, police 28C4/28C6,
2C9C/2C9D cop flags.

### 4.4 Row projection (0338 front)

```c
void project_front_rows(void) {
  for (si = 0; si != 0x78; si += 2) {              // rows 0..59, near → far
    u8 b = *walk_ptr;
    row_flags_b[si] = b >> 7;                       // byte 115C+si
    u8 prev = prev_road_byte; prev_road_byte = b;
    if (si != 0 && (s8)(prev ^ b) < 0) wide_toggle_ptr = walk_ptr;
    walk_ptr++;
    rec = &dat_records[b & 0x7F];                   // r0 r1 r2 r3
    r0_state ^= r0; r0_any |= r0; row_flags_b[si] |= r0;
    row_state_b[si] = r0_state;
    row_flags_b[si+1] = r3;                         // object byte
    pitch_acc += ((s16)(-(s8)r2)) sar 1;
    height_acc += tan256((s8)(pitch_acc >> 8));
    s16 y = mulhi(height_acc, ys_front[i]) + 0x33;  // horizon at buffer row 51
    row_sy[i] = y;
    if (y < top_sy) { top_sy = y; top_row = si; }
    row_clip[i] = top_sy;                           // (value after the update)

    s16 h = heading_acc + ((s16)(s8)r1 << 4);
    if (h < -0x4600) h = -0x4600; else if (h > 0x4600) h = 0x4600;
    heading_acc = h;
    lat_acc += tan256((s8)(h >> 8));
    s16 cx = mulhi(lat_acc, xs_front[i]) + 0x7D;    // 125
    row_cx[i] = cx;
    u16 W = w_front[i], q = W >> 2;

    // left edge with lane widening (only when dat_wide_left)
    s16 L = cx - W;
    if (dat_wide_left) {
        u16 d = walk_ptr - 1 - wide_toggle_ptr;
        if (d < 8) { if (!(prev_road_byte & 0x80)) d = 8 - d; L -= (u16)(W * d) >> 3; }
        else if (prev_road_byte & 0x80) L -= W;
    }
    row_l[i] = L; row_ol[i] = L - q;
    u8 st = r0_state;
    bool hit = false;
    if (st & 0xC0) {                                  // cliff left / tunnel: track the rightmost left edge
        s16 a = (st & 0x80) ? row_l[i] : row_ol[i];
        if (a > left_cut_x) { left_cut_x = a; left_cut_row = si; left_cut_state = st; hit = true; }
    }
    if (!hit) {                                       // leftmost outer edge of a row that is on top
        s16 a = row_ol[i];
        if (si != 0 && a < row_ol[i-1] && row_sy[i] <= top_sy && a < left_sky_x)
            { left_sky_x = a; left_sky_row = si; }
    }
    // right edge: widening ALWAYS applies (no dat_wide_left test)
    s16 R = cx + W;
    { u16 d = walk_ptr - 1 - wide_toggle_ptr;
      if (d < 8) { if (!(prev_road_byte & 0x80)) d = 8 - d; R += (u16)(W * d) >> 3; }
      else if (prev_road_byte & 0x80) R += W; }
    row_r[i] = R; row_or[i] = R + q;
    s16 c = row_or[i];                               // CX
    hit = false;
    if (st & 0x88) {                                  // cliff right / tunnel
        s16 a = (st & 0x80) ? row_r[i] : row_or[i];
        if (a < right_cut_x) { right_cut_x = a; right_cut_row = si; right_cut_state = st; hit = true; }
    }
    if (!hit) {
        s16 a = row_or[i];
        if (si != 0 && a > row_or[i-1] && row_sy[i] <= top_sy && a > right_sky_x)
            { right_sky_x = a; right_sky_row = si; }
    }
    // far-right band (DAT+0x33C)
    u16 p = walk_ptr - 0x3B33;                      // walk_ptr already incremented
    e = first band entry with p <= e.end (unsigned), stop at e.start == 0;
    if (e.start == 0 || p < e.start) row_band[i] = 0x0A00;
    else {
        s16 v = (s16)(((s32)(s16)(e.v1 - e.v0) * (s16)(p - e.start)) / (s16)(e.end - e.start)) + e.v0;
        row_band[i] = c + mid16((u32)(u16)v * W);    // unsigned mul
    }
    // tunnel rows
    s16 ys = row_sy[i]; s16 top = ys - (W >> 1); if (top <= 0) top = 0;
    if (ys >= 0x5C) ys = 0x5C;
    if ((s8)r0 < 0) {
        if ((s8)r0_state >= 0) { tunnel_out_row = si; tunnel_out_sy = ys; tunnel_out_top = top; }
        else                   { tunnel_in_row  = si; tunnel_in_sy  = ys; tunnel_in_top  = top; }
    }
    if ((r0_state & 0x80) && top >= tunnel_ceiling) { tunnel_ceiling = top; tunnel_ceiling_row = si; }
  }
  row_clip[0] = 0x5C;
}
```

Notes: `mulhi` uses the unsigned table value; `row_clip[i] <= row_sy[i]`; row i is hidden when
`row_sy[i] > row_clip[i]` (a nearer row is higher). The `idiv` in the band interpolation can
fault on overflow (not expected with shipped data).

**Mirror (21c3)** differences: 25 rows (`si != 0x32`); reads `*walk_ptr` then `walk_ptr--`;
never updates `wide_toggle_ptr` (uses the front value) and its distance is
`walk_ptr + 1 − wide_toggle_ptr`; tables xs/ys/w_mirror; `y = mulhi + 8`, `cx = mulhi + 0x28`;
band default `0x280`; tunnel sy clamp `0x11`; `row_clip[0] = 0x11`.

**Projection summary.** Row i is at depth `i+4` (front) / `i+6` (mirror). With
`H = Σ tan(pitch)` and `X = Σ tan(heading)`:
front `y = 51 + H·2.1465/(i+4)`, `x = 125 + X·2.9794/(i+4)`, half-width `1200/(i+4)`;
mirror `y = 8 + H·0.8747/(i+6)`, `x = 40 + X·1.6238/(i+6)`, half-width `360/(i+6)`.

### 4.5 Spans (05f8, 06c3, 0746, 08cb, 088e)

```c
void build_spans_front(void) {
    bp = 0;
    for (si = 2; si != 0x78; si += 2) {
        s16 y = row_sy[i];
        if (y == row_sy[bp/2]) continue;                 // bp unchanged
        s16 n = y - row_clip[i-1];
        if (n < 0) {                                      // visible: scanlines y .. y+|n|-1
            n = -n;
            if ((u8)n == 1) {
                span_ol[y]=row_ol[i]; span_l[y]=row_l[i]; span_r[y]=row_r[i];
                span_or[y]=row_or[i]; span_band[y]=row_band[i]; span_flags[y]=row_state_w[i];
            } else {
                s16 dy = row_sy[bp/2] - y;
                for (k = 0; k < n; k++) span_flags[y+k] = row_state_w[i];
                interp_span(row_ol[i],   row_ol[bp/2],   &span_ol[y],   n, dy);
                interp_span(row_l[i],    row_l[bp/2],    &span_l[y],    n, dy);
                interp_span(row_r[i],    row_r[bp/2],    &span_r[y],    n, dy);
                interp_span(row_or[i],   row_or[bp/2],   &span_or[y],   n, dy);
                interp_span(row_band[i], row_band[bp/2], &span_band[y], n, dy);
            }
        }
        bp = si;
    }
}
// row_state_w[i] = word at 11D4+2i: low byte = r0_state, high byte = static 0

void interp_span(s16 a, s16 b, s16 *dst, u16 n, u16 dy) {   // 06c3
    s16 lim = view_width;
    if (a <= 0 && b <= 0) { fill n × 0; return; }
    if (a >= lim && b >= lim) { fill n × lim; return; }
    *dst++ = a; n--;
    s16 d = b - a;
    if (d == 0) { fill n × a; return; }
    int step = d > 0 ? +1 : -1; u16 ad = d > 0 ? d : -d;
    s16 acc = 0;
    if (ad > dy) {                    // unsigned: more than one pixel per scanline
        while (n--) { do { acc += dy; a += step; } while (acc < (s16)ad); acc -= ad; *dst++ = a; }
    } else {
        while (n--) { acc += ad; if (acc >= (s16)dy) { a += step; acc -= dy; } *dst++ = a; }
    }
}
```

```c
void fix_cut_lines_front(void) {                         // 0746
    u8 f = r0_any; if (f == 0) return;
    if (f & 0x20) { left_sky_sy2  = row_sy[left_sky_row/2]  * 2; left_sky_x  = clamp(left_sky_x, 0, 320); }
    if (f & 0x04) { right_sky_sy2 = row_sy[right_sky_row/2] * 2; right_sky_x = clamp(right_sky_x, 0, 320); }
    s16 d = left_cut_x;  if ((f & 0x40) && !(left_cut_state & 0x80))  d -= 22;
    left_cut_x  = d <= 0 ? 0 : min(d, 320);
    d = right_cut_x;     if ((f & 0x08) && !(right_cut_state & 0x80)) d += 22;
    right_cut_x = d <= 0 ? 0 : min(d, 320);
    if (!(f & 0x80)) return;
    if (tunnel_out_sy == 0) { tunnel_out_sy = tunnel_out_top = top_sy; tunnel_out_row = 0x76; }
    if (tunnel_ceiling_row != top_row && tunnel_ceiling_row < top_row && tunnel_ceiling > top_sy)
        top_sy = tunnel_ceiling;
    //   (the other branch, ceiling_row > top_row, writes tunnel_ceiling to itself: no effect)
    if (left_cut_row != right_cut_row) {
        if (left_cut_row < right_cut_row) { if (right_cut_x <= left_cut_x) right_cut_x = left_cut_x; }
        else                              { if (left_cut_x >= right_cut_x) left_cut_x = right_cut_x; }
    }
    tunnel_in_l  = clamp_edge(row_l[tunnel_in_row/2],  tunnel_in_row);   // 1326
    tunnel_in_r  = clamp_edge(row_r[tunnel_in_row/2],  tunnel_in_row);   // 12D6
    tunnel_out_l = clamp_edge(row_l[tunnel_out_row/2], tunnel_out_row);  // 12D8
    tunnel_out_r = clamp_edge(row_r[tunnel_out_row/2], tunnel_out_row);  // 1328
}
s16 clamp_edge(s16 x, u16 si) {                          // 08cb
    if (r0_any & 0x88) {
        if (x < 0) x = 0;
        else if ((s16)si > (s16)right_cut_row) { if (x > right_cut_x) x = right_cut_x; }
        else if (x > 320) x = 320;
    }
    if (r0_any & 0xC0) {
        if (x > 320) return 320;
        if ((s16)si >= (s16)left_cut_row && x < left_cut_x) return left_cut_x;
    }
    return x;
}
void clamp_spans(u16 first, u16 end) {                    // 088e, AX, BP
    for (arr in span_ol, span_l, span_r, span_or, span_band)
        for (y = first; y < end; y++) arr[y] = clamp(arr[y], 0, view_width);  // signed
}
```

`clamp_spans` uses `loop` with `CX = end − first`: if `first == end` the original would run 65536
iterations (overwriting DGROUP). `top_sy` is always < 92 in practice; a port should treat it as
empty. Mirror: `2542`/`268a` use 80 instead of 320, cut offset **6** instead of 22, and default
`tunnel_out_row = 0x30`.

### 4.6 Ground and sky (0b0d, 0c17, 0919, 0bb8)

```c
// 0c17: fills the current scanline from span_x to end-1, then to the end of that byte
void span_fill_to(s16 end, u8 colour) {
    if (end <= span_x) return;
    s16 cb = span_x sar 3; span_x = end;
    u8 p[4] = colour_plane[colour & 15];
    s16 e = end - 1, eb = e sar 3, ebit = e & 7;
    u8 m = mask_from_bit[span_bit];
    for (k in 0..3) row[k][di] = (row[k][di] & ~m) | (p[k] & m);
    if (eb - cb != 0) { di++; for (k) memset(&row[k][di], p[k], eb - cb); di += eb - cb - 1; }
    span_bit = ebit + 1;
    if (span_bit == 8) {
        span_bit = 0; di++;
        if (span_x == view_width) goto *row_skip_target;   // abandon the rest of this scanline
    }
}
```

Pixels after `end` in the last byte take the colour until the next fill overwrites them; the
visible result equals "each span `[start,end)` in order, the last one extended to its byte end".

```c
void draw_ground_front(void) {                            // 0b0d
    for (y = top_sy; y < 92; y++) {
        di = rowtab[y]; span_bit = span_x = 0;
        u16 f = span_flags[y];
        u16 c = col_left;
        if (f & 0x20) {                                   // left drop-off: sky beside the road
            c = col_sky;
            if (2*y >= left_sky_sy2 && left_sky_x < span_ol[y]) { span_fill_to(left_sky_x, col_sky); c = col_left; }
        }
        span_fill_to(span_ol[y], c);
        span_fill_to(span_l[y],  col_shoulder);
        span_fill_to(span_r[y],  7);                      // road surface: light grey
        span_fill_to(span_or[y], col_shoulder);
        if (f & 0x04) {                                   // right drop-off
            if (2*y >= right_sky_sy2 && right_sky_x >= span_or[y]) span_fill_to(right_sky_x, col_right);
            span_fill_to(320, col_sky);
        } else {
            span_fill_to(span_band[y], col_right);
            span_fill_to(320, col_far);
        }
    next_row: ;                                           // DS:0702 = 0B7B
    }
}
```

```c
void draw_sky_front(void) {                               // 0919
    s16 h = top_sy; u8 f = r0_any;
    if (!dat_tunnel_style && f != 0) {
        if (f & 0x80) {                                   // tunnel somewhere in view
            if (!(r0_state & 0x80)) {                     // state after row 59: far end not in a tunnel
                if (f & 0x40) fill(left_cut_x, tunnel_ceiling, tunnel_out_r - left_cut_x, top_sy - tunnel_ceiling, col_sky);
                else          fill(tunnel_out_l, tunnel_ceiling, right_cut_x - tunnel_out_l, top_sy - tunnel_ceiling, col_sky);
                fill(tunnel_out_l, tunnel_in_top, tunnel_out_r - tunnel_out_l, tunnel_ceiling - tunnel_in_top, 0);
            } else
                fill(tunnel_out_l, tunnel_in_top, tunnel_out_r - tunnel_out_l, tunnel_out_top - tunnel_in_top, 0);
            return;
        }
        if (f & 0x40) {
            if (f & 0x08) fill(left_cut_x, 0, right_cut_x - left_cut_x, h, col_sky);
            else          fill(left_cut_x, 0, 320 - left_cut_x, h, col_sky);
            return;
        }
        if (f & 0x08) { fill(0, 0, right_cut_x, h, col_sky); return; }
    }
    fill(0, 0, 320, h, col_sky);
    if (dat_no_mountains || S0704[8].seg == 0) return;     // mtn0
    s16 x = (u16)(-(mountain_scroll - (s8)((u16)(heading << 3) >> 8))) & 0x3FF;
    copy_ch(S0704[8],  x - 1024, h);  copy_ch(S0704[10], x - 500, h);
    copy_ch(S0704[9],  x - 300,  h);  copy_ch(S0704[8],  x,       h);
    if (S0704[11].seg == 0) return;                        // clo1
    x = (u16)(-(cloud_scroll - (s8)((u16)(heading << 3) >> 8))) & 0x3FF;
    s16 cy = row_sy[59] - 30; x -= 100;
    copy_ch(S0704[11], x - 1024, cy); copy_ch(S0704[13], x - 500, cy);
    copy_ch(S0704[12], x - 300,  cy); copy_ch(S0704[11], x,       cy);
}
```

(The order of blits above is the call order; x offsets are cumulative: 0, −300, −500, −1024.)

```c
void draw_tunnel_walls_front(void) {                      // 0bb8, only when r0_any & 0x80
    for (y = tunnel_out_sy; y < tunnel_in_sy; y++) {
        if (!dat_tunnel_style) {
            hline(tunnel_in_l, span_l[y], y, 0);
            hline(span_l[y], span_r[y], y, 8);
            hline(span_r[y], tunnel_in_r, y, 0);
        } else {
            hline(tunnel_in_l, span_l[y], y, 8);
            hline(span_r[y], tunnel_in_r, y, 8);
        }
    }
}
```

Mirror: `26d8` / `284f` / `28f9` are the same with width 80 and the mirror variables, except
mountains: `x = (mountain_scroll − (s8)((heading<<3)>>8)) & 0x3FF` (not negated) then `sar 1`,
y = `row_sy_m[24]`, handles `rmt0` (di), `rmt1` (−150), `rmt2` (−250), `rmt0` (−512); no clouds.

### 4.7 Falling-off-the-road view (inside 00e7 / 1f99)

```c
void draw_front(void) {                                   // 00e7
    row_skip_target = 0x0B7B;
    select_target(main_desc); cache plane segments;
    if (fall_mode == 0 || fall_scroll < 92) {
        draw_sky_front(); draw_ground_front();
        if (r0_any & 0x80) draw_tunnel_walls_front();
        draw_front_objects();
    }
    if (fall_mode == 0 || fall_scroll == 0) return;
    u16 v = fall_scroll, y = 92 - v;
    copy_clip_raw(main_sprite, 0, -v);                    // scroll the finished view up
    if (fall_mode == 4) { fill(0, y, 320, 180, 9); return; }   // water
    s16 x; u8 cl, cr;
    if (fall_mode == 1) { x = left_sky_x;  cl = col_sky; cr = 6; }
    else                { x = right_sky_x; cl = 6; cr = col_sky; }
    fill(0, y + 180, 320, 100, 6);  fill(x, y, 320 - x, 180, cr);  fill(0, y, x, 180, cl);
}
```

Mirror (1f99): mode 4 copies with `v = fall_scroll >> 3` and fills `(0, 17−v, 80, 180, 9)`;
other modes (no scroll): `a = (fall_scroll>>3) + top_sy_m`; `fill(0, a, 80, 17−a, 6)` then
`fill(0, 0, 80, a, col_sky)`. Then (always, also after the normal path) `select_main_view();
copy_own(mirror_sprite)`.

### 4.8 Front objects (0d13)

Rows are drawn **far to near** (si = 0x76 … 0) directly; there is no deferred stack.
`clip.y0` is 0 unless the tunnel ceiling logic sets it; `clip.y1 = row_clip[i]` so objects vanish
behind crests.

```c
void draw_front_objects(void) {
  dash_phase = unit_phase + 59;
  u8 saved_state = r0_state;                     // r0_state holds the state after row 59
  si = 0x76;
  for (;;) {                                     // loop head = 06c9:0D22
    set_ceiling_clip();
    u16 W = w_front[i];
    obj_size = min(W >> 3, 31);
    scale5 = ((s8)obj_size >= 16 ? 16 : obj_size) & 0xFC;   // 0,4,8,12,16 → 5 sizes
    scale4 = (obj_size >> 1) & 0xFC;                        // 0,4,8,12   → 4 sizes
    clip.y1 = row_clip[i];
    s16 y = row_sy[i];
    u8 fl = row_flags_b[si];

    // 1. road markings (only visible rows)
    if (!(y > row_clip[i] || y == 92) && ((fl & 1) || !(dash_phase & 4))) {
        s16 x = row_cx[i];
        if ((u16)x < 320) pixel(x, y) = (pixel & ~1) | 0x0E;     // plane0 cleared, planes1-3 set
        if ((fl & 1) && !(dash_phase & 4)) {                    // wide road: lane lines
            x = row_cx[i] + W; if ((u16)x < 320) pixel |= 15;
            if (dat_wide_left) { x = row_cx[i] - W; if ((u16)x < 320) pixel |= 15; }
        }
    }
    // 2. left cliff (state bit 0x40)
    if (r0_state & 0x40) {
        if (si == left_cut_row && !(r0_state & 0x80)) {
            s16 bx0 = 0, by0 = 0, h = row_clip[i];
            if ((r0_any & 0x80) && si >= tunnel_out_row) { by0 = tunnel_ceiling; h -= by0; bx0 = tunnel_out_l; }
            fill(bx0, by0, left_cut_x - bx0, h, 6);
            s16 yy = min(y, 92);
            and_ch(S0704[4] /*lcfA*/, row_ol[i], yy); or_ch(S0704[5] /*lcfa*/, row_ol[i], yy);
        }
        if (!(r0_state & 0x80) && si < 0x2E && si < left_cut_row) cliff_decoration(LEFT);
    }
    // 3. right cliff (state bit 0x08) — same with right_cut_row, right_cut_x,
    //    fill(right_cut_x, by0, bx1 - right_cut_x, h, 6) where bx1 = 320 or tunnel_out_r,
    //    sprites S0704[0] rcfA (AND) / S0704[1] rcfa (OR) at row_or[i];
    //    cliff_decoration(RIGHT) if !(r0_state & 0x80) && si < 0x2E && si < right_cut_row
    clip.y0 = 0;
    // 4. tunnels (only if r0_any & 0x80)
    if (r0_any & 0x80) tunnel_mouths();          // §4.8.1
    set_ceiling_clip();                          // 06c9:13BF
    // 5. tunnel lights, every 16 units, inside tunnels
    if (!dat_tunnel_style && ((dash_phase + 8) & 15) == 0 && (r0_state & 0x80)) {
        s16 ty = y - (W >> 1);
        if (ty >= 0) or_ch(S1DB2[80 + scale5/4] /*SM00-04*/, row_cx[i], ty);
    }
    // 6. road object r3 (§4.9)
    u8 o = row_flags_b[si+1];
    if (o != 0 && o < 0x15) road_object(o);
    // 7. scenery (§4.10), rows < 44
    if (si < 0x58) scenery();
    // 8. poles every 16 units
    if ((dash_phase & 15) == 0) {
        if (r0_state & 0x80) tunnel_rib_front(si);
        else {
            s16 py = y - obj_size, q = W >> 2;
            s16 xr = row_r[i] - 1 + q, xl = row_l[i] - q;
            if ((u16)xr < 320) { and_ch(ROAD[0 + scale4/4] /*pal*/, xr, py); or_ch(ROAD[4 + scale4/4] /*pol*/, xr, py); }
            if ((u16)xl < 320) { and_ch(ROAD[0 + scale4/4], xl, py);          or_ch(ROAD[4 + scale4/4], xl, py); }
        }
    }
    // 9. traffic (all list entries on this row, list order reversed)
    for (e = last .. first) if (e.dist2 == si) {
        s16 x = mulhi(e.lateral, xs_front[i]) + row_cx[i];
        u16 t = e.type - 1;
        u16 k = ((((t & 3) << 4) + ((t & 4) << 1)) * 2 + carscale_front[i]);  // entry index
        // (t&3) = CAR1 / CAR2 / CAR3 / COP table, (t&4) = rear-view half, carscale 0..7
        and_ch(T1A72[k], x, y - 1); or_ch(T1A72[k + 8], x, y - 1);
    }
    // 10. opponent
    if (opponent_enabled && si == opp_row2) {
        s16 x = mulhi(opp_lat, xs_front[i]) + row_cx[i]; u16 s = carscale_front[i];
        u16 k = r_opp_alt ? 16 + s : s;
        and_ch(S080E[k + 8] /*rc?M / ra?M*/, x, y - 1); or_ch(S080E[k] /*rcr? / rac?*/, x, y - 1);
        if (r_opp_brake) xor_ch(S080E[32 + s] /*brk*/, x, y - 1);
    }
    // 11. police car
    if (r_cop_active && si == cop_row2) {
        s16 x = mulhi(cop_lat, xs_front[i]) + row_cx[i]; u16 s = carscale_front[i];
        and_ch(T1BF2[16 + s] /*COP rc?M*/, x, y - 1); or_ch(T1BF2[24 + s] /*COP rcr?*/, x, y - 1);
        if (r_cop_brake) xor_ch(T1C72[8 + s] /*brk*/, x, y - 1);
        if (time_seconds & 1) xor_ch(T1C72[s] /*CLR light bar*/, x, y - 1);
    }
    // 12. parked police car beside the road (pulled over), one row nearer
    if (r_cop_state >= 7 && si + 2 == cop_row2) {
        u16 k = 16 + carscale_front[i]*4 + ((radar_flags & 0x0C) >> 2);     // CP?x frame
        and_ch(T1C72[k + 32] /*cp..*/, row_r[i], y - 1); or_ch(T1C72[k] /*CP..*/, row_r[i], y - 1);
    }
    dash_phase--;
    r0_state ^= row_flags_b[si];                 // state before this row
    if ((si -= 2) < 0) break;
  }
  r0_state = saved_state;
}

void set_ceiling_clip(void) {                    // inline at 0d22 and 13bf
    if (!dat_tunnel_style) clip.y0 = tunnel_ceiling;
    if ((r0_any & 0x80) && si <= tunnel_ceiling_row) clip.y0 = 0;
}

void cliff_decoration(side) {                    // only beside a cliff wall, rows i < 23, 16-unit pattern
    u16 w = cliff_deco_pattern[dash_phase & 15];
    if ((u8)w == 0) return;
    s16 x = side == LEFT ? row_ol[i] : row_or[i];
    if ((u16)x >= 320) return;
    u16 base = side == LEFT ? 184 : 160;          // S1DB2 index: rcka/wedA/lin1 or rcka/wed0/linA
    u16 k = base + ((u8)w - 1) * 4 + scale4/4;
    s16 yy = row_sy[i];
    if (w >> 8) yy -= (u8)(obj_size >> 1) * (u8)(w >> 8);
    and_ch(S1DB2[k + 12] /*upper case*/, x, yy); or_ch(S1DB2[k], x, yy);
}
```

The traffic entry index `k` works out to: CAR table offset `(t&3)·32`, rear half `+16` when
`t & 4`, then `+carscale`; mask = entry k (`fc?M` / `rc?M`), image = k+8 (`fcr?` / `rcr?`).

#### 4.8.1 Tunnel mouths (inside the row loop)

```c
void tunnel_mouths(void) {
  if (si == tunnel_out_row) {                          // far end of the tunnel
      u8 c = 0; s16 top = tunnel_in_top, a = tunnel_in_l, b = tunnel_out_l;
      if (dat_tunnel_style) { c = 8; b = row_l[i]; top = top_sy - 5; }
      if (b <= a) swap(a, b);
      s16 h = tunnel_out_sy - top;
      s16 a2 = tunnel_out_r, b2 = tunnel_in_r;
      if (dat_tunnel_style) { a2 = row_r[i]; if (b2 <= a2) swap(a2, b2); }
      fill(a2, top, b2 - a2, h, c);  fill(a, top, b - a, h, c);
      if (dat_tunnel_style) tunnel_rib_front(si);
  } else if (!dat_tunnel_style && (r0_state & 0x80)) {
      if (si == right_cut_row) fill(right_cut_x, tunnel_in_top, tunnel_in_r - right_cut_x, row_clip[i] - tunnel_in_top, 0);
      if (si == left_cut_row)  fill(tunnel_in_l, tunnel_in_top, left_cut_x - tunnel_in_l, row_clip[i] - tunnel_in_top, 0);
  }
  if (si != tunnel_in_row) return;                     // near end (entrance)
  if (start_flags & 0x80) {                            // car already inside
      if (dat_tunnel_style) {
          s16 t = top_sy - 5, h = row_clip[i] - t;
          fill(tunnel_in_r, t, 320 - tunnel_in_r, h, 8); fill(0, t, tunnel_in_l, h, 8);
      } else {
          fill(0, 0, tunnel_in_l, row_clip[i], 0); fill(tunnel_in_r, 0, 320 - tunnel_in_r, row_clip[i], 0);
      }
      return;
  }
  if (dat_tunnel_style) { tunnel_rib_front(si); return; }
  if (!(r0_state & 0x40)) {                            // portal variant A (no left-cliff state)
      s16 bp = tunnel_in_l, d = left_sky_x, px;
      if (si > left_sky_row || (d != 0 && bp <= (d += 15))) {
          fill(0, 0, bp, top_sy, col_sky);  px = row_l[i];
      } else {
          fill(d, 0, bp - d, row_clip[i], 6);
          bp = d;
          if (bp == 0) goto walls;
          fill(0, 0, bp, top_sy, col_sky);  px = bp;
      }
      and_ch(S0704[2] /*rcfB*/, px, 0x5B); or_ch(S0704[3] /*rcfb*/, px, 0x5B);
  walls:
      fill(bp, 0, 320 - bp, tunnel_in_top, 6);
      fill(tunnel_in_r, tunnel_in_top, 320 - tunnel_in_r, row_clip[i] - tunnel_in_top, 6);
  } else {                                             // variant B (left-cliff state), mirrored
      s16 bp = tunnel_in_r, d = right_sky_x, px;
      if (si > right_sky_row || (d != 320 && bp >= (d -= 15))) {
          fill(bp, 0, 320 - bp, top_sy, col_sky);  px = row_r[i];
      } else {
          fill(bp, 0, d - bp, row_clip[i], 6);
          bp = d;
          fill(bp, 0, 320 - bp, top_sy, col_sky);  px = bp;
      }
      and_ch(S0704[6] /*lcfB*/, px, 0x5B); or_ch(S0704[7] /*lcfb*/, px, 0x5B);
      fill(0, 0, bp, tunnel_in_top, 6);
      fill(0, tunnel_in_top, tunnel_in_l, row_clip[i] - tunnel_in_top, 6);
  }
  if (si != 0) tunnel_rib_front(si);
}

void tunnel_rib_front(u16 si) {                         // 1ad6
    s16 yb = row_sy[i], yt = yb - (w_front[i] >> 1);
    if (dat_tunnel_style) yt = top_sy - 5;
    if (!dat_tunnel_style) draw_line(row_l[i], yt, row_r[i], yt, 15);
    draw_line(row_r[i], yt, row_r[i], yb, 15);
    draw_line(row_l[i], yt, row_l[i], yb, 15);
}
```

In the "portal, cliff left" path `bp` after the `else` branch is the sky cut x (`left_sky_x+15`
or 0), so `walls` starts the brown fill there; in the first branch it stays `tunnel_in_l`.
The mirrored branch has no `bp == 0` shortcut.

### 4.9 Road objects (record byte r3, 1..20)

```c
void road_object(u8 o) {
  s16 y = row_sy[i], W = w_front[i];
  switch (o) {
  case 1 ... 9: {                                   // signs on both sides of the road
      u16 k = 8 + (o-1)*4 + scale4/4;               // ROAD sign mask (sa*)
      s16 yy = y - obj_size;
      or_ch(ROAD[80 + scale4/4] /*pst*/, row_r[i], yy);
      or_ch(ROAD[80 + scale4/4],         row_l[i], yy);
      and_ch(ROAD[k], row_r[i], yy);  and_ch(ROAD[k], row_l[i], yy);
      or_ch(ROAD[k + 36] /*sp*/, row_r[i], yy);  or_ch(ROAD[k + 36], row_l[i], yy);
      break; }
  case 10: case 12: {                               // white band across the road
      s16 y0 = min(y, 91), y1 = (si < 6) ? 91 : row_sy[i-3];
      clip.y1 = 92;
      for (yy = y0; yy <= y1; yy++) hline(span_l[yy], span_r[yy], yy, 15);
      clip.y1 = row_clip[i];
      break; }
  case 11:                                          // end of stage
      if (!last_stage) {                            // gas station sign
          and_ch(ROAD[112 + scale5/4] /*GST*/, row_r[i] + W, y);
          or_ch (ROAD[117 + scale5/4] /*gst*/, row_r[i] + W, y);
      } else {                                      // FINISH banner
          s16 h = (W sar 1) + (W sar 2), p = (W sar 2) sar 1;   // 3W/4, W/8
          s16 top = y - h, xl = row_l[i] - p;
          fill(xl + p, top, row_r[i] - (xl + p), 2*p, 15);      // banner
          fill(row_r[i], top, p, h, 15);                         // right post
          fill(xl, top, p, h, 15);                               // left post
          s16 ox = xl + p + p;  u16 s = xs_front[i];
          for (seg in finish_letters)                            // DS:5378
              draw_line(hiword(seg.x1*s) + ox, hiword(seg.y1*s) + top,
                        hiword(seg.x0*s) + ox, hiword(seg.y0*s) + top, 0);
      }
      break;
  case 13 ... 20: {                                 // hazards, XOR drawn
      s16 x = row_cx[i] + ((o & 1) ? -(s16)(W >> 1) : (W >> 1));
      u16 g = (((o - 10) * 2 - 6) & 0xFC) * 4;      // 0 rck, 16 oil, 32 gra, 48 pot (bytes)
      xor_ch(ROAD[84 + g/4 + scale4/4], x, y);
      break; }
  }
}
```

`hiword(a*s)` is the unsigned high word of the 32-bit product. The GST/gst pair uses the 5-size
index (`scale5`).

### 4.10 Scenery and text signs (DAT + SGN + FNT)

```c
void scenery(void) {                              // front: rows i < 44; mirror: all rows
  u8 k = dash_phase & 0x7F;
  s8 t = dat_scenery_type[k];
  if (t < 0) return;
  if ((u8)t < 80) {
      far *h = &S1DB2[t + scale5/4];              // t is a multiple of 5: type·5
      if (h->seg != 0) {
          s16 off = (s8)dat_scenery_offset[k]; off += off >= 0 ? 2 : -2;
          s16 x = (s16)(off * W) sar 3;
          x += (x > 0) ? row_r[i] : row_l[i];
          and_ch(*h, x, row_sy[i]); or_ch(S1DB2[t + scale5/4 + 80], x, row_sy[i]);
          return;
      }
  }
  if ((u8)t < 30 || sgn_segment == 0) return;
  u16 n = ((u8)t - 30) / 5;
  u16 ofs = SGN[n];  if (ofs == 0) return;         // word n of the SGN file
  memcpy(sign_work /*52E4*/, SGN + ofs, 45 words);
  sw.w  = mid16(sw.w  * W) >> 1;   sw.h = mid16(sw.h * W) >> 1;   sw.post_h = mid16(sw.post_h * W) >> 1;
  s16 post_w = W >> 4;                              // 52E0
  s16 x = (s16)((s8)dat_scenery_offset[k] * W) sar 3;    // no ±2 here
  x += ((x > 0) ? row_r[i] : row_l[i]) - (sw.w >> 1);
  sign_x = x;                                       // 52E2
  s16 post_top = row_sy[i] - sw.post_h;
  s16 board_top = post_top - sw.h;  sign_y = board_top;   // stored into 52E6
  fill(x, board_top, sw.w, sw.h, sw.board_colour);          // +0C
  fill(x + sw.w - post_w, post_top, post_w, sw.post_h, sw.post_colour);   // +10
  fill(x, post_top, post_w, sw.post_h, sw.post_colour);
  // text, vector font
  u16 x0 = sw.margin_x;                             // saved in 52E0
  for (char *p = sw.text; ; ) {
      s8 c = *p++;
      if (c < 10) break;                            // 0 or ≥ 0x80 ends the text
      if (c == 10) { sw.margin_x = x0; sw.margin_y += sw.line_step; continue; }
      u16 g = FNT[((u8)c - 0x20) * 2];              // glyph offset in the FNT segment
      if (g) for (u8 *s = FNT + g; *s != 0xFF; s += 4) {
          s16 ax = (mid16((s[0] + sw.margin_x) * W) >> 1) + sign_x;
          s16 ay = (mid16((s[1] + sw.margin_y) * W) >> 1) + sign_y;
          s16 bx = (mid16((s[2] + sw.margin_x) * W) >> 1) + sign_x;
          s16 by = (mid16((s[3] + sw.margin_y) * W) >> 1) + sign_y;
          draw_line(ax, ay, bx, by, sw.text_colour);        // +08
      }
      sw.margin_x += sw.advance;                    // +04
  }
}
```

(`sw` fields are the words at 52E4+2k, see §5.2. The stroke bytes are unsigned.)

### 4.11 Mirror objects (2958) — differences from 0d13

| Aspect | Mirror |
|---|---|
| Rows | 25, si = 0x30 … 0; `dash = unit_counter − 1 − 24`, **incremented** per row (row i has `unit_counter−1−i`) |
| Tables | w/xs/carscale mirror; `scale*` in 2C8A/2C8C/2C8E; width 80; `y == 17` means hidden |
| Cliffs | left: `lcfC`/`lcfc` (27CE/27D2) at row_ol; right: `rcfC`/`rcfc` (27BE/27C2) at row_or; y clamp 17 |
| Cliff decorations (rck/wed/lin) | **not drawn** |
| Tunnel entrance | sky-cut offset ±3 (not 15), portal sprites `rcfD`/`rcfd`, `lcfD`/`lcfd` at y 0x10, widths 80 |
| Tunnel lights | same (SM00-04) |
| Signs 1–9 | posts at R and L, then **only the AND masks** at R and L — the sign image is never drawn |
| Objects 10/12 | band from `row_sy[i+3]` (or `top_sy` when si > 0x2C) to `min(row_sy[i],16)`, clip.y1 = 17 |
| Object 11 | GST/gst as front; FINISH: the 3 white rectangles only, **no letters** |
| Hazards | same |
| Scenery / text signs | same, no row limit |
| Poles | same (width 80) |
| Traffic | `x = (mulhi(lat, xs) sar 1) + cx`; type `(t−1) xor 4` (front/rear swapped) |
| Opponent | `x` as traffic; mask 28C8[8+k] (`fc?M`/`fa?M`), image 28C8[k] (`fcr?`/`fac?`), `k = carscale (+16 if opp_alt)`; no brake lights |
| Police | COP front `fc?M` (1BF2[s]) / `fcr?` (1BF2[8+s]); light bar when time odd; no brake lights |
| Parked police | same as front (`si + 2 == cop_row2_m`) |
| End | restore state; `select_main_view(); copy_own(mirror_sprite)` |

### 4.12 HUD (391f) and cockpit

```c
void draw_hud(void) {
    select_main_view();
    and_own(DASH.mirr);                              // mirror frame over the composited mirror
    if (cop_state >= 4 && cop_state <= 6) {          // ticket
        copy_own(ROAD[131] /*tick*/);
        u8 v = ticket_amount; u8 hun = v/100, ten = (v%100)/10, one = (v%100)%10;
        if (hun) xor_raw(ROAD[102+hun], 0x37, 0x13);
        if (hun || ten) xor_raw(ROAD[102+ten], 0x3C, 0x13);
        xor_raw(ROAD[102+one], 0x41, 0x13);
    }
    select_screen();
    if (radar_flags & 4) copy_own(DASH[13 + radar_level]); else copy_own(DASH.radb);
    progress_dot(player_pos_hi, 0, 12); progress_dot(opp_pos_hi, 1, 9); progress_dot(cop_pos_hi, 2, 14);
    if (!redraw_hud) return;
    redraw_hud = 0;
    copy_own(DASH.time);
    u16 d = distance_left > 0 ? distance_left : 0;
    d /= 42;                                          // 16-bit div
    u8 a = d / 100 (byte div: faults if d >= 25600), r = d % 100;
    or_raw(ROAD[102 + r%10], car[0xC9], car[0xC3]);
    or_raw(ROAD[102 + r/10], car[0xC7], car[0xC3]);
    or_raw(ROAD[102 + a],    car[0xC5], car[0xC3]);
    u16 m = time_seconds / 60 (cwd: signed dividend), s = time_seconds % 60;
    or_raw(ROAD[102 + s%10], car[0xD1], car[0xC3]);  or_raw(ROAD[102 + s/10], car[0xCF], car[0xC3]);
    or_raw(ROAD[102 + m%10], car[0xCD], car[0xC3]);  or_raw(ROAD[102 + m/10], car[0xCB], car[0xC3]);
}
void progress_dot(u16 pos, int k, u8 colour) {       // 3ab8
    s16 x = pos - 0x3B51; if (x < 0) x = -32;
    x = x sar 5;
    if (x == dot_x[k]) return;
    s16 old = dot_x[k]; dot_x[k] = x;
    if (old >= 0) plot(old, 0, 0);
    if (x >= 0) plot(x, 0, colour);
}
```

`car[n]` is the word at DS:23A6+n. `DASH[13 + radar_level]` is `rad0` for level 0 and `rad5…rad1`
for levels 1–5.

```c
void draw_gear_gate(void) {                          // 3b95 (TD1 0x351A)
    if (gate_visible != gate_prev) {
        gate_prev = gate_visible;
        if (gate_visible == 1) goto redraw; else goto closed;
    }
    if (gate_visible == 1) goto check;
    if (gate_close_delay == 0) return;
    if (--gate_close_delay != 0) goto check;
closed: select_screen(); copy_own(DASH.gbo0); return;
check:  if (redraw_gate != 1) return;
redraw: redraw_gate = 0;
    select_target(gbox_buf);
    copy_raw(DASH.gbox, 0, 0);
    and_ch(DASH.gnab, knob_x, knob_y); or_ch(DASH.gnob, knob_x, knob_y);
    select_screen(); copy_own(gbox_buf_sprite);
}

void draw_steering(void) {                           // 3c3a
    if (marker_saved) copy_raw(&marker_save_sprite, marker_save_x, marker_save_y);
    u16 old = wheel_pose, p = 2;
    if ((s8)(steer >> 8) >= 4) p = 0;                // right
    if ((s8)(steer >> 8) <= -4) p += 2;              // left
    if (p != old) {
        wheel_pose = p;
        u16 t = (p == 2) ? old : p;                  // back to centre: remove the old pose
        xor_own(DASH[21 + t/4] /*t=0 whl1, t=4 whl3*/);
    }
    u16 k = (s8)(((u16)(0x0F00 - steer) << 1) >> 8);     // 0..60
    u16 tip = car_w(0xD3 + 2*k);                      // lo = x, hi = y
    s16 mx = tip & 0xFF, my = tip >> 8;               // (CH of CX is assumed 0, see §9 item 1)
    marker_saved = (u8)my;
    marker_save_x = (mx - 2) & 0xFFF8; marker_save_y = my - 2;
    grab_into_sprite_raw(&marker_save_sprite, marker_save_x, marker_save_y);
    and_hot(DASH.dota, mx, my); or_hot(DASH.dot, mx, my);
}
```

A direct right↔left change (0↔4 in one frame) XORs the new pose without removing the old one.

```c
void draw_instruments(void) {                        // 3cef
    if (redraw_inst != 1) return;
    redraw_inst = 0;
    select_target(inst_buf); fill_clip(0);
    u16 f = car[0x14D];
    si = <caller's SI>;                               // only defined when the speed uses digits
    if (f & 3) {
        if (f & 1) {                                  // speed bar
            u16 v = speed_mph - car[0x15B]; if (v >= car[0x153]) v = car[0x153];
            u8 len = (u16)(v << 1) / (u8)car[0x157];  // byte div
            s16 x = car[0x175], y = car[0x177], w = len, h = car[0x15D];
            if ((u8)car[0x14F] == 0) { w = car[0x15D]; h = len; y -= len; }   // vertical
            fill_rect(x, y, w, h, 15);
            and_clip_own(DIG.spdo);
            if (!(f & 2)) goto tach;
        }
        si = 0; draw_number3(speed_mph);
    } else {                                          // speed needle
        u16 tip = car_w(0x179 + 2*((u8)(speed_mph*2) / 5));
        draw_line(car[0x175], car[0x177], tip & 0xFF, tip >> 8, 15);
    }
tach:
    if (f & 0x0C) {
        if (f & 4) {                                  // rpm bar
            u16 v = rpm - car[0x15F]; if (v >= car[0x155]) v = car[0x155];
            u8 len = v / (u8)car[0x159];              // byte div of a 16-bit value
            s16 x = car[0x249], y = car[0x24B], w = len, h = car[0x161];
            if ((u8)car[0x151] == 0) { w = car[0x161]; h = len; y -= car[0x161]; }  // NB: subtracts the thickness
            fill_rect(x, y, w, h, 15);
            and_clip_own(DIG.tach);
            if (!(f & 8)) goto done;
        }
        draw_number3((s16)rpm / 100);                 // cwd + div: signed dividend
    } else {                                          // rpm needle
        u16 r = min_u(rpm, car[0x02]) >> 6; if ((u8)car[0x24D]) r >>= 1;
        u16 tip = car_w(0x24F + 2*r);
        draw_line(car[0x249], car[0x24B], tip & 0xFF, tip >> 8, 15);
    }
done:
    or_clip_raw(DASH.inst, 0, 0);
    xor_own(DASH[7 + wheel_pose/2] /*inl1..3*/);      // table 2FC8 + 2·pose
    select_screen(); copy_own(inst_buf_sprite);
}
void draw_number3(u16 v) {                           // 3ea4, uses SI as slot
    u8 h = v / 100, r = v % 100;                      // byte div
    if (h) { digit(h); digit(r / 10); digit(r % 10); return; }
    si += 2;
    if (r / 10) { digit(r / 10); digit(r % 10); }
    else { si += 2; digit(r % 10); }
}
void digit(u8 d) { or_clip_raw(DIG[d], car[0x165 + si], car[0x163]); si += 2; }   // 3ed7
```

`car_w(n)` = word at car+n; coordinates in the instrument buffer. `DIG` = table DS:3010.
`DASH[7 + pose/2]` resolves to `DS:2FC8 + 2·pose` = inl1 (pose 0), inl2 (2), inl3 (4).

### 4.13 Crash, smoke and messages

```c
void crash_sequence(void) {                          // 3532
    sound_play(DS:549F);
    snapshot_front(); snapshot_mirror(); project_front(); draw_front();
    project_mirror(); draw_mirror();
    select_main_view();
    and_clip_own(DASH.hdcM); or_clip_own(DASH.hdcr);  // damaged hood
    for (s = 0; s < 7; s++) {
        set_deadline(10);
        select_main_view();
        for (k = 0; k < crack_count[s]; k++) {        // lines accumulate in the buffer
            u16 a = crack[s][k].p0, b = crack[s][k].p1;
            draw_line(px(a), py(a), px(b), py(b), 15);
        }
        set_palette(s & 1 ? 0x2E08 : 0x2E10);         // flash on even steps
        wait_deadline();
        draw_mirror(); draw_hud(); present_main_view();
    }
    set_palette(0x2E08);
    gfx_video_hook(); w_536C++;
    delay(60);
}
// point word: lo = x/2, hi = screen y
s16 py(u16 p) { return (s8)((p >> 8) - 0x13); }
s16 px(u16 p) { return (s16)(((py(p) < 0 ? 0xFF00 : 0) | (p & 0xFF)) << 1); }

void engine_smoke_sequence(void) {                   // 3643
    sound_play(DS:549F);
    select_screen();
    di = 0;
    for (n = 10; n; n--) {
        flush_keys(); set_deadline(40);
        if (di < 12) { and_own(ROAD[122 + di/4] /*SMK0-2*/); or_own(ROAD[125 + di/4] /*smk0-2*/); }
        else         copy_own(ROAD[125 + di/4]);      // smk3-5
        and_hot(DASH.mirr, 0xF0, 0x1B);
        di += 4; if (di >= 24) di = 12;
        wait_deadline();
    }
    w_536E++;
}

void message_box(void) {                             // 3788
    select_screen(); set_text_colours(15, 0);
    fill_rect(30, 30, 261, 51, 0);
    draw_frame(33, 33, 287, 77, 0xFFFF);
}
// 36e0: box; print_centered("You missed the gas station", 42); print_centered("Hope you enjoy the walk.", 58);
//       print_centered("and you're out of gas.", 50); tail
// 3713/371f/372b/3737/3743/374f: box; print_centered(msg, 50); tail   (374f only if !last_stage)
// 375f: box; if (lives == 1) text = "Careful, it's your last life!";
//       else { sprintf(DS:2F20, "%d", lives); text = "Lives left: " + number }  → print at 50; tail
// tail (362f): delay(30); wait_after_message();
void wait_after_message(void) {                      // 3f0d
    while (poll_key()) ;
    delay(40);
    if (demo_mode == 0) { flush_keys(); wait_ticks_or_key(1800); }
}
```

Counter side effects: DS:8658 is incremented by 3713 itself and, for result 4, by 1b2c before it
calls 36e0; 371f–3743 and 3532 increment DS:536C; 3643 increments DS:536E.

-----------------------------------------------------------------------------------------------

## 5. File formats (drawing-relevant parts)

### 5.1 `<SCN>n.DAT` (packed, loaded at DS:346A, max 0x1E5E bytes)

Offsets are relative to the file start (DS = 346A + offset). The simulation spec documents the
remaining fields.

| Offset | Size | Field | Used by |
|---|---|---|---|
| 0x000 | 20 | scenery archive name (`CCCRED`, `EC_0`, `TDS2TUNN`…) → `<name>.PES` (DS:9260) | game_flow |
| 0x014 | 128×4 | road records: `r0` flags, `r1` curve (s8, heading += r1·16/256°), `r2` pitch (s8, pitch −= r2/2 per unit), `r3` object 0–20 | 0338 |
| 0x214 | 12 | ? (not read here) | |
| 0x220 | 128 | scenery type per unit (`unit & 0x7F`): −1 none; <80 = sprite type·5 in the scenery archive; ≥30 without sprite → SGN sign `(t−30)/5` | 0d13, 2958 |
| 0x2A0 | 128 | scenery lateral offset (s8, ×W/8 from the road edge; >0 right, ≤0 left) | same |
| 0x320 | 2 | ? | |
| 0x322 | 9×2 | colour words (EGA uses the low nibble): +0x322 left verge, +0x326 right ground, +0x32A shoulders, +0x32E sky, +0x332 far-right band; +0x324/+0x328/+0x32C/+0x330 not used here | 1c8f |
| 0x334 | 8 | ? | |
| 0x33C | 10×8 | band table {u16 start, u16 end, s16 v0, s16 v1} (road offsets from DAT+0x6C9), 0-terminated: width of the right ground band, `v·W/256`, linear from v0 to v1 | 0338 |
| 0x38C | 1 | wide road also widens to the left + left lane line | 0338, 0d13 |
| 0x38D | 1 | tunnel style (≠0 "open") | many |
| 0x38E | 1 | no mountains / clouds | 0919, 26d8 |
| 0x38F | 20 | (0x08 each in CCC) not read here | |
| 0x3A3 | 2 | road length (units) | 0201 |
| 0x3A5 | 2 | stage length | 1c8f |
| 0x3A7 | 2 | pointer (+0x3B33 at load) | sim |
| 0x3A9 | 50×8 | traffic list, oncoming lane {u8 type 1–4, u8 0, u16 position ‰ of the road, u16 0, u16 0} | 1e59 |
| 0x539 | 50×8 | traffic list, own lane | 1e59 |
| 0x6C9 | 30 | (zeros) | |
| 0x6E7 | … | road bytes: bit 7 wide road (4 lanes), bits 0–6 record index | 0338 |

`r0` bits as used by the renderer (they toggle a state `r0_state` on each record that has them):
0x80 tunnel, 0x40 cliff wall left, 0x20 drop-off left (sky below the horizon), 0x08 cliff wall
right, 0x04 drop-off right. Bits 0x10 and 0x02 occur in the data but are not read here.
Shipped values of 0x38C/0x38D/0x38E: CCC1/3/6 `00 00 01`, CCC5 `00 01 01`, EC_0/EC_3 `00 01 00`,
EC_1 `01 00 00`, others 0.

### 5.2 `<SCN>n.SGN` (not packed, loaded at segment DS:940E, offset 0)

```
u16 entry_offset[20]      // 0 = unused; index n from the scenery type
entry:
  +00 u16 width            // scaled by W/512
  +02 u16 height           // scaled by W/512
  +04 u16 char advance     // added to the text x cursor (unscaled font units)
  +06 u16 line step        // added to the text y cursor on '\n'
  +08 u16 text colour      // EGA: low nibble
  +0A u16 ?                // 0xFFFF in CCC0
  +0C u16 board colour     // 0x2222 → 2
  +0E u16 ?                // 0xAAAA
  +10 u16 post colour
  +12 u16 ?
  +14 u16 text x margin    // start x in font units
  +16 u16 text y margin
  +18 u16 post height      // scaled by W/512
  +1A char text[]          // 0-terminated, '\n' = new line; bytes < 10 or ≥ 0x80 end the text
```

The renderer copies 45 words from the entry (text is limited to 64 bytes). Example CCC0 #0:
470×130, "WELCOME TO\nCALIFORNIA".

### 5.3 `<SCN>.FNT` (segment DS:8430)

`u16 glyph_offset[…]` indexed by `(char − 0x20)`, 0 = no glyph. A glyph is a list of strokes
`{u8 x0, u8 y0, u8 x1, u8 y1}` terminated by 0xFF. Coordinates are font units, scaled with
the sign (`(v + margin)·W/512`).

### 5.4 `<CAR>.BIN` fields used here (loaded at DS:23A6)

| Offset | Meaning |
|---|---|
| +0x002 | rpm limit for the needle table |
| +0x020 / +0x022 | gear knob start x, y (gbox buffer) |
| +0x0C3 | HUD digit y; +0x0C5/+0x0C7/+0x0C9 distance digit x (hundreds, tens, ones); +0x0CB/+0x0CD/+0x0CF/+0x0D1 time digit x (m10, m1, s10, s1) |
| +0x0D3 | 61 × {u8 x, u8 y} steering-wheel marker positions (index 0 = full right lock) |
| +0x14D | gauge flags: bit0 speed bar, bit1 speed digits, bit2 rpm bar, bit3 rpm digits (bits 0–1 clear → speed needle, bits 2–3 clear → rpm needle); `== 1` also skips loading the dash digit sprites |
| +0x14F / +0x151 | speed / rpm bar horizontal (0 = vertical) |
| +0x153 / +0x155 | speed / rpm bar input limit |
| +0x157 / +0x159 | speed / rpm bar divisor (byte) |
| +0x15B / +0x15D | speed bar input offset / thickness |
| +0x15F / +0x161 | rpm bar input offset / thickness |
| +0x163 | instrument digit y; +0x165…+0x16F six digit x (3 speed, 3 rpm) |
| +0x175 / +0x177 | speed needle pivot or bar origin |
| +0x179 | speed needle tips {u8 x, u8 y}, index `(u8)(speed·2)/5` |
| +0x249 / +0x24B | rpm needle pivot or bar origin |
| +0x24D | rpm table uses `>>7` instead of `>>6` |
| +0x24F | rpm needle tips, index `min(rpm, limit) >> 6` |

### 5.5 Archives used for drawing

`ROAD`, `COP`, `<car>DASH`, `<opp>ROAD` (opponent seen from behind/front, 8 sizes + brake
lights), `<scn>CAR1-3` (traffic), the scenery archive named in the DAT. Names in §3.5. Resource
case conventions differ per group: for scenery (`sm00`/`SM00`) lower case is the AND mask; for
cliff decorations (`rcka`/`RCKA`) upper case is the mask; cliffs use upper case (`rcfA`) as mask.

-----------------------------------------------------------------------------------------------

## 6. Hardware / DOS dependencies

| Dependency | Where | SDL3 replacement |
|---|---|---|
| EGA planar VRAM (screen descriptor CS:AF54) via the blitter family, GC function select | all screen blits | 320×200 indexed framebuffer, AND/OR/XOR/replace on 4-bit indices |
| RAM 4-plane buffers, direct byte writes to plane segments (`DS:5420..5426`) | 0c17, 0d13/2958 marking pixels | u8 index buffers 320×92, 80×17, inst, gbox; fill = set index |
| `fill_rect` colour = low nibble of the word | 89a2 | use `colour & 15` |
| INT 10h AX=1002h palette | 3532 | swap palette table (flash) |
| INT 16h key poll / flush | 3f0d, 3643 | SDL input |
| PIT 100 Hz tick counter DS:5E8C (installed by 601c / 3f40) | delays, deadlines | 100 Hz fixed timestep counter |
| Timer routine 06c9:403b (simulation) | installed by 3f40 | run simulation ticks, then render |
| Self-modifying code: 06c9:06F9–0712 patches `inc ax`/`dec ax` into 06c9:071F and 06c9:0735 | interp_span | a normal step variable |
| Copy protection: 13a8:0189 writes 0xCB at 06c9:1BF7; the unpatched bytes `clc; mov ax,2; mov es,ax; mov es:[66h],ax` would overwrite the INT 21h vector segment (13a8:0178 writes the trap byte 0xF8 instead). The same routines patch 06c9:424A/4275/42AD (simulation) and DS:5656 | 1b2c exit | port returns normally |
| Sound driver calls 7946/7971/7977 | 1b2c, 3532, 3643 | audio module (platform) |

No CRTC start-address flipping and no vertical-retrace wait exist in this range.

-----------------------------------------------------------------------------------------------

## 7. Timing

* **Per frame** (free-running loop): everything in §1.2, including the dash phase (follows
  `unit_counter` from the simulation), the gear-gate close delay (10 frames), the radar sprite,
  wheel pose and marker, progress dots.
* **Dirty flags** (set by the simulation, cleared here): instruments (2F5B), gear gate (2F5A),
  distance/time digits (2F5C).
* **Per tick** (simulation, 100 Hz PIT, see simulation/platform specs): road position, speed,
  traffic, `time_seconds` (bit 0 blinks the police light bar), `radar_flags`, fall scroll.
* **Delays in ticks**: crash step 10 (×7) then 60; smoke step 40 (×10); message 30 + 40, then up to
  1800 or a key (not in demo mode). At 100 Hz: 0.1 s, 0.6 s, 0.4 s, 0.7 s, 18 s.
* There is **no snapshot race protection** like TD1's full copy: 0201/2089 copy scalar state, but
  traffic list entries are read directly from the simulation's lists. A port should run the
  simulation ticks, then render the frame.
* Projection is recomputed completely every frame (no cache, unlike TD1).

-----------------------------------------------------------------------------------------------

## 8. Differences from Test Drive (1987)

| Topic | TD1 | TD2 |
|---|---|---|
| Road view | 3-plane buffer 320×112, colours 0–7 (+8 on screen) | 4-plane buffer 320×92 at y 19, full 16 colours; mirror in its own 80×17 buffer composited at (240,8) |
| Projection | atan/tan trick per row, 40 rows / 25 mirror rows, change cache | reciprocal tables per row (`k/(i+4)`, `k/(i+6)`), `tan256` integrators, 60 rows / 25 mirror rows, no cache |
| Draw order | objects pushed near→far on the CPU stack, popped far→near | rows iterated far→near directly |
| Scenery | fixed two-colour split, XOR rocks, one cliff sprite | scenery sets from DAT: colours, sky, mountains & clouds with parallax, cliff walls both sides, drop-offs, tunnels (two styles), right-side band, 16 scenery sprite types × 5 sizes placed by DAT tables, cliff decoration sprites, text road signs (SGN + vector FNT) |
| Road | 1 lane each way | wide-road bit (lane lines, widening over 8 units), yellow centre line, white lane lines |
| Objects | signs (7 types), rocks/oil/potholes/gravel | 9 sign types drawn on both sides, cross bands (10/12), gas-station sign or FINISH banner (11), hazards 13–20 |
| Cars | 5 traffic groups × 5 sizes | 3 traffic archives + COP, front/rear × 8 sizes; opponent car (8 sizes, alternate set, brake lights); police brake lights, blinking light bar, parked police car |
| Mirror quirks | sign masks only (type 0 mask) | sign masks only (correct type), no FINISH letters, no cliff decorations |
| Cockpit | wheel XOR 3 poses, dot marker, needle or digital cluster | same scheme, 61-entry marker table in the car BIN, per-car bar/digit/needle mix, radar 6 levels, HUD distance & time, ticket, progress dots |
| Crash | 7 crack steps | 7 crack steps + hood damage sprite + palette flash; new engine-smoke sequence; 8 result messages; lives |
| Reusable from the TD1 port | blitter semantics, gear gate logic, steering pose logic, crash crack idea, message boxes | – |

-----------------------------------------------------------------------------------------------

## 9. Open questions

1. `draw_steering` builds the marker y as `CX` with only `CL` set (`mov cl, dh`); `CH` is whatever
   the previous library call left (the unclipped copy when a save-under exists). The port assumes
   `CH = 0`. Confirm from the platform blitter exit path.
2. `r0` bits 0x10 and 0x02 are not used by the renderer — check the simulation (bridges?).
3. DAT fields 0x214–0x21F, 0x320, 0x324/0x328/0x32C/0x330 (colours for other adapters?),
   0x334, 0x38F–0x3A2 are not read in this range. The CGA/Tandy builds may use the pattern bytes.
4. SGN entry words +0x0A, +0x0E, +0x12 are copied but unused here.
5. `tan256` indices 91–127 read unrelated data; only reachable with extreme pitch sums.
6. The exact tick rate of the counter at DS:5E8C (assumed 100 Hz from the PIT divisor 0x2E9C) and
   whether 403b runs every tick: platform / simulation specs.
7. Which archive/names `S0704` clouds/mountains exist per scenery set is data-driven; the port must
   treat missing optional handles (segment 0) exactly as the original: mountains need `mtn0`,
   clouds need `clo1`, scenery sprites need the lower-case mask; other missing handles are
   dereferenced anyway (e.g. `mtn1` when `mtn0` exists).
8. Traffic list entry byte +1 and word +6 on disk are not read here (the loader overwrites +6).
