; Job: cut | Material: Plywood / Basswood 3mm | Laser: 20W (tier 20W)
; Power: 90% -> S900/1000 | Feed: 1000 mm/min | Passes: 1
; Target: 60x60 mm | Origin(out): bottom-left | Polygons: 1
; BBox: X0.000..60.000 Y1.469..58.531 (60.00 x 57.06 mm) | Burn: 226.6 mm | Est: 0.2 min
; WARNING: starting parameters - always test on scrap first.
G21
G90
G17
M5
; --- cut poly1 (S=900, F=1000, passes=1) ---
G0 X30.000 Y58.531
M3 S900
G1 F1000
G1 X37.341 Y37.088
G1 X60.000 Y36.733
G1 X41.875 Y23.129
G1 X48.539 Y1.469
G1 X30.000 Y14.501
G1 X11.461 Y1.469
G1 X18.125 Y23.129
G1 X0.000 Y36.733
G1 X22.659 Y37.088
G1 X30.000 Y58.531
M5
G0 X0.000 Y0.000
M2
