; Job: cut | Material: Plywood / Basswood 3mm | Laser: 20W (tier 20W)
; Power: 90% -> S900/1000 | Feed: 1000 mm/min | Passes: 1
; Target: 38x38 mm | Origin(out): bottom-left | Polygons: 1
; BBox: X1.000..39.000 Y1.930..38.070 (38.00 x 36.14 mm) | Burn: 143.5 mm | Est: 0.2 min
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- cut poly1 (S=900, F=1000, passes=1) ---
G0 X20.000 Y38.070
M3 S900
G1 F1000
G1 X24.649 Y24.489
G1 X39.000 Y24.264
G1 X27.521 Y15.649
G1 X31.741 Y1.930
G1 X20.000 Y10.184
G1 X8.259 Y1.930
G1 X12.479 Y15.649
G1 X1.000 Y24.264
G1 X15.351 Y24.489
G1 X20.000 Y38.070
M5
G0 X1.000 Y1.000
M2
