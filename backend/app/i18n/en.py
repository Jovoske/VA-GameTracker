"""English: what the server says, as it always said it. The reference catalog: every
other language has exactly these keys, with the same placeholders (tests/test_i18n.py).

A value is a str.format template, or {"one", "other"} chosen by the parameter `n`.
"""

MESSAGES: dict[str, str | dict[str, str]] = {
    # ---- lists and the calendar ------------------------------------------------------
    "list.two": "{a} and {b}",
    "list.three": "{a}, {b} and {c}",
    "list.more": "{a}, {b} and {n} more",
    "cal.wd.0": "Mon", "cal.wd.1": "Tue", "cal.wd.2": "Wed", "cal.wd.3": "Thu",
    "cal.wd.4": "Fri", "cal.wd.5": "Sat", "cal.wd.6": "Sun",
    "cal.wdl.0": "Monday", "cal.wdl.1": "Tuesday", "cal.wdl.2": "Wednesday",
    "cal.wdl.3": "Thursday", "cal.wdl.4": "Friday", "cal.wdl.5": "Saturday",
    "cal.wdl.6": "Sunday",
    "cal.mon.1": "Jan", "cal.mon.2": "Feb", "cal.mon.3": "Mar", "cal.mon.4": "Apr",
    "cal.mon.5": "May", "cal.mon.6": "Jun", "cal.mon.7": "Jul", "cal.mon.8": "Aug",
    "cal.mon.9": "Sep", "cal.mon.10": "Oct", "cal.mon.11": "Nov", "cal.mon.12": "Dec",
    "cal.monl.1": "January", "cal.monl.2": "February", "cal.monl.3": "March",
    "cal.monl.4": "April", "cal.monl.5": "May", "cal.monl.6": "June", "cal.monl.7": "July",
    "cal.monl.8": "August", "cal.monl.9": "September", "cal.monl.10": "October",
    "cal.monl.11": "November", "cal.monl.12": "December",
    "cal.day_month": "{day} {month}",
    "cal.wd_day_month": "{wd} {day} {month}",

    # ---- species and what an animal is -----------------------------------------------
    "species.bison": "Bison",
    "species.badger": "Badger",
    "species.ibex": "Ibex",
    "species.beaver": "Beaver",
    "species.red_deer": "Red deer",
    "species.chamois": "Chamois",
    "species.cat": "Cat",
    "species.goat": "Goat",
    "species.roe_deer": "Roe deer",
    "species.dog": "Dog",
    "species.fallow_deer": "Fallow deer",
    "species.squirrel": "Squirrel",
    "species.moose": "Moose",
    "species.equid": "Horse or donkey",
    "species.genet": "Genet",
    "species.wolverine": "Wolverine",
    "species.hedgehog": "Hedgehog",
    "species.lagomorph": "Hare or rabbit",
    "species.wolf": "Wolf",
    "species.otter": "Otter",
    "species.lynx": "Lynx",
    "species.marmot": "Marmot",
    "species.micromammal": "Mouse or rat",
    "species.mouflon": "Mouflon",
    "species.sheep": "Sheep",
    "species.mustelid": "Marten or weasel",
    "species.bird": "Bird",
    "species.bear": "Bear",
    "species.nutria": "Nutria",
    "species.raccoon": "Raccoon",
    "species.fox": "Fox",
    "species.reindeer": "Reindeer",
    "species.wild_boar": "Wild boar",
    "species.cow": "Cow",
    "class.stag": "Stag",
    "class.hind": "Hind",
    "class.hind_calf": "Hind + calf",
    "class.boar": "Boar",
    "class.sow": "Sow",
    "class.sow_piglets": "Sow + piglets",
    "class.sounder": "Sounder",
    "class.herd": "{name} (herd)",
    "class.animal": "Animal",
    "class.animals": "Animals",

    # ---- signing in --------------------------------------------------------------------
    "auth.not_authenticated": "Not authenticated",
    "auth.bad_credentials": "Invalid authentication credentials",
    "auth.token_invalid": "Invalid or expired token",
    "auth.token_subject": "Invalid token subject",
    "auth.user_not_found": "User not found",
    "auth.signed_out": "You were signed out. Sign in again.",
    "auth.admin_only": "Only the estate admin can do that.",
    "auth.busy": "The server is busy. Try again in a minute.",
    "auth.wrong_password": "Wrong email or password",
    "auth.published": (
        "That is the password published with GameSense, so it can't sign in from the "
        "internet. Sign in on the server's own network and change it in Settings, or on "
        "the server run: python -m app.manage set-password {email}"
    ),
    "auth.language_unknown": "Pick English, Suomi, Svenska, Norsk or Español.",
    "auth.not_current_password": "That is not your current password",
    "auth.new_password_short": "New password must be at least 8 characters",
    "auth.password_changed": (
        "Password changed. Every other phone signed in as you has to sign in again."
    ),

    # ---- people on the app ---------------------------------------------------
    "users.email_invalid": "Enter a valid email address",
    "users.password_short": "Password must be at least 8 characters",
    "users.pick_role": "Pick Member or Admin",
    "users.email_taken": "Someone with that email already has a login",
    "users.gone": "That person isn't on the app any more.",
    "users.not_yourself": "You can't remove yourself",
    "users.keep_admin": "Keep at least one admin",
    "users.remove_failed": (
        "Couldn't remove {email}: something on the app still points at them. "
        "Nothing was changed. Try again, or ask whoever runs the server."
    ),
    "users.removed": "{email} can't sign in any more. What they recorded stays.",
    "users.logins_moved": {
        "one": "{n} camera login they added keeps fetching photos, now under your name.",
        "other": "{n} camera logins they added keep fetching photos, now under your name.",
    },

    # ---- Tonight -------------------------------------------------------------
    "time.hours": "{h} h",
    # An hour on the clock, or a run of them ("19–21 h"), not a length of time.
    "time.clock": "{h} h",
    "time.minutes": "{m} min",
    "sun.at_sunset": "sunset",
    "sun.after": "{span} after sunset",
    "sun.before": "{span} before sunset",
    "tonight.factor.not_sending": {
        "one": "Camera is not sending photos right now. Going on {n} nights of history.",
        "other": "Camera is not sending photos right now. Going on {n} nights of history.",
    },
    "tonight.factor.unchecked": (
        "Photos from {n} of the last 7 nights are still being checked. Going on its history."
    ),
    "tonight.factor.few_watched": (
        "Only {n} of the last 7 nights watched here. Going on its history."
    ),
    "tonight.factor.not_watched": " ({n} not watched)",
    "tonight.factor.seen_week": "{species} seen {n} of the last 7 nights here{gap}",
    "tonight.factor.none_week": "No {species} here in the last 7 nights{gap}",
    "tonight.factor.outside_hours": (
        "{species} only seen here outside the hours you can sit, so there are no best hours to give"
    ),
    "tonight.best_hours": "Best hours {start} to {end}",
    "tonight.best_hours_from": "Best hours {start} to {end}, from {relative}",
    "tonight.left_out.unchecked_n": "{n} with photos not checked yet",
    "tonight.left_out.unchecked": "photos not checked yet",
    "tonight.left_out.blind_n": "{n} the camera may not have been watching",
    "tonight.left_out.blind": "the camera may not have been watching",
    "tonight.left_out": {
        "one": "{n} night at {camera} left out: {why}.",
        "other": "{n} nights at {camera} left out: {why}.",
    },
    "tonight.alert.silent": "No photos for {n} days, so it is left out of tonight's ranking",
    "tonight.none.picked": "No camera has seen the animals you picked yet.",
    "tonight.none.sending": "The cameras that are sending have not seen any animals yet.",
    "tonight.none.yet": "No sightings yet.",
    "tonight.reason": "{species} seen {n} of {total} nights at this camera.",
    "tonight.caveat": (
        "The camera watches all night. You will be there a few hours, so pick the best hours "
        "and mind the wind."
    ),

    # ---- wind ----------------------------------------------------------------
    "compass.N": "N", "compass.NE": "NE", "compass.E": "E", "compass.SE": "SE",
    "compass.S": "S", "compass.SW": "SW", "compass.W": "W", "compass.NW": "NW",
    "wind.reading": "Wind {dir} {speed} km/h",
    "wind.no_forecast": "No wind forecast tonight. Check it yourself.",
    "wind.no_forecast_stand": "No wind forecast tonight. Check it yourself before you sit {stand}.",
    "wind.no_position": (
        "{reading}. {stand} isn't on the map yet, so where your scent goes can't be worked out."
    ),
    "wind.no_bedding": (
        "{reading}. No bedding drawn yet, so where your scent lands can't be worked out. "
        "Draw where they lie up on the map."
    ),
    "wind.no_stand": (
        "{reading}. No stand near {camera} yet, so it can't be judged for a seat. Judge it "
        "yourself."
    ),
    "wind.arcs.too_light": (
        "Wind {dir} {speed} km/h, too light to call. Thermals will decide it. Check at the truck."
    ),
    "wind.arcs.no_geometry": (
        "Wind {dir} {speed} km/h. {stand} has no approach directions set, so judge the wind "
        "yourself."
    ),
    "wind.arcs.divert": " Take {stand} instead.",
    "wind.arcs.wrong": (
        "Wind {dir} {speed} km/h, wrong for {stand}. Your scent blows straight into the "
        "{approach} approach.{divert}"
    ),
    "wind.arcs.clean": (
        "Wind {dir} {speed} km/h, clean for {stand}. Your scent goes {scent}, away from where "
        "they come in."
    ),

    # ---- slope wind and bedding ----------------------------------------------
    "thermal.no_terrain": "No terrain map loaded, so the slope wind cannot be worked out.",
    "thermal.off_terrain": (
        "This spot is outside the hill shape that was loaded, so the slope wind can’t be worked "
        "out. An admin can load the hill shape again to cover it."
    ),
    "thermal.flat": "Ground is near flat here. No slope for cold air to run down.",
    "thermal.overcast": (
        "Overcast ({pct}%), so the slope wind will be weak tonight. Check it yourself."
    ),
    "thermal.katabatic": (
        "Forecast is calm, so the slope decides. Cold air runs downhill to the {dir} at about "
        "{speed} km/h. Your scent goes with it."
    ),
    "thermal.katabatic_settling": (
        "Forecast is calm, so the slope decides. Cold air runs downhill to the {dir} at about "
        "{speed} km/h. It is still settling around dusk and may swing. Your scent goes with it."
    ),
    "thermal.anabatic": (
        "Calm and sunny, so air is moving up the slope toward the {dir}. It will turn and run "
        "back downhill around sunset."
    ),
    "bedding.no_position": "{stand} has no position on the map yet.",
    "bedding.none": "No bedding drawn yet — draw where they lie up and this turns into advice.",
    "bedding.too_light": "Wind {dir} {speed} km/h — too light to call. {why}",
    "bedding.thermals_decide": "Thermals will decide this one; read them at the truck.",
    "bedding.lead.katabatic": (
        "Forecast calm, so the slope decides — cold air drains {dir} at ~{speed} km/h{fall}"
    ),
    "bedding.fall": " ({pct}% fall)",
    "bedding.lead.anabatic": "Calm and sunny — air is drawn upslope {dir} at ~{speed} km/h",
    "bedding.caveat.dusk": " It reverses around dusk, so check it on the ground.",
    "bedding.caveat.dem": " A ~90 m terrain model sees the hillside, not your gully.",
    "bedding.into_own": "into {zone}, the bedding your seat is in",
    "bedding.into_near": "into {zone} {m} m away",
    "bedding.into_far": "into {zone}, {m} m away",
    "bedding.carries.thermal": "{lead}, carrying your scent {where}.{caveat}",
    "bedding.carries.wind": "{lead} — your scent runs {dir} {where}.",
    "bedding.clean.thermal": "{lead}, away from bedding ({m} m to the nearest).{caveat}",
    "bedding.clean.wind": (
        "{lead} — clean. Scent goes {dir}, away from bedding ({m} m to the nearest)."
    ),
    "bedding.draw": "Draw bedding to see this.",
    "bedding.no_forecast": "No wind forecast tonight.",
    "bedding.too_light_map": "Wind too light to map — thermals decide on an evening like this.",
    "bedding.safe.note": (
        "Geometry only — this knows nothing about cover, access or a safe backstop. It narrows "
        "where to look; it does not pick the seat."
    ),
    "bedding.safe.note_calm": (
        "Forecast is calm, so this follows the ground: each square uses its own fall line, "
        "because cold air drains downhill after dark. A ~90 m terrain model sees the hillside, "
        "not the gully you are sitting in."
    ),

    # ---- what changed --------------------------------------------------------
    "num.decimal_mark": ".",
    "count.visits": {"one": "{n} visit", "other": "{n} visits"},
    "changed.about": "about {x}",
    "changed.no_cameras": "No cameras set up yet.",
    "changed.camera_down": (
        "{camera} sent nothing last night. Unknown whether anything came through."
    ),
    "changed.return": {
        "one": "Animals back at {camera} after {n} quiet nights.",
        "other": "Animals back at {camera} after {n} quiet nights.",
    },
    "changed.gone_quiet": {
        "one": "{camera} has been quiet for {n} nights. It usually sees {usual} a night.",
        "other": "{camera} has been quiet for {n} nights. It usually sees {usual} a night.",
    },
    "changed.busier": (
        "{camera} was busier than usual last night: {visits} against a usual {usual}."
    ),
    "changed.quieter": (
        "{camera} was quieter than usual last night: {visits} against a usual {usual}."
    ),
    "changed.some_cameras": "some cameras",
    "changed.checking": "Last night's photos from {cameras} are still being checked.",
    "changed.none": "Nothing changed. Much the same as the last few nights.",

    # ---- camera health -------------------------------------------------------
    "health.retired": "Retired {day}. Left out of tonight's plan and the numbers",
    "health.disconnected": "Not connected: no camera login here fetches it now",
    "health.not_syncing": "Photos not coming in. The camera login needs attention.",
    "health.not_fetched": "Photos not coming in. No photo fetch has worked for over 2 hours.",
    "health.fetch_error": "Photos not coming in. {error}",
    "health.no_photos_since": "No photos since {day}",
    "health.no_photos": "No photos yet",
    "health.photos_only": "Sends photos only, no check-ins",
    "health.clock_fast": (
        ". Its clock is {h} h fast (missed the clock change?): photo times are put right, but "
        "set the camera's clock"
    ),
    "health.no_checkin_for": "No check-in for {h}h",
    "health.no_checkin": "No check-in yet",
    "health.photo_limit": "Photo limit reached ({count}/{limit})",
    "health.battery_low": "Battery low ({pct}%)",
    "health.ok": "Reporting normally",

    # ---- camera logins (kept in English, said in the reader's language) ------
    "login.unreadable": "The saved password can't be read. Re-enter it.",
    "login.spypoint_refused": "SPYPOINT refused the password. Re-enter it.",
    "login.ubox_refused": "UBox refused the password. Re-enter it.",
    "login.ubox_signed_out": "UBox signed this login out. Re-enter the password.",
    "login.spypoint_throttled": (
        "SPYPOINT is turning requests away for now. It tries again on the next fetch."
    ),
    "login.spypoint_down": (
        "SPYPOINT isn't answering properly right now. It tries again on the next fetch."
    ),
    "login.spypoint_refused_request": (
        "SPYPOINT refused the request. It tries again on the next fetch."
    ),
    "login.spypoint_unreadable": (
        "SPYPOINT sent something the app can't read. It tries again on the next fetch."
    ),
    "login.ubox_unknown": "UBox doesn't know this login. Check the email used in the UBox Pro app.",
    "login.unreachable": "Couldn't reach {provider}. It tries again on the next fetch.",
    "login.ubox_down": "UBox isn't answering properly right now. It tries again on the next fetch.",
    "login.other": "{text}. It tries again on the next fetch.",
    "login.failed": "The fetch from {provider} failed ({error}). It tries again on the next fetch.",
    "login.primary_label": "Main SPYPOINT login",

    # ---- photo fetches (kept in English, said in the reader's language) ------
    "login.copy_of_primary": (
        "This is the estate's main SPYPOINT login, which is fetched already. Remove this copy."
    ),
    "sync.some_failed": "{n} of {total} cameras failed. {error}",
    "ubox.snap.retry": {
        "one": "{n} photo wouldn't download. It is tried again on the next fetch.",
        "other": "{n} photos wouldn't download. They are tried again on the next fetch.",
    },
    "ubox.snap.dropped": {
        "one": "{n} photo wouldn't download. It was tried {tries} times, so it is left out.",
        "other": (
            "{n} photos wouldn't download. They were tried {tries} times, so they are left out."
        ),
    },
    "ubox.snap.some": {
        "one": (
            "{failed} photos wouldn't download. {n} is tried again on the next fetch; the rest "
            "were tried {tries} times and are left out."
        ),
        "other": (
            "{failed} photos wouldn't download. {n} are tried again on the next fetch; the rest "
            "were tried {tries} times and are left out."
        ),
    },

    # ---- UBox errors (kept in English, said in the reader's language) --------
    "ubox.err.host_unresolved": "UBox image host could not be resolved",
    "ubox.err.host_public": "UBox image URL must use a public HTTPS host",
    "ubox.err.bad_json": "UBox returned an invalid JSON response",
    "ubox.err.unexpected": "UBox returned an unexpected response",
    "ubox.err.rejected_password": "UBox rejected the account or password",
    "ubox.err.rejected_request": "UBox rejected the request; check the account in UBox Pro",
    "ubox.err.no_data": "UBox response is missing its data object",
    "ubox.err.need_login": "UBox email and password are required",
    "ubox.err.unreachable_login": "Unable to reach UBox for login",
    "ubox.err.no_token": "UBox login response is missing the session token",
    "ubox.err.unreachable": "Unable to reach UBox",
    "ubox.err.auth_expired": "UBox authentication expired after retry; reconnect the account",
    "ubox.err.auth_failed": "UBox authentication failed",
    "ubox.err.no_devices": "UBox device response is missing items or infos",
    "ubox.err.device_no_id": "UBox returned a device without an identifier",
    "ubox.err.naive_dates": "UBox event query requires timezone-aware dates",
    "ubox.err.bad_range": "UBox event query has an invalid range or page size",
    "ubox.err.no_events": "UBox event response is missing its list",
    "ubox.err.incomplete_page": "UBox returned an incomplete event page; sync will retry later",
    "ubox.err.bad_event": "UBox returned an invalid event",
    "ubox.err.repeated_page": "UBox repeated an event page; sync will retry later",
    "ubox.err.bad_event_fields": "UBox event has an invalid timestamp or camera identifier",
    "ubox.err.fewer_events": "UBox returned fewer events than advertised; sync will retry",
    "ubox.err.page_limit": "UBox event page limit reached; use a shorter sync period",
    "ubox.err.https_only": "UBox image URL must use HTTPS",
    "ubox.err.too_big": "UBox image exceeds the 20 MB download limit",
    "ubox.err.empty_image": "UBox returned an empty image",
    "ubox.err.download_failed": "Unable to download the UBox image",
    "ubox.err.unknown_account": (
        "UBox did not recognize this account. Check the exact camera app and its signed-in email."
    ),
    "ubox.err.login_http": "UBox login failed (HTTP {status})",
    "ubox.err.request_http": "UBox request failed (HTTP {status})",
    "ubox.err.download_http": "UBox image download failed (HTTP {status})",
    "ubox.err.other_estate": "This UBox camera is already linked to another estate",
    "ubox.err.snapshot_size": "Snapshot is empty or exceeds the 20 MB limit",
    "ubox.err.snapshot_pixels": "Snapshot must be a JPEG of at most 40 megapixels",
    "ubox.err.snapshot_unreadable": "Snapshot is not a readable JPEG",
    "ubox.err.snapshot_failed": "Could not download a readable snapshot",
    "ubox.err.no_estate": "Account has no estate",
    "fetch.disk_label": "Server disk",
    "fetch.failed": "The fetch failed. It tries again on the next one.",
    "fetch.disk_full": (
        "Nearly full ({gb} GB free). The photos wait on the cameras and come in once there is room."
    ),
    "fetch.provider_failed": (
        "The {provider} fetch failed ({error}). It tries again on the next one."
    ),
    "fetch.ai_failed": "Looking for animals failed ({error})",

    # ---- the AI pass (kept in English, said in the reader's language) --------
    "ai.detector_failed": "The animal detector could not start ({error}).",
    "ai.classifier_failed": "The species model could not start ({error}).",
    "ai.models_broken": "The models stopped working ({error}).",
    "ai.stopped_streak": (
        "{why} Checking stopped after {n} photos in a row failed; they were not counted against "
        "the photos."
    ),

    # ---- photos --------------------------------------------------------------
    "photos.not_checked": "Not checked yet",
    "photos.could_not_check": "Couldn’t check",
    "photos.people_admin_only": "Only an admin sees the photos with people or vehicles in them.",
    "photos.gone": "That photo isn't available any more.",
    "people.person_vehicle": "Person and vehicle",
    "people.person": "Person",
    "people.vehicle": "Vehicle",
    "people.person_or_vehicle": "Person or vehicle",

    # ---- cameras and the Check button ----------------------------------------
    "busy.reid": "looking for repeat visitors",
    "busy.plan": "writing tonight’s plan",
    "busy.score": "checking last night’s plan against the cameras",
    "busy.scan": "checking photos for animals",
    "busy.deploy": "installing an update",
    "busy.other": "busy with another job",
    "busy.fetch": "fetching photos",
    "busy.try_later": "The server is {what}. Try again in a few minutes.",
    "cameras.start_failed": "Could not start it on the server. Try again in a minute.",
    "cameras.name_hidden_chars": "Camera name has hidden characters in it. Retype it.",
    "cameras.name_length": "Camera name must be 1 to 100 characters.",
    "cameras.rename_forbidden": "Only estate admins and members can rename cameras.",
    "cameras.not_found": "Camera not found.",
    "cameras.name_taken": "Another camera is already called {name}. Pick another name.",
    "cameras.name_taken_reset": (
        "Another camera is already called {name}, so this one keeps its own name."
    ),
    "cameras.check_viewer": "New photos come in by themselves every 15 minutes.",
    "cameras.check_running": "Already checking. New photos will show shortly.",
    "cameras.check_asked": "Already asked. New photos come in as soon as the server is free.",
    "cameras.check_queued": "The server is {what}. New photos come in when it finishes.",
    "cameras.off_map": "That spot is off the map. Move the map and try again.",
    "cameras.no_own_position": (
        "This camera hasn’t reported a position of its own. Place it by hand."
    ),

    # ---- camera logins in Settings -------------------------------------------
    "accounts.viewer": "Viewers can see the camera logins but can't add one.",
    "accounts.enter_login": "Enter your {provider} email and password",
    "accounts.no_estate": "Join an estate before adding a camera login",
    "accounts.is_primary": "This login is already connected as the estate's main account",
    "accounts.already_added": "That {provider} login is already added",
    "accounts.already_added_refresh": "That {provider} login is already added. Refresh to see it.",
    "accounts.connected_now": {
        "one": "Connected — {provider} reports {n} camera(s). Fetching photos now.",
        "other": "Connected — {provider} reports {n} camera(s). Fetching photos now.",
    },
    "accounts.connected_later": {
        "one": "Connected — {provider} reports {n} camera(s). Photos come in on the next fetch.",
        "other": "Connected — {provider} reports {n} camera(s). Photos come in on the next fetch.",
    },
    "accounts.unreachable": (
        "Couldn't reach {provider} to check the password. Try again in a few minutes."
    ),
    "accounts.ubox_failed": "Could not connect to UBox Pro: {error}",
    "accounts.spypoint_refused": (
        "SPYPOINT refused that email and password. Check them in the SPYPOINT app."
    ),
    "accounts.spypoint_failed": "SPYPOINT did not accept that login: {error}",
    "accounts.not_found": "Account not found",
    "accounts.password_forbidden": (
        "Only whoever added this login, or an admin, can change its password"
    ),
    "accounts.enter_password": "Enter the password",
    "accounts.password_saved": (
        "Password saved. Photos come in on the next fetch, within 15 minutes."
    ),
    "accounts.limits_forbidden": (
        "Only whoever added this login, or an admin, can change its limits"
    ),
    "accounts.limits_ubox_only": "Photo limits only apply to UBox Pro logins",
    "accounts.limits_saved": "Limits saved. They apply from the next fetch.",
    "accounts.remove_forbidden": "Only whoever added this login, or an admin, can remove it",

    # ---- alerts on the phone -------------------------------------------------
    "push.just_now": "just now",
    # A time of day in an alert: "22:14" ("klo 22:14", "a las 22:14").
    "push.time": "{time}",
    "push.last_night": "{time} last night",
    "push.yesterday": "{time} yesterday",
    "push.on_day": "{time} on {day}",
    "push.at_camera": "{name} at {camera}",
    "push.on_cameras": {"one": "{name} on {n} cameras", "other": "{name} on {n} cameras"},
    "push.one_visit": "1 visit at {when}.",
    "push.visits_last": "{visits}, last one {when}.",
    "push.visits_at_last": "{visits} at {cameras}, last one {when}.",
    "push.at_cameras": " at {cameras}",
    "push.update": "{visits}{where} since {since}, last one {last}.",
    "push.summary_title": "{n} new sightings, {animals} animals",
    "push.summary_body": "{names}, last one {when}.",
    "verdict.best_odds": "Best odds",
    "verdict.worth_a_look": "Worth a look",
    "verdict.quiet": "Quiet",
    "verdict.no_data": "Not enough to say",
    "plan.wind.clean": "wind right",
    "plan.wind.wrong": "wind wrong",
    "plan.wind.too_light": "wind too light to call",
    "plan.wind.no_forecast": "no wind forecast",
    "plan.tonight": "{verdict} tonight",
    "plan.sunset": "sunset {time}",
    "plan.no_camera": (
        "Not enough watched nights to judge tonight. Open the app for what the cameras saw."
    ),
    "plan.species_hours": "{species}, best {start} to {end}.",
    "held.one": "{name}: {visits} at {cameras}",
    "held.each": "{name} {visits}",
    "held.worth_a_look": {
        "one": "{n} photo marked Worth a look",
        "other": "{n} photos marked Worth a look",
    },
    "held.title.sit": "While you sat",
    "held.title.quiet": "During your quiet hours",
    "held.body": "{parts}, last one {when}.",

    # ---- alert settings ------------------------------------------------------
    "alerts.unknown_camera": "Unknown camera: {ids}",
    "alerts.unknown_species": "Unknown species: {ids}",
    "alerts.quiet_needs_both": "Quiet hours need a start and an end.",
    "alerts.quiet_same": "Quiet hours can't start and end at the same time.",
    "alerts.endpoint_https": "Push endpoint must be an https URL",
    "alerts.no_phone": "No phone is getting alerts yet. Turn alerts on from that phone first.",
    "alerts.test_title": "Test alert",
    "alerts.test_body": "Alerts are working on this phone.",

    # ---- team notes and people -----------------------------------------------
    "notes.bad_chars": "That note has characters it can’t save. Type it again.",
    "notes.too_long": "Keep the note to {n} characters.",
    "notes.push_title": "Worth a look: {label} at {camera}",
    "notes.push_body": "{name}: {text}",
    "notes.push_marked": "{name} marked a photo",
    "notes.empty_frame": "This photo is marked “nothing in it”. Keep it as an animal photo first.",
    "notes.hidden_only": (
        "Only animals hidden from the app are in this photo, so the team can’t see it."
    ),
    "notes.people_only": (
        "There’s a person or a vehicle in this photo, so it stays with the admins and the team "
        "can’t see it."
    ),
    "notes.not_looked": (
        "The app hasn’t checked this photo yet, so the team can’t see it. Try again in a few "
        "minutes."
    ),
    "notes.photo_not_found": "Photo not found.",
    "notes.viewer": "Viewers can see notes but not add them.",
    "notes.not_saved": "That note couldn’t be saved. Close it and try again.",
    "notes.gone": "That note is already gone.",
    "notes.remove_forbidden": "Only the person who wrote it or an admin can remove a note.",
    "people.hunter": "Hunter",
    "people.removed": "Removed person",
    "crash.too_large": "Report too large",
    "crash.not_a_report": "That isn't a crash report.",
    "crash.too_many": "Too many reports. Later ones are dropped.",
    "crash.unknown_device": "Unknown device",

    # ---- stands and sits -----------------------------------------------------
    "stands.no_estate": "Set up the estate first.",
    "stands.auto_name": "{camera} stand",
    "stands.auto_note": (
        "Each stand is placed at its camera. Move it to where you actually sit. Wind advice starts "
        "once you set the directions animals come in from."
    ),
    "stands.camera_gone": "That camera isn't on the app.",
    "stands.gone": "That stand isn't on the app.",
    "stands.has_sits": {
        "one": (
            "{n} sit recorded at this stand. Deleting it would wipe that history. Rename it "
            "instead."
        ),
        "other": (
            "{n} sits recorded at this stand. Deleting it would wipe that history. Rename it "
            "instead."
        ),
    },
    "stands.claimed": "{stand} is already claimed tonight by another hunter.",
    "stands.arc_conflict": (
        "{stand} and {other} share a shooting arc, and {other} is taken tonight. Pick another "
        "stand."
    ),
    "stands.viewer": "Viewers can look at the stands but can't reserve one.",
    "sits.gone": "That sit isn't on the app.",
    "sits.viewer": "Viewers can look at the sits but can't change them.",
    "sits.not_yours": "That sit is another hunter's.",
    "sits.bad_outcome": "outcome must be one of {outcomes}",
    "sits.cancelled": "That reservation was cancelled. Reserve the stand again.",
    "sits.already_reported": "You've already said what happened on this sit.",
    "sits.not_started": "That sit hasn't started.",

    # ---- approach lines and the dark exit ------------------------------------
    "arcs.no_camera": "This stand is not linked to a camera.",
    "arcs.camera_unplaced": "The linked camera has no position recorded.",
    "arcs.no_others": "No other positioned cameras to infer movement from.",
    "arcs.note": {
        "one": "{n} times, animals reached {camera} within {minutes} min of passing {other}.",
        "other": "{n} times, animals reached {camera} within {minutes} min of passing {other}.",
    },
    "arcs.none": (
        "No repeated movement between cameras yet — not enough to propose an approach line, so "
        "the app will keep saying this one is yours to solve."
    ),
    "exit.no_visits": "No visits at this stand's camera yet.",
    "exit.quiet": (
        "Dark exit {time} — only {pct}% of this camera's visits fall in the hour after, so walking "
        "out then disturbs least."
    ),
    "exit.busy_reason": "No genuinely quiet hour — this stand is busy all night.",
    "exit.busy": (
        "No quiet hour after {after} at this stand — it is busy all night. {time} is the least-bad "
        "exit."
    ),

    # ---- the harvest book ----------------------------------------------------
    "harvest.sex.male": "Male",
    "harvest.sex.female": "Female",
    "harvest.sex.unknown": "Not sure",
    "harvest.age.juvenile": "Young of the year",
    "harvest.age.young_adult": "Young adult",
    "harvest.age.mature_adult": "Adult",
    "harvest.age.old": "Old",
    "harvest.age.unknown": "Not sure",
    "harvest.viewer": "Viewers can’t log a harvest.",
    "harvest.not_yours": "That harvest is another hunter’s. An admin can change it.",
    "harvest.not_a_shot": "That sit isn’t reported as a shot. Say what happened first.",
    "harvest.field.seal": "seal number",
    "harvest.field.note": "note",
    "harvest.field.name": "name",
    "harvest.hidden_chars": "The {what} has hidden characters in it. Retype it.",
    "harvest.too_long": "The {what} is at most {n} characters.",
    "harvest.bad_species": "Pick one of the animals on the list.",
    "harvest.bad_sex": "Sex is male, female or not sure.",
    "harvest.bad_age": "Pick an age from the list.",
    "harvest.future": "That time is still to come. Check the date.",
    "harvest.too_old": "That date is too long ago. Check the year.",
    "harvest.bad_season": "Pick a season from the list.",
    "harvest.not_saved": "That harvest couldn’t be saved. Close it and try again.",
    "harvest.gone": "That harvest isn’t in the book any more.",
    "harvest.admin_names": "Only an admin changes the name on a harvest.",
    "harvest.col.date": "Date",
    "harvest.col.time": "Time",
    "harvest.col.species": "Species",
    "harvest.col.sex": "Sex",
    "harvest.col.age": "Age",
    "harvest.col.seal": "Seal number",
    "harvest.col.weight": "Weight (kg)",
    "harvest.col.hunter": "Hunter",
    "harvest.col.stand": "Stand",
    "harvest.col.notes": "Notes",

    # ---- the activity map ----------------------------------------------------
    "activity.part.dusk": "at dusk",
    "activity.part.night": "in the middle of the night",
    "activity.part.dawn": "at dawn",
    "activity.checking_last": "Still checking last night’s photos.",
    "activity.checking": "Still checking the photos.",
    "activity.unreadable_last": "Not counted: last night’s photos couldn’t all be checked.",
    "activity.unreadable": "Not counted: the photos couldn’t all be checked.",
    "activity.blind_last": "Not counted: the camera may not have been working last night.",
    "activity.blind": "Not counted: the camera wasn’t working on these nights.",
    "activity.tail.times": ", at {times}",
    "activity.tail.mostly": ", mostly {peak} h",
    "activity.tail.busiest": ", busiest {peak} h",
    "activity.tail.no_set_time": ", at no set time",
    "activity.last_night": "last night",
    "activity.last_night_so_far": "last night so far",
    "activity.one.nothing_all": "Nothing on camera{when} {night}.",
    "activity.one.nothing": "No {species}{when} {night}.",
    "activity.one.visits_all": {
        "one": "{n} animal visit{when} {night}{tail}",
        "other": "{n} animal visits{when} {night}{tail}",
    },
    "activity.one.visits": {
        "one": "{n} {species} visit{when} {night}{tail}",
        "other": "{n} {species} visits{when} {night}{tail}",
    },
    "activity.q.working": " it was working",
    "activity.q.checkable": " that could be checked",
    "activity.q.so_far": " checked so far",
    "activity.none_all": {
        "one": "No animals{when} on the {n} nights{qualifier}.",
        "other": "No animals{when} on the {n} nights{qualifier}.",
    },
    "activity.none": {
        "one": "No {species}{when} on the {n} nights{qualifier}.",
        "other": "No {species}{when} on the {n} nights{qualifier}.",
    },
    "activity.some": "{who} on {n} of {total} nights{qualifier}{tail}",

    # ---- the map -------------------------------------------------------------
    "map.bad_nights": "nights is 1, 7 or 30.",
    "map.no_species": "No such species.",
    "map.no_replay": "There is no replay for that night.",

    # ---- insights: what moves the animals ------------------------------------
    "class.animals_all": "All animals",
    "patterns.moon_illum.label": "Moonlight",
    "patterns.moon_illum.high": "a bright moon",
    "patterns.moon_illum.low": "a dark moon",
    "patterns.pressure.label": "Pressure",
    "patterns.pressure.high": "high pressure",
    "patterns.pressure.low": "low pressure",
    "patterns.pressure_trend.label": "Pressure trend",
    "patterns.pressure_trend.high": "rising pressure",
    "patterns.pressure_trend.low": "falling pressure",
    "patterns.temp.label": "Temperature",
    "patterns.temp.high": "warm weather",
    "patterns.temp.low": "cool weather",
    "patterns.wind.label": "Wind",
    "patterns.wind.high": "wind",
    "patterns.wind.low": "still air",
    "patterns.rain.label": "Rain",
    "patterns.rain.high": "rain",
    "patterns.rain.low": "dry weather",
    "patterns.cloud.label": "Cloud cover",
    "patterns.cloud.high": "cloud",
    "patterns.cloud.low": "clear skies",
    "patterns.darkness.label": "Dark hours",
    "patterns.darkness.high": "a long night",
    "patterns.darkness.low": "a short night",
    "patterns.statement": "About {hi} visits a night with {hi_desc}, about {lo} with {lo_desc}.",
    "insights.midnight": "midnight",
    "insights.busiest": "Your cameras are busiest between {start} and {end}.",
    "insights.species_mostly": "The cameras see {species} mostly between {start} and {end}.",
    "insights.concentrated": "Most of the action is at {cameras}. The other cameras see far less.",
    "insights.busiest_cameras": "{cameras} are your busiest cameras.",
    "insights.class_missing": "Pick which animals to show.",

    # ---- species in Settings -------------------------------------------------
    "species.name_hidden_chars": "That name has hidden characters in it. Retype it.",
    "species.name_length": "A name is 1 to 40 characters.",
    "species.not_found": "Species not found.",

    # ---- the alerts feed on Tonight ------------------------------------------
    "ago.unknown": "unknown",
    "ago.just_now": "just now",
    "ago.ago": "{span} ago",
    "ago.m": "{n}m",
    "ago.h": "{n}h",
    "ago.d": "{n}d",
    "feed.seen": {
        "one": "Seen {n} time in the last 2 days, last one {ago}.",
        "other": "Seen {n} times in the last 2 days, last one {ago}.",
    },
    "feed.battery_title": "{camera} battery low",
    "feed.battery": "{pct}% left. Bring batteries on your next visit.",
    "feed.since": ", since the night of {day}",
    "feed.quiet_title": "{camera} quiet",
    "feed.quiet": {
        "one": "Nothing on its last {n} watched nights{since}. It usually sees {usual} a night.",
        "other": "Nothing on its last {n} watched nights{since}. It usually sees {usual} a night.",
    },

    # ---- the week's wind -----------------------------------------------------
    "week.tonight": "Tonight",
    "week.tonight_hours": "tonight {hours}",
    "week.no_position": "{stand} isn’t on the map yet, so its wind can’t be judged.",
    "week.no_bedding": "No bedding drawn yet, so the wind can’t be judged for {stand}.",
    "week.no_geometry": "{stand} has no approach directions set, so judge its wind yourself.",
    "week.no_forecast": "No wind forecast for the week yet.",
    "week.right": "Right wind for {stand}: {when}",
    "week.none": "No right wind for {stand} this week.",

    # ---- the track record ----------------------------------------------------
    "record.too_few": {
        "one": "{n} night checked so far. How often it was right shows after {needed}.",
        "other": "{n} nights checked so far. How often it was right shows after {needed}.",
    },
    "record.verdict": {
        "one": "When it called a camera {verdict}, animals came there {came} of {n} times.",
        "other": "When it called a camera {verdict}, animals came there {came} of {n} times.",
    },
    "record.beats": "Its odds were closer to what happened than each camera's usual rate.",
    "record.no_better": "Its odds were no closer to what happened than each camera's usual rate.",
    "record.too_few_each": {
        "one": "{n} nights checked, too few of any one verdict to say yet.",
        "other": "{n} nights checked, too few of any one verdict to say yet.",
    },

    # ---- photos and animals --------------------------------------------------
    "images.viewer": "Viewers can look at the photos but can't change them.",
    "images.old_link": "This photo link has run out. Open the photo in the app again.",
    "images.sign_in": "Sign in to view photos.",
    "images.no_picture": "This photo has no picture yet, so there's nothing to fix.",
    "images.no_people": "The app doesn’t count anyone in this photo already.",
    "animals.not_found": "Animal not found.",
    "animals.gone": "That animal isn't on the app any more.",
    "animals.name_first": "Type a name first.",
    "animals.name_long": "A name is at most 60 characters.",
    "animals.bad_status": "status must be one of {statuses}",
    "animals.merge_target": "The animal to merge into was not found.",
    "animals.reid_running": "Already looking. This takes a few minutes.",
    "animals.reid_started": "Looking for repeats. This takes a few minutes.",

    # ---- areas on the map, and admin -----------------------------------------
    "zones.name_needed": "Give it a name the group will know.",
    "zones.name_not_empty": "The name can be changed, not left empty.",
    "zones.outline_not_empty": "The outline can be changed, not left empty.",
    "zones.bad_kind": "kind must be one of {kinds}",
    "zones.gone": "That area isn't on the map.",
    "admin.deploying": "The server is installing an update. Try again in a few minutes.",
    "admin.no_api_key": "Add ANTHROPIC_API_KEY to .env first",
    "admin.labelling": "Already labelling. Labels appear over a few minutes.",
    "admin.labels_coming": "Labels appear in Cameras over a few minutes.",
    "admin.retry": {
        "one": "{n} photo will be checked again on the next fetch.",
        "other": "{n} photos will be checked again on the next fetch.",
    },
    "admin.nothing_to_retry": "Nothing to try again.",
    "admin.reload": "Reload the app: updates now show under App version by themselves.",

    # ---- server upkeep (kept in English, said in the reader's language) ------
    "restore.no_table": "The restored copy has no {table} table.",
    "restore.no_rows": "The restored copy has no rows in {table}.",
    "restore.photos_missing": (
        "{n} of {total} photos looked for are not in the backup's photo folder."
    ),
    "restore.failed": "The check couldn't run ({error}).",
    "ops.unreadable": "Its status file can't be read.",

    # ---- drawing on the map --------------------------------------------------
    "shape.not_polygon": "The outline must be a GeoJSON Polygon.",
    "shape.no_corners": "The outline has no corners.",
    "shape.too_many": "That outline has {n} corners. Keep it under {limit}.",
    "shape.two_numbers": "Each corner must be two numbers: longitude, then latitude.",
    "shape.off_map": "A corner is off the map. Corners go longitude first, then latitude.",
    "shape.three": "Tap at least three corners around the area.",
    "shape.too_big": (
        "That outline is over 20 km across. Draw just the cover the animals lie up in."
    ),
    "shape.crosses": "The outline crosses itself. Put the corners in order around the edge.",
    "shape.no_area": "That outline has almost no area. Spread the corners around the cover.",
    "box.four_numbers": "The box needs four numbers: south, west, north and east.",
    "box.off_map": "That box is off the map.",
    "box.too_big": (
        "That is {km} km across, more than a phone should keep. Zoom in so the estate is under "
        "{limit} km across."
    ),
    "box.too_small": "That is too small to be the estate. Zoom out a little.",
    "terrain.busy": "The elevation service is busy. Try again in a few minutes.",
    "terrain.down": "The elevation service didn’t answer. Try again later.",

    # ---- signing in, too many tries ------------------------------------------
    "count.minutes": {"one": "{n} minute", "other": "{n} minutes"},
    "throttle.place": "Too many wrong passwords from here. Try again in {wait}.",
    "throttle.at_once": "Too many sign-ins from here at once. Try again in a few seconds.",
    "throttle.checking": "Still checking your last try. Try again in a few seconds.",
    "throttle.email": {
        "one": "Too many wrong passwords for this email. Try again in {n} second.",
        "other": "Too many wrong passwords for this email. Try again in {n} seconds.",
    },
    "throttle.email_lately": (
        "Too many wrong passwords for this email lately. Try again in {wait}, or on a phone that "
        "has signed in with it before."
    ),

    # ---- the stag/hind labelling pass (kept in English, said in the reader's language) ----
    "sexpass.key_refused": (
        "Anthropic refused the API key. Check ANTHROPIC_API_KEY in the server's .env."
    ),
    "sexpass.no_credit": (
        "The Anthropic account is out of credit. Top it up to label stags and hinds again."
    ),
    "sexpass.no_model": (
        "Anthropic does not know the model {model}. Ask whoever runs the server to update it."
    ),
    "sexpass.limited": "Anthropic is limiting requests just now. It tries again next hour.",
    "sexpass.unreachable": "Couldn't reach Anthropic. It tries again next hour.",
    "sexpass.http": "Anthropic had a problem (HTTP {status}). It tries again next hour.",
    "sexpass.bad_answer": "Anthropic did not answer properly. It tries again next hour.",

    # ---- Look for repeats (kept in English, said in the reader's language) ----
    "reid.failed": "Something went wrong ({error}).",
    "reid.stopped": "It stopped partway: the server was held up too long. Tap it again to finish.",

    # ---- the moon ------------------------------------------------------------
    "moon.new_moon": "New Moon",
    "moon.waxing_crescent": "Waxing Crescent",
    "moon.first_quarter": "First Quarter",
    "moon.waxing_gibbous": "Waxing Gibbous",
    "moon.full_moon": "Full Moon",
    "moon.waning_gibbous": "Waning Gibbous",
    "moon.last_quarter": "Last Quarter",
    "moon.waning_crescent": "Waning Crescent",
    # ---- end ----
}

