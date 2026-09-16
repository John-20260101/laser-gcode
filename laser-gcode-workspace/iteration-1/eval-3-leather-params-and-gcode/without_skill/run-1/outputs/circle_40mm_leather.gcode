; ============================================================
; GRBL Laser Cutting G-code
; ------------------------------------------------------------
; Material : 2mm veg-tanned leather (植鞣皮革)
; Machine  : 20W diode laser (455nm class)
; Shape    : Circle, diameter 40mm
;          : approximated by 24-segment polygon
; Origin   : workpiece corner (0,0) at lower-left
; Center  : X50 Y50 mm  (radius = 20 mm)
;
; CUTTING PARAMETERS
;   Power      : S1000  (100% on 0-1000 GRBL scale)
;   Feed rate  : 150 mm/min
;   Passes     : 4  (repeat the closed path 4 times)
;   Laser mode : M3 constant power (laser mode $32=2)
;
; SAFETY NOTES
;   - 20W diode light is near-visible blue, VERY dangerous to eyes.
;     Always wear 455nm-rated laser safety goggles.
;   - Leather chars and can flame - keep a fire extinguisher nearby,
;     never leave the machine unattended while cutting.
;   - Veg-tanned leather produces smoke/fumes; ensure ventilation/
;     exhaust extraction.
;   - Watch the first pass; if edges scorch excessively, reduce power
;     to S850 or increase feed to 200 mm/min.
;   - Confirm GRBL is in laser mode: send $32=1 (or $32=2) before run.
;   - Homing/limits assumed; verify workpiece fits within machine
;     travel and that the beam is focused on the leather surface.
; ============================================================

G21          ; units = mm
G90           ; absolute positioning
G94           ; feed rate in mm/min
M4 S0         ; ensure laser OFF (dynamic mode, 0 power)

; --- rapid to start vertex (angle 0 deg) ---
G0 X70.0000 Y50.0000

; === PASS 1 ===
M3 S1000               ; laser ON, constant full power
G1 X69.3185 Y55.1764 F150
G1 X67.3205 Y60.0000
G1 X64.1421 Y64.1421
G1 X60.0000 Y67.3205
G1 X55.1764 Y69.3185
G1 X50.0000 Y70.0000
G1 X44.8236 Y69.3185
G1 X40.0000 Y67.3205
G1 X35.8579 Y64.1421
G1 X32.6795 Y60.0000
G1 X30.6815 Y55.1764
G1 X30.0000 Y50.0000
G1 X30.6815 Y44.8236
G1 X32.6795 Y40.0000
G1 X35.8579 Y35.8579
G1 X40.0000 Y32.6795
G1 X44.8236 Y30.6815
G1 X50.0000 Y30.0000
G1 X55.1764 Y30.6815
G1 X60.0000 Y32.6795
G1 X64.1421 Y35.8579
G1 X67.3205 Y40.0000
G1 X69.3185 Y44.8236
G1 X70.0000 Y50.0000   ; close polygon
M5                   ; laser OFF

; === PASS 2 ===
M3 S1000
G1 X69.3185 Y55.1764 F150
G1 X67.3205 Y60.0000
G1 X64.1421 Y64.1421
G1 X60.0000 Y67.3205
G1 X55.1764 Y69.3185
G1 X50.0000 Y70.0000
G1 X44.8236 Y69.3185
G1 X40.0000 Y67.3205
G1 X35.8579 Y64.1421
G1 X32.6795 Y60.0000
G1 X30.6815 Y55.1764
G1 X30.0000 Y50.0000
G1 X30.6815 Y44.8236
G1 X32.6795 Y40.0000
G1 X35.8579 Y35.8579
G1 X40.0000 Y32.6795
G1 X44.8236 Y30.6815
G1 X50.0000 Y30.0000
G1 X55.1764 Y30.6815
G1 X60.0000 Y32.6795
G1 X64.1421 Y35.8579
G1 X67.3205 Y40.0000
G1 X69.3185 Y44.8236
G1 X70.0000 Y50.0000
M5

; === PASS 3 ===
M3 S1000
G1 X69.3185 Y55.1764 F150
G1 X67.3205 Y60.0000
G1 X64.1421 Y64.1421
G1 X60.0000 Y67.3205
G1 X55.1764 Y69.3185
G1 X50.0000 Y70.0000
G1 X44.8236 Y69.3185
G1 X40.0000 Y67.3205
G1 X35.8579 Y64.1421
G1 X32.6795 Y60.0000
G1 X30.6815 Y55.1764
G1 X30.0000 Y50.0000
G1 X30.6815 Y44.8236
G1 X32.6795 Y40.0000
G1 X35.8579 Y35.8579
G1 X40.0000 Y32.6795
G1 X44.8236 Y30.6815
G1 X50.0000 Y30.0000
G1 X55.1764 Y30.6815
G1 X60.0000 Y32.6795
G1 X64.1421 Y35.8579
G1 X67.3205 Y40.0000
G1 X69.3185 Y44.8236
G1 X70.0000 Y50.0000
M5

; === PASS 4 ===
M3 S1000
G1 X69.3185 Y55.1764 F150
G1 X67.3205 Y60.0000
G1 X64.1421 Y64.1421
G1 X60.0000 Y67.3205
G1 X55.1764 Y69.3185
G1 X50.0000 Y70.0000
G1 X44.8236 Y69.3185
G1 X40.0000 Y67.3205
G1 X35.8579 Y64.1421
G1 X32.6795 Y60.0000
G1 X30.6815 Y55.1764
G1 X30.0000 Y50.0000
G1 X30.6815 Y44.8236
G1 X32.6795 Y40.0000
G1 X35.8579 Y35.8579
G1 X40.0000 Y32.6795
G1 X44.8236 Y30.6815
G1 X50.0000 Y30.0000
G1 X55.1764 Y30.6815
G1 X60.0000 Y32.6795
G1 X64.1421 Y35.8579
G1 X67.3205 Y40.0000
G1 X69.3185 Y44.8236
G1 X70.0000 Y50.0000
M5

; --- park & finish ---
G0 X0 Y0
M5
M2           ; end of program
