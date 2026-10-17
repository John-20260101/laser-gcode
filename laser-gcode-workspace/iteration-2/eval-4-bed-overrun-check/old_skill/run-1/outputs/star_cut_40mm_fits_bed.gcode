; Job: cut | Material: Plywood / Basswood 3mm | Laser: 20.0W (tier 20W)
; Power: 90.0% -> S900/1000 | Feed: 1000.0 mm/min | Passes: 1
; Target: 40.0x40.0 mm | Origin(out): bottom-left | Polygons: 1
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- cut poly1 (S=900, F=1000.0, passes=1) ---
G0 X20.000 Y37.370
M3 S900
G1 F1000.0
G1 X24.468 Y24.318
G1 X38.260 Y24.102
G1 X27.228 Y15.822
G1 X31.284 Y2.638
G1 X20.000 Y10.570
G1 X8.716 Y2.638
G1 X12.772 Y15.822
G1 X1.740 Y24.102
G1 X15.532 Y24.318
G1 X20.000 Y37.370
M5
M5
G0 X0 Y0
M2
