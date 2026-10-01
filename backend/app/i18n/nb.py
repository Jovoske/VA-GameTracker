"""Norwegian bokmål (norsk): what the server says. The same keys and placeholders as en.py
(tests/test_i18n.py); a key missing here would be said in English.

Norwegian hunters' words: villsvin, hjort, rådyr, dåhjort, foringsplass,
post, tårn.
"""

MESSAGES: dict[str, str | dict[str, str]] = {
    # ---- lists and the calendar ----------------------------------------------
    "list.two": "{a} og {b}",
    "list.three": "{a}, {b} og {c}",
    "list.more": "{a}, {b} og {n} til",
    "cal.wd.0": "man.",
    "cal.wd.1": "tir.",
    "cal.wd.2": "ons.",
    "cal.wd.3": "tor.",
    "cal.wd.4": "fre.",
    "cal.wd.5": "lør.",
    "cal.wd.6": "søn.",
    "cal.wdl.0": "mandag",
    "cal.wdl.1": "tirsdag",
    "cal.wdl.2": "onsdag",
    "cal.wdl.3": "torsdag",
    "cal.wdl.4": "fredag",
    "cal.wdl.5": "lørdag",
    "cal.wdl.6": "søndag",
    "cal.mon.1": "jan.",
    "cal.mon.2": "feb.",
    "cal.mon.3": "mar.",
    "cal.mon.4": "apr.",
    "cal.mon.5": "mai",
    "cal.mon.6": "jun.",
    "cal.mon.7": "jul.",
    "cal.mon.8": "aug.",
    "cal.mon.9": "sep.",
    "cal.mon.10": "okt.",
    "cal.mon.11": "nov.",
    "cal.mon.12": "des.",
    "cal.monl.1": "januar",
    "cal.monl.2": "februar",
    "cal.monl.3": "mars",
    "cal.monl.4": "april",
    "cal.monl.5": "mai",
    "cal.monl.6": "juni",
    "cal.monl.7": "juli",
    "cal.monl.8": "august",
    "cal.monl.9": "september",
    "cal.monl.10": "oktober",
    "cal.monl.11": "november",
    "cal.monl.12": "desember",
    "cal.day_month": "{day}. {month}",
    "cal.wd_day_month": "{wd} {day}. {month}",

    # ---- species and what an animal is ---------------------------------------
    "species.bison": "Bison",
    "species.badger": "Grevling",
    "species.ibex": "Steinbukk",
    "species.beaver": "Bever",
    "species.red_deer": "Hjort",
    "species.chamois": "Gemse",
    "species.cat": "Katt",
    "species.goat": "Geit",
    "species.roe_deer": "Rådyr",
    "species.dog": "Hund",
    "species.fallow_deer": "Dåhjort",
    "species.squirrel": "Ekorn",
    "species.moose": "Elg",
    "species.equid": "Hest eller esel",
    "species.genet": "Genett",
    "species.wolverine": "Jerv",
    "species.hedgehog": "Pinnsvin",
    "species.lagomorph": "Hare eller kanin",
    "species.wolf": "Ulv",
    "species.otter": "Oter",
    "species.lynx": "Gaupe",
    "species.marmot": "Murmeldyr",
    "species.micromammal": "Mus eller rotte",
    "species.mouflon": "Mufflon",
    "species.sheep": "Sau",
    "species.mustelid": "Mår eller røyskatt",
    "species.bird": "Fugl",
    "species.bear": "Bjørn",
    "species.nutria": "Beverrotte",
    "species.raccoon": "Vaskebjørn",
    "species.fox": "Rødrev",
    "species.reindeer": "Rein",
    "species.wild_boar": "Villsvin",
    "species.cow": "Storfe",
    "class.stag": "Bukk",
    "class.hind": "Kolle",
    "class.hind_calf": "Kolle + kalv",
    "class.boar": "Råne",
    "class.sow": "Purke",
    "class.sow_piglets": "Purke + smågriser",
    "class.sounder": "Villsvinflokk",
    "class.herd": "{name} (flokk)",
    "class.animal": "Dyr",
    "class.animals": "Dyr",

    # ---- signing in ----------------------------------------------------------
    "auth.not_authenticated": "Du er ikke logget inn",
    "auth.bad_credentials": "Ugyldige innloggingsopplysninger",
    "auth.token_invalid": "Ugyldig eller utløpt innlogging",
    "auth.token_subject": "Ugyldig innloggings-ID",
    "auth.user_not_found": "Fant ikke brukeren",
    "auth.signed_out": "Du ble logget ut. Logg inn igjen.",
    "auth.admin_only": "Bare jaktfeltets admin kan gjøre det.",
    "auth.busy": "Serveren er opptatt. Prøv igjen om et minutt.",
    "auth.wrong_password": "Feil e-post eller passord",
    "auth.published": (
        "Det er passordet som er publisert med GameSense, så det kan ikke logge inn fra internett. "
        "Logg inn fra serverens eget nettverk og bytt det i Innstillinger, eller kjør på serveren: "
        "python -m app.manage set-password {email}"
    ),
    "auth.language_unknown": "Velg English, Suomi, Svenska, Norsk eller Español.",
    "auth.not_current_password": "Det er ikke det nåværende passordet ditt",
    "auth.new_password_short": "Det nye passordet må ha minst 8 tegn",
    "auth.password_changed": (
        "Passordet er byttet. Alle andre telefoner som er logget inn som deg, må logge inn igjen."
    ),

    # ---- people on the app ---------------------------------------------------
    "users.email_invalid": "Skriv inn en gyldig e-postadresse",
    "users.password_short": "Passordet må ha minst 8 tegn",
    "users.pick_role": "Velg Medlem eller Admin",
    "users.email_taken": "Noen med den e-postadressen har allerede en innlogging",
    "users.gone": "Den personen er ikke lenger i appen.",
    "users.not_yourself": "Du kan ikke fjerne deg selv",
    "users.keep_admin": "Behold minst én admin",
    "users.remove_failed": (
        "Kunne ikke fjerne {email}: noe i appen peker fortsatt på personen. Ingenting ble endret. "
        "Prøv igjen, eller spør den som drifter serveren."
    ),
    "users.removed": (
        "{email} kan ikke logge inn lenger. Det personen har registrert, blir liggende."
    ),
    "users.logins_moved": {
        "one": "{n} kamerainnlogging som personen la til, henter fortsatt bilder, nå i ditt navn.",
        "other": (
            "{n} kamerainnlogginger som personen la til, henter fortsatt bilder, nå i ditt navn."
        ),
    },

    # ---- Tonight -------------------------------------------------------------
    "time.hours": "{h} t",
    "time.clock": "kl. {h}",
    "time.minutes": "{m} min",
    "sun.at_sunset": "solnedgang",
    "sun.after": "{span} etter solnedgang",
    "sun.before": "{span} før solnedgang",
    "tonight.factor.not_sending": {
        "one": "Kameraet sender ikke bilder nå. Vurderingen bygger på {n} natts historikk.",
        "other": "Kameraet sender ikke bilder nå. Vurderingen bygger på {n} netters historikk.",
    },
    "tonight.factor.unchecked": (
        "Bilder fra {n} av de siste 7 nettene blir fortsatt sjekket. Vurderingen bygger på "
        "historikken."
    ),
    "tonight.factor.few_watched": (
        "Bare {n} av de siste 7 nettene overvåket her. Vurderingen bygger på historikken."
    ),
    "tonight.factor.not_watched": " ({n} uten overvåking)",
    "tonight.factor.seen_week": "{species} sett {n} av de siste 7 nettene her{gap}",
    "tonight.factor.none_week": "Ingen {species} her de siste 7 nettene{gap}",
    "tonight.factor.outside_hours": (
        "{species} bare sett her utenom timene du kan sitte på post, så det finnes ingen beste "
        "timer å gi"
    ),
    "tonight.best_hours": "Beste timer {start}–{end}",
    "tonight.best_hours_from": "Beste timer {start}–{end}, fra {relative}",
    "tonight.left_out.unchecked_n": "{n} med bilder som ikke er sjekket ennå",
    "tonight.left_out.unchecked": "bildene er ikke sjekket ennå",
    "tonight.left_out.blind_n": "{n} der kameraet kanskje ikke overvåket",
    "tonight.left_out.blind": "kameraet overvåket kanskje ikke",
    "tonight.left_out": {
        "one": "{n} natt ved {camera} utelatt: {why}.",
        "other": "{n} netter ved {camera} utelatt: {why}.",
    },
    "tonight.alert.silent": "Ingen bilder på {n} dager, så det er utelatt fra kveldens rangering",
    "tonight.none.picked": "Ingen kameraer har sett dyrene du valgte ennå.",
    "tonight.none.sending": "Kameraene som sender bilder, har ikke sett noen dyr ennå.",
    "tonight.none.yet": "Ingen observasjoner ennå.",
    "tonight.reason": "{species} sett {n} av {total} netter ved dette kameraet.",
    "tonight.caveat": (
        "Kameraet overvåker hele natten. Du sitter der noen timer, så velg de beste timene og pass "
        "på vinden."
    ),

    # ---- wind ----------------------------------------------------------------
    "compass.N": "N",
    "compass.NE": "NØ",
    "compass.E": "Ø",
    "compass.SE": "SØ",
    "compass.S": "S",
    "compass.SW": "SV",
    "compass.W": "V",
    "compass.NW": "NV",
    "wind.reading": "Vind {dir} {speed} km/t",
    "wind.no_forecast": "Ingen vindvarsel i kveld. Sjekk selv.",
    "wind.no_forecast_stand": "Ingen vindvarsel i kveld. Sjekk selv før du setter deg på {stand}.",
    "wind.no_position": (
        "{reading}. {stand} er ikke på kartet ennå, så det går ikke å regne ut hvor teften din går."
    ),
    "wind.no_bedding": (
        "{reading}. Ingen liggeplasser er tegnet inn ennå, så det går ikke å regne ut hvor teften "
        "din havner. Tegn inn hvor dyrene ligger på kartet."
    ),
    "wind.no_stand": (
        "{reading}. Ingen post nær {camera} ennå, så vinden kan ikke vurderes for en plass. Vurder "
        "den selv."
    ),
    "wind.arcs.too_light": (
        "Vind {dir} {speed} km/t, for svak til å vurdere. Termikken avgjør. Sjekk ved bilen."
    ),
    "wind.arcs.no_geometry": (
        "Vind {dir} {speed} km/t. {stand} har ingen innkomstretninger satt, så vurder vinden selv."
    ),
    "wind.arcs.divert": " Ta heller {stand}.",
    "wind.arcs.wrong": (
        "Vind {dir} {speed} km/t, feil for {stand}. Teften din blåser rett mot trekket fra "
        "{approach}.{divert}"
    ),
    "wind.arcs.clean": (
        "Vind {dir} {speed} km/t, god for {stand}. Teften din går mot {scent}, bort fra der de "
        "kommer inn."
    ),

    # ---- slope wind and bedding ----------------------------------------------
    "thermal.no_terrain": "Ingen terrengmodell lastet inn, så hellingsvinden kan ikke regnes ut.",
    "thermal.off_terrain": (
        "Stedet ligger utenfor terrengmodellen som er lastet inn, så hellingsvinden kan ikke regnes"
        " ut. En admin kan laste inn terrenget på nytt så det dekker stedet."
    ),
    "thermal.flat": "Terrenget er nesten flatt her. Ingen helling for kald luft å renne ned.",
    "thermal.overcast": "Overskyet ({pct} %), så hellingsvinden blir svak i kveld. Sjekk selv.",
    "thermal.katabatic": (
        "Varselet er vindstille, så hellingen avgjør. Kald luft renner nedover mot {dir} i omtrent "
        "{speed} km/t. Teften din følger med."
    ),
    "thermal.katabatic_settling": (
        "Varselet er vindstille, så hellingen avgjør. Kald luft renner nedover mot {dir} i omtrent "
        "{speed} km/t. Den legger seg fortsatt i skumringen og kan snu. Teften din følger med."
    ),
    "thermal.anabatic": (
        "Stille og sol, så luften stiger oppover hellingen mot {dir}. Den snur og renner nedover "
        "igjen rundt solnedgang."
    ),
    "bedding.no_position": "{stand} har ingen posisjon på kartet ennå.",
    "bedding.none": (
        "Ingen liggeplasser tegnet inn ennå — tegn inn hvor dyrene ligger, så blir dette et råd."
    ),
    "bedding.too_light": "Vind {dir} {speed} km/t — for svak til å vurdere. {why}",
    "bedding.thermals_decide": "Termikken avgjør denne; les den av ved bilen.",
    "bedding.lead.katabatic": (
        "Vindstille varsel, så hellingen avgjør — kald luft renner mot {dir} i ~{speed} km/t{fall}"
    ),
    "bedding.fall": " ({pct} % fall)",
    "bedding.lead.anabatic": "Stille og sol — luften trekkes oppover mot {dir} i ~{speed} km/t",
    "bedding.caveat.dusk": " Den snur rundt skumringen, så sjekk på stedet.",
    "bedding.caveat.dem": " En terrengmodell på ~90 m ser lia, ikke kløfta di.",
    "bedding.into_own": "inn i {zone}, liggeplassen posten din står i",
    "bedding.into_near": "inn i {zone} {m} m unna",
    "bedding.into_far": "inn i {zone}, {m} m unna",
    "bedding.carries.thermal": "{lead}, og bærer teften din {where}.{caveat}",
    "bedding.carries.wind": "{lead} — teften din går mot {dir} {where}.",
    "bedding.clean.thermal": "{lead}, bort fra liggeplassene ({m} m til nærmeste).{caveat}",
    "bedding.clean.wind": (
        "{lead} — rent. Teften går mot {dir}, bort fra liggeplassene ({m} m til nærmeste)."
    ),
    "bedding.draw": "Tegn inn liggeplasser for å se dette.",
    "bedding.no_forecast": "Ingen vindvarsel i kveld.",
    "bedding.too_light_map": "Vinden er for svak til å kartlegge — en slik kveld avgjør termikken.",
    "bedding.safe.note": (
        "Bare geometri — dette vet ingenting om dekning, adkomst eller sikker kulefang. Det snevrer"
        " inn hvor du bør lete; det velger ikke plassen."
    ),
    "bedding.safe.note_calm": (
        "Varselet er vindstille, så dette følger terrenget: hver rute bruker sin egen falllinje, "
        "fordi kald luft renner nedover etter mørkets frembrudd. En terrengmodell på ~90 m ser lia,"
        " ikke kløfta du sitter i."
    ),

    # ---- what changed --------------------------------------------------------
    "num.decimal_mark": ",",
    "count.visits": {
        "one": "{n} besøk",
        "other": "{n} besøk",
    },
    "changed.about": "omtrent {x}",
    "changed.no_cameras": "Ingen kameraer er satt opp ennå.",
    "changed.camera_down": "{camera} sendte ingenting i natt. Ukjent om noe passerte.",
    "changed.return": {
        "one": "Dyr tilbake ved {camera} etter {n} rolig natt.",
        "other": "Dyr tilbake ved {camera} etter {n} rolige netter.",
    },
    "changed.gone_quiet": {
        "one": "{camera} har vært stille i {n} natt. Der pleier det å være {usual} besøk per natt.",
        "other": (
            "{camera} har vært stille i {n} netter. Der pleier det å være {usual} besøk per natt."
        ),
    },
    "changed.busier": "Mer liv enn vanlig ved {camera} i natt: {visits} mot vanligvis {usual}.",
    "changed.quieter": "Roligere enn vanlig ved {camera} i natt: {visits} mot vanligvis {usual}.",
    "changed.some_cameras": "noen kameraer",
    "changed.checking": "Nattens bilder fra {cameras} blir fortsatt sjekket.",
    "changed.none": "Ingen endring. Omtrent som de siste nettene.",

    # ---- camera health -------------------------------------------------------
    "health.retired": "Tatt ut av bruk {day}. Utelatt fra kveldens plan og tallene",
    "health.disconnected": "Ikke tilkoblet: ingen kamerainnlogging her henter det nå",
    "health.not_syncing": "Bildene kommer ikke inn. Kamerainnloggingen må ses på.",
    "health.not_fetched": "Bildene kommer ikke inn. Ingen bildehenting har virket på over 2 timer.",
    "health.fetch_error": "Bildene kommer ikke inn. {error}",
    "health.no_photos_since": "Ingen bilder siden {day}",
    "health.no_photos": "Ingen bilder ennå",
    "health.photos_only": "Sender bare bilder, ingen statusmeldinger",
    "health.clock_fast": (
        ". Klokka går {h} t for fort (glemt omstillingen?): bildetidene rettes, men still klokka på"
        " kameraet"
    ),
    "health.no_checkin_for": "Ingen kontakt siden {day}",
    "health.no_checkin": "Ingen kontakt ennå",
    "health.photo_limit": "Tom for bildekreditter ({count}/{limit})",
    "health.battery_low": "Lavt batteri ({pct} %)",
    "health.ok": "Rapporterer som normalt",

    # ---- camera logins (kept in English, said in the reader's language) ------
    "login.unreadable": "Det lagrede passordet kan ikke leses. Skriv det inn på nytt.",
    "login.spypoint_refused": "SPYPOINT godtok ikke passordet. Skriv det inn på nytt.",
    "login.ubox_refused": "UBox godtok ikke passordet. Skriv det inn på nytt.",
    "login.ubox_signed_out": "UBox logget ut denne innloggingen. Skriv inn passordet på nytt.",
    "login.spypoint_throttled": (
        "SPYPOINT avviser forespørsler akkurat nå. Neste henting prøver igjen."
    ),
    "login.spypoint_down": "SPYPOINT svarer ikke ordentlig akkurat nå. Neste henting prøver igjen.",
    "login.spypoint_refused_request": "SPYPOINT avviste forespørselen. Neste henting prøver igjen.",
    "login.spypoint_unreadable": (
        "SPYPOINT sendte noe appen ikke kan lese. Neste henting prøver igjen."
    ),
    "login.ubox_unknown": (
        "UBox kjenner ikke denne innloggingen. Sjekk e-posten som brukes i UBox Pro-appen."
    ),
    "login.unreachable": "Fikk ikke kontakt med {provider}. Neste henting prøver igjen.",
    "login.ubox_down": "UBox svarer ikke ordentlig akkurat nå. Neste henting prøver igjen.",
    "login.other": "{text}. Neste henting prøver igjen.",
    "login.failed": "Hentingen fra {provider} feilet ({error}). Neste henting prøver igjen.",
    "login.primary_label": "Hovedinnlogging for SPYPOINT",

    # ---- photo fetches (kept in English, said in the reader's language) ------
    "login.copy_of_primary": (
        "Dette er jaktfeltets hovedinnlogging for SPYPOINT, som allerede hentes. Fjern denne "
        "kopien."
    ),
    "sync.some_failed": "{n} av {total} kameraer feilet. {error}",
    "sync.login_not_saved": (
        "Bildene kom inn, men statusen til innloggingen kunne ikke lagres ({error}). "
        "Neste henting prøver igjen."
    ),
    "ubox.snap.retry": {
        "one": "{n} bilde lot seg ikke laste ned. Neste henting prøver igjen.",
        "other": "{n} bilder lot seg ikke laste ned. Neste henting prøver igjen.",
    },
    "ubox.snap.dropped": {
        "one": "{n} bilde lot seg ikke laste ned. Det ble prøvd {tries} ganger, så det utelates.",
        "other": "{n} bilder lot seg ikke laste ned. De ble prøvd {tries} ganger, så de utelates.",
    },
    "ubox.snap.some": {
        "one": (
            "{failed} bilder lot seg ikke laste ned. {n} prøves igjen ved neste henting; resten ble"
            " prøvd {tries} ganger og utelates."
        ),
        "other": (
            "{failed} bilder lot seg ikke laste ned. {n} prøves igjen ved neste henting; resten ble"
            " prøvd {tries} ganger og utelates."
        ),
    },

    # ---- UBox errors (kept in English, said in the reader's language) --------
    "ubox.err.host_unresolved": "Navnet på UBox sin bildeserver kunne ikke slås opp",
    "ubox.err.host_public": "UBox sin bildeadresse må bruke en offentlig HTTPS-server",
    "ubox.err.bad_json": "UBox svarte med ugyldig JSON",
    "ubox.err.unexpected": "UBox ga et uventet svar",
    "ubox.err.rejected_password": "UBox avviste kontoen eller passordet",
    "ubox.err.rejected_request": "UBox avviste forespørselen; sjekk kontoen i UBox Pro",
    "ubox.err.no_data": "Svaret fra UBox mangler dataobjekt",
    "ubox.err.need_login": "E-post og passord for UBox kreves",
    "ubox.err.unreachable_login": "Fikk ikke kontakt med UBox for innlogging",
    "ubox.err.no_token": "Innloggingssvaret fra UBox mangler økt-token",
    "ubox.err.unreachable": "Fikk ikke kontakt med UBox",
    "ubox.err.auth_expired": (
        "UBox-innloggingen gikk ut etter nytt forsøk; koble til kontoen på nytt"
    ),
    "ubox.err.auth_failed": "UBox-autentiseringen feilet",
    "ubox.err.no_devices": "Enhetssvaret fra UBox mangler opplysninger",
    "ubox.err.device_no_id": "UBox returnerte en enhet uten ID",
    "ubox.err.naive_dates": "Hendelsessøket i UBox krever datoer med tidssone",
    "ubox.err.bad_range": "Hendelsessøket i UBox har ugyldig tidsrom eller sidestørrelse",
    "ubox.err.no_events": "Hendelsessvaret fra UBox mangler liste",
    "ubox.err.incomplete_page": (
        "UBox ga en ufullstendig hendelsesside; hentingen prøver igjen senere"
    ),
    "ubox.err.bad_event": "UBox returnerte en ugyldig hendelse",
    "ubox.err.repeated_page": "UBox gjentok en hendelsesside; hentingen prøver igjen senere",
    "ubox.err.bad_event_fields": "En UBox-hendelse har ugyldig tidsstempel eller kamera-ID",
    "ubox.err.fewer_events": "UBox ga færre hendelser enn oppgitt; hentingen prøver igjen",
    "ubox.err.page_limit": "Grensen for hendelsessider i UBox er nådd; bruk en kortere periode",
    "ubox.err.https_only": "UBox sin bildeadresse må bruke HTTPS",
    "ubox.err.too_big": "UBox-bildet er større enn nedlastingsgrensen på 20 MB",
    "ubox.err.empty_image": "UBox returnerte et tomt bilde",
    "ubox.err.download_failed": "Kunne ikke laste ned UBox-bildet",
    "ubox.err.unknown_account": (
        "UBox kjente ikke igjen kontoen. Sjekk riktig kameraapp og e-posten den er logget inn med."
    ),
    "ubox.err.login_http": "UBox-innloggingen feilet (HTTP {status})",
    "ubox.err.request_http": "UBox-forespørselen feilet (HTTP {status})",
    "ubox.err.download_http": "Nedlastingen av UBox-bildet feilet (HTTP {status})",
    "ubox.err.other_estate": "Dette UBox-kameraet er allerede koblet til et annet jaktfelt",
    "ubox.err.snapshot_size": "Bildet er tomt eller større enn 20 MB",
    "ubox.err.snapshot_pixels": "Bildet må være en JPEG på høyst 40 megapiksler",
    "ubox.err.snapshot_unreadable": "Bildet er ikke en lesbar JPEG",
    "ubox.err.snapshot_failed": "Kunne ikke laste ned et lesbart bilde",
    "ubox.err.no_estate": "Kontoen har ikke noe jaktfelt",
    "fetch.disk_label": "Serverens disk",
    "fetch.failed": "Hentingen feilet. Neste henting prøver igjen.",
    "fetch.disk_full": (
        "Nesten full ({gb} GB ledig). Bildene venter i kameraene og kommer inn når det er plass."
    ),
    "fetch.provider_failed": (
        "Hentingen fra {provider} feilet ({error}). Neste henting prøver igjen."
    ),
    "fetch.ai_failed": "Søket etter dyr feilet ({error})",

    # ---- the AI pass (kept in English, said in the reader's language) --------
    "ai.detector_failed": "Dyredetektoren kunne ikke starte ({error}).",
    "ai.classifier_failed": "Artsmodellen kunne ikke starte ({error}).",
    "ai.models_broken": "Modellene sluttet å virke ({error}).",
    "ai.stopped_streak": (
        "{why} Sjekkingen stanset etter at {n} bilder på rad feilet; de ble ikke regnet mot "
        "bildene."
    ),

    # ---- photos --------------------------------------------------------------
    "photos.not_checked": "Ikke sjekket ennå",
    "photos.could_not_check": "Kunne ikke sjekkes",
    "photos.people_admin_only": "Bare en admin ser bildene med folk eller kjøretøy i.",
    "photos.gone": "Det bildet er ikke tilgjengelig lenger.",
    "people.person_vehicle": "Person og kjøretøy",
    "people.person": "Person",
    "people.vehicle": "Kjøretøy",
    "people.person_or_vehicle": "Person eller kjøretøy",

    # ---- cameras and the Check button ----------------------------------------
    "busy.reid": "leter etter gjengangere",
    "busy.plan": "skriver kveldens plan",
    "busy.score": "sammenligner gårsdagens plan med kameraene",
    "busy.scan": "leter etter dyr i bildene",
    "busy.deploy": "installerer en oppdatering",
    "busy.other": "holder på med en annen jobb",
    "busy.fetch": "henter bilder",
    "busy.try_later": "Serveren {what}. Prøv igjen om noen minutter.",
    "cameras.start_failed": "Kunne ikke starte det på serveren. Prøv igjen om et minutt.",
    "cameras.name_hidden_chars": "Kameranavnet har skjulte tegn. Skriv det inn på nytt.",
    "cameras.name_length": "Kameranavnet må ha 1 til 100 tegn.",
    "cameras.rename_forbidden": "Bare jaktfeltets admins og medlemmer kan gi kameraer nytt navn.",
    "cameras.not_found": "Fant ikke kameraet.",
    "cameras.name_taken": "Et annet kamera heter allerede {name}. Velg et annet navn.",
    "cameras.name_taken_reset": (
        "Et annet kamera heter allerede {name}, så dette beholder sitt eget navn."
    ),
    "cameras.check_viewer": "Nye bilder kommer inn av seg selv hvert 15. minutt.",
    "cameras.check_running": "Sjekker allerede. Nye bilder vises snart.",
    "cameras.check_asked": "Allerede bedt om. Nye bilder kommer så snart serveren er ledig.",
    "cameras.check_queued": "Serveren {what}. Nye bilder kommer når den er ferdig.",
    "cameras.off_map": "Det stedet er utenfor kartet. Flytt kartet og prøv igjen.",
    "cameras.no_own_position": (
        "Dette kameraet har ikke rapportert en egen posisjon. Plasser det for hånd."
    ),

    # ---- camera logins in Settings -------------------------------------------
    "accounts.viewer": "Lesere kan se kamerainnloggingene, men ikke legge til noen.",
    "accounts.enter_login": "Skriv inn e-post og passord for {provider}",
    "accounts.no_estate": "Bli med i et jaktfelt før du legger til en kamerainnlogging",
    "accounts.is_primary": "Denne innloggingen er allerede koblet til som jaktfeltets hovedkonto",
    "accounts.already_added": "Den innloggingen for {provider} er allerede lagt til",
    "accounts.already_added_refresh": (
        "Den innloggingen for {provider} er allerede lagt til. Oppdater for å se den."
    ),
    "accounts.connected_now": {
        "one": "Tilkoblet — {provider} melder {n} kamera. Henter bilder nå.",
        "other": "Tilkoblet — {provider} melder {n} kameraer. Henter bilder nå.",
    },
    "accounts.connected_later": {
        "one": "Tilkoblet — {provider} melder {n} kamera. Bildene kommer ved neste henting.",
        "other": "Tilkoblet — {provider} melder {n} kameraer. Bildene kommer ved neste henting.",
    },
    "accounts.unreachable": (
        "Fikk ikke kontakt med {provider} for å sjekke passordet. Prøv igjen om noen minutter."
    ),
    "accounts.ubox_failed": "Kunne ikke koble til UBox Pro: {error}",
    "accounts.spypoint_refused": (
        "SPYPOINT godtok ikke e-posten og passordet. Sjekk dem i SPYPOINT-appen."
    ),
    "accounts.spypoint_failed": "SPYPOINT godtok ikke innloggingen: {error}",
    "accounts.not_found": "Fant ikke kontoen",
    "accounts.password_forbidden": (
        "Bare den som la til innloggingen, eller en admin, kan bytte passordet"
    ),
    "accounts.enter_password": "Skriv inn passordet",
    "accounts.password_saved": (
        "Passordet er lagret. Bildene kommer ved neste henting, innen 15 minutter."
    ),
    "accounts.limits_forbidden": (
        "Bare den som la til innloggingen, eller en admin, kan endre grensene"
    ),
    "accounts.limits_ubox_only": "Bildegrenser gjelder bare innlogginger for UBox Pro",
    "accounts.limits_saved": "Grensene er lagret. De gjelder fra neste henting.",
    "accounts.remove_forbidden": "Bare den som la til innloggingen, eller en admin, kan fjerne den",

    # ---- alerts on the phone -------------------------------------------------
    "push.just_now": "akkurat nå",
    "push.time": "kl. {time}",
    "push.since_time": "kl. {time}",
    "push.last_night": "i natt kl. {time}",
    "push.yesterday": "i går kl. {time}",
    "push.on_day": "{day} kl. {time}",
    "push.at_camera": "{name} ved {camera}",
    "push.on_cameras": {
        "one": "{name} på {n} kamera",
        "other": "{name} på {n} kameraer",
    },
    "push.one_visit": "1 besøk {when}.",
    "push.visits_last": "{visits}, sist {when}.",
    "push.visits_at_last": "{visits} ved {cameras}, sist {when}.",
    "push.at_cameras": " ved {cameras}",
    "push.update": "{visits}{where} siden {since}, sist {last}.",
    "push.summary_title": "{n} nye observasjoner, {animals} dyr",
    "push.summary_body": "{names}, sist {when}.",
    "verdict.best_odds": "Best sjanse",
    "verdict.worth_a_look": "Verdt en titt",
    "verdict.quiet": "Stille",
    "verdict.no_data": "For lite å gå på",
    "plan.wind.clean": "riktig vind",
    "plan.wind.wrong": "feil vind",
    "plan.wind.too_light": "for svak vind til å vurdere",
    "plan.wind.no_forecast": "ingen vindvarsel",
    "plan.tonight": "{verdict} i kveld",
    "plan.sunset": "solnedgang {time}",
    "plan.no_camera": (
        "For få overvåkede netter til å vurdere kvelden. Åpne appen for å se hva kameraene har "
        "sett."
    ),
    "plan.species_hours": "{species}, best {start}–{end}.",
    "held.one": "{name}: {visits} ved {cameras}",
    "held.each": "{name}: {visits}",
    "held.worth_a_look": {
        "one": "{n} bilde merket Verdt en titt",
        "other": "{n} bilder merket Verdt en titt",
    },
    "held.title.sit": "Mens du satt på post",
    "held.title.quiet": "I de stille timene dine",
    "held.body": "{parts}, sist {when}.",

    # ---- alert settings ------------------------------------------------------
    "alerts.unknown_camera": "Ukjent kamera: {ids}",
    "alerts.unknown_species": "Ukjent art: {ids}",
    "alerts.quiet_needs_both": "Stille timer trenger en start og en slutt.",
    "alerts.quiet_same": "Stille timer kan ikke starte og slutte samtidig.",
    "alerts.endpoint_https": "Push-adressen må være en https-adresse",
    "alerts.no_phone": "Ingen telefon får varsler ennå. Slå på varsler fra den telefonen først.",
    "alerts.test_title": "Testvarsel",
    "alerts.test_body": "Varslene virker på denne telefonen.",

    # ---- team notes and people -----------------------------------------------
    "notes.bad_chars": "Notatet har tegn som ikke kan lagres. Skriv det på nytt.",
    "notes.too_long": "Hold notatet til {n} tegn.",
    "notes.push_title": "Verdt en titt: {label} ved {camera}",
    "notes.push_body": "{name}: {text}",
    "notes.push_marked": "{name} merket et bilde",
    "notes.empty_frame": (
        "Dette bildet er merket «ingenting i det». Behold det som dyrebilde først."
    ),
    "notes.hidden_only": (
        "Bare dyr som er skjult i appen, er i dette bildet, så laget kan ikke se det."
    ),
    "notes.people_only": (
        "Det er en person eller et kjøretøy i dette bildet, så det blir hos admins og laget kan "
        "ikke se det."
    ),
    "notes.not_looked": (
        "Appen har ikke sjekket dette bildet ennå, så laget kan ikke se det. Prøv igjen om noen "
        "minutter."
    ),
    "notes.photo_not_found": "Fant ikke bildet.",
    "notes.viewer": "Lesere kan se notater, men ikke legge til noen.",
    "notes.not_saved": "Notatet kunne ikke lagres. Lukk det og prøv igjen.",
    "notes.gone": "Notatet er allerede borte.",
    "notes.remove_forbidden": "Bare den som skrev det, eller en admin, kan fjerne et notat.",
    "people.hunter": "Jeger",
    "people.removed": "Fjernet person",
    "crash.too_large": "Rapporten er for stor",
    "crash.not_a_report": "Det er ikke en krasjrapport.",
    "crash.too_many": "For mange rapporter. Senere rapporter forkastes.",
    "crash.unknown_device": "Ukjent enhet",

    # ---- stands and sits -----------------------------------------------------
    "stands.no_estate": "Sett opp jaktfeltet først.",
    "stands.auto_name": "Post {camera}",
    "stands.auto_note": (
        "Hver post er plassert ved kameraet sitt. Flytt den dit du faktisk sitter. Vindrådene "
        "starter når du setter retningene dyrene kommer fra."
    ),
    "stands.camera_gone": "Det kameraet er ikke i appen.",
    "stands.gone": "Den posten er ikke i appen.",
    "stands.has_sits": {
        "one": (
            "{n} postering er registrert ved denne posten. Å slette den ville viske ut historikken."
            " Gi den heller nytt navn."
        ),
        "other": (
            "{n} posteringer er registrert ved denne posten. Å slette den ville viske ut "
            "historikken. Gi den heller nytt navn."
        ),
    },
    "stands.claimed": "{stand} er allerede reservert i kveld av en annen jeger.",
    "stands.arc_conflict": (
        "{stand} og {other} deler skuddsektor, og {other} er tatt i kveld. Velg en annen post."
    ),
    "stands.viewer": "Lesere kan se postene, men ikke reservere noen.",
    "sits.gone": "Den posteringen er ikke i appen.",
    "sits.viewer": "Lesere kan se posteringene, men ikke endre dem.",
    "sits.not_yours": "Den posteringen er en annen jegers.",
    "sits.bad_outcome": "utfallet må være ett av {outcomes}",
    "sits.cancelled": "Den reservasjonen ble avlyst. Reserver posten på nytt.",
    "sits.already_reported": "Du har allerede sagt hva som skjedde på denne posteringen.",
    "sits.not_started": "Den posteringen har ikke startet.",

    # ---- approach lines and the dark exit ------------------------------------
    "arcs.no_camera": "Denne posten er ikke koblet til et kamera.",
    "arcs.camera_unplaced": "Det tilkoblede kameraet har ingen registrert posisjon.",
    "arcs.no_others": "Ingen andre plasserte kameraer å lese bevegelser fra.",
    "arcs.note": {
        "one": "{n} gang kom dyrene til {camera} innen {minutes} min etter at de passerte {other}.",
        "other": (
            "{n} ganger kom dyrene til {camera} innen {minutes} min etter at de passerte {other}."
        ),
    },
    "arcs.none": (
        "Ingen gjentatt bevegelse mellom kameraene ennå — ikke nok til å foreslå et trekk, så appen"
        " lar fortsatt denne være din å løse."
    ),
    "exit.no_visits": "Ingen besøk ved postens kamera ennå.",
    "exit.quiet": (
        "Gå ut i mørket kl. {time} — bare {pct} % av kameraets besøk faller i timen etter, så da "
        "forstyrrer du minst."
    ),
    "exit.busy_reason": "Ingen virkelig stille time — denne posten har liv hele natten.",
    "exit.busy": (
        "Ingen stille time etter kl. {after} ved denne posten — liv hele natten. Kl. {time} er den "
        "minst dårlige tiden å gå ut."
    ),

    # ---- the harvest book ----------------------------------------------------
    "harvest.sex.male": "Hann",
    "harvest.sex.female": "Hunn",
    "harvest.sex.unknown": "Usikker",
    "harvest.age.juvenile": "Årsunge",
    "harvest.age.young_adult": "Ungdyr",
    "harvest.age.mature_adult": "Voksen",
    "harvest.age.old": "Gammel",
    "harvest.age.unknown": "Usikker",
    "harvest.viewer": "Lesere kan ikke føre felt vilt.",
    "harvest.not_yours": "Det felte viltet er en annen jegers. En admin kan endre det.",
    "harvest.not_a_shot": "Den posteringen er ikke rapportert som skudd. Si hva som skjedde først.",
    "harvest.field.seal": "merkenummer",
    "harvest.field.note": "notat",
    "harvest.field.name": "navn",
    "harvest.hidden_chars": "Feltet «{what}» har skjulte tegn. Skriv det på nytt.",
    "harvest.too_long": "Feltet «{what}» kan ha høyst {n} tegn.",
    "harvest.bad_species": "Velg et av dyrene på listen.",
    "harvest.bad_sex": "Kjønn er hann, hunn eller usikker.",
    "harvest.bad_age": "Velg en alder fra listen.",
    "harvest.future": "Det tidspunktet har ikke kommet ennå. Sjekk datoen.",
    "harvest.too_old": "Den datoen er for langt tilbake. Sjekk året.",
    "harvest.bad_season": "Velg en sesong fra listen.",
    "harvest.not_saved": "Det felte viltet kunne ikke lagres. Lukk og prøv igjen.",
    "harvest.gone": "Det felte viltet er ikke i boka lenger.",
    "harvest.admin_names": "Bare en admin kan endre navnet på felt vilt.",
    "harvest.col.date": "Dato",
    "harvest.col.time": "Tid",
    "harvest.col.species": "Art",
    "harvest.col.sex": "Kjønn",
    "harvest.col.age": "Alder",
    "harvest.col.seal": "Merkenummer",
    "harvest.col.weight": "Vekt (kg)",
    "harvest.col.hunter": "Jeger",
    "harvest.col.stand": "Post",
    "harvest.col.notes": "Notater",

    # ---- the activity map ----------------------------------------------------
    "activity.part.dusk": "i skumringen",
    "activity.part.night": "midt på natten",
    "activity.part.dawn": "i grålysningen",
    "activity.checking_last": "Nattens bilder blir fortsatt sjekket.",
    "activity.checking": "Bildene blir fortsatt sjekket.",
    "activity.unreadable_last": "Ikke telt: ikke alle bildene fra i natt kunne sjekkes.",
    "activity.unreadable": "Ikke telt: ikke alle bildene kunne sjekkes.",
    "activity.blind_last": "Ikke telt: kameraet virket kanskje ikke i natt.",
    "activity.blind": "Ikke telt: kameraet virket ikke disse nettene.",
    "activity.tail.times": ", kl. {times}",
    "activity.tail.mostly": ", mest kl. {peak}",
    "activity.tail.busiest": ", mest liv kl. {peak}",
    "activity.tail.no_set_time": ", uten fast tid",
    "activity.last_night": "i natt",
    "activity.last_night_so_far": "i natt så langt",
    "activity.one.nothing_all": "Ingenting på kameraet{when} {night}.",
    "activity.one.nothing": "Ingen {species}{when} {night}.",
    "activity.one.visits_all": {
        "one": "{n} dyrebesøk{when} {night}{tail}",
        "other": "{n} dyrebesøk{when} {night}{tail}",
    },
    "activity.one.visits": {
        "one": "{n} besøk av {species}{when} {night}{tail}",
        "other": "{n} besøk av {species}{when} {night}{tail}",
    },
    "activity.q.working": " da det virket",
    "activity.q.checkable": " som kunne sjekkes",
    "activity.q.so_far": " som er sjekket så langt",
    "activity.none_all": {
        "one": "Ingen dyr{when} den {n} natten{qualifier}.",
        "other": "Ingen dyr{when} de {n} nettene{qualifier}.",
    },
    "activity.none": {
        "one": "Ingen {species}{when} den {n} natten{qualifier}.",
        "other": "Ingen {species}{when} de {n} nettene{qualifier}.",
    },
    "activity.some": "{who} på {n} av {total} netter{qualifier}{tail}",

    # ---- the map -------------------------------------------------------------
    "map.bad_nights": "Antall netter er 1, 7 eller 30.",
    "map.no_species": "Ingen slik art.",
    "map.no_replay": "Det finnes ingen avspilling for den natten.",

    # ---- insights: what moves the animals ------------------------------------
    "class.animals_all": "Alle dyr",
    "patterns.moon_illum.label": "Månelys",
    "patterns.moon_illum.high": "lys måne",
    "patterns.moon_illum.low": "mørk måne",
    "patterns.pressure.label": "Lufttrykk",
    "patterns.pressure.high": "høytrykk",
    "patterns.pressure.low": "lavtrykk",
    "patterns.pressure_trend.label": "Trykkutvikling",
    "patterns.pressure_trend.high": "stigende trykk",
    "patterns.pressure_trend.low": "fallende trykk",
    "patterns.temp.label": "Temperatur",
    "patterns.temp.high": "varmt vær",
    "patterns.temp.low": "kjølig vær",
    "patterns.wind.label": "Vind",
    "patterns.wind.high": "vind",
    "patterns.wind.low": "stille luft",
    "patterns.rain.label": "Regn",
    "patterns.rain.high": "regn",
    "patterns.rain.low": "opphold",
    "patterns.cloud.label": "Skydekke",
    "patterns.cloud.high": "skyer",
    "patterns.cloud.low": "klar himmel",
    "patterns.darkness.label": "Mørke timer",
    "patterns.darkness.high": "lang natt",
    "patterns.darkness.low": "kort natt",
    "patterns.statement": "Omtrent {hi} besøk per natt med {hi_desc}, omtrent {lo} med {lo_desc}.",
    "insights.midnight": "midnatt",
    "insights.busiest": "Kameraene dine har mest liv mellom {start} og {end}.",
    "insights.species_mostly": "Kameraene ser {species} mest mellom {start} og {end}.",
    "insights.concentrated": (
        "Mesteparten skjer ved {cameras}. De andre kameraene ser langt mindre."
    ),
    "insights.busiest_cameras": "{cameras} er de travleste kameraene dine.",
    "insights.class_missing": "Velg hvilke dyr som skal vises.",

    # ---- species in Settings -------------------------------------------------
    "species.name_hidden_chars": "Navnet har skjulte tegn. Skriv det på nytt.",
    "species.name_length": "Et navn er 1 til 40 tegn.",
    "species.not_found": "Fant ikke arten.",

    # ---- the alerts feed on Tonight ------------------------------------------
    "ago.unknown": "ukjent",
    "ago.just_now": "akkurat nå",
    "ago.ago": "for {span} siden",
    "ago.m": "{n} min",
    "ago.h": "{n} t",
    "ago.d": "{n} d",
    "feed.seen": {
        "one": "Sett {n} gang de siste 2 døgnene, sist {ago}.",
        "other": "Sett {n} ganger de siste 2 døgnene, sist {ago}.",
    },
    "feed.battery_title": "{camera}: lavt batteri",
    "feed.battery": "{pct} % igjen. Ta med batterier neste gang du er der.",
    "feed.since": ", siden natt til {day}",
    "feed.quiet_title": "{camera}: stille",
    "feed.quiet": {
        "one": (
            "Ingenting den siste {n} overvåkede natten{since}. Der pleier det å være {usual} besøk "
            "per natt."
        ),
        "other": (
            "Ingenting de siste {n} overvåkede nettene{since}. Der pleier det å være {usual} besøk "
            "per natt."
        ),
    },

    # ---- the week's wind -----------------------------------------------------
    "week.tonight": "I kveld",
    "week.tonight_hours": "i kveld {hours}",
    "week.no_position": "{stand} er ikke på kartet ennå, så vinden der kan ikke vurderes.",
    "week.no_bedding": (
        "Ingen liggeplasser tegnet inn ennå, så vinden kan ikke vurderes for {stand}."
    ),
    "week.no_geometry": "{stand} har ingen innkomstretninger satt, så vurder vinden der selv.",
    "week.no_forecast": "Ingen vindvarsel for uka ennå.",
    "week.right": "Riktig vind for {stand}: {when}",
    "week.none": "Ingen riktig vind for {stand} denne uka.",

    # ---- the track record ----------------------------------------------------
    "record.too_few": {
        "one": "{n} natt sjekket så langt. Hvor ofte den har truffet, vises etter {needed}.",
        "other": "{n} netter sjekket så langt. Hvor ofte den har truffet, vises etter {needed}.",
    },
    "record.verdict": {
        "one": "Når den sa «{verdict}» om et kamera, kom dyrene dit {came} av {n} ganger.",
        "other": "Når den sa «{verdict}» om et kamera, kom dyrene dit {came} av {n} ganger.",
    },
    "record.beats": "Oddsene lå nærmere det som skjedde enn hvert kameras vanlige nivå.",
    "record.no_better": "Oddsene lå ikke nærmere det som skjedde enn hvert kameras vanlige nivå.",
    "record.too_few_each": {
        "one": "{n} natt sjekket, for få av hver vurdering til å si noe ennå.",
        "other": "{n} netter sjekket, for få av hver vurdering til å si noe ennå.",
    },

    # ---- photos and animals --------------------------------------------------
    "images.viewer": "Lesere kan se bildene, men ikke endre dem.",
    "images.old_link": "Bildelenken har gått ut. Åpne bildet i appen på nytt.",
    "images.sign_in": "Logg inn for å se bilder.",
    "images.no_picture": "Dette bildet har ingen bildefil ennå, så det er ingenting å rette.",
    "images.no_people": "Appen teller allerede ingen i dette bildet.",
    "animals.not_found": "Fant ikke dyret.",
    "animals.gone": "Det dyret er ikke i appen lenger.",
    "animals.name_first": "Skriv et navn først.",
    "animals.name_long": "Et navn kan ha høyst 60 tegn.",
    "animals.bad_status": "status må være en av {statuses}",
    "animals.merge_target": "Fant ikke dyret som skal slås sammen med.",
    "animals.reid_running": "Leter allerede. Det tar noen minutter.",
    "animals.reid_started": "Leter etter gjengangere. Det tar noen minutter.",

    # ---- areas on the map, and admin -----------------------------------------
    "zones.name_needed": "Gi det et navn laget kjenner.",
    "zones.name_not_empty": "Navnet kan endres, men ikke stå tomt.",
    "zones.outline_not_empty": "Omrisset kan endres, men ikke stå tomt.",
    "zones.bad_kind": "typen må være en av {kinds}",
    "zones.gone": "Det området er ikke på kartet.",
    "admin.deploying": "Serveren installerer en oppdatering. Prøv igjen om noen minutter.",
    "admin.no_api_key": "Legg først til ANTHROPIC_API_KEY i .env",
    "admin.labelling": "Merker allerede. Merkene dukker opp i løpet av noen minutter.",
    "admin.labels_coming": "Merkene dukker opp under Kameraer i løpet av noen minutter.",
    "admin.retry": {
        "one": "{n} bilde sjekkes på nytt ved neste henting.",
        "other": "{n} bilder sjekkes på nytt ved neste henting.",
    },
    "admin.nothing_to_retry": "Ingenting å prøve på nytt.",
    "admin.reload": "Last inn appen på nytt: oppdateringer vises nå av seg selv under Appversjon.",

    # ---- server upkeep (kept in English, said in the reader's language) ------
    "restore.no_table": "Den gjenopprettede kopien mangler tabellen {table}.",
    "restore.no_rows": "Den gjenopprettede kopien har ingen rader i {table}.",
    "restore.photos_missing": (
        "{n} av {total} kontrollerte bilder mangler i sikkerhetskopiens bildemappe."
    ),
    "restore.failed": "Kontrollen kunne ikke kjøres ({error}).",
    "ops.unreadable": "Statusfilen kan ikke leses.",

    # ---- drawing on the map --------------------------------------------------
    "shape.not_polygon": "Omrisset må være et GeoJSON-polygon.",
    "shape.no_corners": "Omrisset har ingen hjørner.",
    "shape.too_many": "Omrisset har {n} hjørner. Hold det under {limit}.",
    "shape.two_numbers": "Hvert hjørne må være to tall: lengdegrad, så breddegrad.",
    "shape.off_map": (
        "Et hjørne er utenfor kartet. Hjørnene angis med lengdegrad først, så breddegrad."
    ),
    "shape.three": "Trykk ut minst tre hjørner rundt området.",
    "shape.too_big": "Omrisset er over 20 km bredt. Tegn bare skjulet der dyrene ligger.",
    "shape.crosses": "Omrisset krysser seg selv. Legg hjørnene i rekkefølge rundt kanten.",
    "shape.no_area": "Omrisset har nesten ikke noe areal. Spre hjørnene rundt skjulet.",
    "box.four_numbers": "Rammen trenger fire tall: sør, vest, nord og øst.",
    "box.off_map": "Rammen er utenfor kartet.",
    "box.too_big": (
        "Den er {km} km bred, mer enn en telefon bør lagre. Zoom inn så jaktfeltet er under {limit}"
        " km bredt."
    ),
    "box.too_small": "Den er for liten til å være jaktfeltet. Zoom litt ut.",
    "terrain.busy": "Høydetjenesten er opptatt. Prøv igjen om noen minutter.",
    "terrain.down": "Høydetjenesten svarte ikke. Prøv igjen senere.",

    # ---- signing in, too many tries ------------------------------------------
    "count.minutes": {
        "one": "{n} minutt",
        "other": "{n} minutter",
    },
    "throttle.place": "For mange feil passord herfra. Prøv igjen om {wait}.",
    "throttle.at_once": "For mange innlogginger herfra samtidig. Prøv igjen om noen sekunder.",
    "throttle.checking": "Det forrige forsøket ditt sjekkes fortsatt. Prøv igjen om noen sekunder.",
    "throttle.email": {
        "one": "For mange feil passord for denne e-postadressen. Prøv igjen om {n} sekund.",
        "other": "For mange feil passord for denne e-postadressen. Prøv igjen om {n} sekunder.",
    },
    "throttle.email_lately": (
        "For mange feil passord for denne e-postadressen i det siste. Prøv igjen om {wait}, eller "
        "fra en telefon som har logget inn med den før."
    ),

    # ---- the stag/hind labelling pass (kept in English, said in the reader's language) ----
    "sexpass.key_refused": (
        "Anthropic avviste API-nøkkelen. Sjekk ANTHROPIC_API_KEY i serverens .env."
    ),
    "sexpass.no_credit": (
        "Anthropic-kontoen er tom for kreditt. Fyll på for å merke bukker og koller igjen."
    ),
    "sexpass.no_model": (
        "Anthropic kjenner ikke modellen {model}. Be den som drifter serveren om å oppdatere den."
    ),
    "sexpass.limited": "Anthropic begrenser forespørsler akkurat nå. Nytt forsøk neste time.",
    "sexpass.unreachable": "Fikk ikke kontakt med Anthropic. Nytt forsøk neste time.",
    "sexpass.http": "Anthropic hadde et problem (HTTP {status}). Nytt forsøk neste time.",
    "sexpass.bad_answer": "Anthropic svarte ikke ordentlig. Nytt forsøk neste time.",

    # ---- Look for repeats (kept in English, said in the reader's language) ----
    "reid.failed": "Noe gikk galt ({error}).",
    "reid.stopped": (
        "Det stoppet halvveis: serveren var opptatt for lenge. Trykk igjen for å fullføre."
    ),

    # ---- the moon ------------------------------------------------------------
    "moon.new_moon": "Nymåne",
    "moon.waxing_crescent": "Voksende månesigd",
    "moon.first_quarter": "Første kvarter",
    "moon.waxing_gibbous": "Voksende måne",
    "moon.full_moon": "Fullmåne",
    "moon.waning_gibbous": "Minkende måne",
    "moon.last_quarter": "Siste kvarter",
    "moon.waning_crescent": "Minkende månesigd",
}
