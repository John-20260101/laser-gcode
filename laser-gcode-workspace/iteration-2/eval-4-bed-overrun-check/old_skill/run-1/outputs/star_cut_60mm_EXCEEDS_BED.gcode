; Job: cut | Material: Plywood / Basswood 3mm | Laser: 20.0W (tier 20W)
; Power: 90.0% -> S900/1000 | Feed: 1000.0 mm/min | Passes: 1
; Target: 60.0x60.0 mm | Origin(out): bottom-left | Polygons: 1
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- cut poly1 (S=900, F=1000.0, passes=1) ---
G0 X30.000 Y58.800
M3 S900
G1 F1000.0
G1 X36.702 Y39.222
G1 X57.390 Y38.898
G1 X40.842 Y26.478
G1 X46.926 Y6.702
G1 X30.000 Y18.600
G1 X13.074 Y6.702
G1 X19.158 Y26.478
G1 X2.610 Y38.898
G1 X23.298 Y39.222
G1 X30.000 Y58.800
M5
M5
G0 X0 Y0
M2
