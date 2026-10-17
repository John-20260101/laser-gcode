; Job: cut | Material: Plywood / Basswood 3mm | Laser: 10.0W (tier 10W)
; Power: 100.0% -> S1000/1000 | Feed: 500.0 mm/min | Passes: 2
; Target: 50.0x50.0 mm | Origin(out): bottom-left | Polygons: 1
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- cut poly1 (S=1000, F=500.0, passes=2) ---
G0 X0.000 Y50.000
M3 S1000
G1 F500.0
G1 X50.000 Y50.000
G1 X50.000 Y0.000
G1 X0.000 Y0.000
G1 X0.000 Y50.000
G1 X0.000 Y50.000
G1 X50.000 Y50.000
G1 X50.000 Y0.000
G1 X0.000 Y0.000
G1 X0.000 Y50.000
G1 X0.000 Y50.000
M5
M5
G0 X0 Y0
M2
