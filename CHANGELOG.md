# Changelog

## 26.7.20

### Enhancements

90ca898 Add live radio frequency/band readout via N1MM+'s RadioInfo UDP broadcast
38f3d12 Add DX Cluster band highlighting, live dead-air alert, and a band occupancy board
2bc3ffb Turn the DX Cluster's next-targets line into a live Band Advisor that scores every band by recent needed-mult activity and recommends where to switch
bab56dd Add a one-time hint pointing new users to N1MM+'s Radio broadcast setting when none is detected
bbf3b61 Add a recurring Report Issue reminder pointing at the titlebar's bug/feature-request button
3eb5a3a Add a rotating set of feature-discovery tips (Mini HUD, Operator HUD, Replay, What if?, Band Advisor, and more), shown periodically after the Report Issue reminder
22167d8 Add an animated live-signal pulse to the Overview Radio panel while radio data is flowing
a85c904 Give hint popups an audible "knock" alert (real recorded SFX, tuned for pitch and volume) so they're harder to miss

### Bugfixes

126adba Fix Mini HUD's radio tile missing the "MHz" unit, and unreadable DX Cluster "Not a Mult" rows in Light theme
214c1e8 Fix the live radio readout (and every other live update) stalling behind a single slow/unresponsive WebSocket client
2259b90 Fix a shared lock held across a full log recompute, which could freeze the entire app for several seconds at a time
c251c9e Fix the radio broadcast debounce silently dropping intermediate frequency steps while tuning
3c7352a Fix window dragging lagging behind the cursor by routing through pywebview's fast move-window path instead of the slower generic API bridge
bdc4cb1 Fix the radio-signal pulse icon being cropped by its panel's overflow clipping
47ae321 Fix hint chimes sometimes producing no audible sound due to a suspended AudioContext never being resumed

## 26.7.19

### Enhancements

ff21a83 Give needed-multiplier spots a continuous pulse in the DX Cluster tab

### Bugfixes

Full-app code review — 34 issues found and fixed (#40-#73):

eda26cc Fix ARRL DX plugin misidentification (DX vs W/VE station) and its Overview gauges showing wrong worked/missing counts (#40, #42)
eda26cc Fix DX Cluster connect blocking the whole app for up to 30s on a slow/hung peer (#41)
eda26cc Fix XSS: unescaped call signs, contest names, and filenames reaching innerHTML in 4 places (#43, #44, #56, #65)
eda26cc Fix VK Shires crediting the wrong shire when the exchange digit and callsign area disagree (#45)
eda26cc Fix JIDX missing 8K/8L/8M/8N special-event prefixes, and swapped JA0/JA9 region labels (#46, #67)
eda26cc Fix HA Sprint and IOTA missing the once-per-mode dupe rule, incorrectly zeroing legitimate different-mode reworks (#47, #48)
eda26cc Fix CQWW un-duping genuine N1MM-flagged dupes, and ARRL DX mislabeling non-scoring DX-DX contacts as dupes (#49, #50)
eda26cc Fix a HUD-window creation race and /api/qsos/delete not broadcasting the updated snapshot (#51, #52)
eda26cc Fix inconsistent contest-start clamping across session/rate calculations, band breakdown bypassing plugin multiplier resolution, and the sparkline "new mults" count going permanently to zero when a log's mult flags are unavailable (#53, #54, #55)
eda26cc Fix ARRL 10M failing to parse a glued CW RST+state exchange like "5NNTX" (#57)
eda26cc Fix Pace tab's trajectory chart overshooting near contest end, and its reference-comparison polling never stopping after leaving the tab (#58, #59)
eda26cc Fix Settings dialog polling QRZ status redundantly in all 3 windows and double-firing completion toasts (#60)
eda26cc Fix an unguarded settings-file read-modify-write race and blocking file I/O on the event loop (#61)
eda26cc Fix a bad DX Cluster port silently killing the whole session instead of showing an error (#62)
eda26cc Fix the titlebar showing the wrong contest name after a failed Switch Contest/load (#63)
eda26cc Fix stale fetch responses clobbering fresher data on the Dupes/Debug/Missing/Worked tabs (#64)
eda26cc Fix duplicate /api/os_theme and /api/save_location route registrations (dead code) (#68)
eda26cc Fix /api/dupes error response missing the rule_text field (#69)
eda26cc Fix World Map arc opacity never actually responding to basemap brightness (#70)
eda26cc Fix Missing Mults tab crashing if its markup is ever conditionally absent (#71)
eda26cc Fix Operator HUD polling a Live Rank panel it can never render (#72)
eda26cc Rework several charts to update in place instead of destroy+recreate on every redraw (#73)

## 26.7.18

### Enhancements

7ad524f Add native desktop toast notifications for milestones/best-rate
791cbeb Add new-spot glow and age-fade to the DX Cluster tab
dacf339 Style the Pace tab's trajectory chart as a glowing sparkline
e87f129 Add a custom accent colour picker, layered on top of the 5 themes
515384f Add sound alerts for milestones and best-rate records
eab32b5 Replace the milestone tone with a synthesized clap/cheer burst
ba1d127 Rework milestone/best-rate sound, add contest end-time alerts
37a5623 Add an Operator HUD pop-out window for multi-op contests
e62ecc3 Restyle the Operator HUD: vertical card stack + visual polish
127d73b Add a consolidated Settings panel for QRZ lookup + log search folders
43911ad Move Settings button next to Open Log, give it a distinct colour

### Bugfixes

da389aa Fix /api/notify truncation limits to match Win32's actual struct caps
ef11f57 Fix shutdown-time RuntimeError race in _poll_loop()

## 26.7.17

### Enhancements

2f68fe1 Add live cosmetic feedback to the Overview: new-QSO pulse, best-rate flash, score milestone bursts
be9c89a Add current-hour marker to Rate chart, temperature tint to Bands table
8553d61 De-emphasize low-sample band efficiency figures in the Bands tab
d0b35d1 Expand the Mini HUD: mults, session label, field picker with descriptions, live celebrations, double-click-to-focus-main
b19b749 Add HUD orientation toggle (horizontal ⇄ vertical) and glow-style sparklines matching the Overview

### Bugfixes

8553d61 Fix stale Bands chart tooltip (closed over first-render values, never refreshed on live updates)
b217348 Fix HUD layout overlap once the field count grew to 7
0592832 Fix HUD field-picker menu covering the window's own close/settings buttons

## 26.7.16

### Enhancements

01252dd Add per-panel hide/show to the Overview tab

### Bugfixes

758eb83 Fix loader.py: ambiguous-match self-check, silent exceptions, TOCTOU race (#37, #38, #39)

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
