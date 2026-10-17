; Job: engrave | Material: Dark/cast acrylic 3mm (diodes cannot cut clear acrylic) | Laser: 20.0W (tier 20W)
; Power: 35.0% -> S350/1000 | Feed: 4000.0 mm/min | Passes: 1
; Target: 50.0x50.0 mm | Origin(out): bottom-left | Polygons: 1
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- engrave poly1 (S=350, F=4000.0, passes=1) ---
G0 X25.000 Y46.000
M3 S350
G1 F4000.0
G1 X31.000 Y36.000
G1 X43.000 Y39.000
G1 X36.000 Y28.000
G1 X47.000 Y25.000
G1 X36.000 Y21.000
G1 X43.000 Y10.000
G1 X31.000 Y13.000
G1 X25.000 Y4.000
G1 X19.000 Y13.000
G1 X7.000 Y10.000
G1 X14.000 Y21.000
G1 X3.000 Y25.000
G1 X14.000 Y28.000
G1 X7.000 Y39.000
G1 X19.000 Y36.000
G1 X25.000 Y46.000
G1 X25.000 Y46.000
M5
M5
G0 X0 Y0
M2
