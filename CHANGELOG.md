# Changelog

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
