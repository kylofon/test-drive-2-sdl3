# Simulation subsystem (TD2EGA `06c9:3f40`–`06c9:5cff`, plus `06b3:0008`)

Target: `work/TD2EGA_unp.exe` (DGROUP `178F`). Everything below was read from the disassembly
(`tools/x86dis.py`, and a recursive-descent listing of `06c9:3ff9`–`5d00` built with
`work/sim/rdis.py` → `work/sim/rdis.txt`). The Ghidra output for this range is unusable (assembly with
jump tables through DS). Constant tables: `work/sim/tables.json`. Data tools: `tools/td2car.py`,
`tools/td2road.py`.

## 1. Overview

The driving simulation is hand-written assembly, like TD1's, but it is **no longer an int 8 handler**.

* The platform timer ISR `06c9:61bf` runs at **100 Hz** (PIT ch0 divisor `0x2E9C`, set by
  `06c9:601c`). On every PIT tick it calls the far routines registered in the 5-slot list DS:5F12
  (`06c9:614c` adds, `06c9:601c` clears), unless DS:5EFE is set. It does `cli` before each call.
* `06c9:3f40 sim_stage_start` (called by `06c9:1c8f`, the stage init, once per stage) resets the stage
  state, then registers two routines: the sound player `06c9:6269` (platform) and
  **`06c9:403b sim_timer_routine`**. `06c9:1b2c` (the stage runner) clears the list with `06c9:601c`
  when the stage ends.
* `sim_timer_routine` loads DS/ES itself. On **every PIT tick** it runs `412c` (rpm needle slew, engine
  and effect tones). On **every 10th tick (10 Hz)** it runs the simulation tick. It also keeps a 1 Hz
  seconds counter.
* The frame loop (`06c9:1b2c`, scene_render) only reads the simulation state and draws it. It leaves
  when `run_state` DS:5490 becomes non-zero, then dispatches on it (§4.20). The random number generator
  is **not** called per frame (unlike TD1). All randomness comes from the tick and the stage setup.

```
PIT 100 Hz -> 06c9:61bf timer ISR -> list: 06c9:6269 sound, 06c9:403b sim_timer_routine
 403b sim_timer_routine
  |-- 412c sound_tick (100 Hz): rpm slew, engine note, rumble, squeal/grind/siren/beep
  `-- every 10th call (10 Hz):
      |-- 1 Hz: clock_seconds++, time limit 30 min
      |-- 420a read_input
      |     |-- 06c9:6620 key/joystick bits, 06c9:6828 bits->direction (platform)
      |     |-- 4281 decode_controls (demo autopilot, auto transmission, shifting)
      |     |     `-- 4612 update_rpm, 4441 clutch_check
      |     |-- 43c3 shift_knob_anim (-> 4612, 4441)
      |     |-- 448a curve_sum
      |     |-- 06b3:0008 steer_update (C)
      |     `-- 06c9:6601 BIOS key -> 44a6 hotkeys (Esc, O, D)
      |-- [fall_mode == 0]
      |   |-- 5880 demo_steer (demo only)          -> 5299, 5c5a, 52fd, 5334, 535b
      |   |-- 44ea engine                            -> 4588 free_rev, 45bf drag_apply, 45fc brake, 4612
      |   |-- 4639 overrev_check
      |   |-- 4674 motion (unit loop)
      |   |     |-- 4afa car_edges (station stop)    per tick and per unit
      |   |     |-- scenery spawn (rand), fuel, cornering grip, lateral motion (13a3:0012 sin)
      |   |     |-- 4b5d median_posts, 4b9a road_edges, 4c85 roadside_hit   -> 4d26 overlap, 4a2e hit
      |   |     `-- next unit: region flags, curve, heading, object handler (table DS:33E6)
      |   `-- [clock_seconds != 0]
      |       |-- 50a1 opponent_ai     -> 5299, 5c5a, 52fd, 5334, 535b
      |       |-- 53a6 police          -> 5446 police_start, 56ed police_drive, 5427 police_reset
      |       |-- 4d3f traffic         -> 4f92 meet_check, 5022 push_behind, (5446)
      |       `-- 595f pass_collisions -> 5a25 pass_check
      `-- [fall_mode != 0] 5a6f fall_anim
