# Map, stands, and activity reporting update

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
- **The camera sheet shows no photo count.** The API's `sightings` counts frames, bursts and hidden species included. The header now reads "Last photo 3 h ago · Battery 85%" until the sheet can say "Last night: 2 visits".
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
