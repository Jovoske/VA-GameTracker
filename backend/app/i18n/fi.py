"""Finnish (suomi): what the server says. The same keys and placeholders as en.py
(tests/test_i18n.py); a key missing here would be said in English.

Finnish hunters' words: villisika, saksanhirvi, metsäkauris, kuusipeura,
ruokintapaikka, passi, torni.
"""

MESSAGES: dict[str, str | dict[str, str]] = {
    # ---- lists and the calendar ----------------------------------------------
    "list.two": "{a} ja {b}",
    "list.three": "{a}, {b} ja {c}",
    "list.more": "{a}, {b} ja {n} muuta",
    "cal.wd.0": "ma",
    "cal.wd.1": "ti",
    "cal.wd.2": "ke",
    "cal.wd.3": "to",
    "cal.wd.4": "pe",
    "cal.wd.5": "la",
    "cal.wd.6": "su",
    "cal.wdl.0": "maanantai",
    "cal.wdl.1": "tiistai",
    "cal.wdl.2": "keskiviikko",
    "cal.wdl.3": "torstai",
    "cal.wdl.4": "perjantai",
    "cal.wdl.5": "lauantai",
    "cal.wdl.6": "sunnuntai",
    "cal.mon.1": "tammik.",
    "cal.mon.2": "helmik.",
    "cal.mon.3": "maalisk.",
    "cal.mon.4": "huhtik.",
    "cal.mon.5": "toukok.",
    "cal.mon.6": "kesäk.",
    "cal.mon.7": "heinäk.",
    "cal.mon.8": "elok.",
    "cal.mon.9": "syysk.",
    "cal.mon.10": "lokak.",
    "cal.mon.11": "marrask.",
    "cal.mon.12": "jouluk.",
    "cal.monl.1": "tammikuu",
    "cal.monl.2": "helmikuu",
    "cal.monl.3": "maaliskuu",
    "cal.monl.4": "huhtikuu",
    "cal.monl.5": "toukokuu",
    "cal.monl.6": "kesäkuu",
    "cal.monl.7": "heinäkuu",
    "cal.monl.8": "elokuu",
    "cal.monl.9": "syyskuu",
    "cal.monl.10": "lokakuu",
    "cal.monl.11": "marraskuu",
    "cal.monl.12": "joulukuu",
    "cal.day_month": "{day}. {month}",
    "cal.wd_day_month": "{wd} {day}. {month}",

    # ---- species and what an animal is ---------------------------------------
    "species.bison": "Biisoni",
    "species.badger": "Mäyrä",
    "species.ibex": "Vuorikauris",
    "species.beaver": "Majava",
    "species.red_deer": "Saksanhirvi",
    "species.chamois": "Gemssi",
    "species.cat": "Kissa",
    "species.goat": "Vuohi",
    "species.roe_deer": "Metsäkauris",
    "species.dog": "Koira",
    "species.fallow_deer": "Kuusipeura",
    "species.squirrel": "Orava",
    "species.moose": "Hirvi",
    "species.equid": "Hevonen tai aasi",
    "species.genet": "Genetti",
    "species.wolverine": "Ahma",
    "species.hedgehog": "Siili",
    "species.lagomorph": "Jänis tai kani",
    "species.wolf": "Susi",
    "species.otter": "Saukko",
    "species.lynx": "Ilves",
    "species.marmot": "Murmeli",
    "species.micromammal": "Hiiri tai rotta",
    "species.mouflon": "Mufloni",
    "species.sheep": "Lammas",
    "species.mustelid": "Näätä tai lumikko",
    "species.bird": "Lintu",
    "species.bear": "Karhu",
    "species.nutria": "Nutria",
    "species.raccoon": "Pesukarhu",
    "species.fox": "Kettu",
    "species.reindeer": "Poro",
    "species.wild_boar": "Villisika",
    "species.cow": "Nauta",
    "class.stag": "Saksanhirviuros",
    "class.hind": "Saksanhirvinaaras",
    "class.hind_calf": "Naaras + vasa",
    "class.boar": "Karju",
    "class.sow": "Emakko",
    "class.sow_piglets": "Emakko + porsaat",
    "class.sounder": "Sikalauma",
    "class.herd": "{name} (lauma)",
    "class.animal": "Eläin",
    "class.animals": "Eläimet",

    # ---- signing in ----------------------------------------------------------
    "auth.not_authenticated": "Et ole kirjautunut sisään",
    "auth.bad_credentials": "Kirjautumistiedot ovat virheelliset",
    "auth.token_invalid": "Kirjautuminen on virheellinen tai vanhentunut",
    "auth.token_subject": "Kirjautumisen tunniste on virheellinen",
    "auth.user_not_found": "Käyttäjää ei löydy",
    "auth.signed_out": "Sinut kirjattiin ulos. Kirjaudu uudelleen.",
    "auth.admin_only": "Vain alueen ylläpitäjä voi tehdä tämän.",
    "auth.busy": "Palvelin on kiireinen. Yritä minuutin päästä uudelleen.",
    "auth.wrong_password": "Väärä sähköposti tai salasana",
    "auth.published": (
        "Tämä on GameSensen mukana julkaistu salasana, joten sillä ei voi kirjautua internetistä. "
        "Kirjaudu palvelimen omasta verkosta ja vaihda se Asetuksissa, tai aja palvelimella: python"
        " -m app.manage set-password {email}"
    ),
    "auth.language_unknown": "Valitse English, Suomi, Svenska, Norsk tai Español.",
    "auth.not_current_password": "Tämä ei ole nykyinen salasanasi",
    "auth.new_password_short": "Uudessa salasanassa on oltava vähintään 8 merkkiä",
    "auth.password_changed": (
        "Salasana vaihdettu. Kaikkien muiden puhelinten, joilla olet kirjautuneena, on "
        "kirjauduttava uudelleen."
    ),

    # ---- people on the app ---------------------------------------------------
    "users.email_invalid": "Anna kelvollinen sähköpostiosoite",
    "users.password_short": "Salasanassa on oltava vähintään 8 merkkiä",
    "users.pick_role": "Valitse Jäsen tai Ylläpitäjä",
    "users.email_taken": "Tällä sähköpostilla on jo tunnus",
    "users.gone": "Tätä henkilöä ei ole enää sovelluksessa.",
    "users.not_yourself": "Et voi poistaa itseäsi",
    "users.keep_admin": "Vähintään yksi ylläpitäjä on pidettävä",
    "users.remove_failed": (
        "Käyttäjää {email} ei voitu poistaa: jokin sovelluksessa viittaa vielä häneen. Mitään ei "
        "muutettu. Yritä uudelleen tai kysy palvelimen ylläpitäjältä."
    ),
    "users.removed": "{email} ei voi enää kirjautua. Hänen tallentamansa tiedot säilyvät.",
    "users.logins_moved": {
        "one": "{n} hänen lisäämänsä kameratunnus hakee edelleen kuvia, nyt sinun nimissäsi.",
        "other": "{n} hänen lisäämäänsä kameratunnusta hakee edelleen kuvia, nyt sinun nimissäsi.",
    },

    # ---- Tonight -------------------------------------------------------------
    "time.hours": "{h} t",
    "time.clock": "klo {h}",
    "time.minutes": "{m} min",
    "sun.at_sunset": "heti auringonlaskusta",
    "sun.after": "{span} auringonlaskun jälkeen",
    "sun.before": "{span} ennen auringonlaskua",
    "tonight.factor.not_sending": {
        "one": "Kamera ei lähetä nyt kuvia. Arvio perustuu {n} yön historiaan.",
        "other": "Kamera ei lähetä nyt kuvia. Arvio perustuu {n} yön historiaan.",
    },
    "tonight.factor.unchecked": (
        "Kuvia {n}/7 viime yöltä tarkistetaan vielä. Arvio perustuu kameran historiaan."
    ),
    "tonight.factor.few_watched": (
        "Kamera valvoi täällä vain {n}/7 viime yöstä. Arvio perustuu sen historiaan."
    ),
    "tonight.factor.not_watched": " ({n} valvomatta)",
    "tonight.factor.seen_week": "{species}: nähty täällä {n}/7 viime yönä{gap}",
    "tonight.factor.none_week": "Ei havaintoja täällä 7 viime yönä: {species}{gap}",
    "tonight.factor.outside_hours": (
        "{species}: nähty täällä vain aikoina, jolloin passissa ei istuta, joten parhaita tunteja "
        "ei voi antaa"
    ),
    "tonight.best_hours": "Parhaat tunnit {start}–{end}",
    "tonight.best_hours_from": "Parhaat tunnit {start}–{end}, alkaen {relative}",
    "tonight.left_out.unchecked_n": "{n} yön kuvia ei ole vielä tarkistettu",
    "tonight.left_out.unchecked": "kuvia ei ole vielä tarkistettu",
    "tonight.left_out.blind_n": "{n} yönä kamera ei ehkä valvonut",
    "tonight.left_out.blind": "kamera ei ehkä valvonut",
    "tonight.left_out": {
        "one": "{n} yö kameralla {camera} jätetty pois: {why}.",
        "other": "{n} yötä kameralla {camera} jätetty pois: {why}.",
    },
    "tonight.alert.silent": "Ei kuvia {n} päivään, joten se on jätetty pois illan arviosta",
    "tonight.none.picked": "Mikään kamera ei ole vielä nähnyt valitsemiasi eläimiä.",
    "tonight.none.sending": "Kuvia lähettävät kamerat eivät ole vielä nähneet eläimiä.",
    "tonight.none.yet": "Ei vielä havaintoja.",
    "tonight.reason": "{species}: nähty {n}/{total} yönä tällä kameralla.",
    "tonight.caveat": (
        "Kamera valvoo koko yön. Sinä olet paikalla muutaman tunnin, joten valitse parhaat tunnit "
        "ja huomioi tuuli."
    ),

    # ---- wind ----------------------------------------------------------------
    "compass.N": "P",
    "compass.NE": "KO",
    "compass.E": "I",
    "compass.SE": "KA",
    "compass.S": "E",
    "compass.SW": "LO",
    "compass.W": "L",
    "compass.NW": "LU",
    "wind.reading": "Tuuli {dir} {speed} km/h",
    "wind.no_forecast": "Tälle illalle ei ole tuuliennustetta. Tarkista itse.",
    "wind.no_forecast_stand": (
        "Tälle illalle ei ole tuuliennustetta. Tarkista itse ennen kuin menet passiin {stand}."
    ),
    "wind.no_position": (
        "{reading}. Passi {stand} ei ole vielä kartalla, joten hajusi kulkua ei voi laskea."
    ),
    "wind.no_bedding": (
        "{reading}. Makuupaikkoja ei ole vielä piirretty, joten ei voi laskea, minne hajusi "
        "kulkeutuu. Piirrä kartalle, missä eläimet makaavat."
    ),
    "wind.no_stand": (
        "{reading}. Kameran {camera} lähellä ei ole vielä passia, joten tuulta ei voi arvioida "
        "paikalle. Arvioi itse."
    ),
    "wind.arcs.too_light": (
        "Tuuli {dir} {speed} km/h, liian heikko arvioitavaksi. Termiikki ratkaisee. Tarkista "
        "autolla."
    ),
    "wind.arcs.no_geometry": (
        "Tuuli {dir} {speed} km/h. Passille {stand} ei ole merkitty tulosuuntia, joten arvioi tuuli"
        " itse."
    ),
    "wind.arcs.divert": " Mene mieluummin passiin {stand}.",
    "wind.arcs.wrong": (
        "Tuuli {dir} {speed} km/h, väärä passille {stand}. Hajusi kulkee suoraan tulosuuntaan "
        "{approach}.{divert}"
    ),
    "wind.arcs.clean": (
        "Tuuli {dir} {speed} km/h, sopiva passille {stand}. Hajusi kulkee suuntaan {scent}, "
        "poispäin eläinten tulosuunnasta."
    ),

    # ---- slope wind and bedding ----------------------------------------------
    "thermal.no_terrain": "Maastomallia ei ole ladattu, joten rinnetuulta ei voi laskea.",
    "thermal.off_terrain": (
        "Tämä kohta on ladatun maastomallin ulkopuolella, joten rinnetuulta ei voi laskea. "
        "Ylläpitäjä voi ladata maastomallin uudelleen niin, että se kattaa kohdan."
    ),
    "thermal.flat": "Maasto on tässä lähes tasaista. Kylmällä ilmalla ei ole rinnettä, jota valua.",
    "thermal.overcast": (
        "Pilvistä ({pct} %), joten rinnetuuli jää tänä iltana heikoksi. Tarkista itse."
    ),
    "thermal.katabatic": (
        "Ennuste on tyyni, joten rinne ratkaisee. Kylmä ilma valuu alarinteeseen suuntaan {dir} "
        "noin {speed} km/h. Hajusi kulkee sen mukana."
    ),
    "thermal.katabatic_settling": (
        "Ennuste on tyyni, joten rinne ratkaisee. Kylmä ilma valuu alarinteeseen suuntaan {dir} "
        "noin {speed} km/h. Se asettuu vielä hämärissä ja voi kääntyä. Hajusi kulkee sen mukana."
    ),
    "thermal.anabatic": (
        "Tyyntä ja aurinkoista, joten ilma nousee rinnettä ylös suuntaan {dir}. Se kääntyy ja valuu"
        " takaisin alas auringonlaskun aikoihin."
    ),
    "bedding.no_position": "Passilla {stand} ei ole vielä sijaintia kartalla.",
    "bedding.none": (
        "Makuupaikkoja ei ole vielä piirretty — piirrä, missä eläimet makaavat, niin tästä tulee "
        "neuvo."
    ),
    "bedding.too_light": "Tuuli {dir} {speed} km/h — liian heikko arvioitavaksi. {why}",
    "bedding.thermals_decide": "Termiikki ratkaisee tämän; tarkista se autolla.",
    "bedding.lead.katabatic": (
        "Ennuste tyyni, joten rinne ratkaisee — kylmä ilma valuu suuntaan {dir} noin {speed} "
        "km/h{fall}"
    ),
    "bedding.fall": " ({pct} % kaltevuus)",
    "bedding.lead.anabatic": (
        "Tyyntä ja aurinkoista — ilma nousee rinnettä suuntaan {dir} noin {speed} km/h"
    ),
    "bedding.caveat.dusk": " Se kääntyy hämärissä, joten tarkista paikan päällä.",
    "bedding.caveat.dem": " Noin 90 metrin maastomalli näkee rinteen, ei sinun notkoasi.",
    "bedding.into_own": "makuupaikalle {zone}, jonka sisällä passisi on",
    "bedding.into_near": "makuupaikalle {zone} {m} m päähän",
    "bedding.into_far": "makuupaikalle {zone}, {m} m päähän",
    "bedding.carries.thermal": "{lead}, ja se vie hajusi {where}.{caveat}",
    "bedding.carries.wind": "{lead} — hajusi kulkee suuntaan {dir} {where}.",
    "bedding.clean.thermal": "{lead}, poispäin makuupaikoista (lähimpään {m} m).{caveat}",
    "bedding.clean.wind": (
        "{lead} — puhdas. Haju kulkee suuntaan {dir}, poispäin makuupaikoista (lähimpään {m} m)."
    ),
    "bedding.draw": "Piirrä makuupaikat, niin näet tämän.",
    "bedding.no_forecast": "Tälle illalle ei ole tuuliennustetta.",
    "bedding.too_light_map": (
        "Tuuli on liian heikko kartoitettavaksi — tällaisena iltana termiikki ratkaisee."
    ),
    "bedding.safe.note": (
        "Pelkkää geometriaa — tämä ei tiedä suojasta, kulkureiteistä eikä turvallisesta taustasta. "
        "Se rajaa, mistä etsiä; se ei valitse paikkaa."
    ),
    "bedding.safe.note_calm": (
        "Ennuste on tyyni, joten tämä seuraa maastoa: jokainen ruutu käyttää omaa kaltevuuttaan, "
        "koska kylmä ilma valuu pimeällä alarinteeseen. Noin 90 metrin maastomalli näkee rinteen, "
        "ei notkoa, jossa istut."
    ),

    # ---- what changed --------------------------------------------------------
    "num.decimal_mark": ",",
    "count.visits": {
        "one": "{n} käynti",
        "other": "{n} käyntiä",
    },
    "changed.about": "noin {x}",
    "changed.no_cameras": "Kameroita ei ole vielä lisätty.",
    "changed.camera_down": (
        "{camera} ei lähettänyt viime yönä mitään. Ei tiedetä, kulkiko siitä mitään."
    ),
    "changed.return": {
        "one": "Eläimiä taas kameralla {camera} {n} hiljaisen yön jälkeen.",
        "other": "Eläimiä taas kameralla {camera} {n} hiljaisen yön jälkeen.",
    },
    "changed.gone_quiet": {
        "one": "{camera} on ollut hiljaa {n} yön. Siellä käy yleensä {usual} kertaa yössä.",
        "other": "{camera} on ollut hiljaa {n} yötä. Siellä käy yleensä {usual} kertaa yössä.",
    },
    "changed.busier": (
        "{camera}: viime yönä vilkkaampaa kuin tavallisesti: {visits}, tavallisesti {usual}."
    ),
    "changed.quieter": (
        "{camera}: viime yönä hiljaisempaa kuin tavallisesti: {visits}, tavallisesti {usual}."
    ),
    "changed.some_cameras": "osa kameroista",
    "changed.checking": "Viime yön kuvia tarkistetaan vielä: {cameras}.",
    "changed.none": "Ei muutoksia. Suunnilleen samaa kuin viime öinä.",

    # ---- camera health -------------------------------------------------------
    "health.retired": "Poistettu käytöstä {day}. Ei mukana illan suunnitelmassa eikä luvuissa",
    "health.disconnected": "Ei yhteydessä: mikään kameratunnus ei hae sitä nyt",
    "health.not_syncing": "Kuvia ei tule. Kameratunnus vaatii huomiota.",
    "health.not_fetched": "Kuvia ei tule. Yksikään kuvahaku ei ole onnistunut yli 2 tuntiin.",
    "health.fetch_error": "Kuvia ei tule. {error}",
    "health.no_photos_since": "Ei kuvia {day} jälkeen",
    "health.no_photos": "Ei vielä kuvia",
    "health.photos_only": "Lähettää vain kuvia, ei tilaraportteja",
    "health.clock_fast": (
        ". Sen kello on {h} t edellä (kellojen siirto unohtui?): kuvien ajat korjataan, mutta aseta"
        " kameran kello"
    ),
    "health.no_checkin_for": "Ei yhteydenottoa {h} tuntiin",
    "health.no_checkin": "Ei vielä yhteydenottoa",
    "health.photo_limit": "Kuvaraja täynnä ({count}/{limit})",
    "health.battery_low": "Akku vähissä ({pct} %)",
    "health.ok": "Toimii normaalisti",

    # ---- camera logins (kept in English, said in the reader's language) ------
    "login.unreadable": "Tallennettua salasanaa ei voi lukea. Syötä se uudelleen.",
    "login.spypoint_refused": "SPYPOINT ei hyväksynyt salasanaa. Syötä se uudelleen.",
    "login.ubox_refused": "UBox ei hyväksynyt salasanaa. Syötä se uudelleen.",
    "login.ubox_signed_out": "UBox kirjasi tämän tunnuksen ulos. Syötä salasana uudelleen.",
    "login.spypoint_throttled": (
        "SPYPOINT torjuu pyyntöjä juuri nyt. Seuraava haku yrittää uudelleen."
    ),
    "login.spypoint_down": (
        "SPYPOINT ei vastaa kunnolla juuri nyt. Seuraava haku yrittää uudelleen."
    ),
    "login.spypoint_refused_request": "SPYPOINT hylkäsi pyynnön. Seuraava haku yrittää uudelleen.",
    "login.spypoint_unreadable": (
        "SPYPOINT lähetti jotain, mitä sovellus ei osaa lukea. Seuraava haku yrittää uudelleen."
    ),
    "login.ubox_unknown": (
        "UBox ei tunne tätä tunnusta. Tarkista UBox Pro -sovelluksessa käytetty sähköposti."
    ),
    "login.unreachable": "Palveluun {provider} ei saatu yhteyttä. Seuraava haku yrittää uudelleen.",
    "login.ubox_down": "UBox ei vastaa kunnolla juuri nyt. Seuraava haku yrittää uudelleen.",
    "login.other": "{text}. Seuraava haku yrittää uudelleen.",
    "login.failed": (
        "Haku palvelusta {provider} epäonnistui ({error}). Seuraava haku yrittää uudelleen."
    ),
    "login.primary_label": "SPYPOINT-päätunnus",

    # ---- photo fetches (kept in English, said in the reader's language) ------
    "login.copy_of_primary": (
        "Tämä on alueen SPYPOINT-päätunnus, jolla kuvat haetaan jo. Poista tämä kopio."
    ),
    "sync.some_failed": "{n}/{total} kamerasta epäonnistui. {error}",
    "ubox.snap.retry": {
        "one": "{n} kuva ei latautunut. Seuraava haku yrittää uudelleen.",
        "other": "{n} kuvaa ei latautunut. Seuraava haku yrittää uudelleen.",
    },
    "ubox.snap.dropped": {
        "one": "{n} kuva ei latautunut. Sitä yritettiin {tries} kertaa, joten se jätetään pois.",
        "other": (
            "{n} kuvaa ei latautunut. Niitä yritettiin {tries} kertaa, joten ne jätetään pois."
        ),
    },
    "ubox.snap.some": {
        "one": (
            "{failed} kuvaa ei latautunut. {n} yritetään uudelleen seuraavalla haulla; muita "
            "yritettiin {tries} kertaa, ja ne jätetään pois."
        ),
        "other": (
            "{failed} kuvaa ei latautunut. {n} yritetään uudelleen seuraavalla haulla; muita "
            "yritettiin {tries} kertaa, ja ne jätetään pois."
        ),
    },

    # ---- UBox errors (kept in English, said in the reader's language) --------
    "ubox.err.host_unresolved": "UBoxin kuvapalvelimen nimeä ei voitu selvittää",
    "ubox.err.host_public": "UBoxin kuvaosoitteen on käytettävä julkista HTTPS-palvelinta",
    "ubox.err.bad_json": "UBox palautti virheellisen JSON-vastauksen",
    "ubox.err.unexpected": "UBox palautti odottamattoman vastauksen",
    "ubox.err.rejected_password": "UBox hylkäsi tunnuksen tai salasanan",
    "ubox.err.rejected_request": "UBox hylkäsi pyynnön; tarkista tunnus UBox Prossa",
    "ubox.err.no_data": "UBoxin vastauksesta puuttuu dataosa",
    "ubox.err.need_login": "UBoxin sähköposti ja salasana tarvitaan",
    "ubox.err.unreachable_login": "UBoxiin ei saatu yhteyttä kirjautumista varten",
    "ubox.err.no_token": "UBoxin kirjautumisvastauksesta puuttuu istuntotunniste",
    "ubox.err.unreachable": "UBoxiin ei saatu yhteyttä",
    "ubox.err.auth_expired": (
        "UBox-kirjautuminen vanheni uudelleenyrityksen jälkeen; yhdistä tunnus uudelleen"
    ),
    "ubox.err.auth_failed": "UBox-tunnistautuminen epäonnistui",
    "ubox.err.no_devices": "UBoxin laitevastauksesta puuttuu tietoja",
    "ubox.err.device_no_id": "UBox palautti laitteen ilman tunnistetta",
    "ubox.err.naive_dates": "UBoxin tapahtumahaku vaatii aikavyöhykkeelliset päivämäärät",
    "ubox.err.bad_range": "UBoxin tapahtumahaussa on virheellinen aikaväli tai sivukoko",
    "ubox.err.no_events": "UBoxin tapahtumavastauksesta puuttuu luettelo",
    "ubox.err.incomplete_page": (
        "UBox palautti vajaan tapahtumasivun; haku yrittää myöhemmin uudelleen"
    ),
    "ubox.err.bad_event": "UBox palautti virheellisen tapahtuman",
    "ubox.err.repeated_page": "UBox toisti tapahtumasivun; haku yrittää myöhemmin uudelleen",
    "ubox.err.bad_event_fields": "UBoxin tapahtumassa on virheellinen aikaleima tai kameratunniste",
    "ubox.err.fewer_events": (
        "UBox palautti vähemmän tapahtumia kuin ilmoitti; haku yrittää uudelleen"
    ),
    "ubox.err.page_limit": "UBoxin tapahtumasivujen raja täyttyi; käytä lyhyempää hakujaksoa",
    "ubox.err.https_only": "UBoxin kuvaosoitteen on käytettävä HTTPS:ää",
    "ubox.err.too_big": "UBoxin kuva ylittää 20 Mt:n latausrajan",
    "ubox.err.empty_image": "UBox palautti tyhjän kuvan",
    "ubox.err.download_failed": "UBoxin kuvaa ei voitu ladata",
    "ubox.err.unknown_account": (
        "UBox ei tunnistanut tätä tunnusta. Tarkista oikea kamerasovellus ja siihen kirjautunut "
        "sähköposti."
    ),
    "ubox.err.login_http": "UBox-kirjautuminen epäonnistui (HTTP {status})",
    "ubox.err.request_http": "UBox-pyyntö epäonnistui (HTTP {status})",
    "ubox.err.download_http": "UBoxin kuvan lataus epäonnistui (HTTP {status})",
    "ubox.err.other_estate": "Tämä UBox-kamera on jo liitetty toiseen alueeseen",
    "ubox.err.snapshot_size": "Kuva on tyhjä tai ylittää 20 Mt:n rajan",
    "ubox.err.snapshot_pixels": "Kuvan on oltava JPEG ja enintään 40 megapikseliä",
    "ubox.err.snapshot_unreadable": "Kuva ei ole luettava JPEG",
    "ubox.err.snapshot_failed": "Luettavaa kuvaa ei saatu ladattua",
    "ubox.err.no_estate": "Tunnukseen ei ole liitetty aluetta",
    "fetch.disk_label": "Palvelimen levy",
    "fetch.failed": "Haku epäonnistui. Seuraava haku yrittää uudelleen.",
    "fetch.disk_full": (
        "Lähes täynnä ({gb} Gt vapaana). Kuvat odottavat kameroissa ja tulevat, kun tilaa on."
    ),
    "fetch.provider_failed": (
        "Haku palvelusta {provider} epäonnistui ({error}). Seuraava haku yrittää uudelleen."
    ),
    "fetch.ai_failed": "Eläinten etsiminen epäonnistui ({error})",

    # ---- the AI pass (kept in English, said in the reader's language) --------
    "ai.detector_failed": "Eläintunnistin ei käynnistynyt ({error}).",
    "ai.classifier_failed": "Lajimalli ei käynnistynyt ({error}).",
    "ai.models_broken": "Mallit lakkasivat toimimasta ({error}).",
    "ai.stopped_streak": (
        "{why} Tarkistus pysähtyi, kun {n} kuvaa peräkkäin epäonnistui; niitä ei laskettu kuvia "
        "vastaan."
    ),

    # ---- photos --------------------------------------------------------------
    "photos.not_checked": "Ei vielä tarkistettu",
    "photos.could_not_check": "Ei voitu tarkistaa",
    "photos.people_admin_only": "Vain ylläpitäjä näkee kuvat, joissa on ihmisiä tai ajoneuvoja.",
    "photos.gone": "Kuva ei ole enää saatavilla.",
    "people.person_vehicle": "Ihminen ja ajoneuvo",
    "people.person": "Ihminen",
    "people.vehicle": "Ajoneuvo",
    "people.person_or_vehicle": "Ihminen tai ajoneuvo",

    # ---- cameras and the Check button ----------------------------------------
    "busy.reid": "etsii toistuvia vierailijoita",
    "busy.plan": "kirjoittaa illan suunnitelmaa",
    "busy.score": "vertaa viime yön suunnitelmaa kameroihin",
    "busy.scan": "etsii kuvista eläimiä",
    "busy.deploy": "asentaa päivitystä",
    "busy.other": "tekee toista työtä",
    "busy.fetch": "hakee kuvia",
    "busy.try_later": "Palvelin {what}. Yritä muutaman minuutin päästä uudelleen.",
    "cameras.start_failed": (
        "Sitä ei voitu käynnistää palvelimella. Yritä minuutin päästä uudelleen."
    ),
    "cameras.name_hidden_chars": "Kameran nimessä on piilomerkkejä. Kirjoita se uudelleen.",
    "cameras.name_length": "Kameran nimessä on oltava 1–100 merkkiä.",
    "cameras.rename_forbidden": "Vain alueen ylläpitäjät ja jäsenet voivat nimetä kameroita.",
    "cameras.not_found": "Kameraa ei löydy.",
    "cameras.name_taken": "Toisen kameran nimi on jo {name}. Valitse toinen nimi.",
    "cameras.name_taken_reset": "Toisen kameran nimi on jo {name}, joten tämä pitää oman nimensä.",
    "cameras.check_viewer": "Uudet kuvat tulevat itsestään 15 minuutin välein.",
    "cameras.check_running": "Tarkistetaan jo. Uudet kuvat näkyvät pian.",
    "cameras.check_asked": "Jo pyydetty. Uudet kuvat tulevat heti, kun palvelin vapautuu.",
    "cameras.check_queued": "Palvelin {what}. Uudet kuvat tulevat, kun se on valmis.",
    "cameras.off_map": "Kohta on kartan ulkopuolella. Siirrä karttaa ja yritä uudelleen.",
    "cameras.no_own_position": "Tämä kamera ei ole ilmoittanut omaa sijaintiaan. Sijoita se käsin.",

    # ---- camera logins in Settings -------------------------------------------
    "accounts.viewer": "Katselijat näkevät kameratunnukset mutta eivät voi lisätä niitä.",
    "accounts.enter_login": "Anna {provider}-sähköpostisi ja -salasanasi",
    "accounts.no_estate": "Liity alueeseen ennen kuin lisäät kameratunnuksen",
    "accounts.is_primary": "Tämä tunnus on jo yhdistetty alueen päätunnukseksi",
    "accounts.already_added": "Tämä {provider}-tunnus on jo lisätty",
    "accounts.already_added_refresh": (
        "Tämä {provider}-tunnus on jo lisätty. Päivitä sivu nähdäksesi sen."
    ),
    "accounts.connected_now": {
        "one": "Yhdistetty — {provider} ilmoittaa {n} kameran. Kuvia haetaan nyt.",
        "other": "Yhdistetty — {provider} ilmoittaa {n} kameraa. Kuvia haetaan nyt.",
    },
    "accounts.connected_later": {
        "one": "Yhdistetty — {provider} ilmoittaa {n} kameran. Kuvat tulevat seuraavalla haulla.",
        "other": "Yhdistetty — {provider} ilmoittaa {n} kameraa. Kuvat tulevat seuraavalla haulla.",
    },
    "accounts.unreachable": (
        "Palveluun {provider} ei saatu yhteyttä salasanan tarkistamiseksi. Yritä muutaman minuutin "
        "päästä uudelleen."
    ),
    "accounts.ubox_failed": "Yhteys UBox Prohon epäonnistui: {error}",
    "accounts.spypoint_refused": (
        "SPYPOINT ei hyväksynyt sähköpostia ja salasanaa. Tarkista ne SPYPOINT-sovelluksesta."
    ),
    "accounts.spypoint_failed": "SPYPOINT ei hyväksynyt tunnusta: {error}",
    "accounts.not_found": "Tunnusta ei löydy",
    "accounts.password_forbidden": (
        "Vain tunnuksen lisääjä tai ylläpitäjä voi vaihtaa sen salasanan"
    ),
    "accounts.enter_password": "Anna salasana",
    "accounts.password_saved": (
        "Salasana tallennettu. Kuvat tulevat seuraavalla haulla, 15 minuutin sisällä."
    ),
    "accounts.limits_forbidden": "Vain tunnuksen lisääjä tai ylläpitäjä voi muuttaa sen rajoja",
    "accounts.limits_ubox_only": "Kuvarajat koskevat vain UBox Pro -tunnuksia",
    "accounts.limits_saved": "Rajat tallennettu. Ne ovat voimassa seuraavasta hausta alkaen.",
    "accounts.remove_forbidden": "Vain tunnuksen lisääjä tai ylläpitäjä voi poistaa sen",

    # ---- alerts on the phone -------------------------------------------------
    "push.just_now": "juuri nyt",
    "push.time": "klo {time}",
    "push.last_night": "viime yönä klo {time}",
    "push.yesterday": "eilen klo {time}",
    "push.on_day": "{day} klo {time}",
    "push.at_camera": "{name}, kamera {camera}",
    "push.on_cameras": {
        "one": "{name} {n} kameralla",
        "other": "{name} {n} kameralla",
    },
    "push.one_visit": "1 käynti {when}.",
    "push.visits_last": "{visits}, viimeisin {when}.",
    "push.visits_at_last": "{visits} (kamerat {cameras}), viimeisin {when}.",
    "push.at_cameras": " (kamerat {cameras})",
    "push.update": "{visits}{where} alkaen {since}, viimeisin {last}.",
    "push.summary_title": "{n} uutta havaintoa, {animals} eläintä",
    "push.summary_body": "{names}, viimeisin {when}.",
    "verdict.best_odds": "Parhaat mahdollisuudet",
    "verdict.worth_a_look": "Kannattaa katsoa",
    "verdict.quiet": "Hiljaista",
    "verdict.no_data": "Liian vähän tietoa",
    "plan.wind.clean": "tuuli sopiva",
    "plan.wind.wrong": "tuuli väärä",
    "plan.wind.too_light": "tuuli liian heikko arvioitavaksi",
    "plan.wind.no_forecast": "ei tuuliennustetta",
    "plan.tonight": "{verdict} tänä iltana",
    "plan.sunset": "auringonlasku {time}",
    "plan.no_camera": (
        "Valvottuja öitä on liian vähän tämän illan arvioon. Avaa sovellus, niin näet, mitä kamerat"
        " näkivät."
    ),
    "plan.species_hours": "{species}, parhaat tunnit {start}–{end}.",
    "held.one": "{name}: {visits} ({cameras})",
    "held.each": "{name}: {visits}",
    "held.worth_a_look": {
        "one": "{n} kuva merkitty katsomisen arvoiseksi",
        "other": "{n} kuvaa merkitty katsomisen arvoisiksi",
    },
    "held.title.sit": "Passissa ollessasi",
    "held.title.quiet": "Hiljaisten tuntiesi aikana",
    "held.body": "{parts}, viimeisin {when}.",

    # ---- alert settings ------------------------------------------------------
    "alerts.unknown_camera": "Tuntematon kamera: {ids}",
    "alerts.unknown_species": "Tuntematon laji: {ids}",
    "alerts.quiet_needs_both": "Hiljaisille tunneille tarvitaan alku ja loppu.",
    "alerts.quiet_same": "Hiljaiset tunnit eivät voi alkaa ja loppua samaan aikaan.",
    "alerts.endpoint_https": "Push-osoitteen on oltava https-osoite",
    "alerts.no_phone": (
        "Yksikään puhelin ei vielä saa ilmoituksia. Laita ilmoitukset ensin päälle siitä "
        "puhelimesta."
    ),
    "alerts.test_title": "Testi-ilmoitus",
    "alerts.test_body": "Ilmoitukset toimivat tässä puhelimessa.",

    # ---- team notes and people -----------------------------------------------
    "notes.bad_chars": (
        "Muistiinpanossa on merkkejä, joita ei voi tallentaa. Kirjoita se uudelleen."
    ),
    "notes.too_long": "Pidä muistiinpano enintään {n} merkissä.",
    "notes.push_title": "Kannattaa katsoa: {label}, kamera {camera}",
    "notes.push_body": "{name}: {text}",
    "notes.push_marked": "{name} merkitsi kuvan",
    "notes.empty_frame": "Tämä kuva on merkitty tyhjäksi. Pidä se ensin eläinkuvana.",
    "notes.hidden_only": (
        "Kuvassa on vain sovelluksesta piilotettuja eläimiä, joten porukka ei näe sitä."
    ),
    "notes.people_only": (
        "Kuvassa on ihminen tai ajoneuvo, joten se jää ylläpitäjille eikä porukka näe sitä."
    ),
    "notes.not_looked": (
        "Sovellus ei ole vielä tarkistanut tätä kuvaa, joten porukka ei näe sitä. Yritä muutaman "
        "minuutin päästä uudelleen."
    ),
    "notes.photo_not_found": "Kuvaa ei löydy.",
    "notes.viewer": "Katselijat näkevät muistiinpanot mutta eivät voi lisätä niitä.",
    "notes.not_saved": "Muistiinpanoa ei voitu tallentaa. Sulje se ja yritä uudelleen.",
    "notes.gone": "Muistiinpano on jo poistettu.",
    "notes.remove_forbidden": "Vain kirjoittaja tai ylläpitäjä voi poistaa muistiinpanon.",
    "people.hunter": "Metsästäjä",
    "people.removed": "Poistettu henkilö",
    "crash.too_large": "Raportti on liian suuri",
    "crash.not_a_report": "Tämä ei ole kaatumisraportti.",
    "crash.too_many": "Liikaa raportteja. Myöhemmät hylätään.",
    "crash.unknown_device": "Tuntematon laite",

    # ---- stands and sits -----------------------------------------------------
    "stands.no_estate": "Määritä alue ensin.",
    "stands.auto_name": "Passi {camera}",
    "stands.auto_note": (
        "Jokainen passi on sijoitettu kameransa kohdalle. Siirrä se sinne, missä oikeasti istut. "
        "Tuulineuvot alkavat, kun merkitset suunnat, joista eläimet tulevat."
    ),
    "stands.camera_gone": "Kameraa ei ole sovelluksessa.",
    "stands.gone": "Passia ei ole sovelluksessa.",
    "stands.has_sits": {
        "one": (
            "Passille on kirjattu {n} istunto. Sen poistaminen pyyhkisi historian. Nimeä se "
            "mieluummin uudelleen."
        ),
        "other": (
            "Passille on kirjattu {n} istuntoa. Sen poistaminen pyyhkisi historian. Nimeä se "
            "mieluummin uudelleen."
        ),
    },
    "stands.claimed": "Toinen metsästäjä on jo varannut passin {stand} tälle illalle.",
    "stands.arc_conflict": (
        "Passeilla {stand} ja {other} on yhteinen ampumasektori, ja {other} on varattu tälle "
        "illalle. Valitse toinen passi."
    ),
    "stands.viewer": "Katselijat näkevät passit mutta eivät voi varata niitä.",
    "sits.gone": "Istuntoa ei ole sovelluksessa.",
    "sits.viewer": "Katselijat näkevät istunnot mutta eivät voi muuttaa niitä.",
    "sits.not_yours": "Istunto on toisen metsästäjän.",
    "sits.bad_outcome": "tuloksen on oltava jokin näistä: {outcomes}",
    "sits.cancelled": "Varaus peruttiin. Varaa passi uudelleen.",
    "sits.already_reported": "Olet jo kertonut, mitä istunnossa tapahtui.",
    "sits.not_started": "Istunto ei ole alkanut.",

    # ---- approach lines and the dark exit ------------------------------------
    "arcs.no_camera": "Passia ei ole liitetty kameraan.",
    "arcs.camera_unplaced": "Liitetyllä kameralla ei ole tallennettua sijaintia.",
    "arcs.no_others": "Muita sijoitettuja kameroita ei ole, joista liikettä voisi päätellä.",
    "arcs.note": {
        "one": (
            "{n} kerran eläimet tulivat kameralle {camera} {minutes} min sisällä siitä, kun ne "
            "ohittivat kameran {other}."
        ),
        "other": (
            "{n} kertaa eläimet tulivat kameralle {camera} {minutes} min sisällä siitä, kun ne "
            "ohittivat kameran {other}."
        ),
    },
    "arcs.none": (
        "Kameroiden välillä ei ole vielä toistuvaa liikettä — ei tarpeeksi tulosuunnan "
        "ehdottamiseen, joten sovellus jättää tämän edelleen sinun ratkaistavaksesi."
    ),
    "exit.no_visits": "Passin kameralla ei ole vielä käyntejä.",
    "exit.quiet": (
        "Poistu pimeässä klo {time} — vain {pct} % tämän kameran käynneistä osuu seuraavaan "
        "tuntiin, joten silloin lähteminen häiritsee vähiten."
    ),
    "exit.busy_reason": "Ei todella hiljaista tuntia — tällä passilla on vilkasta koko yön.",
    "exit.busy": (
        "Ei hiljaista tuntia klo {after} jälkeen tällä passilla — vilkasta koko yön. Klo {time} on "
        "vähiten huono lähtöaika."
    ),

    # ---- the harvest book ----------------------------------------------------
    "harvest.sex.male": "Uros",
    "harvest.sex.female": "Naaras",
    "harvest.sex.unknown": "Ei varma",
    "harvest.age.juvenile": "Tämän vuoden poikanen",
    "harvest.age.young_adult": "Nuori aikuinen",
    "harvest.age.mature_adult": "Aikuinen",
    "harvest.age.old": "Vanha",
    "harvest.age.unknown": "Ei varma",
    "harvest.viewer": "Katselijat eivät voi kirjata saalista.",
    "harvest.not_yours": "Saalis on toisen metsästäjän. Ylläpitäjä voi muuttaa sitä.",
    "harvest.not_a_shot": "Istuntoa ei ole ilmoitettu laukaukseksi. Kerro ensin, mitä tapahtui.",
    "harvest.field.seal": "merkin numero",
    "harvest.field.note": "muistiinpano",
    "harvest.field.name": "nimi",
    "harvest.hidden_chars": "Kentässä ”{what}” on piilomerkkejä. Kirjoita se uudelleen.",
    "harvest.too_long": "Kentässä ”{what}” voi olla enintään {n} merkkiä.",
    "harvest.bad_species": "Valitse jokin luettelon eläimistä.",
    "harvest.bad_sex": "Sukupuoli on uros, naaras tai ei varma.",
    "harvest.bad_age": "Valitse ikä luettelosta.",
    "harvest.future": "Aika on vielä tulevaisuudessa. Tarkista päivämäärä.",
    "harvest.too_old": "Päivämäärä on liian kaukana menneisyydessä. Tarkista vuosi.",
    "harvest.bad_season": "Valitse kausi luettelosta.",
    "harvest.not_saved": "Saalista ei voitu tallentaa. Sulje se ja yritä uudelleen.",
    "harvest.gone": "Saalis ei ole enää kirjassa.",
    "harvest.admin_names": "Vain ylläpitäjä voi muuttaa saaliin nimeä.",
    "harvest.col.date": "Päivämäärä",
    "harvest.col.time": "Aika",
    "harvest.col.species": "Laji",
    "harvest.col.sex": "Sukupuoli",
    "harvest.col.age": "Ikä",
    "harvest.col.seal": "Merkin numero",
    "harvest.col.weight": "Paino (kg)",
    "harvest.col.hunter": "Metsästäjä",
    "harvest.col.stand": "Passi",
    "harvest.col.notes": "Muistiinpanot",

    # ---- the activity map ----------------------------------------------------
    "activity.part.dusk": "illan hämärissä",
    "activity.part.night": "keskellä yötä",
    "activity.part.dawn": "aamun hämärissä",
    "activity.checking_last": "Viime yön kuvia tarkistetaan vielä.",
    "activity.checking": "Kuvia tarkistetaan vielä.",
    "activity.unreadable_last": "Ei laskettu: kaikkia viime yön kuvia ei voitu tarkistaa.",
    "activity.unreadable": "Ei laskettu: kaikkia kuvia ei voitu tarkistaa.",
    "activity.blind_last": "Ei laskettu: kamera ei ehkä toiminut viime yönä.",
    "activity.blind": "Ei laskettu: kamera ei toiminut näinä öinä.",
    "activity.tail.times": ", klo {times}",
    "activity.tail.mostly": ", enimmäkseen klo {peak}",
    "activity.tail.busiest": ", vilkkaimmin klo {peak}",
    "activity.tail.no_set_time": ", ei tiettyyn aikaan",
    "activity.last_night": "viime yönä",
    "activity.last_night_so_far": "viime yönä tähän mennessä",
    "activity.one.nothing_all": "Kamerassa ei mitään{when} {night}.",
    "activity.one.nothing": "Ei havaintoja{when} {night}: {species}.",
    "activity.one.visits_all": {
        "one": "{n} eläinkäynti{when} {night}{tail}",
        "other": "{n} eläinkäyntiä{when} {night}{tail}",
    },
    "activity.one.visits": {
        "one": "{n} käynti{when} {night}: {species}{tail}",
        "other": "{n} käyntiä{when} {night}: {species}{tail}",
    },
    "activity.q.working": " (kun kamera toimi)",
    "activity.q.checkable": " (jotka voitiin tarkistaa)",
    "activity.q.so_far": " (tähän mennessä tarkistetut)",
    "activity.none_all": {
        "one": "Ei eläimiä{when} {n} yönä{qualifier}.",
        "other": "Ei eläimiä{when} {n} yönä{qualifier}.",
    },
    "activity.none": {
        "one": "Ei havaintoja{when} {n} yönä{qualifier}: {species}.",
        "other": "Ei havaintoja{when} {n} yönä{qualifier}: {species}.",
    },
    "activity.some": "{who}: {n}/{total} yönä{qualifier}{tail}",

    # ---- the map -------------------------------------------------------------
    "map.bad_nights": "Öitä voi olla 1, 7 tai 30.",
    "map.no_species": "Lajia ei ole.",
    "map.no_replay": "Tälle yölle ei ole toistoa.",

    # ---- insights: what moves the animals ------------------------------------
    "class.animals_all": "Kaikki eläimet",
    "patterns.moon_illum.label": "Kuunvalo",
    "patterns.moon_illum.high": "kirkas kuu",
    "patterns.moon_illum.low": "pimeä kuu",
    "patterns.pressure.label": "Ilmanpaine",
    "patterns.pressure.high": "korkea paine",
    "patterns.pressure.low": "matala paine",
    "patterns.pressure_trend.label": "Paineen suunta",
    "patterns.pressure_trend.high": "nouseva paine",
    "patterns.pressure_trend.low": "laskeva paine",
    "patterns.temp.label": "Lämpötila",
    "patterns.temp.high": "lämmin sää",
    "patterns.temp.low": "viileä sää",
    "patterns.wind.label": "Tuuli",
    "patterns.wind.high": "tuulinen",
    "patterns.wind.low": "tyyni",
    "patterns.rain.label": "Sade",
    "patterns.rain.high": "sade",
    "patterns.rain.low": "poutasää",
    "patterns.cloud.label": "Pilvisyys",
    "patterns.cloud.high": "pilvinen",
    "patterns.cloud.low": "selkeä taivas",
    "patterns.darkness.label": "Pimeät tunnit",
    "patterns.darkness.high": "pitkä yö",
    "patterns.darkness.low": "lyhyt yö",
    "patterns.statement": "{hi_desc}: noin {hi} käyntiä yössä; {lo_desc}: noin {lo}.",
    "insights.midnight": "keskiyö",
    "insights.busiest": "Kamerasi ovat vilkkaimmillaan {start}–{end}.",
    "insights.species_mostly": "Kamerat näkevät lajia {species} enimmäkseen {start}–{end}.",
    "insights.concentrated": (
        "Suurin osa liikkeestä on kameroilla {cameras}. Muut kamerat näkevät paljon vähemmän."
    ),
    "insights.busiest_cameras": "{cameras} ovat vilkkaimmat kamerasi.",
    "insights.class_missing": "Valitse, mitkä eläimet näytetään.",

    # ---- species in Settings -------------------------------------------------
    "species.name_hidden_chars": "Nimessä on piilomerkkejä. Kirjoita se uudelleen.",
    "species.name_length": "Nimessä on oltava 1–40 merkkiä.",
    "species.not_found": "Lajia ei löydy.",

    # ---- the alerts feed on Tonight ------------------------------------------
    "ago.unknown": "ei tiedossa",
    "ago.just_now": "juuri nyt",
    "ago.ago": "{span} sitten",
    "ago.m": "{n} min",
    "ago.h": "{n} t",
    "ago.d": "{n} pv",
    "feed.seen": {
        "one": "Nähty {n} kerran 2 viime päivän aikana, viimeksi {ago}.",
        "other": "Nähty {n} kertaa 2 viime päivän aikana, viimeksi {ago}.",
    },
    "feed.battery_title": "{camera}: akku vähissä",
    "feed.battery": "{pct} % jäljellä. Ota paristoja mukaan seuraavalla käynnillä.",
    "feed.since": ", yöstä {day} lähtien",
    "feed.quiet_title": "{camera}: hiljaista",
    "feed.quiet": {
        "one": (
            "Ei mitään {n} viimeisenä valvottuna yönä{since}. Siellä käy yleensä {usual} kertaa "
            "yössä."
        ),
        "other": (
            "Ei mitään {n} viimeisenä valvottuna yönä{since}. Siellä käy yleensä {usual} kertaa "
            "yössä."
        ),
    },

    # ---- the week's wind -----------------------------------------------------
    "week.tonight": "Tänään",
    "week.tonight_hours": "tänään {hours}",
    "week.no_position": "Passi {stand} ei ole vielä kartalla, joten sen tuulta ei voi arvioida.",
    "week.no_bedding": (
        "Makuupaikkoja ei ole vielä piirretty, joten tuulta ei voi arvioida passille {stand}."
    ),
    "week.no_geometry": (
        "Passille {stand} ei ole merkitty tulosuuntia, joten arvioi sen tuuli itse."
    ),
    "week.no_forecast": "Viikon tuuliennustetta ei vielä ole.",
    "week.right": "Oikea tuuli passille {stand}: {when}",
    "week.none": "Passille {stand} ei ole oikeaa tuulta tällä viikolla.",

    # ---- the track record ----------------------------------------------------
    "record.too_few": {
        "one": "{n} yö tarkistettu tähän mennessä. Osumatarkkuus näkyy {needed} yön jälkeen.",
        "other": "{n} yötä tarkistettu tähän mennessä. Osumatarkkuus näkyy {needed} yön jälkeen.",
    },
    "record.verdict": {
        "one": "Kun arvio oli ”{verdict}”, eläimiä tuli paikalle {came}/{n} kertaa.",
        "other": "Kun arvio oli ”{verdict}”, eläimiä tuli paikalle {came}/{n} kertaa.",
    },
    "record.beats": (
        "Sen todennäköisyydet osuivat lähemmäs toteutunutta kuin kunkin kameran tavallinen taso."
    ),
    "record.no_better": (
        "Sen todennäköisyydet eivät osuneet lähemmäs toteutunutta kuin kunkin kameran tavallinen "
        "taso."
    ),
    "record.too_few_each": {
        "one": "{n} yö tarkistettu, liian vähän minkään yksittäisen arvion osalta sanottavaksi.",
        "other": (
            "{n} yötä tarkistettu, liian vähän minkään yksittäisen arvion osalta sanottavaksi."
        ),
    },

    # ---- photos and animals --------------------------------------------------
    "images.viewer": "Katselijat voivat katsoa kuvia mutta eivät muuttaa niitä.",
    "images.old_link": "Kuvalinkki on vanhentunut. Avaa kuva uudelleen sovelluksessa.",
    "images.sign_in": "Kirjaudu, niin näet kuvat.",
    "images.no_picture": "Tästä kuvasta ei ole vielä tiedostoa, joten korjattavaa ei ole.",
    "images.no_people": "Sovellus ei laske tässä kuvassa ketään muutenkaan.",
    "animals.not_found": "Eläintä ei löydy.",
    "animals.gone": "Eläintä ei ole enää sovelluksessa.",
    "animals.name_first": "Kirjoita ensin nimi.",
    "animals.name_long": "Nimi voi olla enintään 60 merkkiä.",
    "animals.bad_status": "tilan on oltava jokin näistä: {statuses}",
    "animals.merge_target": "Eläintä, johon yhdistetään, ei löytynyt.",
    "animals.reid_running": "Etsitään jo. Tämä kestää muutaman minuutin.",
    "animals.reid_started": "Etsitään toistuvia vierailijoita. Tämä kestää muutaman minuutin.",

    # ---- areas on the map, and admin -----------------------------------------
    "zones.name_needed": "Anna nimi, jonka porukka tuntee.",
    "zones.name_not_empty": "Nimen voi vaihtaa, mutta sitä ei voi jättää tyhjäksi.",
    "zones.outline_not_empty": "Rajausta voi muuttaa, mutta sitä ei voi jättää tyhjäksi.",
    "zones.bad_kind": "tyypin on oltava jokin näistä: {kinds}",
    "zones.gone": "Aluetta ei ole kartalla.",
    "admin.deploying": "Palvelin asentaa päivitystä. Yritä muutaman minuutin päästä uudelleen.",
    "admin.no_api_key": "Lisää ensin ANTHROPIC_API_KEY tiedostoon .env",
    "admin.labelling": "Merkitään jo. Merkinnät näkyvät muutaman minuutin kuluessa.",
    "admin.labels_coming": "Merkinnät näkyvät Kameroissa muutaman minuutin kuluessa.",
    "admin.retry": {
        "one": "{n} kuva tarkistetaan uudelleen seuraavalla haulla.",
        "other": "{n} kuvaa tarkistetaan uudelleen seuraavalla haulla.",
    },
    "admin.nothing_to_retry": "Ei mitään yritettävää uudelleen.",
    "admin.reload": (
        "Lataa sovellus uudelleen: päivitykset näkyvät nyt itsestään kohdassa Sovelluksen versio."
    ),

    # ---- server upkeep (kept in English, said in the reader's language) ------
    "restore.no_table": "Palautetussa kopiossa ei ole taulua {table}.",
    "restore.no_rows": "Palautetun kopion taulussa {table} ei ole rivejä.",
    "restore.photos_missing": (
        "{n}/{total} tarkistetusta kuvasta puuttuu varmuuskopion kuvakansiosta."
    ),
    "restore.failed": "Tarkistusta ei voitu ajaa ({error}).",
    "ops.unreadable": "Sen tilatiedostoa ei voi lukea.",

    # ---- drawing on the map --------------------------------------------------
    "shape.not_polygon": "Rajauksen on oltava GeoJSON-monikulmio.",
    "shape.no_corners": "Rajauksessa ei ole kulmia.",
    "shape.too_many": "Rajauksessa on {n} kulmaa. Pidä kulmia alle {limit}.",
    "shape.two_numbers": "Jokaisen kulman on oltava kaksi lukua: pituusaste ja sitten leveysaste.",
    "shape.off_map": (
        "Kulma on kartan ulkopuolella. Kulmat annetaan pituusaste ensin, sitten leveysaste."
    ),
    "shape.three": "Napauta vähintään kolme kulmaa alueen ympärille.",
    "shape.too_big": "Rajaus on yli 20 km leveä. Piirrä vain suoja, jossa eläimet makaavat.",
    "shape.crosses": "Rajaus leikkaa itsensä. Aseta kulmat järjestykseen reunaa pitkin.",
    "shape.no_area": "Rajauksella ei ole juuri pinta-alaa. Levitä kulmat suojan ympärille.",
    "box.four_numbers": "Rajaus tarvitsee neljä lukua: etelä, länsi, pohjoinen ja itä.",
    "box.off_map": "Rajaus on kartan ulkopuolella.",
    "box.too_big": (
        "Se on {km} km leveä, enemmän kuin puhelimen kannattaa tallentaa. Lähennä niin, että alue "
        "on alle {limit} km leveä."
    ),
    "box.too_small": "Se on liian pieni koko alueeksi. Loitonna hieman.",
    "terrain.busy": "Korkeuspalvelu on kiireinen. Yritä muutaman minuutin päästä uudelleen.",
    "terrain.down": "Korkeuspalvelu ei vastannut. Yritä myöhemmin uudelleen.",

    # ---- signing in, too many tries ------------------------------------------
    "count.minutes": {
        "one": "{n} minuutin",
        "other": "{n} minuutin",
    },
    "throttle.place": "Liian monta väärää salasanaa tästä verkosta. Yritä uudelleen {wait} päästä.",
    "throttle.at_once": (
        "Liian monta kirjautumista tästä verkosta yhtä aikaa. Yritä muutaman sekunnin päästä "
        "uudelleen."
    ),
    "throttle.checking": (
        "Edellistä yritystäsi tarkistetaan vielä. Yritä muutaman sekunnin päästä uudelleen."
    ),
    "throttle.email": {
        "one": (
            "Liian monta väärää salasanaa tälle sähköpostille. Yritä uudelleen {n} sekunnin päästä."
        ),
        "other": (
            "Liian monta väärää salasanaa tälle sähköpostille. Yritä uudelleen {n} sekunnin päästä."
        ),
    },
    "throttle.email_lately": (
        "Liian monta väärää salasanaa tälle sähköpostille viime aikoina. Yritä uudelleen {wait} "
        "päästä tai puhelimella, jolla sillä on kirjauduttu aiemmin."
    ),

    # ---- the stag/hind labelling pass (kept in English, said in the reader's language) ----
    "sexpass.key_refused": (
        "Anthropic hylkäsi API-avaimen. Tarkista ANTHROPIC_API_KEY palvelimen .env-tiedostosta."
    ),
    "sexpass.no_credit": (
        "Anthropic-tilin saldo on lopussa. Lisää saldoa, niin urokset ja naaraat merkitään taas."
    ),
    "sexpass.no_model": (
        "Anthropic ei tunne mallia {model}. Pyydä palvelimen ylläpitäjää päivittämään se."
    ),
    "sexpass.limited": "Anthropic rajoittaa pyyntöjä juuri nyt. Uusi yritys seuraavalla tunnilla.",
    "sexpass.unreachable": "Anthropiciin ei saatu yhteyttä. Uusi yritys seuraavalla tunnilla.",
    "sexpass.http": "Anthropicilla oli ongelma (HTTP {status}). Uusi yritys seuraavalla tunnilla.",
    "sexpass.bad_answer": "Anthropic ei vastannut kunnolla. Uusi yritys seuraavalla tunnilla.",

    # ---- Look for repeats (kept in English, said in the reader's language) ----
    "reid.failed": "Jokin meni vikaan ({error}).",
    "reid.stopped": (
        "Se pysähtyi kesken: palvelin oli varattuna liian kauan. Napauta uudelleen, niin se jatkaa "
        "loppuun."
    ),

    # ---- the moon ------------------------------------------------------------
    "moon.new_moon": "Uusikuu",
    "moon.waxing_crescent": "Kasvava sirppi",
    "moon.first_quarter": "Ensimmäinen neljännes",
    "moon.waxing_gibbous": "Kasvava kuu",
    "moon.full_moon": "Täysikuu",
    "moon.waning_gibbous": "Vähenevä kuu",
    "moon.last_quarter": "Viimeinen neljännes",
    "moon.waning_crescent": "Vähenevä sirppi",
}
