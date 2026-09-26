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
- **Base maps** (`map/basemaps.ts`). All three bases are in one style, and a choice only flips visibility. Nothing calls `setStyle` any more, which is what wiped the drawn layers (B-01, I-11). Each raster has its real max zoom, so MapLibre over-zooms instead of asking for tiles that don't exist (B-24). After four failed tiles in a row on an IGN base, the map shows Aerial (world) and says so in one line. Only base-picture errors raise the banner, and it clears on the next idle once tiles load. **Try again** re-asks only for the failed tiles. It does not call `map.refreshTiles()`: in MapLibre 5.24 that marks a failed raster tile "expired", and the next frame throws while drawing a texture that was never made.
- **Crosshair placing** (`map/CrosshairEditor.tsx`). Stands, cameras and bedding corners are placed with a fixed centre cross and a bar under the map. The bar has a 56 px Add corner button, Undo, and Finish shape (from three corners), and shows the live distance from the last corner and the running area. On a phone, taps don't place anything. With a mouse, a click still adds a corner, and double-click zoom is off while drawing (B-13). The bar sits above the tab bar, and nothing opens the keyboard until the shape is named. Leaving with an unsaved outline asks first (B-12).
- **Measure** gives "134 m · north-east". **Me** shows your own position, which stays on the phone.
- **North** resets bearing and pitch, and small accidental twists snap back (B-23).
- **One palette.** `map/map.css` uses only theme tokens. There is a new `--camera` token for camera pins.

## Earlier: arrows, stands and activity comparisons

The map now uses static geographic arrows, so the arrowhead and shaft use the same bearing. The old sprite pointed east at bearing zero, producing a 90-degree mismatch. The header distinguishes where the wind comes from and where it travels, and its indicator follows map rotation. Uncertain flow does not draw an authoritative arrow.

Satellite imagery is quieter, locations use clear camera/stand markers, and a selected stand reveals its scent footprint. Layers are grouped in a compact menu; editing uses a named draft with explicit Save/Cancel. Markers cannot be moved accidentally while browsing. Selected locations have a details control, and the map fits all saved stands as well as cameras and bedding.

Stands retains reservations and sit reporting. It now separates available, your reservations, and other hunters' reservations, excludes cancelled sits, offers cancellation before starting, and links directly to each stand on the map. Controls for another hunter's sit are not offered. Existing records are preserved.

The activity panel no longer presents normalized contrasts as percentage increases. It displays recorded group averages, sample sizes, and measurement ranges. Moon illumination is explicitly distinguished from actual ground-level moonlight; night duration is distinguished from cloud cover. The existing forecast weighting is preserved. These are unadjusted observational comparisons, including daytime detections, not causal findings or counts of unique animals.

Validation: TypeScript and production build passed; all eight compass bearings and arrowhead alignment passed; real MapLibre browser tests passed for selection, layers, draft/save, reservation ownership, cancellation, and comparison tables. Previous photo-navigation and mobile-scroll tests passed. Two isolated Python tests confirm that comparison copy uses actual averages while preserving the forecast weight. Satellite screenshots use sample locations and conditions. Live camera/stand edits were not performed during testing.
