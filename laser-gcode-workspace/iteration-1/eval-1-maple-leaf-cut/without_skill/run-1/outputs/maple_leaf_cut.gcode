; ============================================================
;  Maple Leaf Outline Cut
;  Material : 3mm basswood (椴木板)
;  Laser    : 10W diode laser
;  Target   : ~80mm x 80mm (scale = 0.8x of 0-100 grid)
;  Origin   : TOP-LEFT, Y increases downward (screen coords)
;  Power    : 100% (S1000)  | Feed: 250 mm/min | Passes: 2
;  Generated: 2026-09-16
; ============================================================

G21            ; units = mm
G90            ; absolute positioning
M5             ; laser OFF (safety: make sure laser is off at start)
G0 X0 Y0       ; move to origin

; --- 2 passes for reliable through-cut on 3mm basswood ---
; Pass 1
M3 S1000       ; laser ON, full power (S1000 = 100% on GRBL)
G1 X40.0 Y1.6 F250
G1 X45.6 Y14.4
G1 X56.8 Y12.8
G1 X49.6 Y28.0
G1 X78.4 Y34.4
G1 X62.4 Y49.6
G1 X74.4 Y54.4
G1 X52.0 Y60.0
G1 X54.4 Y68.0
G1 X42.4 Y64.0
G1 X42.4 Y78.4
G1 X37.6 Y78.4
G1 X37.6 Y64.0
G1 X25.6 Y68.0
G1 X28.0 Y60.0
G1 X5.6 Y54.4
G1 X17.6 Y49.6
G1 X1.6 Y34.4
G1 X30.4 Y28.0
G1 X23.2 Y12.8
G1 X34.4 Y14.4
G1 X40.0 Y1.6

; Pass 2 (retrace same path for clean through-cut)
G1 X45.6 Y14.4
G1 X56.8 Y12.8
G1 X49.6 Y28.0
G1 X78.4 Y34.4
G1 X62.4 Y49.6
G1 X74.4 Y54.4
G1 X52.0 Y60.0
G1 X54.4 Y68.0
G1 X42.4 Y64.0
G1 X42.4 Y78.4
G1 X37.6 Y78.4
G1 X37.6 Y64.0
G1 X25.6 Y68.0
G1 X28.0 Y60.0
G1 X5.6 Y54.4
G1 X17.6 Y49.6
G1 X1.6 Y34.4
G1 X30.4 Y28.0
G1 X23.2 Y12.8
G1 X34.4 Y14.4
G1 X40.0 Y1.6

M5            ; laser OFF
G0 X0 Y0      ; return to origin
M2            ; end of program