```

**Units.**

| Quantity | Globals | Encoding |
|---|---|---|
| Speed | `speed` DS:52CE, `opp_speed` 52D6, `cop_speed` 52DE | u16 8.8, **high byte = mph** |
| Road position | `player_pos` DS:52CA (+ `player_sub` 52C8), `opp_*` 52D2/52D0, `cop_*` 52DA/52D8 | position = **DS address of the road byte** (stream starts at DS:3B51); sub-unit = low byte of the u16 (0..255) |
| Distance | — | 1 road unit = 256 sub-units = 5280/420 ft (12.57 ft, 3.83 m): the results code uses 420 units per mile (`0267:0039`). Each tick adds `3 × mph` sub-units, i.e. 0.1172 units/s per mph (0.4 % off true mph) |
| Lateral position | `player_x` DS:52CC, `opp_x` 52D4, `cop_x` 52DC, traffic `lateral` | **positive = right**. Player car occupies `x-50 .. x+130`, centre `x+40`; start `x = 160`. Lanes: -600, -200 (oncoming), +200, +600 (same direction); road edges ±500, ±900 on wide road, ±400 in narrow sections |
| rpm | `rpm` DS:332C | rpm = `ratio × speed >> 16`, minimum 800 |
| Steering | `steer_angle` DS:2F46 | i16, ±0xE80; 8.8 "degrees" (high byte is fed to `sin_deg`) |
| Heading | `heading` DS:5344 | 1/1024 turn (the backdrop wraps at 0x400) |
| Time | `race_time` DS:331E | tenths of a second (10 Hz ticks); `clock_seconds` DS:942E in seconds |

## 2. Function table

| address | proposed name | signature | purpose | confidence |
|---|---|---|---|---|
| 06c9:3f40 | sim_stage_start | far void() | Stage reset, checksum of look-ahead flags, end-pointer fix-up, registers `6269` and `403b` in the timer list | verified |
| 06c9:3ff9 | sim_restart_reset | far void() | Per-life reset (speed, rpm, damage, clock flag, police) → `5427` | verified |
| 06c9:403b | sim_timer_routine | far void(), sets DS | 100 Hz entry: `412c`, 10 Hz tick, 1 Hz counters | verified |
| 06c9:412c | sound_tick | near | rpm needle slew, engine/rumble/effect divisors | verified |
| 06c9:420a | read_input | near | Controls, idle timeout, hotkeys | verified |
| 06c9:4281 | decode_controls | near | Demo autopilot, auto transmission, steer/throttle, gear selection | verified |
| 06c9:43c3 | shift_knob_anim | near | Knob animation, shift completion | verified |
| 06c9:4441 | clutch_check | near (CX old rpm, DX new rpm) | Downshift lurch, grind tone | verified |
| 06c9:448a | curve_sum | near | Sum of last 8 curve bytes → DS:30E4; speed copy → 30E6 | verified |
| 06c9:44a6 | hotkeys | near (AX key) | Esc / o O / d D | verified |
| 06c9:44bf, 44c5, 44d2 | key_esc, key_gate_mode, key_dash_toggle | near | Hotkey handlers (table DS:33DC) | verified |
| 06c9:44d8, 44de, 44e4 | brake_1600, brake_800, brake_400 | near | `speed -= n` via `45fc` | verified |
| 06c9:44ea | engine | near | Throttle, brake, skid, clutch, torque | verified |
| 06c9:4588 | free_rev | near | rpm decay or free revving (clutch in / neutral) | verified |
| 06c9:45bf | drag_apply | near (DX force) | `speed += force - drag` | verified |
| 06c9:45fc | brake | near (DX amount) | `speed -= DX`, floor 0 → `4612` | verified |
| 06c9:4612 | update_rpm | near → CX old, DX new | rpm from ratio × speed | verified |
| 06c9:4639 | overrev_check | near | Redline counter, blown engine (run_state 3) | verified |
| 06c9:4674 | motion | near | Pull-over, sub-unit step, per-unit loop | verified |
| 06c9:4929 | obj_station_zone | near | Object 0x0A | verified |
| 06c9:4947 | obj_past_station | near | Object 0x0C | verified |
| 06c9:494d | obj_parked_cop | near (BP pos) | Object 0x15 | verified |
| 06c9:495d | obj_roadblock | near (BP pos) | Object 0x16 | verified |
| 06c9:499a | obj_place_roadside | near (BX code×2) | Objects 0x1C–0x2F | verified |
| 06c9:49c9, 49cf, 49d5 | obj_toggle_37f7, obj_toggle_median, obj_toggle_37f8 | near | Objects 0x17, 0x18, 0x19 | verified |
| 06c9:49db, 49e1 | obj_density_up, obj_density_down | near | Objects 0x1A, 0x1B | verified |
| 06c9:49e7 | obj_sign_posts | near | Objects 0x01–0x09 | verified |
| 06c9:4a18 | obj_none | near | Objects 0x00, 0x0B | verified |
| 06c9:4a19 | obj_lane_obstacle | near (BX code×2) | Objects 0x0D–0x14 | verified |
| 06c9:4a2e | hit_object | near | Bump: speed -1600, crash sound, random damage | verified |
| 06c9:4afa | car_edges | near | Car edge positions; station/out-of-gas stop checks | verified |
| 06c9:4b5d | median_posts | near | Posts at ±500/±900 every 16 units | verified |
| 06c9:4b9a | road_edges | near | Walls, drop-offs, shoulder, right-side zones | verified |
| 06c9:4c85 | roadside_hit | near | Scenery object collision | verified |
| 06c9:4d26 | overlap | near (AX centre, BX half width) → ZF | Lateral overlap with the car | verified |
| 06c9:4d3f | traffic | near | Moves both lists; meet/push checks for player, opponent, police | verified |
| 06c9:4f92 | meet_check | near (SI idx, BP list, CX count×8, DX:AX pos:sub, DI x) → ZF=hit | Reaching the next car of a list | verified |
| 06c9:5022 | push_behind | near (SI, DX:AX, DI) | Keeps same-direction cars behind a driver | verified |
| 06c9:50a1 | opponent_ai | near | The duel car | verified |
| 06c9:5299 | ai_road_scan | near (BX pos, DI factor) → BL byte | Lane availability, curve speed limit | verified |
| 06c9:52fd | ai_gap | near (DX self, CX other, AX self mph, BX other mph) → AX | Time-to-reach score, 100 = free | verified |
| 06c9:5334 | ai_lane_min | near (AX gap, BX x) | Keeps the minimum gap per lane | verified |
| 06c9:535b | ai_pick_lane | near (AX own x) → CX target x, DX gap | Lane choice | verified |
| 06c9:53a6 | police | near | Radar trap, chase state machines | verified |
| 06c9:5427 | police_reset | near | Removes the police car | verified |
| 06c9:5446 | police_start | near | Cop appears 26 units behind the player | verified |
| 06c9:54f4 | police_chase_opp | label | State machine DS:33B6 (table DS:3456) | verified |
| 06c9:557a | police_chase_player | label | State machine DS:33B7 (table DS:3446) | verified |
| 06c9:56ed | police_drive | near | Police AI movement (may abort the caller) | verified |
| 06c9:5880 | demo_steer | near | Autopilot lane choice and braking | verified |
| 06c9:595f | pass_collisions | near | Player/opponent/police crossing checks | verified |
| 06c9:5a25 | pass_check | near (SI a, DI b, BX old, DX a.x) → CX new, CF=hit | Sign change of b−a with lateral overlap | verified |
| 06c9:5a6f | fall_anim | near | Car falling off / sinking | verified |
| 06c9:5ada | traffic_resync | far void() | Clears traffic around the player and finds list indices (stage start, after each crash) | verified |
| 06c9:5b5a | resync_list | near | Pushes cars out of the ±60 unit window | verified |
| 06c9:5c30 | nearest_ahead | near (SI list, CX count×8, DX:AX) → SI | Index of the nearest car ahead | verified |
| 06c9:5c5a | at_finish | near (BX pos, DI decel, SI speed) → AL | Braking distance to the finish | verified |
| 06b3:0008 | steer_update | far void() (C) | Steering integration and self-centring | verified |
| 06c9:5c98 | (see scene_render) | far | `7d5e(CS:AF54)` page helper | likely |
| 06c9:5ca6 | (see platform) | far, sets DS | Row-table helper (calls `b0fe`) | likely |

Related functions in other specs: `06c9:1b2c` stage runner, `06c9:1c8f` stage init, `06c9:1e31` restart,
`06c9:1e59` traffic list setup, `06c9:38f2` knob/steering reset, `06c9:3532`… messages (scene_render /
game_flow); `0267:15e4` data loading, `0267:139b` difficulty screen, `0267:0039` results (game_flow);
`06c9:601c`, `614c`, `61bf` timer; `6601`, `6620`, `6686`, `6828` input; `780e` rand8; `7977` queue
sound (platform); `13a3:0012` sin_deg, `13a3:0038` tan_deg (CRT segment, but game tables);
`13a8:002e` copy protection (§4.21).

## 3. Globals table

"sim" = this subsystem. Car fields are listed in §5.1.

| DS | name | type | meaning | written by | read by |
|---|---|---|---|---|---|
| 1DB4 | scenery_sprites | far ptr[] | Stage scenery sprite table (index type×4) | scene_render `1c8f` | 4674, 4c85 |
| 23A6 | car | 0x34F bytes | `<CAR>.BIN` | 0267:15e4 | sim, scene_render |
| 2F46 | steer_angle | i16 | ±0xE80 | 06b3:0008, 4674, 38f2 | 4674, 06b3, 3c3a (wheel) |
| 2F48 | view_yaw | i16 | yaw clamped, >>2, for the renderer | 4674, 38f2 | 0201, 0919, 2089, 26d8 |
| 2F4A | yaw | i16 | car yaw relative to the road, ±0x2800 | 4674, 06b3, 38f2 | 4674, 06b3 |
| 2F4C / 2F4E | knob_x / knob_y | u16 | Gear knob sprite position | 43c3, 38f2 | 3b95 |
| 2F56 | gear | u8 | 0 = neutral, 1..6 | 4281, 5a6f, 38f2 | sim |
| 2F58 | dash_toggle | u8 | D key | 44d2 | 3b95 |
| 2F59 / 2F5A / 2F5B / 2F5C | redraw timers/flags | u8 | gearbox timer (10), gearbox dirty, gauges dirty, clock dirty | sim, 38f2, scene | 3b95, 3cef, 391f |
| 30E4 | curve_sum | i16 | Sum of the last 8 curve bytes | 448a | 06b3 |
| 30E6 | speed_copy | u16 | speed at the time of 448a | 448a | 06b3 |
| 30E8 | ENGINE_NOTE | u16[177] | Divisor per `rpm_display/64` (§7) | const | 412c |
| 330C / 330E | onc_next / same_next | u16 | Player's next car in each traffic list (index × 8) | 4d3f, 5ada, 3f40 | sim |
| 3310 / 3312 | opp_onc_next / opp_same_next | u16 | Same for the opponent | 4d3f, 5ada | sim |
| 3314 / 3316 | cop_onc_next / cop_same_next | u16 | Same for the police car | 4d3f, 5446, 5620 | sim |
| 3318 / 331A | opp_vmax / cop_vmax | u16 8.8 | From difficulty tables | 1c8f | 50a1 / 56ed |
| 331C | opp_crashes | u16 | Opponent crash count | 3f40, 4d3f, 595f | 0267:0039 |
| 331E | race_time | u16 | Player time, tenths | 3f40, 403b | 1b2c, scene |
| 3320 | fuel | u16 | Units left (= length − 10) | 1c8f, 4674 | 4674 |
| 3322 | road_curve | i16 | curve × 64 of the current unit | 3f40, 4674 | 4674, 06b3 |
| 3324 / 3326 | knob_target_x / y | u16 | | 4281 | 43c3 |
| 3328 | gear_ratio | u16 | Ratio of the last engaged gear | 43c3 | 44ea, 4612 |
| 332A | rpm_display | u16 | rpm slewed ±0x60 per 1/100 s | 3ff9, 412c | 412c |
| 332C | rpm | u16 | | 3ff9, 4588, 4612, 4639, 5637 | sim, 3cef |
| 332E | speed_delta | u16 | \|Δspeed\| of the tick (not used) | 403b | 403b |
| 3332 / 3334 / 3336 | car_centre / car_left / car_right | i16 | x+40, x−50, x+130 | 4afa | sim |
| 3338 / 333A | YAW_MIN / YAW_MAX | i16 | −0x2800 / +0x2800 (const) | — | 4674 |
| 333C | grip_limit | i16 | Current skid threshold (signed like steer) | 4674 | 4674 |
| 333E / 3340 / 3342 | lane_gap[3] | u16 | AI gap per lane: left (−400..−1), right (0..399), outer right (400..800) | AI | 535b |
| 3344 | curve_speed_limit | u16 8.8 | AI speed limit for the road ahead | 5299, 5c5a | AI |
| 3346 | tick_count | u16 | 10 Hz counter | 403b | 412c, 53a6, scene |
| 3348 | radar_level | u16 | 0 off, 1 (near) .. 5 | 53a6 | 3a5f (radar lamps) |
| 334A / 334C / 334E | rel_player_opp / rel_player_cop / rel_opp_cop | i16 | Last "ahead/behind" relation (5a25) | 595f, 5446 | 595f |
| 3350 / 335C | siren_pitch / siren_dir | u16 / i8 | Siren sweep | 412c | 412c |
| 3352 | idle_ticks | u16 | Ticks without input | 420a, 4281, 3f40 | 420a |
| 3354 | chase_speed | u16 | Player speed when a chase started (written only) | sim | — |
| 3356 / 3358 | final_time / final_seconds | u16 | Frozen clock on the last stage | 4929 | 403b / — |
| 335A | speed_sq | u16 | speed_mph², shifted >>9 by 06b3 | 4674, 06b3 | 06b3 |
| 335D | curve_ring | i8[8] | Last 8 curve bytes, index (pos+6)&7 | 4674, 3f40 | 448a |
| 3365 / 3366 / 3367 | knob_anim / fire_held / shift_latch | u8 | Shifting state | 4281, 43c3 | sim |
| 3368 / 3369 | div_100hz / div_10hz | u8 | Tick dividers (10) | 403b | 403b, 412c |
| 336A | sound_frame | u8 | 100 Hz counter | 412c | 412c |
| 336B | clock_started | u8 | Set by the first shift | 43c3, 3f40, 3ff9, 1b2c | 403b |
| 336C / 336D | throttle / steer_in | i8 | +1 gas, −1 brake / +1 left, −1 right | 4281, 43c3, 5880 | 44ea, 06b3 |
| 336E | unit_advanced | u8 | A unit was crossed this tick | 4674 | 06b3 (next tick) |
| 336F | skidding | u8 | | 4674, 4b9a | 44ea, 412c |
| 3371 | station_zone | u8 | 0, 1 after object 0x0A, 2 after 0x0C | 49xx, 3f40 | 4afa |
| 3372 / 3373 | opp_braking / cop_braking | u8 | Brake lights | 50a1 / 56ed | 0201 |
| 3374 | siren_on | u8 | Police driving this tick | 53a6, 56ed | 412c |
| 3375 | opp_crash_timer | u8 | Ticks until the opponent restarts | sim | 403b, 0201, 2089 |
| 3376 / 3377 / 3378 | demo_at_finish / opp_at_finish / opp_finished | u8 | | 5880 / 50a1 | |
| 3379 | opp_enabled | u8 | = DS:843E at stage start | 3f40 | sim, scene |
| 337A | scenery_density | u8 | Random roadside object threshold (0x20) | 3f40, 49db, 49e1 | 4674 |
| 337B | damage_hits | u8 | Damaging hits this life (5th → run_state 8) | 3ff9, 4a2e | 4a2e |
| 337C | ROADSIDE_HALFWIDTH | u8[20] | Half width per type/4 | const | 4c85 |
| 3394 / 339D / 33A6 | GEAR_DELTA / STEER_DIR / THROTTLE_DIR | i8[9] | Per joystick direction | const | 4281 |
| 33AF | gate_mode | u8 | O key: joystick direction selects the gate slot | 44c5, 3f40 | 4281 |
| 33B0 / 33B1 | input / input_bits | u8 | direction 0–8 \| fire bits 0x30; raw bits | 420a | 4281, 43c3 |
| 33B2 | grind_timer | u8 | Grind tone ticks | sim | 412c |
| 33B3 | overrev_ticks | u8 | 0..29 | 4639, 3ff9 | 4639 |
| 33B4 / 33B5 | pass_mode / opp_pass_mode | i8 | Always 0 in this build | 4d3f / 50a1 | 4f92, 5022 |
| 33B6 | cop_vs_opp | u8 | 0 or 1–5 (§4.17) | 53a6, 595f, 5427 | sim |
| 33B7 | cop_state | u8 | 0, 1–8 (§4.17) | sim | sim |
| 33B8 | cop_active | u8 | 33B6 \| 33B7 at tick start, 1 after police_start | 53a6, 5446, 595f | sim |
| 33B9 / 33BA | force_meet / cop_force_meet | u8 | Treat every reached car as a collision | 4d3f / sim | 4f92, 5022 |
| 33BB | cop_timer | u8 | | 53a6 | 53a6 |
| 33BC | radar_beep | u8 | Detector beeping this tick | 53a6 | 412c |
| 33BD | lookahead_flags | u8 | Region flags 70 units ahead | 3f40, 4674 | 4674 |
| 33BE | ai_road_byte | u8 | Road byte at the AI car (bit 7 wide) | AI | 535b |
| 33BF | gear_broken | u8[7] | Per gear | 3ff9, 4a2e | 44ea |
| 33C6 | engine_damage | u8 | | 3ff9, 4a2e | 4441, 4a2e |
| 33C8 | suspension_damage | u16 | | 3ff9, 4a2e | 4a2e |
| 33CA | steering_health | u16 | Starts at 250 | 3ff9, 4a2e | 4a2e |
| 33CC | alignment | i16 | | 3ff9, 4a2e | 4a2e |
| 33CE / 33D0 / 33D2 / 33D4 | fall_depth / fall_edge_x / fall_speed / fall_mode | | Fall animation; mode 1 left, 2 right, 4 sinking | 4b9a, 5a6f | 5a6f, 00e7, 1f99 |
| 33D5 | finished | u8 | Last stage finish line crossed | 4929, 3f40 | sim |
| 33D6 | HOTKEY_CHARS | u8[5] | Esc, o, O, d, D | const | 44a6 |
| 33DC / 33E6 / 3446 / 3456 / 3460 | jump tables | u16[] | hotkeys (5, indexed backwards), objects (48), cop_state (8), cop_vs_opp (5), police_drive mode (5) | const | |
| 346A–52C7 | stage | 0x1E5E | `<SCN>n.DAT` image (§5.3) | 0267:15e4 | |
| 368A / 370A | roadside_type / roadside_side | u8[128] / i8[128] | Scenery ring, index = unit counter & 0x7F | 4674, 499a | 4c85, scene |
| 37A6 | right_zones | 8×n | §5.3 | DAT | 4674, 4b9a, scene |
| 37F6 / 37F7 / 37F8 | median / toggle_37f7 / backdrop_off | u8 | Toggled by objects | 49xx | sim, scene |
| 380D / 380F / 3811 | stage_len / finish_unit / stage_end | u16 | end is a DS address after the 3f40 fix-up | DAT, 3f40 | sim |
| 3813 / 39A3 | oncoming / same_dir | 8×50 | Traffic lists {type, pos, sub, x} | DAT, 1e59, sim | sim, scene |
| 52C8 / 52CA / 52CC / 52CE | player sub / pos / x / speed | u16 | | sim, 1c8f, 1e31 | all |
| 52D0 / 52D2 / 52D4 / 52D6 | opp sub / pos / x / speed | u16 | pos = 0 when disabled | 50a1, 1c8f, 595f | |
| 52D8 / 52DA / 52DC / 52DE | cop sub / pos / x / speed | u16 | pos = 0 when no police car | police | |
| 533E | ring_counter | u16 | Units crossed (low 7 bits index the scenery ring) | 4674, 3f40 | 4674, 4b5d, 4c85, scene |
| 5340 / 5342 | stage_len_copy / units_to_finish | u16 | 5342 counts down, min 1 | 1c8f, 4674 | 391f |
| 5344 / 5346 | heading / cloud_scroll | u16 | Backdrop scroll: 5344 += curve>>1 per unit; 5346 += 5/8 of that per unit and +1 per second | sim, 3f40 | 0919, 26d8 |
| 534A–5352 | scene_words | u16 | From DAT 0x322…0x332 | 1c8f | scene |
| 5354 / 5356 | oncoming_count8 / same_count8 | u16 | Entries × 8 | 1e59 | sim, scene |
| 5358 / 535A / 535C / 535E / 5360 | opp accel_mult / min_gap / curve_factor / lat_rate / unused | u16 | Difficulty d | 1c8f | 50a1 |
| 5362 / 5364 / 5366 / 5368 / 536A | police same | u16 | Difficulty min(d+3, 11) | 1c8f | 56ed |
| 536C / 536E / 8658 | failure / … / out_of_gas counts | u16 | game_flow statistics | 1c8f, 37xx | 0267:0039 |
| 5370 | tickets | u16 | Speeding tickets | 1c8f, 560e | 0267:0039 |
| 5372 | opp_time | u16 | Opponent time, tenths | 3f40, 403b | 0267:0039 |
| 5374 / 5376 | player_dist / opp_dist | u16 | Units at stage end, max finish−11 | 1b2c | 0267:0039 |
| 5490 | run_state | i8 | §4.20 | sim, 1e31 | 1b2c |
| 5491 | region_flags | u8 | Current region bits (§5.3) | 4674, 1c8f | sim, scene |
| 5494 / 549F | SND_BUMP / SND_CRASH | song data | `fe 00 fd 0a 00 58 01 00 fa ff`, same with loop 0x32 | const | 7977 |
| 5616 | opp_accel | u16[16] | `<CAR>O.BIN` | 0267:15e4 | 50a1 |
| 5636 | POLICE_ACCEL | u16[16] | = F40O.BIN values | const | 56ed |
| 5656 | protection_failed | u8 | 0x63 until the disk check passes | 13a8 | 019e:06c5 |
| 5FD8 / 5FDA / 5FDC / 5FDE | tone divisors | u16 | engine / effect / (silent) / rumble; 0xFFFF = off | 412c, 1e31 | sound routine (platform) |
| 8424 | lives | u16 | 5 (1 in demo); set to 1 for "game over" events | game_flow, sim | 1b2c |
| 8432 | traffic_speed | u16 | 90 + d×90/11 sub-units per tick (≈30–60 mph) | 0267:139b | 4d3f |
| 843E | opponent_option | u16 | Computer car on | 0267:15e4 | 3f40, 1c8f |
| 8A9A | demo_mode | u16 | 1 = attract demo (autopilot) | game_flow | sim |
| 90A8 | auto_trans | u8 | 1 when difficulty < 4 and not demo | 0267:139b | sim |
| 920C | traffic_keep | u16 | 127 + d×128/11: traffic list thinning | 0267:139b | 1e59 |
| 9258 | escaped | u8 | The police gave up | 56ed | 0267:0039 |
| 9410 | last_stage | u16 | Current stage is the last one | 0267:15e4 | 4929, 374f |
| 940C / 940E | sgn | far ptr | `.SGN` block (segment 0 = none) | 0267:15e4 | 4c85, scene |
| 942E | clock_seconds | u16 | Seconds since the clock started; = race_time at stage end | 3f40, 403b, 1b2c | sim, scene, game_flow |

## 4. Pseudocode

Types `u8/i8/u16/i16/u32`, wrapping at their width. Comparisons are unsigned unless marked `(i16)`
or `(i8)`. `REC(b)` = `&DS[0x347E + (b & 0x7F) * 4]` = {flags, curve, pitch, object}.
`ROAD[p]` = byte at DS address p. `DIFF(p, q)` = high word of the 32-bit subtraction
`(p.pos:p.sub) − (q.pos:q.sub)` (the code does `sub` on the low words, `sbb` on the high words), i.e.
the whole-unit distance, rounded toward −∞. `wrap_up(p)`: `if (p >= stage_end) p -= stage_len`;
`wrap_down(p)`: `if (p < 0x3B51) p += stage_len`. `LEN` = stage_len (DS:380D).

### 4.1 Timer entry `403b` and the tick order

```c
far void sim_timer_routine(void) {          /* called by the 100 Hz timer ISR with IF=0 */
    DS = ES = DGROUP;
    sound_tick();                            /* 412c, every call */
    if (--div_100hz != 0) return;
    div_100hz = 10;
    tick_count++;
    if ((u8)run_state >= 2) return;          /* also 0xFF (quit) */
    if (clock_started) race_time++;
    if (finished) race_time = final_time;
    if (!opp_finished && !opp_crash_timer && race_time != 0) opp_time++;
    if (--div_10hz == 0) {                   /* 1 Hz */
        div_10hz = 10; clock_dirty = 10; cloud_scroll++;
        if (!finished) {
            clock_seconds++;
            if (clock_seconds >= 1800) { lives = 1; run_state = 2; }   /* 30 minute limit = game over */
            if (!clock_started) { div_10hz = 10; clock_seconds--; }
        }
    }
    throttle = 0; steer_in = 0;
    read_input();                            /* 420a */
    if (fall_mode == 0) {
        u16 before = speed;
        if (demo_mode == 1) demo_steer();    /* 5880 */
        engine();                            /* 44ea */
        speed_delta = abs(speed - before);
        overrev_check();                     /* 4639 */
        motion();                            /* 4674 */
        if (clock_seconds == 0) return;      /* nothing else moves before the clock runs */
        opponent_ai();                       /* 50a1 */
        police();                            /* 53a6 (may return early, see 56ed) */
        traffic();                           /* 4d3f */
        pass_collisions();                   /* 595f */
        if (fall_mode == 0) return;
    }
    fall_anim();                             /* 5a6f */
}
```

`clock_seconds` stays 0 until the first shift, so the opponent, police and traffic wait until one
second after the first shift. After a crash `clock_seconds` keeps its value.

### 4.2 `sound_tick` (412c, 100 Hz)

```c
void sound_tick(void) {
    sound_frame++;
    tone_rumble_5FDE = RUMBLE[sound_frame & 0x1F];              /* DS:32AE */
    i16 r = rpm_display, t = rpm;
    if (r <= t) { r += 0x60; if (r >= t) r = t; }               /* signed compares */
    else        { r -= 0x60; if (r <= t) r = t; }
    rpm_display = r;
    tone_engine_5FD8 = ENGINE_NOTE[(u16)r >> 6];                /* word at DS:30E8 + ((r>>5)&~1) */
    if (siren_on) {
        if (clock_seconds & 8) {                                /* wail, 8 s at a time */
            u16 p = siren_pitch;
            if ((i8)siren_dir >= 0) { p += 2; if ((i16)p >= 1800) siren_dir = -1; }
            else                    { p -= 2; if ((i16)p <= 1500) siren_dir = 1; }
            siren_pitch = p; tone_effect_5FDA = p;
        } else tone_effect_5FDA = (tick_count & 4) ? 1500 : 2000;   /* hi-lo */
        return;
    }
    if (radar_beep) { tone_effect_5FDA = 900; return; }
    if (div_100hz == 1) {                     /* once per sim tick: same call, just before it */
        if (grind_timer) { grind_timer--; tone_effect_5FDA = 0x474; }
        else tone_effect_5FDA = 0xFFFF;
    }
    if (skidding) tone_effect_5FDA = 0x8E8;
}
```

`sound_tick` runs before the `dec div_100hz` in `403b`, so `div_100hz == 1` selects the call that
also runs the 10 Hz tick. The sound routine `6269` runs before `403b` in the timer list, so it picks
up these values one PIT tick later.

### 4.3 `read_input` (420a) and `hotkeys` (44a6)

```c
void read_input(void) {
    if (fall_mode == 0) {
        u8 bits = kbd_joy_bits();            /* 06c9:6620: 1 up 2 down 4 right 8 left, 0x10 Space, 0x20 Enter;
                                                keyboard state table, joystick 6686 if no key held */
        input_bits = bits;
        u8 d = DIR_FROM_BITS[bits & 0x0F];   /* 06c9:6828, table DS:629E */
        if (!auto_trans) d |= bits & 0x30;   /* no manual shifting with the automatic */
        input = d;
        if (++idle_ticks > 2400) run_state = 0xFF;          /* 4 minutes without input: quit */
        else if (d) { idle_ticks = 0; if (demo_mode == 1) run_state = 0xFF; }   /* see 4.21 */
        decode_controls();                   /* 4281 */
        if (knob_anim) shift_knob_anim();    /* 43c3 */
        curve_sum();                         /* 448a */
        steer_update();                      /* 06b3:0008 */
    }
    u16 key = bios_key();                    /* 06c9:6601: int 16h, hotkeys via 06c9:6528 */
    if (key && demo_mode == 1) run_state = 0xFF;             /* see 4.21 */
    hotkeys(key);
}
void hotkeys(u16 key) {                      /* scan DS:33DA downwards over 5 bytes (std; repne scasb) */
    switch ((u8)key) {
    case 0x1B: run_state = 0xFF; break;                        /* 44bf */
    case 'o': case 'O': if (!auto_trans) gate_mode ^= 1; break;  /* 44c5 */
    case 'd': case 'D': dash_toggle ^= 1; break;               /* 44d2 */
    }
}
void curve_sum(void) {                       /* 448a */
    i16 s = 0; for (int i = 0; i < 8; i++) s += (i8)curve_ring[i];
    curve_sum_30E4 = s; speed_copy_30E6 = speed;
}
```

Keyboard input is a **held-key state** (int 9 table, platform), not BIOS typematic as in TD1. Only
Esc/O/D (and the platform hotkeys) go through the BIOS buffer.

Tables (index = direction 0–8: 0 none, 1 up, 2 up-right, 3 right, 4 down-right, 5 down, 6 down-left,
7 left, 8 up-left):

| | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| GEAR_DELTA DS:3394 | 0 | +1 | +1 | 0 | −1 | −1 | −1 | 0 | +1 |
| STEER_DIR DS:339D | 0 | 0 | −1 | −1 | −1 | 0 | +1 | +1 | +1 |
| THROTTLE_DIR DS:33A6 | 0 | +1 | +1 | 0 | −1 | −1 | −1 | 0 | +1 |

DIR_FROM_BITS DS:629E = `0 1 5 0 3 2 4 3 7 8 6 7 0 1 5 0`.

### 4.4 `decode_controls` (4281)

```c
void decode_controls(void) {
    u8 anim = knob_anim, held = fire_held, al = input, d;
    u16 r = rpm;
    if (finished) {                                   /* last stage, past the line: brake, steer only */
        d = al & 0x0F;
        steer_in = STEER_DIR[d];
        al = 5;
        goto automatic;                               /* also with the manual gearbox */
    }
    if (demo_mode == 1) {                             /* branch patched at run time, see 4.21 */
        idle_ticks = 0; al = 1; gearbox_timer = 10;
        if (!anim) {
            if (r > car.rpm_redline) al = 0x11;       /* upshift */
            else if (r > car.rpm_downshift) ;
            else if (gear > 1) al = 0x15;             /* downshift */
        }
    }
    d = al & 0x0F;                                    /* BX (BH = 0) */
    steer_in = STEER_DIR[d];
    if ((i8)THROTTLE_DIR[d] < 0) throttle = THROTTLE_DIR[d];     /* brake at once */
    if (auto_trans) {
automatic:                                            /* finished path: d = joystick direction, al = 5 */
        if (!anim) {
            if (r >= car.rpm_upshift) { if (gear != car.num_gears) { al = 0x11; d = 1; } }
            else if (gear > 1 && r <= car.rpm_downshift) { al = 0x15; d = 5; }
        }
    }
    if (!(al & 0x30) && held && !anim) {              /* fire released after the knob arrived */
        fire_held = 0;
        u16 old, new; update_rpm(&old, &new);         /* 4612 */
        clutch_check(old, new);                       /* 4441, CX/DX: see Q3 */
        return;
    }
    if (!(al & 0x30)) {
        shift_latch = 0;
        if (!held) throttle = THROTTLE_DIR[d];
        return;
    }
    fire_held = 1; gearbox_dirty = 1; gearbox_timer = 10;
    u8 latch = 0, g, k;
    if (demo_mode != 1 && gate_mode && run_state == 0) {  /* gate shifting */
        if (d == 0) goto done;
        latch = 1;
        k = car.gate_slot[d] + 7;                     /* BX = d */
        g = car.gate_gear[d];
    } else {                                          /* sequential shifting */
        i8 dg = GEAR_DELTA[d];
        if (dg == 0) goto done;
        g = gear + dg;
        if (g > car.num_gears) goto done;             /* unsigned: 0-1 fails too */
        latch = 1;
        if (shift_latch == 1) goto done;              /* one shift per press */
        k = g;
    }
    gear = g;                                         /* the gear changes before the knob moves */
    knob_target_x = car.knob_xy[k].x; knob_target_y = car.knob_xy[k].y;
    knob_anim = latch;                                /* = 1 */
done:
    shift_latch = latch;
}
```

Notes:
* The automatic sets `d` to 1 or 5 (`mov bl` with BH already 0), so its shift request goes through
  the sequential path (`gate_mode` is cleared by 3f40 when `auto_trans`, and the finished path uses
  the sequential path too unless gate mode is on and `run_state` is 0). When the automatic does not
  shift, the no-fire path uses the joystick direction for the throttle.
* A new shift may start while the knob is still moving: the target is simply replaced.
* During a shift (`knob_anim` or `fire_held`) the direction does not change the throttle.

### 4.5 `shift_knob_anim` (43c3), `update_rpm` (4612), `clutch_check` (4441)

```c
void shift_knob_anim(void) {
    gearbox_dirty = 1; clock_started = 1;             /* the clock starts at the first shift */
    i16 x = knob_x, y = knob_y, ny = car.knob_xy[0].y;
    if (x == knob_target_x) { if (y < knob_target_y) y += 6; else if (y > knob_target_y) y -= 6; }
    else if (y == ny)       x += (x < knob_target_x) ? 6 : -6;
    else                    y += (y > ny) ? -6 : 6;          /* back to the neutral row first */
    knob_x = x; knob_y = y;
    if (x != knob_target_x || y != knob_target_y || (input & 0x30)) return;   /* wait for fire release */
    knob_anim = 0; fire_held = 0;                     /* written from BH = y>>8, which is 0 */
    throttle = 1;                                     /* this tick accelerates */
    if (gear == 0) return;
    gear_ratio = car.gear_ratio[gear];
    u16 old, new; update_rpm(&old, &new);
    clutch_check(old, new);
}
void update_rpm(u16 *old, u16 *new) {                 /* 4612: returns CX=old, DX=new */
    if (gear == 0) return;                            /* CX, DX unchanged (Q3) */
    *old = rpm; gauges_dirty = 1;
    u16 r = ((u32)gear_ratio * speed) >> 16;
    if (r < 800) r = 800;
    rpm = r; *new = r;
}
void clutch_check(u16 old, u16 new) {                 /* 4441 */
    u16 up = new - old;
    if ((i16)old <= (i16)new) {                       /* rpm rose: downshift */
        if (up < 2700 || gear == 0) return;
        grind_timer = 3;
        speed_hi = (u8)(speed_hi - 5);                /* high byte of DS:52CE, wraps */
        return;
    }
    u16 drop = old - new;                             /* upshift */
    if (drop < 3000) return;
    u8 e = car.engine_strength - engine_damage; if (borrow) e = 0;
    if ((u16)e * (gear_ratio >> 8) < 7000) return;
    grind_timer = drop >> 8;                          /* sound only */
}
```

### 4.6 `steer_update` (06b3:0008, C)

```c
void steer_update(void) {
    speed_sq >>= 9;                                   /* u16; 0 unless a unit was crossed last tick */
    i16 target = -(((i16)((u8)curve_sum_30E4 << 8)) >> 5) - (yaw >> 2);
    i16 delta = (i8)steer_in * 120;
    if (steer_in == 0 && unit_advanced && road_curve == 0 &&
        abs(steer_angle) < 0x600 && abs(yaw) < 0xC00) {          /* self-centring on straights */
        yaw -= yaw >> 3;
        steer_angle -= steer_angle >> 2;
        if (abs(steer_angle) < 0x100) steer_angle = 0;           /* sign taken from the subtraction */
        return;
    }
    if (unit_advanced && steer_in == 0 && steer_angle != 0)
        delta -= (i16)((u16)(steer_angle >> 7) * speed_sq);      /* low 16 bits */
    if ((i8)steer_in > 0 && target > steer_angle) delta -= (steer_angle - target) >> 3;
    if ((i8)steer_in < 0 && target < steer_angle) delta -= (steer_angle - target) >> 3;
    i32 k = 256 - (speed_copy_30E6 >> 10);                       /* 256 - mph/4 */
    delta = (i16)(((i32)delta * k) >> 8);                        /* bytes 1-2 of the 32-bit product */
    if (delta > 0xA00) delta = 0xA00; if (delta < -0xA00) delta = -0xA00;
    steer_angle += delta;
    if (steer_angle > 0xE80) steer_angle = 0xE80; if (steer_angle < -0xE80) steer_angle = -0xE80;
}
```

`unit_advanced` and `speed_sq` come from the **previous** tick's motion step. Only the low byte of
`curve_sum` is used (as a signed byte ×8).

### 4.7 `engine` (44ea) and helpers

```c
void engine(void) {
    if (finished) { brake(1600); return; }
    i8 t = throttle;
    if (t < 0)    { brake(1600); return; }            /* 44d8 */
    if (skidding) { brake(800);  return; }            /* 44de */
    if (knob_anim || fire_held || gear == 0) {        /* clutch in or neutral */
        free_rev();
        if ((i8)throttle < 0) { brake(1600); return; }   /* dead: t >= 0 here */
        drag_apply(0);
        return;
    }
    if (t == 0) { grind_timer = 0; return; }          /* in gear, off throttle: speed held, no drag */
    if (gear_broken[gear]) { brake(400); return; }    /* 44e4 */
    if (cop_state != 8 && cop_state >= 2) return;     /* being pulled over */
    gauges_dirty = 1;
    u16 i = (u16)(rpm << 1) >> 8; if (i >= 0x50) i = 0x50;
    u16 f = ((u16)car.torque[i] * (u8)(gear_ratio >> 8)) >> 5;
    if (skidding) f >>= 1;                            /* dead */
    drag_apply(f);
    update_rpm(0, 0);
}
void free_rev(void) {                                 /* 4588 */
    if (gear == 0 && (i8)throttle > 0) { gauges_dirty = 1; rpm += 600; return; }   /* no limit here */
    i16 r = rpm - 200; if (r <= 800) r = 800;         /* signed */
    if ((u16)r != rpm) { rpm = r; gauges_dirty = 1; }
}
void drag_apply(u16 f) {                              /* 45bf */
    if (throttle == -1) { brake(f); return; }         /* 45fc with DX=f; dead in practice */
    u16 dr = DRAG[speed_hi >> 2];                     /* DS:324A, 64 bytes */
    if (f == 0) dr <<= 1;
    i16 dv = f - dr;
    if (dv == 0) return;
    u16 s = speed;
    if (dv < 0) { if (s < (u16)-dv) return; s -= -dv; }   /* would go below 0: speed unchanged */
    else s += dv;                                          /* wraps at 0xFFFF */
    speed = s; gauges_dirty = 1;
}
void brake(u16 n) {                                   /* 45fc */
    u16 s = (speed < n) ? 0 : speed - n;
    if (s == speed) return;
    speed = s; update_rpm(0, 0);
}
```

DRAG (u8, index speed_mph/4): `0 0 0 0 0 1 1 2 2 3 4 5 6 7 8 10 11 13 14 16 18 20 22 24 26 28 30 33 35
38 40 43 46 49 52 55 58 62 65 69 72 76 80 84 88 92 96 100 104 109 113 118 122 127 132 137 142 147
152 158 163 169 174 180`. Below 20 mph there is no drag, so a car in neutral coasts forever.

Acceleration per tick (8.8 mph) = `torque[rpm/128] × ratio_hi / 32 − drag`. At 10 Hz, 256 = 1 mph/tick
= 10 mph/s. Brake: 1600/256 = 6.25 mph per tick; skid 3.1; broken gear 1.6.

### 4.8 `overrev_check` (4639)

```c
void overrev_check(void) {
    i8 c = overrev_ticks;
    if (rpm < car.rpm_redline) { if (--c >= 0) overrev_ticks = c; return; }
    if (rpm <= car.rpm_max && ++c < 30) { overrev_ticks = c; return; }
    if (rpm >= car.rpm_max) rpm = car.rpm_max;
    run_state = 3;                                    /* blown engine */
}
```

### 4.9 `motion` (4674)

```c
void motion(void) {
    if (cop_state != 8 && cop_state >= 2) {           /* pull over to x = 160 at 20 per tick */
        i16 x = player_x;
        if (x > 160) { x -= 20; if (x <= 160) x = 160; }
        else if (x < 160) { x += 20; if (x >= 160) x = 160; }
        player_x = x;
    }
    car_edges();                                      /* 4afa */
    skidding = 0; unit_advanced = 0;
    u16 acc = speed_hi * 3 + player_sub;
    for (;;) {
        if ((u8)run_state >= 2) return;
        player_sub = acc;
        if ((acc >> 8) == 0) return;
        /* ---- one road unit ---- */
        lookahead_flags ^= REC(ROAD[player_pos + 0x47])->flags;   /* region state 70 units ahead */
        unit_advanced = 1;
        u8 r = rand8();
        u8 slot = (++ring_counter_533E + 0x46) & 0x7F;
        if (r < scenery_density && spawn_scenery(slot)) ; else {
            roadside_type[slot] = 0xFF; roadside_side[slot] = 0xFF;
        }
        if (--fuel == 0) run_state = 4;               /* out of gas */
        if (--units_to_finish == 0) units_to_finish = 1;
        /* cornering grip */
        i16 st = steer_angle;
        u16 v2 = (u16)speed_hi * speed_hi;  speed_sq = v2;
        u32 g = car.grip; u16 lim = (u16)g;
        if ((u16)((g >> 16) << 1) < v2) {             /* division fits (also skips v2 == 0) */
            lim = g / v2;
            if (st >= 0) { if (st > (i16)lim) skidding = 1; }
            else { lim = -lim; if (st < (i16)lim) skidding = 1; }
        }
        grip_limit = lim;
        /* yaw */
        i16 c = road_curve;
        if (demo_mode == 1) { yaw = 0; steer_angle = -c; }        /* view_yaw keeps its old value */
        else {
            i16 add = skidding ? (i16)(-st + lim + 2 * lim) >> 1 : st;
            yaw = view_yaw = yaw + c + add;
        }
        view_yaw = clamp(view_yaw, YAW_MIN, YAW_MAX);             /* ±0x2800, see note */
        yaw      = clamp(yaw, YAW_MIN, YAW_MAX);
        view_yaw >>= 2;
        if (cop_state != 8 && cop_state >= 2) { steer_angle = 0; view_yaw = 0; yaw = 0; }
        i8 a = (i8)((u16)(yaw << 1) >> 8);
        player_x -= (i8)((sin_deg(a) * 36) >> 8);    /* 13a3:0012, result's low byte sign-extended */
        car_edges();                                  /* 4afa */
        median_posts();                               /* 4b5d */
        road_edges();                                 /* 4b9a */
        roadside_hit();                               /* 4c85 */
        /* advance */
        u8 b = ROAD[++player_pos];
        const u8 *rec = REC(b);
        region_flags = ((region_flags & 0xFE) | (b >> 7)) ^ rec[0];
        road_curve = (i16)((u16)(i8)rec[1] << 8) >> 2;          /* curve × 64 */
        i16 h = (i8)rec[1] >> 1;
        heading += h;
        cloud_scroll += h + (h >> 2);
        curve_ring[(player_pos + 6) & 7] = rec[1];               /* 8-bit address */
        u8 ob = REC(ROAD[player_pos + 1])->object;               /* BP = player_pos */
        OBJECT_HANDLER[ob]();                                    /* DS:33E6, 48 entries */
        acc = player_sub - 0x100;
    }
}
```

Note on the clamp (4828–4862): `v > max → max`, otherwise `v < min → min`, signed.
`view_yaw` is only assigned in the non-demo branch, so in demo mode the clamp and shift apply to the
previous value.

`sin_deg` (`13a3:0012`, AL = signed degrees): `|a| > 90 → 180−|a|`, result `SIN[|a|]` (DS:54AA,
sin×256, 91 words), negated for negative `a`. `tan_deg` (`13a3:0038`, no folding, table DS:5560) is
used by the renderer only.

Scenery spawn (inside the unit loop, `4713`–`477f`):

```c
bool spawn_scenery(u8 slot) {
    u8 r = rand8() & 0x0F;
    if (r == 0x0F || r == 7) return false;
    i8 side = r - 7;                                  /* -7..-1, 1..7 */
    if (side > 0) {                                   /* right side */
        if (lookahead_flags & 0x8C) return false;
        u16 u = player_pos - 0x3AED;                  /* unit + 100 */
        for (Zone *z = right_zones; z->start; z++)    /* sorted */
            if (u <= z->end) { if (u >= z->start) return false; break; }
    } else if (lookahead_flags & 0xE0) return false;
    roadside_side[slot] = side;
    u8 k; do k = rand8() & 7; while (k >= 6);
    roadside_type[slot] = k * 5;
    return scenery_sprites[k * 5] != 0;               /* far ptr at DS:1DB4 + k*5*4 */
}
```

The object is placed 70 units ahead (`slot` = counter + 0x46). The ring index of the current unit is
`ring_counter & 0x7F` (used by 4c85 and the renderer).

### 4.10 Object handlers (table DS:33E6, `BP` = player_pos, `BX` = code × 2)

| code | handler | effect |
|---|---|---|
| 0x00, 0x0B | 4a18 | none |
| 0x01–0x09 | 49e7 | signs: posts at x = −400 (−800 if wide and median) and +400 (+800 if wide), half width 5 → `hit_object` |
| 0x0A | 4929 | `station_zone = 1`; on the last stage also `final_time = race_time`, `final_seconds = clock_seconds`, `finished = 1` |
| 0x0C | 4947 | `station_zone = 2` |
| 0x0D–0x14 | 4a19 | obstacle at x = +200 (−200 for odd codes), half width 7 → `hit_object` |
| 0x15 | 494d | if no police car: `cop_pos = BP + 80` (parked cop / radar trap, `cop_state` stays 0) |
| 0x16 | 495d | if no police car and `speed > 0x3200` (50 mph): `chase_speed = speed; cop_pos = BP + 60; cop_speed = 0; cop_state = 8; cop_x = (ROAD[cop_pos] & 0x80) ? 800 : 400` |
| 0x17 | 49c9 | DS:37F7 ^= 1 (renderer) |
| 0x18 | 49cf | `median` DS:37F6 ^= 1 |
| 0x19 | 49d5 | DS:37F8 ^= 1 (renderer: backdrop off) |
| 0x1A / 0x1B | 49db / 49e1 | `scenery_density += 0x10` / `-= 0x10` (u8, wraps: EC_4 has 80 × 0x1A) |
| 0x1C–0x2F | 499a | `slot = (ring_counter + 0x45) & 0x7F; roadside_type[slot] = (code − 0x16) × 5; roadside_side[slot] = SIDE[code]` (DS:37DD + code) |

```c
void hit_object(void) {                               /* 4a2e */
    brake(1600);
    queue_sound(SND_BUMP);                            /* 06c9:7977(DS:5494) */
    i8 r = rand8();
    if (r <= 0) return;                               /* 0 or >= 0x80: no damage (50 %) */
    if (demo_mode != 0) return;
    if (++damage_hits > 4) { run_state = 8; return; } /* "Car took too much damage" */
    if (r <= 25) {                                    /* engine */
        u8 a = engine_damage + 25; engine_damage += a;           /* = 2*old + 25 */
        if ((u8)(a << 1) >= car.engine_strength) run_state = 5;
    } else if (r <= 50) {                             /* suspension */
        u16 a = suspension_damage + 1000; suspension_damage += a;
        if ((u16)(a << 1) >= (u16)car.grip) run_state = 6;
    } else if (r <= 75) {                             /* steering */
        steering_health -= 75;
        if (steering_health < 125) run_state = 7;
    } else if (r <= 100) {                            /* alignment */
        if ((i16)alignment >= 0 && (r & 1)) { alignment += 37; if ((i16)alignment >= 62) run_state = 7; }
        else { alignment -= 37; if ((i16)alignment <= -62) run_state = 7; }
    } else if (!auto_trans) gear_broken[gear] = 1;
}
```

The damage values only feed these thresholds (and `engine_damage` feeds `clutch_check`); they do not
change handling. All of them reset with each life (`3ff9`).

### 4.11 Car edges and road edges (4afa, 4b5d, 4b9a, 4c85, 4d26)

```c
void car_edges(void) {                                /* 4afa */
    i16 c = player_x + 40;
    car_centre = c; car_left = c - 90; car_right = c + 90;   /* x-50 .. x+130 */
    if (station_zone == 0) return;
    if (station_zone == 1) {
        if (finished) { if (speed_hi <= 5) run_state = 1; return; }
        if (c >= 600) player_x = 560;
    }
    if (speed_hi > 5) return;
    if (station_zone == 2) { run_state = 4; return; }                 /* stopped past the station */
    run_state = (c < 100) ? 9 : 1;                                    /* "too far left" / stage done */
}
bool overlap(i16 centre, i16 half) {                  /* 4d26: ZF=1 when overlapping */
    return !(centre - half > car_right) && (centre + half >= car_left);
}
void median_posts(void) {                             /* 4b5d */
    if (((u8)(ring_counter - 1) & 0x0F) != 0) return;
    i16 a = (region_flags & 1 && median) ? -900 : -500;
    if (overlap(a, 5)) { hit_object(); return; }
    a = (region_flags & 1) ? 900 : 500;
    if (overlap(a, 5)) hit_object();
}
void road_edges(void) {                               /* 4b9a */
    u8 f = region_flags; i16 e;
    if (car_centre >= 0) {                            /* right */
        e = (f & 0x80) ? 400 : (f & 1) ? 900 : 500;
        if (car_right <= e) return;
        if ((f & 0x80) || (!(f & 0x04) && (f & 0x02))) { player_x = e - 130; run_state = 2; return; }
        if (f & 0x04) { fall_mode = 2; start_fall(e + 70); return; }
        goto zones;
    } else {                                          /* left */
        e = (f & 0x80) ? -400 : (f & 1) ? -900 : -500;
        if (car_left >= e) return;
        if ((f & 0x80) || (!(f & 0x20) && (f & 0x10))) { player_x = e + 50; run_state = 2; return; }
        if (f & 0x20) { fall_mode = 1; start_fall(e - 150); return; }
    }
zones:                                                /* 4c34, both sides */
    for (Zone *z = right_zones; z->start; z++) {
        u16 u = player_pos - 0x3B33;                  /* unit + 30 */
        if (u > z->end) continue;
        if (u < z->start) break;
        i16 w = (i16)(z->b - z->a) * (i16)(u - z->start) / (i16)(z->end - z->start) + z->a;
        e += 2 * w;
        if (car_left >= e) { fall_mode = 4; start_fall(e); return; }   /* sinking */
        break;
    }
    brake(1000);                                      /* shoulder: 3.9 mph per unit crossed */
}
void start_fall(i16 edge) {                           /* 4be1 */
    fall_edge_x = edge; fall_speed = 0; fall_depth = 0; grind_timer = 0; skidding = 0;
}
void roadside_hit(void) {                             /* 4c85 */
    u8 i = ring_counter & 0x7F;
    i8 t = roadside_type[i]; u16 half;
    if (t < 0) return;
    if (t < 0x50 && scenery_sprites[t]) half = ROADSIDE_HALFWIDTH[t >> 2];   /* DS:337C */
    else {
        if (t < 0x1E || sgn_seg == 0) return;
        u16 off = SGN[((t - 0x1E) / 5) * 2];          /* ES = DS:940E */
        if (off == 0) return;
        half = SGN[off] >> 1;                         /* sign width / 2 */
    }
    i16 x = (i8)roadside_side[i] * 50;
    x += (x >= 0) ? 500 : -500;
    if (region_flags & 1) { if (x >= 0) x += 400; else if (median) x -= 400; }
    if (!overlap(x, half)) return;
    hit_object();
    if (BP >= 20) run_state = 2;                      /* big objects crash the car */
}
```

`BP` is the type only on the sprite path (`4c9c mov bp, ax`). On the `.SGN` path it is stale: the
rpm (set in `4281`) on the first unit of a tick, the zone length when `road_edges` went through the
zone loop, otherwise the previous road position. All of these are ≥ 20 in practice, so hitting a
billboard is a crash. Port: `crash = sprite_path ? t >= 20 : true`.

ROADSIDE_HALFWIDTH (index type/4) = `5 5 10 10 0 30 30 100 100 …` (types 0, 5 → 5; 10, 15 → 10;
20, 25 → 30; 30+ → 100).

Zones: the loop compares the right-side edge (`e` = +500/+900, or the left one on the left side,
where the result can never trigger because `car_left < e` there). With no zone the shoulder is
unlimited and only slows the car down.

### 4.12 `fall_anim` (5a6f)

```c
void fall_anim(void) {
    gear = 0; grind_timer = 0;
    free_rev(); brake(1600);
    if (fall_mode == 1) { player_x -= 25; if (player_x < fall_edge_x) goto fall; return; }
    if (fall_mode == 4) { fall_depth += 3; if (fall_depth >= 100) run_state = 2; return; }
    player_x += 25; if (player_x <= fall_edge_x) return;
fall:
    fall_depth += fall_speed; fall_speed += 2;
    if (fall_depth >= 280) run_state = 2;
}
```

### 4.13 Traffic (4d3f)

Traffic lists (DS:3813 oncoming, DS:39A3 same direction) hold {type, pos, sub, x}. Types 1–3 are the
scenery's cars (`<SCN>CAR1..3`), 4 is a police car; same-direction entries get +4 at load (5–8).
`1e59` converts the per-mille positions to addresses, sets x = −200 / +200 and drops some entries
(from the 4th entry on, each entry is removed if `rand8() <= (u8)-traffic_keep`, i.e. about 50 % at
difficulty 0 and 1 % at 11; the list is shifted down and the same slot is tested again).
The lists are ring-ordered by position; `onc_next` DS:330C / `same_next` DS:330E (and 3310/3312 for
the opponent, 3314/3316 for the police) index the next car each driver will meet.

```c
void traffic(void) {
    for (i = 0; i != oncoming_count8; i += 8) {       /* towards the player */
        Car *e = &ONC[i/8];
        u16 s = e->sub - traffic_speed; u16 p = e->pos;
        if (borrow) { s += 0x100; p--; wrap_down(p); }          /* `inc ch` */
        e->sub = s; e->pos = p;
        i16 x = e->x;
        if (e->type != 6 && (ROAD[p - 8] & 0x80) && median) { x -= 20; if (x <= -600) x = -600; }
        else { x += 20; if (x >= -200) x = -200; }
        e->x = x;
    }
    for (i = 0; i != same_count8; i += 8) {
        Car *e = &SAME[i/8];
        u16 s = e->sub + traffic_speed; u16 p = e->pos;
        if (s >> 8) { s -= 0x100; p++; wrap_up(p); }
        e->sub = s; e->pos = p;
        i16 x = e->x;
        if (e->type != 6 && (ROAD[p] & 0x80)) { x += 20; if (x >= 600) x = 600; }
        else { x -= 20; if (x <= 200) x = 200; }
        e->x = x;
    }
    pass_mode = 0; force_meet = 0;
    /* player */
    u16 old = onc_next;
    bool hit = meet_check(&onc_next, ONC, oncoming_count8, player, car_centre);
    if (old != onc_next) {
        Car *e = &ONC[prev(onc_next)];                /* the car just met */
        if (e->type == 4 && cop_pos == 0 && speed_hi > 70) {
            chase_speed = speed; cop_state = 1; police_start();
        }
    }
    if (hit) run_state = 2;
    if (cop_state == 7) force_meet = 1;
    push_behind(&same_next, player, car_centre);
    force_meet = 0;
    if (meet_check(&same_next, SAME, same_count8, player, car_centre)) run_state = 2;
    /* opponent */
    if (opp_enabled) {
        pass_mode = opp_pass_mode;                    /* 0 */
        if (meet_check(&opp_onc_next, ONC, ..., opp, opp_x) && !opp_crash_timer) { opp_crash_timer = 30; opp_crashes++; }
        push_behind(&opp_same_next, opp, opp_x);
        if (meet_check(&opp_same_next, SAME, ..., opp, opp_x) && !opp_crash_timer) { opp_crash_timer = 30; opp_crashes++; }
    }
    /* police: pushes cars, never crashes */
    if (cop_active) {
        pass_mode = 0;
        meet_check(&cop_onc_next, ONC, ..., cop, cop_x);
        force_meet = cop_force_meet;
        push_behind(&cop_same_next, cop, cop_x);
        meet_check(&cop_same_next, SAME, ..., cop, cop_x);
    }
}

