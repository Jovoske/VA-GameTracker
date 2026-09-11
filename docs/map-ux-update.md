# Map, stands, and activity reporting update

The map now uses static geographic arrows, so the arrowhead and shaft use the same bearing. The old sprite pointed east at bearing zero, producing a 90-degree mismatch. The header distinguishes where the wind comes from and where it travels, and its indicator follows map rotation. Uncertain flow does not draw an authoritative arrow.

Satellite imagery is quieter, locations use clear camera/stand markers, and a selected stand reveals its scent footprint. Layers are grouped in a compact menu; editing uses a named draft with explicit Save/Cancel. Markers cannot be moved accidentally while browsing. Selected locations have a details control, and the map fits all saved stands as well as cameras and bedding.

Stands retains reservations and sit reporting. It now separates available, your reservations, and other hunters' reservations, excludes cancelled sits, offers cancellation before starting, and links directly to each stand on the map. Controls for another hunter's sit are not offered. Existing records are preserved.

The activity panel no longer presents normalized contrasts as percentage increases. It displays recorded group averages, sample sizes, and measurement ranges. Moon illumination is explicitly distinguished from actual ground-level moonlight; night duration is distinguished from cloud cover. The existing forecast weighting is preserved. These are unadjusted observational comparisons, including daytime detections, not causal findings or counts of unique animals.

Validation: TypeScript and production build passed; all eight compass bearings and arrowhead alignment passed; real MapLibre browser tests passed for selection, layers, draft/save, reservation ownership, cancellation, and comparison tables. Previous photo-navigation and mobile-scroll tests passed. Two isolated Python tests confirm that comparison copy uses actual averages while preserving the forecast weight. Satellite screenshots use sample locations and conditions. Live camera/stand edits were not performed during testing.
