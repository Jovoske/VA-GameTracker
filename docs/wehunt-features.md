# WeHunt-inspired features: build spec

WeHunt ([wehunt.app](https://wehunt.app/), Svenska Jägareförbundet) is the leading Nordic hunting app. It is
map-first and organised around the team:
- a hunting ground with a drawn border, red forbidden areas and typed map pins;
- forbidden shooting directions per stand;
- a hunt as a timed event, where everyone sees who is where, reports shots and observations, and "hunt over"
  stops position sharing for everyone;
- a game report built automatically afterwards.

This document records what GameSense borrows, how it maps onto an estate of a few hunters doing evening and
night sits, and what it deliberately leaves out. The research is summarised at the end.

GameSense has no "hunt event" object. A night is the event: the existing per-night **sits** (reservations) are
the participant list. Most nights are lone aguardos, not led drives.

## Look and feel borrowed

- **One colour per kind of thing, with shape carrying the meaning.**
  - People use a new token `--hunter: #F2913D` (blaze orange). It is used for people only.
  - No-shoot areas use `--skip` red.
  - The estate edge is `--sand` over a dark casing.
  - Safe shooting sectors use a `--go` outline.
  - Map labels are 12px bold with a dark halo on satellite.
- **Positions go stale in place.** After 5 min a person's dot turns `--text-dim` grey and says
  "last seen 12 min ago".
- **Word + glyph states**, following the app's existing verdict convention: `◌ Reserved`,
  `● In stand since 19:42`, `→ Walking out`, `✓ Out 23:05`, `! Not out yet`.
- **Crosshair placement** for anything placed on the map (area corners, pins):
  - a fixed centre cross;
  - a bottom bar with one 56px primary button;
  - Undo;
  - a live segment length and area.

  This works with gloves, like Sit mode.
- **Map-first chrome.**
  - 48px round floating buttons in the edge columns.
  - One (+) Add button at bottom-left.
  - A north button with a red tick.
  - A bottom sheet on tap, replacing the peek card and the panel below the map.
  - One "Map" sheet with the sections Map type / Show on map / Tools / Size.
- **One palette.** `map.css` uses theme tokens instead of its own olive palette.
- **Honest caveats** in small dim type, e.g. "An indication only. Wind near the ground swirls."
- **Sit mode stays black and amber.** Safety information there is words first, plus a small ring.

**Not borrowed:**
- white bottom sheets (they wreck night vision);
- a neon own-position dot;
- orange primary buttons (orange means people);
- 30 configurable shortcuts;
- organic scent plumes;
- chat;
- tallies and leaderboards.

## Features (build order)

### Stage 1: foundations
1. **Hunter names (W1).** `users.display_name` (≤ 40 characters). The fallback is the capitalised first chunk of
   the email local part, then "Hunter".
   - `PATCH /api/auth/me {display_name}`.
   - Names appear on stands ("Taken by Pedro"), on sits, and in Settings ("Your name").
   - The admin can set a name when adding a person.
2. **A sit lifecycle you can trust** (the part of plan item 2 the board depends on):
   - The outcome is never lowered (shot > shootable_no_shot > seen > nothing), except by an explicit
     `correct: true` from the Stands "What happened?" edit.
   - Every write carries the client `at`, and `sits.reported_at` ignores older writes.
   - `POST /api/sits/{id}/end` sets `ended_at`; outcome taps no longer end the sit.
   - Client queue: one entry per sit, a single-flight flush, cleared on sign-out.
   - Stands shows "Back to sit" while the sit is started and not ended. "What happened?" stays available all
     night.

### Stage 2: the map, WeHunt-style
3. **Map chrome (W8).**
   - Round floating buttons.
   - Right column: Layers/Map sheet, North, Fit estate.
   - Left column: Add (+), Me, Measure.
   - A scale pill.
   - A bottom sheet for the selected stand or camera, with snap points.
   - One palette.
   - "Try again" reloads only the tiles (fixes B-01).
4. **Spanish base maps (W9).**
   - Aerial from PNOA (IGN).
   - Topo from the IGN MTN raster.
   - "Aerial (world)" from Esri, the automatic fallback after repeated tile errors.
   - A "Property lines (Catastro)" overlay from zoom 15.
   - The choice is remembered on the phone.
5. **Measure and distance rings (W10).** Tap two points to get "134 m · north-east". "Distance rings" draws
   50/100/150 m rings around the selected stand.
6. **Me (local only).** Shows your own position (a white dot with a teal ring and an accuracy circle). Nothing
   is sent to the server.
7. **Crosshair editor.** Used for every area and pin. Drawing bedding moves to it.

### Stage 3: what's on the ground
8. **No-shoot areas and estate edge (W2).**
   - A new zone kind `boundary`; the existing `no_go` kind is now drawn.
   - Only admins can edit these.
   - The map heading shows "Piedras Lisas · 412 ha".
   - The stand sheet says "Inside a no-shoot area" or "Estate edge 180 m away".
   - The draw menu offers "Draw area → Bedding / No-shoot area / Estate edge".
9. **Typed map pins (W7).**
   - A `map_pins` table.
   - Types: feeder, water, wallow, salt, gate, parking, meeting point, crossing, hazard tonight, other.
   - Each pin is private or shared with the estate.
   - A hazard expires at the next 06:00 and can push "Heads up: …" to tonight's hunters.
   - A dated notes list.
   - Labels show only from zoom 16.

### Stage 4: safety
10. **Shooting sectors and "Don't shoot this way" (W3).**
    - `stands.shooting_sectors` jsonb, with up to 2 wedges of 10–270°, drawn on the map with drag handles and
      ±5° buttons.
    - A safety setting `{half_angle_deg: 30, reach_m: 3000}`.
    - `GET /api/stands/{id}/safety` lists the blocked bearings from:
      - other hunters in stands tonight;
      - no-shoot areas;
      - hunters tracking (stage 5).
    - Claims refuse a stand that is inside, or has inside its sector, a stand already taken tonight
      (409 `line_of_fire`).
    - Sit mode shows "DON'T SHOOT: North-east · Pedro at Solana · 640 m" and a small amber ring. This is
      cached for no signal.

### Stage 5: tonight, together
11. **"Out tonight" board and roll call (W4).**
    - The sit states are: reserved, in stand, walking out, out, overdue.
    - "When will you be out?" is asked at Start sit.
    - END SIT leads to a Walking-out screen with "I'M OUT · BACK AT THE CAR".
    - Roll-call pushes:
      - the hunter is nudged 45 min after their planned time;
      - 20 min later, the others and the admins are told;
      - "Everyone is out" goes out once.
    - Runs as `pipeline.py rollcall` every 5 min. It is lock-free, and Celery beat runs it in Docker.
12. **Shot, tracking and "Message all hunters" (W6).**
    - SHOT asks "Down / Going to look / Missed", then which way.
    - Going to look opens a Tracking screen that shares the phone position every 30 s, only until "Found it" /
      "Back in my stand" / "Stopped looking" (it auto-expires after 3 h).
    - The others get "Pedro is tracking from Solana, heading north-east. Hold your fire that way.", and see an
      orange dot on the map. Tracking also adds a blocked wedge.
    - Admins can send a 140-character message to everyone, or only to tonight's hunters.

### Stage 6: after
13. **Night report (W13).**
    - `/night/:date` shows who sat where and for how long, what they saw or shot, the saved wind call, and what
      the stand's camera caught during the sit.
    - An unreported sit gets a one-tap fix.
    - A share button builds a plain-text summary for the WhatsApp group.
    - One morning push, "Last night at Piedras Lisas".
    - Linked from Stands and Insights ("Past nights").

## Not built (and why)
- **Team chat and voice notes:** the group already uses WhatsApp.
- **Dog GPS, Garmin, geofences:** no hardware on the estate.
- **Viltrapport and paid tiers:** these are Swedish systems. The Spanish harvest return is plan item 23.
- **Always-on position sharing:** positions are shared only while tracking.
- **Recorded walk-in trails:** background GPS isn't reliable in a PWA.
- **Group day with a stand draw:** a later step that builds on sectors and the board.

## Owner decisions (defaults used)
- The sector safety half-angle is **30°** and the reach is **3 km**. Admins can change both in Settings; check
  them against the Castilla-La Mancha montería rules.
- Roll call nudges **45 min** after the planned out time and escalates **20 min** later. With no plan it assumes
  5 h after the start. There are no roll-call pushes between 08:00 and 16:00.

## Deploy note
`deploy/register-tasks.ps1` gains a **GameSense-Rollcall** task (every 5 minutes). It has to be re-run once,
elevated, on Db01.

## Research sources
- WeHunt site: <https://wehunt.app/en/learn/this-is-wehunt/>, maps: <https://wehunt.app/en/the-app/maps-in-wehunt/>,
  pricing: <https://wehunt.app/pricing/>
- Support centre: <https://support.wehuntapp.com/en/support/solutions/articles/151000213878-what-is-a-hunt-and-how-do-i-use-it->,
  map pins: <https://support.wehuntapp.com/en/support/solutions/articles/151000035876-how-can-i-place-map-pins-in-the-app->,
  hunting ground: <https://support.wehuntapp.com/en/support/solutions/articles/151000036745-how-do-i-create-a-hunting-ground-in-the-app->,
  out-of-bounds zones: <https://support.wehuntapp.com/en/support/solutions/articles/151000036799-how-do-i-create-an-out-of-bounds-zone-on-the-web->
- Safety use: <https://krets.jagareforbundet.se/aneby/sakerhet-wehunt/>
- Reviews: <https://vildmarken.se/reportage/wehunt-4-0-lyfter-jaktupplevelsen/>,
  <https://alltomjaktochvapen.se/jaktnyheter/ny-jaktapp-funktioner-fran-wehunt-tracker-och-burrel/>