bool meet_check(u16 *idx, Car *list, u16 n8, Pos d, i16 dx) {    /* 4f92, result ZF */
    Car *e = &list[*idx/8];
    i16 k = DIFF(e, d); if (k > 0) k -= LEN;          /* ahead: not yet */
    if (k < -4) return false;
    if (!force_meet) {
        if ((i8)pass_mode > 0) goto pass;
        if (e->x < dx - 180 || e->x > dx + 180) goto pass;
    }
    /* collision: shove this car and the ones right behind it in front of the driver */
    u16 p = d.pos + 1; wrap_up(p); u16 j = *idx;
    do {
        list[j/8].sub = d.sub; list[j/8].pos = p;
        p += 3; wrap_up(p);
        j = next(j);                                  /* +8, 0 at n8 */
        if (j == *idx) break;
        k = DIFF(&list[j/8], (Pos){p, d.sub}); if (k >= 0) k -= LEN;
    } while (k >= -4);
    return true;                                      /* *idx unchanged */
pass:
    *idx = next(*idx);
    return false;
}

void push_behind(u16 *idx, Pos d, i16 dx) {           /* 5022: same-direction cars can't drive through you */
    u16 save = *idx, j = *idx; int n = 0; i16 k;
    for (;;) {
        j = prev(j);
        k = DIFF(&SAME[j/8], d); if (k >= 0) k -= LEN;
        if (k < -3) break;
        if (n == 0) {
            if ((i8)pass_mode < 0) break;
            if (!force_meet && (SAME[j/8].x < dx - 180 || SAME[j/8].x > dx + 180)) break;
        }
        d.pos -= 3; wrap_down(d.pos);
        SAME[j/8].sub = d.sub; SAME[j/8].pos = d.pos;
        n++;
    }
    j = save;
    if (n == 0 && (i16)(k + LEN) <= 1) j = prev(j);   /* the car behind is the next one again */
    *idx = j;
}
```

`next(j)`: `j += 8; if (j == n8) j = 0`. `prev(j)`: `if (j == 0) j = n8; j -= 8`. In `meet_check`
the subtraction in the loop compares with the running `p`, as written. Type 6 (a same-direction type-2
car) never changes lanes.

### 4.14 `traffic_resync` (5ada, far, from 1b2c after every (re)start)

```c
far void traffic_resync(void) {
    resync_list(same_next, SAME, same_count8);
    resync_list(onc_next, ONC, oncoming_count8);
    same_next = nearest_ahead(SAME, same_count8, player);
    onc_next  = nearest_ahead(ONC, oncoming_count8, player);
    if (opp_enabled) { opp_same_next = nearest_ahead(SAME, ..., opp); opp_onc_next = nearest_ahead(ONC, ..., opp); }
}
void resync_list(u16 i, Car *L, u16 n8) {             /* 5b5a */
    u16 i0 = i; Pos p = player;
    i16 k = DIFF(&L[i/8], p); if (k < 0) k += LEN;
    if ((u16)k <= 60) {                               /* move cars within 60 ahead to +61, +64, ... */
        p.pos += 61; wrap_up(p.pos);
        do { L[i/8].sub = p.sub; L[i/8].pos = p.pos; p.pos += 3; wrap_up(p.pos);
             i = next(i); if (i == i0) break;
             k = DIFF(&L[i/8], p); if (k > 0) k -= LEN; } while (k >= -62);
    }
    p = player; i = prev(i0);
    k = DIFF(&L[i/8], p); if (k > 0) k -= LEN;
    if (k < -10) return;
    p.pos -= 10; wrap_down(p.pos);                    /* cars within 10 behind go to -10, -13, ... */
    do { L[i/8].sub = p.sub; L[i/8].pos = p.pos; p.pos -= 3; wrap_down(p.pos);
         i = prev(i); if (i == i0) break;
         k = DIFF(&L[i/8], p); if (k < 0) k += LEN; } while (k <= 30);
}
u16 nearest_ahead(Car *L, u16 n8, Pos p) {            /* 5c30: min (DIFF mod LEN), unsigned, first wins */
    u16 best = LEN, bi = 0;
    for (u16 i = 0; i < n8; i += 8) { i16 k = DIFF(&L[i/8], p); if (k < 0) k += LEN;
                                      if ((u16)k <= best) { bi = i; best = k; } }
    return bi;
}
```

(`nearest_ahead` uses `jbe`, so on ties the last entry wins.)

### 4.15 Opponent AI (50a1) and shared AI helpers

```c
void opponent_ai(void) {
    lane_gap[1] = 100;
    if (!opp_enabled) { opp_pos = 0; return; }
    if (opp_crash_timer) {
        if (--opp_crash_timer) return;
        i16 k = DIFF(opp, player);
        opp_x = (k < 4 && k > -4) ? -200 : 200;       /* restart in the left lane next to the player */
        opp_speed = 0;
        return;
    }
    ai_road_byte = ai_road_scan(opp_pos, opp_curve_factor);
    opp_at_finish = at_finish(opp_pos, (opp_vmax >> 8) * 4, opp_speed);
    lane_gap[0] = ai_gap(opp_pos, ONC[opp_onc_next].pos, opp_speed_hi, -50);
    u16 g = ai_gap(opp_pos, SAME[opp_same_next].pos, opp_speed_hi, 50);
    if (!opp_at_finish) ai_lane_min(g, SAME[opp_same_next].x);
    g = ai_gap(opp_pos, player_pos, opp_speed_hi, speed_hi);
    if (!opp_at_finish) ai_lane_min(g, car_centre);
    if (cop_vs_opp || cop_state) {
        g = ai_gap(opp_pos, cop_pos, opp_speed_hi, cop_speed_hi);
        if (!opp_at_finish) ai_lane_min(g, cop_x);
    }
    u16 gap; i16 target = ai_pick_lane(opp_x, &gap);
    if (cop_vs_opp >= 2) target = 200;
    if (opp_at_finish) target = 1000;
    u16 v = opp_speed, vmax = opp_vmax;
    if (cop_vs_opp >= 2 || v >= curve_speed_limit || gap < opp_min_gap) {
        opp_braking = 1;
        if (v < (vmax >> 8) * 4) { v = 0; if (opp_at_finish) opp_finished = 1; }
        else v -= (vmax >> 8) * 4;
    } else {
        opp_braking = 0;
        u16 a = (u16)(((u32)opp_accel[(v >> 11) & 0x1E] * opp_accel_mult) >> 16) >> 1;   /* index is a byte offset */
        u8 dr = DRAG[(v >> 8) >> 2];
        a = (a < dr) ? 0 : a - dr;
        v += a; if (v >= vmax) v = vmax;
    }
    opp_speed = v;
    u16 st = (v >> 8) * 3 + opp_sub;
    opp_sub = (opp_sub & 0xFF00) | (u8)st;            /* only the low byte is written */
    opp_pos += st >> 8;                               /* no wrap */
    opp_pass_mode = 0;
    i16 x = opp_x;
    if (x > target) { x -= opp_lat_rate; if (x <= target) x = target; }
    else if (x < target) { x += opp_lat_rate; if (x >= target) x = target; }
    opp_x = x;
}