# Messages the server keeps as text in the database, in English, and puts in the
# reader's language when read (app.i18n.localize): a camera's fetch error, a login's
# last error.
STORED: tuple[str, ...] = (
    "reid.failed",
    "reid.stopped",
    "sexpass.key_refused",
    "sexpass.no_credit",
    "sexpass.no_model",
    "sexpass.limited",
    "sexpass.unreachable",
    "sexpass.http",
    "sexpass.bad_answer",
    "terrain.busy",
    "terrain.down",
    "restore.no_table",
    "restore.no_rows",
    "restore.photos_missing",
    "restore.failed",
    "ai.detector_failed",
    "ai.classifier_failed",
    "ai.models_broken",
    "ai.stopped_streak",
    "fetch.disk_label",
    "fetch.failed",
    "fetch.disk_full",
    "fetch.provider_failed",
    "fetch.ai_failed",
    "login.primary_label",
    "ubox.err.other_estate",
    "ubox.err.snapshot_size",
    "ubox.err.snapshot_pixels",
    "ubox.err.snapshot_unreadable",
    "ubox.err.snapshot_failed",
    "ubox.err.no_estate",
    "ubox.err.host_unresolved",
    "ubox.err.host_public",
    "ubox.err.bad_json",
    "ubox.err.unexpected",
    "ubox.err.rejected_password",
    "ubox.err.rejected_request",
    "ubox.err.no_data",
    "ubox.err.need_login",
    "ubox.err.unreachable_login",
    "ubox.err.no_token",
    "ubox.err.unreachable",
    "ubox.err.auth_expired",
    "ubox.err.auth_failed",
    "ubox.err.no_devices",
    "ubox.err.device_no_id",
    "ubox.err.naive_dates",
    "ubox.err.bad_range",
    "ubox.err.no_events",
    "ubox.err.incomplete_page",
    "ubox.err.bad_event",
    "ubox.err.repeated_page",
    "ubox.err.bad_event_fields",
    "ubox.err.fewer_events",
    "ubox.err.page_limit",
    "ubox.err.https_only",
    "ubox.err.too_big",
    "ubox.err.empty_image",
    "ubox.err.download_failed",
    "ubox.err.unknown_account",
    "ubox.err.login_http",
    "ubox.err.request_http",
    "ubox.err.download_http",
    "login.copy_of_primary",
    "sync.some_failed",
    "ubox.snap.retry",
    "ubox.snap.dropped",
    "ubox.snap.some",
    "login.unreadable",
    "login.spypoint_refused",
    "login.ubox_refused",
    "login.ubox_signed_out",
    "login.spypoint_throttled",
    "login.spypoint_down",
    "login.spypoint_refused_request",
    "login.spypoint_unreadable",
    "login.ubox_unknown",
    "login.unreachable",
    "login.ubox_down",
    "login.other",
    "login.failed",
)
