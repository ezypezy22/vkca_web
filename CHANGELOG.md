# Changelog

## 26.7.15

### Enhancements

e893bd5 Add VK/ZL area coverage heat and prefix-split gauges to the Trans-Tasman Overview

### Bugfixes

00519b9 Fix noticeable delay when closing the app via the titlebar X

## 26.7.14

### Bugfixes

76c9e85 Fix worked_primary_band_mults() bypassing mult_of_qso()'s resolution (#29)
2b304d3 Fix QRZClient credential race and resize-handle flush bug (#30, #31)
a8a52df Fix XSS: escape log/network-derived text before innerHTML (#32-#36)

## 26.7.13

### Bugfixes

59a1593 Fix no single-instance guard and unchecked startup timeout (#21, #22)
b715f45 Fix DX Cluster reconnect race and port-bind TOCTOU race (#26, #23)
f433239 Fix IOTA off-band mislabeling and Mini HUD close() hang (#24, #25)
6857147 Fix contest_start() crash and pts-floor data corruption (#27, #28)

## 26.7.12

### Enhancements

4abedb1 Add CQ WW Digi and ARRL International Digital contest plugins (#17)

### Bugfixes

76ec01e Fix Bands tab showing blank Score/%/Best Rate/Last QSO for most contests (#19)
2620f0d Fix overview gauge glow bleed and coloured-digit fringing on Linux
1723340 Fix theme/prefs silently resetting on quick app restart on Linux
d36bfbe Fix DX Cluster mode filter and connect/disconnect button state

## 26.7.11

### Enhancements

f2a8c4f Add mode column/filter to DX Cluster tab

### Bugfixes

1d762ae Fix VK Trans-Tasman scoring and a naive-UTC display bug in Rate/Worked tabs
f2a8c4f Fix DX cluster spots never reaching the table
3d48178 Use a fixed port for the pywebview window so localStorage actually persists

## 26.7.10

### Enhancements

96011a4 Add operator efficiency, live countdown, and frameless drag/close to the mini HUD (issue #10)
8b78ced Sync theme changes live across popped-out windows

### Bugfixes

a23102e Fix persistent settings being wiped on every app restart
bccdd19 Fix theme/prefs silently resetting on quick app restart on Linux

## 26.7.9

### Enhancements

8ceb29d Add WRTC 2026 worked-station tracking to the IARU plugin

## 26.7.8

### Enhancements

899648d Add a Mults per hour chart to the Rate tab
22484f1 Style Mults per hour chart as a glowing sparkline, matching Overview

### Bugfixes

c2ad9ee Fix stale v26.7.6 hardcoded in index.html title/titlebar
94e5da2 Fix Linux maximize/restore across monitors (stuck full-screen, wrong position on restore, occasional freeze)
c8bc99c Fix ARRL 10M dupe/scoring blind spot for mode-scoped rework (issue #8)
eb28798 Fix Rate tab always showing 0 new/cum mults and score (issue #9)
5fa1df8 Stop Rate tab charts flashing/redrawing on unrelated snapshot pushes

## 26.7.7

### Enhancements

1aa4429 Show empty logs in the contest picker (fixes #3)

### Bugfixes

57f5e69 Force a real DB reload on manual/auto refresh (fixes #2)
9c9ac4a Fix unreadable table rows in Light theme (fixes #4)
bc3c63e Fix ARRL10M multiplier parsing to handle RST/serial glued onto exchange (issue #7)
e2fa128 Fix Bands tab showing stale data from the previous contest (issue #7)
a701e42 Fix Report Issue dialog not submitting under pywebview (issue #7)
df89a8c Fix dupe detection blind spot for not1mm-sourced logs (issue #7)
f02a90a Fix ITU/HQ/multiplier-by-mode data loss for not1mm-sourced logs (issue #7)
68aa4f1 Fix live-rank lookup only ever checking one COSB contest (fixes #5)
7eb232d Show pre-contest countdown instead of "No contest loaded"