u8 ai_road_scan(u16 pos, u16 factor) {                /* 5299 */
    u8 b = ROAD[pos];
    lane_gap[1] = 100; lane_gap[2] = (b & 0x80) ? 100 : 0;    /* outer lane only on wide road */
    u8 m = 0;
    for (int i = 0; i < 4; i++, pos += 10) {
        u8 c = REC(ROAD[pos])->curve;
        c = -c;                    /* always: the sign test uses the flags of the preceding shl (Q5) */
        if (c > m) m = c;          /* unsigned */
    }
    if ((i8)m < 0) m = -m;
    curve_speed_limit = (u8)CURVE_SPEED[m] * (u8)factor;       /* DS:32EE words, low bytes only */
    return b;                      /* BL */
}
u16 ai_gap(u16 self, u16 other, u16 v_self, u16 v_other) {     /* 52fd */
    i16 d = other - self;
    if (d <= 0) return (d < -2) ? 100 : 90;
    if (d > 60) return 100;
    if (d < 3) return 1;
    i16 cl = v_self - v_other;
    if (cl < 0) return 100;
    u8 c = ((cl + 5) >> 8) ? 0xFF : (u8)(cl + 5);
    if ((u8)(d >> 1) >= c) return 100;
    return (u8)(((u16)d << 7) / c);
}
void ai_lane_min(u16 g, i16 x) {                      /* 5334 */
    int s;
    if (x < -400) return;
    if (x < 0) s = 0; else if (x < 400) s = 1; else if (x <= 800) s = 2; else return;
    if ((i16)g < (i16)lane_gap[s]) lane_gap[s] = g;
}
i16 ai_pick_lane(i16 own_x, u16 *gap) {               /* 535b: CX = target, DX = gap */
    u16 g = lane_gap[0]; i16 t = -200;
    if ((i16)g <= (i16)lane_gap[1]) { g = lane_gap[1]; t = 200; }
    if ((ai_road_byte & 0x80) && (i16)g < (i16)lane_gap[2]) t = 600;
    if (own_x < -40)       *gap = lane_gap[0];
    else if (own_x <= 40)  *gap = 100;
    else if (own_x > 440)  *gap = lane_gap[2];
    else if (own_x < 360)  *gap = 100;
    else                   *gap = lane_gap[1];
    return t;
}
u8 at_finish(u16 pos, u16 decel, u16 v) {             /* 5c5a */
    u16 fin = finish_unit + 0x3B42;                   /* 15 units before the finish */
    if (pos < fin) {
        u16 v2 = ((u32)v * v) >> 16;
        u16 dist = (u16)(((u32)v2 * 3) / decel) >> 1;
        if (fin - pos > dist) return 0;
    }
    curve_speed_limit = 0;
    return 1;
}
```

CURVE_SPEED (DS:32EE, index |curve|): `255 ×9, 242, 196, 162, 136, 116, 100, 0`; index 15+ would
read the variables at DS:330E (no shipped curve exceeds 14).

The opponent restarts in place after a crash (`opp_crash_timer` ticks later). It pulls to x = 1000 at
the finish, brakes to a stop and sets `opp_finished`, which stops its clock `opp_time`.

### 4.16 Pass collisions (595f, 5a25)

```c
void pass_collisions(void) {
    i16 cx = <CX on entry>;                            /* see Q6 */
    if (opp_enabled) {
        i16 old = rel_player_opp;
        bool hit = pass_check(player, opp, old, car_centre, &cx);
        rel_player_opp = cx;
        if (hit) {
            if (old >= 0) { run_state = 2; opp_crash_timer = 10; opp_crashes++; }   /* you hit it from behind */
            else opp_speed = speed;                                                /* it hit you */
            return;
        }
    }
    if (!cop_active) return;
    if (pass_check(player, cop, rel_player_cop, car_centre, &cx)) {
        rel_player_cop = cx;
        if (cx >= 0) { lives = 1; run_state = 2; return; }                         /* rammed the police */
        cop_pos -= 2; cop_speed = speed;                                           /* police hit you */
        cop_state = 1; cop_active = 1; cop_force_meet = 0;
        return;
    }
    rel_player_cop = cx;
    if (!opp_enabled) return;
    if (pass_check(opp, cop, rel_opp_cop, opp_x, &cx)) {
        rel_opp_cop = cx;
        if (cx >= 0) { opp_crash_timer = 30; opp_crashes++; return; }
        cop_pos -= 2; cop_speed = opp_speed + 0x500;
        cop_vs_opp = 1; cop_active = 1; cop_force_meet = 0;
        return;
    }
    rel_opp_cop = cx;
}
bool pass_check(A a, B b, i16 old, i16 ax_, i16 *cx) {         /* 5a25, CF */
    if (a.pos == 0 || b.pos == 0) return false;   /* CX left unchanged (register garbage, Q6) */
    *cx = DIFF(b, a) - 1;                         /* >= 0: b is at least one unit ahead */
    if ((old ^ *cx) >= 0) return false;
    if (b.x < ax_ - 180 || b.x > ax_ + 180) return false;   /* passed side by side */
    if (old >= 0) { b.pos = a.pos + 1; *cx = 1; } else { b.pos = a.pos - 1; *cx = -1; }
    b.sub = a.sub;
    return true;
}
```

In the player/opponent case the test on the handler side is `old` (BX), not the new `cx`; in the two
police cases it is `cx` (+1 when `b` was ahead, i.e. `a` ran into `b`).

### 4.17 Police (53a6, 5446, 557a, 56ed)

There is at most one police car (`cop_pos != 0`). It is created by object 0x15 (parked, 80 units
ahead), object 0x16 (roadblock, 60 ahead, `cop_state = 8`), by meeting an oncoming traffic car of
type 4 above 70 mph, or by a collision.

```c
void police(void) {
    radar_beep = 0; siren_on = 0; radar_level = 0;
    cop_active = cop_vs_opp | cop_state;
    if (cop_pos == 0) return;
    if (cop_vs_opp) { police_chase_opp(); return; }
    if (cop_state)  { police_chase_player(); return; }
    /* parked cop ahead: radar trap */
    i16 d = DIFF(cop, player);
    if (d < 0) { police_reset(); return; }            /* passed without being caught */
    if (tick_count & 4) { radar_beep = 1; radar_level = min((d >> 4) + 1, 5); }
    if (d > 16) return;
    if (speed < opp_speed) {                          /* the opponent is the faster one */
        if (opp_speed_hi <= 50) return;
        cop_vs_opp = 1; police_start(); return;
    }
    if (speed_hi <= 50) return;
    chase_speed = speed; cop_state = 1; police_start();
}
void police_reset(void) { cop_pos = 0; cop_vs_opp = cop_state = cop_active = cop_force_meet = 0; }
void police_start(void) {                             /* 5446 */
    rel_player_cop = -100; cop_active = 1;
    Pos s = player; s.pos -= 26;                      /* no wrap */
    rel_opp_cop = -DIFF(opp, s);
    cop_same_next = first index after walking back from same_next while 0 <= DIFF(SAME[j], s) < 26;
    cop_onc_next  = same walk over ONC from onc_next;
    cop_speed = 0x3200; cop_x = 200; cop = s; cop_force_meet = 0;
}
void police_chase_player(void) {                      /* 557a, table DS:3446 */
    if (cop_state < 6) police_drive();                /* may return from police() directly */
    i16 d = DIFF(cop, player); if (d < 0) d += LEN;
    switch (cop_state) {
    case 1: if (d <= 300) { cop_state = 2; cop_force_meet = 1; } break;   /* cop has caught up */
    case 2: if (d >= 10) cop_state = 3; break;
    case 3:                                                              /* 55be: hold 10 ahead */
        if (d >= 10) {
            cop.sub = player_sub; cop_pos = player_pos + 10;             /* no wrap; `SI += 8` is dead code */
            if (speed == 0) { cop_speed = 0; goto stop; }
        }
        if (cop_speed != 0) break;
    stop:
        speed = 0; cop_state = 4; cop_timer = 20;                        /* both stopped */
        break;
    case 4: if (--cop_timer == 0) cop_state = 5; break;                  /* 2 s */
    case 5: cop_speed += 0x400;
            if (d >= 60) { tickets++; police_reset(); } break;
    case 6: if (--cop_timer == 0) { cop_state = 5; cop_same_next = same_next; cop_onc_next = onc_next; }
            break;
    case 7: if (tick_count & 4) { radar_beep = 1; radar_level = 1; }
            speed_hi = 30; update_rpm(0, 0); gauges_dirty = 1;             /* rolled up to the cop at 30 mph */
            if (d <= 2) { cop_timer = 30; cop_state = 6; speed = 0; rpm = 800; }
            break;
    case 8: if (tick_count & 4) { radar_beep = 1; radar_level = 1; }
            if (d <= 300 && d > 2) { if (speed < 0x1E00) cop_state = 7; break; }   /* slowed below 30 mph */
            if (cop_x - 180 <= car_centre && car_centre <= cop_x + 180) {          /* 56a3: hit the roadblock */
                cop.sub = player_sub; cop_pos = player_pos + 2; wrap_up(cop_pos);
                lives = 1; run_state = 2;
            } else { cop_state = 1; chase_speed = speed; police_start(); }         /* drove past */
            break;
    }
}
```

The opponent machine (`54f4`, DS:33B6, table DS:3456) runs states 1–5 the same way against `opp`,
with `police_drive` every tick. Differences: state 3 (`5531`) pins the police car 10 ahead of the
opponent and goes to state 4 as soon as `cop_speed == 0` (no player-speed test, `opp_speed` is not
forced to 0; the opponent brakes by itself while `cop_vs_opp >= 2`); state 5 (`556c`) resets without
a ticket. `d` is `DIFF(cop, opp)` (+LEN when negative).

```c
void police_drive(void) {                              /* 56ed */
    siren_on = 1;
    ai_road_byte = ai_road_scan(cop_pos, cop_curve_factor);
    lane_gap[0] = ai_gap(cop_pos, ONC[cop_onc_next].pos, cop_speed_hi, -50);
    u16 g = ai_gap(cop_pos, SAME[cop_same_next].pos, cop_speed_hi, 50);
    if (SAME[cop_same_next].x <= 400) lane_gap[1] = g; else lane_gap[2] = g;   /* stored, not min */
    ai_lane_min(ai_gap(cop_pos, player_pos, cop_speed_hi, speed_hi), car_centre);
    if (opp_enabled) ai_lane_min(ai_gap(cop_pos, opp_pos, cop_speed_hi, opp_speed_hi), opp_x);
    u16 gap; i16 target = ai_pick_lane(cop_x, &gap);
    u8 m = cop_active;                                 /* 1..5 here */
    if (m >= 2 && m != 5) target = 200;
    u16 v = cop_speed, vmax = cop_vmax;
    switch (m) {                                       /* table DS:3460 */
    case 1: if (v >= curve_speed_limit || gap < cop_min_gap) goto brake; goto accel;
    case 2: case 5: goto accel;
    case 3: case 4: goto brake;
    }
brake: cop_braking = 1; v = (v < (vmax >> 8) * 4) ? 0 : v - (vmax >> 8) * 4; goto store;
accel: cop_braking = 0;
       v += (u16)(((u32)POLICE_ACCEL[(v >> 11) & 0x1E] * cop_accel_mult) >> 16) >> 1;   /* no drag */
       if (v >= vmax) v = vmax;
store:
    cop_speed = v;
    u16 st = (v >> 8) * 3 + cop_sub; cop_sub = (cop_sub & 0xFF00) | (u8)st; cop_pos += st >> 8;
    if (cop_state) {
        i16 d = DIFF(cop, player);
        if (d >= 300) d -= LEN;
        if (d <= -300) d += LEN;
        if (d < -100) {                               /* the police gave up */
            escaped = 1; police_reset();
            return_from_police();                     /* `pop ax; ret`: back into 403b after `call 53a6` */
        }
    }
    i16 x = cop_x;                                    /* slew to target at cop_lat_rate */
    ...same as the opponent...
    cop_x = x;
}
```

While `cop_state` is 2–7 the player's throttle is ignored (§4.7), steering and yaw are zeroed and the
car is pulled to x = 160 (§4.9). Speed is not reduced by the engine code (no drag in that path): the
player can still brake, and state 3 forces `speed = 0` when the police car stops. State 8 does not
restrict the player.

Summary of police outcomes: stopping for a roadblock (below 30 mph within 300 units, then rolling to
it) or being pulled over costs time and a ticket (`tickets`, reported by game_flow's results). Ramming the
police car from behind, or passing a roadblock on its lane, sets `lives = 1` → game over. Staying 100+
units ahead of a chasing police car sets `escaped`.

### 4.18 `demo_steer` (5880, demo mode only)

```c
void demo_steer(void) {
    lane_gap[1] = 100;
    ai_road_byte = ai_road_scan(player_pos, 0xFF);
    demo_at_finish = at_finish(player_pos, 1600, speed);
    lane_gap[0] = ai_gap(player_pos, ONC[onc_next].pos, speed_hi, -50);
    u16 g = ai_gap(player_pos, SAME[same_next].pos, speed_hi, 50);
    if (!demo_at_finish) ai_lane_min(g, SAME[same_next].x);
    u16 gap; i16 target = ai_pick_lane(player_x + 40, &gap);
    if (cop_state >= 2 || demo_at_finish) target = 200;
    if (cop_state >= 2) throttle = -1;
    else if (speed >= curve_speed_limit) {
        throttle = (gap < 20 || speed - curve_speed_limit >= 1600 || curve_speed_limit == 0) ? -1 : 0;
    } else if (gap < 20) throttle = -1;
    i16 c = player_x + 40;                            /* slew the centre by 44 per tick */
    if (c > target) { c -= 44; if (c <= target) c = target; }
    else if (c < target) { c += 44; if (c >= target) c = target; }
    player_x = c - 40;
}
```

### 4.19 Resets

`sim_stage_start` (3f40): `curve_ring[8] = 0; heading = cloud_scroll = 0; road_curve = 0;
clock_seconds = 0; opp_crashes = 0; opp_time = 0; race_time = 0; clock_started = 0; station_zone = 0;
ring_counter = 0; onc_next = same_next = opp_onc_next = opp_same_next = 0; idle_ticks = 0;
cop_vs_opp = cop_state = 0; radar_beep = 0; siren_on = 0; opp_crash_timer = 0; cop_sub = cop_pos = 0;
opp_speed = 0; demo_at_finish = opp_at_finish = opp_finished = 0; finished = 0;
if (auto_trans) gate_mode = 0; opp_enabled = opponent_option; scenery_density = 0x20;
lookahead_flags = XOR of REC(ROAD[0x3B51 + i]).flags for i = 0..0x46; stage_end += 0x3B33;`
then `timer_clear(); timer_add(06c9:6269); timer_add(06c9:403b)`.

`sim_restart_reset` (3ff9): `knob_anim = shift_latch = 0; speed = 0; rpm = 0; rpm_display = 0;
clock_started = 0; grind_timer = 0; damage_hits = 0; overrev_ticks = 0; gear_broken[0..6] = 0;
engine_damage = 0; suspension_damage = 0; alignment = 0; steering_health = 250; run_state = 0;
fall_mode = 0; police_reset();`

Callers (scene_render/game_flow, for reference): `1c8f` (stage init) sets `heading = 0;
region_flags = 0; units_to_finish = finish_unit; stage_len_copy = LEN; fuel = LEN − 10;
player_pos = opp_pos = 0x3B51 (opp_pos = 0 without opponent); player_sub = opp_sub = 0;
opp_x = −200; opp_speed = 0`, loads the difficulty parameters (§5.4) and calls 3f40. `1e31`
(every life) calls 3ff9, then `player_x = 160; run_state = 0; tone slots 5FD8/5FDA/5FDC = 0xFFFF`,
and `38f2` (`gear = 0; steer_angle = view_yaw = yaw = 0; knob = car.knob_xy[0]`). The road position is
kept after a crash. `1b2c` then calls `traffic_resync`.

### 4.20 Frame loop exit (`1b2c`, for reference)

`run_state` DS:5490 values and the stage runner's reaction (jump table DS:2302):

| value | set by | meaning | 1b2c |
|---|---|---|---|
| 0 | | driving | loop |
| 1 | 4afa | stopped at the gas station (or finished the last stage) | "Fill 'er up…" unless last stage; stage ends |
| 2 | many | crash (also: time limit, rammed police, roadblock → with `lives = 1`) | crash sequence `3532`, `lives--`, 0 → game over, else restart (`1e31`, position kept) |
| 3 | 4639 | blown engine | `3643`, `lives--`, restart |
| 4 | 4674, 4afa | out of gas | "and you're out of gas…", out-of-gas count, `lives--`, stage ends |
| 5 / 6 / 7 / 8 | 4a2e | engine lost power / suspension gone / steering shot / too much damage | message, failure count DS:536C, `lives--`, restart |
| 9 | 4afa | stopped too far left of the pump | message, out-of-gas count, `lives--`, stage ends |
| 0xFF | 420a, 44bf | quit (Esc, demo input, 4 min idle) | leave immediately |

On leaving, `1b2c` stores `player_dist = min(player_pos − 0x3B51, finish_unit − 11)`, the same for the
opponent, and `clock_seconds = race_time`.

### 4.21 Copy protection patches (`13a8:002e`, called from `0000:0907`)

The disk check (int 11h, then sector reads, as in TD1) patches three branch opcodes in this code:

| byte | as shipped (check failed) | after a successful check (`[13a8:03D2]` = 0x75) |
|---|---|---|
| `06c9:424A` | `76` jbe: input never quits | `75` jne: joystick/keypad input quits the **demo** |
| `06c9:4275` | `76` jbe | `75` jne: a BIOS key quits the demo |
| `06c9:42AD` | `77` ja: **autopilot for everyone with demo_mode ≤ 1** | `75` jne: autopilot only in the demo |

It also writes `06c9:1BF7` (`retf` on success, `clc` on failure, which makes `1b2c` fall into code
that overwrites the int 19h vector) and DS:5656 (0 / 0x63, checked by `019e:06c5`). The pseudocode in
this spec uses the patched (successful) behaviour, which the port must implement: `demo_mode == 1`
everywhere. The shipped bytes make an unprotected copy drive itself at full throttle without steering.

## 5. File formats

### 5.1 `<CAR>.BIN` (0x34F bytes → DS:23A6)

Loaded by `0267:15e4`: `06c9:6d18` (raw file into memory) and `06c9:5d01(src, DS:23A6, 0x34F)`.
CAMA.BIN is 896 bytes; the extra 49 bytes (disk junk, "1200 N81N") are never copied.
`tools/td2car.py` → `work/cars/<CAR>.json`.

| off | type | field | used by |
|---|---|---|---|
| +000 | u8 | num_gears (+001 unused) | 4281 |
| +002 | u16 | rpm_max: above it the engine blows at once; rpm clamped to it | 4639, 3cef |
| +004 | u16 | rpm_redline: over-rev counter zone (30 ticks); demo upshift | 4639, 4281 |
| +006 | u16 | rpm_upshift (automatic) | 4281 |
| +008 | u16 | rpm_downshift (automatic, demo) | 4281 |
| +00A | u16 | unused | — |
| +00C | u32 | grip: skid when \|steer\| > grip / mph²; low word = suspension damage limit | 4674, 4a2e |
| +010 | u16 | unused | — |
| +012 | u16[7] | gear ratios, index = gear (0 unused) | 43c3 |
| +020 | {u16 x, y}[16] | knob positions: 0–6 per gear (0 = neutral, its y is the neutral row), 7–15 gate slots | 4281, 43c3, 38f2 |
| +060 | u8[9] | gate slot per joystick direction (knob index − 7) | 4281 |
| +069 | u8[9] | gear per joystick direction in gate mode | 4281 |
| +072 | u8 | engine_strength (equals the peak torque in 9 of 12 cars): engine damage limit and clutch check | 4a2e, 4441 |
| +073 | u8[81] | torque by rpm/128 (index clamped to 80; [80] is also the low byte of +0C3) | 44ea |
| +0C3 | u16, u16[7] | roof clock digit y and x positions | scene_render 391f |
| +0D3… | | wheel frames and cockpit data | scene_render 3c3a, 2477 |
| +14D | u16 | gauge style bits (1, 2, 4, 8; VETT = 2 digital) | scene_render 3cef, 37d0 |
| +14F–+34E | | gauge geometry: pivots +175/+177 and +249/+24B, needle tables +179 and +24F, digital data | scene_render 3cef, 3ed7, 2542, 268a, 1f99 |

Summary (`tools/td2car.py`):

```
car   size  g rpmMax   redl     up   down      grip  eng  ratios 1..N                   vmax*    peakTq dash
F40    847  5  10800   8700   7800   4500  16247914  233  36900 23000 16400 12800 10200   218  233@3968    0
P959   847  6  10200   8300   7400   4500  16247914  175  56000 32960 22560 16640 12960 10240   207  175@5120    0
CAMA   896  4   8000   7200   6500   3000  12600000  110  29736 22184 17228 11800         156  110@5888    0
DODG   847  4   8000   7100   6200   3000  12600000  215  31005 22581 16146 11700         155  105@5248    0
GOAT   847  4   8000   7100   6100   3000  12600000  150  35200 24800 18880 15520         117  100@5376    0
GT50   847  4   7500   6600   6000   3000  12600000  140  27840 20280 15480 12000         140  105@5120    0
STNG   847  4   7000   6400   6000   3000  12600000  184  24640 18368 14672 11200         146  115@4864    0
VETT   847  6   8700   7400   6700   3600  16073206  122  32964 22140 16113 12300  9225  6027   314  122@4992    2
ROSS   847  5   8400   7000   6400   3500  15199662  115  34540 22110 16830 12870  9680   185  115@4480    0
COUN   847  5   9000   7800   7300   3700  15374371  136  33673 24462 16459 12986 10721   186  136@4608    0
LOTU   847  5   8800   7400   6700   3600  14326118   78  47040 28700 19320 14420 11480   165   78@3968    0
RUF    847  5   8400   7300   6600   3600  15199662  169  37530 21600 15120 11205  8505   219  169@4736    0
* vmax = mph at the redline in top gear, ignoring drag
```

### 5.2 `<CAR>O.BIN` (0x20 bytes → DS:5616)

Loaded by `0267:15e4` only when the computer opponent is on (DS:843E). 16 × u16: opponent
acceleration by speed band, index `(speed >> 11) & 0x1E` as a byte offset (8 mph bands), used as
`accel = ((entry × accel_mult) >> 16) >> 1` 8.8 mph per tick, minus drag (§4.15). Trailing zeros
mean no more acceleration (the difficulty vmax applies anyway). The police car uses a built-in table
DS:5636 equal to F40O.BIN, without drag.

### 5.3 `<SCN>n.DAT` (packed; image of DS:346A–52C7)

Loaded by `0267:15e4`: `06c9:6d50` (packed file loader, FORMATS.md "Packed files") and
`06c9:5d01(src, DS:346A, 0x1E5E)`. The file name is `<SCN><'0'+stage>.dat`. Unpacked sizes are
3180–6285 bytes. `tools/td2road.py` → `work/roads/<SCN><n>.json` and `.png`.

| off | DS | type | field |
|---|---|---|---|
| 0x000 | 346A | char[20] | scenery archive name (`CCCRED`, `TDS2DEST`, …) |
| 0x014 | 347E | {u8 flags, i8 curve, i8 pitch, u8 object}[128] | road records, index = road byte & 0x7F |
| 0x214 | 367E | u8[12] | unused (0) |
| 0x220 | 368A | u8[128] | roadside ring types (initial; 0xFF none) |
| 0x2A0 | 370A | i8[128] | roadside ring sides |
| 0x320 | 378A | u16[10] | five (a, b) pairs; b → DS:534A, 534C, 534E, 5350, 5352 (scene_render) |
| 0x334 | 379E | u16[4] | read by the results code `0267:0039` (e.g. 30, 150, 110, 80) |
| 0x33C | 37A6 | {u16 start, u16 end, i16 a, i16 b}[10] | right-side zones, 0-terminated, units + 30, sorted |
| 0x38C | 37F6 | u8[3] | toggles median / 37F7 / 37F8 (initial) |
| 0x38F | 37F9 | i8[20] | side for objects 0x1C–0x2F |
| 0x3A3 | 380D | u16 | stream length (units) |
| 0x3A5 | 380F | u16 | finish unit (= length − 201 in all files) |
| 0x3A7 | 3811 | u16 | stream end − 0x3B33 (= length + 30); 3f40 adds 0x3B33 |
| 0x3A9 | 3813 | {u16 type, u16 pos, u16 sub, i16 x}[50] | oncoming traffic; type low byte 0 ends; pos in per mille of the length |
| 0x539 | 39A3 | same | same-direction traffic |
| 0x6C9 | 3B33 | u8[30] | unused |
| 0x6E7 | 3B51 | u8[length + 71] | road stream + 71 bytes of look-ahead padding (+2 zero/0xFF bytes) |

Road byte: bit 7 = wide road (two lanes each way; edges ±900); low 7 bits = record index.

Record flags are **toggles**: the region state is the running XOR (`region_flags` DS:5491, with bit 0
replaced by the byte's bit 7). Bits:

| bit | meaning (from 4b9a, spawn masks) |
|---|---|
| 0x01 | (never in records) wide road, from bit 7 |
| 0x02 / 0x10 | barrier on the right / left: crash when the car passes the edge |
| 0x04 / 0x20 | drop-off right / left (tested before the barrier): the car falls |
| 0x08 / 0x40 | no random scenery on the right / left |
| 0x80 | narrow section: edges ±400 and they are walls (tunnels; bridges combine it with 0x24 and 0x12) |

All stages use the same record numbering: 1–8 right curves 1, 2, 4, 6, 8, 10, 12, 14; 9–15 left
curves (−1, −2, −4 …); 0x16–0x1D pitch ±24/32/48/64; 25–31 the seven flag bits; 32+ objects;
54/55 = flags 0x24 / 0x12. Curve: `road_curve = curve × 64`, `heading += curve >> 1` (1/1024 turn).
Pitch is a **vertical curvature** used only by the renderer (`06c9:21c3`: slope += −pitch/2 per
row); the data is not balanced, so no absolute elevation exists.

Objects: §4.10. Every stage has a 113–114-unit wide section starting 52–53 units before the finish unit, and
the station objects at fixed places: 0x0A at finish − 23, 0x0B at finish − 12, 0x0C at finish − 1
(record positions; a handler runs one unit earlier, when the player reaches the unit before). The
stopping zone is therefore about 22 units (280 ft) long. The last stage of each scenery (CCC6, EC_5,
TDS25) has 0x0A and 0x0B at finish − 22/− 21 and no 0x0C: there 0x0A is the finish line.

Zones (`a`, `b` interpolated over the interval): the right road limit becomes `edge + 2 × value`;
beyond it the car sinks (fall mode 4). Random right-side scenery is suppressed in the zones.

Stage summary (`tools/td2road.py`):

```
stage   archive    units finish  miles  onc  same zones  wide  heading  sgn
CCC0    CCCRED      2751   2550   6.55   13    11     0   114   -120.2  yes
CCC1    CCCRED      1718   1517   4.09   11    16     4   114    196.9  yes
CCC2    CCCRED      2341   2140   5.57   13    14     0   114    -24.6  yes
CCC3    CCCFRISC    2402   2201   5.72   18    25     5   657    426.8  yes
CCC4    CCCRED      2902   2701   6.91   41    41     7   114    180.4  yes
CCC5    CCCSOUT     3253   3052   7.75   38    33     3   139    325.2  yes
CCC6    CCCSOUTH    2254   2053   5.37   30    27     5   255    -52.7  yes
EC_0    EC_0        4260   4059  10.14   28    34     0   114      3.5  yes
EC_1    EC_1        3522   3321   8.39   38    42     0  2077    182.8  yes
EC_2    EC_2        4447   4246  10.59   18    12     0   114   -285.5  yes
EC_3    EC_3        3920   3719   9.33   35    34     0   114   -151.2  yes
EC_4    EC_4        2479   2278    5.9   29    30     3   114   -435.9  yes
EC_5    EC_5        4152   3951   9.89   23    22     3   113   1159.5  yes
TDS20   TDS2DEST    1342   1141    3.2    6     8     0   556     73.8  yes
TDS21   TDS2TUNN    1950   1749   4.64   11     9     0   325   -350.5   no
TDS22   TDS2TRES    2790   2589   6.64   29    33     0   114    203.9   no
TDS23   TDS2TUNN    2672   2471   6.36   31    22     0   285    971.7   no
TDS24   TDS2TRES    2838   2637   6.76   33    21     0   302    334.0   no
TDS25   TDS2TRES    3055   2854   7.27   36    20     0   291    362.1   no
```

The integrated heading does not close (as in TD1), so the maps are schematic.

### 5.4 Difficulty tables (EXE, index d = DS:02E4, 0–11; police uses min(d+3, 11))

| table | → opponent / police | values |
|---|---|---|
| DS:2316 vmax | 3318 / 331A | 0x5A00 + d × 0x0A00 (90–200 mph) |
| DS:232E accel_mult | 5358 / 5362 | 0x7333 8000 8CCD 9999 A666 B333 C000 CCCD D99A E666 F333 FFFF |
| DS:2346 min_gap | 535A / 5364 | 50 + d |
| DS:235E curve_factor | 535C / 5366 | 128 140 151 163 175 186 198 209 221 233 244 255 |
| DS:2376 lat_rate | 535E / 5368 | 20 21 22 23 25 26 28 30 33 36 40 44 |
| DS:238E | 5360 / 536A | 65 75 90 115 130 135 150 160 170 180 190 200 (not used by the simulation) |

Also from the difficulty screen (`0267:139b`): `traffic_speed = d×90/11 + 90`, `traffic_keep =
d×128/11 + 127`, DS:922E = d×67/11 + 33 (score), `auto_trans = (d < 4 && !demo)`.

### 5.5 `<SCN>n.SGN` (raw, optional)

Loaded by `0267:15e4` with `06c9:6d18` into a far block (DS:940C/940E) when the file exists
(TDS2 has only TDS20.SGN). `u16[20]` offsets (0 = none), index = object code − 0x1C. Each sign:
13 × u16 header, then NUL-terminated text with `\n` line breaks. The simulation only uses header
word 0 (width, 380–700): half width for collisions. Header word 1 is the height; the others
(`0x2B, 0x37, 0xFFFF, 0xFFFF, 0x2222, 0xAAAA, 0, 0, 0x14, 0x14, 0x32/0x41`) belong to the renderer.
Examples: "PLAY GRAND\nPRIX CIRCUIT", "ELEVATION  500", "AUTOBAHN\n BEGINS".

## 6. Hardware / DOS dependencies

| Dependency | Where | SDL3 replacement |
|---|---|---|
| Runs from the PIT ISR (100 Hz, `cli`) via the routine list | 3f40 → 614c, ISR 61bf | Fixed-step accumulator on the main thread: call `sound_tick` every 10 ms and the 10 Hz tick every 10th step, before rendering |
| Key state table (int 9) and joystick port 201h, read inside the ISR | 06c9:6620 / 6686 | SDL key state and gamepad, sampled at the 10 Hz tick |
| int 16h BIOS keyboard inside the ISR (only if SS == DS) | 06c9:6601 | SDL key events queue (Esc, O, D, hotkeys) |
| Tone divisor slots DS:5FD8–5FDE | 412c | Pass the values to the sound emulation (platform) |
| Queue sound DS:5494 | 4a2e → 7977 | Sound module |
| Self-modifying branches (copy protection) | 13a8:013c/0173 | Implement the patched behaviour (§4.21) |
| Far `.SGN` segment through ES | 4c85 | Normal pointer |

## 7. Timing

| What | Rate | Notes |
|---|---|---|
| `sound_tick`: rpm needle slew (±0x60), engine note, rumble, effect selection | 100 Hz | PIT divisor 0x2E9C (99.998 Hz) |
| Input, shifting, steering, engine, motion, AI, police, traffic, collisions | 10 Hz | Every constant is per tick |
| `race_time`, `opp_time` | 10 Hz | tenths of a second |
| `clock_seconds`, cloud scroll +1, clock redraw | 1 Hz | 30-minute limit |
| Knob animation | 6 px per tick | Completes only after fire is released |
| Radar detector beep | `tick_count & 4`: 0.4 s on, 0.4 s off | |
| Police timers | 20 ticks (2 s) stop, 30 ticks (3 s) at a roadblock | |
| Opponent crash delay | 30 ticks (10 after a player collision) | |
| Idle quit | 2400 ticks (4 min) | |
| Rendering | frame rate | Reads the state asynchronously; no simulation writes except redraw flags |

ENGINE_NOTE (DS:30E8, 177 words, index rpm_display/64): 0xFFFF for indices 0–9, then
`E90B D3DB C234 B344 A676 9B5D 91A7 8916 8178 7AA7 …` down to `0D3E` (full list in
`work/sim/tables.json`). RUMBLE (DS:32AE, 32 words): `24F3 2B10 1EAA 1D0F 1062 23BC 17EB 27E5 1577
221E 1EAB 3128 12FB 2099 240D 3097 17F1 2371 1175 278B 268F 1615 1BD6 3515 21BE 1845 2685 34C5 1728
1E46 2C91 21DE`. Effect divisors: 0x474 grind, 0x8E8 squeal, 900 radar beep, siren 1500–1800
(wail, ±2 per 1/100 s) or 1500/2000 (hi-lo).

The simulation itself does not depend on the frame rate (the RNG `06c9:780e` is called only by the
tick, `1e59`, and game_flow). The port must still run the tick synchronously so the renderer sees a
consistent state.

## 8. Differences from Test Drive (1987)

* **Scheduling:** TD1 hooked int 8 itself and ran the tick every 8th of 100 Hz (12.5 Hz). TD2 uses
  the platform's timer routine list and ticks at **10 Hz**; the rpm slew is ±0x60 instead of ±0x40.
* **Road:** TD1 had fixed stages in the EXE, a 40-unit look-ahead and 90 sub-units per unit. TD2
  loads one stage per `.DAT` (a memory image), with 256 sub-units per unit, a 71-unit look-ahead, a
  128-record table per stage, toggle flags for walls/drop-offs/narrow sections, wide road, zones and
  sign files. The speed step is `3 × mph` per tick.
* **Traffic:** TD1 spawned oncoming/same-direction cars from road objects (max 5). TD2 pre-places up
  to 50 cars per direction per stage, moves them at a difficulty-dependent speed, handles lane changes
  on wide roads, and pushes cars instead of passing through them. Random spawning now only places
  roadside scenery.
* **New:** the computer opponent (§4.15), a lane-choosing AI shared with the police and the demo; the
  police chase with pull-over, tickets, roadblocks, radar-detector beeping; damage (engine, suspension,
  steering, alignment, broken gears) with the related game-over messages; drop-offs and falling;
  fuel/out of gas; gas-station stopping zone; automatic transmission (difficulty < 4); gate shifting
  as a direct direction→gear map instead of TD1's node graph; self-centring steering (`06b3:0008`,
  C code) instead of TD1's input-only steering.
* **Engine:** the same model (torque × ratio_hi, rpm = ratio × speed >> 16, 800 idle, speed held when
  coasting in gear), but the force is `>> 5` with drag subtracted directly (TD1: `(force − drag×64)
  >> 6`), no ×1.5 in first gear, no 1st-gear launch boost, braking 1600 instead of 0x304,
  over-rev tolerance of 30 ticks between redline and max.
* **Grip:** TD1 compared a load (sin × speed + accel) with a limit. TD2 compares `steer_angle` with
  `grip / mph²`.
* **Keyboard:** held-key state instead of BIOS typematic; TD1's quirk Q11 is gone.
* **RNG:** same routine (`780e`), but no longer called per frame.
* Reusable from TD1's port: the general fixed-step structure, `rand8`, the sound divisor slots
  concept, knob animation (same algorithm, different completion rule), `update_rpm`.

## 9. Open questions

* **Q1** DS:379E–37A5 (per-stage words 30–65, 100–150, 70–110, 50–80) are used by the results code
  only (average-speed/score messages?): see game_flow.
* **Q2** The meaning of the toggles DS:37F7 (object 0x17) and DS:37F8 (0x19) is renderer-side
  (37F8 disables the backdrop layer at `06c9:0a12`).
* **Q3** `update_rpm` returns with CX/DX unchanged in neutral. When the fire button is released in
  neutral (`4281`, `4332`), `clutch_check` then sees CX = rpm with its low byte replaced by
  `THROTTLE_DIR[d]` (keyboard) or joystick-reader garbage, and DX = 0x0100. With keyboard input and
  rpm ≥ ~3300 (free revving) this can set the grind tone; the only physical effect (−5 mph) needs a
  rise of 2700 and a gear, so it cannot trigger. Suggested: skip the check in neutral, or emulate CX.
* **Q4** Object code 0x0B has no simulation effect; it always lies 11 units after 0x0A (or 1 unit on
  the last stages), so it is probably drawn by the renderer (gas station or finish).
* **Q5** `ai_road_scan` negates every curve before the unsigned max (the `jl` uses flags from `shl`,
  always "not less"). Right curves therefore yield the gentlest one, left curves the sharpest. Faithful
  behaviour is kept in the pseudocode.
* **Q6** `pass_check` leaves CX unchanged when a position is 0; the caller stores CX anyway. This
  cannot happen with the current state handling (the police car is only checked while active).
* **Q7** DS:5360/536A (difficulty table DS:238E) and DS:3354, DS:3358, DS:332E are written but never
  read by the simulation.
* **Q8** `obj_place_roadside` (`499a`) writes the rings with `[bp+368A]`/`[bp+370A]` without a
  segment override, i.e. through **SS**. It works because SS = DGROUP in this program (the ISR also
  checks `SS == DS` before using int 16h); in the port simply write the DS arrays.
* **Q9** `meet_check` places shoved cars at `pos + 1, +4, …` but compares following cars with the
  running position; overlapping cars further back are left alone. Faithful, but worth a visual check.
* **Q10** At the title screen DS:8A9A is set from DS:007C (the value returned by the copy-protection
  routine `13a8:002e`) when a key is pressed; the options and difficulty screens then overwrite it
  with 0 (key) or 1 (demo). Whether other values can reach the simulation is for game_flow to confirm;
  with the patched branches only the value 1 matters.
* **Q11** `nearest_ahead` (`5c30`) with an empty list would loop 65536 times (`loop` with CX = 0) and
  return an uninitialised index; no shipped stage has an empty list.

## 10. Corrections found while porting (td2port/src/game/sim*.c, checked against the listing)

* `road_edges`: the left side never enters the zone loop (4c1f jumps straight to the shoulder brake).
* `roadside_hit`: on the `.SGN` path, BP still holds the type when t < 0x50; it is stale only for t ≥ 0x50.
* Ring counter DS:533E: the motion loop increments only the low byte.
* `scenery_sprites` (DS:1DB4 + t·4) is the segment word of `scenery_handles[t]` (DS:1DB2).
* `pass_collisions`: CX on entry is always `same_count8`.
* `police()`: the "passed the parked cop" test is the sign of the 16-bit distance, not the carry-based
  signed compare.
