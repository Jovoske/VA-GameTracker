# Map, stands, and activity reporting update

## September 2026: where the game is, and a night played back

Two more ways to read the cameras' output on the map (`docs/wehunt-features.md`, sections 3 and 4). Map sheet → **View**: **Cameras** (each camera's photo, as before), **Activity** or **Replay**. The view is kept in the address (`?view=activity`), so a reload or Back returns to it. Each view docks its controls under the map; a camera's sheet or the Map sheet puts them away until it closes, and leaving the view brings the normal map back: photos, counts, wind arrows.

- **One rule for a visit** (`backend/app/forecasting/visits.py`). Frames of the same species at the same camera, each within 30 minutes of the one before, are one visit, with its first and last frame, frame count, largest group and first photo. Only photos the detector has checked and kept count, never a hidden species, and a kept photo nobody has named is an "Animal" visit. The camera sheet's "Last night", the activity map, the replay and the nightly statistics (`exposure.visits_by_night`) all count with it, so their numbers agree. `visits_by_night` now also leaves out hidden species and frames not yet checked, as the rest of the app does.
- **The map's night runs 18:00 to 08:00**, the replay's timeline, so dawn is whole. Parts by local hour: dusk 18–22, night 22–03, dawn 03–08. A visit at 07:30 belongs to the night before. The camera sheet's "Last night" still covers 18:00–06:00.
- **Activity** (`GET /api/map/activity?species=<id|all>&part=dusk|night|dawn|all&nights=1|7|30`, any role):
  - A circle at each camera whose **area** is visits per night the camera was working, in one colour (teal, .35 fill, 2 px line), with a two-size key under the filters. A camera that was working and saw nothing is a small empty ring; one that wasn't working gets no circle.
  - Which nights count comes from `camera_nights` (CONFIRMED or PRESUMED_UP). Where that table hasn't caught up (it is rebuilt hourly), the frames decide, as on the camera sheet: checked frames prove the camera was awake, and unchecked ones mean "still checking". A night out of photo credits never counts. Only visits on counted nights are in the rate, so `per_night` is honest.
  - Filters: period (last night, 7 or 30 nights), part of the night, and the animals seen in the period. They are remembered on the phone.
  - Tapping a circle (or the camera's dot) opens a small card with one line, e.g. "Wild boar on 5 of 7 nights, mostly 21–23 h", or "Wild boar on 3 of 5 nights it was working, …" when some nights didn't count. One to three visits are given by their times ("at 19:40, 23:10 and 02:15"); otherwise the busiest two hours ("mostly" for more than half the visits, "busiest" for a third, "at no set time" below that). The numbers are behind a fold, and **Open camera** opens its sheet. The map moves so the circle stays above the card.
  - Empty periods say "No visits in this period." No signal says so, keeps the circles, and has Try again.
- **Replay** (`GET /api/map/replay/nights?limit=14`, `GET /api/map/replay?night=YYYY-MM-DD`, any role):
  - A night picker (the last 14 finished nights with their visit counts), a timeline from 18:00 to 08:00 with a tick for each visit, play/pause (56 px), −5/+5 min and speed **1× / 10× / 60×**. The speeds are minutes of the night per second, so 1× is an hour in a minute, 10× an hour in 6 seconds and 60× an hour a second. The timeline is a real slider across the whole bar: drag anywhere with a thumb or glove, or use the arrow keys.
  - As the clock passes a visit, it pops up at its camera with its photo, the animal and the time, then fades. The newest is on top, and each goes on the side of its camera that keeps it on the map, off a newer photo and off a fresh arrow. Tapping one opens the photo viewer, which pages through the night.
  - When the same species reaches a different camera within 3 hours of leaving the last one, a faint dashed arrow joins them once the second visit happens, labelled "Likely went this way". The bar says it is a guess. Overlapping visits and ones the animals couldn't have walked (over 15 km/h between the cameras) are never joined, and nor are unnamed animals.
  - Everything drawn follows the clock, so scrubbing back takes photos and arrows off again.
- **Fits.** Entering Activity or Replay fits the placed cameras above the docked bar. `fitEstate` now shrinks its padding when the map is small. Before, a phone on its side with a bar open asked MapLibre for a camera at NaN and took the page down.
- **No migration.** Nothing new is stored.

## September 2026: photos on the map

The cameras' output is now on the map, WeHunt-style (`docs/wehunt-features.md`, section 2).

- **Each camera is its latest photo.** Every placed camera shows its newest animal photo as a 56 px framed thumbnail, with a pointer down to the camera. A white count shows the photos that are new to *you* ("5", "99+"). A camera with no photo keeps its plain round mark. Further out than zoom 13 the photos collapse to the round marks, which still carry the count. Map sheet → Show on map → **Camera photos** turns the photos and counts off, and the phone remembers the choice. A photo that doesn't load (no signal) leaves the plain mark, not an empty frame.
- **"New" is per person** and kept on the server (`camera_views`, migration `0017_camera_views`). Opening a camera's sheet calls `POST /api/cameras/{id}/seen`, which any role may do, and the count clears. A camera you have never opened counts the last 24 hours.
  - What `/seen` records is the arrival stamp of the camera's newest photo, not the time you looked. A sync stamps its photos with its own start and shows them when it commits, so a photo that was still on its way when you looked counts as new once it shows. The SPYPOINT sync now commits camera by camera, as the UBox sync does, so each camera's photos show as soon as that camera is done.
  - New also means recent: only photos taken since a few days before the newest one you had seen. A late upload from a camera that was out of signal is news; a history import (a new account's two months, an admin backfill) doesn't light up the badge.
  - Only photos the detector has checked and kept count, and only they become the camera's map photo. Most frames turn out empty, so an unchecked one would show grass and a count that drops back 15 minutes later. The camera strip asks `/photos?checked=true` for the same reason; the Photos page still shows everything.
  - The count reads an index on `images (camera_id, created_at)` (migration `0018_image_arrivals`) and stops at 100. With 200,000 photos, `/map/cameras` takes about 50 ms rather than 500–700 ms.
- **The camera sheet** (`map/CameraSheet.tsx`) shows:
  - the name, and "Last photo 21:40 (2 h ago)";
  - battery and signal in words, with the numbers one tap away, and a line when the camera isn't checking in or is out of credits;
  - **"Last night: Wild boar · 2 visits, Red deer · 1 visit"**. These are visits, not frames, over 18:00–06:00 of the last finished night, in the same words as the photo tiles. A kept photo nobody has named yet is an "Animal" visit. `last_night_status` says how far to trust the list, and the line follows it:
    - the camera was working and nothing came: "Nothing on camera last night";
    - frames still waiting for the detector: "Still checking last night's photos." (or a note under the visits);
    - it ran out of photo credits partway: "…so this may not be everything";
    - it sent nothing and may have been down: "No photos from last night. The camera may not have been working, so that isn't a quiet night.";
  - a strip of its latest photos, one tile per burst, that opens the photo viewer;
  - **See all photos**, which opens Photos on this camera;
  - Move (admins) and Rename (admins and members).
- **A tap on a camera's photo** opens that camera, unless another pin is under the finger (zoomed in, a photo can cover a stand close by); then it asks "Which one?", as a tap on overlapping pins does.
- **The photo viewer** loads the photos either side of the one showing, so a swipe doesn't stop on "Loading photo…".
- **One call for the map.** `GET /api/map/cameras` returns every camera's position, health, latest photo, new count and last night in four queries, whatever the number of cameras. Hidden species and photos marked "nothing in it" never show and never count, not even as a camera's thumbnail.
- **Small copies of photos.** `GET /api/images/{id}/thumb` (same sign-in as `/file`) serves a 320 px-wide WebP. It is made on first request with EXIF rotation applied, kept under `MEDIA_ROOT/thumbs/`, and recorded in `images.thumbnail_path`. It is cached for a year (`immutable`). If it can't be made, the original is sent uncached, and the small copy outlives an original that retention has pruned. Photos, Cameras, Animals, the Insights drill-down, the map and the camera strip all use it. The photo viewer still opens the full photo (C-04, I-18, J-14 for grids).

## September 2026: the map as the page (WeHunt-style)

The map now fills the screen down to the tab bar. Everything that sat below it moved onto it.

- **Round buttons.** Map sheet, North and Fit estate are on the right. Measure and Me are on the left and ride on top of the bottom sheet. The scale is a pill at the top centre. MapLibre's zoom and compass controls are gone. The attribution button is 44 px (B-16).
- **Bottom sheet** (`map/BottomSheet.tsx`). Tapping a stand, camera or bedding opens it at half height, with snaps at 112 px, 50% and 90%. It holds everything the peek card and the panel below the map used to: the wind verdict, Reserve, Move, Rename, Remove and See photos. Errors show next to the button that failed (B-11). "See photos" opens that camera's photos (B-21). The camera's sheet lives in `map/CameraSheet.tsx`, ready for its photos.
- **Map sheet** (`map/MapSheet.tsx`) has four sections:
  - Map type: Aerial (IGN PNOA), Topo (IGN MTN) and Aerial (world) (Esri), plus Property lines (Catastro).
  - Show on map: the layer switches and the key.
  - Tools: Measure, Me, and for admins Add a stand, Draw bedding, Place for unplaced items, and Load the hill shape.
  - Size: "Bigger pins and names".
  Choices are remembered on the phone.
- **Base maps** (`map/basemaps.ts`). All three bases are in one style, and a choice only flips visibility. Nothing calls `setStyle` any more, which is what wiped the drawn layers (B-01, I-11). Each raster has its real max zoom, so MapLibre over-zooms instead of asking for tiles that don't exist (B-24). If an IGN base gets not one tile through (four or more fail), the map shows Aerial (world) and says so in one line. Only base-picture errors raise the banner, and it clears on the next idle once tiles load. **Try again** re-asks only for the failed tiles. It does not call `map.refreshTiles()`: in MapLibre 5.24 that marks a failed raster tile "expired", and the next frame throws while drawing a texture that was never made.
- **Crosshair placing** (`map/CrosshairEditor.tsx`). Stands, cameras and bedding corners are placed with a fixed centre cross and a bar under the map. The bar has a 56 px Add corner button, Undo, and Finish shape (from three corners), and shows the live distance from the last corner and the running area. On a phone, taps don't place anything. With a mouse, a click still adds a corner, and double-click zoom is off while drawing (B-13). The bar sits above the tab bar, and nothing opens the keyboard until the shape is named. Leaving with an unsaved outline asks first, by tab, Back or the back gesture (B-12).
- **Measure** gives "134 m · north-east". **Me** shows your own position, which stays on the phone.
- **North** resets bearing and pitch, and small accidental twists snap back (B-23).
- **One palette.** `map/map.css` uses only theme tokens. There is a new `--camera` token for camera pins.

### After review

- **Cameras first where pins overlap.** A camera usually sits a few metres from its stand, so at estate zoom the stand pin used to swallow every tap on the camera. Cameras are now drawn on top, and a tap that lands on more than one pin opens **Which one?** with a row for each (`map/pins.ts`, `map/PickSheet.tsx`). Names show from zoom 16. A name that would land on another pin flips to the other side, and waits for more room if that side is taken too.
- **The camera sheet shows no photo count.** The API's `sightings` counts frames, bursts and hidden species included. The header read "Last photo 3 h ago · Battery 85%" until the sheet could say "Last night: 2 visits", which it now does (see "Photos on the map" above).
- **No signal is not calm air.** With no map data the wind bar reads "Wind not loaded". "Too light to call" needs a loaded forecast, and a night with no forecast says "No wind forecast".
- **Nothing spins forever.** `api()` takes `timeoutMs`. Saves, renames and removes on the map give up after 20 s with "No answer from the server. Your outline is kept." Cancel stays live while saving and drops the request. The browser's own "Failed to fetch" is replaced everywhere by "No signal. Try again when you have a connection."
- **Back asks too.** The app now uses a data router (`createBrowserRouter`), so the map's `useBlocker` guards an unsaved outline against the tabs, the browser's Back and the phone's back gesture.
- **The open sheet lives in the address** (`?camera=`, `?stand=`, `?zone=`). Back from a camera's photos comes back to its sheet.
- **Fallback only on an outage.** The switch to Aerial (world) waits until the map settles (`idle`, with a repaint asked for after a failed tile, because MapLibre doesn't repaint on its own). It then happens only if nothing of the IGN picture got through. A partly failing base keeps its banner and Try again. Tapping the chosen map type retries it, and the fallback line can be dismissed.
- **Drawing guards.** Add corner rests until the cross moves off the last corner, so a gloved double press lays one corner. Finish shape waits for an outline that doesn't cross itself, and the hint says why.
- **Smaller fixes.**
  - Fit the estate keeps pins clear of an open sheet.
  - A second tap on a pin while its sheet is closing keeps the sheet open.
  - Escape in a sheet's text field leaves the field and keeps the text.
  - A phone in landscape doesn't scroll.
  - An empty estate says what to do, and admins get Add a stand.
  - Me points the heading triangle with the phone's compass while you stand still.

## Earlier: arrows, stands and activity comparisons

The map now uses static geographic arrows, so the arrowhead and shaft use the same bearing. The old sprite pointed east at bearing zero, producing a 90-degree mismatch. The header distinguishes where the wind comes from and where it travels, and its indicator follows map rotation. Uncertain flow does not draw an authoritative arrow.

Satellite imagery is quieter, locations use clear camera/stand markers, and a selected stand reveals its scent footprint. Layers are grouped in a compact menu; editing uses a named draft with explicit Save/Cancel. Markers cannot be moved accidentally while browsing. Selected locations have a details control, and the map fits all saved stands as well as cameras and bedding.

Stands retains reservations and sit reporting. It now separates available, your reservations, and other hunters' reservations, excludes cancelled sits, offers cancellation before starting, and links directly to each stand on the map. Controls for another hunter's sit are not offered. Existing records are preserved.

The activity panel no longer presents normalized contrasts as percentage increases. It displays recorded group averages, sample sizes, and measurement ranges. Moon illumination is explicitly distinguished from actual ground-level moonlight; night duration is distinguished from cloud cover. The existing forecast weighting is preserved. These are unadjusted observational comparisons, including daytime detections, not causal findings or counts of unique animals.

Validation: TypeScript and production build passed; all eight compass bearings and arrowhead alignment passed; real MapLibre browser tests passed for selection, layers, draft/save, reservation ownership, cancellation, and comparison tables. Previous photo-navigation and mobile-scroll tests passed. Two isolated Python tests confirm that comparison copy uses actual averages while preserving the forecast weight. Satellite screenshots use sample locations and conditions. Live camera/stand edits were not performed during testing.
