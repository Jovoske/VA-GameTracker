"""Swedish (svenska): what the server says. The same keys and placeholders as en.py
(tests/test_i18n.py); a key missing here would be said in English.

Swedish hunters' words: vildsvin, kronhjort, rådjur, dovhjort, åtel, pass,
torn.
"""

MESSAGES: dict[str, str | dict[str, str]] = {
    # ---- lists and the calendar ----------------------------------------------
    "list.two": "{a} och {b}",
    "list.three": "{a}, {b} och {c}",
    "list.more": "{a}, {b} och {n} till",
    "cal.wd.0": "mån",
    "cal.wd.1": "tis",
    "cal.wd.2": "ons",
    "cal.wd.3": "tors",
    "cal.wd.4": "fre",
    "cal.wd.5": "lör",
    "cal.wd.6": "sön",
    "cal.wdl.0": "måndag",
    "cal.wdl.1": "tisdag",
    "cal.wdl.2": "onsdag",
    "cal.wdl.3": "torsdag",
    "cal.wdl.4": "fredag",
    "cal.wdl.5": "lördag",
    "cal.wdl.6": "söndag",
    "cal.mon.1": "jan",
    "cal.mon.2": "feb",
    "cal.mon.3": "mars",
    "cal.mon.4": "apr",
    "cal.mon.5": "maj",
    "cal.mon.6": "juni",
    "cal.mon.7": "juli",
    "cal.mon.8": "aug",
    "cal.mon.9": "sep",
    "cal.mon.10": "okt",
    "cal.mon.11": "nov",
    "cal.mon.12": "dec",
    "cal.monl.1": "januari",
    "cal.monl.2": "februari",
    "cal.monl.3": "mars",
    "cal.monl.4": "april",
    "cal.monl.5": "maj",
    "cal.monl.6": "juni",
    "cal.monl.7": "juli",
    "cal.monl.8": "augusti",
    "cal.monl.9": "september",
    "cal.monl.10": "oktober",
    "cal.monl.11": "november",
    "cal.monl.12": "december",
    "cal.day_month": "{day} {month}",
    "cal.wd_day_month": "{wd} {day} {month}",

    # ---- species and what an animal is ---------------------------------------
    "species.bison": "Bison",
    "species.badger": "Grävling",
    "species.ibex": "Stenbock",
    "species.beaver": "Bäver",
    "species.red_deer": "Kronhjort",
    "species.chamois": "Gems",
    "species.cat": "Katt",
    "species.goat": "Get",
    "species.roe_deer": "Rådjur",
    "species.dog": "Hund",
    "species.fallow_deer": "Dovhjort",
    "species.squirrel": "Ekorre",
    "species.moose": "Älg",
    "species.equid": "Häst eller åsna",
    "species.genet": "Genett",
    "species.wolverine": "Järv",
    "species.hedgehog": "Igelkott",
    "species.lagomorph": "Hare eller kanin",
    "species.wolf": "Varg",
    "species.otter": "Utter",
    "species.lynx": "Lodjur",
    "species.marmot": "Murmeldjur",
    "species.micromammal": "Mus eller råtta",
    "species.mouflon": "Mufflon",
    "species.sheep": "Får",
    "species.mustelid": "Mård eller vessla",
    "species.bird": "Fågel",
    "species.bear": "Björn",
    "species.nutria": "Sumpbäver",
    "species.raccoon": "Tvättbjörn",
    "species.fox": "Räv",
    "species.reindeer": "Ren",
    "species.wild_boar": "Vildsvin",
    "species.cow": "Nötkreatur",
    "class.stag": "Hjort",
    "class.hind": "Hind",
    "class.hind_calf": "Hind + kalv",
    "class.boar": "Galt",
    "class.sow": "Sugga",
    "class.sow_piglets": "Sugga + kultingar",
    "class.sounder": "Rotte",
    "class.herd": "{name} (flock)",
    "class.animal": "Djur",
    "class.animals": "Djur",

    # ---- signing in ----------------------------------------------------------
    "auth.not_authenticated": "Du är inte inloggad",
    "auth.bad_credentials": "Ogiltiga inloggningsuppgifter",
    "auth.token_invalid": "Ogiltig eller utgången inloggning",
    "auth.token_subject": "Ogiltig inloggningsidentitet",
    "auth.user_not_found": "Användaren finns inte",
    "auth.signed_out": "Du har loggats ut. Logga in igen.",
    "auth.admin_only": "Bara jaktmarkens admin kan göra det.",
    "auth.busy": "Servern är upptagen. Försök igen om en minut.",
    "auth.wrong_password": "Fel e-post eller lösenord",
    "auth.published": (
        "Det är lösenordet som publicerats med GameSense, så det kan inte logga in från internet. "
        "Logga in från serverns eget nätverk och byt det under Inställningar, eller kör på servern:"
        " python -m app.manage set-password {email}"
    ),
    "auth.language_unknown": "Välj English, Suomi, Svenska, Norsk eller Español.",
    "auth.not_current_password": "Det är inte ditt nuvarande lösenord",
    "auth.new_password_short": "Det nya lösenordet måste ha minst 8 tecken",
    "auth.password_changed": (
        "Lösenordet är bytt. Alla andra telefoner som är inloggade som du måste logga in igen."
    ),

    # ---- people on the app ---------------------------------------------------
    "users.email_invalid": "Ange en giltig e-postadress",
    "users.password_short": "Lösenordet måste ha minst 8 tecken",
    "users.pick_role": "Välj Medlem eller Admin",
    "users.email_taken": "Någon med den e-postadressen har redan en inloggning",
    "users.gone": "Den personen finns inte längre i appen.",
    "users.not_yourself": "Du kan inte ta bort dig själv",
    "users.keep_admin": "Behåll minst en admin",
    "users.remove_failed": (
        "Kunde inte ta bort {email}: något i appen pekar fortfarande på personen. Inget har "
        "ändrats. Försök igen eller fråga den som sköter servern."
    ),
    "users.removed": "{email} kan inte logga in längre. Det personen registrerat finns kvar.",
    "users.logins_moved": {
        "one": (
            "{n} kamerainloggning som personen lade till hämtar fortfarande bilder, nu i ditt namn."
        ),
        "other": (
            "{n} kamerainloggningar som personen lade till hämtar fortfarande bilder, nu i ditt "
            "namn."
        ),
    },

    # ---- Tonight -------------------------------------------------------------
    "time.hours": "{h} h",
    "time.clock": "kl. {h}",
    "time.minutes": "{m} min",
    "sun.at_sunset": "solnedgången",
    "sun.after": "{span} efter solnedgången",
    "sun.before": "{span} före solnedgången",
    "tonight.factor.not_sending": {
        "one": "Kameran skickar inga bilder just nu. Bedömningen bygger på {n} natts historik.",
        "other": "Kameran skickar inga bilder just nu. Bedömningen bygger på {n} nätters historik.",
    },
    "tonight.factor.unchecked": (
        "Bilder från {n} av de senaste 7 nätterna granskas fortfarande. Bedömningen bygger på "
        "historiken."
    ),
    "tonight.factor.few_watched": (
        "Bara {n} av de senaste 7 nätterna bevakade här. Bedömningen bygger på historiken."
    ),
    "tonight.factor.not_watched": " ({n} obevakade)",
    "tonight.factor.seen_week": "{species}: {n} av de senaste 7 nätterna här{gap}",
    "tonight.factor.none_week": "Inga spår av {species} här de senaste 7 nätterna{gap}",
    "tonight.factor.outside_hours": (
        "{species}: bara observationer här utanför de timmar man kan sitta på pass, så det finns "
        "inga bästa timmar att ge"
    ),
    "tonight.best_hours": "Bästa timmarna {start}–{end}",
    "tonight.best_hours_from": "Bästa timmarna {start}–{end}, från {relative}",
    "tonight.left_out.unchecked_n": "{n} med bilder som inte granskats än",
    "tonight.left_out.unchecked": "bilderna har inte granskats än",
    "tonight.left_out.blind_n": "{n} då kameran kanske inte bevakade",
    "tonight.left_out.blind": "kameran kanske inte bevakade",
    "tonight.left_out": {
        "one": "{n} natt vid {camera} utelämnad: {why}.",
        "other": "{n} nätter vid {camera} utelämnade: {why}.",
    },
    "tonight.alert.silent": (
        "Inga bilder på {n} dagar, så den är utelämnad från kvällens rangordning"
    ),
    "tonight.none.picked": "Ingen kamera har sett de djur du valt än.",
    "tonight.none.sending": "Kamerorna som skickar bilder har inte sett några djur än.",
    "tonight.none.yet": "Inga observationer än.",
    "tonight.reason": "{species}: {n} av {total} nätter vid den här kameran.",
    "tonight.caveat": (
        "Kameran bevakar hela natten. Du sitter där några timmar, så välj de bästa timmarna och "
        "tänk på vinden."
    ),

    # ---- wind ----------------------------------------------------------------
    "compass.N": "N",
    "compass.NE": "NO",
    "compass.E": "O",
    "compass.SE": "SO",
    "compass.S": "S",
    "compass.SW": "SV",
    "compass.W": "V",
    "compass.NW": "NV",
    "wind.reading": "Vind {dir} {speed} km/h",
    "wind.no_forecast": "Ingen vindprognos i kväll. Kontrollera själv.",
    "wind.no_forecast_stand": (
        "Ingen vindprognos i kväll. Kontrollera själv innan du sätter dig på {stand}."
    ),
    "wind.no_position": (
        "{reading}. {stand} finns inte på kartan än, så det går inte att räkna ut vart vittringen "
        "tar vägen."
    ),
    "wind.no_bedding": (
        "{reading}. Inga liggplatser är ritade än, så det går inte att räkna ut vart vittringen "
        "hamnar. Rita in var djuren ligger på kartan."
    ),
    "wind.no_stand": (
        "{reading}. Inget pass nära {camera} än, så vinden kan inte bedömas för en plats. Bedöm den"
        " själv."
    ),
    "wind.arcs.too_light": (
        "Vind {dir} {speed} km/h, för svag för att bedöma. Termiken avgör. Kolla vid bilen."
    ),
    "wind.arcs.no_geometry": (
        "Vind {dir} {speed} km/h. {stand} har inga inkommande riktningar angivna, så bedöm vinden "
        "själv."
    ),
    "wind.arcs.divert": " Ta {stand} i stället.",
    "wind.arcs.wrong": (
        "Vind {dir} {speed} km/h, fel för {stand}. Din vittring blåser rakt mot växeln från "
        "{approach}.{divert}"
    ),
    "wind.arcs.clean": (
        "Vind {dir} {speed} km/h, bra för {stand}. Din vittring går mot {scent}, bort från där de "
        "kommer in."
    ),

    # ---- slope wind and bedding ----------------------------------------------
    "thermal.no_terrain": "Ingen terrängmodell inläst, så sluttningsvinden kan inte räknas ut.",
    "thermal.off_terrain": (
        "Platsen ligger utanför den inlästa terrängmodellen, så sluttningsvinden kan inte räknas "
        "ut. En admin kan läsa in terrängen igen så att den täcker platsen."
    ),
    "thermal.flat": "Marken är nästan platt här. Ingen sluttning för kall luft att rinna ner för.",
    "thermal.overcast": (
        "Mulet ({pct} %), så sluttningsvinden blir svag i kväll. Kontrollera själv."
    ),
    "thermal.katabatic": (
        "Prognosen är vindstilla, så sluttningen avgör. Kall luft rinner nedför mot {dir} i cirka "
        "{speed} km/h. Din vittring följer med."
    ),
    "thermal.katabatic_settling": (
        "Prognosen är vindstilla, så sluttningen avgör. Kall luft rinner nedför mot {dir} i cirka "
        "{speed} km/h. Den sätter sig fortfarande i skymningen och kan vrida. Din vittring följer "
        "med."
    ),
    "thermal.anabatic": (
        "Stilla och soligt, så luften stiger uppför sluttningen mot {dir}. Den vänder och rinner "
        "nedför igen runt solnedgången."
    ),
    "bedding.no_position": "{stand} har ingen position på kartan än.",
    "bedding.none": "Inga liggplatser ritade än — rita var djuren ligger så blir det här ett råd.",
    "bedding.too_light": "Vind {dir} {speed} km/h — för svag för att bedöma. {why}",
    "bedding.thermals_decide": "Termiken avgör den här; läs av den vid bilen.",
    "bedding.lead.katabatic": (
        "Vindstilla prognos, så sluttningen avgör — kall luft rinner mot {dir} i ~{speed} "
        "km/h{fall}"
    ),
    "bedding.fall": " ({pct} % lutning)",
    "bedding.lead.anabatic": "Stilla och soligt — luften dras uppför mot {dir} i ~{speed} km/h",
    "bedding.caveat.dusk": " Den vänder runt skymningen, så kontrollera på plats.",
    "bedding.caveat.dem": " En terrängmodell på ~90 m ser sluttningen, inte din ravin.",
    "bedding.into_own": "in i {zone}, liggplatsen som ditt pass ligger i",
    "bedding.into_near": "in i {zone} {m} m bort",
    "bedding.into_far": "in i {zone}, {m} m bort",
    "bedding.carries.thermal": "{lead}, och bär din vittring {where}.{caveat}",
    "bedding.carries.wind": "{lead} — din vittring går mot {dir} {where}.",
    "bedding.clean.thermal": "{lead}, bort från liggplatserna ({m} m till närmaste).{caveat}",
    "bedding.clean.wind": (
        "{lead} — rent. Vittringen går mot {dir}, bort från liggplatserna ({m} m till närmaste)."
    ),
    "bedding.draw": "Rita liggplatser för att se det här.",
    "bedding.no_forecast": "Ingen vindprognos i kväll.",
    "bedding.too_light_map": (
        "Vinden är för svag för att kartlägga — en sådan kväll avgör termiken."
    ),
    "bedding.safe.note": (
        "Bara geometri — den vet inget om skydd, tillträde eller säker kulfång. Den smalnar av var "
        "du ska leta; den väljer inte platsen."
    ),
    "bedding.safe.note_calm": (
        "Prognosen är vindstilla, så det här följer marken: varje ruta använder sin egen fallinje, "
        "eftersom kall luft rinner nedför efter mörkret. En terrängmodell på ~90 m ser sluttningen,"
        " inte ravinen du sitter i."
    ),

    # ---- what changed --------------------------------------------------------
    "num.decimal_mark": ",",
    "count.visits": {
        "one": "{n} besök",
        "other": "{n} besök",
    },
    "changed.about": "cirka {x}",
    "changed.no_cameras": "Inga kameror är tillagda än.",
    "changed.camera_down": "{camera} skickade ingenting i natt. Okänt om något passerade.",
    "changed.return": {
        "one": "Djur tillbaka vid {camera} efter {n} lugn natt.",
        "other": "Djur tillbaka vid {camera} efter {n} lugna nätter.",
    },
    "changed.gone_quiet": {
        "one": "{camera} har varit tyst i {n} natt. Där brukar det vara {usual} besök per natt.",
        "other": (
            "{camera} har varit tyst i {n} nätter. Där brukar det vara {usual} besök per natt."
        ),
    },
    "changed.busier": (
        "Mer rörelse än vanligt vid {camera} i natt: {visits} mot vanligtvis {usual}."
    ),
    "changed.quieter": "Lugnare än vanligt vid {camera} i natt: {visits} mot vanligtvis {usual}.",
    "changed.some_cameras": "några kameror",
    "changed.checking": "Nattens bilder från {cameras} granskas fortfarande.",
    "changed.none": "Inget har ändrats. Ungefär som de senaste nätterna.",

    # ---- camera health -------------------------------------------------------
    "health.retired": "Tagen ur bruk {day}. Utelämnad från kvällens plan och siffrorna",
    "health.disconnected": "Inte ansluten: ingen kamerainloggning här hämtar den nu",
    "health.not_syncing": "Bilderna kommer inte in. Kamerainloggningen behöver åtgärdas.",
    "health.not_fetched": (
        "Bilderna kommer inte in. Ingen bildhämtning har lyckats på över 2 timmar."
    ),
    "health.fetch_error": "Bilderna kommer inte in. {error}",
    "health.no_photos_since": "Inga bilder sedan {day}",
    "health.no_photos": "Inga bilder än",
    "health.photos_only": "Skickar bara bilder, inga statusrapporter",
    "health.clock_fast": (
        ". Klockan går {h} h före (missat tidsomställningen?): bildtiderna rättas, men ställ "
        "kamerans klocka"
    ),
    "health.no_checkin_for": "Ingen kontakt på {h} h",
    "health.no_checkin": "Ingen kontakt än",
    "health.photo_limit": "Bildgränsen nådd ({count}/{limit})",
    "health.battery_low": "Lågt batteri ({pct} %)",
    "health.ok": "Rapporterar som vanligt",

    # ---- camera logins (kept in English, said in the reader's language) ------
    "login.unreadable": "Det sparade lösenordet kan inte läsas. Ange det igen.",
    "login.spypoint_refused": "SPYPOINT godtog inte lösenordet. Ange det igen.",
    "login.ubox_refused": "UBox godtog inte lösenordet. Ange det igen.",
    "login.ubox_signed_out": "UBox loggade ut den här inloggningen. Ange lösenordet igen.",
    "login.spypoint_throttled": (
        "SPYPOINT avvisar förfrågningar just nu. Nästa hämtning försöker igen."
    ),
    "login.spypoint_down": "SPYPOINT svarar inte ordentligt just nu. Nästa hämtning försöker igen.",
    "login.spypoint_refused_request": "SPYPOINT avvisade förfrågan. Nästa hämtning försöker igen.",
    "login.spypoint_unreadable": (
        "SPYPOINT skickade något appen inte kan läsa. Nästa hämtning försöker igen."
    ),
    "login.ubox_unknown": (
        "UBox känner inte till den här inloggningen. Kontrollera e-postadressen i appen UBox Pro."
    ),
    "login.unreachable": "Kunde inte nå {provider}. Nästa hämtning försöker igen.",
    "login.ubox_down": "UBox svarar inte ordentligt just nu. Nästa hämtning försöker igen.",
    "login.other": "{text}. Nästa hämtning försöker igen.",
    "login.failed": (
        "Hämtningen från {provider} misslyckades ({error}). Nästa hämtning försöker igen."
    ),
    "login.primary_label": "Huvudinloggning för SPYPOINT",

    # ---- photo fetches (kept in English, said in the reader's language) ------
    "login.copy_of_primary": (
        "Det här är jaktmarkens huvudinloggning för SPYPOINT, som redan hämtas. Ta bort den här "
        "kopian."
    ),
    "sync.some_failed": "{n} av {total} kameror misslyckades. {error}",
    "ubox.snap.retry": {
        "one": "{n} bild gick inte att ladda ner. Nästa hämtning försöker igen.",
        "other": "{n} bilder gick inte att ladda ner. Nästa hämtning försöker igen.",
    },
    "ubox.snap.dropped": {
        "one": (
            "{n} bild gick inte att ladda ner. Den försöktes {tries} gånger och utelämnas därför."
        ),
        "other": (
            "{n} bilder gick inte att ladda ner. De försöktes {tries} gånger och utelämnas därför."
        ),
    },
    "ubox.snap.some": {
        "one": (
            "{failed} bilder gick inte att ladda ner. {n} försöks igen vid nästa hämtning; resten "
            "försöktes {tries} gånger och utelämnas."
        ),
        "other": (
            "{failed} bilder gick inte att ladda ner. {n} försöks igen vid nästa hämtning; resten "
            "försöktes {tries} gånger och utelämnas."
        ),
    },

    # ---- UBox errors (kept in English, said in the reader's language) --------
    "ubox.err.host_unresolved": "UBox bildserverns namn kunde inte slås upp",
    "ubox.err.host_public": "UBox bildadress måste använda en publik HTTPS-server",
    "ubox.err.bad_json": "UBox svarade med ogiltig JSON",
    "ubox.err.unexpected": "UBox gav ett oväntat svar",
    "ubox.err.rejected_password": "UBox avvisade kontot eller lösenordet",
    "ubox.err.rejected_request": "UBox avvisade förfrågan; kontrollera kontot i UBox Pro",
    "ubox.err.no_data": "UBox svar saknar dataobjekt",
    "ubox.err.need_login": "E-post och lösenord för UBox krävs",
    "ubox.err.unreachable_login": "Kunde inte nå UBox för inloggning",
    "ubox.err.no_token": "UBox inloggningssvar saknar sessionstoken",
    "ubox.err.unreachable": "Kunde inte nå UBox",
    "ubox.err.auth_expired": "UBox inloggning gick ut efter nytt försök; anslut kontot igen",
    "ubox.err.auth_failed": "UBox autentisering misslyckades",
    "ubox.err.no_devices": "UBox enhetssvar saknar uppgifter",
    "ubox.err.device_no_id": "UBox returnerade en enhet utan identitet",
    "ubox.err.naive_dates": "UBox händelsesökning kräver datum med tidszon",
    "ubox.err.bad_range": "UBox händelsesökning har ogiltigt intervall eller sidstorlek",
    "ubox.err.no_events": "UBox händelsesvar saknar lista",
    "ubox.err.incomplete_page": (
        "UBox gav en ofullständig händelsesida; hämtningen försöker igen senare"
    ),
    "ubox.err.bad_event": "UBox returnerade en ogiltig händelse",
    "ubox.err.repeated_page": "UBox upprepade en händelsesida; hämtningen försöker igen senare",
    "ubox.err.bad_event_fields": "UBox händelse har ogiltig tidsstämpel eller kameraidentitet",
    "ubox.err.fewer_events": "UBox gav färre händelser än utlovat; hämtningen försöker igen",
    "ubox.err.page_limit": "UBox gräns för händelsesidor nådd; använd en kortare period",
    "ubox.err.https_only": "UBox bildadress måste använda HTTPS",
    "ubox.err.too_big": "UBox bild överskrider nedladdningsgränsen på 20 MB",
    "ubox.err.empty_image": "UBox returnerade en tom bild",
    "ubox.err.download_failed": "Kunde inte ladda ner UBox-bilden",
    "ubox.err.unknown_account": (
        "UBox kände inte igen kontot. Kontrollera rätt kameraapp och e-postadressen den är inloggad"
        " med."
    ),
    "ubox.err.login_http": "UBox-inloggningen misslyckades (HTTP {status})",
    "ubox.err.request_http": "UBox-förfrågan misslyckades (HTTP {status})",
    "ubox.err.download_http": "Nedladdningen av UBox-bilden misslyckades (HTTP {status})",
    "ubox.err.other_estate": "Den här UBox-kameran är redan kopplad till en annan jaktmark",
    "ubox.err.snapshot_size": "Bilden är tom eller större än 20 MB",
    "ubox.err.snapshot_pixels": "Bilden måste vara en JPEG på högst 40 megapixel",
    "ubox.err.snapshot_unreadable": "Bilden är inte en läsbar JPEG",
    "ubox.err.snapshot_failed": "Kunde inte ladda ner en läsbar bild",
    "ubox.err.no_estate": "Kontot saknar jaktmark",
    "fetch.disk_label": "Serverns disk",
    "fetch.failed": "Hämtningen misslyckades. Nästa hämtning försöker igen.",
    "fetch.disk_full": (
        "Nästan full ({gb} GB ledigt). Bilderna väntar i kamerorna och kommer in när det finns "
        "plats."
    ),
    "fetch.provider_failed": (
        "Hämtningen från {provider} misslyckades ({error}). Nästa hämtning försöker igen."
    ),
    "fetch.ai_failed": "Djursökningen misslyckades ({error})",

    # ---- the AI pass (kept in English, said in the reader's language) --------
    "ai.detector_failed": "Djurdetektorn kunde inte starta ({error}).",
    "ai.classifier_failed": "Artmodellen kunde inte starta ({error}).",
    "ai.models_broken": "Modellerna slutade fungera ({error}).",
    "ai.stopped_streak": (
        "{why} Granskningen stoppades efter att {n} bilder i rad misslyckats; de räknades inte mot "
        "bilderna."
    ),

    # ---- photos --------------------------------------------------------------
    "photos.not_checked": "Inte granskad än",
    "photos.could_not_check": "Kunde inte granskas",
    "photos.people_admin_only": "Bara en admin ser bilder med människor eller fordon.",
    "photos.gone": "Den bilden finns inte längre.",
    "people.person_vehicle": "Människa och fordon",
    "people.person": "Människa",
    "people.vehicle": "Fordon",
    "people.person_or_vehicle": "Människa eller fordon",

    # ---- cameras and the Check button ----------------------------------------
    "busy.reid": "letar efter återkommande besökare",
    "busy.plan": "skriver kvällens plan",
    "busy.score": "jämför gårdagens plan med kamerorna",
    "busy.scan": "letar efter djur i bilderna",
    "busy.deploy": "installerar en uppdatering",
    "busy.other": "håller på med ett annat jobb",
    "busy.fetch": "hämtar bilder",
    "busy.try_later": "Servern {what}. Försök igen om några minuter.",
    "cameras.start_failed": "Det gick inte att starta på servern. Försök igen om en minut.",
    "cameras.name_hidden_chars": "Kameranamnet innehåller dolda tecken. Skriv det igen.",
    "cameras.name_length": "Kameranamnet måste vara 1 till 100 tecken.",
    "cameras.rename_forbidden": "Bara jaktmarkens admins och medlemmar kan byta namn på kameror.",
    "cameras.not_found": "Kameran hittades inte.",
    "cameras.name_taken": "En annan kamera heter redan {name}. Välj ett annat namn.",
    "cameras.name_taken_reset": (
        "En annan kamera heter redan {name}, så den här behåller sitt eget namn."
    ),
    "cameras.check_viewer": "Nya bilder kommer in av sig själva var 15:e minut.",
    "cameras.check_running": "Kontrollerar redan. Nya bilder syns strax.",
    "cameras.check_asked": "Redan begärt. Nya bilder kommer så snart servern är ledig.",
    "cameras.check_queued": "Servern {what}. Nya bilder kommer när den är klar.",
    "cameras.off_map": "Den platsen ligger utanför kartan. Flytta kartan och försök igen.",
    "cameras.no_own_position": (
        "Den här kameran har inte rapporterat någon egen position. Placera den för hand."
    ),

    # ---- camera logins in Settings -------------------------------------------
    "accounts.viewer": "Läsare kan se kamerainloggningarna men inte lägga till några.",
    "accounts.enter_login": "Ange din e-post och ditt lösenord för {provider}",
    "accounts.no_estate": "Gå med i en jaktmark innan du lägger till en kamerainloggning",
    "accounts.is_primary": "Den här inloggningen är redan ansluten som jaktmarkens huvudkonto",
    "accounts.already_added": "Den inloggningen för {provider} är redan tillagd",
    "accounts.already_added_refresh": (
        "Den inloggningen för {provider} är redan tillagd. Uppdatera för att se den."
    ),
    "accounts.connected_now": {
        "one": "Ansluten — {provider} rapporterar {n} kamera. Hämtar bilder nu.",
        "other": "Ansluten — {provider} rapporterar {n} kameror. Hämtar bilder nu.",
    },
    "accounts.connected_later": {
        "one": "Ansluten — {provider} rapporterar {n} kamera. Bilderna kommer vid nästa hämtning.",
        "other": (
            "Ansluten — {provider} rapporterar {n} kameror. Bilderna kommer vid nästa hämtning."
        ),
    },
    "accounts.unreachable": (
        "Kunde inte nå {provider} för att kontrollera lösenordet. Försök igen om några minuter."
    ),
    "accounts.ubox_failed": "Kunde inte ansluta till UBox Pro: {error}",
    "accounts.spypoint_refused": (
        "SPYPOINT godtog inte e-posten och lösenordet. Kontrollera dem i SPYPOINT-appen."
    ),
    "accounts.spypoint_failed": "SPYPOINT godtog inte inloggningen: {error}",
    "accounts.not_found": "Kontot hittades inte",
    "accounts.password_forbidden": (
        "Bara den som lade till inloggningen, eller en admin, kan byta dess lösenord"
    ),
    "accounts.enter_password": "Ange lösenordet",
    "accounts.password_saved": (
        "Lösenordet är sparat. Bilderna kommer vid nästa hämtning, inom 15 minuter."
    ),
    "accounts.limits_forbidden": (
        "Bara den som lade till inloggningen, eller en admin, kan ändra dess gränser"
    ),
    "accounts.limits_ubox_only": "Bildgränser gäller bara inloggningar för UBox Pro",
    "accounts.limits_saved": "Gränserna är sparade. De gäller från nästa hämtning.",
    "accounts.remove_forbidden": (
        "Bara den som lade till inloggningen, eller en admin, kan ta bort den"
    ),

    # ---- alerts on the phone -------------------------------------------------
    "push.just_now": "nyss",
    "push.time": "kl. {time}",
    "push.last_night": "i natt kl. {time}",
    "push.yesterday": "i går kl. {time}",
    "push.on_day": "{day} kl. {time}",
    "push.at_camera": "{name} vid {camera}",
    "push.on_cameras": {
        "one": "{name} på {n} kamera",
        "other": "{name} på {n} kameror",
    },
    "push.one_visit": "1 besök {when}.",
    "push.visits_last": "{visits}, senast {when}.",
    "push.visits_at_last": "{visits} vid {cameras}, senast {when}.",
    "push.at_cameras": " vid {cameras}",
    "push.update": "{visits}{where} sedan {since}, senast {last}.",
    "push.summary_title": "{n} nya observationer, {animals} djur",
    "push.summary_body": "{names}, senast {when}.",
    "verdict.best_odds": "Bäst chans",
    "verdict.worth_a_look": "Värt en titt",
    "verdict.quiet": "Lugnt",
    "verdict.no_data": "För lite att gå på",
    "plan.wind.clean": "rätt vind",
    "plan.wind.wrong": "fel vind",
    "plan.wind.too_light": "för svag vind för att bedöma",
    "plan.wind.no_forecast": "ingen vindprognos",
    "plan.tonight": "{verdict} i kväll",
    "plan.sunset": "solnedgång {time}",
    "plan.no_camera": (
        "För få bevakade nätter för att bedöma kvällen. Öppna appen för att se vad kamerorna sett."
    ),
    "plan.species_hours": "{species}, bäst {start}–{end}.",
    "held.one": "{name}: {visits} vid {cameras}",
    "held.each": "{name}: {visits}",
    "held.worth_a_look": {
        "one": "{n} bild markerad Värt en titt",
        "other": "{n} bilder markerade Värt en titt",
    },
    "held.title.sit": "Medan du satt på pass",
    "held.title.quiet": "Under dina tysta timmar",
    "held.body": "{parts}, senast {when}.",

    # ---- alert settings ------------------------------------------------------
    "alerts.unknown_camera": "Okänd kamera: {ids}",
    "alerts.unknown_species": "Okänd art: {ids}",
    "alerts.quiet_needs_both": "Tysta timmar behöver en början och ett slut.",
    "alerts.quiet_same": "Tysta timmar kan inte börja och sluta samtidigt.",
    "alerts.endpoint_https": "Push-adressen måste vara en https-adress",
    "alerts.no_phone": (
        "Ingen telefon får aviseringar än. Slå på aviseringar från den telefonen först."
    ),
    "alerts.test_title": "Testavisering",
    "alerts.test_body": "Aviseringarna fungerar på den här telefonen.",

    # ---- team notes and people -----------------------------------------------
    "notes.bad_chars": "Anteckningen innehåller tecken som inte kan sparas. Skriv den igen.",
    "notes.too_long": "Håll anteckningen till {n} tecken.",
    "notes.push_title": "Värt en titt: {label} vid {camera}",
    "notes.push_body": "{name}: {text}",
    "notes.push_marked": "{name} markerade en bild",
    "notes.empty_frame": "Den här bilden är markerad ”inget i den”. Behåll den som djurbild först.",
    "notes.hidden_only": "Bara djur som är dolda i appen finns i bilden, så laget kan inte se den.",
    "notes.people_only": (
        "Det finns en människa eller ett fordon i bilden, så den stannar hos admins och laget kan "
        "inte se den."
    ),
    "notes.not_looked": (
        "Appen har inte granskat den här bilden än, så laget kan inte se den. Försök igen om några "
        "minuter."
    ),
    "notes.photo_not_found": "Bilden hittades inte.",
    "notes.viewer": "Läsare kan se anteckningar men inte lägga till några.",
    "notes.not_saved": "Anteckningen kunde inte sparas. Stäng den och försök igen.",
    "notes.gone": "Anteckningen är redan borta.",
    "notes.remove_forbidden": "Bara den som skrev den, eller en admin, kan ta bort en anteckning.",
    "people.hunter": "Jägare",
    "people.removed": "Borttagen person",
    "crash.too_large": "Rapporten är för stor",
    "crash.not_a_report": "Det där är ingen kraschrapport.",
    "crash.too_many": "För många rapporter. Senare rapporter kastas.",
    "crash.unknown_device": "Okänd enhet",

    # ---- stands and sits -----------------------------------------------------
    "stands.no_estate": "Lägg upp jaktmarken först.",
    "stands.auto_name": "Pass {camera}",
    "stands.auto_note": (
        "Varje pass är placerat vid sin kamera. Flytta det dit du faktiskt sitter. Vindråden börjar"
        " när du anger riktningarna djuren kommer ifrån."
    ),
    "stands.camera_gone": "Den kameran finns inte i appen.",
    "stands.gone": "Det passet finns inte i appen.",
    "stands.has_sits": {
        "one": (
            "{n} passning är registrerad vid det här passet. Att radera det skulle sudda ut "
            "historiken. Byt namn på det i stället."
        ),
        "other": (
            "{n} passningar är registrerade vid det här passet. Att radera det skulle sudda ut "
            "historiken. Byt namn på det i stället."
        ),
    },
    "stands.claimed": "{stand} är redan bokat i kväll av en annan jägare.",
    "stands.arc_conflict": (
        "{stand} och {other} har ett gemensamt skjutfält, och {other} är bokat i kväll. Välj ett "
        "annat pass."
    ),
    "stands.viewer": "Läsare kan se passen men inte boka något.",
    "sits.gone": "Den passningen finns inte i appen.",
    "sits.viewer": "Läsare kan se passningarna men inte ändra dem.",
    "sits.not_yours": "Den passningen är en annan jägares.",
    "sits.bad_outcome": "utfallet måste vara ett av {outcomes}",
    "sits.cancelled": "Den bokningen avbokades. Boka passet igen.",
    "sits.already_reported": "Du har redan sagt vad som hände på den här passningen.",
    "sits.not_started": "Den passningen har inte börjat.",

    # ---- approach lines and the dark exit ------------------------------------
    "arcs.no_camera": "Det här passet är inte kopplat till någon kamera.",
    "arcs.camera_unplaced": "Den kopplade kameran har ingen registrerad position.",
    "arcs.no_others": "Inga andra placerade kameror att läsa rörelser från.",
    "arcs.note": {
        "one": (
            "{n} gång kom djuren till {camera} inom {minutes} min efter att de passerat {other}."
        ),
        "other": (
            "{n} gånger kom djuren till {camera} inom {minutes} min efter att de passerat {other}."
        ),
    },
    "arcs.none": (
        "Ingen återkommande rörelse mellan kamerorna än — inte nog för att föreslå en växel, så "
        "appen fortsätter att lämna den här åt dig."
    ),
    "exit.no_visits": "Inga besök vid passets kamera än.",
    "exit.quiet": (
        "Gå ut i mörkret kl. {time} — bara {pct} % av kamerans besök sker timmen efter, så då stör "
        "du minst."
    ),
    "exit.busy_reason": "Ingen riktigt lugn timme — det här passet har rörelse hela natten.",
    "exit.busy": (
        "Ingen lugn timme efter kl. {after} vid det här passet — rörelse hela natten. Kl. {time} är"
        " den minst dåliga tiden att gå ut."
    ),

    # ---- the harvest book ----------------------------------------------------
    "harvest.sex.male": "Hane",
    "harvest.sex.female": "Hona",
    "harvest.sex.unknown": "Osäker",
    "harvest.age.juvenile": "Årsunge",
    "harvest.age.young_adult": "Ungdjur",
    "harvest.age.mature_adult": "Vuxen",
    "harvest.age.old": "Gammal",
    "harvest.age.unknown": "Osäker",
    "harvest.viewer": "Läsare kan inte registrera fällt vilt.",
    "harvest.not_yours": "Det fällda viltet är en annan jägares. En admin kan ändra det.",
    "harvest.not_a_shot": "Den passningen är inte rapporterad som skott. Säg vad som hände först.",
    "harvest.field.seal": "märkningsnummer",
    "harvest.field.note": "anteckning",
    "harvest.field.name": "namn",
    "harvest.hidden_chars": "Fältet ”{what}” innehåller dolda tecken. Skriv det igen.",
    "harvest.too_long": "Fältet ”{what}” får vara högst {n} tecken.",
    "harvest.bad_species": "Välj ett av djuren i listan.",
    "harvest.bad_sex": "Kön är hane, hona eller osäker.",
    "harvest.bad_age": "Välj en ålder i listan.",
    "harvest.future": "Den tiden har inte kommit än. Kontrollera datumet.",
    "harvest.too_old": "Det datumet är för långt tillbaka. Kontrollera året.",
    "harvest.bad_season": "Välj en säsong i listan.",
    "harvest.not_saved": "Det fällda viltet kunde inte sparas. Stäng och försök igen.",
    "harvest.gone": "Det fällda viltet finns inte längre i boken.",
    "harvest.admin_names": "Bara en admin kan ändra namnet på fällt vilt.",
    "harvest.col.date": "Datum",
    "harvest.col.time": "Tid",
    "harvest.col.species": "Art",
    "harvest.col.sex": "Kön",
    "harvest.col.age": "Ålder",
    "harvest.col.seal": "Märkningsnummer",
    "harvest.col.weight": "Vikt (kg)",
    "harvest.col.hunter": "Jägare",
    "harvest.col.stand": "Pass",
    "harvest.col.notes": "Anteckningar",

    # ---- the activity map ----------------------------------------------------
    "activity.part.dusk": "i skymningen",
    "activity.part.night": "mitt i natten",
    "activity.part.dawn": "i gryningen",
    "activity.checking_last": "Nattens bilder granskas fortfarande.",
    "activity.checking": "Bilderna granskas fortfarande.",
    "activity.unreadable_last": "Inte räknat: alla bilder från i natt kunde inte granskas.",
    "activity.unreadable": "Inte räknat: alla bilder kunde inte granskas.",
    "activity.blind_last": "Inte räknat: kameran fungerade kanske inte i natt.",
    "activity.blind": "Inte räknat: kameran fungerade inte de här nätterna.",
    "activity.tail.times": ", kl. {times}",
    "activity.tail.mostly": ", mest kl. {peak}",
    "activity.tail.busiest": ", mest rörelse kl. {peak}",
    "activity.tail.no_set_time": ", ingen fast tid",
    "activity.last_night": "i natt",
    "activity.last_night_so_far": "i natt hittills",
    "activity.one.nothing_all": "Inget på kameran{when} {night}.",
    "activity.one.nothing": "Inga spår av {species}{when} {night}.",
    "activity.one.visits_all": {
        "one": "{n} djurbesök{when} {night}{tail}",
        "other": "{n} djurbesök{when} {night}{tail}",
    },
    "activity.one.visits": {
        "one": "{n} besök av {species}{when} {night}{tail}",
        "other": "{n} besök av {species}{when} {night}{tail}",
    },
    "activity.q.working": " då den fungerade",
    "activity.q.checkable": " som kunde granskas",
    "activity.q.so_far": " som granskats hittills",
    "activity.none_all": {
        "one": "Inga djur{when} under den {n} natten{qualifier}.",
        "other": "Inga djur{when} under de {n} nätterna{qualifier}.",
    },
    "activity.none": {
        "one": "Inga spår av {species}{when} under den {n} natten{qualifier}.",
        "other": "Inga spår av {species}{when} under de {n} nätterna{qualifier}.",
    },
    "activity.some": "{who} under {n} av {total} nätter{qualifier}{tail}",

    # ---- the map -------------------------------------------------------------
    "map.bad_nights": "Antal nätter är 1, 7 eller 30.",
    "map.no_species": "Ingen sådan art.",
    "map.no_replay": "Det finns ingen repris för den natten.",

    # ---- insights: what moves the animals ------------------------------------
    "class.animals_all": "Alla djur",
    "patterns.moon_illum.label": "Månljus",
    "patterns.moon_illum.high": "ljus måne",
    "patterns.moon_illum.low": "mörk måne",
    "patterns.pressure.label": "Lufttryck",
    "patterns.pressure.high": "högtryck",
    "patterns.pressure.low": "lågtryck",
    "patterns.pressure_trend.label": "Trycktrend",
    "patterns.pressure_trend.high": "stigande tryck",
    "patterns.pressure_trend.low": "fallande tryck",
    "patterns.temp.label": "Temperatur",
    "patterns.temp.high": "varmt väder",
    "patterns.temp.low": "svalt väder",
    "patterns.wind.label": "Vind",
    "patterns.wind.high": "blåst",
    "patterns.wind.low": "stilla luft",
    "patterns.rain.label": "Regn",
    "patterns.rain.high": "regn",
    "patterns.rain.low": "uppehåll",
    "patterns.cloud.label": "Molnighet",
    "patterns.cloud.high": "moln",
    "patterns.cloud.low": "klar himmel",
    "patterns.darkness.label": "Mörka timmar",
    "patterns.darkness.high": "lång natt",
    "patterns.darkness.low": "kort natt",
    "patterns.statement": "Cirka {hi} besök per natt med {hi_desc}, cirka {lo} med {lo_desc}.",
    "insights.midnight": "midnatt",
    "insights.busiest": "Mest rörelse vid dina kameror mellan {start} och {end}.",
    "insights.species_mostly": "Kamerorna ser {species} mest mellan {start} och {end}.",
    "insights.concentrated": (
        "Det mesta händer vid {cameras}. De andra kamerorna ser betydligt mindre."
    ),
    "insights.busiest_cameras": "{cameras} är dina livligaste kameror.",
    "insights.class_missing": "Välj vilka djur som ska visas.",

    # ---- species in Settings -------------------------------------------------
    "species.name_hidden_chars": "Namnet innehåller dolda tecken. Skriv det igen.",
    "species.name_length": "Ett namn är 1 till 40 tecken.",
    "species.not_found": "Arten hittades inte.",

    # ---- the alerts feed on Tonight ------------------------------------------
    "ago.unknown": "okänt",
    "ago.just_now": "nyss",
    "ago.ago": "för {span} sedan",
    "ago.m": "{n} min",
    "ago.h": "{n} h",
    "ago.d": "{n} d",
    "feed.seen": {
        "one": "{n} observation de senaste 2 dygnen, senast {ago}.",
        "other": "{n} observationer de senaste 2 dygnen, senast {ago}.",
    },
    "feed.battery_title": "{camera}: lågt batteri",
    "feed.battery": "{pct} % kvar. Ta med batterier nästa gång du är där.",
    "feed.since": ", sedan natten till {day}",
    "feed.quiet_title": "{camera}: tyst",
    "feed.quiet": {
        "one": (
            "Inget under den senaste {n} bevakade natten{since}. Där brukar det vara {usual} besök "
            "per natt."
        ),
        "other": (
            "Inget under de senaste {n} bevakade nätterna{since}. Där brukar det vara {usual} besök"
            " per natt."
        ),
    },

    # ---- the week's wind -----------------------------------------------------
    "week.tonight": "I kväll",
    "week.tonight_hours": "i kväll {hours}",
    "week.no_position": "{stand} finns inte på kartan än, så vinden där kan inte bedömas.",
    "week.no_bedding": "Inga liggplatser ritade än, så vinden kan inte bedömas för {stand}.",
    "week.no_geometry": (
        "{stand} har inga inkommande riktningar angivna, så bedöm vinden där själv."
    ),
    "week.no_forecast": "Ingen vindprognos för veckan än.",
    "week.right": "Rätt vind för {stand}: {when}",
    "week.none": "Ingen rätt vind för {stand} den här veckan.",

    # ---- the track record ----------------------------------------------------
    "record.too_few": {
        "one": "{n} natt kontrollerad hittills. Hur ofta den haft rätt visas efter {needed}.",
        "other": "{n} nätter kontrollerade hittills. Hur ofta den haft rätt visas efter {needed}.",
    },
    "record.verdict": {
        "one": "När den sa ”{verdict}” om en kamera kom djuren dit {came} av {n} gånger.",
        "other": "När den sa ”{verdict}” om en kamera kom djuren dit {came} av {n} gånger.",
    },
    "record.beats": "Dess odds låg närmare utfallet än varje kameras vanliga nivå.",
    "record.no_better": "Dess odds låg inte närmare utfallet än varje kameras vanliga nivå.",
    "record.too_few_each": {
        "one": "{n} natt kontrollerad, för få av varje bedömning för att säga något än.",
        "other": "{n} nätter kontrollerade, för få av varje bedömning för att säga något än.",
    },

    # ---- photos and animals --------------------------------------------------
    "images.viewer": "Läsare kan titta på bilderna men inte ändra dem.",
    "images.old_link": "Bildlänken har gått ut. Öppna bilden i appen igen.",
    "images.sign_in": "Logga in för att se bilder.",
    "images.no_picture": "Den här bilden har ingen bildfil än, så det finns inget att rätta.",
    "images.no_people": "Appen räknar redan ingen i den här bilden.",
    "animals.not_found": "Djuret hittades inte.",
    "animals.gone": "Det djuret finns inte längre i appen.",
    "animals.name_first": "Skriv ett namn först.",
    "animals.name_long": "Ett namn får vara högst 60 tecken.",
    "animals.bad_status": "status måste vara en av {statuses}",
    "animals.merge_target": "Djuret att slå ihop med hittades inte.",
    "animals.reid_running": "Letar redan. Det tar några minuter.",
    "animals.reid_started": "Letar efter återkommande besökare. Det tar några minuter.",

    # ---- areas on the map, and admin -----------------------------------------
    "zones.name_needed": "Ge den ett namn som laget känner igen.",
    "zones.name_not_empty": "Namnet kan ändras men inte lämnas tomt.",
    "zones.outline_not_empty": "Konturen kan ändras men inte lämnas tom.",
    "zones.bad_kind": "typen måste vara en av {kinds}",
    "zones.gone": "Det området finns inte på kartan.",
    "admin.deploying": "Servern installerar en uppdatering. Försök igen om några minuter.",
    "admin.no_api_key": "Lägg först till ANTHROPIC_API_KEY i .env",
    "admin.labelling": "Märker redan. Märkningarna dyker upp inom några minuter.",
    "admin.labels_coming": "Märkningarna dyker upp under Kameror inom några minuter.",
    "admin.retry": {
        "one": "{n} bild granskas igen vid nästa hämtning.",
        "other": "{n} bilder granskas igen vid nästa hämtning.",
    },
    "admin.nothing_to_retry": "Inget att försöka igen.",
    "admin.reload": "Ladda om appen: uppdateringar visas nu av sig själva under Appversion.",

    # ---- server upkeep (kept in English, said in the reader's language) ------
    "restore.no_table": "Den återställda kopian saknar tabellen {table}.",
    "restore.no_rows": "Den återställda kopian har inga rader i {table}.",
    "restore.photos_missing": (
        "{n} av {total} kontrollerade bilder saknas i säkerhetskopians bildmapp."
    ),
    "restore.failed": "Kontrollen kunde inte köras ({error}).",
    "ops.unreadable": "Dess statusfil kan inte läsas.",

    # ---- drawing on the map --------------------------------------------------
    "shape.not_polygon": "Konturen måste vara en GeoJSON-polygon.",
    "shape.no_corners": "Konturen har inga hörn.",
    "shape.too_many": "Konturen har {n} hörn. Håll den under {limit}.",
    "shape.two_numbers": "Varje hörn måste vara två tal: longitud, sedan latitud.",
    "shape.off_map": (
        "Ett hörn ligger utanför kartan. Hörnen anges med longitud först, sedan latitud."
    ),
    "shape.three": "Tryck ut minst tre hörn runt området.",
    "shape.too_big": "Konturen är över 20 km bred. Rita bara skyddet där djuren ligger.",
    "shape.crosses": "Konturen korsar sig själv. Lägg hörnen i ordning runt kanten.",
    "shape.no_area": "Konturen har nästan ingen yta. Sprid ut hörnen runt skyddet.",
    "box.four_numbers": "Rutan behöver fyra tal: syd, väst, nord och öst.",
    "box.off_map": "Rutan ligger utanför kartan.",
    "box.too_big": (
        "Den är {km} km bred, mer än en telefon bör spara. Zooma in så att jaktmarken är under "
        "{limit} km bred."
    ),
    "box.too_small": "Den är för liten för att vara jaktmarken. Zooma ut lite.",
    "terrain.busy": "Höjdtjänsten är upptagen. Försök igen om några minuter.",
    "terrain.down": "Höjdtjänsten svarade inte. Försök igen senare.",

    # ---- signing in, too many tries ------------------------------------------
    "count.minutes": {
        "one": "{n} minut",
        "other": "{n} minuter",
    },
    "throttle.place": "För många felaktiga lösenord härifrån. Försök igen om {wait}.",
    "throttle.at_once": "För många inloggningar härifrån samtidigt. Försök igen om några sekunder.",
    "throttle.checking": (
        "Ditt förra försök kontrolleras fortfarande. Försök igen om några sekunder."
    ),
    "throttle.email": {
        "one": (
            "För många felaktiga lösenord för den här e-postadressen. Försök igen om {n} sekund."
        ),
        "other": (
            "För många felaktiga lösenord för den här e-postadressen. Försök igen om {n} sekunder."
        ),
    },
    "throttle.email_lately": (
        "För många felaktiga lösenord för den här e-postadressen på sistone. Försök igen om {wait},"
        " eller från en telefon som har loggat in med den förut."
    ),

    # ---- the stag/hind labelling pass (kept in English, said in the reader's language) ----
    "sexpass.key_refused": (
        "Anthropic avvisade API-nyckeln. Kontrollera ANTHROPIC_API_KEY i serverns .env."
    ),
    "sexpass.no_credit": (
        "Anthropic-kontot saknar kredit. Fyll på för att märka hjortar och hindar igen."
    ),
    "sexpass.no_model": (
        "Anthropic känner inte till modellen {model}. Be den som sköter servern att uppdatera den."
    ),
    "sexpass.limited": "Anthropic begränsar förfrågningar just nu. Nytt försök nästa timme.",
    "sexpass.unreachable": "Kunde inte nå Anthropic. Nytt försök nästa timme.",
    "sexpass.http": "Anthropic hade ett problem (HTTP {status}). Nytt försök nästa timme.",
    "sexpass.bad_answer": "Anthropic svarade inte ordentligt. Nytt försök nästa timme.",

    # ---- Look for repeats (kept in English, said in the reader's language) ----
    "reid.failed": "Något gick fel ({error}).",
    "reid.stopped": (
        "Det stannade halvvägs: servern var upptagen för länge. Tryck igen för att slutföra."
    ),

    # ---- the moon ------------------------------------------------------------
    "moon.new_moon": "Nymåne",
    "moon.waxing_crescent": "Tilltagande skära",
    "moon.first_quarter": "Första kvarteret",
    "moon.waxing_gibbous": "Tilltagande måne",
    "moon.full_moon": "Fullmåne",
    "moon.waning_gibbous": "Avtagande måne",
    "moon.last_quarter": "Sista kvarteret",
    "moon.waning_crescent": "Avtagande skära",
}
