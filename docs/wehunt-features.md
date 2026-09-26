# WeHunt-inspired features: camera output first

WeHunt ([wehunt.app](https://wehunt.app/), Svenska Jägareförbundet) is the leading Nordic hunting app. It is
map-first:
- trail cameras sit on the map as their latest photo, with a "new" count;
- a Timeline replays what happened on the ground;
- a heatmap of where game moves over time was announced for 2026;
- camera alerts can be switched on and off per camera.

The owner's brief: **use the cameras' output to our advantage as a team first.** Hunt planning, collaboration and
safety come later. This document records what GameSense borrows now, what waits, and why.

## Built now

### 1. The map, WeHunt-style
- **Controls and panels.**
  - Round 48px floating buttons: Map sheet, North and Fit estate on the right; Measure and Me on the left.
  - A scale pill.
  - Tapping a camera or stand opens a **bottom sheet** (snap points 112px / 50% / 90%). It replaces the peek card
    and the panel below the map.
  - One **Map sheet** with the sections Map type / Show on map / Tools / Size. Size has one switch, "Bigger pins
    and names".
- **Spanish base maps.**
  - **Aerial** from PNOA (IGN) and **Topo** from IGN MTN.
  - **Aerial (world)** from Esri, which is also the automatic fallback.
  - A **Property lines (Catastro)** overlay.
  - The choice is remembered on the phone.
- **Measure** ("134 m · north-east"), and **Me**, which shows your own position on your phone only.
- **Drawing bedding** uses a fixed centre crosshair with one big "Add corner" button, which works with gloves.
- **One palette.** The map uses the app's theme tokens.
- The map rework also fixes these bugs from the audit:
  - "Try again" no longer wipes the map (B-01).
  - Errors are shown next to the control (B-11).
  - "See photos" opens that camera (B-21).
  - Glove-sized controls (B-16).
  - North reset (B-23).
  - A zoom cap on the satellite layer (B-24).

### 2. Photos on the map
- Each camera shows its **latest animal photo** as a small framed thumbnail pointing at the camera, with a
  **"new" count**. "New" means photos since *you* last opened that camera, and it is tracked per person on the
  server.
- Tapping a camera opens its sheet:
  - last photo time, battery and signal;
  - **"Last night: Wild boar · 2 visits, Red deer · 1 visit"** (visits, not photos);
  - a strip of recent photos that opens the photo viewer;
  - "See all photos" (that camera's photos);
  - the camera's alert switch.
- **Small thumbnails.** Photos are served as cached 320 px WebP, so the map and the grids stop downloading
  originals (part of plan item 13).

### 3. Activity map ("where the game is")
- A map mode with a circle at each camera, sized by **animal visits per watched night**. Nights a camera wasn't
  working don't count as quiet.
- Filters:
  - **species**;
  - **part of the night**: dusk 18–22, night 22–03, dawn 03–08, or all;
  - **period**: last night, 7 nights or 30 nights.
- Hidden species and photos marked "nothing in it" never count.
- Tapping a circle gives a one-line read, e.g. "Charca: boar on 5 of 7 nights, mostly 21–23 h", and opens the
  camera sheet.

### 4. Replay a night
- Pick a night from the last 14. A timeline from 18:00 to 08:00 plays the camera visits on the map in order:
  - each visit pops at its camera with the species and a thumbnail;
  - play/pause, ±5 min jumps, and 1×/10×/60× speed.
- When the same species reaches another camera within 3 h, a faint arrow connects the two: **"likely went this
  way"**. It is labelled as a guess.

### 5. Per-camera alerts
- On top of the per-species alerts, each person can **mute a camera** (e.g. the busy feeder) or keep it on. The
  switch is in Settings → Alerts and in the camera's sheet.

### 6. Team notes on photos ("Worth a look")
- In the photo viewer, anyone except viewers can tap **"Worth a look"** and add an optional short note (≤ 140),
  e.g. "Big boar, third night running".
- **Worth a look** strips appear on Photos and in the camera sheet. The whole team sees them, newest first, with
  who marked each one and when.
- Other people can add their own note to the same photo.
- The author or an admin can remove a note.
- Optional **"Tell the team"** (off by default) sends one push.
- Names come from the email address (pedro.garcia@… → "Pedro") until hunter names are built.

## Later (parked by the owner)
- Hunt planning.
- Collaboration: hunter names, an "Out tonight" board, roll call.
- Safety: no-shoot areas, estate edge, shooting sectors, shot and tracking alerts.
- The night report.
- Typed map pins.

The research and specs for these are kept for when they come back. The already-written stage (hunter names plus
the sit-report fixes from plan item 2) is parked outside this branch.

## Not borrowed
- Team chat (the group uses WhatsApp).
- Dog GPS.
- Swedish reporting systems.
- Always-on position sharing.
- White bottom sheets (they wreck night vision).
- Orange used for anything other than people.

## Research sources
- Maps: <https://wehunt.app/en/the-app/maps-in-wehunt/>
- What WeHunt is: <https://wehunt.app/en/learn/this-is-wehunt/>
- Support centre (cameras, map pins, timeline):
  <https://support.wehuntapp.com/en/support/solutions/articles/151000035876-how-can-i-place-map-pins-in-the-app->
- Reviews: <https://vildmarken.se/reportage/wehunt-4-0-lyfter-jaktupplevelsen/>
