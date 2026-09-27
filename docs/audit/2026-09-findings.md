# GameSense audit — verified findings (26 Sep 2026)

Companion to [`../improvement-plan.md`](../improvement-plan.md). Ten auditors each covered one area of the app, and a completeness pass looked for gaps. An independent verifier then tried to refute every finding against the code; most of them were reproduced with a test or a Playwright run. 269 of 271 findings survived (confirmed or plausible). They are grouped here by plan item, most severe first. Line numbers are as of commit `fe8f228`.

Severity is the verifier's calibrated rating. Verdict: **confirmed** = reproduced or proven from the code; **plausible** = the code path holds but could not be fully exercised here.

Refuted and left out: H-16 (Night and date keys use the server's clock date, not Madrid's), I-17 (Nothing is compressed: slow first load on 3G).


## 1. App never goes blank

### B-02 — If the lazy Map chunk fails to load (offline before the first map visit, or any deploy while the PWA is open), the whole app goes blank

*high · confirmed · reliability · effort S* — `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/public/sw.js`, `deploy/update.ps1`

- **What the hunter sees:** A hunter who leaves the app open and taps Map after the owner pushes an update, or who first opens the map in a dead valley, gets a black screen with no navigation. They have to kill and relaunch the app.
- **Evidence:** App.tsx:24 `lazy(() => import('./pages/Map'))` sits inside <Suspense> (App.tsx:59) with no error boundary anywhere (no componentDidCatch/getDerivedStateFromError in src). update.ps1:68-72 rebuilds and robocopy /MIR's dist, which deletes the old hashed Map-*.js. The native server mounts /assets with StaticFiles → 404. sw.js:89-102 is network-first and only falls back to its cache when fetch THROWS, so a 404 goes straight through. Offline, it answers a missing script with index.html. PROVEN with Playwright (s_chunk.cjs): Map chunk served as 404, open /stands, tap the Map tab → pageerror 'Failed to fetch dynamically imported module', #root innerHTML length 0, no nav left.
- **Verifier:** I reproduced it (verify-B/s_chunk.cjs against a fresh build): with Map-*.js returning 404, tapping Map empties #root to length 0 and leaves 0 nav links. No ErrorBoundary exists anywhere in src (grep). The SW (sw.js:89-102) passes a 404 straight through. Offline, it answers the script request with index.html (sw.js:101). update.ps1 uses robocopy /MIR, which deletes the old hashed chunks.
- **Fix:** As proposed: an ErrorBoundary around the /map Suspense (ideally around the Layout outlet too). On a chunk-load error, reload once, with a sessionStorage guard against reload loops. Also add `window.addEventListener('vite:preloadError', ...)`. In sw.js, fall back to index.html only when `req.mode === 'navigate'`; for other requests return the cached copy or `Response.error()`. Optionally stop /MIR from deleting old /assets files.

### C-02 — Coming back to the app with a photo open deep in the feed crashes the whole app (blank screen); otherwise the list silently drops back to the first 60

*high · confirmed · bug · effort M* — `frontend/src/pages/Photos.tsx`, `frontend/src/components/PhotoLightbox.tsx`, `frontend/src/hooks.ts`

- **What the hunter sees:** A hunter going through last night's photos switches to WhatsApp to share one, comes back and gets a black or blank app, or a different animal than the one they were looking at, or loses their place in the list.
- **Evidence:** Photos.tsx:95 useRefetchOnReturn(load, 120_000). load() does setPhotos(page.items) (line 87), which replaces every loaded page with the newest 60. The open lightbox receives the new, shorter array (line 225), but its idx state (PhotoLightbox.tsx:59) is not re-clamped, so `im = photos[idx]` is undefined and line 289 `new Date(im.captured_at)` throws. The app has no ErrorBoundary. PROVEN with Playwright (pw.cjs scenarioLightboxCrash): load 240 photos, open #151 ('PL19 · Photo 151 of 240'), move Date.now forward 3 min and fire focus. Result: TypeError "Cannot read properties of undefined (reading 'captured_at')" and #root innerHTML length 0. If idx < 60 there is no crash, but the viewer silently jumps to a different photo when new ones arrived. With no lightbox open, the grid collapses from N pages to 60 and the scroll position is lost.
- **Verifier:** Reproduced: loaded 240 photos, opened #151, advanced the clock 3 minutes and fired focus. Result: TypeError reading 'captured_at' and #root innerHTML length 0. load() replaces the list with 60 items (Photos.tsx:87), PhotoLightbox keeps idx (line 59), so im is undefined and line 289 throws. There is no ErrorBoundary anywhere (grep finds none; main.tsx renders App bare). Opening the share sheet from the lightbox can itself fire visibilitychange and set this off.
- **Fix:** The proposed fix is right. Minimum version: in Photos, skip the return refetch while zoom != null, and have the refetch prepend only photos newer than photos[0] instead of replacing the loaded pages. In PhotoLightbox, clamp or track by id and return null plus onClose() when !im. Add a top-level ErrorBoundary with a Reload button.

### D-01 — Tapping Map after a deploy, or offline before it was ever opened, blanks the whole app

*high · confirmed · bug · effort S* — `frontend/src/App.tsx`, `frontend/public/sw.js`, `frontend/src/main.tsx`, `deploy/update.ps1`

- **What the hunter sees:** If the app has stayed open since the last deploy (normal for an installed PWA), or there is no signal, tapping Map wipes the screen with no way back except killing the app.
- **Evidence:** App.tsx:24 lazy-loads Map, and App.tsx:59 wraps it in <Suspense> only. There is no error boundary anywhere (grep for ErrorBoundary/componentDidCatch/vite:preloadError finds nothing), so a failed chunk import unmounts the whole React root. Trigger 1 (deploy): deploy/update.ps1 runs robocopy /MIR, which deletes the old hashed chunks, and FastAPI's /assets StaticFiles then answers 404. The SW passes that 404 through, because sw.js:90 is network-first and only falls back to the cache on a thrown error. Trigger 2 (offline): sw.js:101 answers a script request that has no cache hit with the cached /index.html, which fails the module MIME check. PROVEN with Playwright against the real dist build (scratchpad/D/pw/deploy_and_login.cjs and offline.cjs). The test opened Tonight, renamed Map-*.js to simulate the deploy, then tapped Map: '#root children = 0' plus 'Failed to fetch dynamically imported module'. Offline, tapping Map for the first time gave '#root children = 0' plus 'Expected a JavaScript module script but the server responded with text/html'. The hunter sees a blank dark screen with no tab bar and has to force-quit the PWA.
- **Verifier:** I re-ran both Playwright scenarios against the current dist. After the deploy (Map chunk renamed), tapping Map left '#root children = 0' with 'Failed to fetch dynamically imported module'. Offline, sw.js:101 returned index.html for the script and the page blanked the same way. App.tsx:59 has only <Suspense> and there is no error boundary anywhere, and update.ps1:72 uses robocopy /MIR, which deletes the old chunks, so the next import gets a 404.
- **Fix:** The ErrorBoundary is the actual fix. Put it around <Outlet/> in Layout, keyed on location.pathname so moving to another tab clears it, and give it Retry/Reload. The vite:preloadError listener does work in this build: Vite 5.4.21's helper runs `t().catch(l)`, so it fires when the import itself fails. Guard it with a sessionStorage flag so an offline reload can't loop. Changing sw.js so script/style misses return Response.error() only makes the error clearer.

### I-01 — Coming back to the app with a photo open blanks the whole app (Photos page)

*high · confirmed · bug · effort M* — `frontend/src/pages/Photos.tsx`, `frontend/src/components/PhotoLightbox.tsx`, `frontend/src/main.tsx`

- **What the hunter sees:** A hunter flicks through last night's photos, checks a message, comes back and gets a black screen. Only a reload fixes it, and their place in the feed is gone.
- **Evidence:** Photos.tsx:81-95. On return, useRefetchOnReturn(load, 120_000) calls load(), and load() does setPhotos(page.items), which puts the list back to the first 60. The lightbox keeps its own idx (PhotoLightbox.tsx:59), so im = photos[idx] is undefined and im.captured_at throws at line 289. main.tsx:12-18 has no error boundary, so React unmounts everything. Proven with the scratch script I/f_photos.cjs: open Photos, tap 'Show older photos' (120 loaded), open photo 101, fast-forward the clock 3 min, fire focus/visibilitychange. Result: pageerror "Cannot read properties of undefined (reading 'captured_at')" and #root innerHTML length 0. Screenshot: shots/photos_lightbox_after_return.png (all dark). The same refetch also throws away the pages already scrolled through. If new photos arrived, the open lightbox also jumps to a different photo.
- **Verifier:** Reproduced (verify-I/v_photos.cjs): 120 loaded, photo 101 open, clock +3 min, focus led to pageerror "Cannot read properties of undefined (reading 'captured_at')" and #root length 0. The cause: load() replaces the list with the first page (Photos.tsx:87), the lightbox idx is state that is never re-clamped (PhotoLightbox.tsx:59-60, 289), and there is no error boundary anywhere in src.
- **Fix:** Refresh on return should skip while zoom != null. It should fetch only the head of the feed and prepend new ids, keeping the pages already loaded. Photos should pass the lightbox a stable snapshot, as Cameras.tsx:500 does with zoom.photos, or the lightbox should track by id. PhotoLightbox should render nothing if photos[idx] is missing. Add an ErrorBoundary around <Outlet/> with a Reload button.

### D-18 — After a deploy, open apps can keep stale code: no cache headers, HTML returned for unknown API paths, and no update prompt

*medium · confirmed · reliability · effort M* — `backend/app/main.py`, `frontend/src/api.ts`, `frontend/src/main.tsx`

- **What the hunter sees:** After an update, cryptic red errors ('Unexpected token <') or a blank page (with D-01) until the hunter happens to fully restart the app.
- **Evidence:** The _spa catch-all (main.py:79-89) returns index.html with 200 for any unmatched GET, including /api/*. It sets no Cache-Control on index.html, sw.js or /assets, so browsers apply heuristic freshness to index.html (10% of its age since Last-Modified), and Cloudflare caches .js by default. PROVEN via TestClient with FRONTEND_DIST set: GET /api/forecast/tonite and /api/stands/x/extra/x return 200 text/html; '/', '/sw.js' and '/assets/index-*.js' all have cache-control None. When an old bundle calls an endpoint that has been renamed, api() (api.ts:52) throws JSON parse 'Unexpected token '<''. FastAPI 422 bodies (detail is an array) become 'Error: [object Object]' (api.ts:47). main.tsx:20-23 registers the SW but nothing compares versions, so an installed PWA that stays in memory runs the old bundle indefinitely.
- **Verifier:** Checked with TestClient and FRONTEND_DIST set: GET /api/forecast/tonite and /api/stands/x/extra/x both return 200 text/html from _spa (main.py:79-89). '/', '/sw.js' and '/assets/index-*.js' carry no Cache-Control, only ETag and Last-Modified. api.ts:47 turns a 422 array detail into '[object Object]', and api.ts:52 fails parsing HTML. Nothing compares versions after main.tsx:20-23 registers the SW.
- **Fix:** No change needed; the proposed fix is fine as written.

### H-06 — After a deploy, an open or installed app can go blank: old chunks are deleted, index.html may be cached, and there is no error boundary

*medium · confirmed · ux · effort S* — `deploy/update.ps1`, `backend/app/main.py`, `frontend/public/sw.js`, `frontend/src/App.tsx`

- **What the hunter sees:** A hunter with the PWA open or suspended since before a push taps Map (or reopens the app with a stale index.html) and gets a white screen until a hard refresh. This can happen at dusk, whenever the owner pushes.
- **Evidence:** robocopy /MIR (update.ps1:72) deletes the previous hashed assets, including the lazily loaded Map chunk (App.tsx:24). index.html is served with Last-Modified and no Cache-Control (PROVEN with TestClient: cache-control=None, last-modified set). Browsers therefore cache it heuristically (about 10% of its age), and the service worker's network-first fetch (sw.js:89-102) goes through that HTTP cache. The service worker only falls back to its cache on a network error; a 404 for the deleted chunk is passed straight through. No ErrorBoundary exists anywhere in frontend/src (grep).
- **Verifier:** robocopy /MIR (update.ps1:72) deletes the old hashed chunks, and a missing asset returns 404 from the /assets StaticFiles mount (verified). sw.js:89-98 passes a non-ok response straight through instead of falling back to its cache. MapPage is React.lazy (App.tsx:24) and there is no ErrorBoundary anywhere in src, so a rejected chunk unmounts the whole root. index.html is served with Last-Modified and no Cache-Control (verified). Not driven in a browser, but every link in the chain was checked.
- **Fix:** Cheapest fix: in main.tsx, add window.addEventListener('vite:preloadError', () => location.reload()) (Vite 5.4 supports it), plus a small route-level ErrorBoundary that reloads once on a chunk-load error. Copy web\assets without /MIR and prune files older than 14 days. Serve index.html and sw.js with Cache-Control: no-cache.

### I-06 — After an update the app can open to a blank screen (index.html cached, old bundle gone)

*medium · plausible · reliability · effort S* — `backend/app/main.py`, `frontend/public/sw.js`

- **What the hunter sees:** After the owner runs the update, hunters can get a black app until the browser cache expires (hours to days). Many will conclude the app is broken.
- **Evidence:** main.py:74-89 serves index.html (and sw.js) as FileResponse with Last-Modified/ETag but no Cache-Control, so browsers cache index.html by heuristic. The service worker's navigation fetch (sw.js:89-103) goes through the HTTP cache. It also passes a 404 for a script straight through and only falls back to its cache on a network error. Proven with I/f_deploy.cjs on :8013: index.html mtime set to 30 days ago; open the app with the service worker active; then 'deploy' (new bundle name, old index-*.js deleted, as vite build --emptyOutDir does); then open '/' normally. Result: 404 /assets/index-BekHVFbG.js and #root empty. Screenshot: shots/after_deploy_blank.png.
- **Verifier:** The mechanism is real. main.py:77-89 sends Last-Modified with no Cache-Control, the production deploy uses robocopy /MIR, which deletes old hashed assets (deploy/update.ps1:72), and sw.js:89-103 passes a 404 straight through. But the repro back-dated only index.html's mtime. In production index.html and the JS share the build mtime, so they get the same heuristic freshness. The likelier real failure is a stale index.html plus the never-fetched lazy Map chunk returning 404, with no error boundary; the main bundle blanking is less likely.
- **Fix:** Send Cache-Control: no-cache for index.html, sw.js and the SPA fallback, and 'public, max-age=31536000, immutable' for /assets. Stop /MIR from purging old assets/ on deploy (keep the previous build's hashed files). Wrap lazy(() => import('./pages/Map')) so a chunk-load error triggers one location.reload(). In sw.js, fall back to caches.match when a script or style response is not ok.

### K-02 — With a server or tunnel outage and signal on the phone, the installed app opens on a Cloudflare error page instead of the saved plan

*medium · confirmed · reliability · effort S* — `frontend/public/sw.js`, `deploy/update.ps1`, `docs/09-handoff.md`

- **What the hunter sees:** Any restart, Windows update or tunnel drop at dusk replaces the whole standalone app with a full-screen Cloudflare error. There is no back button and no saved plan, even though the plan is in the cache.
- **Evidence:** Phones reach Db01 through cloudflared (docs/09-handoff.md:31, https://gamesense.daa-ops.com). When Db01 is rebooting, restarting on a deploy (update.ps1:151) or its tunnel is down, Cloudflare answers every request with a 502/530 HTML page. sw.js:89-103 returns any fetch() that resolves, so a 5xx navigation is passed straight through and the cached shell is only used on a thrown network error. sw.js:44-64 does the same for the API: the cached copy is only used in catch. PROVEN with Playwright (scratchpad/K/pw/origin_down.cjs and origin_down_api.cjs, real built SW). The app is loaded online, then the origin returns 530: reload gives title 'Cloudflare Tunnel error', body 'Error 1033'. The same app truly offline shows 'Plan from just now…'. With a 502 origin, fetch('/api/stands') gives '502 stale=null <html>' and the Stands page says 'Couldn't load stands. Something went wrong (50…'. Truly offline it gives '200 stale=true' with the cached stands. Not covered by D-09/J-06 (slow network) or I-05 (offline label).
- **Verifier:** I re-ran origin_down.cjs against the real built sw.js. With the origin returning 530, a reload shows 'Cloudflare Tunnel error / Error 1033'. Truly offline, the same reload shows 'Plan from just now…'. The cause is sw.js:89-103 and :46-63: fetch() resolves on a 5xx, so the cache is only used in catch. Downgraded from high because a deploy restart is only about 8-10 s (update.ps1:151-158). The real exposure is longer Db01 or tunnel outages.
- **Fix:** Navigation branch: if req.mode==='navigate' and res.status>=500, return (await caches.match('/index.html')) || res. apiWithFallback: if !res.ok and res.status>=500, return the cached copy with X-GameSense-Stale when there is one, otherwise return res. Treat only 5xx (500-530) as an outage; 401 and other 4xx must still pass through, because api.ts relies on 401 to sign the user out.

### K-03 — The first launch never caches the app's own code, so the next launch without signal is a blank screen

*medium · confirmed · reliability · effort M* — `frontend/public/sw.js`, `frontend/src/main.tsx`

- **What the hunter sees:** A hunter installs the app at the lodge, opens it once, and in the valley gets a white screen instead of tonight's plan.
- **Evidence:** sw.js:19/26 precaches only ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png']. Hashed JS and CSS are cached only when they are fetched *through* the worker (sw.js:89-97). main.tsx:20-24 registers the worker on 'load', after index-*.js and index-*.css have already been fetched from the network, so they are never stored. iOS gives a home-screen app its own storage partition, so the first launch after 'Add to Home Screen' (log in, look around) is exactly this first visit. PROVEN with Playwright (scratchpad/K/pw/first_visit_offline.cjs, real build and SW). After a full first session (Tonight, Photos, Stands, Cameras, SW controlling), the cache holds only the four shell files. '/assets/index-BekHVFbG.js -> in cache? false'. The next launch offline: #root has 0 children, and the console shows 'Expected a JavaScript-or-Wasm module script but the server responded with a MIME type of "text/html"'. This is different from B-02/D-01 (lazy Map chunk) and H-06 (post-deploy): here the main bundle is never cached on first use. Other audits' offline proofs reloaded once online first, which hides this.
- **Verifier:** I rebuilt the app (identical hashes to the auditor's copy) and re-ran first_visit_offline.cjs. The cache held only the 4 SHELL files, index-BekHVFbG.js was not cached, and the offline relaunch gave an empty #root with a MIME error. main.tsx:20-24 registers the worker on 'load', after the bundle has already downloaded. It is less severe than claimed: Starlette StaticFiles sends Last-Modified/ETag, and when my server sent a 72 h old Last-Modified, the browser's heuristic HTTP cache served the bundle and the offline relaunch rendered. So the blank screen only happens after about 10% of the build's age has passed, and only before a second online launch.
- **Fix:** On install, fetch('/index.html'), pull out its /assets/*.js and *.css URLs (or read a Vite build manifest listing every chunk, including Map and the fonts), and cache.addAll them together with SHELL. Change the CACHE name so existing clients re-install. Serving /assets with 'Cache-Control: public, max-age=31536000, immutable' also closes most of the gap cheaply.

### D-20 — The service worker keeps every build's JS and every visited URL forever

*low · confirmed · perf · effort S* — `frontend/public/sw.js`

- **What the hunter sees:** Storage on hunters' phones grows by roughly 0.5–1.5 MB per deploy, and on iOS storage pressure the OS can evict the whole origin, including the push registration.
- **Evidence:** CACHE is the constant 'gamesense-v2' (sw.js:17), and activate only deletes caches with other names. The fetch handler (sw.js:93-97) runtime-caches every script, style, font and image and every navigation URL, including each query-string variant such as every notification's /photos?species=…&image=…. Nothing is ever pruned. The current build is about 1.5 MB (Map chunk 1.07 MB, index 327 KB, CSS 113 KB), and there were about 40 frontend commits in the last 2 months, each auto-deployed. Not measured on a device.
- **Verifier:** The code is clear: CACHE is the constant 'gamesense-v2' (sw.js:17), activate only deletes caches with other names, and sw.js:93-97 stores every script/style/font/image and every navigation URL including query strings. git log shows 40 frontend commits since 2026-07-26. The growth is real but a few tens of MB, and the iOS eviction consequence is speculative.
- **Fix:** The 'prune on activate' option won't run: sw.js is byte-identical across deploys, so install/activate never fires again. Stamp a build id into sw.js at build time (a small Vite plugin or a define step) so every deploy installs a new worker. Then prune /assets/ entries not referenced by the new index.html, and cache navigations under a single '/index.html' key.

### K-14 — Crashes and blank screens on hunters' phones are invisible to the owner

*low · confirmed · reliability · effort S* — `frontend/src/main.tsx`, `frontend/src/App.tsx`, `backend/app/main.py`

- **What the hunter sees:** Bugs hunters hit in the field never reach the person who can fix them, so they keep recurring.
- **Evidence:** src/ has no ErrorBoundary, componentDidCatch, window.onerror or unhandledrejection handler (grep finds none), and there is no client-log endpoint. Known blank-screen paths (C-02 lightbox crash, B-02/D-01 chunk failure, K-03 first-launch offline) therefore leave no trace anywhere. The owner's 'some things still feel a bit buggy' can only be reproduced by hand. H-06 notes the missing boundary as one cause of post-deploy blanks; the missing reporting is not covered.
- **Verifier:** grep finds no ErrorBoundary, componentDidCatch, getDerivedStateFromError, window error or unhandledrejection handler in frontend/src. The backend has no client-error endpoint. App.tsx renders routes, including a lazy Map, with no boundary, so an uncaught render error blanks the whole tree with no trace. The missing boundary overlaps H-06; the missing error reporting is what this finding adds.
- **Fix:** Add a top-level ErrorBoundary with a 'Something broke. Reload' screen. It should also reload once on ChunkLoadError. Add window 'error' and 'unhandledrejection' listeners that POST {message, stack, route, build} to a new rate-limited /api/client-errors, which logs via structlog. Show the last N entries in Settings for admins.


## 2. Sit reports are never lost or overwritten

### A-01 — Sit mode: any later tap overwrites the outcome, and offline taps replay over newer ones (Shot becomes Saw animals)

*high · confirmed · data-correctness · effort M* — `frontend/src/pages/SitMode.tsx`, `backend/app/api/routes_stands.py`

- **What the hunter sees:** A hunter shoots a boar and taps SHOT. The report then silently becomes 'Saw animals' or 'Saw nothing' if any of these happens: a glove or pocket brushes the full-screen button, a hold registers, or an earlier no-signal tap replays at END SIT. The app's only ground truth is lost. Stands then shows 'Reported: saw animals' with no way to correct it.
- **Evidence:** SitMode.tsx:135-147 record() PATCHes {outcome} on every tap. The whole screen below the header is the SAW ANIMALS button (SitMode.tsx:227-271), and a 1.2 s hold writes 'nothing'. routes_stands.py:329 update_sit sets `sit.outcome = body.outcome` unconditionally. Queued items (SitMode.tsx:35-43) store `at`, but flushSitQueue (45-65) ignores it and replays in queue order at END SIT or when Stands mounts. PROVEN: scratch pytest test_later_tap_overwrites_shot_and_first_tap_sets_ended_at (seen, then shot, then seen ends as 'seen'). Also Playwright pw_tonight_sit.cjs S1: tap SAW ANIMALS with no signal (queued), tap SHOT with signal (server=shot), tap END SIT. The flush replays 'seen', so the server's final outcome is 'seen' and PATCH order is ['shot','seen'].
- **Verifier:** Reproduced: backend test shows seen→shot→seen ends as 'seen'. My Playwright rerun gives PATCH order ['shot','seen'] with final 'seen'. update_sit assigns `sit.outcome = body.outcome` unconditionally (routes_stands.py:305; the finding's line numbers for this file are about 24 too high). flushSitQueue ignores `at` (SitMode.tsx:45-65), and Stands only offers 'What happened?' while outcome=='unreported' (Stands.tsx:89,97-100). Downgraded from critical: no backend code reads Sit.outcome today (scoring.py explicitly avoids sits), so the damage is the stored record and the Stands display, not a live calculation.
- **Fix:** Server: rank nothing<seen<shootable_no_shot<shot and keep the higher value. Leave 'cancelled' and 'unreported' out of the ranking. Refuse downgrades unless the body has `correct: true`, which only the Stands correction UI sends. Client: queue one item per sit (the latest or highest) rather than a replay log, so older taps cannot land after newer ones. The optional 'Undo' flash is fine.

### A-02 — Sit report queue: a flush in progress wipes reports queued during it, and a second END SIT tap starts a second flush

*high · confirmed · data-correctness · effort S* — `frontend/src/pages/SitMode.tsx`, `frontend/src/pages/Stands.tsx`, `frontend/src/api.ts`

- **What the hunter sees:** Signal flickers in the valley and the phone starts sending an earlier report. The hunter taps SHOT, it fails and is kept on the phone, and then it is silently deleted. It never reaches the server and no message says so. On weak signal END SIT gives no feedback, which invites the repeated taps that trigger this race.
- **Evidence:** SitMode.tsx:45-65 reads the queue and awaits each PATCH (no timeout, api.ts:31). It then writes `left` back over the whole localStorage key, so any queueWrite() (SitMode.tsx:144) that happens during the await is overwritten. Three things trigger a flush: the 'online' listener (122-133), END SIT (280-284), and Stands mount (Stands.tsx:48). END SIT has no busy state, so a second tap starts a second concurrent flush. PROVEN: Playwright pw_tonight_sit.cjs S2. Start with queue [seen] and dispatch 'online' (the seen PATCH takes 3 s). Tap SHOT with no signal: the queue becomes [seen, shot]. When the flush finishes the queue is '[]' and the server only ever received 'seen'.
- **Verifier:** Reproduced in Playwright S2: the queue is [seen, shot] during the flush, '[]' after it, and the server only ever received 'seen'. The 'saved, no signal' counter also drops to 0 because setPending subtracts the flushed count. flushSitQueue writes a snapshot `left` back over the key (SitMode.tsx:63), and END SIT has no busy guard (SitMode.tsx:280-284). Downgraded from critical, but kept high: with no fetch timeout (api.ts:31) a flush can hang for minutes, so the loss window is wide.
- **Fix:** The proposed fix is right. Also route the 'online' handler and the Stands mount through the same single-flight promise. Pair it with the api() timeout from A-05 so a flush cannot hang indefinitely.

### A-06 — END SIT does not end the sit, the first tap does; Stands then locks the hunter out of Sit mode and out of correcting the report

*high · confirmed · bug · effort M* — `frontend/src/pages/SitMode.tsx`, `frontend/src/pages/Stands.tsx`, `backend/app/api/routes_stands.py`

- **What the hunter sees:** After a blank sit, the hunter taps END SIT and still sees 'Your sit is on' all night, and the record stays 'unreported' instead of 'saw nothing'. A hunter who tapped 'Saw animals' early and then left Sit mode (END SIT by mistake, a reload, or the app killed) cannot get back in to record the later shot.
- **Evidence:** END SIT (SitMode.tsx:280-284) only flushes the queue and navigates; no request marks the sit ended. update_sit sets ended_at on the first outcome other than 'unreported' (routes_stands.py:334-335), which means the first 'Saw animals' tap mid-sit. Stands treats `active = outcome === 'unreported'` (Stands.tsx:89) and shows 'Back to sit' and 'What happened?' only while active (97-100). PROVEN: scratch pytest shows the first 'seen' PATCH sets ended_at and a later 'shot' keeps that time. Playwright S3: END SIT with no taps sends 0 writes, and Stands shows 'Your sit is on' plus 'Back to sit'. After one 'seen' tap, Stands shows 'Reported: saw animals' and only 'Wind details': no way back into Sit mode and no way to report a shot.
- **Verifier:** Reproduced (S3). END SIT with no taps sends 0 writes, and Stands shows 'Your sit is on' plus 'Back to sit'. After one 'seen' it shows only 'Wind details', so there is no way back in and no correction. update_sit sets ended_at on the first non-unreported outcome (routes_stands.py:310-311), and Stands gates everything on outcome==='unreported' (Stands.tsx:89,97). ended_at is not read anywhere else in the backend. The harm is the stuck UI and the unrecordable later shot; every blank sit ends looking still 'on'.
- **Fix:** The proposed fix is right. The minimal version: an end endpoint or `end: true` flag that sets ended_at; update_sit stops setting it; Stands shows 'Back to sit' while started_at && !ended_at; 'What happened?' stays available all night and sends the A-01 correction flag.

### A-07 — Two hunters reserving at the same time can both get the same stand, or stands whose fire lanes cross

*high · confirmed · reliability · effort S* — `backend/app/api/routes_stands.py`, `backend/app/models.py`

- **What the hunter sees:** When a group reserves at once (a 'reserve now' message in the group chat), or during the first request of the day while the weather loads, two hunters can end up in the same seat or in seats whose fire lanes cross. That is exactly what the safety interlock exists to prevent.
- **Evidence:** claim_stand (routes_stands.py:262-311) reads existing claims and checks same-stand and fire-lane conflicts. Only then does it call _tonight_conditions() (a live Open-Meteo request, up to 20 s; weather.py:51) and assess(), and after that it inserts and commits. There is no lock and no unique index on sits(stand_id, night); models.py:456-463 has only plain indexes. PROVEN: scratch test_concurrent_claims_double_book. Two threads, for two users, claim the same stand with a barrier inside assess(). Both calls return a sit id and 2 live sits exist for one stand and night. The same window lets claims on two stands with overlapping shooting arcs both pass the interlock.
- **Verifier:** Reproduced: two concurrent claim_stand calls both return ids, leaving 2 live sits on one stand. Only plain indexes exist on sits (models.py:461-462, alembic 0009). The check runs before _tonight_conditions() (routes_stands.py:239-267), which makes an uncached weather request with timeout=20 on every call while Open-Meteo is failing (weather.py:52-55). That widens the window from milliseconds to seconds, and the same window bypasses the fire-lane interlock.
- **Fix:** The proposed fix is right. Take pg_advisory_xact_lock before the `existing` SELECT, in the same transaction as the INSERT. The partial unique index cannot express fire-lane conflicts, so the lock is the real fix and the index only a backstop. The migration must first de-duplicate any existing live duplicates, or index creation will fail.

### I-02 — Sit Mode's offline queue overwrites a newer 'Shot' with an older queued 'Saw animals'

*high · confirmed · data-correctness · effort M* — `frontend/src/pages/SitMode.tsx`, `backend/app/api/routes_stands.py`

- **What the hunter sees:** The one record that matters, the shot, is silently replaced by 'saw animals'. Sit outcomes are the app's only ground truth for scoring the forecast.
- **Evidence:** SitMode.tsx:135-146: record() PATCHes directly and only queues when a write fails. flushSitQueue (45-65) replays the queue later, in queue order, with no timestamp. routes_stands.py:305 is last-write-wins. Proven with I/f_sit.cjs: reserve Charca stand, Start sit. First PATCH aborted as a weak-signal failure (navigator.onLine stays true, so no 'online' event fires): tap SAW ANIMALS, which queues 'seen' ('1 saved, no signal'). Tap SHOT, which succeeds: server outcome = shot. Tap END SIT (line 282), which flushes the queue: server outcome = seen, ended_at set. Stands then shows 'Reported: saw animals'. Also, queued items that get a 403 or 404 stay in the queue forever. The queue is not cleared on sign-out, so an admin signing in next replays another hunter's outcome.
- **Verifier:** Deterministic from code. record() queues only on failure (SitMode.tsx:141-146), and flushSitQueue replays in FIFO order with no timestamp (45-65). END SIT awaits the flush (282), and PATCH is last-write-wins (routes_stands.py:305). A queued 'seen' therefore overwrites a later successful 'shot'. Any error, 403/404/422 included, keeps the item forever (line 59-60), and sign-out never clears gs_sit_queue.
- **Fix:** Keep one queued entry per sitId holding the latest outcome and client 'at'. Delete that entry when a direct write succeeds. Drop entries on 4xx other than 401/408/429. Server side, store reported_at and ignore PATCHes whose client 'at' is older. Clear the queue on sign-out.

### J-02 — A saved 'Shot' can be overwritten by an older queued 'Saw animals' tap

*high · confirmed · data-correctness · effort S* — `backend/app/api/routes_stands.py`, `frontend/src/pages/SitMode.tsx`, `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** The hunter sees 'Saved: shot', but the register ends up saying 'saw animals'. The only ground-truth write the app gets loses its most important outcome.
- **Evidence:** routes_stands.py:305 sets `sit.outcome = body.outcome` unconditionally, so the last write wins. SitMode.tsx:141-146 queues a failed tap in localStorage. The queue is replayed later: by END SIT (SitMode.tsx:281-283), by the `online` event, or when Stands mounts (Stands.tsx:48). Any of these can happen after a newer tap has already saved. Sequence: at 20:10 SAW ANIMALS is tapped with no signal and queued; at 20:40 one bar comes back and SHOT saves; END SIT flushes the queue and PATCHes 'seen'. PROVEN by a scratch API test: PATCH shot, then PATCH seen, leaves outcome='seen'. Also, the 'Some sit reports couldn't send' branch in Stands.tsx:48 can never run because flushSitQueue never rejects, so reports that fail again stay on the phone silently. SitMode's pending counter restarts at 0 whenever the page mounts again.
- **Verifier:** routes_stands.py:305 overwrites the outcome unconditionally. SitMode.tsx:141-146 queues failed taps, and they are replayed after newer writes by END SIT (281-283), the online event (122-133) and the Stands mount (Stands.tsx:48). No network failure is even needed: the big button is SAW ANIMALS, so tapping it after SHOT when more animals come also downgrades the sit. flushSitQueue catches every error, so the .catch branch at Stands.tsx:48 can never run.
- **Fix:** Server: rank shot > shootable_no_shot > seen > nothing > unreported and never lower a sit's outcome unless the request sets `override: true`. Only the Stands edit sends it, and today that edit only appears while outcome=='unreported' (Stands.tsx:97), so it must also be shown for reported sits. Client: queued items already carry `at`; replay them oldest first, drop items older than the last successful write, and return the pending count instead of throwing.

### A-17 — Sit mode loses the keep-screen-on lock after the phone is backgrounded and never gets it back; a late lock can leak

*medium · confirmed · bug · effort S* — `frontend/src/pages/SitMode.tsx`

- **What the hunter sees:** A hunter glances at a message mid-sit. Back in Sit mode the screen now dims and locks after the normal timeout, forcing the gloved unlock this screen exists to avoid.
- **Evidence:** SitMode.tsx:104-118 requests the screen wake lock once, on mount. Under the Wake Lock spec the browser releases it whenever the page is hidden (screen off, app switch, notification shade), and there is no visibilitychange handler to request it again. The lock is assigned when the promise resolves, so if the effect is cleaned up first (a quick END SIT, or React StrictMode's double mount in dev), the late lock is never released.
- **Verifier:** The wake lock is requested once on mount (SitMode.tsx:106-108), and SitMode has no visibilitychange handler. The only one in the app is useRefetchOnReturn in hooks.ts, which SitMode does not use. The Screen Wake Lock spec releases screen locks whenever the document is hidden, so the lock is not regained after the screen turns off or the app is switched. The late-resolve leak is real but narrow: the promise usually resolves in milliseconds, and StrictMode only affects dev.
- **Fix:** The proposed fix is right.

### I-03 — Two hunters can reserve the same stand at the same time (no lock between check and insert)

*medium · confirmed · security · effort S* — `backend/app/api/routes_stands.py`, `backend/app/models.py`

- **What the hunter sees:** Both hunters are told the stand is theirs. Two people end up on the same seat or in each other's fire lanes, which is exactly what reservations exist to prevent.
- **Evidence:** routes_stands.py:238-287. claim_stand reads the existing claims, then calls _tonight_conditions() (a live weather fetch: about 0.3 s here, 20 s when Open-Meteo stalls, see I-04), then inserts. There is no unique constraint on sits(stand_id, night) and no row lock. Proven with I/race_claim.py: 6 concurrent POST /api/sits for 'Loma sin sitio' (3 as admin, 3 as member) all returned 201. Result: 6 active claims on one stand from 2 different users. The fire-lane interlock (lines 252-261) is bypassed the same way.
- **Verifier:** Reproduced: 6 concurrent POST /sits for 'Loma sin sitio' all returned 201, leaving 6 active claims from 2 users. There is only a non-unique index ix_sits_stand_night (models.py:462), and the check-then-insert straddles a live weather fetch (routes_stands.py:239-286). Downgraded because the normal window is ~0.3 s and the client already guards double taps (Stands.tsx:56); it widens to 20 s only when the weather call stalls (I-04).
- **Fix:** A unique index cannot enforce the fire-lane interlock, which spans different stands. Take pg_advisory_xact_lock(<night hash>) at the start of claim_stand to serialise claims per night. Compute the wind verdict before taking the lock, from a cache. Optionally also add a partial unique index on (stand_id, night) WHERE outcome<>'cancelled', after the migration removes existing duplicates, and catch IntegrityError as 409 or an idempotent return.

### I-09 — END SIT doesn't end the sit: the stand still says 'Your sit is on'

*medium · confirmed · bug · effort S* — `frontend/src/pages/SitMode.tsx`, `backend/app/api/routes_stands.py`

- **What the hunter sees:** A hunter who ends a quiet sit sees it still running and isn't asked what happened. Unreported sits pile up in the only ground-truth data.
- **Evidence:** SitMode.tsx:280-284: END SIT only flushes the queue and goes to /stands. ended_at is only set when an outcome is PATCHed (routes_stands.py:310-311). Proven with I/f_endsit.cjs: Reserve, Start sit, END SIT with no taps. Server: outcome=unreported, ended_at=null. Stands shows 'Your sit is on' with a 'Back to sit' button. Screenshot: shots/endsit_no_outcome.png.
- **Verifier:** END SIT only flushes the queue and navigates (SitMode.tsx:280-284). ended_at is set only when an outcome is PATCHed (routes_stands.py:310-311), so the stand still reads 'Your sit is on' with 'Back to sit' (Stands.tsx:71, 98). The finding slightly overstates one point: Stands does offer a collapsed 'What happened?' fold for this sit (Stands.tsx:99).
- **Fix:** The proposed fix is right. Also have Stands treat started_at plus a client-side 'ended' flag as 'Sit ended: what happened?' and open the outcome fold by default.

### I-23 — Sit Mode's keep-screen-on is lost after the phone leaves the app once

*medium · confirmed · ux · effort S* — `frontend/src/pages/SitMode.tsx`

- **What the hunter sees:** After a quick look at another app during a long sit, the screen sleeps. Waking it in the dark with gloves on is exactly what Sit Mode is meant to avoid.
- **Evidence:** SitMode.tsx:105-118 requests navigator.wakeLock once on mount. Browsers release a screen wake lock when the page is hidden, and there is no visibilitychange handler to request it again.
- **Verifier:** SitMode.tsx:105-118 requests the screen wake lock once on mount and never again. The Screen Wake Lock spec requires the browser to release screen locks when the document becomes hidden, so after any app switch the screen can sleep for the rest of the sit.
- **Fix:** The proposed fix is right. Keep the sentinel in a ref, re-request it on visibilitychange when the page is visible, and release it on unmount.

### J-03 — Sit lifecycle is wrong: the first tap ends the sit, END SIT ends nothing, and unreported sits disappear at 06:00

*medium · confirmed · bug · effort S* — `backend/app/api/routes_stands.py`, `frontend/src/pages/SitMode.tsx`, `frontend/src/pages/Stands.tsx`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** Hunters get locked out of Sit Mode mid-sit. Sit durations and pressure data are wrong, and quiet sits stay 'unreported' forever.
- **Evidence:** routes_stands.py:310-311 sets ended_at on the first PATCH that is not 'unreported'. PROVEN: in the scratch test, one 'seen' tap set ended_at and later PATCHes left it unchanged, so a 20:15 sighting marks the sit as ended at 20:15. Stands.tsx:89 counts a sit as active only while outcome=='unreported'. After one tap the stand reads 'Reported: saw animals' and 'Back to sit' disappears. If iOS kills the PWA mid-sit (manifest start_url '/'), there is no way back into Sit Mode, and Tonight has no resume link. END SIT (SitMode.tsx:280-287) only flushes the queue and navigates away. No request records the end, so a sit with no taps keeps showing 'Your sit is on'. list_sits defaults to tonight() (routes_stands.py:216), so after 06:00 an unreported sit drops off Stands and can no longer be reported.
- **Verifier:** routes_stands.py:310-311 sets ended_at on the first non-unreported PATCH. Stands.tsx:89 treats a sit as active only while outcome=='unreported', so 'Back to sit' disappears after one tap. END SIT (SitMode.tsx:280-288) sends no end request, and list_sits defaults to tonight() (routes_stands.py:216), so unreported sits vanish at 06:00. Nothing reads ended_at yet, so the harm today is the lockout and the lost reports; wrong durations only matter for future analysis.
- **Fix:** As proposed: add POST /sits/{id}/end, stop PATCH from touching ended_at, and on Stands use active = started_at && !ended_at. Add the Tonight resume banner and the next-morning reporting from J-22.

### J-15 — Sit Mode's keep-screen-on is lost after the first interruption

*medium · confirmed · ux · effort S* — `frontend/src/pages/SitMode.tsx`

- **What the hunter sees:** After one pocket or power-button press, the screen sleeps on its normal timeout. The hunter then has to wake and unlock the phone in gloves and in the dark to tap.
- **Evidence:** SitMode.tsx:104-108 requests navigator.wakeLock once, when the page mounts. The Screen Wake Lock API releases the lock automatically when the document becomes hidden (screen locked, a glance at the camera app, a notification tapped), and nothing listens for visibilitychange to request it again. The SIT's own comment says keeping the screen on is the point.
- **Verifier:** SitMode.tsx:104-108 requests the screen wake lock once, on mount, and nothing in SitMode listens for visibilitychange. The spec releases a screen wake lock whenever the document is hidden, so one power-button press or app switch loses it for the rest of the sit.
- **Fix:** Re-request the lock on visibilitychange when the page becomes visible, and release it on unmount. The amber marker is optional; keep it tiny so it does not add light.

### J-22 — FEATURE: One-tap 'What happened last night?' the next morning

*medium · confirmed · feature · effort S* — `backend/app/api/routes_stands.py`, `frontend/src/pages/Stands.tsx`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** Most quiet sits end up 'unreported' permanently, which biases the register toward successes.
- **Evidence:** Why it fits: the redesign names outcome capture as the scarce ground truth and budgets one interaction per sit (docs/redesign/02 §10). Today, unreported sits disappear from Stands at the 06:00 rollover (routes_stands.py:216; Stands.tsx:43 requests /sits with no night), so a hunter who skipped Sit Mode can never report.
- **Verifier:** list_sits defaults to tonight() (routes_stands.py:216), Stands.tsx:43 calls /sits with no night, and the outcome buttons appear only for tonight's unreported sits (Stands.tsx:97-99). After the 06:00 rollover an unreported sit can no longer be reported anywhere. The fix fits the one-interaction budget and the ground-truth goal.
- **Fix:** Add GET /sits?mine=1&unreported=1&days=3 (or reuse the existing `night` param) and show one card with the four outcome buttons on Tonight and Stands. It shares the ended_at/active changes with J-03.

### A-20 — Dawn sits: the 06:00 night cutover makes a reservation vanish mid-sit, or refuses it before 06:00

*low · confirmed · bug · effort M* — `backend/app/api/routes_stands.py`, `frontend/src/pages/Stands.tsx`, `frontend/src/pages/SitMode.tsx`

- **What the hunter sees:** Dawn roe or red deer sits can't be reserved reliably, and the hunter's seat is offered to others mid-sit.
- **Evidence:** routes_stands.tonight() (54-58) switches to the new night at 06:00 local, and list_stands, list_sits and claim_stand all use it. PROVEN: tonight() at 05:30 returns 2026-09-26 and at 06:30 returns 2026-09-27 (the DST night is handled correctly). A dawn-sit reservation made at 05:30 (sunrise 07:57 on 27 Sep) counts toward the previous evening. It is refused with a 409 if anyone sat that stand the evening before. If it is accepted, at 06:00 it disappears from Stands and from Sit mode's /sits lookup, and the stand shows 'Free tonight' to others while the hunter is in it.
- **Verifier:** tonight() moves to the new night at 06:00 local (routes_stands.py:30-34), and list_stands, list_sits and claim_stand all filter on it. A 05:30 dawn claim is checked against the previous evening's sits, and the sit disappears from lists at 06:00. Downgraded: the app is built for evening sits ('Reservations are for tonight only'), and after 06:00 'Free tonight' refers to the coming evening, so no fire-lane overlap follows. A reload of Sit mode just loses the header, while PATCH by id still works.
- **Fix:** Do NOT move the cutover to noon: a reservation made at 10:00 for that evening would then be filed under the previous night. The minimal fix is to include started_at-set, ended_at-null sits in list_stands and list_sits whatever their night. Add a dawn session only if the owner actually wants dawn sits.

### A-23 — Any member can start another hunter's sit, and a late write can bring a cancelled reservation back to life

*low · confirmed · security · effort S* — `backend/app/api/routes_stands.py`

- **What the hunter sees:** A member can start someone else's sit. A late or replayed write revives a cancelled reservation on a stand someone else now holds, double-booking it and bypassing the interlock.
- **Evidence:** start_sit (routes_stands.py:341-352) has no owner or admin check and accepts cancelled sits. update_sit (314-338) accepts any change, including out of 'cancelled'. PROVEN by scratch test: Bob starts Alice's sit (200). Alice cancels and Bob reserves the stand; Alice's late PATCH {'outcome':'seen'} then succeeds, leaving two live sits on one stand.
- **Verifier:** Reproduced at API level: Bob can start Alice's sit (200), and Alice's late PATCH revives her cancelled sit next to Bob's live one. start_sit has no owner check (routes_stands.py:317-328), and update_sit accepts any transition (290-314). Not reachable from the UI: Start sit is only shown for your own sits, Cancel only before start, and Sit mode (the only offline queue) needs a started sit.
- **Fix:** The proposed fix is right.

### A-25 — Sit mode forgets the 'saved, no signal' count after a reload and doesn't retry the queue on its own

*low · confirmed · ux · effort S* — `frontend/src/pages/SitMode.tsx`

- **What the hunter sees:** After a reload or re-entering Sit mode, the hunter can't see that reports are still stuck on the phone, and they aren't retried until END SIT.
- **Evidence:** `pending` starts at 0 (SitMode.tsx:89) and only counts failures during the current visit. The queue is sent only on the 'online' event (122-133) or END SIT, not on mount or when the app comes back to the foreground. Phones rarely fire 'online' when they keep a cell connection with no data. PROVEN: Playwright S4. With 2 items in gs_sit_queue, opening /sit/s1 does not show '2 saved, no signal'.
- **Verifier:** Reproduced (S4): with 2 items in gs_sit_queue, opening /sit/s1 shows no 'saved, no signal'. pending starts at 0 (SitMode.tsx:89), and the queue is only sent on 'online' or END SIT (122-133, 280-284).
- **Fix:** The proposed fix is right. Use the single-flight flush from A-02 for the mount, foreground and interval retries.

### J-11 — Two hunters can reserve the same stand at the same moment

*low · confirmed · bug · effort S* — `backend/app/api/routes_stands.py`, `backend/app/models.py`

- **What the hunter sees:** Two people walk to the same seat, or into neighbouring fire lanes, each believing the stand is theirs. That breaks the core promise of the sit register.
- **Evidence:** claim_stand (routes_stands.py:238-287) checks for existing claims, then fetches the weather (an Open-Meteo call on a cache miss), then inserts. There is no unique constraint on (stand_id, night) for live sits; models.py:461-462 has only plain indexes. PROVEN: two users posting concurrently (with a 0.5 s weather call) both got 201, leaving two live sits on one stand. The same window defeats the shooting-arc safety check.
- **Verifier:** claim_stand checks for existing sits (routes_stands.py:239-247), then calls _tonight_conditions, then inserts. There is no unique constraint: models.py:461-462 and migration 0009 create only plain indexes. The race is real, but with a handful of hunters and a weather cache that is usually warm (J-07), the window is milliseconds on most calls, so a collision is unlikely in practice.
- **Fix:** Add a partial unique index on sits(stand_id, night) WHERE outcome <> 'cancelled', de-duplicating any existing rows in the migration first so it cannot fail on deploy. Map IntegrityError to 409, move the weather call before the check, and take pg_advisory_xact_lock(hash(night)) around the arc check.


## 3. Safe deploys and a test gate

### H-04 — update.ps1: a failed pip install or vite build is never retried, and the server keeps running half-deployed

*medium · confirmed · reliability · effort S* — `deploy/update.ps1`

- **What the hunter sees:** The app is down, or shows an old frontend against a new API, until someone logs into Db01. The self-update loop never repairs it by itself.
- **Evidence:** If pip install fails, update.ps1:50-54 only writes a note and carries on to back up, migrate and restart the API (lines 112-151). If vite fails, lines 71-76 keep the old frontend and also carry on. The code is now at origin/main, so every later run exits at line 42 ('if ($before -eq $after) { exit 0 }'). Neither step is ever retried, and the next deploy only re-runs pip or npm if that diff touches requirements.txt or frontend/ again. Trigger: a push that adds a package (as ebc2f5f added pywebpush) plus a transient PyPI or proxy error. The API restarts into ModuleNotFoundError; NSSM keeps restarting it. The final check (lines 159-164) only notes 'API unhealthy' and does not roll back.
- **Verifier:** update.ps1:53 only notes a pip failure and continues, and line 75 does the same for a vite failure. After the git reset at line 45 HEAD equals origin/main, so every later run exits at line 42 and neither step is retried until a later diff touches requirements.txt or frontend/ again. The example is overstated, though: pywebpush is imported lazily inside notifications/push.py:41-42. A missing package there silently breaks one feature (push) for weeks rather than putting the API into a crash loop.
- **Fix:** Record the last fully applied SHA in C:\GameSense\data\deployed.sha and compute $changed and the early exit against that file, not against HEAD. Write it only after pip, vite, migrate and restart have all succeeded, so a failed step is retried on the next 10-minute run. Do not git reset back to $before on a pip failure unless the web copy is also restored.

### H-05 — The new frontend goes live before the backup and migration, and stays live when the deploy rolls back; unknown /api paths then return HTML with a 200

*medium · confirmed · bug · effort S* — `deploy/update.ps1`, `backend/app/main.py`

- **What the hunter sees:** During every deploy (for the length of the dump and migration), and indefinitely after a failed one, new screens call endpoints the running API does not have. Pages built on api() then show "Unexpected token '<' ... is not valid JSON" instead of a message.
- **Evidence:** update.ps1:64-77 builds the SPA and runs robocopy /MIR into C:\GameSense\web BEFORE pg_dump (84-129) and alembic (138-147). The rollback paths (116, 127, 145) run 'git reset --hard $before' but leave C:\GameSense\web untouched. The old API keeps running (it is only restarted at line 151). The SPA catch-all @app.get('/{full_path:path}') (main.py:79-89) also answers unknown API GETs. PROVEN with TestClient and FRONTEND_DIST set: GET /api/does-not-exist returned 200 text/html '<!doctype html>...'.
- **Verifier:** update.ps1:64-77 robocopies the new SPA into C:\GameSense\web before pg_dump (120-129) and alembic (140). None of the rollback paths (116, 127, 145) touch web. Verified with TestClient and FRONTEND_DIST set: GET /api/does-not-exist returns 200 text/html (main.py:79-89), so api() fails with a JSON parse error. POSTs get 405 JSON.
- **Fix:** Build into frontend\dist as now, but move the robocopy to just before Restart-Service, after alembic succeeds. In _spa(), return JSONResponse 404 for any full_path starting with 'api/'.

### H-08 — The only schema-drift guard cannot catch a model change that has no migration

*medium · confirmed · tech-debt · effort M* — `backend/tests/test_migrations.py`, `backend/alembic/versions/0001_initial.py`

- **What the hunter sees:** The next forgotten migration passes CI and deploys. Then every screen that reads that table returns 500 until someone hand-writes the migration on Db01.
- **Evidence:** 0001 runs Base.metadata.create_all() on the CURRENT models (0001_initial.py:107-108). So test_fresh_upgrade_matches_the_orm_exactly (test_migrations.py:60-82), whose docstring says 'If someone changes models.py without a migration, this fails', can never fail. PROVEN with scratch/H/guard_check.py. I appended a column to Image.__table__: the fresh-DB guard reported diff=[] (green), while a database already at head that then ran upgrade head raised UndefinedColumn when that column was queried. A separate simulation (v0.21 models from 3280a7d, create_all, stamp 0007, upgrade head, compare) found only harmless nullable drift today.
- **Verifier:** 0001_initial.py:19 runs Base.metadata.create_all on the current models (the cited lines 107-108 are wrong; the file is 23 lines). So test_fresh_upgrade_matches_the_orm_exactly (test_migrations.py:60-82) can never catch a column added to models.py without a migration. The auditor's guard_check.py logic is sound. The existing per-migration tests hand-restore old shapes (e.g. test_migrations.py:114-156), which shows the team knows about the gap, but nothing covers it in general.
- **Fix:** Commit a schema-only snapshot (pg_dump --schema-only plus the alembic_version row) taken at the current head. Add a test that loads it, runs upgrade head, and asserts compare_metadata == []. Refresh the snapshot in the same PR as each new migration.

### H-10 — The season's data depends on backups and server setup that are not in the repo, cannot be checked, and are not monitored

*medium · plausible · reliability · effort M* — `deploy/update.ps1`, `deploy/register-tasks.ps1`, `docs/09-handoff.md`, `docs/09-deployment.md`, `docs/07-deployment.md`

- **What the hunter sees:** A disk failure or a botched migration could lose the season's photos and sightings with no tested way back. Rebuilding Db01 relies on memory.
- **Evidence:** The only backup code in the repo is the pre-migration pg_dump in update.ps1:82-132. It only runs when a new commit arrives, writes to C:\GameSense\backups (the same disk as pgdata and the photos), and keeps the newest 7 by count (131-132). One busy day of pushes (08-04 had about 20 commits) rotates out the dump taken before a bad data migration. The daily 03:00 backup to D:\GameSense-Backup (09-handoff.md:147) lives in C:\GameSense\tools (09-deployment.md:93), outside git. Nothing shows whether it includes C:\GameSense\data\media, which is the ONLY copy of photos once SPYPOINT purges its cloud after about 30 days (09-handoff.md:158-160). The GameSenseAPI and GameSensePG services and the Sync, Sex, Update and Backup tasks are also not scripted in the repo; register-tasks.ps1 registers only Plan and Score. There is no restore procedure and no backup-freshness check.
- **Verifier:** Confirmed in the repo: the only backup code is the pre-migration dump in update.ps1:82-132. It writes to C:, runs on every deploy, and keeps the newest 7 by count. The Sync, Sex, Update and Backup tasks and the services are not scripted (register-tasks.ps1 only registers Plan and Score). But 09-handoff.md:27 documents a daily 03:00 backup to D:\GameSense-Backup. So the real risk is that it cannot be checked and is not monitored, not that no backup exists. Whether it covers media cannot be verified from here.
- **Fix:** Bring the existing 03:00 backup script into deploy/backup.ps1 and confirm it copies data\media as well as a pg_dump. Record a last_backup_at value in app_settings and show it on Admin, in red after 36 h. Script the missing task and service registrations idempotently. Rehearse one restore.

### H-18 — No disk-space guard or alert for the drive that holds the database, the photos and the backups

*medium · plausible · reliability · effort S* — `backend/app/ingestion/sync.py`, `backend/app/ingestion/ubox_sync.py`, `deploy/update.ps1`

- **What the hunter sees:** When C: fills mid-season, Postgres stops (or corrupts WAL), photo downloads fail and the app goes down, with no warning beforehand.
- **Evidence:** Photos (sync.py:44-49, ubox_sync.py:141-144), pgdata and the update dumps (update.ps1:82-84) all live under C:\GameSense. UBox allows up to 500 images per day per camera (models.py:69-71). Only ftp-receiver/receiver.py:183 checks free space. Nothing in the backend or the Admin page reports disk usage.
- **Verifier:** Only ftp-receiver/receiver.py:183 checks free space. There is no retention job (media_retention_days in config.py:43 is used nowhere), so the photo archive grows without limit, alongside pgdata and 7 dumps on the same C: drive. Actual disk size and growth rate cannot be seen. 'Corrupts WAL' is an overclaim: Postgres PANICs and refuses writes when full, it does not corrupt.
- **Fix:** Add shutil.disk_usage(settings.media_root) free/total to /api/admin/status and show it on Admin, amber below 20 GB. In pipeline sync, skip downloads below about 5 GB free and log it.

### K-09 — Every push to main goes live on Db01 within 10 minutes, at any hour, with no test gate

*medium · confirmed · reliability · effort M* — `deploy/update.ps1`, `docs/09-deployment.md`

- **What the hunter sees:** A broken or half-finished commit can reach every hunter's phone mid-hunt, and even a good one interrupts them at dusk.
- **Evidence:** update.ps1:37-45 resets to origin/main whenever it moved, and update.ps1:151 then runs Restart-Service GameSenseAPI. The GameSense-Update task runs every 10 minutes (docs/09-deployment.md:13,50), so a push at 19:30 restarts the API at prime time. The repo has no CI (no .github/ directory), the 263 backend tests are never run before deploy, and 5 of the 7 UI scripts are stale (I-29). A restart window at dusk then produces K-02's Cloudflare error page and B-02/H-06's stale-chunk blank for open apps. H-04, H-05 and H-09 cover the robustness of the script's steps, but not when a deploy is allowed or whether it has been tested.
- **Verifier:** There is no .github directory. update.ps1:37-45 hard-resets to origin/main whenever it has moved, and update.ps1:151 restarts GameSenseAPI with no time-of-day guard. The task runs every 10 min (docs/09-deployment.md:13,50). There is also no rollback when the post-restart health check fails: update.ps1:159-164 only logs 'API unhealthy'. A bad commit therefore stays live.
- **Fix:** Add a GitHub Actions workflow (Postgres service, pytest, npm run build) that moves a 'deploy' branch or tag on success, and have update.ps1 fetch that ref instead of main. Also roll back to $before and restart when /api/health fails after an update. The hunting-window deploy freeze is optional.

### B-25 — No backend tests cover the map endpoints or geometry, and the map-and-stands Playwright test is stale

*low · confirmed · tech-debt · effort M* — `backend/tests`, `frontend/tests/map-and-stands.cjs`

- **What the hunter sees:** B-03, B-05, B-08, B-10 and B-14 all shipped unnoticed, and future map fixes will regress silently.
- **Evidence:** grep finds no test that touches zones, /map/tonight, terrain or geo in backend/tests. frontend/tests/map-and-stands.cjs asserts copy that no longer exists in Map.tsx ('From NW → SE', 'Estimated scent exposure', 'Save location', 'Location saved': 0 matches), so it fails. The package has no test script. map-geometry.cjs still passes.
- **Verifier:** No backend test touches zones, /map/tonight, geo, bedding, thermal or terrain (grep over backend/tests finds only test_wind and stands). frontend/tests/map-and-stands.cjs asserts 'From NW → SE', 'Estimated scent exposure', 'Save location' and 'Location saved', none of which exist in src. package.json has no test script.
- **Fix:** As proposed: turn the verified scratch cases (authz, polygon validation, elongated bedding, now-vs-dusk, missing forecast, safe-ground consistency, weather TTL) into backend/tests/test_map.py, and update map-and-stands.cjs to the current copy.

### D-22 — 'Check for updates' says 'Up to date' when GitHub rate-limits the check

*low · confirmed · bug · effort S* — `backend/app/api/routes_admin.py`

- **What the hunter sees:** The admin is told the server is current when the check never actually ran.
- **Evidence:** version_check (routes_admin.py:55-58) never checks the HTTP status. GitHub's rate-limit reply is a JSON dict, iterating a dict yields strings, so names=[], latest=None and update_available=False. PROVEN (scratchpad/D/test_area_d.py::test_version_check_rate_limited_reads_as_up_to_date): the response was {'current':'v0.23.0','latest':None,'update_available':False} with no error, and the UI renders 'Up to date (v0.23.0).'
- **Verifier:** Reproduced the rate-limit case. The real problem is bigger: GitHub's tags for Jovoske/VA-GameTracker stop at v0.17.0 (checked live) while the app is 0.23.0 (version.py). Deploys go by pushes to main (update.ps1:39-45), so version_check (routes_admin.py:55-72) reports 'Up to date' every time, rate limit or not.
- **Fix:** raise_for_status alone won't make the button meaningful. Either compare the running commit (write `git rev-parse HEAD` at deploy time) against the GitHub commits API for main and show 'N changes waiting / last pulled at', or remove the button, since the server pulls itself every 10 minutes. In either case, treat a non-200 or non-list body as an error.

### H-07 — Health endpoints lie: /api/health reports ok with the database down, and /api/ready returns 200 even when degraded (production has no Redis, so it is always degraded)

*low · confirmed · reliability · effort S* — `backend/app/api/routes_health.py`, `backend/app/main.py`, `deploy/update.ps1`

- **What the hunter sees:** A deploy that leaves the database unreachable, or the schema out of step with the code, is logged as 'done: API healthy'. Nothing can monitor the server honestly.
- **Evidence:** /api/health returns a constant {'status':'ok','version':'0.1.0'} (routes_health.py:13-15). app/version.py says 0.23.0, and FastAPI(version='0.1.0') at main.py:30 is also wrong. /api/ready answers HTTP 200 with 'degraded' (lines 18-30) and requires Redis, which the native Db01 build does not run (docs/09-handoff.md:147). PROVEN with DATABASE_URL pointed at a missing database: /api/health returned 200 ok with version 0.1.0; /api/ready returned 200 {'status':'degraded','database':false,'redis':false}. update.ps1:160 treats /api/health as proof the deploy worked.
- **Verifier:** With DATABASE_URL pointing at a missing DB, /api/health returned 200 {status:ok, version:0.1.0} and /api/ready returned 200 {status:degraded, checks:{database:false, redis:false}} (routes_health.py:13-30). app/version.py says 0.23.0. The native build has no Redis (09-handoff.md:27), so /ready is always degraded. This matters for ops only: update.ps1:159-164 just writes a note either way and never rolls back.
- **Fix:** /api/health: return __version__ and run SELECT 1, answering 503 on failure. /api/ready: answer 503 when degraded, and check Redis only when a Celery broker is actually in use. Set FastAPI(version=__version__).

### H-09 — update.ps1 checks the pipeline lock but never takes it, so a sync can run new code against the old schema, or have its rows moved twice by a data migration

*low · plausible · data-correctness · effort S* — `deploy/update.ps1`, `backend/alembic/versions/0015_spypoint_local_time.py`

- **What the hunter sees:** During a deploy, a sync can crash, or a migration can quietly corrupt sighting times for photos that arrived during the deploy.
- **Evidence:** update.ps1:32-35 checks pipeline.lock once and never creates it. It then runs git reset --hard (45), npm and vite (64-77), pg_dump (120-123) and alembic (140), which takes minutes on a season-sized database. GameSense-Sync starts a fresh python every 15 minutes from the same repo, so it can load the new code while the schema is still old. With a data migration like 0015 (which shifts every spypoint captured_at by the UTC offset), photos imported by the new, already-correct importer during that window get shifted a second time (+2 h in summer). update.ps1 also hard-codes C:\GameSense\data\pipeline.lock, while pipeline.py derives the path from MODELS_ROOT (pipeline.py:38-39).
- **Verifier:** True that update.ps1:32-35 only checks the lock, and that the code on disk changes at line 45 minutes before alembic runs at line 140. A sync starting in that window will run new code against the old schema. The worst case the auditor cites, a non-idempotent data migration like 0015 shifting rows imported in that window, is real in principle. The shift would be -2 h, not +2 h. But 0015 already ran (dated 2026-09-19), so the risk only applies to future data migrations. Otherwise the result is one failed sync that retries 15 minutes later.
- **Fix:** Once H-03's atomic PID lock exists, have update.ps1 take it after the busy check (create it exclusively, write its PID) and release it in a finally block after Restart-Service. Also make future data migrations limit themselves to rows created before the migration started (for example WHERE created_at < now()).

### H-15 — The API and pipeline read .env differently from alembic and the FTP importer (quotes and inline comments are kept)

*low · confirmed · bug · effort S* — `backend/serve.py`, `backend/pipeline.py`

- **What the hunter sees:** A harmless-looking edit to .env (quotes or a trailing note) breaks the API's time handling or the SPYPOINT login, while migrations and the FTP importer keep working, which makes it very confusing to diagnose.
- **Evidence:** serve.py:12-19 and pipeline.py:23-29 copy raw 'KEY=value' text into os.environ, and environment variables override pydantic's own .env parsing. PROVEN (scratch/H/envq/t.py): given ESTATE_TIMEZONE="Europe/Madrid" and SPYPOINT_PASSWORD=abc#123 # my note, pydantic alone (alembic, ftp_import) reads 'Europe/Madrid' and 'abc#123'. The serve.py/pipeline.py path reads '"Europe/Madrid"' and 'abc#123 # my note'.
- **Verifier:** Reproduced (verify-H/envq/t.py). With ESTATE_TIMEZONE="Europe/Madrid" and SPYPOINT_PASSWORD=abc#123 # my note, pydantic alone reads 'Europe/Madrid' and 'abc#123'. The serve.py/pipeline.py loop (serve.py:12-19, pipeline.py:23-29) stores the raw text in os.environ, which takes precedence, so the API and pipeline see '"Europe/Madrid"' and 'abc#123 # my note'. This only bites if someone quotes a value or adds a trailing comment.
- **Fix:** Replace both loops with dotenv.load_dotenv(path, override=False). python-dotenv is already installed through pydantic-settings; pin it in requirements.txt.

### H-21 — Photo paths are stored as absolute paths, so a restore or media move leaves every photo 'not found'

*low · confirmed · reliability · effort M* — `backend/app/ingestion/sync.py`, `backend/app/ingestion/ubox_sync.py`, `backend/app/ingestion/ftp_import.py`, `backend/app/api/routes_images.py`

- **What the hunter sees:** If media is moved off a full C: drive, or restored to D: after a disk failure, every photo in the app shows as missing, even though the files are all there.
- **Evidence:** images.original_path stores os.path.join(settings.media_root, ...) or str(destination) as an absolute path (sync.py:44-49 and 122; ubox_sync.py:141-155; ftp_import.py:276-281). image_file returns 404 'Photo not found.' whenever os.path.exists(original_path) is false (routes_images.py:54-56). docs/07-deployment.md:26 promises that relocating media is 'a setting, not a code change'.
- **Verifier:** All three importers store absolute paths (sync.py:44-49,122; ubox_sync.py:140-155; ftp_import.py:276-281), and image_file returns 404 when the file is not at that path (routes_images.py:54-55). But recovering after a move is one SQL UPDATE using replace(), or a directory junction. It is an ops step, not data loss, so severity is low.
- **Fix:** In image_file, fall back to the current media_root: if the absolute path is missing, strip the known old prefix and rejoin the rest under settings.media_root. Document the one-line UPDATE for a relocation. A full migration to relative paths is optional.

### I-29 — 5 of the 7 UI test scripts fail on current main and nothing runs them

*low · confirmed · tech-debt · effort M* — `frontend/tests/camera-accounts.cjs`, `frontend/tests/insights.cjs`, `frontend/tests/map-and-stands.cjs`, `frontend/tests/stands.cjs`, `frontend/tests/ux-smoke.cjs`, `frontend/package.json`

- **What the hunter sees:** The copy rewrite broke the only UI regression net without anyone noticing, so regressions like I-01 and I-11 get through.
- **Evidence:** I copied the specs to scratch, pointed them at the bundled chromium and :5181, and ran them. PASS: mobile-scroll.cjs, map-geometry.cjs. FAIL: stands.cjs ('Reserve for tonight' no longer exists; it is now 'Reserve'). ux-smoke.cjs ('Retry loading photos', 'Retry loading stands', 'Retry forecast' and 'NO DATA' are all gone). insights.cjs ('Most sightings: lighter wind' is gone). camera-accounts.cjs (Settings cards are now folded, so 'Oak ridge UBox' is never visible). map-and-stands.cjs (waits for live ArcGIS tiles and uses 'Save location' / 'Location saved.'). grep of src finds 0 hits for each of these strings. All the specs hard-code channel 'msedge' and :5173, and package.json has no test script or CI.
- **Verifier:** The specs make positive assertions on strings that grep finds nowhere in src: 'Reserve for tonight', 'Retry loading stands/photos', 'Retry forecast', 'NO DATA', 'Most sightings: lighter wind', 'Save location'. package.json has no test script and there is no CI. Minor correction: camera-accounts, insights, ux-smoke and stands already read BROWSER_CHANNEL or BASE_URL from env; only some hard-code msedge and :5173.
- **Fix:** The proposed fix is right. Also add a spec for the Photos refetch-with-lightbox and Map retry cases, since the current specs would not catch I-01 or I-11.


## 4. No gaps in photo ingestion; broken camera logins are visible

### E-01 — If a SPYPOINT photo download fails once, the app never tries again and that night stays uncounted for good

*high · confirmed · data-correctness · effort S* — `backend/app/ingestion/sync.py:103`, `backend/app/ingestion/sync.py:106-127`, `backend/app/ai/empty_filter.py:47`, `backend/app/forecasting/exposure.py:131-134`, `backend/app/api/routes_cameras.py:284`

- **What the hunter sees:** A single CDN hiccup means that photo never appears in the camera strip: file_url is null and the frontend filters it out. It still counts toward 'Last photo…' and image_count. That camera's whole night is also dropped from every statistic permanently, so 'excluded nights' keeps growing.
- **Evidence:** sync.py:107-111 swallows any download error, then sync.py:118-127 still inserts the Image row with original_path=None and file_hash=None. The dedupe at sync.py:103 keys on spypoint_photo_id, so later sync_all and backfill runs skip that photo. scan_unprocessed only selects rows where original_path IS NOT NULL (empty_filter.py:47), so processed_at stays NULL. exposure.py:131-134 then marks the night UNPROCESSED. PROVEN with scratch test scratchpad/E/test_e_spypoint.py::test_failed_download_is_permanent_and_blinds_the_night: photo p2's download raises ReadTimeout once, the CDN recovers, and the second sync_all does not retry it. After scan and recompute_camera_nights the states are {09-23 CONFIRMED, 09-24 UNPROCESSED, 09-25 CONFIRMED}.
- **Verifier:** sync.py:107-127 inserts the row with original_path=None after a swallowed download error. The dedupe at sync.py:103 then blocks any retry, scan_unprocessed skips the row (empty_filter.py:47), and exposure.py:131-134 marks that night UNPROCESSED for good. The auditor's test passes. My own scratch test (verify-E/test_verify_e01.py) shows it is worse than claimed: when one of last night's 5 frames times out once, whats_changed() (changes.py:57-65) puts 'PL14 sent nothing last night. Unknown whether anything came through.' on the Tonight headline, even though 4 frames did arrive.
- **Fix:** Don't simply skip the insert: because of E-02, a photo that falls out of the newest 100 would still be lost. Instead: (1) in _ingest_photo, when the existing row has original_path IS NULL and a URL, retry the download and fill in path and hash; (2) run a small repair pass each run over rows WHERE spypoint_photo_id IS NOT NULL AND original_path IS NULL, using cdn_url, with an attempt cap; (3) as a safety net, let scan_unprocessed also take rows with original_path NULL that are older than about 24 h. scan_image already sets processed_at and is_empty_frame=None for those, so a lost frame stops blinding the night.

### E-02 — Routine SPYPOINT sync only reads the newest 100 photos per camera, so any outage leaves a permanent gap that is later counted as 'no animals'

*high · confirmed · data-correctness · effort M* — `backend/app/ingestion/sync.py:135-143`, `backend/app/ingestion/sync.py:229-234`, `backend/app/forecasting/exposure.py:124-129`

- **What the hunter sees:** Suppose the server or pipeline is down for a few hours at a busy feeder, or a guest login is broken for a day. The missing nights then count as nights the camera 'watched and saw nothing'. Patterns and the forecast undercount exactly the busiest periods. A backfill endpoint exists, but there is no button for it.
- **Evidence:** sync_camera calls list_photos(limit=100) with dateEnd=2100, which returns newest first, and never pages further. No watermark is stored. This is defect D13 in docs/redesign/01-review-and-defects.md:182, and docs/04-spypoint-integration.md:21 planned incremental cursor paging; it is still unfixed. PROVEN with scratchpad/E/test_e_spypoint.py::test_newest_100_only_leaves_a_permanent_gap_counted_as_empty_nights: 3 nights of 60 photos arrive during an outage, and two later sync_all runs store only 101 of 181. recompute_camera_nights then marks night 09-22 PRESUMED_UP with 0 frames, and marks 09-23 CONFIRMED with only 40 of its 60 frames.
- **Verifier:** sync_camera (sync.py:135-143) makes one list_photos(limit=100) call with dateEnd=2100 and keeps no watermark or paging. This is the known defect D13, still open. The auditor's test stores 101 of 181 photos, and a fully missing night becomes PRESUMED_UP with 0 frames (exposure.py:124-129). Outages that trigger this are realistic here: the 3 h stale lock (E-11) and hours-long AI backlogs (E-12) both stop the 15-minute sync.
- **Fix:** Page backward with client.date_cursor(oldest) until a page contains an already-stored spypoint_photo_id, or captured_at <= the camera's newest stored captured_at minus a small overlap. Cap it at about 20 pages and commit per page. Reuse backfill_camera's loop with a stop condition rather than writing a second pager.

### E-05 — Broken camera logins are invisible: sync reports ok, cards stay green, then hunters are told to check batteries

*high · confirmed · ux · effort M* — `backend/app/ingestion/sync.py:195-226`, `backend/app/api/routes_camera_accounts.py:67-104`, `frontend/src/pages/Admin.tsx:389-398`, `backend/app/health.py:17-46`, `frontend/src/pages/Cameras.tsx:98-113`, `frontend/src/pages/Cameras.tsx:343-351`, `backend/app/forecasting/alerts.py:88-92`

- **What the hunter sees:** When a guest changes their SPYPOINT password, their cameras stop without any notice. Hunters are told everything is fine, later told to go check batteries, and the 'Check the camera login in Settings' hint leads to a page that shows nothing to check.
- **Evidence:** SPYPOINT _run returns status 'ok' if any account succeeds. Account errors go only into SyncLog.error and camera errors only into the returned dict. PROVEN with test_one_broken_guest_login_reports_ok, which returns {'status':'ok','accounts_failed':1}, so the Check button shows 'Nothing new since last time.' Settings shows last_import only for UBox (Admin.tsx:389) and never shows last_sync_at or an error for SPYPOINT; the .env primary login is not listed at all. camera_health uses last_report_at from the last successful sync, so the card stays green 'Sending photos' for 36 h. After that the alert reads 'offline… Check battery and signal on your next visit'.
- **Verifier:** sync.py:220 sets status 'ok' when any account succeeds, and account errors go only to SyncLog.error, which the UI never reads. Admin.tsx:389 renders last_import only for UBox. list_accounts (routes_camera_accounts.py:67-104) never lists the .env primary login. health.py:17-21 relies on last_report_at, which only a successful sync refreshes. The worst case: the owner's own SPYPOINT password changes while guests exist. The run then still reports 'ok', the 4 main cameras read 'Sending photos' for 36 h, then 'offline… Check battery and signal' (alerts.py:88-92), and Settings has nothing to check.
- **Fix:** As proposed: write per-account SPYPOINT results into SyncLog.details in the UBox shape, and include a synthetic row for the .env primary login. Surface last success or error per login in Settings. In camera_health, when the camera's account last failed or last_sync_at is more than about 2 h old, return a distinct 'not_syncing' status with 'Photos not coming in — camera login needs attention' rather than 'offline/check battery'.

### C-07 — "Check for new photos": the busy path spins forever, and the slow path promises photos that never refresh

*medium · confirmed · bug · effort S* — `frontend/src/pages/Cameras.tsx`

- **What the hunter sees:** The status line spins forever, or tells the hunter photos will appear, and nothing does until they leave the page and come back.
- **Evidence:** Cameras.tsx:334-335: when POST /cameras/sync returns status 'busy' (lock held by the 15-min sync, the hourly 'sex' pass, plan or score), state is set to 'running' and no polling happens. The effect at 254-258 only clears 'ok'/'quiet', so the spinner and the text stay until the next tap. PROVEN with Playwright (scenarioSyncBusy): 12s after tapping, spinner=1, msg='Already checking. New photos will show shortly.', button re-enabled. On the non-busy path the poll gives up after 24x2.5s = 60s (line 359) with 'Taking a while. Photos show up as they arrive.', calls loadCameras() once and never refreshes again. Sync plus MegaDetector plus DeepFaune on CPU easily takes more than 60s after a busy night.
- **Verifier:** Reproduced: after the busy response, 12s later spinner=1 and the message was still 'Already checking…'. Cameras.tsx:334-335 sets state 'running' with no poll, and the effect at 254-258 only clears 'ok'/'quiet'. The non-busy path gives up after 24×2.5s (line 339) and calls loadCameras once (line 364).
- **Fix:** Polling after 'busy' needs care. The scheduled pipeline.py writes no pipeline-summary SyncLog, so /cameras/sync/status would report the last provider row (UBox only), or a stale row after a sex/plan/score pass. On busy, poll until status != 'running', then call loadCameras() and show a neutral 'Done checking' with no count, or have pipeline.py write the same summary row as _sync_work. Past 60s, keep a slow poll and always end in a terminal state.

### C-08 — One failing camera account turns a successful check into "Could not reach the cameras" and hides the new photos

*medium · confirmed · bug · effort S* — `backend/app/api/routes_cameras.py`, `frontend/src/pages/Cameras.tsx`

- **What the hunter sees:** When a guest's UBox password expires, every check the owner runs shows a red failure even though 7 new SPYPOINT photos came in.
- **Evidence:** routes_cameras.py:74: the pipeline summary is status='error' if ANY provider result is 'error', even when another provider downloaded photos. Cameras.tsx:349-350 then shows only 'Could not reach the cameras. Check the camera login in Settings.' and throws away images_downloaded. PROVEN with a scratch pytest (test_sync_summary_error_hides_downloaded_count): SPYPOINT ok with 7 photos, UBox error, so /cameras/sync/status returns status='error', images_downloaded=7.
- **Verifier:** The auditor's pytest passes: status='error' with images_downloaded=7. routes_cameras.py:74 marks the whole run 'error' if any provider result is 'error'. It is worse than claimed: ubox_sync.py:351 sets UBox to 'error' when even a single photo download failed (totals['failed']), so one bad file turns a good check red. Cameras.tsx:349-350 then drops the count.
- **Fix:** In _sync_work, set 'partial' when images_downloaded > 0 or any provider is 'ok' while another errored, and keep the per-provider details. In the UI, show the count first, add a one-line note naming the failing account, and use red only for status 'error' with 0 downloaded.

### E-04 — The whole SPYPOINT run is one database transaction, so one DB error throws away every camera's photos and the sync log, and skips UBox and the AI pass

*medium · confirmed · reliability · effort M* — `backend/app/ingestion/sync.py:97-143`, `backend/app/ingestion/sync.py:178-226`, `backend/pipeline.py:55-59`, `backend/app/api/routes_cameras.py:59-69`

- **What the hunter sees:** One bad moment throws away every camera's new photos for that 15-minute run. Triggers include a login removed mid-run, two overlapping runs inserting the same new camera, or a dropped DB connection. Nothing reaches the sync log, UBox and AI stop too, and the Check button shows 'Could not reach the cameras'.
- **Evidence:** sync_all commits only once, at sync.py:224, and neither Image inserts nor enrich_image run inside a savepoint. The per-camera except at sync.py:206-208 catches the DB error, but the transaction is already aborted, so every later statement fails and the final commit raises. PROVEN with a realistic trigger, scratchpad/E/test_e_spypoint.py::test_login_removed_mid_run_poisons_whole_run: a guest removes their login (DELETE /camera-accounts) while the run is between accounts. upsert_camera then hits a ForeignKeyViolation and sync_all raises PendingRollbackError. Result: 0 images kept, including the primary account's photo that had already been processed, and 0 SyncLog rows. test_db_error_in_one_camera_discards_every_camera_and_the_sync_log shows the same for any statement error. In pipeline.py the exception also skips sync_ubox_all, the AI pass and the exposure recompute for that run. UBox does not have this problem because it uses begin_nested plus a commit per camera.
- **Verifier:** The only commit in _run is at sync.py:224, and neither _ingest_photo nor enrich runs inside a savepoint. The auditor's tests reproduce PendingRollbackError with 0 images and 0 SyncLog rows kept, and pipeline.py:58-59 then skips UBox, the AI pass and exposure. Downgraded because the realistic triggers (a login removed in the few seconds before its turn, a dropped DB connection) are rare and not deterministic. Nothing was committed, so the next 15-minute run re-lists the newest 100 per camera and recovers the photos. The loss is one run plus the skipped UBox/AI pass, not permanent, except in the more-than-100 case that E-02 covers.
- **Fix:** Follow ubox_sync: commit the 'running' SyncLog first. Wrap each camera in db.begin_nested() and commit after it. Wrap each photo's insert and enrich in its own begin_nested(), as the UBox path does at ubox_sync.py:160-162. On a per-camera error, roll back to the savepoint and record it. In pipeline.py, also wrap sync_all in try/except so UBox and AI still run.

### E-06 — UBox catch-up looks back at most 24 h, so a longer outage leaves a permanent gap

*medium · confirmed · data-correctness · effort S* — `backend/app/ingestion/ubox_sync.py:213-217`, `backend/app/ingestion/ubox_sync.py:283-284`, `backend/app/ingestion/ubox_sync.py:315-317`

- **What the hunter sees:** If the UBox login breaks or the server is off over a weekend, fixing it brings back only the last day of photos. The rest never arrive.
- **Evidence:** For an account that has synced before, since = max(camera.last_sync_at − 2 h, until − 24 h). PROVEN with scratchpad/E/test_e_ubox.py::test_outage_longer_than_24h_leaves_a_permanent_gap: the camera and account last synced 3 days ago. After recovery the earliest window requested is now−24 h (2026-09-15 13:00), and the event from 2 days ago is never requested or imported.
- **Verifier:** For an account that has synced before, ubox_sync.py:213-217 computes since = max(camera.last_sync_at − 2 h, until − 24 h), so the window can never exceed 24 h. The auditor's test shows an event from 2 days ago during an outage is never requested (earliest window: now − 24 h).
- **Fix:** Use min(camera.last_sync_at, account.last_sync_at) − 2 h as the floor, capped at the provider's listing retention (for example 7 days) rather than hours=24. _event_windows already splits long periods into day windows, so the cost is bounded.

### E-07 — Changing JWT_SECRET silently switches off every saved guest SPYPOINT login

*medium · confirmed · reliability · effort S* — `backend/app/core/crypto.py:17-27`, `backend/app/ingestion/sync.py:32-40`, `backend/app/ingestion/ubox_sync.py:307`, `backend/app/ingestion/ubox_sync.py:338-341`

- **What the hunter sees:** Changing the default JWT secret, which the audit recommends (D5), stops every guest camera. The app gives no sign of it.
- **Evidence:** The Fernet key is derived as sha256(JWT_SECRET). _accounts catches the decrypt error, logs 'sync.account_decrypt_failed' and drops the account without recording an error. PROVEN with scratchpad/E/test_e_spypoint.py::test_rotated_jwt_secret_silently_drops_guest_accounts: after rotation the run reports status 'ok', accounts_failed 0 and SyncLog.error None. UBox logins show 'Account connection failed (InvalidToken)'.
- **Verifier:** crypto.py:17-19 derives the Fernet key from JWT_SECRET, and sync._accounts (sync.py:37-40) swallows the decrypt error with only a log line. The auditor's test shows status 'ok', accounts_failed 0 and SyncLog.error None after rotation. Rotation is exactly what D5 recommends, so following the audit silently stops every guest SPYPOINT camera, and then E-05's misleading 'check battery' alert follows.
- **Fix:** As proposed: add a dedicated CREDENTIALS_KEY with a MultiFernet fallback to the JWT-derived key, so old tokens stay readable. On a decrypt failure, append '<label>: saved password can't be read — re-enter it' to errors and mark the account in list_accounts. The UBox path already surfaces it, only as a class name (E-18).

### E-08 — One UBox snapshot that won't download marks every sync as 'error' and re-scans a week of events every 15 min

*medium · confirmed · ux · effort S* — `backend/app/ingestion/ubox_sync.py:283-285`, `backend/app/ingestion/ubox_sync.py:315-317`, `backend/app/ingestion/ubox_sync.py:325-337`, `backend/app/ingestion/ubox_sync.py:352`, `backend/app/api/routes_cameras.py:73-77`, `frontend/src/pages/Cameras.tsx:348-351`

- **What the hunter sees:** The Check button shows red 'Could not reach the cameras. Check the camera login in Settings.' while photos are arriving normally. The login row reads 'Problem: Some snapshots could not be imported' for up to a week.
- **Evidence:** PROVEN with scratchpad/E/test_e_ubox.py::test_one_dead_snapshot_flags_every_run_as_error_and_rescans_7_days: one event's URL returns 404. Run 1 and run 2 are both status 'error', even though each downloaded a new photo. account.last_sync_at stays None, so run 2 lists the full 7-day initial window again. The pipeline summary copies 'error', and the frontend maps it to the login message.
- **Verifier:** One failed snapshot sets sync.status 'error' (ubox_sync.py:352) and keeps account.last_sync_at None (ubox_sync.py:335-337), so every run repeats the 7-day initial window (ubox_sync.py:315-317). _sync_work copies 'error' (routes_cameras.py:73-77), and Cameras.tsx:348-351 shows the 'Check the camera login' message. The auditor's test passes: both runs 'error', the second run looks back 7 days, while photos still download. Expired signed URLs in a 7-day initial import make this likely on the first connection.
- **Fix:** As proposed: treat per-snapshot failures as a warning ('partial' with a failed count) and set account.last_sync_at once listing succeeds. Keep a small per-event attempt counter (for example in a table, or in SyncLog details keyed by event_id) so a dead event is dropped after 3 tries. Map only login/listing failures to the 'Couldn't sign in' copy.

### E-10 — Check button: when a sync is already running the spinner never stops, and a real photo count is rarely reported

*medium · confirmed · ux · effort S* — `frontend/src/pages/Cameras.tsx:254-258`, `frontend/src/pages/Cameras.tsx:334-336`, `frontend/src/pages/Cameras.tsx:339-359`, `backend/app/api/routes_cameras.py:51-80`, `backend/app/api/routes_cameras.py:216-222`

- **What the hunter sees:** A spinner that never stops, and the button seldom confirms the photos it actually fetched.
- **Evidence:** PROVEN with Playwright: when POST returns {status:'busy'}, 20 s later the status line still reads 'Already checking. New photos will show shortly.' with the spinner, and the button is enabled again. sync.state stays 'running', and the clearing effect only handles ok/quiet. Separately, _sync_work writes the summary SyncLog only after scan_unprocessed, classify_unclassified and recompute_camera_nights, and /sync/status reports 'running' while the lock exists. So when new photos did arrive, the 60 s poll (24 × 2.5 s) usually ends with 'Taking a while…'. The '<N> new photos came in' message effectively only appears in the 'nothing new' case.
- **Verifier:** The busy path is proven. Cameras.tsx:334-336 sets state 'running', the clearing effect at :254-258 only handles ok/quiet, and the auditor's screenshot shows the spinner still running after 20 s with the button enabled again. The second claim (summary SyncLog written only after scan, classify and recompute; routes_cameras.py:59-80, with /sync/status returning 'running' while the lock exists) is correct in code. Whether the 60 s poll usually times out depends on CPU AI speed, so that part is plausible rather than proven.
- **Fix:** On 'busy', run the same /sync/status poll loop, or show a static line with no spinner. In _sync_work, write an interim SyncLog (provider 'fetch', images_downloaded) right after ingestion, and have /sync/status return it with status 'identifying' while the lock is held.

### E-13 — A SPYPOINT login added while the pipeline is busy never gets its photo history

*medium · confirmed · bug · effort S* — `backend/app/api/routes_camera_accounts.py:179-216`, `backend/app/ingestion/sync.py:178-234`, `backend/app/ingestion/sync.py:245-264`

- **What the hunter sees:** A guest who connects at dusk, when the pipeline is often busy, gets only their last few days. Their cameras have little history to learn patterns from.
- **Evidence:** When _pipeline_busy() is true, add_account replies 'Photos come in on the next fetch.' But _run and sync_camera never check CameraAccount.last_sync_at; UBox does, at ubox_sync.py:315-317. The next scheduled run therefore imports only the newest 100 photos per camera, the 2-month backfill never runs, and the UI has no backfill button. backfill_account also has no per-camera try: one camera's SpypointError aborts the rest and leaves last_sync_at None.
- **Verifier:** My scratch test (verify-E/test_verify_e.py) shows a new guest account with last_sync_at None, picked up by the scheduled sync_all, stores only 100 of 400 photos. It then sets last_sync_at, so no backfill ever follows: _run never checks it, unlike ubox_sync.py:315-317. A second test shows backfill_account (sync.py:255-262) aborting on one camera's SpypointError: the other camera is never imported and last_sync_at stays None. That error also skips scan, classify and recompute in add_account's work().
- **Fix:** As proposed: in _run, when acct['id'] is set and that CameraAccount.last_sync_at is None, call backfill_camera(months=2) for its cameras. In backfill_account, wrap each camera in try/except with begin_nested and commit, and set last_sync_at only when all cameras succeed (or record per-camera errors).

### H-20 — Stale data is shown as fresh: nothing tells the hunter that syncing has stopped

*medium · confirmed · ux · effort S* — `backend/app/forecasting/model.py`, `frontend/src/pages/Tonight.tsx`, `backend/app/api/routes_cameras.py`

- **What the hunter sees:** A hunter can pick a stand based on photos that are days old while the app looks up to date.
- **Evidence:** Tonight's 'Plan from {ageLabel(planAt)}' (Tonight.tsx:169-204) measures when the API answered, not how old the data is. The forecast_tonight response (model.py:370-414) has no newest-photo time and no last-successful-sync time. /cameras/sync/status returns only the newest SyncLog row (routes_cameras.py:220). pipeline.py writes a SPYPOINT row and then a UBox row, so a failing SPYPOINT login is hidden behind a UBox 'ok'. If the pipeline is stuck (stale lock, disabled task after a bad deploy, expired SPYPOINT password), Tonight still says 'Plan from just now'.
- **Verifier:** The forecast_tonight response (model.py:370-414) has no newest-photo or last-successful-sync time. Tonight's 'Plan from X' (Tonight.tsx:169,200-204) measures when the API answered. /cameras/sync/status returns only the newest SyncLog row, and a scheduled sync writes the SPYPOINT row before the UBox row. Mitigation the auditor missed: after 36 h without check-ins, cameras show in Tonight's alerts as offline (model.py:291-295). So the gap is the first 36 h, and any failure mode where cameras still report but photos stop.
- **Fix:** Add data_as_of (max images.captured_at) and last_sync_ok_at (max finished_at of status='ok' sync rows, per provider) to /forecast/tonight. On Tonight, show one plain line such as 'Newest photo 5 h ago, cameras not syncing' when last_sync_ok_at is older than about 2 h.

### E-03 — One photo stamped with a reset camera clock creates years of fake 'camera watched, saw nothing' nights

*low · confirmed · data-correctness · effort S* — `backend/app/ingestion/ftp_import.py:115-118`, `backend/app/ingestion/ftp_import.py:137-148`, `backend/app/ingestion/spypoint.py:162-191`, `backend/app/ingestion/spypoint.py:318-323`, `backend/app/forecasting/exposure.py:113-129`

- **What the hunter sees:** Picture one frame shot after a battery swap, before the camera has set its clock. That camera then looks like it watched about 6 years of empty nights, and every rate for it collapses ('3 of 2263 nights'). A SPYPOINT frame with a future date would also sit at the top of the strip as 'Last seen' for months.
- **Evidence:** FTP plausible() only rejects year<2000 or more than 1 day after receipt. SPYPOINT _parse_dt has no plausibility check at all. Probes: '1970-01-01T00:00:00.000Z' is accepted as 1969-12-31 23:00 UTC, '2027-03-01T21:00Z' is accepted, and ftp _timestamp accepts PICT_20200718_0012.jpg as 2020-07-17 22:12 UTC. exposure walks every day between a camera's first and last frame and marks empty days between frames PRESUMED_UP. PROVEN with scratchpad/E/test_e_clock.py: a camera with 10 real nights gets one extra 2020-dated photo, and observed_nights goes from 10 to 2263 (2252 of them PRESUMED_UP).
- **Verifier:** The mechanism is real. ftp_import.py:115-118 only rejects year<2000 or more than 1 day ahead, spypoint._parse_dt has no bounds, and exposure.py:120-130 fills every gap between the first and last frame with PRESUMED_UP. But the claimed impact is overstated: observed_nights() has no caller anywhere in backend/app or the frontend. The forecast denominator is distinct capture dates (model.py:117-120), so one old frame adds 1, not 2000. changes.py and scoring.py read only the last 30 nights and last night. The real effects are small: a wrong 'oldest' date in analytics, and, for a future-dated SPYPOINT frame only, a stuck 'Last photo' plus PRESUMED_UP instead of UNKNOWN on dead nights, which would hide 'camera_down'.
- **Fix:** Cheapest real protection: in _recompute_one, never presume nights across a gap of more than about 14 days (mark them UNKNOWN), and never presume nights after today. FTP/email: fall back to received_at with a note when captured_at < received_at − 30 days. SPYPOINT: when originDate is more than 1 h after the photo's 'date', or more than 30 days before it, use 'date' and log it.

### E-15 — The Suntek email/FTP camera is flagged 'offline' and dropped from the forecast after any 36 quiet hours

*low · confirmed · bug · effort S* — `backend/app/ingestion/ftp_import.py:300-301`, `backend/app/health.py:13-21`, `backend/app/health.py:46`, `backend/app/forecasting/alerts.py:88-92`, `backend/app/forecasting/model.py:284-300`

- **What the hunter sees:** A day and a half with no triggers at the Suntek gives a red 'Quiet since…' card and a false 'check battery' alert, and that spot drops out of tonight's ranking.
- **Evidence:** For FTP/email cameras, last_report_at moves only when a photo arrives: max(last_report_at, received_at). camera_health treats more than 36 h without it as offline; its comment says 'cameras check in at least daily', which holds for SPYPOINT status reports but not for a camera that only sends photos. Offline sets producing=False, so the forecast excludes the camera and alerts add 'offline — Check battery and signal on your next visit'.
- **Verifier:** ftp_import.py:300-301 advances last_report_at only on photo arrival, and health.py:13-21 marks the camera offline and producing=False after 36 h (my test shows 'No check-in for 40h'). alerts.py:88-92 then says 'Check battery and signal'. But the claim that the camera 'drops out of tonight's ranking' is wrong: forecast_tonight keeps non-producing cameras on their historical presence and only skips the recent-silence penalty (model.py:284-301). So the real impact is a false red card and alert, not a forecast change.
- **Fix:** Make health provider-aware. For cameras with neither spypoint_id nor ubox_uid, use a 'quiet' status with a longer threshold (for example 5–7 days) before 'offline', and word it 'No photos since …' rather than 'check battery'.

### E-17 — Renaming a camera or moving its marker hangs while a SPYPOINT sync is running

*low · confirmed · ux · effort S* — `backend/app/ingestion/sync.py:55-56`, `backend/app/ingestion/sync.py:139-143`, `backend/app/ingestion/sync.py:224`, `backend/app/api/routes_cameras.py:146-170`

- **What the hunter sees:** Rename or marker drag spins until every download and weather lookup in the run is finished. That is seconds normally and minutes after an outage.
- **Evidence:** upsert_camera takes SELECT … FOR UPDATE on each camera row, and the lock lasts until the single commit at the end of the run. PROVEN with test_camera_row_lock_is_held_for_the_whole_run: while the run is paused inside camera 2, a FOR UPDATE on camera 1 (what PATCH /cameras/{id}/name does) fails with LockNotAvailable after a 1.5 s lock_timeout. Without a timeout it just waits.
- **Verifier:** upsert_camera takes FOR UPDATE (sync.py:55-56), and the lock is only released by the single commit at sync.py:224. The auditor's test hits LockNotAvailable on camera 1 while the run is inside camera 2. rename_camera (FOR UPDATE), set_location (UPDATE) and remove_account (UPDATE cameras) all wait for the whole run, including per-photo weather HTTP calls.
- **Fix:** Fixed by E-04's per-camera commit. No separate change needed.

### E-18 — UBox login errors show the code class name instead of the readable reason

*low · confirmed · ux · effort S* — `backend/app/ingestion/ubox_sync.py:332`, `backend/app/ingestion/ubox_sync.py:341`, `backend/app/ingestion/ubox.py:56-57`

- **What the hunter sees:** The hunter can't tell a wrong password from a UBox outage.
- **Evidence:** PROVEN with test_e_ubox.py::test_safe_vendor_message_is_replaced_by_exception_class_name: login raises UboxError('UBox rejected the account or password'), and Settings shows 'Problem: Account connection failed (UboxError)'. UboxError's own docstring says its message is safe to show.
- **Verifier:** ubox_sync.py:332 and :341 format errors as type(exc).__name__, so a login failure shows 'Account connection failed (UboxError)' (the auditor's test passes), even though UboxError is documented as safe to show (ubox.py:54-55) and carries 'UBox rejected the account or password'.
- **Fix:** For UboxError, use str(exc) mapped to hunter words ('UBox refused the password — re-enter it', 'Couldn't reach UBox'). Keep the class-name fallback only for unexpected exceptions, and give InvalidToken (see E-07) its own 're-enter the password' message.

### E-19 — Suntek imports that hit a disk or file-lock error are parked for good and never reported

*low · confirmed · reliability · effort S* — `backend/app/ingestion/ftp_import.py:326-332`, `backend/app/ingestion/ftp_import.py:391-406`

- **What the hunter sees:** After a short disk-full or file-lock incident, those Suntek photos never appear and nobody is told.
- **Evidence:** Only DB OperationalError and pool timeouts count as transient. An OSError from _atomic_write moves the package to failed/, which only the CLI 'retry' command replays. Examples: disk full (ENOSPC), or a Windows sharing violation from antivirus on the media folder on Db01. No count of failed packages reaches the app.
- **Verifier:** _transient_db_failure (ftp_import.py:326-332) only treats OperationalError, pool timeouts and invalidated connections as transient. Any OSError from _atomic_write goes to failed/ (ftp_import.py:399-406), which only the CLI 'retry' replays (existing test_failed_import_keeps_photo_and_explicit_retry_succeeds confirms 'failures never spin on their own'). /admin/status (routes_admin.py:77-88) reports nothing about the spool. On ENOSPC the error.json write can itself raise inside the except block and crash the --watch loop.
- **Fix:** Treat ENOSPC, EACCES, PermissionError and Windows sharing violations as deferred: return the package to ready/, stop the batch, and keep an attempt counter in the package. Park it in failed/ only after N attempts. Guard the error.json write with try/except so it can't kill the watcher, and expose failed/ and ready/ counts (via a settings path) in /admin/status.

### E-20 — Right after connecting, the new login shows '0 cameras' under 'SPYPOINT reports 3 camera(s)'

*low · confirmed · ux · effort S* — `backend/app/api/routes_camera_accounts.py:76-82`, `backend/app/api/routes_camera_accounts.py:183-216`, `frontend/src/pages/Admin.tsx:176-189`

- **What the hunter sees:** It looks as if the connection failed.
- **Evidence:** list_accounts counts cameras by Camera.account_id, which is set only when the background import upserts the cameras. Admin.tsx reloads the list immediately after the POST, so the new row reads '0 cameras' next to 'Connected — SPYPOINT reports 3 camera(s). Fetching photos now.' and never refreshes.
- **Verifier:** list_accounts counts cameras by Camera.account_id (routes_camera_accounts.py:76-82). backfill_account commits the upserted cameras only after the first photo page (sync.py:166), while Admin.tsx:188 reloads the list right after the POST and never polls again. So the new row reads '0 cameras' next to 'Connected — SPYPOINT reports N camera(s)'.
- **Fix:** As proposed: return the verified camera count on the account, or show 'importing…' while last_sync_at is None. Refetch the list a few times, or when the import's SyncLog finishes.

### E-21 — Every account logs in fresh every 15 min, with no token reuse and no handling of rate limits

*low · plausible · reliability · effort M* — `backend/app/ingestion/ubox.py:220-244`, `backend/app/ingestion/spypoint.py:225-259`, `backend/app/ingestion/sync.py:196-199`, `backend/app/ingestion/ubox_sync.py:307-309`

- **What the hunter sees:** Risk that SPYPOINT or UBox throttles or locks a guest's login.
- **Evidence:** Each run logs every account in again: about 96 logins per day per account, plus manual checks. Each UBox login sends a new random device_token, even though the token is valid for 696 h (docs/18). SPYPOINT and UBox 429/5xx responses get no retry or backoff, so one 429 on /camera/all fails the whole account for that run.
- **Verifier:** The facts hold. Every run constructs a new client and calls login() (sync.py:196-198, ubox_sync.py:307-308). UBox login sends a new random device_token each time (ubox.py:230-236). SpypointClient._request raises on any status of 400 or above, including 429, with no backoff (spypoint.py:257-258). Throttling or lockout is speculative: about 96 logins/day per account has not been shown to trigger it.
- **Fix:** Low priority: keep one stable device_token per UBox account, cache tokens encrypted with their expiry, and honour Retry-After once on 429 or 5xx.

### E-22 — The same login can be added twice, and both copies are synced every run

*low · confirmed · bug · effort S* — `backend/app/api/routes_camera_accounts.py:128-140`, `backend/app/ingestion/sync.py:26-41`

- **What the hunter sees:** Double API traffic, which adds to the throttling risk in E-21, and confusing account ownership.
- **Evidence:** The duplicate check is an exact, case-sensitive username match and ignores settings.spypoint_username. 'Julle@gmail.com' can therefore sit next to 'julle@gmail.com' or next to the .env primary login. Both are synced every run, and camera.account_id flips between them.
- **Verifier:** The duplicate check is an exact match (routes_camera_accounts.py:134-140), as is the DB constraint uq_camera_accounts_provider_username (models.py:86), and neither considers settings.spypoint_username. The .env primary is not listed in Settings (see E-05), so an admin re-adding it there is realistic, and both copies would then sync every run. Minor inaccuracy: for primary plus guest, account_id is set to the guest row and doesn't flip back, because a primary id of None is never written (sync.py:62-63).
- **Fix:** Compare lower(username), add a unique index on (provider, lower(username)), and reject a SPYPOINT guest login equal to settings.spypoint_username (case-insensitive) with 'This login is already connected as the estate's main account'.

### E-23 — Cameras whose login was removed show as 'offline — check battery' forever

*low · confirmed · ux · effort S* — `backend/app/api/routes_camera_accounts.py:256-258`, `backend/app/health.py:17-46`, `backend/app/forecasting/alerts.py:88-92`

- **What the hunter sees:** False alerts after someone disconnects a login on purpose.
- **Evidence:** remove_account sets account_id to NULL but leaves the cameras active. 36 h later they count as offline, and the alerts say 'Check battery and signal on your next visit' indefinitely. Camera.active is not checked by health, alerts or the forecast.
- **Verifier:** remove_account only sets Camera.account_id to NULL (routes_camera_accounts.py:257). alerts.py:73 and forecast_tonight (model.py:290) select all cameras without filtering on active (only changes.py filters it), and there is no endpoint to deactivate a camera. So orphaned cameras show 'offline… Check battery and signal' indefinitely.
- **Fix:** On removal, set active=False on cameras no other login still reaches (the next sync re-activates any camera a remaining login lists). Filter active in alerts, forecast and health, and label the card 'Not connected (login removed)'.

### H-22 — FTP and email cameras show as 'offline' after 36 quiet hours, and the forecast treats them as not producing

*low · confirmed · data-correctness · effort S* — `backend/app/health.py`, `backend/app/ingestion/ftp_import.py`

- **What the hunter sees:** A working Suntek camera on a quiet stretch looks broken, and its genuine absence of game is not reflected in tonight's ranking.
- **Evidence:** For Suntek cameras, last_report_at only advances when a photo arrives (ftp_import.py:301), and health.py:13-21 marks a camera offline after OFFLINE_HOURS=36. producing=False (health.py:46) makes the forecast skip that camera's recency penalty (model.py:147-150) and suppresses the 'gone quiet' alert (alerts.py:105-106). The Cameras page shows 'Quiet since yesterday' in the SKIP colour (Cameras.tsx:101-105).
- **Verifier:** For FTP and email cameras, last_report_at only moves when a photo arrives (ftp_import.py:300). health.py:13-21 marks a camera offline after 36 h, and producing=False (health.py:46) then skips the recency penalty (model.py:150) and suppresses gone-quiet (alerts.py:105). The camera also shows up in Tonight's alerts. Whether the Suntek sends a daily heartbeat photo is unknown.
- **Fix:** For cameras with neither spypoint_id nor ubox_uid, report 'no heartbeat available' rather than 'offline'. Treat them as producing unless they have been silent for more than about 7 days, or unless received photos show a daily report pattern.

### I-30 — 'Check for new photos' says 'Nothing new since last time' even when a login failed or nothing was checked

*low · confirmed · ux · effort S* — `backend/app/ingestion/sync.py`, `backend/app/api/routes_cameras.py`, `frontend/src/pages/Cameras.tsx`

- **What the hunter sees:** When a guest's camera login breaks, the check still looks clean and their cameras go quiet unnoticed.
- **Evidence:** In sync.py:220, the run status is 'ok' if any single account worked, so a failed guest login or a per-camera error (lines 206-216) still reads as ok. In routes_cameras.py:74, the 'skipped' provider results (no logins configured) also give 'ok'. Cameras.tsx:343-347 then shows 'Nothing new since last time.' Proven for the skipped case: with no SPYPOINT or UBox logins, the button reported 'Nothing new since last time.' after 2.7 s. The sync_log details said both providers were 'skipped'. The partial-failure path is shown by the code only.
- **Verifier:** Code path confirmed. _run sets status 'ok' if any account succeeded (sync.py:220), and the pipeline summary treats 'skipped' and partial failures as ok (routes_cameras.py:73-76). Cameras.tsx:343-347 then says 'Nothing new since last time.' Downgraded because a camera whose login broke will stop updating last_report_at and surface in camera-health alerts within hours.
- **Fix:** The proposed fix is right. Mark the pipeline row 'partial' when accounts_failed > 0 or any camera has an error, and have Cameras.tsx name the failing login.


## 5. Background jobs and the AI pass run reliably

### F-04 — A detector or model failure is recorded as a watched night with no animals, retried forever in classification, and reported as 'classified'

*high · confirmed · data-correctness · effort M* — `backend/app/ai/empty_filter.py`, `backend/app/ai/species.py`, `backend/app/forecasting/exposure.py`

- **What the hunter sees:** After a bad deploy or broken weights, every new night counts as 'the camera was watching and saw nothing'. Tonight's presence figures drop, the forecast is scored as misses, and the photos show only as 'Animal'/'Unknown animal'. Nothing tells anyone the AI is down.
- **Evidence:** empty_filter.py:29,36-39: processed_at is set before detection, and any exception (ultralytics import error, corrupt or partial weights, unreadable file) sets is_empty_frame=False and returns. The frame counts as scanned, and nothing ever re-scans it. species.py:50-56 then fails on the same frame every run with only a log warning, and line 74 returns classified=len(images) whatever happened. exposure.py:88/134-141 only checks processed_at, so the night becomes CONFIRMED. There is no circuit breaker: a model that cannot load is retried once per image across up to 5000 images. Proven (scratch pytest, mocked detector raising): after scan and classify, the image had processed_at set, is_empty_frame=False and animal_conf=None, the night was CONFIRMED, there were 0 detections, and the result was {'classified': 1, 'by_species': {}}.
- **Verifier:** Reproduced with the detector raising. Scan returned {'animal':1}, and the image had processed_at set, is_empty_frame=False and animal_conf=None (empty_filter.py:29,36-39). Each classify pass returned {'classified': 1, 'by_species': {}} (species.py:74 returns len(images)) and retried the image on every run. The night came out CONFIRMED (exposure.py:131-142) with 0 detections, so a broken model reads as 'watched, no animals'.
- **Fix:** The proposed fix is sound. In addition, catch model-load failures (ImportError, a failing _get_model or weights download) once per pass and abort before touching any rows. Otherwise, with missing weights and a hanging download host, every image repeats the 300 s download attempt.

### F-08 — A network, auth or credit failure in the cloud sex pass permanently uses up each photo's only attempt

*high · confirmed · bug · effort S* — `backend/app/ai/vision_sex.py`, `backend/pipeline.py`

- **What the hunter sees:** If the API key is wrong, credit runs out or the line drops during a run, hundreds of stags, hinds, boar and sows are marked as checked but never labelled, and they stay 'Red deer' or 'Wild boar' forever. The only trace is a log warning.
- **Evidence:** vision_sex.py:30 sets MAX_SEX_ATTEMPTS=1. Lines 180-190 increment sex_attempts before the call and only log a warning on any exception, and the query at 171 then excludes the crop forever. The hourly 'sex' mode processes up to 150 per species (pipeline.py:95-97). Proven (scratch pytest): classify_sex raising anthropic.APIConnectionError gave run1 {'processed': 1, 'undetermined': 0}. After the API 'recovered', run2 was {'processed': 0} and the detection stayed sex='unknown', attempts=1.
- **Verifier:** Reproduced: classify_sex raising anthropic.APIConnectionError gave run1 {'processed': 1}. After the API recovered, run2 was {'processed': 0}, and the detection stayed sex='unknown' with sex_attempts=1 (vision_sex.py:30,171,180-190). The SDK already retries transient errors twice, so what reaches this except is a sustained outage, a bad key or exhausted credit. At 150 crops per species per hourly run, those burn every crop's only attempt.
- **Fix:** After the SDK's built-in retries, treat any anthropic.APIError, including APIConnectionError and APIStatusError, as not an attempt. Undo the increment and abort the whole pass instead of continuing through the batch. Count an attempt only when a tool_use block came back. Record the last error in a status the Admin page shows.

### J-01 — Tonight's claim job skips itself whenever sync or the sex pass holds the lock, and a missed night is never scored

*high · confirmed · reliability · effort S* — `backend/pipeline.py`, `deploy/register-tasks.ps1`, `backend/app/forecasting/scoring.py`, `docs/09-deployment.md`

- **What the hunter sees:** Nothing on screen says a night was missed. The 'How often this has been right' line stays stuck at 'N scored nights so far', and any night with no claim written before dusk can never be graded, so the honesty loop quietly stalls.
- **Evidence:** pipeline.py:105-107: if pipeline.lock exists, `plan`/`score` log pipeline.skip_locked at info level and exit 0. GameSense-Sync runs every 15 min and GameSense-Sex hourly (docs/09-deployment.md:50-54), so the 17:00 Plan races both of them, and a 16:45 sync still doing CPU AI can be holding the lock. register-tasks.ps1 sets no retry, and Task Scheduler sees the run as a success. scoring.py:133 evaluate_night only scores yesterday, so a skipped 11:00 Score is never retried. Taking the lock is not atomic either (exists check, then write_text: pipeline.py:43-46,108). PROVEN: with a lock file present, running `pipeline.py plan` logged pipeline.skip_locked and never called _run.
- **Verifier:** pipeline.py:105-107 returns exit 0 on a held lock, and register-tasks.ps1:31-33 only sets StartWhenAvailable, which covers missed triggers, not a run that exits cleanly. Sync fires every 15 min, so it can land on 17:00/11:00 exactly, and the check-then-write lock (pipeline.py:43-46,108) makes that a race. scoring.py:133 only ever scores date.today()-1, so a skipped Score run is never graded.
- **Fix:** In plan/score, poll the lock (every 30 s, up to about 40 min) instead of returning, and take it atomically with os.open(O_CREAT|O_EXCL). Make `score` loop over every night in the last 14 days that has Forecast rows but no ForecastOutcome. For `plan`, a catch-up in `sync` (from 15:00 to sunset local, no Forecast for today yet) is enough; never write one after dark.

### C-21 — A restart during a manual check leaves the pipeline lock behind and blocks all syncing for 3 hours

*medium · plausible · reliability · effort S* — `backend/app/api/routes_cameras.py`, `backend/pipeline.py`

- **What the hunter sees:** After an update during hunting season, no new photos arrive for up to 3 hours and nothing on screen says why.
- **Evidence:** _run_locked (routes_cameras.py:36-48) writes pipeline.lock and removes it only in `finally`. If the API process is killed mid-run (deploy or service restart), the file stays. _pipeline_busy (31-33) and pipeline.py _locked (40-45) treat any lock younger than 3h as held, with no PID or heartbeat check. For 3h the scheduled 15-min sync exits early, the button answers 'busy', which combined with C-07 means an endless spinner, and no photos or alerts arrive. The mtime is never refreshed, so a backfill longer than 3h counts as stale and a second run can overlap it. The check-then-write is also not atomic. Proven by code reading.
- **Verifier:** _run_locked (routes_cameras.py:36-48) and pipeline.py:110-116 only remove the lock in finally, and staleness is a flat 3h on mtime with no PID check, so a killed process blocks sync for up to 3h. The specific trigger cited, a deploy restart, is mostly guarded: update.ps1:32 stands down while the lock is fresh. Real triggers remain: the TOCTOU window between that check and the restart minutes later in update.ps1, reboots, service restarts, and Task Scheduler's 1h ExecutionTimeLimit (register-tasks.ps1:33) killing plan/score. A stale lock also blocks deploys for the same 3h.
- **Fix:** Write '{owner} {pid} {ts}' and create the lock atomically (O_CREAT|O_EXCL). Treat it as stale when the PID is dead. On API startup, delete any 'api' lock, since a fresh process means the old run is dead. Touch the lock periodically during long runs and cut staleness to about 20 min. Have update.ps1 re-check the lock immediately before restarting GameSenseAPI.

### E-11 — The pipeline lock file can be deleted by a run that doesn't own it, and a crash leaves photos blocked for up to 3 h

*medium · confirmed · reliability · effort M* — `backend/app/api/routes_cameras.py:27-48`, `backend/pipeline.py:39-46`, `backend/pipeline.py:105-115`, `deploy/update.ps1:33-36`

- **What the hunter sees:** After a crash there are no new photos for up to 3 h while the button says 'Already checking'. Long imports can be cut short by a deploy or run twice.
- **Evidence:** The API checks _pipeline_busy() inside the request but writes the lock later, in the background task. Its finally block then unlinks the lock unconditionally, even if pipeline.py wrote it in the meantime; pipeline.py has the same check-then-write gap. The lock has no PID and is never refreshed. After a crash (server reboot, API restart, Task Scheduler kill), a fresh lock blocks every scheduled sync and the button for up to 3 h. A run longer than 3 h, such as a 13-month backfill plus CPU AI, looks stale, so a second run can start on top of it. update.ps1 uses the same 3 h rule, so a deploy can also start and restart GameSenseAPI mid-run.
- **Verifier:** The code is unambiguous. routes_cameras.py:36-48 and pipeline.py:105-115 check, then write, then unconditionally unlink the lock, with no PID and no refresh. Nothing clears a leftover lock at startup (grep finds no other lock references), so a reboot or kill mid-run blocks every sync for 3 h, and update.ps1:33-36 uses the same 3 h rule. The auditor missed one consequence: plan (17:00) and score (11:00) also exit with 'skip_locked' (pipeline.py:105-107) and are not retried, so a stale or long lock at 17:00 means that night's forecast is never recorded or scored.
- **Fix:** Use a Postgres session advisory lock (pg_try_advisory_lock on a dedicated connection held for the run) in _run_locked and pipeline.main; it is released when the process dies. Add a 'pipeline.py busy' exit-code command, or a pg_locks query, for update.ps1 to use instead of the file age. Let plan and score bypass the sync lock (they are short and read-mostly), or retry them every 10 min until done.

### E-12 — A backlog of photos waiting for AI blocks new photo fetching and sighting alerts for hours

*medium · plausible · perf · effort M* — `backend/pipeline.py:55-71`, `backend/pipeline.py:105-107`, `backend/app/api/routes_cameras.py:51-66`, `backend/app/ai/empty_filter.py:46-49`, `backend/app/ai/species.py:41-71`

- **What the hunter sees:** Right after someone connects a login, new photos and sighting alerts stall for hours, possibly right at dusk.
- **Evidence:** 'sync' mode runs ingestion, then scan_unprocessed(limit=5000) and classify_unclassified(limit=2000), all under one lock. Any 15-minute run that finds the lock held simply exits. On CPU (1–3 s per frame, per docs D23), a backlog of a few thousand frames holds the lock for hours. Such backlogs follow a new guest's 2-month SPYPOINT backfill or a UBox 7-day import at up to 500/day, both of which add_account starts. Sighting notifications are sent only after the whole classify pass (species.py:62-71).
- **Verifier:** The structure is confirmed. pipeline.py:55-71 and routes_cameras.py:59-66 run fetch, then scan (limit 5000), then classify (limit 2000, with a second MegaDetector pass per frame) under one lock. add_account runs backfill_account (2 months) plus the full AI pass under the same lock (routes_camera_accounts.py:186-203). dispatch_new_sightings runs only after the whole classify pass (species.py:62-71). The duration was not measured, but at 1–3 s per frame on CPU (D23) thousands of frames means hours. This also causes the missed 17:00 'plan' run noted in E-11.
- **Fix:** Fetch under a short lock every run, then give AI its own lock (or a separate task) with a per-run cap of about 150–300 frames, newest first. Commit and dispatch notifications per batch of 20 (the classify loop already commits every 20).

### F-01 — Daily 'plan' and 'score' runs are silently dropped whenever a sync or sex pass holds the pipeline lock

*medium · confirmed · reliability · effort S* — `backend/pipeline.py`, `backend/app/forecasting/scoring.py`, `deploy/register-tasks.ps1`, `docs/09-deployment.md`

- **What the hunter sees:** On any evening the 17:00 plan collides with a sync, tonight's claim is never recorded, so that night can never be scored. The Tonight track record ('N scored nights') grows slowly or not at all, and a skipped 11:00 score run loses yesterday for good.
- **Evidence:** pipeline.py:105-107: every mode, including the DB-only 'plan' (17:00) and 'score' (11:00), exits with only an info log when pipeline.lock is fresh. GameSense-Sync fires every 15 min (so also at 17:00 and 11:00) and GameSense-Sex runs hourly for up to hundreds of cloud calls, so the lock is often held at those minutes. Nothing catches up afterwards: persist_tonight is only called from pipeline/Celery (no API fallback), and evaluate_night (scoring.py:133) only scores yesterday. Proven: I created the lock and ran `python pipeline.py plan` with MODELS_ROOT pointing at scratch. It printed {"event":"pipeline.skip_locked"} and exited 0 without touching the DB, so Task Scheduler records a success.
- **Verifier:** pipeline.py:105-107 returns exit 0 on a fresh lock for every mode, 'plan' included. I reproduced it: with a lock present, `pipeline.py plan` logged pipeline.skip_locked and exited 0. persist_tonight has no other caller in the native build (only pipeline.py:79 and the unused Celery tasks/scoring.py), and evaluate_night (scoring.py:133) only scores yesterday. Downgraded to medium because a collision depends on how the Sync and Sex tasks are anchored, which is not in the repo, and the damage is a slower track record rather than wrong advice.
- **Fix:** Do NOT exempt 'score' from the lock. It calls recompute_camera_nights, and a concurrent sync inserting the same new CameraNight row can hit uq_camera_night (models.py:414). Instead, have 'plan' and 'score' poll for the lock (for example every 30 s for up to ~40 min, inside the 1 h ExecutionTimeLimit) and exit non-zero if still blocked, so Task Scheduler shows a failure. Make evaluate_night catch up every night in the last 7 days that has Forecast rows and no ForecastOutcome. Do not back-fill a plan after dark: _claims_for says a claim made after dark is not a forecast.

### F-02 — The pipeline lock is not a real lock: it goes stale after 3h, is check-then-write, and the API run deletes a lock it does not own, so AI passes can double-run and create duplicate detections

*medium · confirmed · reliability · effort M* — `backend/pipeline.py`, `backend/app/api/routes_cameras.py`, `backend/app/api/routes_camera_accounts.py`, `backend/app/ai/species.py`

- **What the hunter sees:** Photos arrive late or not at all for up to 3h after a crash. When runs overlap, each photo gets two detections, which inflates the Detection-row counts that rank species on Tonight (model.py:95-110) and 'frames' in visits. Overlapping runs can also crash a sync on duplicate spypoint_photo_id inserts.
- **Evidence:** pipeline.py:43-46,105-108: the check and the write are separate steps, and the lock's mtime is written once and never refreshed, so a run over 3h (a 13-month backfill from /cameras/backfill, whose default is months=13, plus a CPU AI pass) looks stale and the 15-min sync starts on top of it. routes_cameras.py:174-178: the route checks _pipeline_busy() at request time, but _run_locked (36-47) writes the lock later in a background task without re-checking, and unlinks it unconditionally in finally. That happens even when another process wrote it, so the next scheduled run starts while one is still going. A process killed mid-run (reboot, service restart) leaves the lock, which blocks every sync and every deploy (update.ps1 checks the same file) for 3h. Two admins pressing 'Check for new photos' at once both pass the check. The consequence is proven with a scratch test: two concurrent classify_unclassified runs (mocked models) over 4 kept frames produced 8 Detection rows, because the ~has_detection filter is evaluated only at query time (species.py:42-48) and nothing constrains detections.image_id.
- **Verifier:** Check and write are separate steps (pipeline.py:105-108), and the file's mtime is never refreshed. _run_locked (routes_cameras.py:36-48) writes the lock without re-checking and unlinks it unconditionally, and _pipeline_busy uses the same 3 h staleness. I reproduced the consequence: a nested second classify_unclassified over 4 kept frames produced 8 Detection rows, because nothing constrains detections.image_id. Rated medium because overlap needs specific timing, a crash mid-run, or a run over 3 h (a 13-month backfill plus a CPU AI pass).
- **Fix:** The advisory lock is right, but it must be held on one dedicated connection for the whole run (pg_try_advisory_lock at session level, with the connection kept checked out). _run_locked must acquire it itself and return busy if it cannot. Keep writing the file only as a mirror for update.ps1, and refresh its mtime periodically as a heartbeat. Against duplicates, re-check `exists(Detection where image_id=…)` inside classify_image just before inserting, or claim images in small FOR UPDATE SKIP LOCKED batches. Avoid a unique index on image_id, which blocks storing several animals per frame later.

### F-05 — One failed download or one early manual review leaves a camera-night 'UNPROCESSED' forever

*medium · confirmed · data-correctness · effort S* — `backend/app/ai/empty_filter.py`, `backend/app/api/routes_images.py`, `backend/app/ingestion/sync.py`, `backend/app/forecasting/exposure.py`

- **What the hunter sees:** That camera-night is excluded from '10 of 44 nights this camera was watching' and from forecast scoring for good. One CDN hiccup or one tap on a fresh photo quietly removes real observations. The SPYPOINT photo itself is also lost.
- **Evidence:** scan_unprocessed (empty_filter.py:47-50) only selects images where original_path IS NOT NULL and reviewed IS FALSE. A SPYPOINT photo whose download failed is stored with original_path=None (sync.py:106-125) and is never re-downloaded (no code path retries cdn_url). A photo the hunter flags before the scan reaches it gets reviewed=True (routes_images.py:84-85), but processed_at is never set. exposure.py:88 counts any processed_at IS NULL row, so the night stays UNPROCESSED. Proven (scratch pytest, 3 scan runs): nights with one path-less image or one reviewed-before-scan image stayed 'UNPROCESSED'. The clean night was 'CONFIRMED'.
- **Verifier:** Reproduced: a path-less image and a reviewed-before-scan image both left their nights UNPROCESSED after 3 scans. scan_unprocessed filters out original_path IS NULL and reviewed rows (empty_filter.py:47), so scan_image's no-path branch (lines 30-33) is unreachable from it. A failed SPYPOINT download is stored with original_path=None and is never retried, because it is deduped by spypoint_photo_id (sync.py:103-120). The reviewed path is likelier than stated: Suntek FTP photos import every 30 s but are only scanned by the 15-min sync, so a hunter has up to 15 min to flag one first.
- **Fix:** The proposed fix is fine. Setting processed_at in flag_image when it is NULL is the minimal part. Pair it with a bounded re-download of cdn_url for rows with original_path NULL, and a one-off UPDATE for existing rows.

### F-10 — The cloud sex pass holds the AI lock through hundreds of sequential Opus calls, blocking photo sync, and it pays per frame rather than per visit

*medium · plausible · perf · effort M* — `backend/pipeline.py`, `backend/app/ai/vision_sex.py`

- **What the hunter sees:** After a backfill, or in the rut, new photos can arrive 30+ minutes late at dusk while the app labels old deer. The API bill is several times what one label per visit would cost.
- **Evidence:** pipeline.py:90-97: the 'sex' mode runs under the same pipeline.lock as 'sync' and makes up to 150 calls per species, one after another (claude-opus-5, $5/$25 per MTok, adaptive thinking on by default, SDK timeout 10 min × 3 attempts). The pass needs no local model, yet while it runs every 15-min sync exits 'skip_locked', and the Cameras button answers 'busy'. The query (vision_sex.py:166-175) has no ORDER BY, so tonight's sightings can wait behind the backlog, and each frame of a 3-5-shot burst of the same stag is billed separately.
- **Verifier:** Code confirms the 'sex' mode runs under pipeline.lock (pipeline.py:90-97) with up to 300 sequential claude-opus-5 calls. That model has adaptive thinking on by default at $5/$25, and the SDK's 10-min timeout is retried twice. The query has no ORDER BY (vision_sex.py:165-175), and each burst frame is billed separately. Per-call latency and real backlog sizes were not measured. Blocking only bites during a backlog, such as after a backfill.
- **Fix:** The proposed fix is sound. Its minimal first step is its own lock plus ORDER BY Image.captured_at DESC. Batches API and one crop per visit can follow.

### F-12 — 'Look for repeats' does all its heavy work inside the HTTP request, outside the lock, and is quadratic

*medium · plausible · perf · effort M* — `backend/app/api/routes_animals.py`, `backend/app/ai/reid.py`, `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** The first 'Look for repeats' after a busy week spins for minutes and then says 'Something went wrong (524)', although it is still running. Tapping again can leave duplicate candidates.
- **Evidence:** routes_animals.py:257-267 runs recompute(db) synchronously. That embeds up to 5000 un-embedded crops with DINOv2 ViT-L on CPU (reid.py:44-68, roughly 0.5-1 s each), loads every 1024-float JSONB embedding (reid.py:129-140), then runs a greedy loop that renormalises every centroid for every detection (reid.py:153-160). I timed the same loop on synthetic 1024-d vectors: 500 took 0.3 s, 1000 took 1.3 s and 2000 took 5.2 s, which is quadratic. It takes no pipeline lock, so it runs next to a sync that has ViT-L loaded in another process. The frontend fetch has no timeout. A tunnel with a request limit (cloudflared, 100 s) returns an error while the work carries on, and 'Look for repeats' is enabled again, so a second concurrent recompute deletes and rebuilds the same candidates.
- **Verifier:** Verified in code: recompute runs synchronously in the request (routes_animals.py:257-267) and takes no lock. It embeds up to 5000 crops with ViT-L on CPU (reid.py:44-68). I reproduced the quadratic greedy loop: 500 detections took 0.32 s, 1000 took 1.23 s, 2000 took 5.04 s. cloudflared is in the deploy toolset, and api() has no timeout. The 524 and the duplicate candidates on a second tap were not reproduced end to end.
- **Fix:** The proposed fix is fine. The cheapest win is to embed new detections at the end of classify_unclassified in the pipeline and run recompute as a locked background job returning 202.

### F-13 — Manual checks load MegaDetector and ViT-L into the web server, where they stay resident and compete with page requests for CPU

*medium · plausible · perf · effort M* — `backend/app/api/routes_cameras.py`, `backend/app/api/routes_camera_accounts.py`, `backend/app/ai/classifier.py`, `backend/app/ai/detector.py`, `backend/serve.py`

- **What the hunter sees:** After 'Check for new photos', the app is sluggish while the AI pass runs. The server keeps ~1.5-2 GB more memory for good, and a second copy loads when the scheduled pipeline runs, which can push the VM into swap.
- **Evidence:** _sync_work (routes_cameras.py:50-80), trigger_backfill/trigger_scan (180-213) and the add-account backfill (routes_camera_accounts.py:184-203) run scan_unprocessed and classify_unclassified inside the single uvicorn process (serve.py starts one worker). Both models are module globals that are never released (classifier.py _model, detector.py _model): about 1.2 GB fp32 for ViT-L plus YOLOv9-c and the torch runtime. By default torch uses every core for intra-op work in the same process that serves Tonight and Photos.
- **Verifier:** Confirmed in code: the manual sync, scan, backfill and add-account routes run scan and classify in the single uvicorn process (serve.py starts one worker; routes_cameras.py:50-80,180-213). _model globals are never released (detector.py:159, classifier.py:53), and ViT-L alone is ~1.2 GB in fp32. The sluggishness and swap were not measured.
- **Fix:** The proposed fix is sound. Running the button's work as a `pipeline.py sync` subprocess also brings it under the same lock semantics as the scheduled runs.

### F-15 — The app never shows that a photo is still being checked or that checking failed

*medium · confirmed · ux · effort M* — `backend/app/api/visibility.py`, `backend/app/api/routes_photos.py`, `frontend/src/pages/Cameras.tsx`, `backend/app/api/routes_admin.py`

- **What the hunter sees:** Right after a sync, empty frames appear as 'Animal' and the camera card announces an 'Unknown animal'. A minute later they vanish as the scan catches up, which feels like flicker and false alarms. When the AI is broken, every photo just says 'Animal' with no explanation.
- **Evidence:** VISIBLE_ANIMAL (visibility.py:25) accepts is_empty_frame IS NULL, so frames the detector has not reached yet are listed as animal photos. The Photos feed labels anything without a detection 'Animal' (routes_photos.py:112). Cameras labels it 'Unknown animal', and the card headline reads 'Last seen: Unknown animal, 2 min ago' (Cameras.tsx:230,236-239). No field in any payload says pending or failed, and /admin/status (routes_admin.py:77-88) reports no backlog or AI error. Combined with F-04, failed frames stay 'Animal' forever.
- **Verifier:** VISIBLE_ANIMAL accepts is_empty_frame NULL (visibility.py:25). The Photos feed falls back to 'Animal' (routes_photos.py:112), and Cameras shows 'Unknown animal', including in the 'Last seen' line (Cameras.tsx:230-239). The window is larger than claimed: Suntek FTP photos are imported every 30 s but only scanned by the 15-min sync, so unscanned blanks show as 'Unknown animal' for up to 15 min. /admin/status (routes_admin.py:77-88) reports no backlog or AI error.
- **Fix:** The proposed fix is sound. The cheapest partial fix is to leave frames with processed_at NULL out of the 'Last seen' line, or to scan FTP imports right after import.

### F-17 — An interrupted model download is kept as if complete, with no checksum, and the weights are unpickled with weights_only=False

*medium · confirmed · reliability · effort S* — `backend/app/ai/detector.py`, `backend/app/ai/classifier.py`

- **What the hunter sees:** After one bad download on a fresh install or model update, every scan fails. Through F-04 that means every photo shows as 'Animal' and every night counts as watched with no animals, until someone deletes the file by hand.
- **Evidence:** detector.py:28-39 and classifier.py:59-70 stream straight into the final path and only check os.path.exists. A connection drop leaves a truncated file that later runs use as-is (ViT-L is about 1.2 GB with a 900 s timeout). classifier.py:88 uses torch.load(weights_only=False) on a file from HuggingFace, and line 94 loads with strict=False, which hides key mismatches. Proven (scratch pytest, mocked httpx.stream resetting after 1 KB): the first _weights_path raised, and the second returned the 1024-byte file with no new download attempt.
- **Verifier:** Both downloaders stream straight into the final path and check only os.path.exists (detector.py:163-174, classifier.py:59-70), so an interrupted download leaves a truncated file that later runs reuse. classifier.py:88 unpickles a third-party HuggingFace mirror file with torch.load(weights_only=False), and line 94 loads with strict=False, which hides a missing head. Combined with F-04, a bad file silently disables the AI.
- **Fix:** The proposed fix is sound: .part plus size/sha256 check plus os.replace, delete the file on a load error, and check the load_state_dict key report.

### G-15 — Plan/score runs are silently dropped when the pipeline lock is held, and missed nights are never scored

*medium · confirmed · reliability · effort M* — `backend/pipeline.py`, `deploy/register-tasks.ps1`, `backend/app/forecasting/scoring.py`

- **What the hunter sees:** On busy evenings no claim is recorded, and on busy mornings nothing is graded. 'N scored nights so far' grows slowly and unevenly, so the track record never becomes available or is biased toward quiet days.
- **Evidence:** pipeline.py:103-105: if the lock is held (the 15-min sync with the CPU AI pass, or the hourly sex pass), 'plan' and 'score' log skip_locked and exit 0. register-tasks.ps1:46-49 registers each once daily at a fixed time with no retry, and the 17:00/11:00 triggers coincide with the :00 sync and hourly runs. evaluate_night (scoring.py:131-176) only grades the single previous night. Nights skipped as UNPROCESSED at 11:00, or missed because the task skipped, are never revisited.
- **Verifier:** I simulated pipeline.main() with the lock present and mode 'plan' (verify-G/lock_sim.py): it logs pipeline.skip_locked and returns normally with exit 0, so Task Scheduler records success and never retries (register-tasks.ps1:24-49 has only daily triggers). evaluate_night defaults to date.today()-1 only (scoring.py:133), so a skipped or UNPROCESSED night is never graded. How often the 17:00/11:00 runs collide with the 15-min sync or the hourly sex pass depends on run length, which I could not measure.
- **Fix:** plan does not load AI models and only inserts Forecast rows, so let it bypass the lock, or poll for it for <= 30 min. score should poll for the lock. Make evaluate_night grade every Forecast from the last 14 days that has no ForecastOutcome and a CONFIRMED or PRESUMED_UP camera-night, but only after G-12 is fixed; otherwise dead-battery gaps become misses. Also check _locked/write_text: they are not atomic, so two runs starting in the same second can both proceed. Use os.open with O_CREAT|O_EXCL.

### H-02 — The 17:00 plan run and the 11:00 score run silently skip whenever a sync holds the lock, so tonight's forecast is never recorded

*medium · confirmed · data-correctness · effort S* — `backend/pipeline.py`, `deploy/register-tasks.ps1`

- **What the hunter sees:** That night is never claimed, so it can never be scored. Tonight's track record ('N scored nights') grows more slowly, or not at all, and nobody can tell why: Task Scheduler shows success.
- **Evidence:** pipeline.py:105-107: if _locked() it logs pipeline.skip_locked at info level and returns exit code 0. register-tasks.ps1:25-33 runs 'pipeline.py plan' once a day at 17:00, and 'score' at 11:00. StartWhenAvailable only helps with starts that were missed, not runs that exit early. The Sync task runs every 15 minutes (docs/09-deployment.md:51) and does download plus CPU AI under the same lock, and the hourly 'sex' pass also takes the lock. So any sync or sex pass running at 17:00 makes plan exit with no claim written. PROVEN: with a lock file present, `MODELS_ROOT=... python pipeline.py plan` printed skip_locked, exit=0, and model_runs stayed at 0 rows.
- **Verifier:** Reproduced: with pipeline.lock present, `pipeline.py plan` logged skip_locked, exited 0 and wrote 0 model_runs (pipeline.py:105-107). Nothing catches up later: evaluate_night only ever scores yesterday (scoring.py:133), and plan runs once a day. How often a sync or sex pass actually overlaps 17:00/11:00 depends on the Sync/Sex task triggers, which are not in the repo. The check-then-write lock (105-108) is also racy when tasks start in the same minute.
- **Fix:** For plan/score only, wait for the lock: poll every 30 s for up to about 40 min, which fits the 1 h ExecutionTimeLimit in register-tasks.ps1. If the lock never frees, exit 1. Make score catch up by evaluating every target_date in the last ~7 days that has Forecast rows but no ForecastOutcome, not just yesterday. Do NOT add a plan catch-up after sunset: a claim written after dark is not a forecast (see _claims_for). Only catch up if the current time is before local sunset.

### H-03 — The pipeline lock only goes by file age: a crash or reboot blocks all syncing for 3 hours, but a genuine run longer than 3 hours lets a second run in, which double-counts detections

*medium · confirmed · reliability · effort M* — `backend/pipeline.py`, `backend/app/api/routes_cameras.py`, `deploy/update.ps1`, `backend/app/ai/species.py`

- **What the hunter sees:** (a) After a reboot, no new photos arrive for up to 3 hours and 'Check for new photos' answers 'Already checking'. (b) After a big import, sightings are counted twice in every stat and alerts can fire twice.
- **Evidence:** The lock counts as held while its mtime is under 3 hours old (pipeline.py:40-46, routes_cameras.py:31-33, update.ps1:32). It is written once and never refreshed (pipeline.py:108, routes_cameras.py:39). (a) If the process is killed (Windows Update reboot, or Restart-Service GameSenseAPI during a manual 'Check for new photos'), the finally block never runs. The leftover lock then blocks scheduled syncs, the Check button ('Already checking'), plan/score and deploys for up to 3 hours. (b) A run that lasts longer than 3 hours looks stale to the next 15-minute sync, which then starts alongside it. Examples: /cameras/backfill defaults to months=13 (routes_cameras.py:184) and runs in the API; a first UBox import pulls 7 days at up to 500 photos per day per camera. classify_unclassified (species.py:41-60) claims nothing, so both runs classify the same photos. PROVEN with scratch/H/dup_classify.py: two overlapping classify_unclassified runs over 20 new photos produced 40 detections.
- **Verifier:** Code: the lock is judged only by mtime < 3 h and is never refreshed (pipeline.py:40-46,108; routes_cameras.py:31-39; update.ps1:32). A killed process skips the finally block, so the lock stays until 3 h after it was written. A run longer than 3 h lets the next sync in, and that sync's finally then deletes the lock the long run still needs. Reproduced the double-count: two staggered classify_unclassified runs over 60 photos produced 100 detections for 60 images. The >3 h trigger (a big backfill or a 5000-photo scan_unprocessed backlog) is realistic but rare, so this is medium, not high.
- **Fix:** Smallest cross-platform fix: acquire the lock atomically (os.open with O_CREAT|O_EXCL, writing the PID). Start a daemon heartbeat thread that touches the lock mtime every 60 s for the whole run, in both pipeline.py and _run_locked. Drop the stale threshold to about 10 min in all three places (pipeline.py, routes_cameras.py, update.ps1). A dead process then frees the lock within minutes, and a live long run never looks stale. Only unlink the lock if its PID is ours. Separately, select images in classify_unclassified/scan_unprocessed with FOR UPDATE SKIP LOCKED in small committed batches, as a backstop.

### H-11 — Output from every scheduled pipeline run is thrown away, so failures and skips leave no trace

*medium · confirmed · reliability · effort S* — `deploy/register-tasks.ps1`, `backend/pipeline.py`, `backend/app/core/logging.py`

- **What the hunter sees:** When photos stop arriving or alerts go quiet, the owner has nothing to look at. The problem only shows up as 'the app feels stale'.
- **Evidence:** The scheduled-task action is `python.exe pipeline.py <mode>` with no redirection (register-tasks.ps1:25). configure_logging() only prints JSON to stdout through structlog's PrintLoggerFactory (logging.py:7-20), and Task Scheduler discards stdout. So pipeline.skip_locked, sync.account_failed, classify.failed, notify.failed and even unhandled tracebacks from sync, sex, plan and score are never written anywhere. By contrast, the FTP and mail services get rotating log files (install-ftp.ps1:178-181).
- **Verifier:** register-tasks.ps1:25 runs pipeline.py with no redirection, and configure_logging sends structlog output only to stdout via PrintLoggerFactory (logging.py:17), which Task Scheduler discards. So plan/score skips and failures leave no text anywhere. Two overstatements: unhandled exceptions already exit 1 (visible as Last Run Result), and provider failures do reach the sync_log table (sync.py:218-223, ubox_sync.py:352-362). The Sync/Sex task definitions are not in the repo.
- **Fix:** In pipeline.py, add a RotatingFileHandler to C:\GameSense\logs\pipeline.log and route structlog through stdlib logging, or simply append JSON lines to that file. Exit non-zero from plan/score when the lock is never acquired (ties to H-02).

### H-19 — 'Check for new photos' runs the whole AI pass inside the web API process

*medium · plausible · perf · effort S* — `backend/app/api/routes_cameras.py`, `backend/app/ai/detector.py`, `backend/app/ai/classifier.py`

- **What the hunter sees:** After a hunter taps 'Check for new photos' at dusk, every page (Tonight, Map, Photos) crawls for minutes, and the API process keeps an extra 1-2 GB of memory. A deploy restart in the middle also leaves a stale lock (H-03).
- **Evidence:** POST /cameras/sync queues _sync_work as a FastAPI BackgroundTask in the API process (routes_cameras.py:173-178, 50-66). That runs scan_unprocessed and classify_unclassified, which load MegaDetector and the DINOv2 ViT-L into module-level globals (detector.py:24-52, classifier.py:53-100). Those models then stay resident in the API for good, and torch takes every core while it classifies. /cameras/backfill (months up to 24) does the same. Db01 also runs a production MS SQL Server (09-deployment.md:104).
- **Verifier:** Confirmed in code: POST /cameras/sync runs _sync_work (downloads, then scan_unprocessed and classify_unclassified) as a BackgroundTask in the API process (routes_cameras.py:51-66,173-178). The detector and classifier keep their models in module globals (detector.py:24-52, classifier.py:53-100), so they stay resident in the API after the first press. The 'every page crawls' impact is not measured. The button is admin-only.
- **Fix:** Have the button spawn the venv's `python pipeline.py sync` detached, which also moves the stale-lock-on-API-restart problem out of the API. Note that the Check button's result line reads the combined 'pipeline' SyncLog row that only _sync_work writes (routes_cameras.py:72-80), so that summary row must move into pipeline.py's sync mode, or the button will report the UBox row alone.

### C-22 — "Look for repeats" runs the whole re-ID inside one HTTP request, outside the pipeline lock

*low · plausible · reliability · effort M* — `backend/app/api/routes_animals.py`, `backend/app/ai/reid.py`, `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** The button sits on 'Looking…' for minutes, then often shows a network error even though the work is still running, and it slows the photo sync.
- **Evidence:** recompute_animals (routes_animals.py:257-267) calls recompute(db) synchronously. The first pass embeds up to 5000 crops with DINOv2-L on CPU (reid.py:43-67), which takes minutes or longer, and the UI shows 'Looking…' the whole time (Animals.tsx:286). It doesn't take pipeline.lock, so it can run alongside the 15-min sync and its detector models. A phone that sleeps or drops signal aborts the request and shows a raw error while the server carries on. Proven by code reading.
- **Verifier:** recompute_animals (routes_animals.py:256-267) runs embed_detections plus cluster inside the request. embed_crop is DeepFaune's DINOv2 ViT-L on CPU (classifier.py:1,132-143), with up to 5000 crops per pass (reid.py:44), and no pipeline.lock is taken. The UI itself says 'It takes a few minutes' (Animals.tsx:308). A multi-minute request is likely to drop on mobile, but no timing was measured.
- **Fix:** Run it as a BackgroundTask via _run_locked. Return {status:'started'} or {status:'busy'} and poll a small status endpoint, reusing the sync-button pattern.

### F-09 — Two sex passes can run at once and bill every crop twice

*low · confirmed · bug · effort S* — `backend/app/api/routes_admin.py`, `frontend/src/pages/Admin.tsx`, `backend/app/ai/vision_sex.py`

- **What the hunter sees:** Tapping 'run' twice, or tapping it while the hourly pass runs, doubles the Anthropic bill for the same labels.
- **Evidence:** routes_admin.py:24-43 starts _run_sex_pass as a background task with no lock or 'already running' check, and it ignores the hourly GameSense-Sex run. Admin.tsx:129-138 turns sexBusy off as soon as the POST returns 'started', so the button can be tapped again immediately. sex_unclassified loads its batch up front and commits attempts only every 20 rows (vision_sex.py:166-196). Proven (scratch pytest): two concurrent sex_unclassified runs over 6 red-deer crops made 12 classify_sex calls.
- **Verifier:** Reproduced: a second sex_unclassified started during the first made 12 classify_sex calls for 6 crops. The admin route starts _run_sex_pass with no lock and no busy check (routes_admin.py:24-43). Admin.tsx:129-138 re-enables the button as soon as the POST returns. Downgraded to low because the waste is a few dollars per overlap.
- **Fix:** Use one dedicated 'sex-pass' advisory lock in both pipeline.py's sex mode and _run_sex_pass, and return {'status':'busy'} when it is held. Claim rows in small committed chunks before calling.

### F-14 — Per-photo weather lookups sit on the ingest path with a 20 s timeout and no memory of failures, and 'unavailable' weather is kept forever

*low · confirmed · perf · effort S* — `backend/app/enrichment/weather.py`, `backend/app/enrichment/enrich.py`, `backend/app/ingestion/sync.py`

- **What the hunter sees:** When Open-Meteo is slow, a 100-photo sync can hold every new photo back for many minutes, and the 'Check for new photos' line stays on 'Still checking…'. The weather attached to those photos stays blank for good.
- **Evidence:** weather.py:48-55 uses httpx.get(..., timeout=20) and deliberately does not cache failures. enrich_image runs for every new photo inside the sync transaction (sync.py:128-131), and SPYPOINT commits only at the end of _run (sync.py:224). enrich.py:30-36 returns any existing snapshot, including source='unavailable' with all fields NULL, and nothing backfills it. Proven (scratch pytest): 10 photos from one camera-night made 10 Open-Meteo calls while the host timed out. After the provider recovered, enrich_image still returned source='unavailable', temp_c=None. EnvSnapshot is only read by forecasting/diagnostics.py.
- **Verifier:** weather.py:48-55 makes one httpx.get per uncached day with timeout=20 and deliberately does not cache failures. enrich_image runs per photo inside the SPYPOINT transaction, which commits at the end of _run (sync.py:128-131,224). enrich.py:30-36 returns an existing 'unavailable' snapshot forever. Downgraded to low: it needs Open-Meteo to hang rather than fail fast, and EnvSnapshot is only read by forecasting/diagnostics.py.
- **Fix:** Remember a failure for the rest of the run and cut the timeout to ~5 s. Let enrich_image redo a snapshot whose source is 'unavailable'.


## 6. Tonight is fast and honest on weak signal

### A-04 — A days-old plan served by the service worker is labelled 'Plan from just now'; falling back to a saved plan is silent

*high · confirmed · bug · effort S* — `frontend/src/api.ts`, `frontend/public/sw.js`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** In the installed PWA with no signal, a plan from days ago, with that day's wind and moon, is shown as current. The hunter picks a stand on out-of-date wind advice.
- **Evidence:** When a /api/forecast/tonight fetch fails, sw.js:64-70 returns the cached copy as HTTP 200 with X-GameSense-Stale and X-GameSense-Cached-At headers. api.ts:25-53 never reads headers, so apiCached (api.ts:84-88) treats it as a fresh success: writeCache() restamps localStorage with the current time and returns at=now. PROVEN: pw_sw_stale.cjs (built app with the real service worker, API sockets dropped, cached copy aged 2 days). The page shows 'Plan from just now' with data-stale=false and no alert, and gs_cache:/forecast/tonight.at is rewritten to now. Without a service worker, the localStorage fallback (api.ts:89-92) also resolves as success, so the 'Could not refresh… Try again' banner (Tonight.tsx:175) is practically never shown. The staleness rule is a flat 12 h (Tonight.tsx:169), so last night's plan opened at 09:00 is not flagged.
- **Verifier:** Reproduced with the real built SW (my own build and run). A cached copy aged 2 days renders 'Plan from just now', data-stale=false, with no alert, and gs_cache .at is restamped to now. sw.js:64-70 returns the stale hit as 200. api() never reads headers (api.ts:25-53), and apiCached calls writeCache with a fresh time (api.ts:86-88). Without the SW, the localStorage fallback keeps its true age, so that path is only affected by the flat 12 h rule (Tonight.tsx:169).
- **Fix:** api() only returns the JSON body, so give apiCached its own fetch path (or an api variant that returns the Response). When X-GameSense-Stale is set, return {data, at: X-GameSense-Cached-At, stale: true}, skip writeCache, and show the 'Could not refresh' banner. Base staleness on the evening boundary (made before 06:00-local cutover of the current night), not on 12 h.

### A-05 — Tonight waits on the network with no timeout and never shows the saved plan first; the spinner can run for minutes

*high · confirmed · ux · effort S* — `frontend/src/pages/Tonight.tsx`, `frontend/src/api.ts`, `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** At the top of the track with one bar of signal, Tonight spins indefinitely although a good plan is on the phone. Stands can sit on 'Loading stands…' or show frozen buttons.
- **Evidence:** The comment at Tonight.tsx:114-116 says 'Paint from the last good plan first; refresh underneath'. The code does not: apiCached (api.ts:84-94) waits for the network and reads the cache only after fetch rejects. fetch in api.ts:31 has no AbortController or timeout. PROVEN: Playwright T1. With a cached plan in localStorage and a /api/forecast/tonight request that never answers, the page still shows only 'Working out tonight…' after 8 s and the cached plan never appears. Stands has the same pattern: Stands.tsx:48 waits for flushSitQueue() before starting load(), and a hung POST in run() (55-61) leaves every button disabled on 'Reserving…'.
- **Verifier:** Reproduced (T1): with a cached plan in localStorage and a hanging /forecast/tonight request, the page still shows only 'Working out tonight…' after 8 s. apiCached waits for the network before reading the cache (api.ts:84-94), contrary to the comment at Tonight.tsx:114-115, and fetch has no timeout (api.ts:31). Stands chains load() after flushSitQueue() (Stands.tsx:48); this only blocks when the queue has items, because an empty queue resolves at once.
- **Fix:** The proposed fix is right. Show the cached copy with its real age (not 'just now'), and let the network result replace it. Map an AbortError to a plain 'No signal' message.

### D-02 — Offline, a days-old plan from the service worker is labelled 'Plan from just now'

*high · confirmed · data-correctness · effort S* — `frontend/public/sw.js`, `frontend/src/api.ts`

- **What the hunter sees:** At a stand with no signal the hunter is shown last week's verdict as if it were computed just now. This is the exact case the age label was built for.
- **Evidence:** When the network fails, sw.js:64-69 replays the cached /api/forecast/tonight with status 200 and an X-GameSense-Stale header. api.ts never reads headers, so api() resolves normally. apiCached (api.ts:86-88) then writes the old body back to localStorage stamped at:new Date() and returns it as fresh, and the 'Could not refresh' banner never shows. PROVEN (scratchpad/D/pw/offline.cjs, real dist, SW active). The test loaded the plan online, moved the page clock 3 days ahead, cut the server and reloaded. Result: 'offline+3d: Plan from just now', 'refresh-failed banner shown: false'. Without the SW replay, apiCached's catch branch would have returned the localStorage copy with its real age and the '… may be out of date' warning. /api/alerts and /api/sits replays are unlabelled in the same way.
- **Verifier:** Reproduced with the SW active: after going offline and moving the clock 3 days on, the page still showed 'Plan from just now'. sw.js:64-69 replays the cached body as a 200, and api.ts never reads X-GameSense-Stale/Cached-At. apiCached (api.ts:86-88) then re-stamps it with now. One side claim is wrong: the 'Could not refresh' banner never appears in either path, because apiCached's catch returns the localStorage hit without rejecting, so Tonight.tsx:121 setErr is never reached.
- **Fix:** In api(), read X-GameSense-Stale and X-GameSense-Cached-At and return them with the data. apiCached should return {data, at: cachedAt, stale: true} and skip writeCache for replayed bodies. The localStorage fallback in apiCached's catch should also return stale: true. Tonight should show the 'Could not refresh. Showing the last plan.' banner whenever stale is true, not only on rejection.

### D-03 — The saved plan is not painted first: on weak signal Tonight sits on 'Working out tonight…' for as long as the request hangs

*high · confirmed · ux · effort S* — `frontend/src/api.ts`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** With one bar of signal at dusk the hunter stares at a spinner instead of the plan that was already on the phone. That is the single most important screen in the app.
- **Evidence:** api.ts:70-77 and Tonight.tsx:115 both say the page paints the last good plan immediately and refreshes underneath. apiCached (api.ts:84-94) actually awaits the network first and reads the cache only in the catch. api() (api.ts:31) also has no timeout or AbortController, so a stalled link keeps the spinner until the browser gives up, which can take minutes. PROVEN (scratchpad/D/pw/cache_first.cjs). With a 40-minute-old plan in localStorage and the forecast request delayed 10 s, the screen still said 'Working out tonight…' 2.5 s after opening. The saved plan first appeared after 10.4 s, and it was labelled 'Plan from just now', which is wrong as well.
- **Verifier:** Reproduced: with a 40-minute-old plan in localStorage and the forecast delayed 10 s, the screen still said 'Working out tonight…' at 2.5 s. apiCached (api.ts:84-94) awaits the network first and reads the cache only in its catch, and api() has no timeout. One sub-claim is wrong: what appeared at ~10.5 s was the fresh network response, not the saved plan, so 'Plan from just now' was correct there.
- **Fix:** Make it stale-while-revalidate: Tonight calls readCache() synchronously and setF/setPlanAt before the network call, then replaces them when the fetch resolves. Put an AbortController timeout on GET revalidation only. Once the cached plan is painted first, the timeout can be generous (about 15 s) so a slow but valid forecast isn't aborted. Don't apply it to writes.

### I-05 — Installed app offline shows yesterday's plan as 'Plan from just now'

*high · confirmed · data-correctness · effort S* — `frontend/public/sw.js`, `frontend/src/api.ts`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** In the valley with no signal, the installed app presents an old verdict and old wind as current. The app's own promise is never to imply stale data is current.
- **Evidence:** When offline, sw.js:64-70 replays the cached /api/forecast/tonight with status 200 and headers X-GameSense-Stale / X-GameSense-Cached-At. api() (api.ts:25-53) ignores those headers. apiCached (84-94) treats the response as fresh, rewrites localStorage and stamps at = now. Proven on the production build (served on :8013) with I/f_swstale.cjs: load Tonight online, fast-forward the clock 14 h, go offline, refocus. With serviceWorkers=block the page says 'Plan from 14 h ago, may be out of date'. With the service worker active (installed PWA) it says 'Plan from just now'. Screenshots: shots/offline_14h_sw_allow.png, shots/offline_14h_sw_block.png.
- **Verifier:** Deterministic. Offline, sw.js:64-70 answers the cached /api/forecast/tonight with status 200 plus X-GameSense-Stale. Nothing in src reads those headers (grep finds 0 hits). apiCached (api.ts:84-88) then rewrites localStorage and returns at=now, so Tonight shows 'Plan from just now' (Tonight.tsx:202-205) and never shows the 'Could not refresh' banner.
- **Fix:** Add an api variant that returns response headers. When X-GameSense-Stale is present, return {data, at: X-GameSense-Cached-At}, do not writeCache, and let Tonight show 'No signal. Plan from N h ago.' The simpler option is for the service worker to return 503 for API calls when offline and let the existing localStorage fallback label the age.

### J-05 — Offline, the installed app shows an old plan as 'Plan from just now'

*high · confirmed · ux · effort S* — `frontend/public/sw.js`, `frontend/src/api.ts`, `frontend/src/pages/Tonight.tsx`, `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** In the valley with no signal, the exact case the freshness chip exists for, a hunter acts on yesterday's verdict and wind believing they are current.
- **Evidence:** When /api/forecast/tonight fails, sw.js:64-70 answers with the cached body as HTTP 200 plus X-GameSense-Stale and X-GameSense-Cached-At headers. api.ts:116-123 never reads headers, so apiCached (api.ts:155-159) treats the answer as fresh: it returns at=now and re-stamps the localStorage copy. PROVEN with Playwright (built app, stub API, SW registered, then the server dropping connections). With the SW the chip read 'Plan from just now'. The same state with the SW blocked read 'Plan from 20 h ago, may be out of date'. The localStorage timestamp was re-stamped to now. The SW replays /api/sits and /api/stands the same way (sw.js:23), and Stands shows no age at all, so yesterday's reservations can appear as tonight's. Every existing UI test runs with serviceWorkers:'block' (frontend/tests/ux-smoke.cjs:11), so this path was never exercised.
- **Verifier:** sw.js:64-69 answers a failed fetch with the cached body as HTTP 200 plus X-GameSense-Stale. api.ts:31-52 never looks at headers, so apiCached (api.ts:84-88) treats it as fresh, re-stamps localStorage with new Date() and returns at=now, and Tonight.tsx:202-205 then shows 'Plan from just now'. /api/sits and /api/stands are replayed the same way (sw.js:23), and Stands shows no age at all.
- **Fix:** Return the headers from api() (or read them in apiCached). When X-GameSense-Stale is set, use X-GameSense-Cached-At as `at` and do not writeCache. Add generated_at to the forecast payload, and give Stands a freshness line, or stop the SW replaying /api/sits across the 06:00 rollover.

### A-15 — Switching species with no signal wipes the whole Tonight page, chips included, and the failed choice sticks

*medium · confirmed · ux · effort S* — `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** With no signal, one chip tap throws away the plan that was on screen and leaves no way back to 'Anything' until signal returns.
- **Evidence:** toggleSpecies calls load(next, true). If it fails and there is no cached copy for that exact query, Tonight.tsx:125 sets f to null, and the early return at Tonight.tsx:157 replaces the whole page, chip row included, with 'Could not load tonight's plan'. The new choice is already saved (145), and 'Try again' reloads with it. PROVEN: Playwright T2. The first plan loads; tapping 'Red deer' with the request failing shows the alert with 0 chips left. After Try again there are still 0 chips, and the saved filter stays ['red_deer'], so an offline reload hits the same wall even though an 'Anything' plan is cached.
- **Verifier:** Reproduced (T2): tapping 'Red deer' with the request failing shows 'Could not load tonight's plan' with 0 chips. Try again still shows 0 chips, and gs_species_filter stays ['red_deer']. Cause: `if (settle) setF(null)` (Tonight.tsx:125), then the early return at :157. The choice is saved before the request succeeds (:145).
- **Fix:** The proposed fix is right. Keep the previous f and revert picked and localStorage on failure, instead of setF(null).

### A-18 — The Stands page and Start sit don't work offline, although Sit mode is designed for no signal

*medium · confirmed · reliability · effort S* — `frontend/src/pages/Stands.tsx`, `frontend/public/sw.js`

- **What the hunter sees:** At the stand with no signal, the hunter can't open the list or start Sit mode. The offline Sit mode is reachable only if the sit was started while there was signal.
- **Evidence:** Stands.load() (Stands.tsx:43) needs /stands, /sits and /auth/me together in one Promise.all. The service worker caches /api/stands and /api/sits but not /api/auth/me (sw.js:23), and the page uses api() rather than apiCached. 'Start sit' (Stands.tsx:98) needs POST /sits/{id}/start to succeed before it opens Sit mode, even though Sit mode itself queues reports offline. PROVEN: Playwright S5. /stands and /sits answer, /auth/me fails, and the page shows 'Couldn't load stands. Failed to fetch' with no stands.
- **Verifier:** Reproduced (S5): with /stands and /sits answering and /auth/me failing, Stands shows 'Couldn't load stands. Failed to fetch' and no stands. It uses a single Promise.all (Stands.tsx:43), and /api/auth/me is not in CACHEABLE_API (sw.js:23). 'Start sit' awaits POST /start before navigating (Stands.tsx:98 via run()).
- **Fix:** The proposed fix is right. Load `me` independently, from a cached copy stored at login, so its failure cannot blank the list.

### D-09 — On a slow link the fully cached app shows a blank screen for three times the network latency

*medium · confirmed · perf · effort S* — `frontend/public/sw.js`

- **What the hunter sees:** Opening the installed app at the stand on one bar shows a black screen for half a minute or more, which reads as 'the app is broken'.
- **Evidence:** sw.js:89-103 is strictly network-first, with no timeout, for navigations and for hashed immutable /assets. So when the link is slow rather than dead, index.html, then each JS/CSS file, then the API each wait on the network in sequence, even though every byte is already cached. PROVEN (scratchpad/D/pw/weak_signal.cjs). With everything in the SW cache and a proxy adding 12 s latency, the plan became visible after 36.4 s. Until then the screen stays blank.
- **Verifier:** Reproduced: with the app fully cached and a 12 s latency proxy, the plan appeared after 36.4 s. sw.js:89-103 is network-first with no timeout for navigations and for content-hashed /assets, so the document, then the JS/CSS, then the API each wait on the network in turn, even though every byte is already cached.
- **Fix:** Serve /assets/* cache-first; the names are content-hashed, so this is safe. For navigations, use stale-while-revalidate: serve the cached /index.html at once and refresh it in the background, rather than a 3 s race. Pair it with the D-18 version check so a cache-first shell doesn't pin old builds.

### G-19 — Species-chip taps refetch the heavy /analytics/overview (about 600 ms of DB work) although it does not depend on the chip

*medium · confirmed · perf · effort S* — `backend/app/api/routes_analytics.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** Every chip tap costs about 1.1 s of server time on a desktop-class DB (more on the estate box) and slows the verdict refresh the hunter is waiting for, often on weak signal.
- **Evidence:** routes_analytics.py:256, :265 and :269-275 each evaluate the VISIBLE_ANIMAL EXISTS predicate over all images. Measured (G/test_g_perf.py, test_g_perf2.py, 71k images): overview 603 ms, of which the sightings count takes 290 ms and by_camera 234 ms. Tonight.tsx:128-133 refetches /analytics/overview, /alerts and /species on every toggleSpecies/pickAll call (load(next, true)), and none of the three depends on the selected species.
- **Verifier:** Tonight.tsx:109-135: every toggleSpecies/pickAll calls load(), which refetches /analytics/overview, /alerts and /species, and none of them depend on the selected species. Re-running G/test_g_perf.py gives overview 569 ms and alerts 248 ms on 71k images. routes_analytics.py:42, :51 and :55-61 each re-evaluate the VISIBLE_ANIMAL EXISTS predicate over all images.
- **Fix:** Split load(): chip changes refetch only /forecast/tonight. In overview, compute sightings, by_hour and by_camera from one grouped scan (GROUP BY camera_id, local hour over the VISIBLE_ANIMAL images) and sum in Python.

### I-07 — A saved animal pick that is no longer offered empties Tonight and Photos with nothing selected

*medium · confirmed · bug · effort S* — `frontend/src/pages/Tonight.tsx`, `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** The main decision card says there is nothing to go on, and nothing on screen explains why or offers a fix.
- **Evidence:** Tonight keeps gs_species_filter (Tonight.tsx:101-107) and always sends it (line 112). The chips only list huntable species with detections (line 133), so a stale id is sent but never shown. Proven with I/f_tonight.cjs: localStorage gs_species_filter=['fox']; admin turns Fox out of the advice. Tonight then shows 'Not enough to say. No camera has seen the animals you picked yet.' with no chip pressed, 'Anything' not pressed either, and Fox has hundreds of sightings. Screenshot: shots/tonight_stale_species_pick.png. Photos has the same problem (readPick, Photos.tsx:33-40), proven with I/f_photopick.cjs: pick ['lagomorph'] after Rabbit was hidden gives 'Nothing for that choice yet. Try fewer chips.', 0 tiles, no chip pressed (shots/photos_stale_hidden_pick.png).
- **Verifier:** Code is deterministic. Tonight always sends the saved gs_species_filter (Tonight.tsx:101-112), but the chips list only huntable species with detections (133). The backend's huntable filter (model.py:103) then yields NO_DATA with the reason 'No camera has seen the animals you picked yet.' (308), and neither 'Anything' nor any chip is pressed. Photos has the same pattern with hidden species excluded by VISIBLE_ANIMAL. Medium rather than high because tapping Anything or Everything, which is still visible, recovers.
- **Fix:** The proposed fix is right. Also drop camera ids missing from /photos/filters, such as inactive cameras.

### I-10 — Stands can't open offline even though the service worker caches stands and sits; errors say 'Failed to fetch'

*medium · confirmed · reliability · effort S* — `frontend/src/pages/Stands.tsx`, `frontend/public/sw.js`, `frontend/src/api.ts`

- **What the hunter sees:** At the stand with no signal, the hunter can't see their reservation or get back to Sit Mode from Stands. The errors are in browser jargon.
- **Evidence:** Stands.tsx:43 wraps /stands, /sits and /auth/me in a single Promise.all. /auth/me is not in CACHEABLE_API (sw.js:23), so offline the whole Promise.all rejects. Proven with I/f_offline.cjs on the production build with the service worker active: every tab visited online, then offline. Stands shows 'Couldn't load stands. Failed to fetch' on tab switch and on a cold start. Screenshots: shots/offline_stands.png, shots/offline_cold_stands.png. Photos ('Could not load photos: Failed to fetch'), Cameras and Map also show the raw browser text. Settings shows 'Loading…' forever for the species list, because Admin.tsx:143 swallows the error.
- **Verifier:** Stands.tsx:43 puts /auth/me in the same Promise.all as /stands and /sits, and /auth/me is not in CACHEABLE_API (sw.js:23). Offline, fetch rejects and the whole list fails with 'Couldn't load stands. Failed to fetch'. Admin.tsx:143 swallows the /species error, so the list stays on 'Loading…' (line 299-300).
- **Fix:** The proposed fix is right. At minimum, make /auth/me its own non-blocking request, since only me.id is needed for 'owned'.

### J-06 — On a weak signal the installed app waits on the network for every file before showing the cached plan

*medium · confirmed · perf · effort S* — `frontend/public/sw.js`

- **What the hunter sees:** At the truck with one bar, the app looks dead for a minute or more.
- **Evidence:** sw.js:89-103 is network-first with no timeout, for navigations and for the content-hashed /assets/*.js files, which never change. apiWithFallback (sw.js:44-64) also awaits fetch() with no timeout. PROVEN with Playwright at 25 s latency per request (a one-bar connection): the verdict appeared after 75.1 s, even though the shell, the JS and the plan were all cached. CACHE='gamesense-v2' is never versioned, so old asset entries pile up.
- **Verifier:** sw.js:89-103 is network-first with no timeout for every non-API GET, including navigations and the content-hashed /assets/*. apiWithFallback (sw.js:44-47) awaits fetch() with no timeout, so on a hanging one-bar link each request waits for the browser's own timeout before falling back. CACHE is fixed at 'gamesense-v2' and activate never prunes it, so old hashed bundles pile up across deploys.
- **Fix:** Serve /assets/* cache-first. Race navigations and cacheable API calls against a ~3 s timer that falls back to the cache and marks the response stale (as in J-05). Put the build hash in the cache name so activate deletes old caches.

### K-08 — Switching tabs throws away what was loaded, and the tab you left keeps downloading on the thin link

*medium · confirmed · perf · effort M* — `frontend/src/api.ts`, `frontend/src/hooks.ts`, `frontend/src/pages/Tonight.tsx`, `frontend/src/pages/Cameras.tsx`, `frontend/src/pages/Stands.tsx`, `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** Flicking between Tonight, Stands and Cameras at the stand shows spinners every time, and coming back to Tonight after Cameras can take several seconds on one bar of signal.
- **Evidence:** Each page keeps its data in component state and restarts from 'Loading…' on every mount (Stands.tsx:78, Cameras.tsx:391, Photos.tsx:180, Tonight.tsx 'Working out tonight…'). There is no in-memory cache across routes and no AbortController anywhere in src (grep). api.ts:120-148 has no timeout, so requests and image strips from the page just left keep running. PROVEN with Playwright against the real API on the QA dataset, CDP-throttled to 600 ms RTT / 60 KB/s (scratchpad/K/pw/tabflick.cjs). Tonight→Stands: 'Loading stands' for 0.9 s. →Tonight: 'Working out tonight…' 0.9 s. →Cameras: 2.8 s. →Tonight again: 'Working out tonight…' for 5.9 s with 17 requests / 268 KB, because Cameras' photo strips were still downloading. A-05/D-03 cover Tonight not painting its saved plan first; this finding is about every tab and the leftover traffic. Server-side, the abandoned requests keep holding DB connections (K-04).
- **Verifier:** I checked the code, not the timings. Every page keeps its data in component state and starts over on mount (Stands.tsx:28, Tonight.tsx 'Working out tonight…'). There is no cache that survives a route change, and grep finds no AbortController or signal in src. api.ts:31 calls fetch with no timeout or abort, so requests from a page you left keep running. Tonight writes a localStorage copy (apiCached) but does not paint from it first. That part is A-05/D-03. The throttled timings were not re-measured.
- **Fix:** Drop the loading='lazy' part: Cameras.tsx:439 already has it. Keep the module-level stale-while-revalidate Map for GETs and the AbortController per effect, and abort Tonight's superseded chip requests. The server side of this is K-04.

### A-16 — A saved species filter for an animal no longer listed hides itself: no chip is selected but the verdict is still filtered

*low · confirmed · bug · effort S* — `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** After the species list changes in Settings, Tonight says nothing has been seen and shows no selected chip. The hunter has to guess to tap 'Anything'.
- **Evidence:** `picked` is read from localStorage (Tonight.tsx:101-107) and sent as ?species= (112), but it is never checked against the chip list, which shows only species that are huntable and have detections (133). A species switched off or hidden in Settings stays in the filter invisibly. PROVEN: Playwright T3. With ['roe_deer'] saved and /species offering Wild boar and Red deer, no chip (not even 'Anything') is selected, the request uses ?species=roe_deer, and the verdict reads 'No camera has seen the animals you picked yet.'
- **Verifier:** Reproduced (T3): with ['roe_deer'] saved and not offered, 0 chips are pressed and the request carries ?species=roe_deer. `picked` is never reconciled with the chip list (Tonight.tsx:101-107,133). Downgraded: it needs a Settings change to trigger, and the 'Anything' chip is visible one tap away.
- **Fix:** The proposed fix is right.

### C-27 — A saved chip for a hidden or vanished animal filters the feed invisibly, leaving it empty with nothing highlighted

*low · confirmed · ux · effort S* — `frontend/src/pages/Photos.tsx`, `backend/app/api/routes_photos.py`

- **What the hunter sees:** The Photos page looks empty or broken, and there's no visible chip to turn off.
- **Evidence:** The pick is restored from localStorage (Photos.tsx:33-40, 56-62) and sent as-is (74-75). Chips render only from /photos/filters (157-174), which drops hidden species (routes_photos.py:34) and zero-count ones (47). If a picked species is later hidden in Settings, the feed is filtered by an id with no chip, 'Everything' isn't pressed (135), and the page says 'Nothing for that choice yet. Try fewer chips.' with no chip lit. Proven by code reading.
- **Verifier:** The pick is restored from localStorage (Photos.tsx:33-40, 56-62), while chips come from /photos/filters, which drops hidden and zero-count species (routes_photos.py:34, 47) and inactive cameras (line 41). VISIBLE_ANIMAL in the feed then returns nothing for a hidden-only pick. The impact is milder than claimed: the 'Everything' chip is always rendered and unpressed, and tapping it resets the pick.
- **Fix:** Once filters load, intersect pick with the ids in filters (and save the result). Or render any picked-but-unknown id as a pressed chip labelled 'Hidden animal ✕'.

### I-24 — 'Plan from just now' never ages while Tonight stays on screen

*low · confirmed · ux · effort S* — `frontend/src/pages/Tonight.tsx`, `frontend/src/hooks.ts`

- **What the hunter sees:** A phone left open on Tonight through the evening shows a stale plan as current.
- **Evidence:** The age label is computed only when the component renders (Tonight.tsx:202-206). Refresh only happens on focus or visibility change (line 140). Proven with I/f_agelabel.cjs: clock run forward 3 h with the page visible. Label is still 'Plan from just now' and no new /forecast/tonight request was made.
- **Verifier:** ageLabel(planAt) is computed only at render (Tonight.tsx:202-205). Nothing re-renders it on a timer, and the only refetch is useRefetchOnReturn on focus or visibility (hooks.ts:13-26). A page left visible never ages or refreshes.
- **Fix:** The proposed fix is right: a 60 s tick for the label and a 15-20 min refetch while the page is visible.


## 7. Weather and wind: fresh, and one answer everywhere

### A-09 — The Stands page and Sit mode (and Tonight) use two different wind models and can contradict each other for the same stand

*high · confirmed · data-correctness · effort M* — `frontend/src/pages/Stands.tsx`, `frontend/src/pages/SitMode.tsx`, `backend/app/api/routes_stands.py`, `backend/app/forecasting/model.py`, `backend/app/api/routes_zones.py`

- **What the hunter sees:** Same stand, same minute: the Stands list says 'Wind is right' and the seat screen says 'Wind is wrong' (or 'not set up'). At the moment it matters, the hunter can't tell which to trust.
- **Evidence:** The Stands wind line comes from /map/tonight via bedding.stand_wind_report (routes_zones.py:138-141), which uses drawn bedding areas and thermals. The wind saved on the sit (routes_stands.py:288-307) drives the Sit mode headline (SitMode.tsx:27-33, 174-201); Tonight's wind line (model.py:343-351) likewise uses wind.assess against hand-typed approach arcs. PROVEN: scratch test_stands_and_sit_mode_disagree_on_wind. Stand with bedding 400 m south and approach arc N, wind S 15 km/h. Stands says 'clean — Scent goes N, away from bedding'; the reservation and Sit mode say 'scent_carries — wrong for Puente'. Stands created by the bootstrap have no arcs, so Sit mode shows 'Wind not set up for this stand' while Stands gives advice. Sit mode also shows the reservation-time verdict in the present tense with no time or refresh.
- **Verifier:** Reproduced: for the same stand and wind, /map/tonight says 'clean — Scent goes N, away from bedding' and the saved sit says 'scent_carries'. Stands uses bedding.stand_wind_report with thermals (routes_zones.py:139-142). claim_stand and forecast_tonight use wind.assess on approach arcs (routes_stands.py:270-275; model.py:345-351). Both lines appear together under 'Wind details' on Stands (Stands.tsx:101-104). On calm evenings they also split structurally: bedding gives a katabatic verdict while assess says too_light.
- **Fix:** The proposed fix is right. Sit mode must also show the reservation time next to the saved verdict. Refresh it only from the same stand_wind_report source, or the refresh will reintroduce the split.

### B-03 — Scent check aims at the middle of the bedding and measures to the nearest corner, so it says 'Wind is right' when scent blows straight into the near end or edge

*high · confirmed · data-correctness · effort M* — `backend/app/forecasting/bedding.py`, `backend/app/geo.py`

- **What the hunter sees:** The headline answer is wrong. A hunter picks a stand the app calls clean and blows the bedding it was meant to protect, and the distance in the sentence is off by hundreds of metres.
- **Evidence:** bedding.py:93-102 treats a stand as a hit only if the bearing to the polygon CENTROID is within ±half_deg of the scent bearing. geo.py:323-335 distance_to_polygon_m uses the nearest VERTEX. That is fine only for densely digitised outlines, but the UI draws bedding with a handful of taps. PROVEN in a scratch pytest (scratchpad/B/pyt/test_map_geom.py) with a 1.2 km × 150 m bedding strip drawn as 4 taps. (a) Stand 250 m due south of its west end, wind S 15 km/h (scent due north, straight into the bedding) → status 'clean', text 'Wind S 15 km/h — clean. Scent goes N, away from bedding (255 m to the nearest).' (b) Stand 200 m south of the middle of the long edge: distance reported as 632 m. At 8 km/h the verdict is 'clean', at 9 km/h 'scent_carries … 632 m away'. The cone the map draws for the selected stand (layers.ts windGeometry) visibly overlaps the bedding while the label says clean.
- **Verifier:** I re-ran scratch test_map_geom.py. A 1.2 km x 150 m strip drawn with 4 taps, stand 250 m south of the west end, wind S 15 km/h → 'clean … 255 m to the nearest'. For a stand 200 m south of the middle of the edge, distance_to_polygon_m reports 632 m and the verdict flips between 8 and 9 km/h. The causes are the centroid bearing test (bedding.py:101) and the nearest-vertex distance (geo.py distance_to_polygon_m). The same miss happens with compact polygons when a stand sits off one corner and the cone half-angle (16-28°) is smaller than the angle to the centroid.
- **Fix:** As proposed: test the cone against the polygon's boundary in local metres (vertices plus points sampled along each edge, within range and within ±half_deg), and use true point-to-segment distance. That distance also feeds approach_bearings, routes and the safe_ground near-filter, so all of them improve.

### B-04 — The map mixes tonight's 22:00 forecast with the air movement at the moment you open it, so midday planning gives the opposite scent call; pre-dawn also reads as 'sunny, upslope'

*high · confirmed · data-correctness · effort M* — `backend/app/api/routes_zones.py`, `backend/app/forecasting/thermal.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** The hunter plans at lunch, sees 'Wind is right' under a 'Wind tonight' header, and sits a stand that drains scent straight into bedding at dusk. Morning sitters get an upslope call in the dark.
- **Evidence:** routes_zones.py:130-165,183-185 take the wind from _tonight_conditions (local 22:00, model.py:235-238) but pass when=datetime.now() to stand_wind_report, thermal.regime and safe_ground. PROVEN (test_map_geom.py::test_map_uses_now_not_tonight_for_thermals): calm 22:00 forecast, synthetic hillside falling north, bedding 300 m downhill. At 14:00 local the map says airflow=anabatic and the stand is 'clean' ('air is drawn upslope S … away from bedding'). At 20:30 local the same stand is 'scent_carries … into Barranco 316 m away'. Separately, thermal.py:120 compares `local.time() < sunrise.time()`, which is Madrid wall time against astral's UTC sunrise. At 06:45 local (dark) the map says 'Calm and sunny — air is drawn upslope'. The wrong window is 05:57–07:57 local today; after DST ends on 25 Oct it becomes 06:27–07:27 (sunrise 06:26 UTC). _tonight_conditions after midnight also samples the NEXT evening's 22:00. The Stands page reads the same endpoint.
- **Verifier:** Scratch test output: with the same calm 22:00 forecast, 14:00 local gives anabatic/'clean' and 20:30 local gives katabatic/'scent_carries … Barranco 316 m'. At 06:45 local (dark) it still says anabatic. astral returns UTC (sunrise 05:56 UTC = 07:56 local today; 06:26 UTC = 07:26 local after DST ends), and thermal.py:120 compares naive .time() values. Stands.tsx:41 reads the same endpoint. One small correction: at 14:00 the map's header reads 'Calm and sunny. Air drifting uphill', not 'Wind tonight'.
- **Fix:** Pick one evaluation instant `at` in map_tonight. Use now if it is already after sunset−30 min or before sunrise; otherwise use tonight's sunset+45 min. Pass `at` to stand_wind_report, thermal.regime and safe_ground, and ideally sample the forecast at that same hour. In thermal.py compare aware datetimes: `local < sunrise`. Label the bar with the time it describes.

### F-03 — Tonight/Stands/Zones wind and weather are cached for the whole day in the API process and never refreshed

*high · confirmed · data-correctness · effort S* — `backend/app/enrichment/weather.py`, `backend/app/forecasting/model.py`, `backend/app/api/routes_stands.py`, `backend/app/api/routes_zones.py`

- **What the hunter sees:** At dusk the hunter gets a wind verdict ('wind carries your scent onto the approach, use X') built from whatever forecast was fetched first that day, often 10+ hours old. A wind swing during the day is never reflected, so the stand choice can be wrong.
- **Evidence:** weather.py:37-58: _DAY_CACHE keys on (lat, lng, day, recent, tz) with no TTL and holds the forecast endpoint's response for 'today' too. _tonight_conditions (model.py:228-247) samples 22:00 through weather_at, and its wind feeds the Tonight wind verdict (model.py:345-351), the per-stand verdicts (routes_stands.py:267) and zones (routes_zones.py:130). uvicorn is one long-lived process, and the first request of the local day seeds the cache; Tonight also calls /alerts on load, which runs forecast_tonight. Proven: weather_at for local 22:00 returned wind 90°. After the mocked provider changed to 270°, a second call still returned 90°.
- **Verifier:** _DAY_CACHE (weather.py:37-58) has no TTL. For local 22:00, recent=True always, so the forecast fetched on the first request of the day is served until the process restarts. Reproduced: wind 90° was still returned after the mocked provider switched to 270°, with only 1 HTTP call. The same value feeds Tonight (model.py:228-247), stand check-in (routes_stands.py:267) and the map (routes_zones.py:130).
- **Fix:** Store (fetched_at, hourly). Treat recent=True entries older than ~30-60 min as expired, and keep archive entries indefinitely. If the refresh fails, serve the stale entry rather than {}, so the wind verdict does not vanish when the network drops at dusk.

### G-07 — Map and Stands say 'Calm and sunny, air moving upslope' before dawn: sunrise compared in UTC

*high · confirmed · bug · effort S* — `backend/app/forecasting/thermal.py`, `backend/app/api/routes_zones.py`

- **What the hunter sees:** On a calm dawn sit, the stand's scent verdict and safe-ground shading point the scent the wrong way, downslope versus upslope, with 'sunny' wording in the dark.
- **Evidence:** thermal.py:106 calls solar(..., when.date()) with a UTC date. astral returns UTC-aware datetimes. thermal.py:120 then compares local.time() (Madrid) with sunrise.time() (UTC clock). Between UTC-sunrise-as-clock and the real local sunrise (about 2h in summer time, 1h in winter) the regime falls through to 'anabatic'. PROVEN (G/test_g_proofs2.py::test_thermal_predawn_reads_as_sunny_upslope): at 06:45 Madrid on 26 Sep (sunrise 07:57), regime() returns source 'anabatic' with text 'Calm and sunny, so air is moving up the slope toward the W...'. At 07:30 on 10 Nov (sunrise 07:43) it is also anabatic. /map/tonight (routes_zones.py:141-186) feeds this into every stand verdict and the safe-ground shading. Related: map_tonight passes when=now, so planning at 15:00 for tonight's sit also shows the daytime upslope direction, which is the opposite of the after-dark drainage.
- **Verifier:** thermal.py:106 calls solar() with the UTC date, and :120 compares local.time() (Madrid) with sunrise.time() (UTC clock). My run of regime() on 26 Sep, calm with a slope, returns 'anabatic' at 06:45 and 07:45 local (sunrise 07:57). It also returns 'anabatic' at 15:45, because /map/tonight (routes_zones.py:136-185) evaluates the regime at now rather than at the sit time. So afternoon planning for a calm evening shows upslope scent verdicts and shading on Map and Stands, the reverse of the after-dark drainage.
- **Fix:** Take the night key nk = (local - 6h).date() and s = solar(nk). Set draining = local >= s.sunset - 30min or local < solar(nk+1).sunrise, comparing aware datetimes. Compute 'settled' against s.sunset so a 01:00 regime is not labelled 'still settling around dusk'. For /map/tonight, safe_ground and stand_wind_report, pass when = max(now, sunset+45min) (or the best-window start) instead of now.

### G-08 — Tonight's wind forecast is fetched once per day and never refreshed

*high · confirmed · reliability · effort S* — `backend/app/enrichment/weather.py`, `backend/app/forecasting/model.py`, `backend/app/api/routes_zones.py`

- **What the hunter sees:** The Tonight wind line ('clean for X' / 'scent blows into the approach'), the Map arrows and the stand verdicts can come from a forecast made up to ~22 hours earlier. That is stale advice shown as current on the single most decisive variable.
- **Evidence:** model.py:235-238 asks weather_at for local 22:00. weather.py:40-58 caches the hourly forecast by (lat, lng, day, recent, tz) in a process-global dict with no TTL, cleared only above 8192 entries. The first request of the local day, often just after midnight, pins that day's 22:00 wind for the life of the API process (the native build runs one long-lived uvicorn). PROVEN (G/test_g_proofs2.py::test_weather_day_cache_never_refreshes): the second weather_at call for the same evening returns the first response's wind (0 deg, N) after the upstream value changed to 180 (S), and httpx is called once.
- **Verifier:** weather.py:191-213 caches hourly data by (lat, lng, day, recent, tz) in a process-global dict with no TTL; for a future 22:00, recent is always True (negative .days). The native build runs one long-lived uvicorn. Re-ran G/test_g_proofs2.py::test_weather_day_cache_never_refreshes: httpx is called once, and the second call returns the stale wind (0 degrees) after the upstream value changed to 180.
- **Fix:** Store (fetched_at, hourly) and expire forecast-endpoint entries after ~60 min. Keep archive entries indefinitely. On a failed refresh, fall back to the stale entry rather than to 'unavailable'. Optionally return fetched_at in conditions so Tonight can show the forecast's age.

### J-04 — Three different wind verdicts for the same stand on the same evening

*high · confirmed · data-correctness · effort M* — `backend/app/forecasting/model.py`, `backend/app/api/routes_stands.py`, `backend/app/api/routes_zones.py`, `backend/app/forecasting/bedding.py`, `frontend/src/pages/Map.tsx`, `frontend/src/pages/SitMode.tsx`

- **What the hunter sees:** The most decisive field variable contradicts itself from screen to screen. The Tonight card never gives wind advice, and the stand-conflict safety check is inert.
- **Evidence:** Tonight runs wind.assess against Stand.approach_dirs_deg of the stand linked to the top camera (model.py:343-351). The claim stores that same model's text, which Sit Mode displays (routes_stands.py:264-283). Stands and Map use bedding.stand_wind_report instead (routes_zones.py:142). Approach and shooting arcs cannot be entered anywhere in the UI: the frontend never mentions approach_dirs or shooting_dirs, Map.tsx:158 posts only name/lat/lon, and /stands/{id}/suggested-arcs is never called. PROVEN by a scratch test with a map-placed stand, bedding 300 m north and a S 15 km/h wind. Tonight says 'Wind S 15 km/h. PL19 has no approach directions set, so judge the wind yourself.', naming a camera as if it were a stand. Stands/Map say 'Wind S 15 km/h — your scent runs N into Umbria, 260 m away' under 'Wind is wrong'. Sit Mode says 'Wind not set up for this stand'. The shooting-arc safety check (routes_stands.py:252-261) can never fire.
- **Verifier:** Tonight and the claim use wind.assess with Stand.approach_dirs_deg (model.py:343-351, routes_stands.py:264-283), while Stands and Map use bedding.stand_wind_report (routes_zones.py:142). The only stand write in the frontend is Map.tsx:158, which sends name/lat/lon only, so camera_id, approach_dirs and shooting_dirs are never set. As a result Tonight names the camera as the stand, Sit Mode says 'not set up', and shooting_arcs_conflict (routes_stands.py:252-261) can never fire.
- **Fix:** As proposed, but Tonight must first map the top camera to a stand by nearest position, because Map-placed stands never have camera_id. Add no_bedding/no_position to SitMode's WIND_HEAD. For safety, shooting-arc entry matters more than approach-arc confirmation, since stand_wind_report never reads approach_dirs.

### A-10 — Tonight's weather cache never refreshes during the day, and a failed weather fetch blocks every request for 20 s

*medium · confirmed · perf · effort S* — `backend/app/enrichment/weather.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** Tonight's wind direction, which decides the scent verdict, can come from a forecast fetched just after midnight (about 20 h old by evening) and never updates until the server restarts. When Open-Meteo or the estate internet link is down, every Tonight load, chip tap, map view and reservation waits about 20 s, twice per Tonight load (forecast plus alerts).
- **Evidence:** In weather.py:37-58 the _DAY_CACHE key is (lat, lng, day, recent, tz) with no time. The first successful fetch for a date is served for the life of the process; it is only cleared past 8192 entries. Failures are not cached (54-55), and each one costs up to timeout=20 inside the request. _tonight_conditions runs synchronously in /forecast/tonight, /alerts (via the forecast), /map/tonight and POST /sits. PROVEN with a Python snippet: two weather_at calls for the same date after the upstream wind changed (90° to 270°) both return 90°, with 1 upstream call. With a failing upstream, 3 requests make 3 upstream attempts.
- **Verifier:** Reproduced with a stubbed upstream: two weather_at calls for tonight's 22:00 return 90° after the upstream changed to 270°, from 1 upstream call. _DAY_CACHE is keyed without a time and only cleared past 8192 entries (weather.py:40-58). Three calls against a failing upstream make 3 attempts with timeout=20. /forecast/tonight and /alerts each run _tonight_conditions (alerts.py:44), so a Tonight load pays this twice.
- **Fix:** The proposed fix is right. Keep long-lived caching for archive (recent=False) entries, which is correct for photo backfill, and apply the TTL only to recent=True entries. Use a short timeout on the request path, not the backfill path.

### A-11 — After local midnight, 'tonight' conditions use the next evening's weather and the UTC date for the sun

*medium · confirmed · bug · effort S* — `backend/app/forecasting/model.py`, `backend/app/api/routes_stands.py`

- **What the hunter sees:** A hunter checking Tonight from the seat at 00:30, or reserving after midnight, gets tomorrow evening's wind. The reservation's saved wind verdict then belongs to the wrong night, and moon and darkness describe a different night than the wind.
- **Evidence:** _tonight_conditions (model.py:228-238) builds local_22 from the local calendar date. From 00:00 local it therefore samples 22:00 of the NEXT evening, while solar() uses now.date() in UTC (model.py:230). routes_stands.tonight() uses a 06:00 cutover for the same idea. PROVEN with a Python snippet: now=2026-09-26T22:30Z (00:30 local on 27 Sep) samples weather for 2026-09-27 22:00 and the sun for 2026-09-26. The DST night (25 Oct) is otherwise handled correctly.
- **Verifier:** Reproduced. At 00:30 local on 27 Sep it samples weather for 2026-09-27 22:00 (the next evening) and the sun for 2026-09-26. At 03:30 local both use the 27th. model.py:230 uses now.date() in UTC, and :235 replaces the hour on today's local date. routes_stands.tonight() uses the 06:00 shift (routes_stands.py:30-34), so a claim made after midnight stores the next evening's wind verdict on the current night's sit.
- **Fix:** The proposed fix is right. Put an `evening_date(now)` helper in one place and use it in model.py, routes_stands.py and changes.py. Build local_22 as datetime.combine(evening, time(22), tzinfo=Madrid) so DST is handled.

### B-05 — No wind forecast shows as a calm evening with cold air sliding downhill in the map's wind bar

*medium · confirmed · data-correctness · effort S* — `backend/app/api/routes_zones.py`, `backend/app/forecasting/thermal.py`, `frontend/src/pages/Map.tsx`

- **What the hunter sees:** The biggest line on the map tells the hunter it is a calm drainage night when the app actually has no forecast (it could be blowing 30 km/h). It also contradicts every stand below it.
- **Evidence:** When Open-Meteo fails, _tonight_conditions returns wind None (routes_zones.py:129-135). thermal.regime (thermal.py:69-80) only skips the slope logic when speed >= 8. For None it falls through to katabatic/anabatic. PROVEN (scratchpad/B/pyt/test_map_nodata.py): forecast missing, terrain loaded, 20:30 local → airflow {source:'katabatic', wind_dir_deg:180, text:'Forecast is calm, so the slope decides. Cold air runs downhill to the N…'}, while the stand says 'no_wind_data' and safe_ground says 'no_wind_data'. Map.tsx:180-193 then shows 'Calm evening. Cold air sliding downhill / From the south / Scent goes north / 4 km/h'.
- **Verifier:** I re-ran scratch test_map_nodata.py. With no forecast, airflow comes back {source:'katabatic', wind_dir_deg:180, 'Cold air runs downhill to the N…'}, while stands and safe_ground say no_wind_data. thermal.regime (thermal.py:69) skips the slope logic only when speed is not None and ≥8. Downgraded from high: it needs an Open-Meteo failure plus loaded terrain, and every per-stand verdict and the safe-ground layer still correctly say there is no data.
- **Fix:** As proposed: in thermal.regime, return source 'unknown' with 'No wind forecast tonight.' when wind_speed_kmh or wind_dir_deg is None, and have Map.tsx show 'No wind forecast' when data.conditions.wind_speed_kmh == null.

### B-14 — The scent-safe shading uses a different scent spread than the stand calls, so the two can disagree about the same spot

*medium · confirmed · data-correctness · effort S* — `backend/app/forecasting/bedding.py`

- **What the hunter sees:** The 'Scent-safe ground' layer can shade a spot as safe where a stand placed there is called 'Wind is wrong', or the reverse.
- **Evidence:** bedding.py:308-310 computes `geom` ('Same plume shape the stand verdicts use…'), but :334 calls scent_hits_zone(lat, lon, z, cell_bearing) with the DEFAULT max_range=800 m and half_deg=22.5°. Stand verdicts use geom (range 350-1100 m, half 16-45°). PROVEN (test_map_geom.py::test_safe_ground_uses_different_cone_than_stands): at 25 km/h, 20 of 660 shaded cells disagree with stand_wind_report run at the same coordinates. On calm drainage nights the gap is larger (half 32-40° vs 22.5°, range ~360-620 m vs 800 m).
- **Verifier:** bedding.py:334 calls scent_hits_zone with the defaults (800 m, 22.5° from SCENT_CONE_DEG=45) although :310 computes geom 'so the shading and the markers can never tell different stories'. The scratch test shows 20 of 660 cells disagreeing with stand_wind_report at 25 km/h. The layer is off by default, which limits the impact.
- **Fix:** As proposed: pass max_range=geom['range_m'], half_deg=geom['half_deg']. For drainage cells, compute geom from each cell's own slope speed and confidence.

### B-15 — The map's wind forecast is fetched once a day and never refreshed, so dusk shows the morning's forecast

*medium · confirmed · data-correctness · effort S* — `backend/app/enrichment/weather.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** 'Wind tonight' and every stand call can come from a forecast that is 12+ hours old and shown as current, which matters when a front arrives in the afternoon.
- **Evidence:** weather.py:37-60 _DAY_CACHE keys on (lat,lng,day,recent,tz) with no TTL. _tonight_conditions (model.py:238) reads through it on every /map/tonight. PROVEN (test_map_sync.py::test_weather_day_cache_never_refreshes): the first fetch returns 5 km/h; after the upstream forecast changes to 25 km/h, the second call still returns 5.0 with 1 HTTP call. Failures are not cached, so a hanging Open-Meteo also makes every map load wait for the 20 s timeout.
- **Verifier:** weather.py:40-58 caches by (lat,lng,day,recent,tz) with no TTL (cleared only above 8192 entries). The scratch test returns 5.0 again after the upstream changes to 25, with 1 HTTP call. This also affects the Tonight page, which reads the same _tonight_conditions. Failures are not cached, so each call can wait the full 20 s timeout.
- **Fix:** As proposed: store fetched_at and expire forecast entries after about 60 min (archive entries can stay). Negatively cache failures for about 2 min.

### G-09 — Tonight and Map give different wind advice for the same stand

*medium · confirmed · ux · effort S* — `backend/app/forecasting/model.py`, `backend/app/forecasting/bedding.py`

- **What the hunter sees:** Two screens contradict each other about the same stand and the same evening. The hunter cannot tell which one to trust.
- **Evidence:** model.py:343-351 uses wind.assess() with the stand's hand-entered approach_dirs_deg and synoptic wind only. /map/tonight and Stands use bedding.stand_wind_report() (bedding.py:130-254), which derives approaches from drawn bedding and switches to thermal drainage on calm evenings. PROVEN (G/test_g_proofs5.py): with bedding drawn 300 m east of 'High seat', no arcs, and wind W 15 km/h, Tonight shows 'Wind W 15 km/h. High seat has no approach directions set, so judge the wind yourself.' The Map shows 'Wind W 15 km/h — your scent runs E into Oak bedding, 321 m away.' On calm nights Tonight says 'too light to call ... Check at the truck' while Map gives a drainage verdict.
- **Verifier:** model.py:343-351 uses wind.assess() with the stand's hand-entered approach_dirs_deg, while /map/tonight uses bedding.stand_wind_report (bedding.py:130-254), which derives approaches from drawn bedding and falls back to thermal drainage. Re-ran G/test_g_proofs5.py: Tonight says 'no_geometry' while the Map says 'scent_carries' for the same stand and wind. A third caller, the sit claim at routes_stands.py:270, also uses assess(). Stands.tsx:101-103 therefore shows the live stand_wind_report text and the 'When you reserved' assess() text side by side, and they can contradict each other.
- **Fix:** Make one helper that calls stand_wind_report when the stand has a position and bedding is drawn, and otherwise falls back to assess(). Map its status to {status,text,is_advice}. Use it in forecast_tonight AND in the sit claim (routes_stands.py:270), with the same sit-time 'when' as G-07.

### G-10 — After midnight, 'tonight' conditions jump to the next evening

*medium · confirmed · bug · effort S* — `backend/app/forecasting/model.py`, `backend/app/api/routes_zones.py`

- **What the hunter sees:** A mid-sit refresh after midnight shows the wind verdict and map arrows for a different evening.
- **Evidence:** model.py:235-237 uses local_22 = now_local.replace(hour=22). At 00:30 on 27 Sep that is 27 Sep 22:00, 21.5 h ahead (G/test_g_proofs3.py::test_after_midnight_weather_is_for_next_evening). SITTABLE_HOURS includes 00 and 01, so a hunter still sitting at 00:30 who refreshes Tonight, the Map or Stands gets tomorrow evening's wind. Combined with G-08, the 00:30 fetch is also the one cached for the whole next day.
- **Verifier:** model.py:235-237 uses now_local.replace(hour=22), so at 00:30 it samples 22:00 of the new calendar day, 21.5 h ahead (G/test_g_proofs3.py). SITTABLE_HOURS (model.py:40) includes 00 and 01. routes_zones.py:130 and routes_stands.py:266 share the same _tonight_conditions. Because of the G-08 cache, that 00:30 fetch also pins the next evening's wind.
- **Fix:** Pick the sample time by night key: if the local hour is before 06:00, sample the current or next whole hour of the night in progress; otherwise sample max(now, 22:00 today). Also compute moon and solar for the night key rather than now.date() (UTC). Share one current_night_key(now) helper with changes.py and scoring.py (G-16).

### I-04 — A slow weather service freezes Tonight, Alerts, Map and Reserve for 20 s on every request

*medium · confirmed · reliability · effort S* — `backend/app/enrichment/weather.py`, `backend/app/forecasting/model.py`, `backend/app/api/routes_stands.py`

- **What the hunter sees:** At dusk, when the uplink or Open-Meteo is struggling, Tonight sits on 'Working out tonight…' and Reserve on 'Reserving…' for 20 s at a time.
- **Evidence:** weather.py:50 uses httpx.get(..., timeout=20), and failures are deliberately not cached (line 54, 'retried later'). So every request retries. _tonight_conditions (model.py:223-241) runs inside /forecast/tonight, /alerts, /map/tonight and POST /sits (routes_stands.py:267). Proven: a second backend on :8012 with HTTPS_PROXY pointed at a local blackhole that accepts connections and never answers. Timings: /forecast/tonight 20.2 s, /alerts 20.1 s, /map/tonight 20.1 s, POST /sits (Reserve) 20.1 s; /stands 0.01 s. It repeats on every load and every species chip tap.
- **Verifier:** Reproduced on :8032 with https_proxy pointed at an accept-and-hang socket: /forecast/tonight took 20.15 s, then 20.10 s again, while /stands took 0.008 s. This comes from httpx timeout=20 with failures never cached (weather.py:50-55), and _tonight_conditions sits on every forecast/map/claim path. Downgraded because it needs Open-Meteo itself to stall; if the server's uplink is down, the Cloudflare tunnel is down too.
- **Fix:** Use httpx.Timeout(5, connect=3). Negative-cache failures for about 10 min. Also note that a successful forecast for 'today' is cached forever in _DAY_CACHE (keyed by day only), so the evening wind is the morning's fetch. Give the forecast entries a ~30-60 min TTL, and have claim_stand read the cache only.

### J-07 — Tonight's wind is fetched once a day and never refreshed

*medium · confirmed · data-correctness · effort S* — `backend/app/enrichment/weather.py`, `backend/app/forecasting/model.py`, `backend/serve.py`

- **What the hunter sees:** Whatever wind the first request of the day fetched (a 07:00 model run, say) is what Tonight, Map and Stands show at 19:00 and what gets stored on the sit, even if the forecast has since swung.
- **Evidence:** weather._DAY_CACHE (weather.py:37-59) is keyed by (lat, lon, day, recent, tz) and never expires. _tonight_conditions (model.py:228-248), /map/tonight and claim_stand all read it inside the single long-lived uvicorn process (serve.py). PROVEN: with the upstream forecast changing from 200° to 20° between two weather_at() calls, both calls returned 200° and only one HTTP request was made.
- **Verifier:** weather.py:40-43 returns any cached (lat, lon, day, recent, tz) entry forever; the only eviction is clear() above 8192 keys. _tonight_conditions, /map/tonight and claim_stand all read it inside the long-lived uvicorn process (serve.py). The API only restarts when update.ps1 deploys, so the first fetch of the day (possibly around 01:00 local) sets the 22:00 wind for the rest of the day.
- **Fix:** Store (fetched_at, hourly) and refetch recent=True entries after about 60 min. Keep archive entries indefinitely. Do not cache failures, as today.

### K-04 — A slow weather service drains the database pool: Photos, Cameras, Stands and even sign-in stall for 19 s, then fail with 500 for everyone

*medium · confirmed · perf · effort M* — `backend/app/core/db.py`, `backend/app/forecasting/model.py`, `backend/app/enrichment/weather.py`, `backend/app/forecasting/alerts.py`, `backend/app/api/routes_stands.py`, `backend/app/api/routes_zones.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** At dusk, when everyone opens Tonight and taps chips, an Open-Meteo slowdown makes the whole app hang and then error, including photos and sign-in, for every hunter.
- **Evidence:** db.py:23 uses SQLAlchemy defaults (pool 5 + overflow 10, 30 s wait). forecast_tonight runs its SQL (model.py:280-303) and then calls weather (model.py:305 -> weather.py:50, timeout=20, failures not cached) while the session still holds its connection. /alerts (alerts.py:42), POST /sits (claim) and /map/tonight follow the same pattern. Tonight fires forecast and alerts on every load and on every chip tap, with no abort. PROVEN with the real API under uvicorn (scratchpad/K/pool_server.py, with httpx.get made to hang 20 s, and pool_client.py). With 16 forecast requests in flight, /cameras, /photos, /auth/me and /stands (50 ms at baseline) each took 19.0 s, and the 16th forecast took 40.6 s. With 30 in flight, all four returned 500 after 30.3 s, and pool_server.log shows 'QueuePool limit' 4 times. A-10 and I-04 found the 20 s stall on forecast routes; the knock-on to every unrelated page is new.
- **Verifier:** The code path holds. get_current_user (deps.py:33) checks out the session's connection. forecast_tonight then calls weather_at (model.py:305, weather.py:50, timeout=20) without releasing it. compute_alerts calls forecast_tonight again (alerts.py:42). A single uvicorn worker (serve.py) shares the default pool of 5+10 with a 30 s wait, and the auditor's log shows 'QueuePool limit of size 5 overflow 10 reached'. Downgraded because a successful fetch is cached for the whole day (_DAY_CACHE), so this only happens while Open-Meteo hangs rather than fails fast, and with 15 or more requests in flight at once.
- **Fix:** The suggested stopgap of calling _tonight_conditions before the first query does not work: the auth dependency has already checked out the connection on that session. Call db.commit() (expire_on_commit=False makes this safe) before the HTTP call, or better, fetch the weather outside the request. Cache failures for about 10 min and use httpx.Timeout(5, connect=3). Optionally raise pool_size/max_overflow to match the threadpool.

### A-22 — Before sunrise, the Stands wind line reverses the scent direction on calm mornings (compares local time with UTC sunrise)

*low · confirmed · bug · effort S* — `backend/app/forecasting/thermal.py`, `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** On a calm dawn sit, in the dark before sunrise, the Stands wind line says scent drifts upslope when it is actually draining downslope. It can call a bad stand 'Wind is right'.
- **Evidence:** thermal.regime (thermal.py:106-122) compares the local wall-clock time with sunrise.time(), but astral returns sunrise in UTC; it also uses when.date() in UTC. So from about 06:00 local until real sunrise it reports 'anabatic' ('Calm and sunny, air moving up the slope'). PROVEN with a Python snippet on a sloped grid: on 27 Sep (sunrise 07:57 local), 05:30 gives katabatic but 06:30 and 07:30 give anabatic. This feeds the Stands wind line through bedding.stand_wind_report, and the Map.
- **Verifier:** Reproduced on a stubbed 10% slope with calm wind: 27 Sep 06:30 and 07:30 local give 'anabatic' although real sunrise is 07:57. On 5 Nov, 07:30 local (sunrise 07:37) is also 'anabatic'. thermal.py:111-113 compares local.time() with astral's UTC sunrise.time() and uses when.date() in UTC. Low because it only affects the pre-dawn window, and at that hour the Stands line is already fed tonight's 22:00 forecast wind rather than the current wind.
- **Fix:** The proposed fix is right. Compute solar() for the local date and compare aware datetimes: draining = local >= sunset-30min or local < sunrise(local date).

### B-07 — When the map fails to load, the wind bar still reads 'Wind tonight: Too light to call'

*low · confirmed · ux · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** A load failure looks like a real calm-wind forecast.
- **Evidence:** Map.tsx:180 derives `from` from `air?.source !== 'unknown'` (true when data is null). Map.tsx:192 prints 'Too light to call' whenever from==null and !loading. PROVEN (s_loadfail.cjs): /map/tonight 503 → wind bar text 'Wind tonight | Too light to call | — | km/h' next to the red error.
- **Verifier:** Reproduced with s_loadfail.cjs: /map/tonight 503 → wind bar 'Wind tonight | Too light to call | — | km/h'. This happens because `air?.source !== 'unknown'` is true when data is null (Map.tsx:180) and the fallback text at :192. Downgraded because the red load-error banner sits directly above it.
- **Fix:** As proposed: when !data && !loading, render 'No wind reading. The map didn’t load.' Use 'Too light to call' only when data exists and a real forecast speed exists.

### B-19 — Stand detail says 'That's the slope air at this seat' right after saying no slope wind could be worked out

*low · confirmed · ux · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** Contradictory copy makes the wind advice feel untrustworthy.
- **Evidence:** Map.tsx:216 shows the slope sentence when `stand.wind.source && stand.wind.source !== 'synoptic'`. too_light reports have source 'unknown'. PROVEN (s_toolight.cjs): the detail reads 'Wind too light to call. | Wind S 5 km/h — too light to call. No terrain map loaded, so the slope wind cannot be worked out. | That’s the slope air at this seat, not the forecast wind above.'
- **Verifier:** too_light reports have source 'unknown' (bedding.py:165), and Map.tsx:216 shows the slope line for any truthy source other than 'synoptic', so the contradictory sentence appears.
- **Fix:** As proposed: show the line only when source is 'katabatic' or 'anabatic'.

### B-20 — Stands more than 2.5 km from the configured estate centre are told the ground is flat

*low · confirmed · data-correctness · effort S* — `backend/app/forecasting/thermal.py`, `backend/app/terrain.py`

- **What the hunter sees:** On calm nights, outlying stands get a wrong reason ('flat'), and a steep barranco looks like a no-advice spot.
- **Evidence:** terrain.py:385-386,428-432 fetch a fixed 5 km box around settings.estate_lat/lon. slope_at returns None outside it (terrain.py:486-491), and thermal.py:88-94 maps None to 'Ground is near flat here. No slope for cold air to run down.' PROVEN (test_map_nodata.py): a point 3 km north → source unknown, that text. At the box edge, slope_at's clamped index halves the slope (i±1 clamps but still divides by 2 cells).
- **Verifier:** fetch_grid uses a fixed BOX_KM=5 around the settings centre (terrain.py:34,76-80). _indices returns None outside it, so slope_at returns None and thermal.py:89-93 says 'Ground is near flat here'. The scratch test confirms this 3 km out. At the edges, _at clamps i±1 yet still divides by 2 cells, which halves the slope.
- **Fix:** As proposed: separate out-of-box copy, size the box from the stand, zone and camera bounds plus a margin, and use a one-sided difference at the edges.


## 8. Best hours follow sunset; sunset and last legal light on screen

### A-08 — Best hours ignore legal shooting light: red deer is recommended for 21:00–00:00, and sunset or last light is never shown

*high · confirmed · bug · effort M* — `backend/app/forecasting/model.py`, `frontend/src/pages/Tonight.tsx`, `frontend/src/pages/SitMode.tsx`

- **What the hunter sees:** With Red deer (or roe or fallow deer) picked, the headline says to sit 21:00-00:00. Spanish regional rules generally allow deer only from 1 h before sunrise to 1 h after sunset; night esperas are a boar-only authorisation. The app points the hunter at hours they cannot legally shoot, and nothing on screen says when light ends.
- **Evidence:** SITTABLE_HOURS is 16:00-01:00 for every species (model.py:40; _best_window 43-53). Nothing in the forecast knows sunset: the conditions (model.py:243-248) carry only darkness_minutes, and neither Tonight nor Sit mode shows sunset or last light. PROVEN: scratch test_deer_best_hours_fall_after_legal_light. Red deer photographed at 21-23 h gives headline BEST_ODDS with 'Best hours 21:00 to 00:00'. Astral puts Alatoz sunset on 26 Sep at 19:56, so the whole window falls after sunset + 1 h (20:56).
- **Verifier:** Reproduced: Red deer photographed at 22-23 h gives BEST_ODDS with best_window 21:00-00:00, while astral puts Alatoz sunset on 26 Sep at 19:56 local. SITTABLE_HOURS is 16-01 for every species (model.py:40), conditions carry no sunset (model.py:243-248), and Tonight never renders the sunset that /analytics/overview already returns. Castilla-La Mancha generally limits hunting to 1 h before sunrise until 1 h after sunset, with night esperas as a boar-specific authorisation. The owner's exact permits still need confirming.
- **Fix:** The proposed fix is right. Compute sunset for the evening date (the 06:00-shift rule), not for now.date() in UTC. Make night-allowed a per-species setting that the owner confirms, defaulting to boar only.

### G-05 — 'Best hours' are summer clock hours: after 25 Oct DST ends the window starts after the animals arrive

*high · confirmed · data-correctness · effort M* — `backend/app/forecasting/model.py`

- **What the hunter sees:** From 25 Oct the Tonight card sends hunters to the stand 1-2 hours after the boar have passed. This happens right in the middle of the season.
- **Evidence:** model.py:135-144 builds the best window from an all-time histogram of local clock hours. Sunset in Alatoz moves from ~21:30 CEST in early August to 18:11 CET on 26 Oct (DST end plus shorter days), but the histogram does not move with it. PROVEN (G/test_g_proofs4.py): boar arrive 45, 70 and 90 min after that night's sunset every night from 1 Aug to 24 Oct. On 26 Oct _camera_forecast returns best_window 20:00-23:00 (share 100%), while tonight's sunset is 18:11 and arrivals are expected 18:56-19:41. The same drift affects Insights 'busiest between ...' (insights.py:65-70).
- **Verifier:** model.py:135-144 builds the best window from an all-time histogram of local clock hours, with no seasonal or DST adjustment. Re-ran G/test_g_proofs4.py: with arrivals tied to sunset, 26 Oct gives best_window starting 20:00, while that night's sunset is 18:11 CET. insights.py:176-188 has the same drift. DST ends on 25 Oct, a month away, and sunset has also moved about 3 h earlier since August.
- **Fix:** Build the histogram on minutes after that night's sunset (sunset for the night key date(local-6h)), weighted toward the last ~30 nights. Convert back using tonight's sunset, and keep the SITTABLE constraint after conversion. At minimum, restrict the histogram to the last ~21 nights so it tracks the season.

### J-08 — 'Best hours' drift away from sunset, and after the 25 Oct clock change they will be 1–2 hours late

*high · confirmed · data-correctness · effort M* — `backend/app/forecasting/model.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** From next month the app tells hunters to be in the seat an hour after the first animals arrive, and to stay two hours after they have gone.
- **Evidence:** model.py:135-144 builds the window from a whole-season histogram of local clock hours, and SITTABLE_HOURS is a fixed 16:00–01:00 (model.py:40). PROVEN with the app's own _best_window and astro.solar for Alatoz, simulating boar arriving 30–150 min after sunset every night from 1 Aug to 24 Oct. The app says 'Best hours 20:00 to 23:00'. On 26 Oct sunset is 18:11, so the same animals arrive 18:41–20:41; on 20 Nov they arrive 18:17–20:17. Because the histogram covers the whole season, the lag lasts for weeks. Tonight shows no sunset time at all (Tonight.tsx:227).
- **Verifier:** Reproduced with the app's own _best_window and astro.solar: boar arriving 30-150 min after each night's sunset from 1 Aug to 24 Oct gives 'Best hours 20:00 to 23:00' (91% share). On 26 Oct sunset is 18:11, so arrivals fall 18:41-20:41 and overlap that window by only 41 min. model.py:135-144 uses an all-time clock-hour histogram, so it catches up only slowly. Tonight shows no sunset (Tonight.tsx:227,254-260).
- **Fix:** As proposed: bin detections by minutes after that date's sunset over the last ~30 watched nights, then convert back using tonight's sunset. inference.dark_exit uses the same clock-hour histogram and needs the same change. Scoring does not use the window (_detected checks the whole night), so persisting it is for audit, not for correctness.

### J-18 — FEATURE: Sunset, last legal light and per-species legal hours on Tonight

*high · confirmed · feature · effort M* — `backend/app/forecasting/model.py`, `backend/app/enrichment/astro.py`, `frontend/src/pages/Tonight.tsx`, `frontend/src/pages/Insights.tsx`

- **What the hunter sees:** A guest can be sent to a 'best hours 21:00–24:00' red-deer sit that is outside legal light. The rule is set by the annual regional order and needs to be stated, not guessed.
- **Evidence:** Why it fits: the redesign's Phase 1 legal-light gate is not built; there is no sunset or legal-hours reference in the Tonight/model path. astro.solar() already returns sunset and civil_twilight_end (astro.py:127-141), and Insights shows 'Last light' for the week (Insights.tsx:151-169) but Tonight does not. In Castilla-La Mancha the 2026-27 general season opens 8 Oct, while boar can be taken all year by aguardo (castillalamancha.es orden de vedas 2026-2027), so legal hours differ by species. Best hours come from a fixed 16:00–01:00 clock range (model.py:40).
- **Verifier:** This is not built, and it is roadmap Phase 1 item 8 (docs/redesign/05:51). _tonight_conditions computes solar() but returns only darkness_minutes (model.py:230,245). Tonight shows no sunset or last light, and Insights.tsx:169 shows civil twilight only for the week view. Best hours come from a fixed 16:00-01:00 range (model.py:40), so a non-boar species can be given a window after legal light.
- **Fix:** As proposed: owner-set, effective-dated offsets per species, clamp the window, show 'Sunset hh:mm · last legal hh:mm', and stamp the rule version on the Forecast. Build it together with J-08, because both change how the window is computed.

### E-14 — After the 25 Oct clock change, Suntek photos may be stamped an hour late, and nothing would notice

*medium · plausible · data-correctness · effort S* — `backend/app/ingestion/ftp_import.py:112-152`, `mail-receiver/receiver.py:264-281`, `mail-receiver/receiver.py:409`

- **What the hunter sees:** A boar at 19:30 would show as 20:30 at that camera all winter. Hour charts, peak windows and 'last seen' shift by an hour with no warning.
- **Evidence:** On the live email path the photos carry no EXIF time. Capture time comes only from the PICT_YYYYMMDD_HHMM filename, read as Europe/Madrid wall time (ftp_import.py:137-148). docs/16 says the camera sets its clock by NTP. If its firmware applies a fixed GMT+2 offset instead of following Madrid daylight saving, every filename is 1 h ahead from 25 Oct. Nothing detects this: received_at comes from the camera-written Date header (receiver.py:264-281), not Gmail's Received: header. plausible() also accepts a capture time up to 24 h after the email was sent, which is physically impossible.
- **Verifier:** The code path is right. Suntek email JPEGs carry no EXIF (docs/16-suntek-email.md:156-159), so capture time comes from the PICT_ filename read as Europe/Madrid (ftp_import.py:137-148). received_at comes from the camera-written Date header (receiver.py:264-281), and plausible() tolerates +24 h. Whether the 2020 firmware follows EU DST or uses a fixed offset cannot be verified before 25 Oct. The ambiguous 02:00–02:59 hour itself is handled: _aware_local rejects it and falls back to the receipt time.
- **Fix:** Capture IMAP INTERNALDATE (the server receipt time, available from the fetch; simpler than parsing Received: headers) into metadata.json. In _timestamp, flag captured_at > server_received_at + 5 min as clock skew with a note and a log line, and tighten plausible() from +1 day to a few minutes after the server receipt. Auto-correct only a whole-hour skew, and check the first photos after 25 Oct 03:00.

### H-17 — Suntek (FTP and email) camera clocks: from 25 Oct every photo may be stamped an hour late, and nothing checks for it

*medium · plausible · data-correctness · effort S* — `.env.ftp.example`, `compose.ftp.yaml`, `backend/app/ingestion/ftp_import.py`

- **What the hunter sees:** All winter, boar and deer at the Suntek camera appear an hour later than reality in the photos, the best-hour patterns and the alerts.
- **Evidence:** FTP_CAMERA_TIMEZONE defaults to Europe/Madrid (.env.ftp.example:7, compose.ftp.yaml:59), and the importer reads EXIF and filename times as wall-clock time in that zone (ftp_import.py:133, 148). Trail cameras usually keep the clock they were set to and do not switch for daylight saving. If the HC801LTE does not, then after 2026-10-25 03:00 CEST it still runs on CEST while Europe/Madrid is CET, so every capture is stored one hour late. The importer already has received_at (ftp_import.py:178-180), and 4G uploads land within minutes, but it never compares capture time with receipt time.
- **Verifier:** The importer reads EXIF and filename times as wall-clock time in FTP_CAMERA_TIMEZONE (ftp_import.py:133,148). The only sanity check is 'not more than 1 day after receipt' (ftp_import.py:116-118), so a camera still on CEST after 25 Oct would store every capture 1 h late with no warning. Whether the HC801LTE adjusts for DST or syncs its clock from the network cannot be verified here. The repeated 02:00-03:00 hour is already handled: _aware_local rejects it and falls back to received_at.
- **Fix:** In _persist_photo, flag skew when captured_at is later than received_at plus about 10 minutes, which is physically impossible. Log ftp.clock_skew and show the camera's median (received_at - captured_at) on the Cameras page. Check the first Suntek photo after 25 Oct.

### A-27 — The Sit mode clock uses the phone's time zone while Tonight's hours are Spain time with no label

*low · plausible · ux · effort S* — `frontend/src/pages/SitMode.tsx`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** A guest whose phone is on UK or Canary time sees the Sit mode clock read 20:00 when Tonight's 'Best hours 21:00' has already started.
- **Evidence:** The Sit mode clock uses toLocaleTimeString(undefined, …) (SitMode.tsx:195), i.e. the phone's time zone. Every hour on Tonight is a Europe/Madrid hour from the server (model.py:32-33) shown without a zone (Tonight.tsx:71-72).
- **Verifier:** The code matches the claim: toLocaleTimeString(undefined, …) at SitMode.tsx:195, and the hours are Madrid hours with no zone label. But a phone physically at the estate sets its time zone automatically from the network, so a mismatch needs the time zone set by hand. The impact is marginal.
- **Fix:** Pass timeZone: 'Europe/Madrid' to the Sit mode clock (one line). Skip the 'Spain time' label unless the owner reports guests with manually set time zones.

### F-21 — Moon phase names are binned off-centre: the full moon night reads 'Waxing Gibbous' and the next three nights read 'Full Moon'

*low · confirmed · bug · effort S* — `backend/app/enrichment/astro.py`, `frontend/src/pages/Insights.tsx`

- **What the hunter sees:** Hunters who plan boar nights around the full moon see 'Full Moon' three nights late, and see 'First quarter' at about 80% light.
- **Evidence:** astro.py:24 uses MOON_PHASES[int(frac * 8) % 8], so each name covers the 3.7 days after its exact phase rather than the days centred on it. Proven around the real full moon of 2026-09-26 16:49 UTC: Sat 26 06:49 gives 'Waxing Gibbous' at 99.8%, Tue 29 gives 'Full Moon' at 89.6%, and Wed 30 gives 'Full Moon' at 86.2%. The quarter names are shifted in the same way. The Insights almanac prints this name for each night (Insights.tsx:167).
- **Verifier:** astro.py:24 uses int(frac*8)%8, so each name covers the 3.7 days after its exact phase. Reproduced: 2026-09-26 06:49Z reads 'Waxing Gibbous' at 99.9%, while 2026-09-29 12:00Z reads 'Full Moon' at 90.9%. The name shows in the Insights almanac (Insights.tsx:167) and on Tonight.
- **Fix:** Use MOON_PHASES[int(frac * 8 + 0.5) % 8], as proposed.

### F-22 — On the DST change day (25 Oct), the two passes of the 02:00–03:00 hour get the same weather hour

*low · confirmed · bug · effort S* — `backend/app/enrichment/weather.py`

- **What the hunter sees:** Photos taken around 02:00–03:00 on 25 Oct 2026 (and later hours if the offset is fixed) get the weather for the wrong hour. The effect is small but lands on the date called out as a risk.
- **Evidence:** weather.py:81-93 matches a naive local wall-clock time against Open-Meteo's local 'time' strings. Proven: 2026-10-25 00:30 UTC (02:30 CEST) and 01:30 UTC (02:30 CET) both resolve to index 2. Open-Meteo also sends a single utc_offset_seconds for the whole response, which could shift the post-change hours on that day. That part is unverified because Open-Meteo is blocked from this sandbox.
- **Verifier:** Reproduced: 2026-10-25 00:30Z (02:30 CEST) and 01:30Z (02:30 CET) both resolve to hourly index 2 via naive wall-clock matching (weather.py:81-93). This affects one hour per year.
- **Fix:** Minimal: request timeformat=unixtime (keeping timezone=Europe/Madrid, so the day boundaries stay local) and match on when.timestamp(). Switching to timezone=GMT would also change which calendar day is fetched for late-evening local times.


## 9. Forecast counts nights and ranks cameras correctly

### A-03 — A camera with fewer than 15 nights takes over the Tonight headline as 'Not enough to say' and pushes a proven Best-odds spot down

*high · confirmed · bug · effort S* — `backend/app/forecasting/model.py`

- **What the hunter sees:** For about 15 nights after a camera is added (UBox cameras are being added now), Tonight's headline reads 'Not enough to say · New feeder'. It still shows best hours and species for a spot the app says it can't judge, while the real Best-odds stand is demoted to 'Other places'.
- **Evidence:** model.py:303 and :326 sort all cameras by probability, and model.py:379 uses the verdict of forecasts[0]. _verdict (59-77) returns NO_DATA whenever active_nights < 15, whatever the probability. So a new camera with a few 100% nights gets presence 1.0 (0.97 after the recency bonus) and outranks every other camera. PROVEN: scratch test_new_camera_hijacks_headline_verdict. 'Old ridge' has 40 nights (BEST_ODDS, 0.78); 'New feeder' has 5 of 5 nights. The headline verdict is NO_DATA ('Not enough to say') for New feeder, and Old ridge only appears in the 'where' list.
- **Verifier:** Reproduced: headline NO_DATA for 'New feeder' (0.97, 5 of 5 nights) while 'Old ridge' BEST_ODDS 0.78 only appears in where[]. model.py:303/326 sort by probability only, and :379 takes _verdict of forecasts[0], which returns NO_DATA for active_nights<15 (model.py:71-72). Tonight.tsx:215-230 then shows 'Not enough to say' along with best hours and species for that camera.
- **Fix:** Sort key `(f['active_nights'] >= MIN_NIGHTS_TO_JUDGE, f['probability'])`, descending. Use the same ordering for alternates and where. Headline NO_DATA only when no camera is judgeable.

### G-01 — Forecast counts calendar dates, not nights: 'seen 8 of the last 7 nights' and inflated presence

*high · confirmed · data-correctness · effort S* — `backend/app/forecasting/model.py`

- **What the hunter sees:** The headline verdict and the 'seen X of Y nights' reason overstate how often animals come. The Why line can show an impossible 'seen 8 of the last 7 nights', which makes the whole card look broken.
- **Evidence:** model.py:99 (nights_present), :119 (active_nights), :125 (recent_nights) and :281 (total_nights) all use func.date(timezone(tz, captured_at)), i.e. the calendar date. The rest of the app keys a night by its evening (exposure.night_expr, 18:00->06:00). One boar visit at 23:40 plus another at 00:20 counts as two 'nights'. recent_nights also uses a 7x24h window (captured_at > now-7d), which covers 8 calendar dates. PROVEN (scratch pytest against the test DB, G/test_g_proofs.py): (1) boar at 23:30 and 01:30 each night, plus one detection 2 min after the window opens, gives recent_nights=8, and the Why line reads 'Wild boar seen 8 of the last 7 nights here'. (2) Boar on 8 of 20 watched nights, each visit straddling midnight, is reported as 'seen 16 of 21 nights', presence 0.76, verdict BEST_ODDS. The truth is 8/20 = 0.40, which is WORTH_A_LOOK.
- **Verifier:** model.py:99, :119, :125 and :281 key nights by func.date(timezone(tz, captured_at)), while exposure.night_expr (exposure.py:54-56) is the app-wide night key. recent_nights uses captured_at > now-7d (:131), which spans 8 calendar dates. Re-ran G/test_g_proofs.py: recent_nights=8 ('seen 8 of the last 7 nights'), and 8 true boar nights out of 20 are reported as 16 of 21 with verdict BEST_ODDS.
- **Fix:** Use exposure.night_expr() for nights_present, active_nights and total_nights. For recent_nights, take k = date(now_local - 6h), the current night key, and count distinct night keys in [k-7, k-1], the last 7 completed nights. The proposed '>= k-7' still allows 8 keys because it includes night k. Add a regression test for a visit that straddles midnight and one for the 8-date window.

### G-03 — A camera moved or added a few days ago hijacks the headline as 'Not enough to say'

*high · confirmed · bug · effort S* — `backend/app/forecasting/model.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** Hunters move cameras often during the season. Each time, the hero card reads 'Not enough to say' for the new spot while still giving its best hours. The camera that actually has the best odds is shown only as a small row under 'Other places'.
- **Evidence:** Forecasts are ranked by raw presence (model.py:303/326). A camera with 3 watched nights and boar on all 3 has presence 1.0, so it sorts first. The headline verdict is then _verdict(top.probability, top.active_nights), which returns NO_DATA for fewer than 15 nights (model.py:71-72, :379). PROVEN (G/test_g_proofs3.py::test_new_camera_hijacks_headline_as_no_data): Old camera with boar on 40 of 60 nights, New camera with boar on 3 of 3. Result: verdict NO_DATA, recommended camera 'New', and alternates[0] = Old with BEST_ODDS.
- **Verifier:** forecast_tonight sorts by raw probability (model.py:303/326), and the headline verdict is _verdict(top.probability, top.active_nights), which returns NO_DATA below 15 nights (:71-72, :379). Re-ran G/test_g_proofs3.py: verdict NO_DATA with New recommended, while Old (40/60 nights) sits in alternates as BEST_ODDS. Tonight.tsx:79 renders this as 'Not enough to say' on the hero card. It happens for about two weeks after any camera is added.
- **Fix:** Sort by (verdict != 'NO_DATA', probability) so judged cameras always lead. If every camera is NO_DATA, keep the current behaviour. Optional shrinkage, e.g. (n+1)/(N+2), is fine but changes the persisted probabilities that scoring uses, so make that change separately.

### K-01 — A camera taken down weeks ago keeps topping Tonight as 'Best odds' on its old history, and there is no way to retire it

*high · confirmed · data-correctness · effort S* — `backend/app/forecasting/model.py`, `backend/app/health.py`, `backend/app/api/routes_cameras.py`, `backend/app/forecasting/changes.py`

- **What the hunter sees:** The hunter is sent to the spot of a camera that has been in a drawer for weeks, while the camera that is actually seeing boar is ranked below it.
- **Evidence:** model.py:149-154 skips the recency penalty whenever producing=False, and nothing limits how long that exemption lasts. model.py:290 ranks every Camera row with no active filter (only changes.py:51 and routes_photos.py:41 honour Camera.active). No route or UI ever sets Camera.active (grep finds only reads). health.py:46 marks a camera 'not producing' after 36 h and it stays that way forever. Trigger: PL07 saw boar on 24 of 30 nights, was taken down 45 days ago and is still in the SPYPOINT account. PL19 is live and saw boar on 3 of the last 7 nights. PROVEN with scratchpad/K/test_k_retired.py against the test DB. forecast_tonight returns verdict BEST_ODDS, camera 'PL07 (taken down in August)', 'Wild boar seen 24 of 30 nights at this camera.' The live PL19 is demoted to 'Other places: Worth a look'. The same screen lists PL07 under 'Cameras not sending: No check-in for 1080h'. This differs from E-23 (the offline label for removed logins) and H-20 (sync stopped): here the headline itself goes to a dead camera, indefinitely.
- **Verifier:** I re-ran scratchpad/K/test_k_retired.py and got BEST_ODDS for 'PL07 (taken down in August)' while the live PL19 dropped to WORTH_A_LOOK. model.py:290 ranks every Camera row with no active filter. model.py:149-154 keeps a camera on its full history once it is not producing, and nothing limits how long that lasts. Camera.active is only read (changes.py:51, routes_photos.py:41) and never written by any route. The 'Why' row (Tonight.tsx:262, model.py:253-259) does say 'Camera is not sending photos right now', but the headline still names the dead camera.
- **Fix:** Ending the not-producing exemption alone is not enough: PL07 at 0.8-0.15=0.65 would still outrank PL19 at 0.4. In forecast_tonight, leave out of `forecasts` (and so out of persist_tonight's `where`) any camera whose hours_since_report or newest image is older than about 7 days. Keep those cameras in the 'Cameras not sending' alerts. Add an admin PATCH /cameras/{id} {active} with a 'Retire camera' switch. Filter Camera.active at model.py:290, alerts.py and scoring.persist_tonight.

### A-12 — /alerts recomputes the whole forecast only to check a verdict that no longer exists; each chip tap runs two full forecasts and dead cameras are listed twice

*medium · confirmed · perf · effort S* — `backend/app/forecasting/alerts.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** Every chip tap costs two full forecasts plus the weather call, on a phone with weak signal. The same dead camera is reported twice on the first screen. When a background refresh of the overview fails, the charts under 'Show the numbers' disappear (setD(null)).
- **Evidence:** compute_alerts (alerts.py:41-50) runs the full forecast_tonight() on every GET /alerts only to test `verdict == 'GO'`. That verdict no longer exists (it is now BEST_ODDS etc.), so the 'Strong night ahead' alert never fires. Tonight.load() (Tonight.tsx:116-134) requests the forecast, /analytics/overview, /alerts and /species on every chip tap and every return to the app. alerts.py:70-95 also re-lists offline and out-of-credit cameras that the forecast already returns in f.alerts. PROVEN: scratch test_alerts_recomputes_forecast_and_duplicates_camera_faults. With 8 cameras the forecast runs 48 SQL statements and /alerts 51, including one full forecast; 'GO' is never true; 'Cam0' appears under 'Cameras not sending' and again as 'Cam0 offline' under 'Alerts'. Playwright T2: one chip tap sends 4 requests.
- **Verifier:** Reproduced: /alerts runs 51 SQL statements, including one full forecast_tonight (alerts.py:44). It tests verdict=='GO', which _verdict can never return (model.py:71-77), so the 'Strong night ahead' alert is dead code. 'Cam0' appears in both f.alerts and '/alerts' 'Cam0 offline'. T2 logs 4 requests per chip tap, and Tonight.tsx:128 sets d to null on a failed overview refresh.
- **Fix:** Delete the forecast call and the dead GO block from compute_alerts. If an opportunity alert is wanted, derive it on the client from the forecast it already has (BEST_ODDS). Drop the camera-health cards from /alerts on Tonight, since f.alerts already shows them. On chip taps, refetch only the forecast, and keep the previous overview on failure.

### A-13 — Nights are counted by calendar date: 'Wild boar seen 8 of the last 7 nights' and inflated 'Seen X of Y nights'

*medium · confirmed · data-correctness · effort S* — `backend/app/forecasting/model.py`

- **What the hunter sees:** 'Seen 8 of the last 7 nights' reads as broken, and the 'Seen X of Y nights' figures are inflated for exactly the nocturnal animals the app is for.
- **Evidence:** _camera_forecast counts nights with func.date(timezone(tz, captured_at)) (model.py:99, 119, 125, and total_nights at 280-282). Those are calendar days, while exposure.py:54-56 defines a night by its evening date (minus 6 h). A visit spanning midnight counts as two nights, and the 7-day recent window covers 8 dates. PROVEN: scratch test_nights_are_calendar_days_so_one_visit_counts_twice. 20 real nights, each with one visit from 23:40 to 00:20, give 'Wild boar seen 21 of 21 nights', the factor 'Wild boar seen 8 of the last 7 nights here', and nights_of_data 21.
- **Verifier:** Reproduced: 20 nights of 23:40→00:20 visits give 'Wild boar seen 8 of the last 7 nights here' and nights_of_data 21. model.py:99,119,125,281 count func.date(timezone(tz, captured_at)), i.e. calendar dates, and the recent window is a rolling 7×24 h (model.py:131). exposure.night_expr already implements the 6 h-shifted night (exposure.py:41,54). Any activity after midnight this morning also adds an 8th date.
- **Fix:** The proposed fix is right.

### A-14 — When the classifier falls behind, the verdict drops and says the animals are gone; the 'Changed' line says the camera sent nothing

*medium · confirmed · data-correctness · effort M* — `backend/app/forecasting/model.py`, `backend/app/forecasting/changes.py`

- **What the hunter sees:** Whenever the classifier lags or stops (AI machine off, model crash), the headline drops and says the animals have left. The 'Changed' line claims a camera sent nothing when it sent 35 photos.
- **Evidence:** active_nights (model.py:118-121) counts every image date, including photos the classifier hasn't checked yet (processed_at IS NULL). When recent detections are missing, the forecast applies the -0.15 penalty and the '--' factor (model.py:149-154, 267) even though producing=True. exposure.py marks those nights UNPROCESSED, but the forecast ignores that. whats_changed reads an UNPROCESSED last night as 'sent nothing' (changes.py:57-66) and uses date.today() in server UTC (changes.py:40). PROVEN by scratch tests. With the photos classified: BEST_ODDS 0.78 and 'seen 7 of the last 7 nights'. Same photos not yet classified: WORTH_A_LOOK 0.34 and 'No Wild boar here in the last 7 nights'. test_changed_line… gives 'Cerro sent nothing last night' with 35 unchecked photos.
- **Verifier:** Reproduced: the same photos classified give BEST_ODDS 0.78 and 'seen 7 of the last 7'. Left unclassified, they give WORTH_A_LOOK 0.34 and 'No Wild boar here in the last 7 nights'. active_nights counts every image date, processed or not (model.py:118-121), and the -0.15 penalty applies whenever producing=True (model.py:150-154). whats_changed treats UNPROCESSED the same as UNKNOWN or missing, so it says 'Cerro sent nothing last night' with 35 frames (changes.py:57-66). It also uses date.today() on the server clock (changes.py:40).
- **Fix:** The proposed fix is right.

### G-02 — Tonight ignores the exposure table: unscanned or unclassified nights count as empty, and the 'N nights left out' note is false

*medium · confirmed · data-correctness · effort M* — `backend/app/forecasting/model.py`, `backend/app/forecasting/exposure.py`

- **What the hunter sees:** After a backfill, a new camera account, or a slow classifier pass, the best stand is downgraded and the card says the animals have been absent. It then claims the unwatched nights were excluded when they were counted as empty.
- **Evidence:** The model.py:118-121 denominator is any date with any Image row, including frames still waiting for the empty filter or the classifier. model.py:153-154 subtracts 0.15 when recent_nights==0, even if those nights were never processed. model.py:366-377 prints excluded_nights(db), an estate-wide all-time count of UNKNOWN/UNPROCESSED camera-nights, as 'N nights left out because the camera was not watching'. The forecast never reads camera_nights, so nothing is actually left out. PROVEN (G/test_g_proofs3.py::test_excluded_note_is_false_and_backlog_deflates): 30 processed nights with boar on 15, plus the last 7 nights synced but not yet scanned. Output: verdict WORTH_A_LOOK, 'Wild boar seen 15 of 37 nights', factor '-- No Wild boar here in the last 7 nights', and the foot note '7 nights left out because the camera was not watching'. Those 7 nights are in the 37. The truth is 15/30, which is BEST_ODDS.
- **Verifier:** model.py:118-121 counts any date with any Image, including frames not yet scanned, and model.py never reads CameraNight except for the excluded_nights count shown in the note (:366-377). My test shows frameless gaps inside a camera's range are always PRESUMED_UP and never UNKNOWN (exposure.py:127-129). So the note only counts UNPROCESSED nights and out-of-credits nights that still have frames, and both of those ARE in the forecast denominator: the note is false by construction. The deflation itself is transient, since scanning runs newest-first every sync, so it mainly shows after a backfill or new account; hence medium.
- **Fix:** Fix G-12 first. Otherwise, switching the denominator to observed_nights (CONFIRMED+PRESUMED_UP) turns battery outages into weeks of zeros. Then build active_nights and nights_present over CONFIRMED/PRESUMED_UP night keys per camera; this also stops a camera that only fires on animals from reading near 1.0. Skip the -0.15 penalty when fewer than ~4 of the last 7 night keys are observed. Make the note per recommended camera, with the reason ('photos not processed yet' or 'out of photo credits').

### G-12 — A camera silent for weeks is 'PRESUMED_UP', so a flat battery counts as a month of true zeros

*medium · confirmed · data-correctness · effort S* — `backend/app/forecasting/exposure.py`

- **What the hunter sees:** When batteries are replaced after a dead spell, the app treats the whole spell as 'watched and empty'. It then reports misses and 'quiet for N nights', which is the exact artefact the exposure table was built to remove.
- **Evidence:** exposure.py:123-130 marks any frameless night PRESUMED_UP when the camera has frames at some point before and some point after, however long the gap. PROVEN (G/test_g_proofs.py::test_long_outage_is_presumed_up): frames on 1 Oct and 31 Oct only produce 29 PRESUMED_UP nights. Those nights feed observed_nights, calibration misses, the Changed history medians and quiet runs.
- **Verifier:** Any frameless night between a camera's first and last frame is PRESUMED_UP (exposure.py:123-130); my test shows UNKNOWN never arises from gaps at all. verify-G/test_vg.py::test_battery_gap_reads_as_animals_back: a busy camera with 12 dead nights, then back, makes the Tonight Changed line say 'Animals back at Puente after 12 quiet nights.', and that kind outranks everything (score 100+). The calibration claim is overstated. observed_nights is unused, and evaluate_night grades the next morning, before the gap is bracketed (the night has no row, so it is skipped). It would only become real if past nights were regraded (see G-15).
- **Fix:** Only presume up a frameless run of <= 2 nights that has frames on both neighbouring nights; mark longer runs UNKNOWN. Where last_report_at or battery telemetry exists, use it to confirm uptime. Land this before any change that regrades past nights (G-15) or moves the forecast denominator onto camera_nights (G-02).

### G-14 — Track-record copy claims 'better than each camera's usual rate' but compares with an estate-wide rate

*medium · confirmed · data-correctness · effort S* — `backend/app/forecasting/scoring.py`

- **What the hunter sees:** The 'How often this has been right' line tells the hunter the model adds skill when it does no better than 'this camera is usually busy'. It can also show a verdict on the model after under a week.
- **Evidence:** The scoring.py docstring promises per-camera climatology, but :206-209 uses one pooled base rate for all cameras. The statement at :240-247 says 'better than simply assuming each camera's usual rate'. MIN_EVALUATED=30 (:50) counts camera-nights, so with 6 cameras the hit rate appears after 5 nights. PROVEN (G/test_g_proofs.py::test_calibration_pooled_climatology_overclaims): a model whose probability is exactly each camera's own base rate (0.8 and 0.1) gets skill_vs_climatology 0.598, beats_baseline True, and the statement 'Right on 89% of 80 scored camera-nights, better than simply assuming each camera's usual rate.'
- **Verifier:** scoring.py:206-209 uses one pooled base rate, while the docstring (:24-26) and the statement (:240-247) promise 'each camera's usual rate'. MIN_EVALUATED=30 (:50) counts Forecast rows, and each night writes one row per camera in 'where'. The re-run G/test_g_proofs.py::test_calibration_pooled_climatology_overclaims shows a model equal to per-camera base rates getting 'better than simply assuming each camera's usual rate'.
- **Fix:** Compute climatology per camera as a leave-one-out base rate over that camera's evaluated rows, falling back to the pooled rate for cameras with fewer than ~10 rows. Gate availability on distinct target_date >= 30 as well as rows.

### G-16 — 'Changed' line reports the night still in progress between midnight and 06:00

*medium · confirmed · bug · effort S* — `backend/app/forecasting/changes.py`, `backend/app/forecasting/scoring.py`

- **What the hunter sees:** A hunter checking at 01:00 or before a dawn sit is told the ground went quiet, based on half a night.
- **Evidence:** changes.py:40 sets last_night = date.today() - 1. On the native Windows host date.today() is the Madrid date, so at 01:00 on 1 Nov 'last night' is 31 Oct, the night currently under way. In Docker (UTC) the same happens from 02:00 in summer time. PROVEN (G/test_g_proofs6.py): 14 nights with 4 visits each (21:00, 23:00, 02:00, 04:00). At 01:00 only the 21:00 and 23:00 visits of the current night exist, and whats_changed returns 'Puente was quieter than usual last night: 2 visits against a usual 4.'
- **Verifier:** changes.py:40 uses (today or date.today()) - 1 day. On the Madrid-local native host at 00:00-06:00 that is the night still in progress. Re-ran G/test_g_proofs6.py: 'Puente was quieter than usual last night: 2 visits against a usual 4.' The same default is at scoring.py:60 and :133. In Docker (UTC) it is also wrong the other way: at 00:00-02:00 CEST it skips back two nights.
- **Fix:** Add current_night_key(now) = (now.astimezone(estate_tz) - 6h).date(). Set last_night = current_night_key - 1 day in whats_changed and evaluate_night, and set persist_tonight target = current_night_key when run before 06:00, otherwise today in the estate TZ. Never use date.today().

### G-17 — 'Changed' line flags one-visit swings and counts unobserved nights as quiet

*medium · confirmed · data-correctness · effort S* — `backend/app/forecasting/changes.py`

- **What the hunter sees:** A single extra boar is presented as news, the copy is ungrammatical ('1 visits against a usual 0'), and 'quiet for 4 nights' can include nights nobody looked at.
- **Evidence:** changes.py:123-130 'shift' fires when |count-median|/max(median,1) >= 0.5, and prints '{count} visits' and '{median:.0f}'. PROVEN (G/test_g_proofs2.py::test_changed_shift_tiny_sample_copy): history of boar on 5 of 10 nights (median 0.5) and 1 visit last night gives 'Puente was busier than usual last night: 1 visits against a usual 0.' Also, gone_quiet (:108-121) counts prior nights with per_night==0 without checking exposure. PROVEN (G/test_g_proofs3.py::test_gone_quiet_counts_unobserved_nights): 3 unscanned nights plus 1 watched empty night give 'Puente has been quiet for 4 nights. It usually sees 2 a night.' The run is also capped at 4 however long the silence is.
- **Verifier:** The shift test at changes.py:123-130 (|count-median|/max(median,1) >= 0.5 with median > 0) fires for any camera with a median of 0.5. Re-ran G/test_g_proofs2.py: '1 visits against a usual 0.' My test gives 'Puente was quieter than usual last night: 0 visits against a usual 0.' So a camera with boar on half its nights produces a 'Changed' line every night. gone_quiet (:108-121) counts prior nights without an exposure check and caps at 4 (G/test_g_proofs3.py passes).
- **Fix:** For shift, require median >= 1 and |count - median| >= 2. Pluralise 'visit', and print the median as 'about N' (1 decimal below 2). For gone_quiet, count only CONFIRMED or PRESUMED_UP nights and walk back until the first night with visits to get the real run length (and fix G-12, or dead gaps count as quiet).

### H-12 — Tonight's forecast claims are matched to cameras by name, so two cameras with the same name swap or lose their claims

*medium · confirmed · data-correctness · effort S* — `backend/app/forecasting/scoring.py`, `backend/app/models.py`, `backend/app/api/routes_cameras.py`

- **What the hunter sees:** One camera never gets scored, and the other is graded on its neighbour's prediction. The track record on Tonight becomes wrong without any sign.
- **Evidence:** persist_tonight builds {c.name: c.id} over all cameras (scoring.py:70) and looks each claim up with entry['camera'] (scoring.py:76), even though every entry already carries camera_id (model.py:217). cameras.name has no unique constraint (models.py:92), rename allows any name (routes_cameras.py:147-164), and vendor defaults ('SPYPOINT', UBox device names) can repeat. PROVEN with scratch/H/dup_name.py: cameras A and B both named 'Feeder', claims p=0.9 for A and p=0.1 for B. Both Forecast rows were written against camera B.
- **Verifier:** scoring.py:70,76 map claims by camera name even though every entry already carries camera_id (model.py:157,217). Reproduced with a more realistic case: a live camera 'Feeder' and a retired, inactive camera also named 'Feeder'. The live camera's p=0.9 claim was written against the retired camera's id. There is no unique constraint on the name (models.py:98), and rename accepts any value.
- **Fix:** In persist_tonight, use cam_id = uuid.UUID(entry['camera_id']) and skip the entry if that camera no longer exists. A unique name index is optional; it could fail on existing data, so check for duplicates first.

### J-10 — After midnight the 'Changed' line treats the night in progress as 'last night'

*medium · confirmed · bug · effort S* — `backend/app/forecasting/changes.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** A hunter on a boar espera who checks the app at 00:30 gets a false camera-down alarm, or a 'quieter than usual' built on half a night.
- **Evidence:** whats_changed uses date.today() (changes.py:290), the server's local calendar date. Every other night key uses local time minus 6 h (routes_stands.tonight, exposure.night_expr). PROVEN with a scratch test: 20 nights of boar at 22:00 and nothing yet on the current night. At 18:00 the line says 'Nothing changed. Much the same as the last few nights.' With the same data at 00:30 it says 'PL19 sent nothing last night. Unknown whether anything came through.' Separately, changes.py:308-316 reports UNPROCESSED nights (frames arrived, classifier still behind) as 'sent nothing'.
- **Verifier:** The cited line numbers are wrong (the file is 144 lines), but the bug is real. changes.py:40 uses date.today(), so between 00:00 and 06:00 local, last_night is the night still in progress. That night has no CameraNight row until frames arrive (exposure.py only spans first..last observed night), and changes.py:56-66 then reports camera_down whenever the previous 4 nights include a CONFIRMED one. The same branch reports UNPROCESSED nights as 'sent nothing'.
- **Fix:** Use last_night = routes_stands.tonight(now) - 1 day, with the estate timezone and 06:00 rollover. Give UNPROCESSED its own sentence ('Last night's photos are still being sorted') instead of camera_down. Apply the same night key to scoring.persist_tonight and evaluate_night, which also use date.today().

### J-12 — Tonight lists every broken camera twice, and /alerts recomputes the whole forecast for an alert that can never fire

*medium · confirmed · ux · effort S* — `frontend/src/pages/Tonight.tsx`, `backend/app/forecasting/alerts.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** The duplicate warning reads as a glitch, and Tonight is slower than it needs to be on the Db01 VM.
- **Evidence:** forecast_tonight returns non-producing cameras (model.py:292-295), which Tonight shows as 'Cameras not sending' (Tonight.tsx:314-325). compute_alerts adds the same cameras again as 'PL19 offline' or 'out of photo credits' (alerts.py:70-94) in the Alerts card (Tonight.tsx:327-344). PROVEN: a camera last seen 48 h ago appears in both cards. compute_alerts calls forecast_tonight() (alerts.py:42) only to test verdict=='GO' (alerts.py:44), a value the model no longer returns. Measured on a synthetic season (8 cameras, 36k detections, weather mocked): /forecast/tonight took 366 ms and 49 SQL statements, /alerts 288 ms and 52, /analytics/overview 766 ms. That is about 1.4 s of database work per Tonight open, before any weather call, repeated on every return to the app.
- **Verifier:** forecast_tonight returns non-producing cameras as alerts (model.py:292-295), which Tonight.tsx:314-325 shows. compute_alerts adds the same offline/out_of_credits cameras again (alerts.py:70-89), shown at Tonight.tsx:327-344, and camera_health marks both states producing=False (health.py:46). alerts.py:42-44 recomputes the whole forecast only to test verdict=='GO', which _verdict never returns. Out-of-credit SPYPOINTs are common, so the duplicate card is often visible. The timing figures were not re-measured.
- **Fix:** Delete block 1 (the dead GO check and forecast call) and block 3 (camera health) from compute_alerts. Consider dropping block 4 ('quiet') too, since whats_changed already reports gone_quiet using exposure. Loading /analytics/overview only when the fold opens is a separate, optional win.

### A-24 — With no photos, Tonight says 'From 1 nights of camera photos.'

*low · confirmed · bug · effort S* — `backend/app/forecasting/model.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** A fresh install with no photos shows the wrong number, with broken grammar, on the first screen.
- **Evidence:** model.py:280-282 computes total_nights with `... or 1`, and Tonight.tsx:307 renders 'From {n} nights of camera photos.' PROVEN: scratch test_zero_data_says_one_night gives nights_of_data == 1 with zero images.
- **Verifier:** Reproduced: with zero images, nights_of_data==1 (model.py:280-282 `or 1`). Tonight.tsx:306-307 always renders 'From {n} nights of camera photos.' inside the verdict card.
- **Fix:** The proposed fix is right.

### A-26 — The green 'busiest hours' in the hour chart can contradict the headline 'Best hours'

*low · confirmed · ux · effort S* — `frontend/src/pages/Tonight.tsx`, `backend/app/api/routes_analytics.py`

- **What the hunter sees:** The headline says 'Best hours 21:00 to 00:00' while the chart under 'Show the numbers' highlights, say, 03:00-06:00 in green. The numbers seem to contradict the verdict, especially with a species chosen.
- **Evidence:** The 'Sightings by hour' chart colours overview.best_window green (Tonight.tsx:166-168, 395-401). That window is computed over all 24 h and all visible species (routes_analytics.py:25-37, 50-53). The headline 'Best hours' is limited to 16:00-01:00 and to the chosen species at the top camera (model.py:40-53).
- **Verifier:** By construction: overview.best_window searches all 24 hours over all visible species (routes_analytics.py:26-37,50-53,82). The headline window is limited to 16:00-01:00 for the chosen species at the top camera (model.py:40-53,135-144). Tonight colours the overview window green (Tonight.tsx:166-168,399). The chart is labelled 'busiest hours', which softens but does not remove the contradiction.
- **Fix:** The proposed fix is right. Relabelling the band is the cheapest version.

### G-11 — Exposure marks nights CONFIRMED before the species classifier has run

*low · confirmed · data-correctness · effort S* — `backend/app/forecasting/exposure.py`, `backend/app/forecasting/scoring.py`

- **What the hunter sees:** Camera-nights with real animals, still waiting for the classifier, count as misses in 'How often this has been right' and as quiet nights in the Changed line.
- **Evidence:** exposure.py:87-89 and :131-142 treat a night as UNPROCESSED only when Image.processed_at is NULL. The empty filter sets processed_at (empty_filter.py:29), but the species pass (classify_unclassified, 2000-image limit, separate schedule in Docker) may not have written Detections yet, and it leaves failed images with none. Such a night is CONFIRMED with zero detections. PROVEN (G/test_g_proofs.py::test_unclassified_animal_frames_are_confirmed_and_scored_as_miss): 5 kept animal frames with no Detection give state CONFIRMED, and evaluate_night scores the boar claim occurred=False.
- **Verifier:** exposure.py:88 and :131 key UNPROCESSED only on processed_at IS NULL, which empty_filter.py:29 sets before species.py writes any Detection. The re-run proof test gives CONFIRMED and occurred=False. In practice the gap is narrow: the native sync runs scan, then classify, then exposure in sequence (pipeline.py:62-71), and a 06:00 night boundary with an 11:00 score leaves 5 h to classify. It bites only during backlogs (scan limit 5000 vs classify limit 2000), with Docker's independent 20/25/60-min schedules, or for images whose classification keeps failing.
- **Fix:** Count kept frames (is_empty_frame false, original_path not null) with no Detection per night, and mark the night UNPROCESSED only when that count is > 0 AND the frames are recent or unattempted. A frame whose classify keeps throwing (e.g. missing file, logged at species.py:56) would otherwise pin its night UNPROCESSED forever. The clean way is a classified_at or classify_attempts column set by classify_unclassified.

### G-13 — Scoring counts detections made before the claim, and ignores the claimed hours

*low · confirmed · data-correctness · effort S* — `backend/app/forecasting/scoring.py`, `backend/app/forecasting/exposure.py`

- **What the hunter sees:** 'Right on X% of N nights' is inflated by the forecast grading itself on data it already had. The one honest trust signal overstates the model.
- **Evidence:** scoring.py:105-113 _detected uses night_expr()==night, and night_expr covers 06:00 D to 06:00 D+1 (exposure.py:54-56), not 18:00-06:00 as its comment says. The claim is written at 17:00 on D, so a boar photographed at 09:00 that morning, already known to the forecast via recent_nights, scores as a hit. PROVEN (G/test_g_proofs.py::test_pre_forecast_morning_detection_counts_as_hit): boar at 09:00 local and empty frames all night give occurred=True for the night's claim.
- **Verifier:** scoring.py:105-113 grades with night_expr()==night, and night_expr covers 06:00 D to 06:00 D+1 (exposure.py:41,54-56), contrary to the '18:00 D' comment at :38. The re-run proof test shows a 09:00 boar on the forecast day counted as a hit for a claim persisted at 17:00. The net effect on the hit rate is modest: it raises occurrence at every camera, which helps high-p claims and hurts low-p ones. So this is low rather than medium, but it is still grading on data the model already had.
- **Fix:** In _detected, restrict to captured_at >= max(Forecast.generated_at, local 18:00 on D) and < local 06:00 on D+1, built with the estate TZ so the DST night (25 Oct) is 13 h long, not 12.

### G-18 — The only 'Strong night ahead' alert can never fire, but every Tonight load still recomputes the whole forecast for it

*low · confirmed · bug · effort S* — `backend/app/forecasting/alerts.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** The only high-severity alert is silently gone, and each Tonight open or chip tap does double the server work for nothing.
- **Evidence:** alerts.py:42-44 calls forecast_tonight(db) and checks verdict == 'GO', a label that was retired; verdicts are BEST_ODDS/WORTH_A_LOOK/QUIET/NO_DATA. PROVEN (G/test_g_proofs.py::test_opportunity_alert_is_dead_code): forecast verdict BEST_ODDS with probability 0.97 produces no 'opportunity' alert. Tonight.tsx:129 fetches /alerts on every load and on every species-chip tap, so the forecast is computed twice per view. Timing on 71k images / 32k detections (G/test_g_perf.py): forecast_tonight 235 ms, /alerts 258 ms, almost all of it the duplicated forecast.
- **Verifier:** alerts.py:42-44 checks verdict == 'GO', a label _verdict can no longer return (model.py:59-77). The re-run proof test gives BEST_ODDS 0.97 and no opportunity alert. compute_alerts recomputes forecast_tonight on every /alerts call, and Tonight.tsx:129 fetches /alerts on each load; re-measured about 227 ms forecast plus 248 ms alerts on 71k images. The lost alert is harmless because the hero card already shows the verdict, so this is mostly waste: low.
- **Fix:** Delete the opportunity block and the forecast_tonight import from alerts.py. That halves the Tonight server cost and removes the model-to-alerts import.

### G-22 — Herd-makeup drill-down loads every detection into Python and returns an unbounded list

*low · confirmed · perf · effort M* — `backend/app/api/routes_insights.py`, `frontend/src/pages/Insights.tsx`

- **What the hunter sees:** Tapping 'Stag' or 'Hind' on weak signal shows 'Loading photos…' for a long time and then a huge grid.
- **Evidence:** routes_insights.py:194-213 selects every Detection joined to Image, Species and Camera with no WHERE, then filters by class_label in Python and returns everything. Measured on a synthetic season (32k detections): 179 ms server time and 2,142 photos for 'Stag', about 400 KB of JSON. Insights.tsx:209-227 renders all 2,142 tiles in one grid. The sibling /species/{id}/images caps at limit=300.
- **Verifier:** routes_insights.py:36-55 selects every Detection joined to Image, Species and Camera with no WHERE or LIMIT and filters by class_label in Python. Re-measured: 173 ms and 2,142 rows for 'Stag' on synthetic data. Insights.tsx:220 already lazy-loads the images, so the cost is JSON size and DOM. Real Stag counts are probably smaller, because sex labels come from a capped paid pass (SEX_LIMIT_PER_RUN=150). A hidden-species leak here is not reachable, since _composition never offers hidden labels.
- **Fix:** Translate the label to SQL predicates (species_id, sex, group_type), order by captured_at desc, add limit=120 with a 'before' cursor, and load more on scroll in the overlay.

### G-24 — Insights says 'The other cameras see far less' when there are no other cameras

*low · confirmed · ux · effort S* — `backend/app/forecasting/insights.py`

- **What the hunter sees:** The copy refers to cameras that don't exist, or overstates the difference, which undermines trust in the other findings.
- **Evidence:** insights.py:107-114: the 'Most of the action is at A and B. The other cameras see far less.' wording fires whenever the top-2 share is >= 50%. With only 2 cameras that is always 100%, and with 4 near-equal cameras (30/25/25/20) it still claims 'far less'. It also counts burst frames. PROVEN (G/test_g_proofs2.py::test_two_cameras_other_cameras_far_less): two cameras give 'Most of the action is at Track and Wallow. The other cameras see far less.'
- **Verifier:** insights.py:213-226 emits 'Most of the action is at A and B. The other cameras see far less.' whenever the top-2 share of detection rows is >= 50%. With only two cameras that is always 100% (G/test_g_proofs2.py passes), and with 30/25/25/20 it still claims 'far less'.
- **Fix:** Emit the concentration line only when >= 3 cameras have sightings and the third camera's share is < half the second's. Otherwise say '{A} and {B} are your busiest cameras.' Count visits, not frames, and exclude hidden species (G-06).

### I-20 — Tonight's 'Seen here' lists other animals first when the verdict is for Wild Boar

*low · confirmed · ux · effort S* — `backend/app/forecasting/model.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** The card says 'go for boar' and then leads with roe deer and fox, which reads as a contradiction.
- **Evidence:** When no species is picked, _expectations (model.py:185-229) collects the classes of every huntable species at the camera, and line 330 copies the top 4 onto the card. Wild boar is split into Boar/Sow/Sow + piglets/Sounder, so undivided species outrank it. Live result with 'Anything' picked: verdict 'Wild Boar … seen 31 of 41 nights', Seen here: 'Roe Deer ×66, Fox ×48, Sow + piglets ×48, Boar ×44'. The API's 'expect' field is 'Roe Deer'. Screenshot: shots/crawl_390_tonight.png.
- **Verifier:** Live API: recommended.species 'Wild Boar', expect 'Roe Deer', classes [Roe Deer 66, Fox 48, Sow + piglets 48, Boar 44]. With no pick, _expectations aggregates every huntable species at the camera (model.py:188-225), and line 330 copies the top 4. Downgraded because the heading is 'Seen here', which is accurate, but it does contradict the headline.
- **Fix:** For the top card, filter the classes to the recommended species_id and keep the mixed list in the per-camera fold. Also fix 'expect' so it is derived from that filtered list.

### I-26 — Two cameras can be given the same name, and their sightings then merge

*low · confirmed · data-correctness · effort S* — `backend/app/api/routes_cameras.py`, `backend/app/api/routes_analytics.py`

- **What the hunter sees:** 'Sightings by camera' and camera counts become wrong after an easy rename mistake.
- **Evidence:** rename_camera (routes_cameras.py:146-170) has no uniqueness check. overview groups by Camera.name (routes_analytics.py:59). Tonight and Stands also key React rows by camera name. Proven: renaming 'Pinar Alto' to 'PL19 Charca' returned 200; /analytics/overview by_camera then showed one 'PL19 Charca' row with 910 sightings and totals.cameras = 3 instead of 4.
- **Verifier:** Reproduced: renaming 'Pinar Alto' to 'PL19 Charca' returned 200. /analytics/overview then showed one 'PL19 Charca' row with 910 sightings and totals.cameras 3, because it groups by Camera.name (routes_analytics.py:56-62) and rename_camera has no uniqueness check (routes_cameras.py:146-170).
- **Fix:** The proposed fix is right.

### J-24 — FEATURE: Count visits, not photos, in what hunters see

*low · confirmed · feature · effort S* — `backend/app/forecasting/exposure.py`, `backend/app/forecasting/model.py`, `frontend/src/pages/Tonight.tsx`, `backend/app/forecasting/insights.py`

- **What the hunter sees:** '×47' reads as 47 animals or visits; one loitering boar dominates the ranking.
- **Evidence:** Why it fits: DeerLab groups photos into 15-minute sightings so loitering animals don't inflate counts (deerlab.com, 'how we pattern bucks'). exposure.visits_by_night (exposure.py:192-250) already collapses bursts into visits with group size, but only the Changed line uses it. Tonight still shows 'Sow + piglets ×47' as photo counts (Tonight.tsx:274-285, model.py:188-225), and Insights shows 'N photos, mostly at X' (insights.py:123-150).
- **Verifier:** _expectations and _composition count Detection rows, i.e. photos (model.py:188-225, insights.py:122-150). The Tonight hero shows '×N' with no note, while the 'Counts are photos' note sits only behind the fold (Tonight.tsx:274-285 vs 380). visits_by_night already exists (exposure.py:192-250). The camera ranking uses distinct nights, so 'dominates the ranking' is true only for which species is chosen at a camera (model.py:109,114).
- **Fix:** Use visits_by_night for the class and composition counts and label them 'N visits'. Pick each camera's top species by nights or visits instead of count(Detection.id). Keep photo counts behind the fold.

### K-10 — The track record's percentage grades 'Worth a look' as a prediction of no animals and includes 'Not enough to say' cameras

*low · confirmed · data-correctness · effort S* — `backend/app/forecasting/scoring.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** 'How often this has been right' punishes the app for correct 'Worth a look' calls and inflates itself with easy 'Quiet' nights, so hunters can't tell whether 'Best odds' actually delivers.
- **Evidence:** scoring.py:227 counts a claim as right when (p >= 0.5) == occurred. The screen's verdicts are BEST_ODDS >= 0.5, WORTH_A_LOOK 0.2–0.5, QUIET < 0.2 and NO_DATA under 15 nights (model.py:59-77). persist_tonight writes a claim for every camera in `where`, including NO_DATA ones (scoring.py:75-96). PROVEN with scratchpad/K/test_k_calib.py: 30 'Worth a look' nights on which boar came every time gives 'Right on 0% of 30 scored camera-nights.' Adding 60 'Quiet' and empty nights at another camera gives 'Right on 67% of 90 … better than simply assuming each camera's usual rate.' G-14 covers the baseline wording, not this grading rule.
- **Verifier:** I re-ran test_k_calib.py: 30 'Worth a look' nights with boar every time scored 'Right on 0%', and adding 60 empty 'Quiet' nights raised it to 67%. scoring.py:227 grades on p>=0.5, but the screen's verdicts split at 0.2 and 0.5 (model.py:73-77). persist_tonight (scoring.py:75-96) also writes claims for NO_DATA cameras. Low because the figure sits behind the 'Show the numbers' fold (Tonight.tsx:385).
- **Fix:** Report what the hunter reads: 'When it said Best odds, animals came X of N nights' and 'When it said Quiet, they came Y of M'. Grade per verdict stored in Forecast.factors['verdict'], and exclude NO_DATA claims. Keep Brier or skill in the fold only.


## 10. Hidden animals and hidden photos stay hidden everywhere

### G-06 — Hidden species still leak into alerts, Insights findings, Changed line and patterns

*high · confirmed · bug · effort S* — `backend/app/forecasting/alerts.py`, `backend/app/forecasting/insights.py`, `backend/app/forecasting/patterns.py`, `backend/app/forecasting/exposure.py`, `backend/app/api/routes_insights.py`

- **What the hunter sees:** The owner hid rabbits (or foxes) a week ago and still sees them as alerts, in 'Changed: X busier than usual', and in daytime 'busiest hours'. The Hide button looks broken.
- **Evidence:** Commit a1574b7 says a hidden species leaves 'the alert choices' and Insights, but only two lines of insights.py were filtered. Remaining leaks: alerts.py:18,59 uses a hardcoded PRIORITY set (ignoring Species.hidden and Species.is_priority). alerts.py:97-110 quiet check counts all detections. insights.py:60 total, :65-70 busiest window and :101-106 camera concentration have no hidden filter. patterns.py:117-126 'all' scope counts every species. exposure.visits_by_night (:209-239, used by the Changed line) has no species filter. The routes_insights.py:194-203 class drill-down has no hidden filter. PROVEN (G/test_g_proofs.py, test_g_proofs2.py): with Fox hidden, compute_alerts still returns an alert titled 'Fox'. With 60 hidden fox photos at camera 'Track', Insights says 'Most of the action is at Track and Ridge'. With 40 hidden rabbit photos at midday and boar only at 22:00, Insights says 'Your cameras are busiest between 10:00 and 13:00.'
- **Verifier:** Hide promises 'out of the app altogether (photos, counts, alerts, advice)' (routes_species.py:144), but alerts.py:18,59 uses a hardcoded PRIORITY set that includes fox, the alerts quiet query (:97-103) counts all detections, insights.py:172-218 total/hour/camera queries have no hidden filter, patterns.py:117-126 has none, and neither has visits_by_night (exposure.py:192-239). My test verify-G/test_vg.py::test_hidden_rabbit_moves_changed_line shows hidden rabbits turning the Tonight Changed line into 'Puente was busier than usual last night: 7 visits against a usual 2.' The /insights/class leak is not reachable from the UI, because _composition already filters hidden labels.
- **Fix:** Add one shared predicate (Species.hidden false) and apply it to: alerts sightings (use Species.is_priority AND NOT hidden in place of PRIORITY), the alerts quiet query, insights._correlations (total, hour and camera), patterns._nightly_activity, visits_by_night (JOIN species s ON s.id=d.species_id AND NOT s.hidden), and bedding.routes counts. class_images is optional. Add one 'hidden never appears' test per surface.

### C-05 — A photo marked "nothing in it" still counts as a sighting on Animals: count, 'Seen today', thumbnail and gallery

*medium · confirmed · data-correctness · effort S* — `backend/app/api/routes_species.py`, `backend/app/api/routes_photos.py`, `backend/app/api/routes_images.py`

- **What the hunter sees:** A hunter hides a false 'Wild boar' (a bush in IR) on Cameras. Animals still says 'Wild boar · Seen today' with the bush as its picture, and opening the gallery shows it again.
- **Evidence:** POST /images/{id}/flag (routes_images.py:74-84) only sets is_empty_frame=True and leaves the Detection in place. /species/spotted (routes_species.py:47-56) and its thumbnail query (69-74), /species/{id}/images (104-110) and the /photos/filters species counts (routes_photos.py:31-37) never filter on is_empty_frame or VISIBLE_ANIMAL. PROVEN with a scratch pytest (test_flagged_empty_still_counted_and_shown_in_animals): after flagging a boar photo empty, /photos returns 0 items, but /species/spotted still shows count=1 with thumb_image_id = the hidden photo and last_seen = its time, the wild_boar gallery still lists it, and the filter chip count is still 1.
- **Verifier:** The auditor's pytest passes: after flag, /photos is empty but /species/spotted count=1 with the flagged thumb, the gallery lists it, and the chip count is 1. flag_image (routes_images.py:84) only sets is_empty_frame. spotted (routes_species.py:47-56, 69-74), species_images (100-110) and filters (routes_photos.py:31-37) never check is_empty_frame, contrary to the 'everywhere' promise in visibility.py. It is a visible inconsistency with no data loss, so medium.
- **Fix:** Add Image.is_empty_frame.isnot(True) to spotted(), its thumb query and species_images(), and join Image with that predicate in the filters species count. A shared helper or the VISIBLE_ANIMAL predicate keeps them in step. Add one test that flags a photo and asserts every list endpoint drops it.

### K-05 — Hiding a false 'animal' photo never reaches Tonight, Changed, Insights or the track record

*medium · confirmed · data-correctness · effort S* — `backend/app/api/routes_images.py`, `backend/app/forecasting/model.py`, `backend/app/forecasting/exposure.py`, `backend/app/forecasting/scoring.py`, `backend/app/forecasting/insights.py`, `backend/app/forecasting/changes.py`

- **What the hunter sees:** The hunter corrects the AI, the photos disappear, and Tonight keeps recommending the spot on the strength of those same photos. The correction looks like it did nothing.
- **Evidence:** routes_images.py:73-87 ('Hide this photo: nothing in it' on Cameras) only sets is_empty_frame=True and keeps the Detection row. Every forecasting query counts Detection rows with no is_empty_frame filter: model.py:94-110, 124-133 and 194-211; exposure.visits_by_night (exposure.py:195-213, which feeds Changed and scoring); scoring._detected (105-113); and insights._correlations and _composition (insights.py:65-140). PROVEN with scratchpad/K/test_k_flag.py (the real POST /api/images/{id}/flag via TestClient). Six detector 'boar' false positives on 6 of the last 7 nights were all hidden, and afterwards the Photos feed returns 0 items. forecast_tonight is unchanged: 'Wild boar seen 6 of 20 nights at this camera.', 'Wild boar seen 6 of the last 7 nights here', verdict WORTH_A_LOOK. visits_by_night still counts 6 visits. C-05 covers only the Animals page.
- **Verifier:** I re-ran test_k_flag.py through the real POST /api/images/{id}/flag. The Photos feed then returned 0 items, but the forecast stayed 'Wild boar seen 6 of 20 nights' and 'seen 6 of the last 7 nights', and visits_by_night still counted 6. routes_images.py:84 only sets is_empty_frame. The queries at model.py:94-133 and 194-211, scoring._detected (105-113) and exposure.visits_by_night never filter on it. Only api/visibility.py's VISIBLE_ANIMAL does, and it is used by the photo lists.
- **Fix:** Do not delete Detection rows on flag. It is a toggle ('Keep this photo: there is an animal in it', Cameras.tsx:451), and un-hiding would lose the sighting. Add Image.is_empty_frame.isnot(True) (the same predicate as VISIBLE_ANIMAL) to the model.py queries, the exposure.visits_by_night SQL, scoring._detected, insights and the dispatch query. Then recompute that camera's nights after a flag.

### C-23 — Hidden species (rabbits) still show up under Named animals

*low · confirmed · data-correctness · effort S* — `backend/app/api/routes_animals.py`, `backend/app/ai/reid.py`

- **What the hunter sees:** Species the owner hid in Settings keep reappearing on the Animals page.
- **Evidence:** list_animals (routes_animals.py:58-81) and reid.cluster have no Species.hidden or empty-frame filter. PROVEN with a scratch pytest (test_hidden_species_individuals_listed): a hidden 'lagomorph' individual is returned as 'Rabbit #1'.
- **Verifier:** The auditor's pytest passes: a hidden 'lagomorph' individual is listed as 'Rabbit #1'. list_animals (routes_animals.py:61-81) has no Species.hidden or is_empty_frame filter, and neither does reid.cluster (reid.py:129-146).
- **Fix:** Add `.where(or_(Individual.species_id.is_(None), Species.hidden.is_(False)))` to list_animals, and skip hidden species and empty-flagged frames in cluster().

### I-25 — Cameras 'with animals' count still includes hidden animals and unprocessed frames

*low · confirmed · data-correctness · effort S* — `backend/app/api/routes_cameras.py`

- **What the hunter sees:** The numbers disagree from one tab to the next, which reads as a bug and undermines trust in the counts.
- **Evidence:** routes_cameras.py:98-109 computes sightings as count(all images) minus empty. It doesn't use VISIBLE_ANIMAL, and NULL (unprocessed) frames count as animals. Proven after hiding Rabbit: Cameras Details for PL19 Charca says 526 with animals, the Photos feed and filters say 496 (Barranco 462 vs 432, Encinar 495 vs 453, Pinar 456 vs 414). The same function also makes 4 queries per camera (N+1).
- **Verifier:** Reproduced: /cameras gives PL19 Charca 526 'with animals' against 496 from /photos/filters; the other cameras differ the same way (462/432, 495/453, 456/414). sightings is count minus empty (routes_cameras.py:92-109), and Cameras.tsx:399 recomputes the same thing, ignoring VISIBLE_ANIMAL. There are 4 queries per camera.
- **Fix:** The proposed fix is right. Also make Cameras.tsx use the server's visible count instead of image_count - empty_count.


## 11. Insights stops presenting chance as findings

### G-04 — Insights 'Weather and moon' prints findings from pure noise and from camera downtime

*high · confirmed · data-correctness · effort M* — `backend/app/forecasting/patterns.py`, `frontend/src/components/WeatherPatterns.tsx`

- **What the hunter sees:** Hunters will plan around moon and pressure 'findings' that are statistical noise or a flat battery. The disclaimer is hidden behind 'How to read this' at the bottom of the page.
- **Evidence:** patterns.py:108-133 builds a series for every date from the first to the last detection and fills missing dates with 0. It never consults camera_nights, so nights when the cameras were down count as zero sightings. It counts raw Detection rows, so bursts count many times, and the 'all' scope includes hidden species (:126). _driver (:153-199) keeps anything with effect >= 15% and confidence >= 0.15 across 8 variables and 3 scopes. WeatherPatterns.tsx:139-142 turns every unique top tercile into a plain sentence, 'More sightings ...'. model.py:319-325 already states that this code finds a driver in 97.8-99.8% of null runs, which is why it was removed from the verdict. Insights still shows it. PROVEN: (1) G/null_patterns.py runs _scope_drivers plus the frontend compare() logic on counts that are independent of every covariate. At least one 'More sightings when...' line appears in 97% (30 nights), 94% (60) and 86% (90) of runs, and 95-99% with overdispersed counts, averaging 1.7-3.2 findings. (2) G/test_g_proofs7.py: the same 2-3 boar visits every night, with the camera dead (no frames at all) on the 21 nights near full moon. compute_patterns returns 'About 1.1 sightings a day with a bright moon, about 2.5 with a dark moon', and the frontend sentence is 'More sightings on a dark moon.'
- **Verifier:** Re-ran G/null_patterns.py: on counts independent of every covariate, at least one 'More sightings ...' line appears in 86-99% of runs (1.7-3.2 findings each). This matches the admission in model.py:319-325, yet WeatherPatterns.tsx:139-155 still states them as plain findings. patterns.py:108-133 zero-fills every date from min to max with no exposure check and no hidden-species filter (:117-126), and it counts raw Detection rows.
- **Fix:** Short term: drop the 'More sightings ...' sentences (keep the bars behind 'Show the numbers' with a 'not tested' caption). Then build the series from visits_by_night over CONFIRMED/PRESUMED_UP camera-nights, normalised per watching camera and excluding hidden species. Only return a driver that beats a permutation null (e.g. 95th percentile of 200 shuffles), with some correction for testing 8 variables across 3 scopes.

### A-19 — Insights' 'More sightings when…' weather findings are mostly chance, and camera outages can create them

*medium · confirmed · data-correctness · effort M* — `frontend/src/components/WeatherPatterns.tsx`, `backend/app/forecasting/patterns.py`

- **What the hunter sees:** Insights presents chance patterns ('More sightings on a bright moon.') as plain facts. Hunters plan around noise, and a camera outage can manufacture a moon or weather 'finding'.
- **Evidence:** WeatherPatterns.tsx:139-142 prints 'More sightings …' for any factor whose top group is unique and 'separated' (95-103). The groups are sorted thirds of the nights (patterns.py:153-200), which never overlap, so the separation check filters nothing. patterns.py filters only on effect >= 15% and a correlation-based 'confidence'. model.py:319-325 already notes that this _driver code finds a 'driver' in 97.8-99.8% of simulations on pure noise. patterns.py:213 also counts 0 sightings for every night in range, including nights the cameras were down, which is the error exposure.py was written to remove. PROVEN by simulation using patterns._driver and the component's compare() logic: 500 synthetic 60-night seasons with counts independent of all 8 weather and moon factors. 96% show at least one 'More sightings …' finding, 2.8 on average.
- **Verifier:** My own null simulation used the real patterns._driver plus a port of WeatherPatterns.compare(), with counts independent of all 8 factors. Seasons with at least one 'More sightings…' finding: 91-94% (Poisson) and 98.7-99.7% (overdispersed), with 2-3.6 findings each on average. The separation check can't filter, because sorted thirds never overlap except at exact ties (WeatherPatterns.tsx:95-103). patterns.py:213 counts every night in range as 0 when there are no detections, including camera-down nights. This is Insights, not area A.
- **Fix:** The proposed fix is right. As an immediate step, hide the plain-sentence findings, or label them 'could be chance', until the permutation test lands.

### G-20 — One failed weather fetch blanks the Insights weather cards until a new night of data arrives, and they wrongly say 'Not enough nights'

*medium · confirmed · reliability · effort M* — `backend/app/forecasting/patterns.py`, `frontend/src/components/WeatherPatterns.tsx`

- **What the hunter sees:** After a brief outage the weather section reads 'Not enough nights to compare yet' for the day, and it misleads permanently for variables that simply show no effect.
- **Evidence:** patterns.py:70-79 swallows Open-Meteo errors and still caches the all-None result under (start,end) at :102-104. end is the last night with a detection, so the key only changes when a new night of data arrives. PROVEN (G/test_g_proofs2.py::test_patterns_weather_failure_is_cached): after one failure, a second call returns cached None weather and never retries. The fetch runs on the request path with two 30 s timeouts (:74). With no driver for a variable, which is also what happens when _driver drops a weak effect (:170-174), WeatherPatterns.tsx:110 shows 'Not enough nights to compare yet' even with 90 nights of data.
- **Verifier:** patterns.py:69-79 swallows fetch errors, and :102-104 caches the all-None result under (start, end). hi comes from the max night of any image (:114), so the failure sticks until the next day's first post-06:00 image. Re-ran G/test_g_proofs2.py::test_patterns_weather_failure_is_cached: no retry. When a driver is None (no pairs, or dropped by the effect/confidence filters at :170-174), WeatherPatterns.tsx:110 shows 'Not enough nights to compare yet' even with 90 nights of data.
- **Fix:** Cache only when every segment succeeded; otherwise cache for <= 10 min. Return a per-variable status (insufficient / no_difference / unavailable) so the card can say 'Weather history unavailable right now' or 'No difference'. Moving compute_patterns off the request path (pipeline, per night key) removes the 2x30 s timeouts from /insights/patterns.

### J-09 — Insights 'Weather and moon' presents noise as findings and counts dead-camera nights as quiet nights

*medium · confirmed · data-correctness · effort M* — `backend/app/forecasting/patterns.py`, `frontend/src/components/WeatherPatterns.tsx`, `backend/app/api/routes_insights.py`

- **What the hunter sees:** Hunters read 'More sightings when the wind is light' or 'on cool nights' as fact and plan sits on it, when the data supports no such claim.
- **Evidence:** _scope_drivers (patterns.py:206-212) fills 0 for every night without detections and ignores the camera_nights exposure table. So weeks when a camera was out of credits (the SPYPOINT free plan is 100 photos/month, docs/09-handoff.md:40) or offline read as empty nights. _driver (patterns.py:153-199) keeps any driver above MIN_EFFECT 15%. WeatherPatterns.tsx:145-149 then turns every surviving driver with a single top bucket into 'More sightings …'. PROVEN by a null simulation using the app's _scope_drivers plus the frontend's compare() logic, on counts independent of every covariate: at least one finding in 98% of runs at 30 and at 60 nights, and 88% at 120 nights. The redesign removed this surface (docs/redesign/03 §2); commit b81f444 brought it back as headline findings. It still runs on the request path, with 30 s Open-Meteo calls.
- **Verifier:** Reproduced a null simulation with the real _scope_drivers plus a port of WeatherPatterns compare(), on counts independent of every covariate. At least one 'More sightings …' sentence appeared in 98.7% of runs at 30 and at 60 nights and 90% at 120 nights. patterns.py:213 also imputes 0 for every night without detections and ignores CameraNight exposure. model.py:319-325 already documents this failure and removed the drivers from the verdict, but Insights still prints them as findings. Downgraded to medium because it misleads on Insights, not the Tonight decision.
- **Fix:** Minimal version: stop printing headline sentences unless a driver beats a permutation null (block-shuffled, ≥95th percentile), and otherwise say 'No weather pattern stands out yet.' Restrict nights to CONFIRMED/PRESUMED_UP exposure and count visits. Compute in the nightly job and cache it, not on the request path.


## 12. Access and security

### D-05 — Removing a guest who reserved a stand or added a camera login fails with a 500, so their access can't be revoked

*high · confirmed · bug · effort S* — `backend/app/api/routes_users.py`, `backend/app/models.py`, `frontend/src/pages/Admin.tsx`

- **What the hunter sees:** The admin cannot remove any guest who has ever reserved a stand or connected their cameras, which is nearly every active guest. The guest keeps full access.
- **Evidence:** routes_users.py:69 runs db.delete(u). sits.user_id (models.py:444), camera_accounts.owner_user_id (models.py:60, migration 0006) and zones.created_by (models.py:178, migration 0010) reference users with no ON DELETE, so Postgres raises an FK violation and the route 500s. PROVEN (scratchpad/D/test_area_d.py). Admin DELETE /api/users/{guest} returned 500 'Internal Server Error' both for a guest owning a CameraAccount and for a guest with a Sit. Settings then shows only 'Something went wrong (500)' (Admin.tsx:165-168 via api.ts:47).
- **Verifier:** Reproduced: DELETE /api/users/{guest} returns 500 for a guest with a CameraAccount and for a guest with a Sit. The FKs have no ON DELETE: models.py:60/178/444, migrations 0006:25, 0009:43 and 0010:32. Sits are never deleted (claim_stand inserts at routes_stands.py:277 and cancel is only an outcome value), so any guest who ever claimed a stand can't be removed.
- **Fix:** In delete_user, set sits.user_id, zones.created_by and camera_accounts.owner_user_id to NULL before db.delete(u). Add an additive migration with ON DELETE SET NULL on those three FKs. Wrap the commit in an IntegrityError handler that returns 409 with readable text. Decide explicitly whether a removed guest's camera account keeps syncing or is deactivated; setting active=False is the safer default.

### D-06 — No throttling on the public login, and the admin email is pre-filled on the sign-in page

*high · confirmed · security · effort S* — `backend/app/api/routes_auth.py`, `frontend/src/pages/Login.tsx`, `backend/app/core/security.py`, `.env.example`

- **What the hunter sees:** Anyone on the internet can guess the admin password at full speed, and one script can starve the estate server of memory.
- **Evidence:** routes_auth.py:16-22 has no attempt counter, lockout or delay, and main.py has no rate-limit middleware. Production is public at https://gamesense.daa-ops.com (docs/09-handoff.md). Login.tsx:8 pre-fills 'admin@gamesense.local', so every visitor learns the admin username. .env.example and README ship ADMIN_PASSWORD=changeme. Each attempt also runs Argon2 with defaults (64 MiB, t=3), so a parallel flood across the 40-thread pool can push roughly 2.5 GB of RAM onto the Db01 VM, which also runs Postgres and MS SQL. PROVEN (scratchpad/D/test_area_d.py::test_login_has_no_throttle): 40 consecutive wrong passwords all returned 401 (no 429), and the right password still worked afterwards.
- **Verifier:** Reproduced: 40 wrong passwords all returned 401 and the right one still worked afterwards. routes_auth.py:16-22 and main.py have no throttle. Login.tsx:8 pre-fills 'admin@gamesense.local', and docs/09-handoff.md:32 confirms that is the real production admin login on the public URL. argon2-cffi defaults (64 MiB per hash) on a sync route run in the 40-thread pool.
- **Fix:** Production sits behind cloudflared, so request.client.host is the tunnel's local address. A naive per-IP limit would therefore throttle everyone together. Key the IP part on CF-Connecting-IP, trusted only when the peer is the tunnel. For per-email limits use progressive delay rather than a hard lockout, so an attacker can't lock the admin out. Add a Cloudflare rate-limit rule on /api/auth/login as the zero-code first step. Replace the pre-fill with the last email used on this device (localStorage).

### H-01 — Removing a guest who ever claimed a stand, drew a zone or linked a camera login crashes with a 500, so that guest can never be removed

*high · confirmed · bug · effort S* — `backend/app/models.py`, `backend/app/api/routes_users.py`

- **What the hunter sees:** At the end of the season, or when a guest falls out, the owner taps Remove and gets 'Something went wrong (500)'. The guest keeps full access, including 30-day tokens that refresh every time they log in.
- **Evidence:** Three foreign keys to users have no ondelete rule: camera_accounts.owner_user_id (models.py:60), zones.created_by (models.py:178) and sits.user_id (models.py:444). DELETE /api/users/{id} just calls db.delete(u) (routes_users.py:69). PROVEN on the test Postgres using scratch/H/del_user.py. I created three member users: one with a Sit, one with a Zone, one with a CameraAccount. Then I called DELETE /api/users/{id} as admin. All three calls returned 500 Internal Server Error (ForeignKeyViolation). There is no endpoint to disable a user or change their role (routes_users.py has only GET, POST and DELETE), so the admin has no other way to cut the guest off.
- **Verifier:** Reproduced this on a database built with alembic upgrade head (verify-H/del_user.py). DELETE /api/users/{id} returned 500 for a member with a Sit, one with a Zone and one with a CameraAccount, and 200 for a plain member. The FKs have no ondelete (models.py:60,178,444) and delete_user just calls db.delete(u) (routes_users.py:69). Members can create all three through get_current_user routes (routes_stands.py:279, routes_zones.py:83, routes_camera_accounts.py:163).
- **Fix:** Minimal fix with no migration: in delete_user, before db.delete(u), run UPDATE sits SET user_id=NULL, UPDATE zones SET created_by=NULL, and for camera_accounts either set owner_user_id=NULL or set active=false. Choose deliberately, because SET NULL keeps the removed guest's SPYPOINT/UBox login syncing. If you also add migration 0017 for ON DELETE SET NULL, look up the FK names at runtime. Production tables created by 0006/0010 raw SQL have Postgres default names (camera_accounts_owner_user_id_fkey, zones_created_by_fkey), while fresh installs have the convention names (fk_..._users), so a hard-coded drop_constraint will fail on one of them.

### B-08 — Any signed-in user, including 'viewer', can delete or redraw bedding, move cameras and start the terrain download; an out-of-range camera position blanks the map for everyone

*medium · confirmed · security · effort S* — `backend/app/api/routes_zones.py`, `backend/app/api/routes_cameras.py`, `frontend/src/pages/Map.tsx`

- **What the hunter sees:** A guest account can wipe the bedding every wind call depends on, or move cameras, from any HTTP client. One bad coordinate bricks the map for the whole estate.
- **Evidence:** routes_zones.py:71-116 (create/patch/delete zone) and :192-193 (terrain refresh) depend only on get_current_user. routes_cameras.py:235-248 PUT /cameras/{id}/location also uses get_current_user, and LocationBody (:230-232) has no range check. Stand writes are admin-only (routes_stands.py:133,150,164), and the UI only shows edit controls to admins. PROVEN (scratchpad/B/pyt/test_map_b.py): a role='viewer' token gets 204 on DELETE /zones/{admin's zone}, 201 on POST /zones, 200 on POST /terrain/refresh, and 200 on PUT location with lat=1000. POST /stands returns 403 for contrast. Then PROVEN in Playwright (s_badlat.cjs): a camera with lat 1000 makes MapLibre throw 'Invalid LngLat latitude value' in the marker effect, and #root goes empty (whole app blank on /map for every user).
- **Verifier:** I re-ran scratch test_map_b.py. A viewer token gets 204 on DELETE /zones, 201 on POST /zones, 200 on POST /terrain/refresh and 200 on PUT location with lat=1000, while POST /stands returns 403. These routes depend only on get_current_user (routes_zones.py:73,94,110,193; routes_cameras.py:238). s_badlat.cjs shows 'Invalid LngLat latitude value' and #root emptied. Downgraded to medium because it needs a signed-in user deliberately using a raw HTTP client; the UI never sends out-of-range coordinates.
- **Fix:** As proposed: use get_current_admin (or admin|member for camera placement) and range-bounded, finite Field constraints on LocationBody, StandIn and StandPatch. In the frontend, filter invalid coordinates in BOTH the marker effect and fitEstate (layers.ts:34), because fitBounds also throws on lat>90.

### C-09 — Members see buttons that only admins can use (the sync button, and merge, confirm and look-for-repeats on Animals)

*medium · confirmed · ux · effort S* — `frontend/src/pages/Cameras.tsx`, `frontend/src/pages/Animals.tsx`, `backend/app/api/routes_cameras.py`, `backend/app/api/routes_animals.py`

- **What the hunter sees:** A member hunter taps the main button on Cameras and gets a red error. Animals curation fails for them in the same way.
- **Evidence:** POST /cameras/sync requires get_current_admin (routes_cameras.py:174). Animals PATCH, merge, confirm and recompute are admin-only too (routes_animals.py:155-267). The UI shows all of them to every role: Cameras.tsx:374 and Animals.tsx:286-299. The empty state even says 'tap Check for new photos' (Cameras.tsx:392). PROVEN with a scratch pytest (test_member_gets_403_on_animal_rename_and_sync): a member gets 403 'Admin privileges required' for both. On Cameras this becomes a red '! Could not start the check. Admin privileges required'.
- **Verifier:** The auditor's pytest passes: a member gets 403 'Admin privileges required' on PATCH /animals/{id} and POST /cameras/sync. routes_cameras.py:174 uses get_current_admin, but Cameras.tsx:374 renders the sync button with no role check, and Animals.tsx:286-299 shows recompute, merge and confirm to everyone. Cameras.tsx:362 turns that into a red 'Could not start the check. Admin privileges required'.
- **Fix:** Either allow members to trigger /cameras/sync (the pipeline lock already rate-limits it), or return can_sync and can_curate the same way list_cameras returns can_rename (routes_cameras.py:114) and hide or disable the controls with a one-line reason. Prefer letting members sync, since it's harmless.

### C-19 — Photo URLs still work for deleted users for up to 30 days, and the token sits in every image URL

*medium · confirmed · security · effort M* — `backend/app/api/routes_images.py`, `frontend/src/api.ts`, `backend/app/core/config.py`

- **What the hunter sees:** A removed guest hunter, or anyone who gets a copied photo link or a server log, can keep downloading estate photos, which include people, for a month.
- **Evidence:** image_file (routes_images.py:43-50) only calls decode_token(raw) and never checks that the user still exists. Tokens last 30 days (config.py access_token_expire_minutes=43200), and imageUrl puts them in ?token= on every <img> and download link (api.ts:19-23). uvicorn runs with its access log on (serve.py log_level='info'), so every photo request writes the bearer token to the log. PROVEN with a scratch pytest (test_deleted_user_token_still_opens_photos): after deleting the user, /api/photos returns 401 but /api/images/{id}/file?token=… returns 200.
- **Verifier:** The auditor's pytest passes: once the user is deleted, /api/photos gives 401 but /images/{id}/file?token= gives 200. image_file (routes_images.py:49-50) only calls decode_token and never does the db.get(User) that get_current_user does (deps.py:33-35). Tokens last 30 days (config.py:17). uvicorn's access log includes the query string (h11_impl.py:477 get_path_with_query_string), and serve.py leaves the access log on, so the bearer token is written on every photo request.
- **Fix:** In image_file, resolve the user the same way get_current_user does (sub → db.get(User)) and reject missing users. Better: have the API issue short-lived, image-scoped signed URLs (HMAC of image_id plus exp, about 1h) or a separate 'media' JWT with a short exp, so the 30-day session token never appears in a URL. Filter `token=` out of access logs.

### D-07 — Sessions can't be ended: a password change keeps old tokens valid for 30 days, and a removed person's token still opens photos

*medium · confirmed · security · effort S* — `backend/app/api/routes_auth.py`, `backend/app/api/routes_images.py`, `backend/app/core/security.py`

- **What the hunter sees:** A hunter who loses their phone and changes their password has not locked the finder out. A guest removed at the end of the season can keep pulling trail-camera photos (including photos of people) for up to 30 days.
- **Evidence:** change_password (routes_auth.py:35-47) only rehashes. Tokens carry no password or version claim, and exp is 30 days (config.py:17). routes_images.py:50 only calls decode_token(raw) and never checks that the subject user still exists. PROVEN (scratchpad/D/test_area_d.py). The token issued before a password change still got 200 on /auth/me. After the admin removed a guest, that guest's token got 401 on /auth/me but 200 on /api/images/{id}/file.
- **Verifier:** Reproduced: after change_password (routes_auth.py:35-47 only rehashes), the old token still got 200 on /auth/me. For a removed guest, /auth/me returned 401 but /api/images/{id}/file?token= returned 200, because image_file (routes_images.py:50) only calls decode_token and never loads the user. In practice D-05 blocks removal of most guests today, which is worse.
- **Fix:** Factor a user_from_token(raw, db) helper out of deps.get_current_user and use it in image_file too, so missing users get 401. Add users.password_changed_at (additive migration) and reject tokens with iat < password_changed_at. Set it in change_password, and later from an admin 'sign out everywhere' action.

### D-12 — Members see admin-only switches that snap back silently, a version that never loads, and a 'Check for updates' button that does nothing

*medium · confirmed · ux · effort S* — `frontend/src/pages/Admin.tsx`, `backend/app/api/routes_species.py`, `backend/app/api/routes_admin.py`

- **What the hunter sees:** A guest thinks they switched boar off, or that updates are broken. The switch flips back with no explanation, which reads as a bug.
- **Evidence:** PATCH /species (routes_species.py:138) and every /admin/* route require an admin, and the server answers 403 to members (PROVEN in scratchpad/D/test_area_d.py::test_member_sees_admin_switches_but_server_refuses). Admin.tsx still renders the species toggles and Hide buttons (302-334), the App version section (506-545) and Photo labelling (547-558) to everyone. Failures are swallowed at Admin.tsx:141, 249-252 and 273-274. PROVEN UI (scratchpad/D/pw/settings.cjs, member role): 'Wild boar in the advice' went from true to false on tap and back to true with no message. The section shows 'GameSense v…' permanently, and tapping 'Check for updates' changes nothing.
- **Verifier:** Backend 403s reproduced for a member on PATCH /species and every /admin route. The settings.cjs run showed the switch going true→false→true with no explanation, 'GameSense v…' staying permanently, and 'Check for updates' doing nothing (errors swallowed at Admin.tsx:141, 249-252 and 273-274). One detail is overstated: against the real backend, 'Photo labelling' does show 'Admin privileges required' via setSexMsg (Admin.tsx:134-135). The harness's 'Started.' came from a mock that returned 200.
- **Fix:** Gate on me?.role === 'admin' the same way 'Who can sign in' already does (Admin.tsx:456). Members see the species list read-only with 'Only an admin can change this'. App version, Photo labelling and System are hidden for them.

### E-09 — The main 'Check for new photos' button is admin-only but shown to everyone, so members just get a red error

*medium · confirmed · ux · effort S* — `backend/app/api/routes_cameras.py:173-174`, `frontend/src/pages/Cameras.tsx:329-374`, `frontend/src/pages/Cameras.tsx:392`

- **What the hunter sees:** Most hunters are members. The most prominent control on the Cameras page shows them a jargon error.
- **Evidence:** PROVEN with a Playwright run (scratchpad/E/sync-ui.cjs, mocked API, 390 px viewport, the built app served from scratch): for a member, POST /cameras/sync returns 403 and the status line reads '! Could not start the check. Admin privileges required'. The button renders for every role, and the empty state tells everyone to 'tap Check for new photos'.
- **Verifier:** trigger_sync depends on get_current_admin (routes_cameras.py:173-174, deps.py:39-42), and Cameras.tsx:370-374 renders the button with no role check. The auditor's Playwright screenshot shows a member getting '! Could not start the check. Admin privileges required'. The empty-state and per-camera copy also tell everyone to 'Tap Check for new photos'.
- **Fix:** Let admin and member trigger the sync: it is lock-guarded and cheap when nothing is new. For viewers, hide the button and show 'New photos arrive every 15 minutes'. Also change the per-camera 'Tap Check for new photos' copy for roles that can't.

### H-13 — 30-day session tokens end up in the access log, and a removed user's token still opens photos

*medium · confirmed · security · effort M* — `backend/serve.py`, `backend/app/api/routes_images.py`, `backend/app/core/security.py`

- **What the hunter sees:** Anyone who can read the server or tunnel logs gets working 30-day logins. A guest removed (once H-01 is fixed) can keep pulling estate photos for up to 30 days.
- **Evidence:** Every photo <img> sends ?token=<JWT> (frontend api.ts imageUrl). uvicorn's access log records the path WITH the query string (uvicorn/protocols/utils.py get_path_with_query_string, checked in the installed package), and serve.py:26-30 runs at log_level='info', so access logging is on. Cloudflare sees the same URLs. The image route only checks the signature (routes_images.py:49-52, decode_token) and never checks that the user still exists. security.py has no token version, so neither a password change nor removing the user revokes tokens.
- **Verifier:** image_file only checks the JWT signature (routes_images.py:49-52) and never loads the user, unlike deps.get_current_user. Every photo URL carries the full-scope 30-day API token (api.ts imageUrl). uvicorn's access log includes the query string (uvicorn/protocols/utils.py:52-56, h11_impl.py:477), and serve.py uses log_level=info. A likelier leak than server logs: a hunter long-presses a photo, copies its address and shares it, which hands over a working 30-day login to the whole API.
- **Fix:** Mint a separate short-lived, image-only token (for example scope='img', about 12 h expiry) from an authenticated endpoint. Accept only that scope in ?token=, and reject full-scope tokens in query strings. In image_file, confirm the subject user still exists. Add a filter on uvicorn.access that strips query strings.

### H-14 — The server starts happily with the published default secrets on a public URL

*medium · plausible · security · effort S* — `backend/app/core/config.py`, `.env.example`, `start.bat`, `backend/app/core/crypto.py`

- **What the hunter sees:** If either default survives on Db01, anyone can sign in as admin or forge sessions, and can decrypt guests' camera passwords from a database dump.
- **Evidence:** config.py:15 defaults jwt_secret='dev-secret-change-me' and config.py:21 defaults admin_password='changeme'. .env.example:13 and :18 ship 'dev-secret-change-me-please' and 'changeme', and start.bat:14-17 copies .env.example into .env automatically. Nothing refuses to start with these values. The same secret also derives the Fernet key protecting guests' SPYPOINT and UBox passwords (crypto.py:17-19). The app is public at gamesense.daa-ops.com (09-handoff.md:151), and /auth/login has no throttling (routes_auth.py:16-22). I cannot see whether Db01's .env changed these values.
- **Verifier:** Confirmed that the defaults exist (config.py:15,21; .env.example:15,20), that start.bat:14-17 copies .env.example into .env, that nothing refuses to start with them, and that /auth/login has no throttling (routes_auth.py:16-22). Whether Db01's .env still has them cannot be seen, so exploitability is unproven.
- **Fix:** At startup, refuse to run when jwt_secret is a known default or shorter than 32 characters. Important: crypto.py:18 derives the Fernet key from JWT_SECRET, so rotating the secret on Db01 makes every stored guest SPYPOINT/UBox password undecryptable. Guest syncs then fail with only a log line (sync.py:39-40). Ship a re-encrypt step (decrypt with the old secret, encrypt with the new) or a separate CREDENTIALS_KEY that falls back to the old derivation before telling the owner to rotate.

### I-12 — Removing a person who has ever reserved a stand fails with a 500

*medium · confirmed · bug · effort S* — `backend/app/api/routes_users.py`, `backend/app/models.py`

- **What the hunter sees:** The admin can't remove a guest hunter once they have used the app, and gets no explanation.
- **Evidence:** routes_users.py:69 db.delete(u). Sit.user_id (models.py:444), Zone.created_by and CameraAccount.owner_user_id (line 60) reference users.id with no ondelete. Proven: DELETE /api/users/{member} (member had cancelled sits) returned 500. backend.log shows ForeignKeyViolation 'fk_sits_user_id_users'. Settings shows 'Something went wrong (500)'.
- **Verifier:** Reproduced: DELETE /api/users/<member with sits> returned 500, and the log shows ForeignKeyViolation fk_sits_user_id_users. sits.user_id, zones.created_by and camera_accounts.owner_user_id have no ondelete (models.py:60, 178, 444), and User has no ORM relationships that would nullify them.
- **Fix:** Prefer a soft delete (users.disabled checked in get_current_user and login), because SET NULL erases who sat, which the sit ground truth may need. If hard delete stays, add SET NULL through a migration and map IntegrityError to a plain-words 409.

### I-15 — Members see Settings switches that silently snap back (admin-only on the server)

*medium · confirmed · ux · effort S* — `frontend/src/pages/Admin.tsx`, `backend/app/api/routes_species.py`

- **What the hunter sees:** To a member the buttons appear to do nothing, which is a classic 'app is buggy' moment.
- **Evidence:** The 'Animals in the advice' switches and 'Hide' buttons are shown to every role (Admin.tsx:296-350), but PATCH /species is admin-only (routes_species.py:138). toggleSpecies and hideSpecies catch the error and revert with no message (Admin.tsx:249-252, 263-265). Proven with I/f_settings.cjs as member: the Fox switch gets PATCH 403, aria-checked stays true, no alert appears; Hide does the same. The member also sees 'App version' and 'Photo labelling'. 'Check for updates' swallows its 403 (lines 269-277), so the button does nothing.
- **Verifier:** The 'Animals in the advice' switches and Hide buttons render for every role (Admin.tsx:296-350), but PATCH /species requires get_current_admin (routes_species.py:138). The catch blocks silently revert (249-252, 262-265). The App version section is ungated (505) while /admin/version is admin-only, and checkUpdates swallows the 403 (269-277).
- **Fix:** The proposed fix is right. Gate these sections the way 'Who can sign in' is gated with me?.role === 'admin' (line 456), or render them read-only with one line saying why.

### C-28 — Camera location accepts any role, any estate and impossible coordinates, and any user can hide photos for everyone

*low · confirmed · security · effort S* — `backend/app/api/routes_cameras.py`, `backend/app/api/routes_images.py`

- **What the hunter sees:** A guest account can move camera pins off the map, which breaks map bounds and wind and scent geometry, or hide photos for everyone.
- **Evidence:** set_location (routes_cameras.py:230-248) uses get_current_user, has no estate check, and LocationBody has no bounds. PROVEN with a scratch pytest (test_viewer_can_move_camera): a viewer PUTs lat=999, lng=-999 and gets 200. flag_image (routes_images.py:74-84) also lets any role, including viewer, hide a photo from every list (proven in test_flagged_empty_still_counted_and_shown_in_animals: the viewer flag returns 200), while rename is limited to admin and member.
- **Verifier:** The auditor's pytest passes: a viewer PUTs lat=999, lng=-999 and gets 200. set_location (routes_cameras.py:235-248) uses get_current_user, and LocationBody (230-232) has no bounds. flag_image (routes_images.py:73-87) accepts any role. The estate-scoping part is moot for this single-estate install, so low.
- **Fix:** Add Field(ge=-90, le=90) and Field(ge=-180, le=180), and require role in {admin, member} on both routes to match rename_camera. Estate scoping is optional given one estate.

### D-08 — The full 30-day session token is written into every photo URL, so it lands in server logs and saved links

*low · confirmed · security · effort M* — `frontend/src/api.ts`, `backend/app/api/routes_images.py`, `backend/serve.py`

- **What the hunter sees:** Anyone who can read the server's log files, or receives a shared photo link, gets a month of full access to the estate as that hunter.
- **Evidence:** imageUrl (api.ts:19-23) appends ?token=<bearer JWT> to every <img> src and download link. serve.py runs uvicorn at log_level='info' with the access log on by default, and that log records the path plus query string of every photo request ('GET /api/images/…/file?token=eyJ…'). The same goes for the Cloudflare tunnel logs, and for browser history or share-sheet links when a hunter long-presses and shares a photo. routes_images.py:43-45 acknowledges this trade-off. Combined with D-07 the leaked token cannot be revoked. Not run live; the code path is unambiguous.
- **Verifier:** The mechanism is real. imageUrl (api.ts:19-23) puts the full session JWT in ?token=. uvicorn's access log is on by default (serve.py:25-30 doesn't disable it) and logs get_path_with_query_string (uvicorn h11_impl.py:473-477). Downgraded because the realistic leak paths are narrow: the logs are operator-only, the lightbox shares files rather than URLs (PhotoLightbox.tsx:265-270), and same-origin img requests send no cross-site Referer. The code comment at routes_images.py:43-45 already accepts this trade-off.
- **Fix:** Interim: add a logging.Filter on 'uvicorn.access' that strips token= values (a few lines). Longer term: short-lived HMAC image signatures instead of the session JWT, as proposed.

### D-11 — Sessions end on a fixed date 30 days after sign-in, even for a hunter using the app daily

*low · confirmed · ux · effort S* — `backend/app/core/security.py`, `backend/app/core/config.py`, `frontend/src/api.ts`

- **What the hunter sees:** Once a month, possibly at the stand at dusk with gloves on, the app throws the hunter out to a password prompt.
- **Evidence:** create_access_token (security.py:24-33) sets exp = login + 30 days (config.py:17). There is no refresh endpoint and the frontend never renews the token. RequireAuth only checks that a token is present (App.tsx:27), so the expiry shows up as a 401 mid-use, followed by a full page reload to /login (api.ts:37-41) that discards anything unsaved (a sit report, a stand being drawn on Map). Not run live; the config and code are explicit.
- **Verifier:** Confirmed from the code: create_access_token (security.py:24-33) sets a fixed exp of 30 days (config.py:17). There is no refresh route in routes_auth.py and no renewal in api.ts. On a 401, api.ts:37-41 does a full-page window.location.assign, which discards unsaved state. Downgraded because this is a deliberate design ('a field app shouldn't log you out weekly') and hits about once a month.
- **Fix:** Sliding renewal as proposed: return a fresh token in an X-Refreshed-Token header when the current one is over ~7 days old, and have api() store it. Keep the D-07 revocation check so renewal can't outlive a password change.

### D-23 — Login is case-sensitive, but new logins are stored lowercased

*low · confirmed · bug · effort S* — `backend/app/api/routes_auth.py`, `backend/app/api/routes_users.py`

- **What the hunter sees:** A guest types their email exactly as the admin gave it and is told the password is wrong.
- **Evidence:** create_user lowercases (routes_users.py:38), and login compares exactly (routes_auth.py:18). PROVEN (scratchpad/D/test_area_d.py::test_login_email_is_case_sensitive_but_creation_lowercases): an admin created 'Marco@Finca.es' (stored as marco@finca.es), and signing in with 'Marco@Finca.es' as it was handed out returned 401 'Wrong email or password'.
- **Verifier:** Reproduced: create_user lowercases the email (routes_users.py:38), and login matches exactly (routes_auth.py:18). 'Marco@Finca.es' returned 401 and so did a trailing space. LoginRequest.email is a plain str (schemas.py:8), with no normalisation.
- **Fix:** Normalise with body.email.strip().lower() in login, and compare against func.lower(User.email) so any mixed-case rows created before this fix still match.

### H-23 — The Docker stack exposes Postgres and Redis on all interfaces with default credentials and does not come back after a reboot

*low · confirmed · security · effort S* — `compose.yaml`, `backend/entrypoint.sh`, `start.bat`, `docs/07-deployment.md`

- **What the hunter sees:** Anyone following the documented server path gets a database open to the LAN or internet, and the app stays down after every reboot.
- **Evidence:** compose.yaml:30-31 and :40-41 publish 5432 and 6379 on 0.0.0.0, with DB password default 'gamesense' (compose.yaml:8, 26) and a Redis with no password. No service has a restart: policy, so nothing restarts after a host reboot. The API runs 'uvicorn --reload' (entrypoint.sh:18). docs/07-deployment.md:31 and 09-pwa-deploy.md:30 still recommend 'the same compose.yaml' for a server. Production is native Windows (09-handoff.md), so this only bites if someone follows the docs.
- **Verifier:** compose.yaml:30-31 and 40-41 publish db and redis on all interfaces, with a fallback password of 'gamesense' and no Redis auth. No service has a restart policy, and entrypoint.sh:18 uses --reload. This is the dev stack, and production is native Windows, so it only matters if someone follows docs 07/09-pwa-deploy to build a server.
- **Fix:** Bind the ports to 127.0.0.1, add restart: unless-stopped, and add a comment at the top of compose.yaml and in docs 07/09-pwa-deploy saying it is dev-only.

### I-13 — A removed person's session still opens every trail-camera photo for up to 30 days

*low · confirmed · security · effort S* — `backend/app/api/routes_images.py`, `backend/app/core/config.py`

- **What the hunter sees:** A guest who has been removed can keep pulling photos, which may show people, for a month.
- **Evidence:** routes_images.py:44-51 only checks the JWT signature and never looks the user up. Tokens last 43200 min (config.py). Proven: log in as viewer, then admin removes the viewer. Viewer /api/auth/me returns 401, but GET /api/images/{id}/file?token=<viewer token> returns 200 image/jpeg. Changing a password doesn't revoke existing tokens either.
- **Verifier:** Reproduced: a removed member's token got 401 on /auth/me but 200 image/jpeg on /images/{id}/file?token=, because image_file only calls decode_token (routes_images.py:46-50). Downgraded because a removed user cannot list photos any more (the feed returns 401) and their push subscriptions cascade-delete. They can only re-open image UUIDs they already had.
- **Fix:** The proposed fix is right: look the user up after decode (reuse get_current_user's logic). A token_version claim is the longer-term fix for password changes.

### K-12 — The full API map (/docs, /openapi.json) is public on the internet-facing URL

*low · confirmed · security · effort S* — `backend/app/main.py`

- **What the hunter sees:** Anyone who finds gamesense.daa-ops.com gets a ready-made list of every admin and camera-login endpoint to probe, which makes D-06's unthrottled login easier to attack.
- **Evidence:** main.py:30 creates FastAPI() with the default docs_url, redoc_url and openapi_url. These are registered before the SPA catch-all and need no auth. PROVEN: against the real app, curl /docs returns 200, and /openapi.json returns 60 paths (including /api/users, /api/camera-accounts and /api/admin/*) without a token. D-area listed the unauthenticated API routes but not the docs endpoints.
- **Verifier:** FastAPI() at main.py:30 uses the default docs URLs. A TestClient with no token gets 200 for /docs and 59 paths from /openapi.json, including /api/admin/* and /api/camera-accounts. The leak adds little, though: the public bundle index-*.js already contains '/admin/status', '/admin/version' and '/camera-accounts'. It only adds request and response schemas.
- **Fix:** FastAPI(docs_url=None, redoc_url=None, openapi_url=None) unless an ENABLE_API_DOCS env flag is set.


## 13. Photos and Animals fixes

### C-10 — A name given to an animal is wiped the next time anyone taps "Look for repeats"

*high · confirmed · data-correctness · effort S* — `backend/app/api/routes_animals.py`, `backend/app/ai/reid.py`, `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** The owner names the big boar 'Cyclops'. A few days later someone taps 'Look for repeats' and the name disappears without a word.
- **Evidence:** PATCH /animals/{id} (routes_animals.py:155-173) only sets label. It doesn't mark any DetectionIndividual as confirmed_by_user. reid.cluster() (reid.py:84-103) keeps only individuals with at least one confirmed sighting and deletes every other Individual (line 100), recreating them as '<Species> #n'. PROVEN with a scratch pytest (test_named_animal_lost_on_recompute): rename 'Wild Boar #1' to 'Cyclops', and /animals shows ['Cyclops']. After cluster(db), /animals is []. The name is gone.
- **Verifier:** The auditor's pytest passes: after rename to 'Cyclops', cluster() leaves /animals empty. patch_animal (routes_animals.py:164-165) never sets confirmed_by_user, and reid.cluster deletes every Individual with no confirmed sighting (reid.py:94-103). The UI's rename (Animals.tsx:146-151) doesn't call confirm either. The loss is deterministic on the next 'Look for repeats', not a race.
- **Fix:** In patch_animal, when label, status or notes change, run update(DetectionIndividual).where(individual_id==id).values(confirmed_by_user=True), because naming asserts identity. Alternatively add Individual.user_named and include it in confirmed_ids inside cluster().

### C-01 — "Show older photos" gets stuck on "Loading…" for good if you change a chip (or come back to the app) while an older page is loading

*medium · confirmed · bug · effort S* — `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** On a weak signal a hunter scrolls down, then taps an animal chip, or locks the phone and comes back. The feed stops at 60 photos with a greyed-out "Loading…" button that never changes, and older photos can't be reached until the page is reloaded.
- **Evidence:** Photos.tsx:107-119: loadMore captures id=request.current and only clears the flag in `.finally(() => { if (id === request.current) setLoadingMore(false) })` (line 118). load() (81-92) bumps request.current but never resets loadingMore. So when a newer load() replaces an older-page request, loadingMore stays true. After that, loadMore returns early at line 108 and the IntersectionObserver (122-128) does nothing. PROVEN with Playwright against the built app and a mocked API (scratchpad/C/pw.cjs): scroll to the bottom (older page takes 2.5s), tap the 'Red deer' chip, then wait. Result: button text="Loading…", disabled=true, 0 older-page requests for the new filter even after scrolling and tapping the button.
- **Verifier:** Re-ran the auditor's Playwright scenario against a fresh build of current source. Result: button text "Loading…", disabled, and 0 older-page requests for the new filter even after tapping. load() (Photos.tsx:81-92) bumps request.current but never resets loadingMore, and loadMore's finally (line 118) only clears the flag when the ids match. Downgraded because it needs an older page in flight when the chip is tapped, and leaving the Photos page remounts it and recovers; a full reload is not required.
- **Fix:** Keep the in-flight guard in a ref (inFlight.current = id). Clear it in finally whenever inFlight.current === id, and reset it (plus setLoadingMore(false)) at the top of load(). Then a stale page can neither hold the flag nor append to the new filter.

### C-03 — Feed paging skips photos that share a timestamp (Suntek FTP bursts are minute-precision)

*medium · confirmed · data-correctness · effort S* — `backend/app/api/routes_photos.py`, `backend/app/ingestion/ftp_import.py`, `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** Photos silently vanish from the feed at page boundaries. They're usually burst frames, where the second or third frame is often the one that shows the tusks or antlers.
- **Evidence:** routes_photos.py:84-86 filters `Image.captured_at < before` and sorts by (captured_at desc, id desc), but next_before (line 125) is only rows[-1].captured_at. Every photo tied with the last row of a page is dropped. ftp_import.py:142-147: Suntek FTP filenames PICT_YYYYMMDD_HHMM set seconds to 00, so a 3-shot burst shares one captured_at exactly. PROVEN with a scratch pytest against the test DB (scratchpad/C/test_area_c.py::test_feed_pagination_drops_photos_sharing_a_timestamp): 58 distinct photos plus a 4-frame burst at one minute gives 62 photos, but paging with limit=60 returns only 60 unique. 2 burst frames can never be reached.
- **Verifier:** The auditor's pytest passes here: 62 photos, 60 unique reachable. routes_photos.py:85 filters captured_at < before, and next_before (line 125) is only rows[-1].captured_at, while the sort is (captured_at, id). ftp_import.py sets seconds to 00 only when EXIF DateTimeOriginal is missing, and a tie must also land on a page boundary. Photos are also still reachable from the Cameras strip and the species gallery, so downgraded from high.
- **Fix:** Add an optional before_id query param (backward compatible, since before is typed datetime) and return next_before_id. When both are given, filter tuple_(Image.captured_at, Image.id) < tuple_(before, before_id); otherwise keep the current behaviour for cached clients.

### C-04 — Every grid and strip downloads the full-size original; there are no thumbnails, no Cache-Control and no prefetch in the lightbox

*medium · confirmed · perf · effort M* — `backend/app/api/routes_images.py`, `frontend/src/pages/Photos.tsx`, `frontend/src/pages/Cameras.tsx`, `frontend/src/pages/Animals.tsx`, `frontend/src/components/PhotoLightbox.tsx`

- **What the hunter sees:** On the estate's weak mobile signal the Photos and Cameras pages load slowly, burn data, and each swipe in the viewer pauses on 'Loading photo…'.
- **Evidence:** The only image route is /api/images/{id}/file (routes_images.py:33-66), which returns FileResponse(image.original_path) with no resize and no Cache-Control. It feeds 150x118 tiles (Photos.tsx:200, photos.css .photos-tile img 118px), 100x74 camera thumbs (Cameras.tsx:437), 56px species thumbs and gallery tiles (Animals.tsx:225, 328, 410). Nothing else in the backend makes thumbnails (grep 'thumb'). Originals can be up to 20MB (ftp_import MAX_BYTES), and Suntek and UBox full frames are multi-MB. The lightbox (PhotoLightbox.tsx:335) doesn't preload the next or previous photo, so every swipe shows 'Loading photo…'. Proven from code. Byte sizes were not measured.
- **Verifier:** routes_images.py:33-66 only serves FileResponse(original_path), with no resize and no Cache-Control. Image.thumbnail_path exists in models.py:274 but nothing writes or reads it. sw.js:84-86 passes /api/images straight through, and the lightbox doesn't preload neighbours. Downgraded from high: sizes were not measured, SPYPOINT sync pulls the non-HD 'large' variant (spypoint.py:305,339), tiles use loading=lazy, and FileResponse's ETag/Last-Modified allow heuristic caching.
- **Fix:** Generate a ~320px thumb and a ~1280px screen variant lazily with Pillow and store the thumb path in the existing Image.thumbnail_path column. Add ?size=thumb|screen and set Cache-Control: private, max-age=31536000, immutable on those variants. Note the ?token= in the URL changes on re-login, so cache keys churn. Preload photos[idx±1] in the lightbox.

### C-12 — Renaming an animal fails silently (unhandled promise, and the old name stays)

*medium · confirmed · bug · effort S* — `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** The hunter types a name, taps OK and nothing happens, with no message saying why.
- **Evidence:** Animals.tsx:146-151: `await api(...)` has no try/catch. On any failure (403 for members, offline, 500) the promise rejects unhandled and nothing appears on screen. The name is also sent untrimmed, while the client shows whatever was typed. PROVEN with Playwright (scenarioAnimalRename): PATCH returns 403, the name shown is still 'Wild Boar #1', no .an-error appears, and the console shows 'unhandledrejection: Admin privileges required'.
- **Verifier:** Reproduced: PATCH returns 403, the name shown stays 'Wild Boar #1', no .an-error appears, and the page logs 'unhandledrejection: Admin privileges required'. Animals.tsx:149 awaits api() with no try/catch. The client stores the untrimmed name while the server trims it (routes_animals.py:165), and a whitespace-only name shows as blank on the client while the server keeps the old one.
- **Fix:** Wrap rename in try/catch → setErr('Could not save the name. …'), trim before sending and before updating local state, and disable the name tap for non-admins (see C-09). Consider replacing window.prompt with the inline editor pattern already used by CameraNameEditor.

### C-13 — The photo viewer stops at the last loaded photo ("Photo 60 of 60") when older photos exist

*medium · confirmed · ux · effort S* — `frontend/src/components/PhotoLightbox.tsx`, `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** Swiping through last night's photos, the viewer hits a dead end at 60 and suggests there are no more.
- **Evidence:** PhotoLightbox.tsx:111-113: step() stops at photos.length-1, and Next is disabled at line 385. Photos.tsx:223-230 passes only the loaded array and no way to fetch more. PROVEN with Playwright (scenarioLightboxEnd): the server has more pages (next_before set), yet the toolbar reads 'PL19 · Photo 60 of 60' and Next is disabled.
- **Verifier:** Reproduced: the toolbar reads 'PL19 · Photo 60 of 60' with Next disabled while next_before is set. step() stops at photos.length-1 (PhotoLightbox.tsx:113), Next is disabled at line 385, and Photos.tsx:223-230 passes no way to load more. The IntersectionObserver sentinel sits behind the overlay, so it never fires while the viewer is open.
- **Fix:** Add optional `hasMore` and `onNeedMore()` props to PhotoLightbox. Call onNeedMore when idx >= photos.length - 3, keep Next enabled while hasMore, and show '60+' instead of 'of 60'. Photos passes nextBefore and loadMore.

### F-11 — 'Look for repeats' erases names, notes and status the hunter gave unconfirmed animals

*medium · confirmed · data-correctness · effort S* — `backend/app/ai/reid.py`, `backend/app/api/routes_animals.py`, `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** A hunter names 'Big tusker', later taps 'Look for repeats', and the name and notes are silently gone. They are replaced by 'Wild boar #3'.
- **Evidence:** reid.py:84-104: cluster() deletes every Individual with no confirmed_by_user link. PATCH /animals/{id} (routes_animals.py:155-172) changes label, notes and status without confirming anything, and Animals.tsx:146-150 lets you 'Tap to name' any card, including unconfirmed candidates. Proven (scratch pytest): after cluster(), I set label='Big tusker' and notes='left ear torn' on a candidate and ran cluster() again. The labels were ['Wild boar #1', 'Wild boar #2'] and the name was gone.
- **Verifier:** Reproduced: after naming a candidate 'Big tusker' with notes and re-running cluster(), the individuals were ['Red deer #1', 'Red deer #2'] with notes None. cluster() deletes every Individual with no confirmed_by_user link (reid.py:84-103), and PATCH (routes_animals.py:155-172) confirms nothing. Downgraded from high because re-ID is labelled experimental and the Confirm action protects a candidate.
- **Fix:** Minimal fix: in patch_animal, also run UPDATE detection_individual SET confirmed_by_user=true WHERE individual_id=:id. This matches reid.py's own rule that an individual the user has touched is ground truth.

### I-18 — Photo grids download full-size originals as thumbnails

*medium · confirmed · perf · effort M* — `frontend/src/pages/Photos.tsx`, `frontend/src/pages/Cameras.tsx`, `frontend/src/pages/Animals.tsx`, `frontend/src/pages/Insights.tsx`, `backend/app/api/routes_images.py`

- **What the hunter sees:** The Photos tab burns data and battery and fills in slowly exactly where signal is weak.
- **Evidence:** Every grid tile uses imageUrl(file_url), which is the original JPEG (Photos.tsx:200, Cameras.tsx:437, Animals.tsx:225 and 410, Insights.tsx:220). There is no thumbnail variant (routes_images.py:30-58). I/f_slow3g.cjs: on first view of Photos on throttled 3G, Chrome fetched 34 originals for 7 visible tiles, because lazy-load margins grow on slow connections. With real 150-300 KB trail-camera photos that is 5-10 MB before any scrolling. The lightbox also doesn't preload the next photo, so each swipe shows 'Loading photo…'.
- **Verifier:** Every grid tile uses imageUrl(file_url), which is the original (Photos.tsx:200 and the other cited lines). routes_images.py:33-64 has no size variant, and Chrome widens lazy-load margins on slow connections. Cloudflare does not shrink JPEGs, so every original goes over the phone link.
- **Fix:** The proposed fix is right. Generate the ?w=360 thumbnail at ingest or on first request, cache it on disk, serve it with a long Cache-Control, and preload idx+1 in the lightbox.

### I-19 — Photos feed skips photos at page boundaries when a burst shares one timestamp

*medium · confirmed · bug · effort S* — `backend/app/api/routes_photos.py`, `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** Some frames of a sighting never appear in the feed, which is often the frame where the animal is clearest.
- **Evidence:** routes_photos.py:85 filters captured_at < before, and line 125 returns next_before = rows[-1].captured_at. Ordering is (captured_at, id) but the cursor carries only the time, so any other frame of the same burst with the same second is skipped. Proven with I/paging.py on the QA data (3-frame bursts): 1,939 visible photos. Paging with limit 60 after one extra single photo arrived returned 1,938. limit 50 returned 1,900 (38 lost). /photos/filters counts still add up to 1,939.
- **Verifier:** Reproduced on the QA data: paging with limit 60 returned 1,794 of 1,795 photos, and with limit 50 it returned 1,759 (36 lost). The cursor carries only captured_at with a strict < (routes_photos.py:85, 125) while ordering is (captured_at, id). Real-world loss needs same-second bursts, which second-resolution EXIF from Suntek makes plausible (ftp_import.py:123).
- **Fix:** Return next_before plus next_id and filter with tuple_(Image.captured_at, Image.id) < (before, before_id). Pass both from Photos.tsx.

### J-14 — Galleries download full-resolution originals, and the service worker keeps every photo forever

*medium · confirmed · perf · effort M* — `frontend/public/sw.js`, `backend/app/api/routes_images.py`, `backend/app/models.py`, `frontend/src/api.ts`

- **What the hunter sees:** Scrolling Photos over rural 4G is slow and eats data, and the PWA's storage grows without bound across a season.
- **Evidence:** routes_images.py:71 always serves the original file. Image.thumbnail_path (models.py:274) is never written anywhere. Photos pages in 60 at a time (Photos.tsx:31). sw.js:93-97 stores every image response in 'gamesense-v2', which is never versioned or trimmed (activate only deletes other cache names). Each image URL carries ?token= (api.ts:90-94), so signing in again duplicates every entry.
- **Verifier:** routes_images.py always returns the original file, and Image.thumbnail_path (models.py:274) is written nowhere. Photos loads 60 per page (Photos.tsx:31). sw.js:93-97 puts every image response into 'gamesense-v2', which activate never trims, and the ?token= in each URL (api.ts:19-23) creates a new cache key per sign-in. Bandwidth was not measured, but the unbounded cache growth follows directly from the code.
- **Fix:** As proposed. Make the thumbnail cache key token-free (for example, strip the token param before cache.put and match with ignoreSearch on a thumb path), or duplicates persist.

### C-11 — Merging keeps the name of the animal with the most sightings and throws away the one the hunter typed

*low · confirmed · data-correctness · effort S* — `frontend/src/pages/Animals.tsx`, `backend/app/api/routes_animals.py`

- **What the hunter sees:** A hunter merges their named animal with a bigger unnamed cluster, and the name they gave it disappears.
- **Evidence:** Animals.tsx:156 picks the target as the individual with the most sightings. merge_animals deletes each source Individual (routes_animals.py:211) and never looks at its label. PROVEN with a scratch pytest (test_merge_drops_source_name): merging 'Cyclops' (1 sighting) into 'Wild Boar #1' (3 sightings) leaves ['Wild Boar #1'].
- **Verifier:** The auditor's pytest passes: merging 'Cyclops' (1 sighting) into 'Wild Boar #1' (3 sightings) leaves ['Wild Boar #1']. Animals.tsx:156 picks the target by sightings, and merge_animals (routes_animals.py:202-211) deletes sources without looking at their labels. It is recoverable by renaming afterwards, and the merge confirms the target, so the new name then sticks. Low.
- **Fix:** Server side: if the target's label still matches the auto pattern '<Species> #n' and exactly one source has a custom label, carry that label (and notes) over to the target. Client side: prefer a target that has a custom name, or ask which name to keep when more than one is custom.

### C-14 — Animals says "Seen today" for last night's sighting (days counted as elapsed 24h, not calendar days)

*low · confirmed · data-correctness · effort S* — `frontend/src/pages/Animals.tsx`, `frontend/src/pages/Cameras.tsx`

- **What the hunter sees:** Every morning the Animals page says a boar was 'Seen today' when it came through last night, and it disagrees with the Photos page.
- **Evidence:** Animals.tsx:44-52 lastSeen() and Cameras.tsx:89-96 sinceLabel() use floor((now - t)/24h), while Photos.tsx:42-50 dayOf() uses calendar days. PROVEN with node under TZ=Europe/Madrid (scratchpad/C/days.cjs), now = 26 Sep 08:00: a 25 Sep 21:30 sighting reads Animals 'Seen today' but Photos 'Yesterday', and a 24 Sep 21:30 sighting reads Animals 'Seen yesterday' but Photos 'Thu 24 Sept'. Cameras 'Quiet since yesterday' has the same off-by-one.
- **Verifier:** Reproduced with node under TZ=Europe/Madrid, now=26 Sep 08:00. A 25 Sep 21:30 sighting reads Animals 'Seen today' vs Photos 'Yesterday'. A 24 Sep 21:30 sighting reads 'Seen yesterday' vs 'Thu Sep 24'. Animals.tsx:47 and Cameras.tsx:91 floor elapsed 24h periods, while Photos dayOf compares calendar dates. It is cosmetic and both labels still mean 'recent', so low.
- **Fix:** Share one helper (for example relativeDay(iso) in a utils file) that compares local calendar dates like dayOf, and use it in Animals lastSeen, Cameras sinceLabel and Photos dayOf.

### C-15 — The same photo gets different labels on Cameras than on Photos and Animals

*low · confirmed · ux · effort S* — `frontend/src/pages/Cameras.tsx`, `backend/app/api/routes_cameras.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** Tap the same photo from Cameras and from Photos and the viewer names the animal differently, which makes the labels hard to trust.
- **Evidence:** Cameras builds labels client-side with its own classLabel (Cameras.tsx:50-66). Photos and Animals use the backend class_label (model.py:167-185). PROVEN by running both on the same inputs (scratchpad/C/labels.cjs plus python): male solitary boar is 'Boar ♂' vs 'Boar'; unknown boar is 'Wild Boar' vs 'Wild boar'; male sounder of 5 is 'Boar sounder (5)' vs 'Boar ×5'; male red deer herd of 3 is 'Red Deer herd (3)' vs 'Stag ×3'.
- **Verifier:** Cameras.tsx:50-66 builds its own labels ('Boar ♂', 'Boar sounder (5)', 'Wild Boar'), while /photos and /species use class_label (model.py:167-185: 'Boar', 'Sounder', 'Wild boar'). Also, the det_map comprehension in routes_cameras.py:274 keeps the arbitrary last detection row and does not skip hidden species, so a boar+rabbit photo can be labelled 'Rabbit' on Cameras only.
- **Fix:** Add `label` (class_label plus group size) to /cameras/{id}/images, as /photos does, and delete the frontend classLabel. While there, choose the label from the highest-confidence non-hidden detection, as /photos does, instead of the arbitrary last row in the det_map comprehension (routes_cameras.py:274).

### C-16 — "Show empty photos" can show the wrong set when tapped while the strip is still loading

*low · confirmed · bug · effort S* — `frontend/src/pages/Cameras.tsx`

- **What the hunter sees:** On a slow link the hunter asks to see empty frames and still sees none, with the button saying they're shown.
- **Evidence:** loadImages (Cameras.tsx:269-272) has no request guard. loadCameras (280) and toggleHidden (295-303) both write images[camId], so whichever response arrives last wins. PROVEN with Playwright (pw3.cjs scenarioToggleRace): tap the toggle while the initial include_empty=false request is still in flight (3s). The toggle reads 'Hide empty photos', but the strip shows 8 photos and 0 empty (dimmed) ones.
- **Verifier:** Reproduced with pw3.cjs: the toggle says 'Hide empty photos', but 8 thumbs show and 0 of them are empty. loadImages (Cameras.tsx:269-272) has no request guard, so a slow include_empty=false response overwrites the newer one. It needs the tap inside the first strip load's latency window and tapping again recovers it, so low. syncNow also calls a loadCameras closure captured at tap time, with the showHidden value from then.
- **Fix:** Keep a per-camera request counter (useRef<Record<string, number>>). In loadImages, ignore responses that aren't the latest for that camera. Have loadCameras read showHidden through a ref so a refetch uses the current mode.

### C-17 — The camera card's photo counts are wrong and cost 4 queries per camera

*low · confirmed · data-correctness · effort S* — `backend/app/api/routes_cameras.py`, `frontend/src/pages/Cameras.tsx`

- **What the hunter sees:** The numbers on the camera card don't match what the strip or the Photos feed shows, and don't move after the hunter reviews photos.
- **Evidence:** list_cameras (routes_cameras.py:84-126) counts all images and all empty frames with no VISIBLE_ANIMAL or original_path filter, so Details 'N with animals' (Cameras.tsx:399, 491) includes hidden-species photos (rabbits), unscanned photos and file-less photos. PROVEN with a scratch pytest (test_camera_details_count_includes_hidden_and_unscanned): 1 boar photo plus 3 rabbit-only photos shows '4 with animals' while the strip shows 1. The counts also go stale after flag() (it reloads only the strip), so 'Show 12 empty photos' stays at 12. The strip is capped at 80 with no paging, so older empties can't be reviewed. Query count is 42 for 10 cameras (test_list_cameras_query_count).
- **Verifier:** The auditor's pytests pass: 1 boar plus 3 rabbit-only photos give '4 with animals' while the strip shows 1, and 42 queries for 10 cameras. list_cameras (routes_cameras.py:92-106) counts every Image with no VISIBLE_ANIMAL or original_path filter, and runs 4 queries per camera, including a redundant lat/lon re-select of a row already loaded. flag() (Cameras.tsx:318) reloads only the strip, so empty_count goes stale.
- **Fix:** Compute last_capture, animal count (VISIBLE_ANIMAL) and empty count in one grouped query (GROUP BY camera_id) and use lat/lon from the Camera row already loaded. After flag(), adjust empty_count locally, or refetch that camera. Add 'Show older' paging (before cursor) to the strip.

### C-18 — The species gallery stops at 300 photos while the chip says 'All 1234', and the query reads every row first

*low · confirmed · perf · effort M* — `backend/app/api/routes_species.py`, `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** The boar gallery gets slower as the season goes on, and the oldest photos silently can't be reached.
- **Evidence:** species_images (routes_species.py:92-126) has limit=300 but no SQL LIMIT. It loads every detection row for the species and filters and truncates in Python. Animals.tsx:369 and 380 show '300 photos' next to 'All {sp.count}'. PROVEN with a scratch pytest (test_species_gallery_capped_below_chip_count): chip count 305, gallery returns 300. The oldest photos are unreachable.
- **Verifier:** The auditor's pytest passes: the chip says 305 and the gallery returns 300. species_images (routes_species.py:100-110) has no SQL LIMIT and truncates in Python (line 124), and Animals.tsx:369/380 shows '300 photos' next to 'All 305'.
- **Fix:** Push the label filter into SQL (map the class to sex and group_type conditions), add .limit() and a `before` cursor like /photos, and page the gallery with the same infinite-scroll pattern (after C-01 is fixed).

### C-20 — Photos saved on a computer are named in UTC (22:05 saves as 20-05)

*low · plausible · bug · effort S* — `backend/app/api/routes_images.py`, `frontend/src/components/PhotoLightbox.tsx`

- **What the hunter sees:** Downloaded files show the wrong time, 2h off in summer and 1h in winter, so sorting a folder by name misleads.
- **Evidence:** download_name (routes_images.py:26-30) formats the tz-aware captured_at as-is. psycopg returns it in the session zone (UTC), and Content-Disposition takes priority over the <a download> name the lightbox computes in local time (PhotoLightbox.tsx:39-44, 279-280). PROVEN with a scratch pytest (test_download_name_is_utc_not_madrid): a 22:05 Madrid photo downloads as 'PL19_2026-09-25_20-05.jpg'. Around 25 Oct, the repeated 02:xx hour also produces duplicate names.
- **Verifier:** download_name (routes_images.py:30) formats captured_at in whatever zone psycopg returns, which is the Postgres server's TimeZone. db.py sets no session timezone. The test DB is UTC, so the test shows 20-05. Production runs on a Windows Postgres (docs/09-deployment.md), where initdb usually takes the OS zone (CET/CEST for Spain), which would give the correct name, so the real outcome depends on deployment. Phones use the share path, which already names files in local time (PhotoLightbox.tsx:260).
- **Fix:** Deployment-independent fix: captured_at.astimezone(ZoneInfo(estate.timezone)) in download_name, plus seconds or the offset so the DST-repeat hour stays unique.

### C-25 — Tapping a chip keeps showing the old photos, with no loading cue, until the new list arrives

*low · confirmed · ux · effort S* — `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** On a slow link the hunter taps 'Red deer', still sees boar, thinks the tap missed and taps again, which turns the chip back off.
- **Evidence:** Photos.tsx:81-92: load() doesn't clear photos or set any pending state. 'Loading photos…' (line 180) only renders when photos === null, which happens on first mount only. After a chip tap, the previous filter's grid stays under the newly highlighted chip until the response lands. Proven by code reading.
- **Verifier:** load() (Photos.tsx:81-92) neither clears photos nor sets any pending flag, and 'Loading photos…' renders only when photos === null (line 180), which is first mount only. After a chip tap the old grid stays under the newly pressed chip until the response lands, and a second tap toggles the chip off again via toggleIn.
- **Fix:** Track `pending` (a request id in flight). While pending, dim the grid (opacity 0.5) and show a small 'Loading…' next to the chips, or clear to null when the filter changes.

### C-29 — "Save photo" on phones downloads the full image before opening the share sheet, which can fail on slow links

*low · plausible · bug · effort S* — `frontend/src/components/PhotoLightbox.tsx`

- **What the hunter sees:** 'Save photo' sometimes opens the photo full-screen in Safari instead of showing Save Image.
- **Evidence:** PhotoLightbox.tsx:265-272 awaits fetch(src).blob() of the original and only then calls navigator.share(). Safari and Chrome need share() to run within transient user activation. After a multi-second download that activation has expired, share() rejects with NotAllowedError (not AbortError), and the code falls through to the <a download> path (277-283), which in the iOS PWA opens the photo in a view the user has to find a way out of. This is exactly what the comment says it avoids. Not reproduced: headless Chromium has no share sheet.
- **Verifier:** PhotoLightbox.tsx:267-270 awaits fetch(src).blob() of the original before navigator.share(). Browsers require transient user activation, and Chrome's window is about 5s, with WebKit's shorter. An expired activation raises NotAllowedError, which is not caught as AbortError, so the code falls through to the <a download> path. This can't be reproduced headless because there is no share sheet.
- **Fix:** Fetch the blob as soon as the photo is showing (imgReady) and keep it in a ref, so download() can call navigator.share() synchronously inside the click. With C-04 in place, fetch the 'screen' size.

### E-24 — UBox full-size originals are used as strip thumbnails, and nothing checks free disk space

*low · confirmed · perf · effort M* — `backend/app/ingestion/ubox.py:325-331`, `backend/app/ingestion/ubox_sync.py:141-157`, `backend/app/api/routes_images.py:66`, `backend/app/models.py:274`

- **What the hunter sees:** Each visible UBox tile costs about 0.4–1 MB on a weak dusk signal. At the 500/day cap, one camera's media can grow by 0.2–0.5 GB per day with no warning before the disk fills.
- **Evidence:** UBox import prefers cloud_hd_image_url: 4608×2592, about 400 KB for an indoor frame per docs/18, and the live import marked 17 of 18 frames empty. It is stored as the only file. thumbnail_path is never written, so the lazy-loaded Cameras strip loads full originals. No ingestion path checks free disk space before writing, and the disk is shared with Postgres. Overlaps with D33.
- **Verifier:** ubox.py:325-331 prefers cloud_hd_image_url, and the file is stored as the only copy. thumbnail_path (models.py:274) is never written anywhere, and routes_images.py serves original_path for every request, so the strips load full-size files for all providers. No shutil.disk_usage or free-space check exists anywhere in backend/app. Impact is bandwidth on weak signal and unmonitored disk growth, overlapping D33.
- **Fix:** As proposed: write a JPEG of about 480 px at ingest, backfill it lazily on first request, and serve ?size=thumb in the strips. Record a visible SyncLog or /admin/status warning when free space on media_root falls below about 2 GB.

### I-27 — Photos groups by calendar day on the phone, splitting each night at midnight

*low · confirmed · ux · effort S* — `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** 'What came through last night' is split across two headings, and the headings mislabel it.
- **Evidence:** dayOf (Photos.tsx:42-50) uses the device's calendar date, and grouping happens at lines 137-146. Proven with I/f_photodays.cjs: 'Today: 00:56 → 16:14' holds last night's after-midnight photos, while 'Yesterday: 00:22 → 23:37' mixes the tail of the night before with last evening. The backend defines a night as 18:00-06:00 in estate time (exposure.py NIGHT_SHIFT).
- **Verifier:** dayOf uses the device's calendar date (Photos.tsx:42-50) and grouping splits on it (137-146), so photos after midnight land under the next day's heading. That differs from the backend's night definition.
- **Fix:** Group by estate-local time shifted back 6 h, using Intl with timeZone 'Europe/Madrid' so it also holds across the 25 Oct DST change. Label the groups 'Last night', 'Thu night' and so on.

### I-28 — The Animals gallery stops at 300 photos with no way to see older ones

*low · confirmed · ux · effort S* — `backend/app/api/routes_species.py`, `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** Older boar photos seem to have vanished, and the two counts contradict each other.
- **Evidence:** routes_species.py:95 defaults to limit 300 with no cursor. Animals.tsx:369 shows the loaded count. Proven: /species/spotted gives wild_boar 684 photos, while /species/wild_boar/images returns 300 with the oldest from 6 Sep. The row says '684 photos' and the gallery says '300 photos'.
- **Verifier:** Reproduced: /species/spotted gives wild_boar 684, while /species/wild_boar/images returns 300, the oldest from 2026-09-06, because the default is limit=300 with no cursor (routes_species.py:95). The gallery header shows galleryImgs.length (Animals.tsx:369).
- **Fix:** The proposed fix is right. The cheapest version is 'Newest 300 of 684' plus a link to /photos?species=wild_boar.

### J-13 — Photo feed drops frames that share a timestamp at a page boundary

*low · confirmed · bug · effort S* — `backend/app/api/routes_photos.py`

- **What the hunter sees:** Some photos of a burst silently never appear in Photos when a page break falls inside the burst.
- **Evidence:** Paging uses `captured_at < before` (routes_photos.py:84-85) with next_before = the last row's captured_at (routes_photos.py:124), while ordering by (captured_at, id). Suntek FTP filenames have minute precision (ftp_import.py:143-147, 'seconds set to 00'), so all frames of a burst share one timestamp. PROVEN: three frames with the same time and limit=2 gave page 1 = 2 frames and page 2 = 0; the third frame is never shown.
- **Verifier:** routes_photos.py:84-86 filters captured_at < before and orders by (captured_at, id), and next_before is the last row's captured_at (line 125). Any rows that share that timestamp beyond the page break are skipped for good. It triggers mainly with minute-precision Suntek filename times (ftp_import.py, used when EXIF is missing) or bursts within the same second, so it is rare.
- **Fix:** Use a keyset cursor on (captured_at, id): return both values and filter tuple_(Image.captured_at, Image.id) < (t, id).


## 14. Map fixes

### B-01 — Tapping "Try again" on the satellite error breaks the map: the overlays disappear and "Loading map…" never goes away

*high · confirmed · bug · effort S* — `frontend/src/pages/Map.tsx`, `frontend/src/map/layers.ts`

- **What the hunter sees:** On weak signal one tile times out. The hunter taps the only offered fix, and the map loses its bedding and scent arrows and shows 'Loading map…' forever. Drawing and Fit estate stop working until they reload the whole app.
- **Evidence:** Map.tsx:206: the retry calls `map.current?.setStyle(style); setReady(false)`. MapLibre 5.24 compares the new style with the current one. The current style also holds the layers added by addLayers (bedding, wind, cones, draft), so the comparison REMOVES them. A diff update never fires 'style.load', so Map.tsx:81 never calls setReady(true) again. Map.tsx:80 also sets mapErr on ANY map error: one failed tile shows the banner, and the banner never clears by itself. PROVEN with Playwright (scratchpad/B/s_tileretry.cjs, screenshot tileretry.png). Tiles were served as 500 → banner shown → tiles restored → tapped Try again. 6 s later '.map-loading' was still visible, 'Fit estate' was disabled, the bedding polygon and wind arrows were gone, and the 'Loading map…' box blocked taps in the middle of the map (the next Draw-bedding tap timed out on 'map-loading intercepts pointer events').
- **Verifier:** I reproduced it (verify-B/v_retry.cjs, with the map instance exposed). Before retry the bedding source held 4 features and wind held 8. After tapping Try again both held 0, '.map-loading' stayed visible and 'Fit estate' stayed disabled. The auditor's explanation of why is slightly off. MapLibre 5.24 Style.setState DOES fire 'style.load' synchronously during the diff, so addLayers re-adds the sources empty and setReady(true) runs. Then Map.tsx:206 calls setReady(false) after setStyle, and in React's batch the last call wins, so ready stays false and renderLayers never runs again. Recovery is possible by switching tabs and back (the page remounts), so a full app reload is not needed.
- **Fix:** Do not touch the style or `ready` in the retry. Use `onClick={() => { setMapErr(''); map.current?.refreshTiles('satellite') }}`. refreshTiles is public API in 5.24. The suggested `style.sourceCaches` does not exist in MapLibre 5 (it is `style.tileManagers`). In the 'error' handler, set mapErr only when `(e as any).sourceId === 'satellite'`. Clear it on the next 'idle' when `map.isSourceLoaded('satellite')`.

### B-09 — A camera placed by hand on the map snaps back to SPYPOINT's reported position at the next sync

*medium · confirmed · data-correctness · effort S* — `backend/app/ingestion/sync.py`, `backend/app/api/routes_cameras.py`

- **What the hunter sees:** The hunter fixes a camera's position, and within 15 minutes the pin (and every route and fit that uses it) jumps back to a cell-tower guess, sometimes kilometres off. It feels like the save didn't work.
- **Evidence:** sync.py:74-76 overwrites row.lat/row.lon whenever the provider reports coordinates (spypoint.py:146-159 reads status.coordinates, usually a cell-tower fix). PROVEN (scratchpad/B/pyt/test_map_sync.py): camera synced at 39.20,-1.30, hunter moves it to 39.0947,-1.3608 (what PUT /location does), next upsert_camera → back to 39.2,-1.3.
- **Verifier:** sync.py:74-76 overwrites row.lat/lon whenever the provider reports coordinates, and nothing marks a manual placement. The scratch test restores (39.2,-1.3) after a hand move. spypoint.py:276 reads status.coordinates. I could not check how often the real SPYPOINT API returns coordinates.
- **Fix:** As proposed: add a location_manual flag (migration), set it in PUT /location, and skip provider coordinates when it is set. Also ignore (0,0) and out-of-range provider fixes.

### B-11 — After a failed save or remove, the error appears off-screen or its 'Try again' button quietly does the wrong thing

*medium · confirmed · ux · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** The hunter taps Remove and nothing happens, or taps Try again, sees the error disappear, and believes the new position was saved when it wasn't.
- **Evidence:** All write errors share `err`, which renders at the top of the page with `<button onClick={load}>Try again</button>` (Map.tsx:187; set at :160 and :169). PROVEN (s_writeerr.cjs, phone viewport): (1) Remove a stand → DELETE returns the common 409 'N sits recorded at this stand… Rename it instead'. The banner sits at top −385 px (scrollY 517) while the confirm box stays up, so Remove seems to do nothing. (2) PATCH fails → 'That didn’t save. Bad gateway' → tapping 'Try again' re-runs load(), which clears the banner. 0 writes are retried and the draft is still unsaved in edit mode.
- **Verifier:** Reproduced with s_writeerr.cjs. After a DELETE 409, the banner sits at top −385 px (scrollY 517) with the confirm box still shown. After a PATCH 502, 'Try again' (Map.tsx:187 → load) clears the banner with 0 writes retried. The claim that the hunter 'believes it saved' is overstated: the edit toolbar stays visible and no 'Saved.' appears.
- **Fix:** As proposed: keep a separate writeErr rendered inline (in the edit toolbar and inside the confirm box) whose retry calls saveEdit()/removeSelected(). For the 409, map to 'This stand has sit history, so it can’t be removed. Rename it instead.'

### E-16 — If SPYPOINT reports GPS for a camera, the next sync moves a hand-placed map marker back

*medium · confirmed · bug · effort S* — `backend/app/ingestion/sync.py:74-76`, `backend/app/api/routes_cameras.py:235-248`

- **What the hunter sees:** A hunter's corrected camera position jumps back within 15 min, and the wind and bedding logic uses the wrong spot.
- **Evidence:** upsert_camera overwrites lat/lon whenever SPYPOINT reports coordinates, and there is no 'set by hand' flag. PROVEN with scratchpad/E/test_e_spypoint.py::test_manual_map_placement_is_reverted_by_next_sync: the location is set to (39.1234,-1.4567) the way PUT /location does, and the next upsert resets it to (39.0,-1.3). This only applies to cameras that report coordinates.
- **Verifier:** upsert_camera (sync.py:74-76) overwrites lat and lon whenever SPYPOINT reports coordinates, and set_location (routes_cameras.py:235-248) sets no flag. The auditor's test shows the manual position reverted on the next upsert. tests/test_spypoint.py:46 uses a coordinate fixture at Alatoz (-1.36, 39.09), which suggests these cameras do report positions (likely set in the SPYPOINT app), so this probably applies to the main cameras.
- **Fix:** As proposed: add location_is_custom (migration), set it in set_location, and copy SPYPOINT coordinates only when it is false or lat is None. Add a 'reset to SPYPOINT position' action, the same way name_is_custom works.

### I-11 — Map 'Try again' after a tile failure wipes bedding and wind layers and disables Fit estate

*medium · confirmed · bug · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** The one button offered when the satellite picture fails leaves the map worse: no bedding, no wind arrows, until a full reload.
- **Evidence:** Map.tsx:206: Try again calls map.setStyle(style) and setReady(false). With MapLibre's default diff mode the style is reapplied without the custom layers added by addLayers(). No 'style.load' fires, so ready stays false, and every render effect (lines 98-108) is gated on ready. Proven with I/f_maptry.cjs: tiles aborted, then allowed, then Try again. Result: bedding polygon gone, 'Fit estate' disabled, error banner still showing. Screenshot: shots/map_try_again_before_after.png.
- **Verifier:** Reproduced (verify-I/v_maptry.cjs). After Try again the bedding polygon is gone, 'Fit estate' is disabled and the tile error banner is back. The stated mechanism is slightly off: in MapLibre 5.24, Style.setState does fire 'style.load' synchronously, so addLayers and setReady(true) run. The click handler's setReady(false) then runs after it and wins (Map.tsx:206). The unchanged satellite source is also left as is by the diff, so failed tiles are never actually retried.
- **Fix:** Do not call setStyle. Clear mapErr and reload only the raster: (map.getSource('satellite') as RasterTileSource).setTiles([...style.sources.satellite.tiles]). Leave ready untouched.

### B-10 — Zone input validation: malformed polygons return 500, twisted or zero-area shapes are accepted, and PATCH with null returns 500

*low · confirmed · bug · effort S* — `backend/app/api/routes_zones.py`, `backend/app/geo.py`

- **What the hunter sees:** A mis-tapped outline saves silently and quietly skews every wind call. API clients get 500s instead of a clear message.
- **Evidence:** _validate_polygon (routes_zones.py:52-63) calls geo.ring (geo.py:280-283), which does float(pt[1]) and len(pt) without guarding. It counts the closing vertex toward the 3-point minimum and never checks self-intersection or area. ZonePatch (:46-49) lets explicit nulls through to setattr. PROVEN (test_map_b.py): coordinates [[['a','b'],…]] → 500; [[1,2,3,4]] → 500. A bow-tie, 4 identical points and 2 distinct points + closure all → 201. PATCH {'name': null} → 500 (NOT NULL). PATCH {'name':'   '} → 200 with a blank name. From the UI, tapping corners out of order (or a double tap, B-12) saves a self-crossing or degenerate bedding shape. geo.contains is even-odd, so the crossed part counts as 'outside'.
- **Verifier:** Scratch tests confirm: [['a','b'],…] → 500 and [[1,2,3,4]] → 500 (geo.ring calls float() and len() unguarded). A bow-tie, 4 identical points and 2 distinct points plus closure all → 201. PATCH name:null → 500; name '   ' → 200. Downgraded to low: the 500s and PATCH paths are API-only (the UI has no zone PATCH). The UI-reachable part is a self-crossing or degenerate outline from mis-taps.
- **Fix:** As proposed: typed coordinates, dedupe consecutive points, ≥3 distinct vertices, minimum shoelace area, self-intersection check with hunter copy, and reject explicit nulls in ZonePatch with stripped names.

### B-12 — Drawing on a phone: the keyboard covers the map, the point counter hides under the tab bar, a tap near the bottom leaves the page and loses the outline

*low · confirmed · ux · effort M* — `frontend/src/pages/Map.tsx`, `frontend/src/map/map.css`

- **What the hunter sees:** While outlining bedding with gloves, the hunter can't see how many points they have. A tap near the bottom of the map jumps to another tab and the whole outline is gone.
- **Evidence:** Map.tsx:197 autoFocus on Name when entering Draw bedding or Move (Playwright: document.activeElement is INPUT right after tapping Move, so the soft keyboard opens). The edit toolbar is inserted above the map (Map.tsx:195) and pushes the map down 208 px (map-stage top 214 → 422 on 390×844). The canvas then runs to y=887 while the fixed tab bar covers 784-844. PROVEN (s_hint.cjs): the '· N points' hint (map.css:68, bottom:38px) is under the tab bar, and elementFromPoint at the hint returns a nav <a>. Taps in that strip navigate away, and nothing guards an unsaved draft (Cancel at Map.tsx:196 also discards without asking).
- **Verifier:** Reproduced with s_hint.cjs and s_move.cjs. The edit hint sits at y 805-849 under the fixed tab bar (784-844), and elementFromPoint there returns a nav <a>. document.activeElement is INPUT after Move, and the map stage moves down by 208 px. The tab bar itself is visible, so the 'tap near the bottom leaves the page' risk is real but limited. Drawing bedding is also an infrequent task.
- **Fix:** The proposed useBlocker does NOT work here. main.tsx uses <BrowserRouter>, and react-router 6 useBlocker requires a data router (createBrowserRouter). Instead, expose an 'unsaved draft' flag, for example via context, that Layout's tab links check with confirm(), plus beforeunload. Or migrate to createBrowserRouter first. Keep the other parts: drop autoFocus, move the hint to the top of the stage, and confirm Cancel when ≥3 points are drawn.

### B-13 — Double-tap to zoom while drawing bedding drops a stray corner

*low · confirmed · ux · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** The natural 'zoom in to be precise' gesture adds a corner the hunter didn't intend. That makes spikes or self-crossing outlines (see B-10) that are easy to miss as a 4 px dot.
- **Evidence:** Map.tsx:82-87 appends a point on every map 'click'. doubleClickZoom and touch double-tap stay enabled in edit mode. PROVEN (s_doubletap.cjs, touch emulation): 1 point, then a double tap elsewhere → counter '2 points' and the scale changed 300 m → 200 m (it zoomed AND added a vertex).
- **Verifier:** Reproduced with s_doubletap.cjs: a touch double-tap in draw mode took the counter from 1 to 2 points and the scale from 300 m to 200 m. Map.tsx:82-87 appends on every click, and doubleClickZoom stays enabled. The Undo point button softens the impact.
- **Fix:** `instance.doubleClickZoom.disable()` while editing is correct; in MapLibre it disables both mouse dblclick and touch TapZoom. Keep the ~20 px / 350 ms dedupe too. Once zoom is disabled, the second tap of a double-tap still fires 'click' and would add a duplicate point.

### B-17 — After Save, the pin jumps back to its old spot until the reload finishes, while 'Saved.' is already showing

*low · confirmed · ux · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** On slow signal the hunter sees 'Saved.' next to a pin in the old place and taps Move again.
- **Evidence:** Map.tsx:159 calls setEditing(null) (removing the draft dot) before `await load()`. The markers still come from the old data. PROVEN (s_saveflicker.cjs) with a 4 s reload: the pin stays at its old canvas position (64,277) with the draft gone for the whole wait, then moves.
- **Verifier:** Reproduced with s_saveflicker.cjs and a 4 s reload: 0.6 s after Save the pin is still at its old canvas position (64,277), the draft is gone and 'Saved.' is shown. setEditing(null) runs before `await load()` (Map.tsx:159).
- **Fix:** As proposed: patch data or cameras optimistically with the saved lat/lon before load(), or clear the draft only after load() resolves.

### B-18 — Loading the hill shape: a doubled, URL-length error message, a request held open for 21+ seconds, and the button shown to everyone

*low · confirmed · ux · effort S* — `backend/app/api/routes_zones.py`, `backend/app/terrain.py`, `frontend/src/pages/Map.tsx`

- **What the hunter sees:** A wall of URL text on the phone, a button stuck on 'Loading…', and editing locked meanwhile.
- **Evidence:** routes_zones.py:200-201 returns 502 f"Couldn't download the hill shape. {e}", and Map.tsx:230 prefixes 'Couldn’t load the hill shape.' again. PROVEN (scratchpad/B/pyt/test_map_terrain.py): an upstream 500 produces 'Couldn’t load the hill shape. Couldn't download the hill shape. Server error '500 Internal Server Error' for url 'https://api.open-meteo.com/v1/elevation?latitude=39.07224%2C…' (≈3 KB of coordinates). On 429 the request sleeps 21 s in-thread (terrain.py:400-411) before failing, and can take minutes with 45 s timeouts. The frontend has no timeout. While it runs, `busy` also disables map taps and every save.
- **Verifier:** Scratch test_map_terrain.py: an upstream 500 produces 'Couldn’t load the hill shape. Couldn't download the hill shape. Server error … for url https://api.open-meteo.com/v1/elevation?latitude=…' (kilobytes of URL). A 429 sleeps 3+6+12=21 s in-request (terrain.py:49-59). The button at Map.tsx:230 is not admin-gated and shares `busy`. The admin-gating part overlaps B-08's fix.
- **Fix:** As proposed: short server copy with details in the log, a background task returning 202 while the UI polls terrain_loaded, a separate busy flag, and the button shown to admins only.

### B-21 — The camera's 'See photos' link on the map opens the whole camera list instead of that camera's photos

*low · confirmed · ux · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** An extra hunt through the list to see what that camera caught.
- **Evidence:** Map.tsx:217 links to '/cameras'. Photos.tsx:59 already honours ?camera=<id> (pick.cameras holds IDs, sent as the cameras= query at :75).
- **Verifier:** Map.tsx:217 links 'See photos →' to /cameras, and Cameras.tsx reads no search params. Photos.tsx:58-60 already honours ?camera=<id> and sends it as cameras= to routes_photos (comma-separated camera ids).
- **Fix:** Link to `/photos?camera=${camera.id}`.

### B-22 — Bedding can't be renamed or reshaped from the map, and every zone type is drawn as 'Bedding'

*low · confirmed · feature · effort M* — `frontend/src/pages/Map.tsx`, `frontend/src/map/layers.ts`

- **What the hunter sees:** Tedious fixes to outlines; any non-bedding zone added via the API would be shown and described as bedding.
- **Evidence:** Map.tsx:219 hides Move for zones and there is no UI for PATCH /zones. Fixing one bad corner means Remove plus redraw. layers.ts:22 renders every zone in data.zones as bedding, and Map.tsx:207/218 labels any selected zone 'Bedding… Where the animals lie up', but the backend allows feeding/water/no_go (routes_zones.py:22) and bedding.py only protects kind=='bedding'.
- **Verifier:** The code agrees: no UI calls PATCH /zones, Move is hidden for zones (Map.tsx:219), layers.ts:22 renders every zone as bedding, and map_tonight returns all kinds (routes_zones.py:138). The UI only ever creates kind 'bedding', though, so mislabeled zones can only come from the API. The rest is a feature gap.
- **Fix:** Filter bedding-fill to kind=='bedding' (or have map_tonight return only bedding) now. Treat 'Edit outline' as a separate feature.

### B-23 — Two-finger pinch on phones also rotates the map, with no snap back to north

*low · plausible · ux · effort S* — `frontend/src/pages/Map.tsx`

- **What the hunter sees:** After a pinch-zoom the estate is a few degrees off north, which makes 'from the north-west' harder to match to the ground.
- **Evidence:** Map.tsx:74 constructs the map with default touchZoomRotate (rotation enabled) and dragRotate. Only the small 29 px compass (see B-16) resets it. The wind-bar arrow compensates (Map.tsx:191), but the satellite view, pins and labels stay skewed.
- **Verifier:** Default touchZoomRotate is enabled (Map.tsx:74). MapLibre starts rotating once the fingers twist about 25 px around the pinch circle (ROTATION_THRESHOLD), so pinch-zooms can rotate. I did not reproduce it. The claim that pins and labels stay skewed is wrong: DOM markers stay upright and only the imagery and GL layers rotate. Many map apps allow rotation on purpose, so this is a preference.
- **Fix:** `instance.touchZoomRotate.disableRotation()`, or snap the bearing to 0 on 'rotateend' when |bearing|<15°. Enlarging the compass button (B-16) also helps.

### B-24 — The satellite source has no max zoom, so zooming past the imagery's detail level asks for tiles that don't exist

*low · plausible · ux · effort S* — `frontend/src/map/layers.ts`, `frontend/src/pages/Map.tsx`

- **What the hunter sees:** Zooming in close to place a stand can turn the imagery grey or placeholder and show 'Part of the satellite picture didn’t load'.
- **Evidence:** layers.ts:3 raster source has no maxzoom (MapLibre default 22) and the map has no maxZoom (Map.tsx:74). Esri World_Imagery over rural Spain generally tops out around z19. Beyond that the service returns placeholder or error tiles instead of letting MapLibre overzoom, and any error also fires the permanent banner (B-01). Could not verify live because egress to server.arcgisonline.com is blocked in the sandbox.
- **Verifier:** The satellite source has no maxzoom (layers.ts:3) and the map has no maxZoom, so MapLibre requests z20-22 tiles. I could not verify how Esri responds for rural Spain: it may return 200 'Map data not yet available' placeholders rather than errors. App-driven zooms cap at 16 (fitEstate and the focus jump); only manual pinch-zoom reaches higher.
- **Fix:** Add `maxzoom: 19` to the raster source so MapLibre overzooms, and set the map's maxZoom to about 20.

### G-25 — Map 'Animal routes' are proximity lines, not movement evidence

*low · confirmed · data-correctness · effort S* — `backend/app/forecasting/bedding.py`

- **What the hunter sees:** Turning on 'Animal routes' shows a fan of confident lines that only encode distance.
- **Evidence:** bedding.py:395-417 draws a route from every bedding zone to every camera within 1.5 km that has >= 5 detections of any species, hidden rabbits included. No sequence or timing evidence is used, although the docstring and the Map layer copy say 'Routes come from camera sightings' and 'gated on repeat evidence'. Three bedding zones and five nearby cameras produce 15 'routes'. avg_hour (:384-393) averages clock hours across midnight (23 and 01 give 12), but it is not displayed.
- **Verifier:** bedding.py:375-417 links every bedding zone to every camera within BEDDING_RELEVANT_M=1500 m that has >= MIN_ROUTE_DETECTIONS=5 detections of any species, hidden included, with no timing or sequence evidence. Map.tsx:204 says 'Routes come from camera sightings'. avg_hour (:384-393) is a linear mean across midnight but is not rendered. Impact is limited: the layer is off by default (Map.tsx:43) and already drawn as a light dashed line (layers.ts:15).
- **Fix:** Rename the layer 'Cameras near bedding', or gate a link on visible-species visits within 0-3 h after sunset on >= N distinct nights. Drop avg_hour or use a circular mean.


## 15. Notifications that respect the hunter

### D-04 — Push alerts silently stop after a network blip, and Settings keeps saying 'This phone gets alerts'

*medium · confirmed · reliability · effort M* — `backend/app/notifications/push.py`, `frontend/src/components/NotificationSettings.tsx`, `frontend/public/sw.js`, `frontend/src/push.ts`

- **What the hunter sees:** After one server internet hiccup the hunter stops getting boar alerts with no sign anything changed. The screen contradicts itself, and the only way out is toggling Alerts off and on, which nobody would guess.
- **Evidence:** push.py:78-84 counts every network/DNS/TLS exception as a failure and deletes the subscription row after MAX_FAILURES=10 (push.py:26). dispatch sends one push per species per run, so two bad runs with 5 species are enough. 404/410 also deletes the row (push.py:67), and sw.js has no 'pushsubscriptionchange' handler, so a rotated endpoint is never re-registered. The UI decides 'subscribed' only from the browser's own PushSubscription (NotificationSettings.tsx:98, 185-188). The 'Get alerts on this phone' button only renders when device==='not_subscribed' (line 217), and nothing ever re-POSTs an existing subscription. PROVEN backend (scratchpad/D/test_area_d.py::test_transient_push_errors_silently_delete_the_subscription): 10 ConnectionErrors left rows=0, settings.subscriptions=0, and POST /notifications/test returned 400. PROVEN UI (scratchpad/D/pw/push_drift.cjs): with the browser still holding a subscription and the server holding none, the section reads 'This phone gets alerts.', has no re-subscribe button, and after 'Send a test' shows 'No phone is getting alerts yet. Turn alerts on from that phone first.' right next to it.
- **Verifier:** Backend reproduced: 10 ConnectionErrors from push.py:78-84 deleted the row, and /notifications/test then returned 400. The UI takes 'subscribed' only from the browser (NotificationSettings.tsx:98,185-188), the re-subscribe button needs device==='not_subscribed' (line 217), and sw.js has no pushsubscriptionchange handler. The push_drift run showed 'This phone gets alerts.' next to the 400 message. Downgraded because pushes are only attempted when new detections exist (dispatch.py:205), and that usually needs the same internet link that sync uses, so '10 failures from one blip' is rarer than claimed. The drift itself is real and never self-heals.
- **Fix:** Priority 1 is self-heal on app start as well as on Settings mount: if permission is granted and currentSubscription() exists, POST it to /notifications/subscriptions (it is an idempotent upsert). In push.py, keep the 404/410 deletion and replace the failure counter with age-based expiry, e.g. drop when last_success_at is older than 14 days and failures > N. The SW cannot call the API because the token is in localStorage, so a pushsubscriptionchange handler can only stash the new endpoint for the page to POST.

### D-14 — Quick taps on 'which animals' leave the server with a different alert list from the one on screen

*medium · confirmed · data-correctness · effort S* — `frontend/src/components/NotificationSettings.tsx`

- **What the hunter sees:** The hunter turns on alerts for deer and boar and only gets boar, or keeps getting alerts they switched off, with nothing on screen to say so.
- **Evidence:** toggleSpecies (NotificationSettings.tsx:140-155) PUTs the full species_ids list on every tap. Requests can land out of order, savingId holds only one id so the first switch is re-enabled while its save is still in flight, and a failure reverts to a snapshot taken before the tap, which also discards later taps. PROVEN (scratchpad/D/pw/species_race.cjs), tapping boar then deer 150 ms apart with the first PUT slow. Slow case: screen shows boar=true deer=true, server stored ['wild_boar']. Failure case (first PUT 503): screen shows boar=false deer=false, server stored ['wild_boar','red_deer'], and no error text.
- **Verifier:** Reproduced with species_race.cjs. Slow first PUT: the screen showed boar and deer on while the server stored only ['wild_boar']. First PUT failing: the screen showed both off while the server stored both, and there was no error text. toggleSpecies (NotificationSettings.tsx:140-155) PUTs the full list from a closure snapshot, reverts to a pre-tap `before`, and savingId tracks only one id. Out-of-order arrival is less likely over HTTP/2 through Cloudflare, but the failure-revert path is realistic on weak signal.
- **Fix:** Keep a desiredRef and a single in-flight save. When a save finishes, send again if desiredRef has changed since. On failure, refetch /notifications/settings rather than restoring a stale snapshot, and show a one-line message.

### G-23 — Alerts count burst frames as 'times', repeat camera faults already shown on Tonight, contradict 'Changed', and can say '-40m ago'

*medium · confirmed · ux · effort S* — `backend/app/forecasting/alerts.py`, `frontend/src/pages/Tonight.tsx`

- **What the hunter sees:** The Alerts card overstates activity, repeats faults, contradicts the line above it, and can show nonsense ages.
- **Evidence:** alerts.py:55-68 builds 'Seen {n} times in the last 2 days' from raw Detection rows, so one sounder loitering for a 30-frame burst reads 'Seen 30 times'. alerts.py:92-116 lists offline and out-of-credits cameras, which Tonight.tsx:314-325 already shows under 'Cameras not sending', so the same camera appears twice on one screen. alerts.py:97-110 'quiet' ignores exposure and hidden species and uses its own thresholds, so it can say 'X quiet ... usually sees more' while the Changed line says 'Nothing changed' (for example during a classifier backlog). alerts.py:21-33 has no clamp: PROVEN in a python REPL, _ago(now+40min) returns '-40m ago' for any captured_at in the future (e.g. a camera clock left on summer time after 25 Oct).
- **Verifier:** alerts.py:55-68 counts raw Detection rows ('Seen 30 times' for one burst). alerts.py:77-89 lists offline and out_of_credits cameras, which forecast_tonight also returns as f.alerts (model.py:292-295), so Tonight.tsx:314-346 shows the same camera in both 'Cameras not sending' and 'Alerts'. _dur (alerts.py:27-34) has no clamp, so a future captured_at (e.g. a camera clock left on CEST after 25 Oct) gives '-40m ago'. The quiet alert (:97-110) ignores exposure and counts hidden species, so hidden rabbits can also hide a genuinely quiet camera.
- **Fix:** Count visits with visits_by_night (hidden excluded) for sightings. Drop offline and out_of_credits from /alerts, since Tonight already shows them, and keep low_battery. Base the quiet alert on CONFIRMED nights and suppress it when whats_changed names the same camera. In _dur, use s = max(0, s) and return 'just now' below 60 s.

### K-06 — One sounder at a feeder buzzes the phone every 15 minutes all night

*medium · confirmed · ux · effort S* — `backend/app/notifications/dispatch.py`, `frontend/public/sw.js`, `backend/pipeline.py`

- **What the hunter sees:** Hunters who turn on boar alerts get woken repeatedly through the night and will mute or uninstall the alerts, losing the feature.
- **Evidence:** dispatch_new_sightings (dispatch.py:140-228) groups only within one run and has no per-species cooldown across runs and no quiet hours. The sync runs every 15 min. sw.js:123-124 sets tag=species and renotify:true, so each replacement banner sounds and vibrates again. PROVEN with scratchpad/K/test_k_nightbuzz.py (push.send_to_user patched): one boar frame per 15-minute sync from 00:55 to 02:40 Madrid time gives 8 pushes, 'Wild boar at PL19 | 1 photo at 00:55.' … '1 photo at 02:40.', all tag sighting-wild_boar. Not covered by J-20 (a daily plan push) or J-21 (silence during a sit).
- **Verifier:** I re-ran test_k_nightbuzz.py and got 8 pushes between 00:55 and 02:40 Madrid time, all tagged sighting-wild_boar. dispatch.py:140-228 groups only within one run and has no cooldown across runs. NotificationPref (models.py:482-499) has no quiet hours. The sync task runs every 15 min (docs/09-deployment.md:51) and dispatches at the end of each classification pass (species.py:67-69). sw.js:124 sets renotify:true whenever a tag is present, so every replacement banner sounds again.
- **Fix:** Keep a last-sent time per (user, species) in AppSetting or on Notification. Within about 2 h, send the push with renotify:false (a silent banner update) rather than skipping it. In sw.js, take renotify from the payload instead of Boolean(tag). Quiet hours in Europe/Madrid local time are an optional second step.

### D-17 — Signing out leaves the phone subscribed to that person's alerts

*low · confirmed · security · effort S* — `frontend/src/components/Layout.tsx`, `frontend/src/pages/Admin.tsx`, `backend/app/api/routes_notifications.py`

- **What the hunter sees:** A borrowed or shared phone keeps buzzing with the previous hunter's sightings. The new person is told they are set up when they are not.
- **Evidence:** Both sign-out paths (Layout.tsx:55-58, Admin.tsx:565-569) only clear the token. The push subscription row stays owned by the signed-out user (routes_notifications.py:173-192 re-homes it only when someone else subscribes from that device). The next person to sign in on that phone sees 'This phone gets alerts.', because the browser still holds the subscription (NotificationSettings.tsx:98, 185-188). Their own s.subscriptions is 0, so their 'Send a test' fails with 400, as in D-04. Verified by reading the code; the UI half matches the push_drift.cjs run.
- **Verifier:** Confirmed from the code: both sign-out paths (Layout.tsx:55-58, Admin.tsx:565-569) only call setToken(null). The push row stays with the old user until someone else POSTs from that device (routes_notifications.py re-homes it in subscribe), so a signed-out phone keeps getting that user's alerts. A new user sees 'This phone gets alerts.' with the Alerts switch off (their prefs default to disabled in prefs.py). Turning it on re-homes the row, so this does recover. Low, because phones are rarely shared on a single estate.
- **Fix:** No change needed; the proposed shared logout() helper is right. Its unsubscribe call should be best-effort with a short timeout, so sign-out still works offline.

### D-19 — Turning Alerts on asks for notification permission only after a network round trip, which may lose the tap on iPhone

*low · plausible · bug · effort S* — `frontend/src/components/NotificationSettings.tsx`, `frontend/src/push.ts`

- **What the hunter sees:** On an installed iPhone app with weak signal, turning Alerts on can fail with a vague message and no system prompt. That is the main way iPhone users enable alerts.
- **Evidence:** setEnabled (NotificationSettings.tsx:107-110) awaits the PUT /notifications/settings first and only then calls subscribeThisDevice, whose first line is Notification.requestPermission() (push.ts:84). WebKit only grants push permission prompts 'in response to direct user interaction' (transient activation). On a slow link the activation from the tap can expire before requestPermission runs, and the hunter then sees 'Permission was not given.' without ever seeing a prompt. subscribeHere (line 130) does not have this problem. Not reproducible headless; this finding comes from reading the code and WebKit's documented user-gesture requirement.
- **Verifier:** The code order is as described: setEnabled awaits the PUT (NotificationSettings.tsx:107) before subscribeThisDevice calls Notification.requestPermission (push.ts:84), while subscribeHere calls it straight from the tap. WebKit and Firefox gate the permission prompt on transient user activation, which can expire during a slow PUT. It can't be reproduced headless, and it only affects first-time enabling on a slow link.
- **Fix:** No change needed; calling requestPermission first, before any await, is the right fix.

### D-21 — Alert text gives no day, and the summary alert opens Photos under the hunter's last filter

*low · confirmed · ux · effort S* — `backend/app/notifications/dispatch.py`, `frontend/src/pages/Photos.tsx`

- **What the hunter sees:** A morning alert saying '23:50' reads as tonight, and tapping '7 new sightings' can open a Photos list that doesn't show them.
- **Evidence:** compose() (dispatch.py:120) prints only HH:MM, but notify_lookback_hours=24. PROVEN via a python snippet: a boar captured 25 Sep 23:50 and pushed the next morning reads '1 photo at 23:50.' The summary notification uses url=FEED_URL '/photos' with no species (dispatch.py:191), and Photos without params restores the last saved chip choice (Photos.tsx:56-62), so the new sightings can be filtered out.
- **Verifier:** Re-run: compose() gives ('Wild boar at PL19', '1 photo at 23:50.') for a 25 Sep 23:50 Madrid capture, with no day (dispatch.py:120). The summary uses url=FEED_URL '/photos' (dispatch.py:191), and Photos.tsx:56-62 falls back to readPick() when there are no params. The summary path only fires when more than 5 wanted species appear in one run, which is rare. The DST handling is correct (astimezone).
- **Fix:** No change needed; the proposed fix is fine as written.

### I-14 — Two quick taps on alert switches can lose one: the screen shows it on, the server has it off

*low · plausible · bug · effort S* — `frontend/src/components/NotificationSettings.tsx`, `backend/app/api/routes_notifications.py`

- **What the hunter sees:** The hunter believes they will be told about badger or boar and never are.
- **Evidence:** NotificationSettings.tsx:140-155 PUTs the whole species_ids list on every tap, with no ordering. The backend replaces the list (routes_notifications.py:80-85). Proven with I/f_notif.cjs: the first PUT is held 3 s (weak signal); tap Fox, then Badger. UI shows fox=on, badger=on. Server has badger=false, and after a reload Badger shows off. A failed PUT also restores the whole earlier state (line 152), which can undo a different switch that did save.
- **Verifier:** The code race is real. Each tap PUTs the full species list with no sequencing, only the tapped row is disabled (NotificationSettings.tsx:140-155, 245), and a failure reverts to the whole earlier snapshot. But the repro forced the first PUT to arrive 3 s after the second. Two PUTs sent about 1 s apart over one HTTP/2 connection through Cloudflare rarely arrive out of order.
- **Fix:** Serialise the writes, sending the latest desired list after the in-flight PUT resolves. On failure, re-GET the settings rather than restoring the old snapshot.

### I-21 — Sign out leaves the phone getting the old account's alerts, plus its queued sit reports and cached plan

*low · confirmed · security · effort S* — `frontend/src/components/Layout.tsx`, `frontend/src/pages/Admin.tsx`, `frontend/src/push.ts`, `frontend/public/sw.js`

- **What the hunter sees:** A borrowed or shared phone keeps buzzing with someone else's sightings, and their queued reports get replayed under the next login.
- **Evidence:** Both Sign out buttons only call setToken(null) (Layout.tsx:55-58, Admin.tsx:565-569). They never call unsubscribeThisDevice(), so the push subscription stays registered to the old user on the server. Proven for storage with I/f_401.cjs: after Sign out, localStorage still holds gs_sit_queue and gs_cache:/forecast/tonight. The service worker's API cache (sw.js:23) is keyed by URL only, so the next person signing in on this device can see the previous person's cached /api/sits offline.
- **Verifier:** Both sign-outs only call setToken(null) (Layout.tsx:55-58, Admin.tsx:566-568). The push subscription stays assigned to the old user until another user subscribes and re-homes it (routes_notifications.py:111-114), and gs_sit_queue and gs_cache:* survive. The 'security' framing is overstated: /api/sits and the forecast are estate-wide data every user can already read (routes_stands.py:210-220).
- **Fix:** The proposed logout() is right. Best effort: flush the queue, then unsubscribeThisDevice(), clear gs_sit_queue and gs_cache:*, and delete API_CACHE via postMessage or caches.delete from the page.

### J-21 — FEATURE: Silence sighting pushes while the hunter is sitting

*low · plausible · feature · effort S* — `backend/app/notifications/dispatch.py`, `frontend/public/sw.js`

- **What the hunter sees:** The phone lights up and buzzes at the worst moment.
- **Evidence:** Why it fits: Sit Mode goes true black with no imagery to protect concealment (SitMode.tsx:5-13). Yet dispatch sends every sighting push with renotify:true (dispatch.py:205-212, sw.js:124), which lights the screen and buzzes in the high seat. Tactacam's 'Hunt Sync' holds photo delivery during a hunt session (tactacam.com/reveal-app-plan). Dispatch never checks sits today.
- **Verifier:** Dispatch never checks sits (dispatch.py:140-228), and the SW sets renotify for tagged pushes (sw.js:124). It fits the concealment goal, but `silent` is ignored on iOS web push, and hunters can mute their phones themselves. 'Currently sitting' cannot be detected reliably until J-03 fixes ended_at (today it is set on the first tap).
- **Fix:** After J-03: in dispatch_new_sightings, hold (do not send) pushes for users with a sit that has started_at set and ended_at null, and deliver them as one digest when the sit ends or in the morning. Do not rely on silent:true, and drop the optional 'animal on your stand's camera' push.

### K-07 — An alert tapped later opens nothing when 60+ newer photos of that animal have arrived since

*low · confirmed · bug · effort S* — `frontend/src/pages/Photos.tsx`, `backend/app/notifications/dispatch.py`

- **What the hunter sees:** 'Wild boar at PL19, 22:14' tapped the next morning drops the hunter at the top of a long boar feed with no sign of the photo they were told about.
- **Evidence:** The push URL is /photos?species=X&image=ID (dispatch.py:48-55). Photos.tsx:97-104 looks for ID only in the first page (PAGE=60, Photos.tsx:31). If it is not there, it silently drops the image param (setParams({})) and opens nothing. A sounder in 3-frame bursts easily adds 60+ frames overnight. PROVEN with Playwright (scratchpad/K/pw/deeplink_late.cjs, mocked /api/photos with 150 boar frames): a push naming img-95 gives 'lightbox open: false | url now: /photos' and the feed top shows 05:30. The control (deeplink_control.cjs, img-10) opens the lightbox. I-area verified the deep link only for a fresh photo.
- **Verifier:** Photos.tsx:97-104 looks for the image only in the first page (PAGE=60), then clears the params with setParams({}) and silently opens nothing. The feed is newest-first across all cameras (routes_photos.py:84), so 60 or more newer photos of that species push the target off page 1. Downgraded because the hunter still lands in the right species feed and can scroll to the time.
- **Fix:** Put the capture time in the push URL (&at=<captured_at>). On a miss, fetch /photos?species=X&before=<at+1ms>&limit=5 and open the first item whose image_id matches. Or add GET /photos/{image_id}. If it still isn't found (hidden or deleted), say so in one line instead of failing silently.


## 16. Glove-sized and small-screen UI polish

### A-21 — Species chips (34 px) and 'Edit list' (25 px) are below glove size

*low · confirmed · ux · effort S* — `frontend/src/pages/tonight.css`

- **What the hunter sees:** The species chips are the Tonight control a hunter uses every evening. With gloves at dusk they hit the neighbouring chip, and each mis-tap triggers the 4-request reload. 'Edit list' is a 25 px link.
- **Evidence:** tonight.css:9-16: .tn-chip has min-height 34px, and .tn-chip-edit is 12px text with 5px 6px padding. Measured with Playwright at 390 px width: each chip is 80×34 px and 'Edit list' is 52×25 px. The app's own minimum elsewhere is 44 px (tonight.css:73; map.css:5, 10, 92).
- **Verifier:** Measured in my Playwright rerun at 390 px: chip 80×34 and 'Edit list' 52×25. CSS is .tn-chip min-height 34px and .tn-chip-edit padding 5px 6px (tonight.css:9-16), against 44 px used elsewhere (tonight.css:73). This is a polish item, so low.
- **Fix:** The proposed fix is right. Check that the chip row still wraps cleanly at 360 px once chips grow to 44 px.

### B-16 — Some map controls are too small for gloves; the zoom buttons shrink to 29 px because MapLibre's stylesheet overrides ours

*low · confirmed · ux · effort S* — `frontend/src/map/map.css`, `frontend/src/pages/Map.tsx`

- **What the hunter sees:** Hunters wearing gloves at dusk miss the close and zoom buttons.
- **Evidence:** Measured in Playwright on 390×844 touch (s_targets.cjs, s_move.cjs): selection-peek '×' clear button 8×44 px (map.css:10 .map-link has 0 horizontal padding, Map.tsx:207). MapLibre zoom +/− and compass render 29×29 even though map.css:46 sets 40×40: map/map.css ships in the main CSS (Stands imports it), and maplibre-gl.css loads later in the Map chunk with the same specificity and wins. The notice 'OK' button is 33×36.
- **Verifier:** Measured with s_targets.cjs: clear-selection × is 8x44, zoom + is 29x29, notice OK is 33x36. The built CSS shows the 40px rule in index-*.css and MapLibre's 29px rule in the later-loaded Map-*.css, with equal specificity, so MapLibre's rule wins.
- **Fix:** As proposed: raise specificity (`.estate-map .maplibregl-ctrl-group button{width:44px;height:44px}`) and give the × and message buttons a 44 px minimum.

### C-24 — Touch targets too small for gloves: the 26px hide button sits on the photo, chips are about 26px, and the name vs card tap zones overlap

*low · confirmed · ux · effort S* — `frontend/src/pages/cameras.css`, `frontend/src/pages/animals.css`, `frontend/src/pages/photos.css`, `frontend/src/pages/Animals.tsx`

- **What the hunter sees:** With gloves at dusk, hunters hide the wrong photo, miss chips, or get a rename prompt when they meant to select.
- **Evidence:** cameras.css:74-78 .cam-flag is 26x26px and sits on top of the thumbnail, whose tap opens the lightbox. A miss either opens the photo or hides it. animals.css:23-26 .an-chip has 5px vertical padding and 12px text, about 26px tall with no min-height. photos.css:5 .photos-chip has min-height 32px. On Animals, tapping the name text renames while tapping anywhere else on the card selects it (Animals.tsx:321, 342). Proven by reading the CSS.
- **Verifier:** From the CSS: .cam-flag is 26×26 and sits on the thumbnail (cameras.css:74-78). .an-chip has 5px padding, 12px text and no min-height (animals.css:23-26), about 26-30px tall. .photos-chip has min-height 32px (photos.css:5). The Animals name div stops propagation and renames, while the rest of the card selects (Animals.tsx:321, 342). Hiding by mistake is reversible from the empties view.
- **Fix:** Give .cam-flag a 44px hit area (a transparent ::before inset or padding) and keep the visual at 26px. Set min-height: 44px on .an-chip and .photos-chip (at least 40px). Move rename to an explicit 'Name' button in the selection bar instead of a tap on the text.

### C-26 — Error messages show raw browser and server text instead of plain words

*low · confirmed · ux · effort S* — `frontend/src/pages/Photos.tsx`, `frontend/src/pages/Cameras.tsx`, `frontend/src/pages/Animals.tsx`, `frontend/src/api.ts`

- **What the hunter sees:** With no signal on the hill, the page reads 'Could not load photos: Failed to fetch'.
- **Evidence:** Photos.tsx:179 'Could not load photos: {e.message}', Cameras.tsx:386 'Cameras did not load. {err}', Animals.tsx:208 and 291 and Cameras.tsx:362 all render e.message. Offline, fetch throws 'Failed to fetch' (non-cached API paths pass straight through sw.js:84-86). Server errors become 'Something went wrong (500)' (api.ts:47), and role errors become 'Admin privileges required'. Only the Animals gallery (line 108) uses hunter wording ('Check your signal and try again').
- **Verifier:** These render raw e.message: Photos.tsx:179, Cameras.tsx:282/386 and 362, Animals.tsx:84/208 and 169-195/291. sw.js:86 passes non-cached API calls straight through, so offline fetch throws 'Failed to fetch' (Chrome) or 'Load failed' (Safari). api.ts:47 produces 'Something went wrong (500)' and backend role strings like 'Admin privileges required'. Only the gallery (Animals.tsx:108) uses hunter wording.
- **Fix:** Add a friendlyError(e) helper in api.ts: TypeError or offline gives 'No signal. Showing nothing new until you're back in range.', 5xx gives 'The server had a problem. Try again in a minute.', 403 gives 'Only the estate admin can do that.'. Use it in these pages.

### D-10 — After sign-in the hunter lands on Tonight, not on the photo the alert pointed to or the page they were on

*low · confirmed · ux · effort S* — `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/pages/Login.tsx`

- **What the hunter sees:** Tap 'Wild boar at PL19', sign in, and the boar photo is gone. The hunter has to go and find it.
- **Evidence:** RequireAuth (App.tsx:27) redirects to '/login' and drops the location. The 401 handler (api.ts:40) goes to '/login?expired=1', also without the path. Login.tsx:19 always runs nav('/'). PROVEN (scratchpad/D/pw/deploy_and_login.cjs). Opening '/photos?species=wild_boar&image=abc' (a notification deep link) while signed out went to /login and, after signing in, to '/'. A session that expired on /photos also came back to '/' after re-sign-in.
- **Verifier:** Reproduced: signed out, opening /photos?species=wild_boar&image=abc went to /login and then to '/'. After an expiry on /photos, re-sign-in also landed on '/'. RequireAuth (App.tsx:27), api.ts:40 and Login.tsx:19 all drop the destination. Downgraded because sessions last 30 days, so this happens roughly once a month.
- **Fix:** Pass next= as proposed. Validate it with next.startsWith('/') && !next.startsWith('//') so a protocol-relative URL can't make it an open redirect, and navigate with { replace: true }.

### D-13 — Settings loaders never end and failed saves give no feedback

*low · confirmed · ux · effort S* — `frontend/src/pages/Admin.tsx`, `frontend/src/components/NotificationSettings.tsx`

- **What the hunter sees:** On weak signal the settings screen either loads forever or looks saved when it isn't.
- **Evidence:** 'Animals in the advice' renders 'Loading…' whenever species.length===0 (Admin.tsx:299-300), but the fetch error is swallowed (line 143). PROVEN (scratchpad/D/pw/settings.cjs): with /api/species returning 502, the section still said 'Loading…' after 4 s and offered no retry. The same text shows forever if every species is hidden or none exist. Toggle failures revert with no message in Admin.toggleSpecies (249-252), hideSpecies (263-265) and NotificationSettings.toggleSpecies (151-153). In NotificationSettings.setEnabled (101-123), when the PUT fails the optimistic enabled value is kept (setS at line 105, never reverted, and refreshSettings also fails offline), so the Alerts switch shows ON while the server still has OFF. checkUpdates swallows errors (Admin.tsx:273).
- **Verifier:** Reproduced: with /api/species returning 502, 'Loading…' stayed on screen for more than 4 s with no retry (Admin.tsx:143 swallows the error, lines 299-300 test species.length===0). Toggle reverts are silent. setEnabled keeps the optimistic value when offline. Part of this overlaps D-12 (swallowed Admin failures) and D-14 (NotificationSettings reverts). Two sub-claims are wrong: 'all species hidden' doesn't show Loading, because hidden rows stay in the array and render under 'Hidden everywhere'; and setEnabled's catch does set a message, just a raw 'Failed to fetch'.
- **Fix:** Keep a per-section error with Retry, and show a separate 'No animals yet' state when the list is genuinely empty. In setEnabled's catch, revert s.enabled and replace the raw fetch error with a hunter-worded line.

### D-15 — Settings switches and buttons are too small for gloved thumbs (26–27 px tall)

*low · confirmed · ux · effort S* — `frontend/src/components/Toggle.tsx`, `frontend/src/pages/Admin.tsx`, `frontend/src/components/NotificationSettings.tsx`

- **What the hunter sees:** With gloves or cold hands, taps miss or hit the neighbouring control. Hide and Remove are the dangerous neighbours.
- **Evidence:** Toggle.tsx:26-27 is 46x26. smallBtn (Admin.tsx:92-101, NotificationSettings.tsx:35-44) uses padding 5px 10px at 12px text. PROVEN, measured in Chromium at 390 px (scratchpad/D/pw/settings.cjs): every switch 46x26, 'Hide' 47x27, 'Send a test' 83x27, 'Remove' 67x27, 'Edit limits' 75x27, 'Add login'/'Change password' 320x37. The guideline is 44 px minimum. 'Hide' sits 10 px from the in-advice switch, so a gloved miss hides the animal everywhere.
- **Verifier:** Measured again at 390 px: switches 46x26 (Toggle.tsx:26-27), Hide 47x27, Send a test 83x27, Remove 67x27, Edit limits 75x27, Add login and Change password 320x37. Hide is 10 px from the switch (gap:10 at Admin.tsx:321). Downgraded because these are setup-screen controls and Hide can be undone with 'Show again'.
- **Fix:** No change needed; the proposed fix is fine as written.

### D-16 — Back after signing in shows the login form again, and a typo there signs the hunter out

*low · confirmed · bug · effort S* — `frontend/src/pages/Login.tsx`, `frontend/src/api.ts`

- **What the hunter sees:** Android's back gesture from Tonight looks like being logged out. Signing in again with a typo reports 'you were signed out' instead of 'wrong password', and actually signs them out.
- **Evidence:** Login.tsx:19 calls nav('/') without replace, and Login never redirects when a token already exists. /auth/login is sent with the stored token (api.ts:29), so a wrong password there returns 401-with-token, which api.ts:37-38 treats as session expiry. PROVEN (scratchpad/D/pw/back.cjs). After sign-in, Back showed /login with the form visible and the token still set. A mistyped password then showed 'You were signed out. Sign in again.' and cleared the token.
- **Verifier:** Reproduced: after sign-in, Back showed /login with the form and the token still set. A mistyped password there then read 'You were signed out. Sign in again.' and cleared the token. Login.tsx:19 pushes without replace, and api.ts:29/37-38 sends the stale token with /auth/login and treats the 401 as an expired session. Downgraded because it happens once per sign-in and does no harm unless the password is mistyped.
- **Fix:** As proposed, plus: in api(), skip both the Authorization header and the expiry branch when path === '/auth/login'.

### D-24 — 'Add person' and 'Change password' can be submitted twice and then report an error after succeeding

*low · plausible · ux · effort S* — `frontend/src/pages/Admin.tsx`

- **What the hunter sees:** The hunter is told the password change failed when it actually succeeded, and then locks themselves out trying the 'old' one.
- **Evidence:** addUser (Admin.tsx:149-159, button at 482-485) and changePw (229-241, button at 498-501) have no busy state. A double tap on a slow link sends two requests. The second one fails ('Someone with that email already has a login', possibly a 500 from the unique constraint if both pass the pre-check, or 'That is not your current password' once the first commit lands), and whichever finishes last sets the message. Not run live.
- **Verifier:** addUser and changePw (Admin.tsx:149-159, 229-241) have no busy flag, and their buttons are disabled only on input validity (lines 483, 499), so they stay enabled while a request is in flight. users.email is unique (models.py:44), so a racing double add can 500, and a second change-password can report 'That is not your current password' after the first succeeded. Not run live.
- **Fix:** Add busy flags as proposed. Also map an IntegrityError in create_user to a 400 'Someone with that email already has a login'.

### G-21 — Insights jumps 547 px when the findings arrive after the weather section

*low · confirmed · ux · effort S* — `frontend/src/pages/Insights.tsx`

- **What the hunter sees:** The Weather section appears at the top and then slides below the fold just as the hunter reaches to tap a scope chip, so the tap lands on something else.
- **Evidence:** Insights.tsx:148 renders WeatherPatterns unconditionally, while the findings and 'Who is on the cameras' blocks above it render only once /insights resolves (:102-146). /insights/patterns is often faster once its weather is cached (56 ms vs 87 ms measured). PROVEN (G/pw/jump.cjs, Playwright with the built dist, 390x844 viewport, /api/insights delayed 1.5 s): the 'All animals' scope chip moves from y=282 to y=829, a 547 px jump. Screenshot at G/pw/before.png.
- **Verifier:** Insights.tsx:148 renders WeatherPatterns unconditionally, while the findings and composition blocks (:102-146) wait for /insights. Re-ran G/pw/jump.cjs against the built dist at 390x844: the scope chip moves from y=282 to y=829 (547 px). The artificial 1.5 s delay overstates how often a tap lands wrongly: server times are 84 vs 56 ms. It is a real layout shift but low impact.
- **Fix:** Render WeatherPatterns only once /insights has settled (d set or err set), or give the findings and composition blocks min-height skeletons while d is null.

### I-08 — Stands list jumps when the wind arrives, moving Reserve buttons under the thumb

*low · confirmed · ux · effort S* — `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** On a slow connection the buttons move just as the hunter taps, and they can reserve or open the wrong stand.
- **Evidence:** Stands.tsx:41 loads /map/tonight separately. Lines 91-95 and 101-105 then insert the wind line and the 'Wind details' fold into every card once it lands. Crawl measured CLS 0.287 on a 390x844 phone. Proven with I/f_standsjump.cjs (map/tonight delayed 2.5 s). Reserve y before: 301 / 443 / 585 / 727. After: 348 / 593 / 838 / 1083. A tap aimed at Charca stand's Reserve (y=443) now lands inside the Barranco high seat card. Screenshots: shots/stands_before_wind.png, shots/stands_after_wind.png. Smaller jumps: Insights CLS 0.13 (weather block) and Cameras 0.12 (photo strips).
- **Verifier:** Stands.tsx:41 loads /map/tonight separately; it is always slower than /stands (weather call, ~0.35 s against 0.01 s measured). Lines 95 and 101-105 then insert the wind line and the fold, pushing the Reserve buttons down. Downgraded because the miss-tap window is short and a wrong reservation is visible and can be cancelled.
- **Fix:** Always render the wind line slot with a fixed min-height ('Checking wind…'). Or make /stands include the cached wind status so no second request changes the layout.

### I-16 — Primary controls are too small for gloves; 'Hide' sits right next to the advice switch

*low · confirmed · ux · effort S* — `frontend/src/components/Toggle.tsx`, `frontend/src/pages/Admin.tsx`, `frontend/src/pages/Tonight.tsx`, `frontend/src/pages/Photos.tsx`, `frontend/src/pages/Animals.tsx`, `frontend/src/components/Layout.tsx`

- **What the hunter sees:** Gloved, one-handed taps miss. Missing the advice switch hides the animal from the whole app, and 'Show again' leaves it out of the advice.
- **Evidence:** Measured by the crawl (I/crawl.cjs and crawl.json; I/f_settings.cjs with every section open). Every switch is 46x26 (Toggle.tsx:21-33). 'Hide <animal> everywhere' is 47x27 and sits 10 px left of the switch (Admin.tsx:321-331). Other sizes: Tonight 'I'm after' chips 34 px tall, 'Edit list' 52x25, Photos chips 32 px, Animals class chips 29 px, 'Send a test' 83x27, 'Remove' 67x27, map zoom buttons 29x29, tablet (768) top-nav links 32 px, Insights gallery 'Close' about 26 px.
- **Verifier:** The sizes are in the code: Toggle is 46x26 (Toggle.tsx:26-27), smallBtn has padding 5px 10px and 12px text (Admin.tsx:92-100), .tn-chip has min-height 34px, and .photos-chip min-height 32px. These pass WCAG AA (24 px) but miss the 44 px guidance. Downgraded because the smallest targets are rarely used Settings controls, Hide is admin-only, and Sit Mode's in-field controls are already 64 px or more.
- **Fix:** The proposed fix is right. Prioritise the Tonight and Photos chips, which are used in the field, and put 'Hide everywhere' behind a confirm or an Undo.

### I-22 — Signing in again drops the hunter on Tonight instead of the photo or page they opened

*low · confirmed · ux · effort S* — `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/pages/Login.tsx`

- **What the hunter sees:** Tapping a sighting alert after the session lapses loses the photo the alert was about.
- **Evidence:** On 401, api.ts:37-43 goes to /login?expired=1 without the current path. RequireAuth (App.tsx:27) does the same, and Login.tsx:19 always nav('/'). Proven with I/f_deeplink.cjs: a notification link /photos?species=fox&image=… with an expired session goes to /login?expired=1, and after signing in lands on '/' with no photo open. A valid session opens the photo correctly ('Photo 3 of 60').
- **Verifier:** api.ts:40 redirects to '/login?expired=1', RequireAuth (App.tsx:27) redirects to '/login', and Login navigates to '/'. Neither redirect carries the original path, so a notification deep link such as /photos?image=… is lost after re-auth.
- **Fix:** The proposed fix is right. Validate next as a same-origin path that starts with '/' and not '//'.

### K-11 — On a 320 px screen (small phones, or 'Display size: Large' or Display Zoom), the Settings tab and sign-out sit off-screen behind an unmarked sideways scroll

*low · confirmed · ux · effort S* — `frontend/src/theme.css`, `frontend/src/components/Layout.tsx`

- **What the hunter sees:** Hunters who enlarge their phone's display for readability can't find Settings (alerts, sign-out) unless they happen to swipe the tab bar.
- **Evidence:** theme.css:385 gives .tabbar overflow-x:auto with a 48 px minimum per tab below 380 px, so 7 tabs plus padding make 352 px. theme.css:258 hides the header Sign out on phones ('lives in Settings'). PROVEN with Playwright on the real API (scratchpad/K/pw/narrow.cjs). At 320×568, every route has tabbar scrollWidth 352 against clientWidth 320, with hiddenTabs ['Settings']. At 360 px everything fits and no page scrolls sideways (checked all 7 routes). I-area measured only 390 and 768 px.
- **Verifier:** theme.css:385 sets min-width 48px per tab at 380px and below. With 7 TABS (Layout.tsx:27-35) and 8px padding on each side that is 352px, against a 320px viewport. The last tab, Settings, is mostly off-screen behind a scroll with no visible scrollbar. The header Sign out is hidden on phones (theme.css:258). This only affects 320-351px viewports.
- **Fix:** Below 380 px, drop the tab minimum to 44 px and shrink the side padding, or move Insights and Settings into a 'More' tab (the redesign spec's 3–5 tabs). At minimum, add a fade or arrow cue at the bar's right edge.

### K-13 — Installed Android app is locked to portrait, so rotating the phone to see a trail-cam photo bigger does nothing

*low · plausible · ux · effort S* — `frontend/public/manifest.webmanifest`, `frontend/src/components/PhotoLightbox.tsx`

- **What the hunter sees:** Checking whether that shape is a boar or a bush means pinch-zooming a small image with gloves, instead of just turning the phone.
- **Evidence:** manifest.webmanifest:10 sets "orientation": "portrait-primary". Android enforces this for installed PWAs (iOS ignores it). Trail-camera frames are landscape (16:9), so in the lightbox they fill about a third of a portrait screen, and the natural rotate-to-enlarge gesture is blocked. Not proven: manifest orientation only applies to an installed app, which Playwright can't emulate.
- **Verifier:** manifest.webmanifest:10 does set 'orientation': 'portrait-primary', and Chrome on Android applies manifest orientation to installed standalone apps. I could not test that on a device here. The lightbox already has zoom tools (the .ov-tool buttons), so the impact is minor.
- **Fix:** Set "orientation": "any" (or remove it) and make sure Tonight, Sit Mode and the tab bar tolerate landscape. If portrait must stay for other pages, call screen.orientation.unlock() or lock('any') while the lightbox is open (Android only).


## 17. AI accuracy

### F-06 — MegaDetector runs at ultralytics' default conf=0.25, so the 'conservative' 0.10 empty threshold never takes effect and faint animals are dropped as empty

*medium · confirmed · bug · effort S* — `backend/app/ai/detector.py`, `backend/app/ai/empty_filter.py`, `backend/app/ai/grouping.py`, `frontend/src/pages/Cameras.tsx`

- **What the hunter sees:** Distant, partial or IR-dim animals are hidden as 'No animal' and never classified or counted. These are exactly the frames the hunter asked the filter to keep. The 'Maybe' hint the UI was built to show never shows.
- **Evidence:** detector.py:58 calls model.predict(image_path, device='cpu', verbose=False) without conf. In the pinned ultralytics 8.4.66 (checked in the downloaded wheel), engine/model.py:524 sets `custom = {"conf": 0.25, ...}` as the predict default, and cfg/default.yaml:53 says 'defaults: predict=0.25'. No box under 0.25 is ever returned. So empty_filter.py:22 ANIMAL_THRESHOLD=0.10 has no effect, and every frame whose best box scores 0.10–0.25 gets max_conf=0.0 and is flagged empty (line 42). animal_conf is always 0.0 on empties, so the 'stored so the threshold can be re-tuned' promise fails, and the Cameras 'Maybe' tag (Cameras.tsx:463, animal_conf >= 0.05) can never appear. grouping.py CONF=0.2 has no effect either.
- **Verifier:** detector.py:193 passes no conf. In ultralytics 8.4.66 (wheel sha256 matches PyPI), engine/model.py:524-525 builds args = {**overrides, 'conf': 0.25, ..., **kwargs}, so every box under 0.25 is dropped. That makes ANIMAL_THRESHOLD=0.10 (empty_filter.py:22) and grouping CONF=0.2 dead code, detector-flagged empties always get animal_conf 0.0, and the 'Maybe' tag (Cameras.tsx:463) can never show for them. Downgraded from high: 0.2-0.25 is a common MegaDetector operating point, so only the 0.10-0.25 band is lost.
- **Fix:** Pass conf=0.05 in detect_animals. Ship it together with F-07's classifier confidence floor, because the 0.05-0.25 band holds many IR false positives (grass, branches) that would otherwise get argmax species labels. Re-scan the unreviewed frames flagged empty only for a bounded recent window (for example 30 days), as a background job, not in the dusk sync.

### F-07 — Classifier stores the top guess with no confidence floor or Iberian taxa list, even on box-less frames, and every new species defaults to huntable=True

*medium · confirmed · data-correctness · effort M* — `backend/app/ai/species.py`, `backend/app/ai/classifier.py`, `backend/app/models.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** The feed shows 'Moose' or 'Bison' on Spanish night frames. Sheep, farm dogs or birds that dominate a camera can become that stand's 'best species tonight' and appear as alert chips until someone turns them off in Settings.
- **Evidence:** species.py:25-27: with no boxes, classify_crop runs on the whole frame. classifier.py:197-199 returns the argmax of 34 DeepFaune classes whatever the probability (bison, moose, reindeer, wolverine, bear, beaver, marmot, raccoon, nutria and chamois cannot occur at Alatoz). species.py:18-20 creates the Species with huntable left at its default True (models.py:196), including dog, cat, cow, sheep, goat, bird and micromammal, and badger, which is protected in Spain. _camera_forecast (model.py:95-110) ranks a camera by the huntable species with the most Detection rows. Proven (scratch pytest): once the detector returned [] and the classifier returned ('moose', 0.08), a Detection species_id='moose', species_conf=0.08, bbox=None was written, and Species('moose').huntable is True.
- **Verifier:** classify_crop takes the argmax over all 34 DeepFaune classes with no floor (classifier.py:126-129). _ensure_species creates new species with huntable at its model default True (species.py:18-20, models.py:196-198). The Tonight ranking uses the huntable species with the most Detection rows (model.py:95-110). The box-less whole-frame path is mostly reached through user-flagged 'animal' frames, which is legitimate, so the main defects are the missing floor and the huntable default.
- **Fix:** Keep an estate allow-list and a confidence floor. DeepFaune's own tool uses ~0.8 and returns 'undefined' below it, so store species_id NULL below ~0.5-0.8. Set huntable from a GAME set only when a species is created. Do not rewrite huntable on existing rows, which would overwrite choices the hunter already made in Settings; show a one-time Settings nudge instead.

### F-18 — Nested boxes, or two adults at different distances, turn a lone boar or deer into 'Sow + piglets' / 'Hind + calf'

*medium · confirmed · data-correctness · effort S* — `backend/app/ai/grouping.py`, `backend/app/forecasting/model.py`

- **What the hunter sees:** Tonight's expectation chips and the photo labels claim 'Sow + piglets' for a single boar or two adults. That matters for shoot / no-shoot decisions and hides real 'Boar' labels.
- **Evidence:** grouping.py:32-44 calls the frame juvenile when the smallest box area is under 40% of the largest. It does not account for one box sitting inside another (MegaDetector often boxes the forequarters or head of a close animal separately) or for perspective (an adult 15 m behind another is much smaller). class_label maps the result to 'Sow + piglets' and 'Hind + calf' (model.py:170,178), and it overrides the sex label. Proven on synthetic boxes: group_type([whole boar 0.92, box inside it 0.31], 'wild_boar') == (2, 'sow_with_piglets'). How often MegaDetector produces this was not measured.
- **Verifier:** group_type([whole boar 0.92, box inside it 0.31], 'wild_boar') returns (2, 'sow_with_piglets') (grouping.py:32-44). The perspective case, a second adult further back with under 40% of the area, is common on trail cameras. class_label checks sow_with_piglets and hind_with_calf before sex (model.py:170,178), so the group label overrides a vision 'Boar' or 'Stag'. How often MegaDetector produces nested boxes is unmeasured.
- **Fix:** The proposed fix is sound. Also note: once F-06 lowers the detector's conf, grouping's CONF=0.2 filter becomes active and must stay above the detector's threshold.

### F-19 — Species is decided frame by frame, so one burst can flip between species and split one visit into several

*medium · plausible · data-correctness · effort M* — `backend/app/ai/species.py`, `backend/app/forecasting/exposure.py`

- **What the hunter sees:** Photos of one animal show different species from frame to frame. Visit counts and 'seen N of the last 7 nights' pick up misreads as extra species.
- **Evidence:** species.py:24-38 classifies each frame on its own. exposure.visits_by_night partitions by (camera_id, species_id), so a burst read as red_deer / fallow_deer / red_deer counts two species and extra visits, and the feed labels consecutive frames of one animal differently. classifier.py:113 also squashes each box to 182×182 without keeping its aspect ratio. DeepFaune's own pipeline makes a square crop, so long side-on boar and deer boxes are distorted. Not measured on estate data.
- **Verifier:** classify_image works frame by frame (species.py:24-38), and visits partition by species, so a misread frame creates a separate species visit. classifier.py:113 squashes the rectangular box to 182x182, whereas DeepFaune's own pipeline crops a square around the box, so crops are systematically distorted relative to training. The accuracy impact on estate data is unmeasured.
- **Fix:** Do the square-padded crop (side = max(w,h), centred on the box) first. It is a small change and addresses a systematic input mismatch. Burst majority voting can follow.

### F-16 — A photo flagged by the hunter while a scan is running is overwritten by the scan

*low · confirmed · bug · effort S* — `backend/app/ai/empty_filter.py`, `backend/app/api/routes_images.py`

- **What the hunter sees:** The hunter hides a fresh 'Unknown animal' that is really grass or a person. Once the scan reaches it, the photo comes back with a teal 'reviewed' border, as if the tap did nothing.
- **Evidence:** scan_unprocessed loads up to 5000 Image objects up front (empty_filter.py:47-50), then for each one checks `image.reviewed` on that stale object (line 27) and writes is_empty_frame and processed_at (29-42). A POST /images/{id}/flag (routes_images.py:84-86) committed in between is not seen. Proven (scratch pytest with two sessions): a flag of is_empty=True arrived during the scan, and afterwards the row was reviewed=True, is_empty_frame=False.
- **Verifier:** Reproduced: a flag committed from a second session during the scan ended as reviewed=True, is_empty_frame=False. SessionLocal uses expire_on_commit=False (core/db.py), so the stale reviewed=False loaded at empty_filter.py:50 is never refreshed. Downgraded to low because the window is only the scan itself: seconds to a minute in steady state, longer during backfills.
- **Fix:** Make the write conditional (UPDATE … WHERE id=:id AND reviewed=false), or call db.refresh(image, ['reviewed']) just before writing.

### F-20 — The stag/hind prompt treats 'no antlers' as hind, which is wrong while stags have cast (roughly Feb–Apr), and its seasonal hint is fixed to June

*low · plausible · data-correctness · effort S* — `backend/app/ai/vision_sex.py`

- **What the hunter sees:** Stags photographed in spring, and labels from a backfill of those months, are stored as 'Hind'. That skews the stag/hind split the hunter reads on Tonight and in the galleries.
- **Evidence:** vision_sex.py:36-44 (_DEER_PROMPT) says 'hinds never have antlers' and 'in June they are growing and velvet-covered'. Red stags in Spain cast their antlers in late winter and spring. For those weeks a stag with no antlers and a clear head matches the prompt's hind rule. The capture date is never passed to the model. Behaviour of the model was not measured.
- **Verifier:** _DEER_PROMPT (vision_sex.py:34-44) states 'hinds never have antlers', gives 'no antlers, slender head' as an example cue, and passes no capture date. Antler-cast stags (roughly Feb-Apr) with a clearly visible head therefore lean toward 'hind'. Model behaviour was not measured. It is not urgent in September, but spring frames from the 13-month backfill were already sent once and MAX_SEX_ATTEMPTS=1 prevents a re-check.
- **Fix:** Add the capture month to the prompt, as proposed. Because MAX_SEX_ATTEMPTS=1, also reset sex_attempts for Feb-Apr red deer detections labelled female, so they are re-judged under the new prompt.

### F-23 — Every kept frame goes through MegaDetector twice

*low · confirmed · perf · effort S* — `backend/app/ai/species.py`, `backend/app/ai/empty_filter.py`

- **What the hunter sees:** New animal photos take noticeably longer to get a species label after each sync.
- **Evidence:** empty_filter.py:35 runs detect_animals, keeps only the maximum confidence and throws the boxes away. classify_image (species.py:25) then runs detect_animals again on the same file to get boxes. On CPU that is an extra ~0.5–1.5 s per animal frame in the dusk sync path.
- **Verifier:** scan_image calls detect_animals and keeps only the maximum confidence (empty_filter.py:35-42). classify_image runs detect_animals again on the same file (species.py:25), in the same pipeline run.
- **Fix:** The proposed fix is sound. Persisting the boxes also lets type_groups (grouping.py) skip its own re-detection.


## 18. NEW: Tonight names a stand, with one-tap Reserve / Start sit

### J-17 — FEATURE: Tonight should name a stand and offer one-tap Reserve / Start sit, and show who is already out

*medium · confirmed · feature · effort M* — `frontend/src/pages/Tonight.tsx`, `backend/app/forecasting/model.py`, `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** The decision and the action sit on different screens, and the forecast cannot warn that a hunter's pick is already taken.
- **Evidence:** Why it fits: the redesign defines the product as the estate's sit register (docs/redesign/00, 03 §1), and HuntStand's most-used club feature is shared stand reservations where members see who is where (huntstand.zendesk.com stand-reservation article). Today: Tonight's hero is a camera name (Tonight.tsx:219, model.py:387-392). Claims live only on Stands, so the 18:00 flow is Tonight → Stands → find the stand → Reserve → Start sit. Tonight never says 'Solana is taken by Pedro'.
- **Verifier:** This is not built. Tonight's hero is a camera name (Tonight.tsx:219) with no Reserve or Start sit and no taken-by information, and claiming exists only on Stands. It matches the redesign's 18:00 flow ('Tap CLAIM' from the plan, docs/redesign/03 §11). /stands returns claimed_by as a user UUID (routes_stands.py:69), so a name like 'Pedro' needs a backend change.
- **Fix:** Map the top camera to the nearest stand by position, since Map stands have no camera_id. Return the claimer's display name from /stands or /sits. Put Reserve / Start sit under the verdict, and add the resume banner (shared with J-03).

### J-25 — FEATURE: Show how long each stand has rested, and allow reserving a future night

*low · confirmed · feature · effort S* — `backend/app/api/routes_stands.py`, `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** Hunters overuse the best stand without noticing, and cannot book the weekend in advance.
- **Evidence:** Why it fits: the roadmap's example of what makes the app indispensable is 'Puente has been rested nine nights' (docs/redesign/05, end), and HuntStand reservations work by date, not only tonight. Today, claim_stand and list_stands are fixed to tonight() (routes_stands.py:77-84, 238), and nothing computes days since a stand was last sat, although the Sit table has every claim.
- **Verifier:** This is not present: nothing computes days since a stand was last sat, and claim_stand and list_stands are fixed to tonight() (routes_stands.py:77-84,238). 'Rested N nights' is cheap from the Sit table and is the roadmap's own example. Booking a future night is useful for weekends but changes the claim semantics.
- **Fix:** Ship 'Rested N nights' first: the latest non-cancelled Sit.night per stand, included in /stands. Add an optional `night` (today to +7 days) on POST /sits only after the J-11 unique index is in place, and have list_stands take a night parameter.


## 19. NEW: One plan push per day, before sunset

### J-20 — FEATURE: One plan push per day, before sunset

*medium · confirmed · feature · effort S* — `backend/pipeline.py`, `backend/app/notifications/push.py`, `backend/app/notifications/dispatch.py`

- **What the hunter sees:** On most nights a hunter could decide from the lock screen without opening the app.
- **Evidence:** Why it fits: the redesign specifies one fixed-schedule, sunset-anchored notification carrying the whole plan, sent even on quiet nights (docs/redesign/03 §11). HuntWise Hunt Alerts notify when conditions are right. Today the only pushes are per-species sighting pushes (dispatch.py:140-228). The `plan` job already computes tonight's forecast at 17:00 (pipeline.py:73-80), and push.send_to_user exists.
- **Verifier:** This is not present: dispatch.py:140-228 sends only per-species sighting pushes, and NotificationPref has no daily-plan flag (models.py:482-499). It is exactly the redesign's single sunset-anchored notification (docs/redesign/03 §11). Task Scheduler cannot anchor to sunset, and the fixed 17:00 run is only ~50 min before sunset after the clock change.
- **Fix:** Send the push from a job that runs hourly (or from sync) when now >= sunset − 2 h and no plan push has gone out for today. It should read the persisted Forecast, so it depends on J-01 making `plan` reliable. Add an opt-in flag to NotificationPref.


## 20. NEW: Fix a wrong species or false alarm from the photo viewer

### C-06 — There's no way to fix a wrong species or hide a false positive where hunters actually look at photos

*medium · confirmed · ux · effort M* — `frontend/src/pages/Cameras.tsx`, `frontend/src/components/PhotoLightbox.tsx`, `frontend/src/pages/Photos.tsx`, `backend/app/api/routes_images.py`

- **What the hunter sees:** Wrong labels (fox called boar, a branch called a deer) stay in the feed and counts, and feed the forecast. A hunter who spots the mistake in the viewer has nothing to tap.
- **Evidence:** The only review control is the 26px ×/+ button on Cameras (Cameras.tsx:448-462). It shows only after 'Show N empty photos' is on, and that toggle is only rendered when c.empty_count > 0 (line 475). A camera with zero empty frames has no way to hide a misdetection. The Photos feed and the shared lightbox have no actions at all (PhotoLightbox.tsx:301-316 offers only zoom and download). No endpoint changes a detection's species: routes_images has only /flag, and routes_species PATCH toggles the species itself.
- **Verifier:** Verified in code. The flag button renders only when hidden is true (Cameras.tsx:448), and the toggle that sets it renders only when c.empty_count > 0 (line 475). The lightbox tools are only zoom and download (PhotoLightbox.tsx:301-316). No route updates Detection.species_id: routes_images has only /flag, and routes_species PATCH toggles species flags. It is a missing feature rather than a crash, but the facts hold.
- **Fix:** Add a 'Wrong?' action to the lightbox toolbar with two choices, 'Nothing in it' (reuse /images/{id}/flag) and 'It's a …' (a species picker). Back the second with a new POST /images/{id}/label {species_id} that updates or replaces the Detection, sets reviewed=True, and marks the change so the classifier never overwrites it. Pass an onChanged callback so Photos and Cameras drop or relabel the tile optimistically.

### F-24 — Species names are DeepFaune taxonomy ('Micromammal', 'Mustelid', 'Equid'), hares show as 'Rabbit', and the names cannot be edited

*low · confirmed · ux · effort S* — `backend/app/ai/classifier.py`, `backend/app/ai/species.py`

- **What the hunter sees:** Filter chips, alerts ('Mustelid at PL19') and galleries use lab words instead of hunter words. Hares, a key small-game species in La Mancha, are called rabbits and disappear when rabbits are hidden.
- **Evidence:** classifier.py:46-50: common_name = name.title() with a single override, lagomorph → 'Rabbit'. The Species rows are created from this text (species.py:18-20), and routes_species offers only huntable and hidden toggles, no rename. Hiding 'Rabbit' also hides every hare.
- **Verifier:** common_name title-cases the DeepFaune labels ('Micromammal', 'Mustelid', 'Equid', 'Wild Boar'), with only lagomorph overridden to 'Rabbit' (classifier.py:46-50). routes_species.py offers only huntable and hidden toggles, with no rename.
- **Fix:** The proposed fix is sound. Existing Species rows also need a one-off UPDATE of common_name, because _ensure_species never touches rows that already exist.


## 21. NEW: Finish stand setup (shooting arcs, a stand per camera, dark exit)

### J-16 — Dark exit, arc suggestions, stand bootstrap and the temperature diagnostic are built but unreachable

*low · confirmed · feature · effort M* — `backend/app/api/routes_stands.py`, `backend/app/forecasting/inference.py`, `backend/app/forecasting/diagnostics.py`, `frontend/src/pages/SitMode.tsx`, `frontend/src/pages/Map.tsx`

- **What the hunter sees:** Hunters never see when and which way to walk out, and wind advice stays 'not set up' even though the app can already propose arcs.
- **Evidence:** The frontend never calls GET /stands/{id}/dark-exit (routes_stands.py:346-354), GET /stands/{id}/suggested-arcs (routes_stands.py:331-343) or POST /stands/bootstrap (routes_stands.py:87-128); a grep of frontend/src finds none. The bootstrap button mentioned in commit 5dbfd6f was lost in the c901c85 redesign. diagnostics.py, the bbox-versus-temperature test, is imported by nothing. Dark exit is the redesign's standout differentiator (docs/redesign/03 §9.4).
- **Verifier:** A grep of frontend/src finds no calls to /stands/bootstrap, /suggested-arcs or /dark-exit; the only stand API call is Map.tsx:158, and diagnostics.py is imported by nothing. The proposed value is overstated, though. dark_exit (inference.py:127-176) returns only an hour after a fixed 23:00, with no walk-out direction, from the same drifting clock-hour histogram as J-08. Both endpoints return 'not linked to a camera' for every Map-placed stand. And if J-04 makes stand_wind_report the single verdict, approach arcs feed nothing.
- **Fix:** Put the bootstrap button on the admin empty-state, or add a camera picker to the Map stand editor, so stands get camera_id. Surface dark exit only after it is anchored to sunset (J-08), and show the hour without promising a direction. Prioritise shooting-arc entry (for the safety check) over approach-arc confirmation. Leave diagnostics behind the Insights fold, or drop it.


## 22. NEW: Hour-by-hour wind for the sit, plus best nights this week

### J-19 — FEATURE: Hour-by-hour wind across the sit, plus 'best nights this week' for each stand

*medium · plausible · feature · effort M* — `backend/app/forecasting/model.py`, `backend/app/forecasting/bedding.py`, `backend/app/enrichment/weather.py`, `frontend/src/pages/Stands.tsx`

- **What the hunter sees:** Hunters cannot see the wind turning at 21:00, or that Thursday is the right wind for Puente, without opening another app.
- **Evidence:** Why it fits: wind is the first thing every guide checks. HuntStand HuntZone gives hourly scent cones 72 h ahead, and HuntWise WindCast forecasts 15 days (huntstand.com HuntZone guide; huntwise.com/features/huntcast). Today: one wind value sampled at 22:00 covers the whole night (model.py:235-238), although Open-Meteo already returns 24 hourly values per call (weather.py:40-59), and bedding.stand_wind_report can already judge any hour for any stand (bedding.py:130-256). Calm-evening drainage reverses around dusk, which the code itself notes (bedding.py:205-209), so one sample misses the shift.
- **Verifier:** This is not present: one wind sample at 22:00 (model.py:235-238), although the cached day already holds 24 hourly values (weather.py:40-59). stand_wind_report accepts `when` (bedding.py:130-160), so hourly verdicts are cheap. The value is credible, but it depends on J-04 (one wind engine) and J-07 (fresh forecasts) landing first. A per-stand strip on Tonight and Stands also cuts against 'lead with the decision, numbers behind a fold'.
- **Fix:** After J-04 and J-07: compute 17:00-24:00 hourly verdicts per stand for tonight, plus the next 6 evenings, and cache them hourly. Show one line up front ('Right wind for Puente: tonight 19–21 h, Thu, Sat') and put the hourly strip behind the fold.


## 23. NEW: Harvest log and season export

### J-23 — FEATURE: Harvest log with seal number, plus a season export

*low · plausible · feature · effort M* — `backend/app/models.py`, `frontend/src/pages/SitMode.tsx`, `backend/app/api/routes_stands.py`

- **What the hunter sees:** The owner still keeps a paper book, and the app cannot relate kills to stands or pressure.
- **Evidence:** Why it fits: harvest entry is paperwork the owner already has to keep for the annual return, so it gets done (docs/redesign/05 Phase 6). BaseMap has a harvest log, and Castilla y León now runs a digital precinto (seal) app (capturascotos.app). In CLM the big-game season opens 8 Oct. Today there is no harvest table, and Sit Mode's SHOT records only outcome='shot' (SitMode.tsx:274-279).
- **Verifier:** This is not present: no harvest model, route or export exists anywhere in the backend or frontend, and SHOT records only outcome='shot' (SitMode.tsx:275). It is in the redesign as Phase 6. The claim that CLM requires precintos is not verified here (the cited app is for Castilla y León), and the feature matters less than the reliability fixes.
- **Fix:** Keep it small: a harvest row linked to the sit (species, sex, age class, optional seal number, notes), prompted the morning after a SHOT, plus a season CSV export for the owner. Do not add counters or leaderboards (redesign 03 §11).


## 24. NEW: Map works offline

### B-06 — The map has no offline fallback: no cached stands, cameras, wind or imagery in a dead valley

*medium · confirmed · reliability · effort M* — `frontend/src/pages/Map.tsx`, `frontend/public/sw.js`, `frontend/src/api.ts`

- **What the hunter sees:** In the field, where the map matters most (which seat, which way the scent goes), the hunter gets an empty list, no pins, a black map and a raw 'Failed to fetch'. The Tonight page does keep a cached plan.
- **Evidence:** Map.tsx:61 uses api() (not apiCached) and Promise.all over /map/tonight and /cameras, so one failure hides both. sw.js:23 CACHEABLE_API does not include /api/map/tonight or /api/cameras. MapLibre fetches raster tiles as resourceType 'fetch' (verified in Playwright, s_tiletype.cjs), so the SW's `wanted` list (sw.js:93) never caches them. On a network failure, sw.js:101 answers the tile request with index.html. PROVEN (s_loadfail.cjs): /map/tonight aborted → banner 'Couldn’t load the map. Failed to fetch', list 'Stands and cameras 0', although /cameras had succeeded.
- **Verifier:** Confirmed: Map.tsx:61 fetches with Promise.all over plain api(), so a /map/tonight failure also wipes the /cameras list (s_loadfail: list count 0). CACHEABLE_API (sw.js:23) lacks both endpoints. Tile requests have resourceType 'fetch' (s_tiletype), so they are never cached, and offline they get index.html. Downgraded to medium: this is mostly a missing offline feature, and the Tonight and Stands pages do have offline fallbacks.
- **Fix:** Use Promise.allSettled with apiCached for both calls and show the data's age. Add both endpoints to CACHEABLE_API. Fall back to index.html only for navigations (shared with B-02). Before caching Esri World Imagery tiles, check Esri's terms of use, which restrict offline caching of basemap tiles. If caching is not allowed, keep only the data offline.


## 25. NEW: People and vehicles on camera (admin only)

### F-25 — Frames with a person or vehicle are silently filed as empty

*low · confirmed · feature · effort S* — `backend/app/ai/detector.py`, `backend/app/ai/empty_filter.py`

- **What the hunter sees:** A walker, poacher, another hunter or a vehicle at a stand leaves no trace in the app, although it is exactly what explains a quiet stand, and it matters for estate security.
- **Evidence:** detector.py:19-20,65 keeps only category 0 (animal), so MegaDetector's person (1) and vehicle (2) detections are dropped, and those frames get is_empty_frame=True. Image has no field to record them.
- **Verifier:** detect_animals keeps only category 0 (detector.py:154-155,200). Frames with only a person or vehicle therefore get max_conf 0 and is_empty_frame=True, and Image has no field for them. This is a feature request: hiding people also has a privacy upside, so any 'People & vehicles' view should be admin-only.
- **Fix:** The proposed fix is sound. Keep person frames admin-only, and out of the shared feed and push alerts by default.
