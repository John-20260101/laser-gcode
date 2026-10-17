; Job: cut | Material: Plywood / Basswood 3mm | Laser: 10W (tier 10W)
; Power: 100% -> S1000/1000 | Feed: 500 mm/min | Passes: 2
; Target: 50x50 mm | Origin(out): bottom-left | Polygons: 1
; BBox: X25.000..75.000 Y25.000..75.000 (50.00 x 50.00 mm) | Burn: 400.0 mm | Est: 0.8 min
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- cut poly1 (S=1000, F=500, passes=2) ---
G0 X25.000 Y75.000
M3 S1000
G1 F500
G1 X75.000 Y75.000
G1 X75.000 Y25.000
G1 X25.000 Y25.000
G1 X25.000 Y75.000
M5
G0 X25.000 Y75.000
M3 S1000
G1 F500
G1 X75.000 Y75.000
G1 X75.000 Y25.000
G1 X25.000 Y25.000
G1 X25.000 Y75.000
M5
G0 X25.000 Y25.000
M2
