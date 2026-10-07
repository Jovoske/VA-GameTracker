"""Spanish (español): what the server says. The same keys and placeholders as en.py
(tests/test_i18n.py); a key missing here would be said in English.

Spanish hunters' words: jabalí, ciervo, corzo, gamo, comedero, puesto,
torreta, aguardo.
"""

MESSAGES: dict[str, str | dict[str, str]] = {
    # ---- lists and the calendar ----------------------------------------------
    "list.two": "{a} y {b}",
    "list.three": "{a}, {b} y {c}",
    "list.more": "{a}, {b} y {n} más",
    "cal.wd.0": "lun",
    "cal.wd.1": "mar",
    "cal.wd.2": "mié",
    "cal.wd.3": "jue",
    "cal.wd.4": "vie",
    "cal.wd.5": "sáb",
    "cal.wd.6": "dom",
    "cal.wdl.0": "lunes",
    "cal.wdl.1": "martes",
    "cal.wdl.2": "miércoles",
    "cal.wdl.3": "jueves",
    "cal.wdl.4": "viernes",
    "cal.wdl.5": "sábado",
    "cal.wdl.6": "domingo",
    "cal.mon.1": "ene",
    "cal.mon.2": "feb",
    "cal.mon.3": "mar",
    "cal.mon.4": "abr",
    "cal.mon.5": "may",
    "cal.mon.6": "jun",
    "cal.mon.7": "jul",
    "cal.mon.8": "ago",
    "cal.mon.9": "sept",
    "cal.mon.10": "oct",
    "cal.mon.11": "nov",
    "cal.mon.12": "dic",
    "cal.monl.1": "enero",
    "cal.monl.2": "febrero",
    "cal.monl.3": "marzo",
    "cal.monl.4": "abril",
    "cal.monl.5": "mayo",
    "cal.monl.6": "junio",
    "cal.monl.7": "julio",
    "cal.monl.8": "agosto",
    "cal.monl.9": "septiembre",
    "cal.monl.10": "octubre",
    "cal.monl.11": "noviembre",
    "cal.monl.12": "diciembre",
    "cal.day_month": "{day} {month}",
    "cal.wd_day_month": "{wd} {day} {month}",

    # ---- species and what an animal is ---------------------------------------
    "species.bison": "Bisonte",
    "species.badger": "Tejón",
    "species.ibex": "Cabra montés",
    "species.beaver": "Castor",
    "species.red_deer": "Ciervo",
    "species.chamois": "Rebeco",
    "species.cat": "Gato",
    "species.goat": "Cabra",
    "species.roe_deer": "Corzo",
    "species.dog": "Perro",
    "species.fallow_deer": "Gamo",
    "species.squirrel": "Ardilla",
    "species.moose": "Alce",
    "species.equid": "Caballo o burro",
    "species.genet": "Gineta",
    "species.wolverine": "Glotón",
    "species.hedgehog": "Erizo",
    "species.lagomorph": "Liebre o conejo",
    "species.wolf": "Lobo",
    "species.otter": "Nutria",
    "species.lynx": "Lince",
    "species.marmot": "Marmota",
    "species.micromammal": "Ratón o rata",
    "species.mouflon": "Muflón",
    "species.sheep": "Oveja",
    "species.mustelid": "Garduña o comadreja",
    "species.bird": "Ave",
    "species.bear": "Oso",
    "species.nutria": "Coipú",
    "species.raccoon": "Mapache",
    "species.fox": "Zorro",
    "species.reindeer": "Reno",
    "species.wild_boar": "Jabalí",
    "species.cow": "Vaca",
    "class.stag": "Venado",
    "class.hind": "Cierva",
    "class.hind_calf": "Cierva + cría",
    "class.boar": "Jabalí macho",
    "class.sow": "Jabalina",
    "class.sow_piglets": "Jabalina + rayones",
    "class.sounder": "Piara",
    "class.herd": "{name} (manada)",
    "class.animal": "Animal",
    "class.animals": "Animales",

    # ---- signing in ----------------------------------------------------------
    "auth.not_authenticated": "No has iniciado sesión",
    "auth.bad_credentials": "Credenciales de acceso no válidas",
    "auth.token_invalid": "Sesión no válida o caducada",
    "auth.token_subject": "Identificador de sesión no válido",
    "auth.user_not_found": "Usuario no encontrado",
    "auth.signed_out": "Se ha cerrado tu sesión. Vuelve a entrar.",
    "auth.admin_only": "Solo el administrador del coto puede hacer eso.",
    "auth.busy": "El servidor está ocupado. Inténtalo de nuevo en un minuto.",
    "auth.wrong_password": "Correo o contraseña incorrectos",
    "auth.published": (
        "Esa es la contraseña publicada con GameSense, así que no puede entrar desde internet. "
        "Entra desde la red del propio servidor y cámbiala en Ajustes, o ejecuta en el servidor: "
        "python -m app.manage set-password {email}"
    ),
    "auth.language_unknown": "Elige English, Suomi, Svenska, Norsk o Español.",
    "auth.not_current_password": "Esa no es tu contraseña actual",
    "auth.new_password_short": "La nueva contraseña debe tener al menos 8 caracteres",
    "auth.password_changed": (
        "Contraseña cambiada. Todos los demás teléfonos con tu sesión tendrán que volver a entrar."
    ),

    # ---- people on the app ---------------------------------------------------
    "users.email_invalid": "Escribe un correo válido",
    "users.password_short": "La contraseña debe tener al menos 8 caracteres",
    "users.pick_role": "Elige Miembro o Administrador",
    "users.email_taken": "Alguien con ese correo ya tiene acceso",
    "users.gone": "Esa persona ya no está en la app.",
    "users.not_yourself": "No puedes quitarte a ti mismo",
    "users.keep_admin": "Tiene que quedar al menos un administrador",
    "users.remove_failed": (
        "No se pudo quitar a {email}: algo en la app todavía apunta a esa persona. No se ha "
        "cambiado nada. Inténtalo de nuevo o pregunta a quien lleva el servidor."
    ),
    "users.removed": "{email} ya no puede entrar. Lo que registró se conserva.",
    "users.logins_moved": {
        "one": "{n} cuenta de cámara que añadió sigue trayendo fotos, ahora a tu nombre.",
        "other": "{n} cuentas de cámara que añadió siguen trayendo fotos, ahora a tu nombre.",
    },

    # ---- Tonight -------------------------------------------------------------
    "time.hours": "{h} h",
    "time.clock": "{h} h",
    "time.minutes": "{m} min",
    "sun.at_sunset": "la puesta de sol",
    "sun.after": "{span} después de la puesta de sol",
    "sun.before": "{span} antes de la puesta de sol",
    "tonight.factor.not_sending": {
        "one": "La cámara no está enviando fotos ahora. Se basa en {n} noche de historial.",
        "other": "La cámara no está enviando fotos ahora. Se basa en {n} noches de historial.",
    },
    "tonight.factor.unchecked": (
        "Todavía se están revisando las fotos de {n} de las últimas 7 noches. Se basa en su "
        "historial."
    ),
    "tonight.factor.few_watched": (
        "Solo {n} de las últimas 7 noches vigiladas aquí. Se basa en su historial."
    ),
    "tonight.factor.not_watched": " ({n} sin vigilar)",
    "tonight.factor.seen_week": "{species}: {n} de las últimas 7 noches aquí{gap}",
    "tonight.factor.none_week": "Sin rastro de {species} aquí en las últimas 7 noches{gap}",
    "tonight.factor.outside_hours": (
        "{species}: solo se ve aquí fuera de las horas de espera, así que no hay mejores horas que "
        "dar"
    ),
    "tonight.best_hours": "Mejores horas de {start} a {end}",
    "tonight.best_hours_from": "Mejores horas de {start} a {end}, desde {relative}",
    "tonight.left_out.unchecked_n": "{n} con fotos aún sin revisar",
    "tonight.left_out.unchecked": "fotos aún sin revisar",
    "tonight.left_out.blind_n": "{n} en que quizá la cámara no vigilaba",
    "tonight.left_out.blind": "quizá la cámara no vigilaba",
    "tonight.left_out": {
        "one": "{n} noche en {camera} no contada: {why}.",
        "other": "{n} noches en {camera} no contadas: {why}.",
    },
    "tonight.alert.silent": (
        "Sin fotos desde hace {n} días, así que queda fuera del orden de esta noche"
    ),
    "tonight.none.picked": "Ninguna cámara ha visto todavía los animales que elegiste.",
    "tonight.none.sending": "Las cámaras que envían fotos aún no han visto animales.",
    "tonight.none.yet": "Todavía no hay avistamientos.",
    "tonight.reason": "{species}: {n} de {total} noches en esta cámara.",
    "tonight.caveat": (
        "La cámara vigila toda la noche. Tú estarás unas horas, así que elige las mejores horas y "
        "ojo con el viento."
    ),

    # ---- wind ----------------------------------------------------------------
    "compass.N": "N",
    "compass.NE": "NE",
    "compass.E": "E",
    "compass.SE": "SE",
    "compass.S": "S",
    "compass.SW": "SO",
    "compass.W": "O",
    "compass.NW": "NO",
    "wind.reading": "Viento {dir} {speed} km/h",
    "wind.no_forecast": "No hay previsión de viento esta noche. Compruébalo tú.",
    "wind.no_forecast_stand": (
        "No hay previsión de viento esta noche. Compruébalo tú antes de ponerte en {stand}."
    ),
    "wind.no_position": (
        "{reading}. {stand} aún no está en el mapa, así que no se puede calcular adónde va tu olor."
    ),
    "wind.no_bedding": (
        "{reading}. Aún no hay encames dibujados, así que no se puede calcular dónde cae tu olor. "
        "Dibuja en el mapa dónde se encaman."
    ),
    "wind.no_stand": (
        "{reading}. Aún no hay puesto cerca de {camera}, así que no se puede juzgar para un sitio. "
        "Júzgalo tú."
    ),
    "wind.arcs.too_light": (
        "Viento {dir} {speed} km/h, demasiado flojo para decir nada. Mandan las térmicas. "
        "Compruébalo en el coche."
    ),
    "wind.arcs.no_geometry": (
        "Viento {dir} {speed} km/h. {stand} no tiene direcciones de entrada puestas, así que juzga "
        "tú el viento."
    ),
    "wind.arcs.divert": " Mejor ponte en {stand}.",
    "wind.arcs.wrong": (
        "Viento {dir} {speed} km/h, malo para {stand}. Tu olor va directo a la entrada del "
        "{approach}.{divert}"
    ),
    "wind.arcs.clean": (
        "Viento {dir} {speed} km/h, bueno para {stand}. Tu olor va hacia el {scent}, lejos de por "
        "donde entran."
    ),

    # ---- slope wind and bedding ----------------------------------------------
    "thermal.no_terrain": (
        "No hay modelo del terreno cargado, así que no se puede calcular el viento de ladera."
    ),
    "thermal.off_terrain": (
        "Este sitio queda fuera del relieve cargado, así que no se puede calcular el viento de "
        "ladera. Un administrador puede volver a cargar el relieve para que lo cubra."
    ),
    "thermal.flat": "Aquí el terreno es casi llano. No hay ladera por la que baje el aire frío.",
    "thermal.overcast": (
        "Cubierto ({pct} %), así que el viento de ladera será flojo esta noche. Compruébalo tú."
    ),
    "thermal.katabatic": (
        "La previsión es de calma, así que manda la ladera. El aire frío baja hacia el {dir} a unos"
        " {speed} km/h. Tu olor va con él."
    ),
    "thermal.katabatic_settling": (
        "La previsión es de calma, así que manda la ladera. El aire frío baja hacia el {dir} a unos"
        " {speed} km/h. Todavía se está asentando al anochecer y puede rolar. Tu olor va con él."
    ),
    "thermal.anabatic": (
        "Calma y sol, así que el aire sube por la ladera hacia el {dir}. Se dará la vuelta y bajará"
        " hacia la puesta de sol."
    ),
    "bedding.no_position": "{stand} aún no tiene posición en el mapa.",
    "bedding.none": (
        "Aún no hay encames dibujados — dibuja dónde se encaman y esto se convierte en consejo."
    ),
    "bedding.too_light": "Viento {dir} {speed} km/h — demasiado flojo para decir nada. {why}",
    "bedding.thermals_decide": "Aquí mandan las térmicas; léelas en el coche.",
    "bedding.lead.katabatic": (
        "Previsión de calma, así que manda la ladera — el aire frío baja hacia el {dir} a ~{speed} "
        "km/h{fall}"
    ),
    "bedding.fall": " ({pct} % de pendiente)",
    "bedding.lead.anabatic": (
        "Calma y sol — el aire sube ladera arriba hacia el {dir} a ~{speed} km/h"
    ),
    "bedding.caveat.dusk": " Se da la vuelta al anochecer, así que compruébalo sobre el terreno.",
    "bedding.caveat.dem": " Un modelo del terreno de ~90 m ve la ladera, no tu barranco.",
    "bedding.into_own": "al encame {zone}, en el que está tu puesto",
    "bedding.into_near": "al encame {zone} a {m} m",
    "bedding.into_far": "al encame {zone}, a {m} m",
    "bedding.carries.thermal": "{lead}, y lleva tu olor {where}.{caveat}",
    "bedding.carries.wind": "{lead} — tu olor va hacia el {dir} {where}.",
    "bedding.clean.thermal": "{lead}, lejos de los encames ({m} m al más cercano).{caveat}",
    "bedding.clean.wind": (
        "{lead} — limpio. El olor va hacia el {dir}, lejos de los encames ({m} m al más cercano)."
    ),
    "bedding.draw": "Dibuja los encames para ver esto.",
    "bedding.no_forecast": "No hay previsión de viento esta noche.",
    "bedding.too_light_map": (
        "Viento demasiado flojo para cartografiar — una tarde así mandan las térmicas."
    ),
    "bedding.safe.note": (
        "Solo geometría — no sabe nada de cobertura, accesos ni de un tiro seguro con buen fondo. "
        "Acota dónde buscar; no elige el puesto."
    ),
    "bedding.safe.note_calm": (
        "La previsión es de calma, así que esto sigue el terreno: cada cuadro usa su propia línea "
        "de máxima pendiente, porque el aire frío baja al oscurecer. Un modelo del terreno de ~90 m"
        " ve la ladera, no el barranco en el que estás."
    ),

    # ---- what changed --------------------------------------------------------
    "num.decimal_mark": ",",
    "count.visits": {
        "one": "{n} visita",
        "other": "{n} visitas",
    },
    "changed.about": "unas {x}",
    "changed.no_cameras": "Aún no hay cámaras.",
    "changed.camera_down": "{camera} no envió nada anoche. No se sabe si pasó algo.",
    "changed.return": {
        "one": "Vuelven los animales a {camera} tras {n} noche tranquila.",
        "other": "Vuelven los animales a {camera} tras {n} noches tranquilas.",
    },
    "changed.gone_quiet": {
        "one": "{camera} lleva {n} noche sin movimiento. Suele ver {usual} visitas por noche.",
        "other": "{camera} lleva {n} noches sin movimiento. Suele ver {usual} visitas por noche.",
    },
    "changed.busier": (
        "{camera} tuvo más movimiento de lo normal anoche: {visits} frente a {usual} de costumbre."
    ),
    "changed.quieter": (
        "{camera} estuvo más tranquila de lo normal anoche: {visits} frente a {usual} de costumbre."
    ),
    "changed.some_cameras": "algunas cámaras",
    "changed.checking": "Todavía se están revisando las fotos de anoche de {cameras}.",
    "changed.none": "Sin cambios. Más o menos como las últimas noches.",

    # ---- camera health -------------------------------------------------------
    "health.retired": "Retirada el {day}. Fuera del plan de esta noche y de las cifras",
    "health.disconnected": "Sin conexión: ninguna cuenta de cámara la trae ahora",
    "health.not_syncing": "No llegan fotos. La cuenta de la cámara necesita atención.",
    "health.not_fetched": "No llegan fotos. Ninguna descarga ha funcionado en más de 2 horas.",
    "health.fetch_error": "No llegan fotos. {error}",
    "health.no_photos_since": "Sin fotos desde el {day}",
    "health.no_photos": "Aún sin fotos",
    "health.photos_only": "Solo envía fotos, sin partes de estado",
    "health.clock_fast": (
        ". Su reloj va {h} h adelantado (¿no se cambió la hora?): las horas de las fotos se "
        "corrigen, pero ajusta el reloj de la cámara"
    ),
    "health.no_checkin_for": "Sin conectar desde el {day}",
    "health.no_checkin": "Aún sin conectar",
    "health.photo_limit": "Sin créditos de fotos ({count}/{limit})",
    "health.battery_low": "Batería baja ({pct} %)",
    "health.ok": "Funciona con normalidad",

    # ---- camera logins (kept in English, said in the reader's language) ------
    "login.unreadable": "No se puede leer la contraseña guardada. Vuelve a escribirla.",
    "login.spypoint_refused": "SPYPOINT rechazó la contraseña. Vuelve a escribirla.",
    "login.provider_refused": "{provider} rechazó la contraseña. Vuelve a escribirla.",
    "login.provider_throttled": "{provider} está ocupado. Se reintentará en la próxima descarga.",
    "login.provider_down": "{provider} no responde. Se reintentará en la próxima descarga.",
    "login.provider_refused_request": (
        "{provider} rechazó la solicitud. Se reintentará en la próxima descarga."
    ),
    "login.ubox_refused": "UBox rechazó la contraseña. Vuelve a escribirla.",
    "login.ubox_signed_out": (
        "UBox cerró la sesión de esta cuenta. Vuelve a escribir la contraseña."
    ),
    "login.spypoint_throttled": (
        "SPYPOINT está rechazando peticiones por ahora. Se vuelve a intentar en la próxima "
        "descarga."
    ),
    "login.spypoint_down": (
        "SPYPOINT no responde bien ahora mismo. Se vuelve a intentar en la próxima descarga."
    ),
    "login.spypoint_refused_request": (
        "SPYPOINT rechazó la petición. Se vuelve a intentar en la próxima descarga."
    ),
    "login.spypoint_unreadable": (
        "SPYPOINT envió algo que la app no sabe leer. Se vuelve a intentar en la próxima descarga."
    ),
    "login.ubox_unknown": (
        "UBox no reconoce esta cuenta. Comprueba el correo que usas en la app UBox Pro."
    ),
    "login.unreachable": (
        "No se pudo contactar con {provider}. Se vuelve a intentar en la próxima descarga."
    ),
    "login.ubox_down": (
        "UBox no responde bien ahora mismo. Se vuelve a intentar en la próxima descarga."
    ),
    "login.other": "{text}. Se vuelve a intentar en la próxima descarga.",
    "login.failed": (
        "La descarga de {provider} falló ({error}). Se vuelve a intentar en la próxima descarga."
    ),
    "login.primary_label": "Cuenta principal de SPYPOINT",

    # ---- photo fetches (kept in English, said in the reader's language) ------
    "login.copy_of_primary": (
        "Esta es la cuenta principal de SPYPOINT del coto, que ya se descarga. Quita esta copia."
    ),
    "sync.some_failed": "Fallaron {n} de {total} cámaras. {error}",
    "sync.login_not_saved": (
        "Las fotos llegaron, pero no se pudo guardar el estado de la cuenta ({error}). "
        "Se vuelve a intentar en la próxima descarga."
    ),
    "ubox.snap.retry": {
        "one": "{n} foto no se pudo descargar. Se vuelve a intentar en la próxima descarga.",
        "other": (
            "{n} fotos no se pudieron descargar. Se vuelven a intentar en la próxima descarga."
        ),
    },
    "ubox.snap.dropped": {
        "one": "{n} foto no se pudo descargar. Se intentó {tries} veces, así que se deja fuera.",
        "other": (
            "{n} fotos no se pudieron descargar. Se intentaron {tries} veces, así que se dejan "
            "fuera."
        ),
    },
    "ubox.snap.some": {
        "one": (
            "{failed} fotos no se pudieron descargar. {n} se vuelve a intentar en la próxima "
            "descarga; el resto se intentó {tries} veces y queda fuera."
        ),
        "other": (
            "{failed} fotos no se pudieron descargar. {n} se vuelven a intentar en la próxima "
            "descarga; el resto se intentó {tries} veces y queda fuera."
        ),
    },

    # ---- UBox errors (kept in English, said in the reader's language) --------
    "ubox.err.host_unresolved": "No se pudo resolver el servidor de imágenes de UBox",
    "ubox.err.host_public": "La dirección de imagen de UBox debe usar un servidor HTTPS público",
    "ubox.err.bad_json": "UBox devolvió un JSON no válido",
    "ubox.err.unexpected": "UBox devolvió una respuesta inesperada",
    "ubox.err.rejected_password": "UBox rechazó la cuenta o la contraseña",
    "ubox.err.rejected_request": "UBox rechazó la petición; revisa la cuenta en UBox Pro",
    "ubox.err.no_data": "A la respuesta de UBox le falta el objeto de datos",
    "ubox.err.need_login": "Hacen falta el correo y la contraseña de UBox",
    "ubox.err.unreachable_login": "No se pudo contactar con UBox para entrar",
    "ubox.err.no_token": "A la respuesta de acceso de UBox le falta el token de sesión",
    "ubox.err.unreachable": "No se pudo contactar con UBox",
    "ubox.err.auth_expired": (
        "La sesión de UBox caducó tras reintentar; vuelve a conectar la cuenta"
    ),
    "ubox.err.auth_failed": "Falló la autenticación de UBox",
    "ubox.err.no_devices": "A la respuesta de dispositivos de UBox le faltan datos",
    "ubox.err.device_no_id": "UBox devolvió un dispositivo sin identificador",
    "ubox.err.naive_dates": "La consulta de eventos de UBox necesita fechas con zona horaria",
    "ubox.err.bad_range": (
        "La consulta de eventos de UBox tiene un intervalo o tamaño de página no válido"
    ),
    "ubox.err.no_events": "A la respuesta de eventos de UBox le falta la lista",
    "ubox.err.incomplete_page": (
        "UBox devolvió una página de eventos incompleta; se reintentará más tarde"
    ),
    "ubox.err.bad_event": "UBox devolvió un evento no válido",
    "ubox.err.repeated_page": "UBox repitió una página de eventos; se reintentará más tarde",
    "ubox.err.bad_event_fields": (
        "Un evento de UBox tiene una hora o un identificador de cámara no válidos"
    ),
    "ubox.err.fewer_events": "UBox devolvió menos eventos de los anunciados; se reintentará",
    "ubox.err.page_limit": (
        "Se alcanzó el límite de páginas de eventos de UBox; usa un periodo más corto"
    ),
    "ubox.err.https_only": "La dirección de imagen de UBox debe usar HTTPS",
    "ubox.err.too_big": "La imagen de UBox supera el límite de descarga de 20 MB",
    "ubox.err.empty_image": "UBox devolvió una imagen vacía",
    "ubox.err.download_failed": "No se pudo descargar la imagen de UBox",
    "ubox.err.unknown_account": (
        "UBox no reconoció esta cuenta. Comprueba la app de cámara correcta y el correo con el que "
        "está abierta."
    ),
    "ubox.err.login_http": "Falló el acceso a UBox (HTTP {status})",
    "ubox.err.request_http": "Falló la petición a UBox (HTTP {status})",
    "ubox.err.download_http": "Falló la descarga de la imagen de UBox (HTTP {status})",
    "ubox.err.other_estate": "Esta cámara UBox ya está vinculada a otro coto",
    "ubox.err.snapshot_size": "La foto está vacía o supera el límite de 20 MB",
    "ubox.err.snapshot_pixels": "La foto debe ser un JPEG de 40 megapíxeles como máximo",
    "ubox.err.snapshot_unreadable": "La foto no es un JPEG legible",
    "ubox.err.snapshot_failed": "No se pudo descargar una foto legible",
    "ubox.err.no_estate": "La cuenta no tiene coto",
    "fetch.disk_label": "Disco del servidor",
    "fetch.failed": "La descarga falló. Se vuelve a intentar en la próxima.",
    "fetch.disk_full": (
        "Casi lleno ({gb} GB libres). Las fotos esperan en las cámaras y llegan cuando haya sitio."
    ),
    "fetch.provider_failed": (
        "La descarga de {provider} falló ({error}). Se vuelve a intentar en la próxima."
    ),
    "fetch.ai_failed": "Falló la búsqueda de animales ({error})",

    # ---- the AI pass (kept in English, said in the reader's language) --------
    "ai.detector_failed": "El detector de animales no pudo arrancar ({error}).",
    "ai.classifier_failed": "El modelo de especies no pudo arrancar ({error}).",
    "ai.models_broken": "Los modelos dejaron de funcionar ({error}).",
    "ai.stopped_streak": (
        "{why} La revisión se paró después de fallar {n} fotos seguidas; no se contaron en contra "
        "de las fotos."
    ),

    # ---- photos --------------------------------------------------------------
    "photos.not_checked": "Aún sin revisar",
    "photos.could_not_check": "No se pudo revisar",
    "photos.people_admin_only": "Solo un administrador ve las fotos con personas o vehículos.",
    "photos.gone": "Esa foto ya no está disponible.",
    "people.person_vehicle": "Persona y vehículo",
    "people.person": "Persona",
    "people.vehicle": "Vehículo",
    "people.person_or_vehicle": "Persona o vehículo",

    # ---- cameras and the Check button ----------------------------------------
    "busy.reid": "buscando visitantes repetidos",
    "busy.plan": "preparando el plan de esta noche",
    "busy.score": "comparando el plan de anoche con las cámaras",
    "busy.scan": "buscando animales en las fotos",
    "busy.deploy": "instalando una actualización",
    "busy.other": "ocupado con otra tarea",
    "busy.fetch": "descargando fotos",
    "busy.try_later": "El servidor está {what}. Inténtalo de nuevo en unos minutos.",
    "cameras.start_failed": "No se pudo arrancar en el servidor. Inténtalo de nuevo en un minuto.",
    "cameras.name_hidden_chars": (
        "El nombre de la cámara tiene caracteres ocultos. Vuelve a escribirlo."
    ),
    "cameras.name_length": "El nombre de la cámara debe tener de 1 a 100 caracteres.",
    "cameras.rename_forbidden": (
        "Solo los administradores y miembros del coto pueden renombrar cámaras."
    ),
    "cameras.not_found": "Cámara no encontrada.",
    "cameras.name_taken": "Otra cámara ya se llama {name}. Elige otro nombre.",
    "cameras.name_taken_reset": (
        "Otra cámara ya se llama {name}, así que esta conserva su propio nombre."
    ),
    "cameras.check_viewer": "Las fotos nuevas llegan solas cada 15 minutos.",
    "cameras.check_running": "Ya se está comprobando. Las fotos nuevas aparecerán enseguida.",
    "cameras.check_asked": "Ya pedido. Las fotos nuevas llegan en cuanto el servidor quede libre.",
    "cameras.check_queued": "El servidor está {what}. Las fotos nuevas llegan cuando termine.",
    "cameras.off_map": "Ese punto está fuera del mapa. Mueve el mapa e inténtalo de nuevo.",
    "cameras.no_own_position": (
        "Esta cámara no ha informado de su propia posición. Colócala a mano."
    ),

    # ---- camera logins in Settings -------------------------------------------
    "accounts.viewer": "Los observadores pueden ver las cuentas de cámara pero no añadir ninguna.",
    "accounts.enter_login": "Escribe tu correo y contraseña de {provider}",
    "accounts.no_estate": "Únete a un coto antes de añadir una cuenta de cámara",
    "accounts.is_primary": "Esta cuenta ya está conectada como cuenta principal del coto",
    "accounts.already_added": "Esa cuenta de {provider} ya está añadida",
    "accounts.already_added_refresh": (
        "Esa cuenta de {provider} ya está añadida. Actualiza para verla."
    ),
    "accounts.connected_now": {
        "one": "Conectada — {provider} indica {n} cámara. Descargando fotos ahora.",
        "other": "Conectada — {provider} indica {n} cámaras. Descargando fotos ahora.",
    },
    "accounts.connected_later": {
        "one": "Conectada — {provider} indica {n} cámara. Las fotos llegan en la próxima descarga.",
        "other": (
            "Conectada — {provider} indica {n} cámaras. Las fotos llegan en la próxima descarga."
        ),
    },
    "accounts.unreachable": (
        "No se pudo contactar con {provider} para comprobar la contraseña. Inténtalo de nuevo en "
        "unos minutos."
    ),
    "accounts.ubox_failed": "No se pudo conectar con UBox Pro: {error}",
    "accounts.provider_failed": "No se pudo conectar con {provider}: {error}",
    "accounts.spypoint_refused": (
        "SPYPOINT rechazó ese correo y contraseña. Compruébalos en la app de SPYPOINT."
    ),
    "accounts.spypoint_failed": "SPYPOINT no aceptó esa cuenta: {error}",
    "accounts.not_found": "Cuenta no encontrada",
    "accounts.password_forbidden": (
        "Solo quien añadió esta cuenta, o un administrador, puede cambiar su contraseña"
    ),
    "accounts.enter_password": "Escribe la contraseña",
    "accounts.password_saved": (
        "Contraseña guardada. Las fotos llegan en la próxima descarga, en menos de 15 minutos."
    ),
    "accounts.limits_forbidden": (
        "Solo quien añadió esta cuenta, o un administrador, puede cambiar sus límites"
    ),
    "accounts.limits_ubox_only": "Los límites de fotos solo se aplican a cuentas de UBox Pro",
    "accounts.limits_saved": "Límites guardados. Se aplican desde la próxima descarga.",
    "accounts.remove_forbidden": (
        "Solo quien añadió esta cuenta, o un administrador, puede quitarla"
    ),

    # ---- alerts on the phone -------------------------------------------------
    "push.just_now": "ahora mismo",
    "push.time": "a las {time}",
    "push.since_time": "las {time}",
    "push.last_night": "anoche a las {time}",
    "push.yesterday": "ayer a las {time}",
    "push.on_day": "el {day} a las {time}",
    "push.at_camera": "{name} en {camera}",
    "push.on_cameras": {
        "one": "{name} en {n} cámara",
        "other": "{name} en {n} cámaras",
    },
    "push.one_visit": "1 visita {when}.",
    "push.visits_last": "{visits}, la última {when}.",
    "push.visits_at_last": "{visits} en {cameras}, la última {when}.",
    "push.at_cameras": " en {cameras}",
    "push.update": "{visits}{where} desde {since}, la última {last}.",
    "push.summary_title": "{n} avistamientos nuevos, {animals} animales",
    "push.summary_body": "{names}, el último {when}.",
    "verdict.best_odds": "Mejores opciones",
    "verdict.worth_a_look": "Merece la pena",
    "verdict.quiet": "Tranquilo",
    "verdict.no_data": "Sin datos suficientes",
    "plan.wind.clean": "viento bueno",
    "plan.wind.wrong": "viento malo",
    "plan.wind.too_light": "viento demasiado flojo para juzgar",
    "plan.wind.no_forecast": "sin previsión de viento",
    "plan.tonight": "{verdict} esta noche",
    "plan.sunset": "puesta de sol {time}",
    "plan.no_camera": (
        "No hay suficientes noches vigiladas para juzgar esta noche. Abre la app para ver lo que "
        "vieron las cámaras."
    ),
    "plan.species_hours": "{species}, mejor de {start} a {end}.",
    "held.one": "{name}: {visits} en {cameras}",
    "held.each": "{name}: {visits}",
    "held.worth_a_look": {
        "one": "{n} foto marcada Merece la pena",
        "other": "{n} fotos marcadas Merece la pena",
    },
    "held.title.sit": "Mientras estabas en el puesto",
    "held.title.quiet": "Durante tus horas de silencio",
    "held.body": "{parts}, la última {when}.",

    # ---- alert settings ------------------------------------------------------
    "alerts.unknown_camera": "Cámara desconocida: {ids}",
    "alerts.unknown_species": "Especie desconocida: {ids}",
    "alerts.quiet_needs_both": "Las horas de silencio necesitan un inicio y un final.",
    "alerts.quiet_same": "Las horas de silencio no pueden empezar y acabar a la misma hora.",
    "alerts.endpoint_https": "La dirección de avisos debe ser https",
    "alerts.no_phone": (
        "Ningún teléfono recibe avisos todavía. Activa los avisos primero desde ese teléfono."
    ),
    "alerts.test_title": "Aviso de prueba",
    "alerts.test_body": "Los avisos funcionan en este teléfono.",

    # ---- team notes and people -----------------------------------------------
    "notes.bad_chars": "La nota tiene caracteres que no se pueden guardar. Escríbela otra vez.",
    "notes.too_long": "Deja la nota en {n} caracteres.",
    "notes.push_title": "Merece la pena: {label} en {camera}",
    "notes.push_body": "{name}: {text}",
    "notes.push_marked": "{name} ha marcado una foto",
    "notes.empty_frame": (
        "Esta foto está marcada como «no hay nada». Guárdala primero como foto de animal."
    ),
    "notes.hidden_only": (
        "En esta foto solo hay animales ocultos en la app, así que la cuadrilla no puede verla."
    ),
    "notes.people_only": (
        "En esta foto hay una persona o un vehículo, así que se queda con los administradores y la "
        "cuadrilla no puede verla."
    ),
    "notes.not_looked": (
        "La app aún no ha revisado esta foto, así que la cuadrilla no puede verla. Inténtalo de "
        "nuevo en unos minutos."
    ),
    "notes.photo_not_found": "Foto no encontrada.",
    "notes.viewer": "Los observadores pueden ver las notas pero no añadirlas.",
    "notes.not_saved": "No se pudo guardar la nota. Ciérrala e inténtalo de nuevo.",
    "notes.gone": "Esa nota ya no está.",
    "notes.remove_forbidden": "Solo quien la escribió o un administrador puede quitar una nota.",
    "people.hunter": "Cazador",
    "people.removed": "Persona eliminada",
    "crash.too_large": "Informe demasiado grande",
    "crash.not_a_report": "Eso no es un informe de fallo.",
    "crash.too_many": "Demasiados informes. Los siguientes se descartan.",
    "crash.unknown_device": "Dispositivo desconocido",

    # ---- stands and sits -----------------------------------------------------
    "stands.no_estate": "Configura primero el coto.",
    "stands.auto_name": "Puesto {camera}",
    "stands.auto_note": (
        "Cada puesto está colocado en su cámara. Muévelo a donde de verdad te pones. Los consejos "
        "de viento empiezan cuando marcas las direcciones por las que entran los animales."
    ),
    "stands.camera_gone": "Esa cámara no está en la app.",
    "stands.gone": "Ese puesto no está en la app.",
    "stands.has_sits": {
        "one": (
            "Hay {n} espera registrada en este puesto. Borrarlo eliminaría ese historial. Mejor "
            "cámbiale el nombre."
        ),
        "other": (
            "Hay {n} esperas registradas en este puesto. Borrarlo eliminaría ese historial. Mejor "
            "cámbiale el nombre."
        ),
    },
    "stands.claimed": "{stand} ya lo ha reservado otro cazador para esta noche.",
    "stands.arc_conflict": (
        "{stand} y {other} comparten sector de tiro, y {other} está ocupado esta noche. Elige otro "
        "puesto."
    ),
    "stands.viewer": "Los observadores pueden ver los puestos pero no reservarlos.",
    "sits.gone": "Esa espera no está en la app.",
    "sits.viewer": "Los observadores pueden ver las esperas pero no cambiarlas.",
    "sits.not_yours": "Esa espera es de otro cazador.",
    "sits.bad_outcome": "el resultado debe ser uno de {outcomes}",
    "sits.cancelled": "Esa reserva se canceló. Vuelve a reservar el puesto.",
    "sits.already_reported": "Ya has dicho lo que pasó en esta espera.",
    "sits.not_started": "Esa espera no ha empezado.",

    # ---- approach lines and the dark exit ------------------------------------
    "arcs.no_camera": "Este puesto no está vinculado a una cámara.",
    "arcs.camera_unplaced": "La cámara vinculada no tiene posición registrada.",
    "arcs.no_others": "No hay otras cámaras colocadas de las que deducir movimientos.",
    "arcs.note": {
        "one": (
            "{n} vez los animales llegaron a {camera} menos de {minutes} min después de pasar por "
            "{other}."
        ),
        "other": (
            "{n} veces los animales llegaron a {camera} menos de {minutes} min después de pasar por"
            " {other}."
        ),
    },
    "arcs.none": (
        "Todavía no hay movimientos repetidos entre cámaras — no basta para proponer una entrada, "
        "así que la app seguirá dejando esto en tus manos."
    ),
    "exit.no_visits": "Todavía no hay visitas en la cámara de este puesto.",
    "exit.quiet": (
        "Salida a oscuras a las {time} — solo el {pct} % de las visitas de esta cámara cae en la "
        "hora siguiente, así que salir entonces molesta lo mínimo."
    ),
    "exit.busy_reason": (
        "No hay una hora de verdad tranquila — este puesto tiene movimiento toda la noche."
    ),
    "exit.busy": (
        "No hay hora tranquila después de las {after} en este puesto — hay movimiento toda la "
        "noche. La salida menos mala es a las {time}."
    ),

    # ---- the harvest book ----------------------------------------------------
    "harvest.sex.male": "Macho",
    "harvest.sex.female": "Hembra",
    "harvest.sex.unknown": "No seguro",
    "harvest.age.juvenile": "Cría del año",
    "harvest.age.young_adult": "Joven",
    "harvest.age.mature_adult": "Adulto",
    "harvest.age.old": "Viejo",
    "harvest.age.unknown": "No seguro",
    "harvest.viewer": "Los observadores no pueden anotar capturas.",
    "harvest.not_yours": "Esa captura es de otro cazador. Un administrador puede cambiarla.",
    "harvest.not_a_shot": "Esa espera no está anotada como disparo. Di primero lo que pasó.",
    "harvest.field.seal": "número de precinto",
    "harvest.field.note": "nota",
    "harvest.field.name": "nombre",
    "harvest.hidden_chars": "El campo «{what}» tiene caracteres ocultos. Vuelve a escribirlo.",
    "harvest.too_long": "El campo «{what}» admite como máximo {n} caracteres.",
    "harvest.bad_species": "Elige uno de los animales de la lista.",
    "harvest.bad_sex": "El sexo es macho, hembra o no seguro.",
    "harvest.bad_age": "Elige una edad de la lista.",
    "harvest.future": "Esa hora todavía no ha llegado. Revisa la fecha.",
    "harvest.too_old": "Esa fecha es demasiado antigua. Revisa el año.",
    "harvest.bad_season": "Elige una temporada de la lista.",
    "harvest.not_saved": "No se pudo guardar la captura. Ciérrala e inténtalo de nuevo.",
    "harvest.gone": "Esa captura ya no está en el libro.",
    "harvest.admin_names": "Solo un administrador cambia el nombre en una captura.",
    "harvest.col.date": "Fecha",
    "harvest.col.time": "Hora",
    "harvest.col.species": "Especie",
    "harvest.col.sex": "Sexo",
    "harvest.col.age": "Edad",
    "harvest.col.seal": "Número de precinto",
    "harvest.col.weight": "Peso (kg)",
    "harvest.col.hunter": "Cazador",
    "harvest.col.stand": "Puesto",
    "harvest.col.notes": "Notas",

    # ---- the activity map ----------------------------------------------------
    "activity.part.dusk": "al anochecer",
    "activity.part.night": "en plena noche",
    "activity.part.dawn": "al amanecer",
    "activity.checking_last": "Todavía se están revisando las fotos de anoche.",
    "activity.checking": "Todavía se están revisando las fotos.",
    "activity.unreadable_last": "Sin contar: no se pudieron revisar todas las fotos de anoche.",
    "activity.unreadable": "Sin contar: no se pudieron revisar todas las fotos.",
    "activity.blind_last": "Sin contar: puede que la cámara no funcionara anoche.",
    "activity.blind": "Sin contar: la cámara no funcionó esas noches.",
    "activity.tail.times": ", a las {times}",
    "activity.tail.mostly": ", sobre todo de {peak} h",
    "activity.tail.busiest": ", más movimiento de {peak} h",
    "activity.tail.no_set_time": ", sin hora fija",
    "activity.last_night": "anoche",
    "activity.last_night_so_far": "anoche hasta ahora",
    "activity.one.nothing_all": "Nada en la cámara{when} {night}.",
    "activity.one.nothing": "Sin rastro de {species}{when} {night}.",
    "activity.one.visits_all": {
        "one": "{n} visita de animales{when} {night}{tail}",
        "other": "{n} visitas de animales{when} {night}{tail}",
    },
    "activity.one.visits": {
        "one": "{n} visita de {species}{when} {night}{tail}",
        "other": "{n} visitas de {species}{when} {night}{tail}",
    },
    "activity.q.working": " en que funcionó",
    "activity.q.checkable": " que se pudieron revisar",
    "activity.q.so_far": " revisadas hasta ahora",
    "activity.none_all": {
        "one": "Ningún animal{when} en la {n} noche{qualifier}.",
        "other": "Ningún animal{when} en las {n} noches{qualifier}.",
    },
    "activity.none": {
        "one": "Sin rastro de {species}{when} en la {n} noche{qualifier}.",
        "other": "Sin rastro de {species}{when} en las {n} noches{qualifier}.",
    },
    "activity.some": "{who} en {n} de {total} noches{qualifier}{tail}",

    # ---- the map -------------------------------------------------------------
    "map.bad_nights": "Las noches son 1, 7 o 30.",
    "map.no_species": "No existe esa especie.",
    "map.no_replay": "No hay repetición para esa noche.",

    # ---- insights: what moves the animals ------------------------------------
    "class.animals_all": "Todos los animales",
    "patterns.moon_illum.label": "Luz de luna",
    "patterns.moon_illum.high": "luna brillante",
    "patterns.moon_illum.low": "luna oscura",
    "patterns.pressure.label": "Presión",
    "patterns.pressure.high": "presión alta",
    "patterns.pressure.low": "presión baja",
    "patterns.pressure_trend.label": "Tendencia de la presión",
    "patterns.pressure_trend.high": "presión subiendo",
    "patterns.pressure_trend.low": "presión bajando",
    "patterns.temp.label": "Temperatura",
    "patterns.temp.high": "tiempo templado",
    "patterns.temp.low": "tiempo fresco",
    "patterns.wind.label": "Viento",
    "patterns.wind.high": "viento",
    "patterns.wind.low": "aire en calma",
    "patterns.rain.label": "Lluvia",
    "patterns.rain.high": "lluvia",
    "patterns.rain.low": "tiempo seco",
    "patterns.cloud.label": "Nubosidad",
    "patterns.cloud.high": "nubes",
    "patterns.cloud.low": "cielo despejado",
    "patterns.darkness.label": "Horas de oscuridad",
    "patterns.darkness.high": "noche larga",
    "patterns.darkness.low": "noche corta",
    "patterns.statement": "Unas {hi} visitas por noche con {hi_desc}, unas {lo} con {lo_desc}.",
    "insights.midnight": "medianoche",
    "insights.busiest": "Tus cámaras tienen más movimiento entre {start} y {end}.",
    "insights.species_mostly": "Las cámaras ven {species} sobre todo entre {start} y {end}.",
    "insights.concentrated": (
        "Casi todo el movimiento está en {cameras}. Las demás cámaras ven mucho menos."
    ),
    "insights.busiest_cameras": "{cameras} son tus cámaras con más movimiento.",
    "insights.class_missing": "Elige qué animales mostrar.",

    # ---- species in Settings -------------------------------------------------
    "species.name_hidden_chars": "Ese nombre tiene caracteres ocultos. Vuelve a escribirlo.",
    "species.name_length": "Un nombre tiene de 1 a 40 caracteres.",
    "species.not_found": "Especie no encontrada.",

    # ---- the alerts feed on Tonight ------------------------------------------
    "ago.unknown": "desconocido",
    "ago.just_now": "ahora mismo",
    "ago.ago": "hace {span}",
    "ago.m": "{n} min",
    "ago.h": "{n} h",
    "ago.d": "{n} d",
    "feed.seen": {
        "one": "Se ha visto {n} vez en los últimos 2 días, la última {ago}.",
        "other": "Se ha visto {n} veces en los últimos 2 días, la última {ago}.",
    },
    "feed.battery_title": "{camera}: batería baja",
    "feed.battery": "Queda un {pct} %. Lleva pilas en la próxima visita.",
    "feed.since": ", desde la noche del {day}",
    "feed.quiet_title": "{camera}: sin movimiento",
    "feed.quiet": {
        "one": "Nada en su última {n} noche vigilada{since}. Suele ver {usual} visitas por noche.",
        "other": (
            "Nada en sus últimas {n} noches vigiladas{since}. Suele ver {usual} visitas por noche."
        ),
    },

    # ---- the week's wind -----------------------------------------------------
    "week.tonight": "Esta noche",
    "week.tonight_hours": "esta noche {hours}",
    "week.no_position": "{stand} aún no está en el mapa, así que no se puede juzgar su viento.",
    "week.no_bedding": (
        "Aún no hay encames dibujados, así que no se puede juzgar el viento para {stand}."
    ),
    "week.no_geometry": (
        "{stand} no tiene direcciones de entrada puestas, así que juzga tú su viento."
    ),
    "week.no_forecast": "Aún no hay previsión de viento para la semana.",
    "week.right": "Viento bueno para {stand}: {when}",
    "week.none": "Sin viento bueno para {stand} esta semana.",

    # ---- the track record ----------------------------------------------------
    "record.too_few": {
        "one": "{n} noche comprobada hasta ahora. Cuántas veces acierta se verá tras {needed}.",
        "other": "{n} noches comprobadas hasta ahora. Cuántas veces acierta se verá tras {needed}.",
    },
    "record.verdict": {
        "one": "Cuando dijo «{verdict}» de una cámara, los animales llegaron {came} de {n} veces.",
        "other": (
            "Cuando dijo «{verdict}» de una cámara, los animales llegaron {came} de {n} veces."
        ),
    },
    "record.beats": (
        "Sus probabilidades se acercaron más a lo que pasó que el nivel habitual de cada cámara."
    ),
    "record.no_better": (
        "Sus probabilidades no se acercaron más a lo que pasó que el nivel habitual de cada cámara."
    ),
    "record.too_few_each": {
        "one": "{n} noche comprobada, demasiado pocas de cada veredicto para decir nada aún.",
        "other": "{n} noches comprobadas, demasiado pocas de cada veredicto para decir nada aún.",
    },

    # ---- photos and animals --------------------------------------------------
    "images.viewer": "Los observadores pueden ver las fotos pero no cambiarlas.",
    "images.old_link": "Este enlace a la foto ha caducado. Vuelve a abrir la foto en la app.",
    "images.sign_in": "Entra para ver las fotos.",
    "images.no_picture": "Esta foto todavía no tiene imagen, así que no hay nada que corregir.",
    "images.no_people": "La app ya no cuenta a nadie en esta foto.",
    "animals.not_found": "Animal no encontrado.",
    "animals.gone": "Ese animal ya no está en la app.",
    "animals.name_first": "Escribe primero un nombre.",
    "animals.name_long": "Un nombre tiene como máximo 60 caracteres.",
    "animals.bad_status": "el estado debe ser uno de {statuses}",
    "animals.merge_target": "No se encontró el animal con el que unir.",
    "animals.reid_running": "Ya se está buscando. Tarda unos minutos.",
    "animals.reid_started": "Buscando visitantes repetidos. Tarda unos minutos.",

    # ---- areas on the map, and admin -----------------------------------------
    "zones.name_needed": "Ponle un nombre que la cuadrilla conozca.",
    "zones.name_not_empty": "El nombre se puede cambiar, pero no dejar vacío.",
    "zones.outline_not_empty": "El contorno se puede cambiar, pero no dejar vacío.",
    "zones.bad_kind": "el tipo debe ser uno de {kinds}",
    "zones.gone": "Esa zona no está en el mapa.",
    "admin.deploying": (
        "El servidor está instalando una actualización. Inténtalo de nuevo en unos minutos."
    ),
    "admin.no_api_key": "Añade primero ANTHROPIC_API_KEY a .env",
    "admin.labelling": "Ya se está etiquetando. Las etiquetas aparecen en unos minutos.",
    "admin.labels_coming": "Las etiquetas aparecen en Cámaras en unos minutos.",
    "admin.retry": {
        "one": "{n} foto se revisará de nuevo en la próxima descarga.",
        "other": "{n} fotos se revisarán de nuevo en la próxima descarga.",
    },
    "admin.nothing_to_retry": "Nada que volver a intentar.",
    "admin.reload": "Recarga la app: las actualizaciones ya aparecen solas en Versión de la app.",

    # ---- server upkeep (kept in English, said in the reader's language) ------
    "restore.no_table": "La copia restaurada no tiene la tabla {table}.",
    "restore.no_rows": "La copia restaurada no tiene filas en {table}.",
    "restore.photos_missing": (
        "Faltan {n} de {total} fotos buscadas en la carpeta de fotos de la copia."
    ),
    "restore.failed": "La comprobación no pudo ejecutarse ({error}).",
    "ops.unreadable": "No se puede leer su archivo de estado.",

    # ---- drawing on the map --------------------------------------------------
    "shape.not_polygon": "El contorno debe ser un polígono GeoJSON.",
    "shape.no_corners": "El contorno no tiene esquinas.",
    "shape.too_many": "Ese contorno tiene {n} esquinas. Déjalo por debajo de {limit}.",
    "shape.two_numbers": "Cada esquina debe ser dos números: longitud y luego latitud.",
    "shape.off_map": (
        "Una esquina está fuera del mapa. Las esquinas van con la longitud primero y luego la "
        "latitud."
    ),
    "shape.three": "Toca al menos tres esquinas alrededor de la zona.",
    "shape.too_big": "Ese contorno mide más de 20 km. Dibuja solo el monte donde se encaman.",
    "shape.crosses": "El contorno se cruza consigo mismo. Pon las esquinas en orden por el borde.",
    "shape.no_area": (
        "Ese contorno casi no tiene superficie. Reparte las esquinas alrededor del monte."
    ),
    "box.four_numbers": "El recuadro necesita cuatro números: sur, oeste, norte y este.",
    "box.off_map": "Ese recuadro está fuera del mapa.",
    "box.too_big": (
        "Mide {km} km, más de lo que un teléfono debería guardar. Acércate hasta que el coto mida "
        "menos de {limit} km."
    ),
    "box.too_small": "Es demasiado pequeño para ser el coto. Aléjate un poco.",
    "terrain.busy": "El servicio de altitudes está ocupado. Inténtalo de nuevo en unos minutos.",
    "terrain.down": "El servicio de altitudes no respondió. Inténtalo más tarde.",

    # ---- signing in, too many tries ------------------------------------------
    "count.minutes": {
        "one": "{n} minuto",
        "other": "{n} minutos",
    },
    "throttle.place": (
        "Demasiadas contraseñas incorrectas desde aquí. Inténtalo de nuevo en {wait}."
    ),
    "throttle.at_once": (
        "Demasiados accesos a la vez desde aquí. Inténtalo de nuevo en unos segundos."
    ),
    "throttle.checking": (
        "Todavía se está comprobando tu último intento. Inténtalo de nuevo en unos segundos."
    ),
    "throttle.email": {
        "one": (
            "Demasiadas contraseñas incorrectas para este correo. Inténtalo de nuevo en {n} "
            "segundo."
        ),
        "other": (
            "Demasiadas contraseñas incorrectas para este correo. Inténtalo de nuevo en {n} "
            "segundos."
        ),
    },
    "throttle.email_lately": (
        "Demasiadas contraseñas incorrectas para este correo últimamente. Inténtalo de nuevo en "
        "{wait}, o desde un teléfono que ya haya entrado con él."
    ),

    # ---- the stag/hind labelling pass (kept in English, said in the reader's language) ----
    "sexpass.key_refused": (
        "Anthropic rechazó la clave de API. Revisa ANTHROPIC_API_KEY en el .env del servidor."
    ),
    "sexpass.no_credit": (
        "La cuenta de Anthropic no tiene saldo. Recárgala para volver a etiquetar venados y "
        "ciervas."
    ),
    "sexpass.no_model": (
        "Anthropic no conoce el modelo {model}. Pide a quien lleva el servidor que lo actualice."
    ),
    "sexpass.limited": (
        "Anthropic está limitando las peticiones ahora mismo. Se vuelve a intentar la próxima hora."
    ),
    "sexpass.unreachable": (
        "No se pudo contactar con Anthropic. Se vuelve a intentar la próxima hora."
    ),
    "sexpass.http": (
        "Anthropic tuvo un problema (HTTP {status}). Se vuelve a intentar la próxima hora."
    ),
    "sexpass.bad_answer": "Anthropic no respondió bien. Se vuelve a intentar la próxima hora.",

    # ---- Look for repeats (kept in English, said in the reader's language) ----
    "reid.failed": "Algo salió mal ({error}).",
    "reid.stopped": (
        "Se paró a medias: el servidor estuvo ocupado demasiado tiempo. Tócalo otra vez para "
        "terminar."
    ),

    # ---- the moon ------------------------------------------------------------
    "moon.new_moon": "Luna nueva",
    "moon.waxing_crescent": "Luna creciente",
    "moon.first_quarter": "Cuarto creciente",
    "moon.waxing_gibbous": "Gibosa creciente",
    "moon.full_moon": "Luna llena",
    "moon.waning_gibbous": "Gibosa menguante",
    "moon.last_quarter": "Cuarto menguante",
    "moon.waning_crescent": "Luna menguante",
}
