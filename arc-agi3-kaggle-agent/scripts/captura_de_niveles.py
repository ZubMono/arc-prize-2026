"""[arc-agi3-kaggle-agent/scripts/captura_de_niveles] BL.21695 paso 1 -- CAPTURA DE "COMO SE VE
GANAR": extrae del harness local la VENTANA de frames alrededor de cada incremento de
`levels_completed` y la deja en un JSONL listo para persistir a `arcReplayFrames`.

POR QUE EXISTE (el agujero MEDIDO). `arcReplayFrames` tenia 2.456 documentos en produccion y CERO
con `levelsCompleted > 0`: el corpus de replay no contiene UN SOLO ejemplo de un nivel superado.
Las subidas de nivel que si se observaron (ft09, lp85, vc33, g50t, sc25, m0r0) ocurrieron en el
harness LOCAL offline, que hasta este BL no persistia nada. Sin esos frames, cualquier vocabulario
de objetivos ("alcanzar destino", "recolectar todo", "pintar region") seria INVENTADO en vez de
DERIVADO -- que es exactamente el anti-objetivo que define el skill world-learning. Este modulo es
el que produce el dato del que se puede derivar.

QUE ES UNA VENTANA Y POR QUE N = 10 (`VENTANA_POR_DEFECTO`). El frame del evento por si solo dice
"el contador subio", no dice QUE lo hizo subir: la maniobra que resuelve el nivel es una SECUENCIA.
El numero se ancla en una magnitud ya medida del propio agente y no en el gusto: la unidad de
maniobra de la politica es la macro-accion, con tope `MACRO_MAX_STEPS = 8`
(arc_agent/exploration_memory.py), asi que 10 frames ANTES contienen una macro-accion COMPLETA mas
dos pasos de contexto -- y ninguna maniobra del agente puede ser mas larga que eso sin haber pasado
por una decision intermedia que la ventana igual captura. 10 frames DESPUES existen por una razon
distinta y igual de concreta: el objetivo del nivel SIGUIENTE se lee en el tablero que queda tras
la transicion (que reaparecio, que se reseteo, donde arranca el avatar), y ese es el otro extremo
de la evidencia. Ventana total <= 21 frames por evento: a 64x64 celdas son ~86KB de JSON crudo por
evento, dos ordenes de magnitud por debajo del presupuesto de 1MB por partida del corpus.

TRUNCAMIENTO HONESTO. Si el evento ocurre en el paso 2 (vc33 sube de nivel en el paso 2 medido) no
hay 10 frames antes: la ventana se recorta y `framesAntes`/`framesDespues` reportan cuantos frames
REALES entraron. Nunca se rellena con frames sinteticos -- un frame inventado en el corpus es peor
que un frame ausente.

SOLO REPO: vive en `scripts/`, no en `arc_agent/`, asi que no viaja al entregable de Kaggle (donde
no hay red ni Mongo). Stdlib pura, sin dependencias de terceros."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Frames capturados a cada lado del evento. Ver el docstring del modulo para la justificacion:
#: 10 >= MACRO_MAX_STEPS (8) + 2 pasos de contexto.
VENTANA_POR_DEFECTO = 10

#: BL.21794 -- clases que NO son las tres de la maniobra (`CLASES_DE_PASO`) y que existen porque una
#: ventana tiene frames a los que la clasificacion NO APLICA. Se nombran en vez de dejarse ausentes:
#: un campo ausente no distingue "este frame no se puede clasificar" de "esta captura es anterior a
#: BL.21794", y esa diferencia decide si el informe puede usar el dato guardado o tiene que
#: reconstruirlo.
CLASE_SIN_PREVIO = "sinPrevio"
CLASE_DEL_EVENTO = "elEvento"
CLASE_POSTERIOR_AL_EVENTO = "posteriorAlEvento"

#: Valor de `accion` cuando no se sabe cual la produjo (frame inicial sintetico del framework
#: oficial, o un motor que no informa la accion). No se inventa 'RESET': eso seria afirmar algo que
#: nadie dijo -- y es exactamente lo que pasaba antes de `registrar_acciones` (ver abajo).
ACCION_DESCONOCIDA = "DESCONOCIDA"


@dataclass(frozen=True)
class AccionRegistrada:
    """La accion que el agente EMITIO, leida en el momento de emitirla."""

    nombre: str
    x: int | None = None
    y: int | None = None


def describir_accion(accion: Any) -> AccionRegistrada:
    """Nombre y coordenadas de una `GameAction` del framework oficial.

    LAS COORDENADAS SE LEEN AL VUELO, no despues: `GameAction` es un Enum y `set_data` muta el
    MIEMBRO del enum, que es un objeto global compartido por todas las partidas del proceso. Leer
    `action_data` mas tarde devolveria las coordenadas del click SIGUIENTE."""
    nombre = getattr(accion, "name", None) or str(accion or ACCION_DESCONOCIDA)
    datos = getattr(accion, "action_data", None)
    x = getattr(datos, "x", None)
    y = getattr(datos, "y", None)
    es_compleja = bool(getattr(accion, "is_complex", lambda: False)())
    if not es_compleja or x is None or y is None:
        return AccionRegistrada(nombre=str(nombre))
    return AccionRegistrada(nombre=str(nombre), x=int(x), y=int(y))


def registrar_acciones(agente: Any) -> list[AccionRegistrada]:
    """Engancha el registro de acciones a UNA instancia de agente y devuelve la lista que se va a
    ir llenando (una entrada por frame efectivamente agregado a `agente.frames`).

    POR QUE HACE FALTA (agujero MEDIDO, 2026-08-18). `FrameData.action_input` del wire oficial trae
    la accion que produjo el frame... cuando la API la informa. El motor OFFLINE que hospeda el
    harness local NO la informa: deja el default del modelo pydantic, que es `RESET`. Los primeros
    12 completados capturados quedaron con `accion: "RESET"` en los 235 frames -- incluidos los
    juegos que se juegan a CLICKS, donde la coordenada del click es el dato central. Un corpus que
    afirma "esto lo hizo un RESET" es peor que uno que dice "no se": la conclusion derivada seria
    falsa y nadie tendria motivo para dudar de ella.

    SE ENGANCHA EN LA INSTANCIA, no en la clase: se sustituye el metodo ligado `take_action` del
    objeto, asi que la clase entregada (`MyAgent`) queda intacta -- ni su nombre, ni su MRO, ni el
    `name` que el framework usa para la scorecard cambian. Y se registra DESPUES de que el motor
    devuelve frame, y solo si devolvio uno: `Agent.main()` unicamente agrega a `frames` cuando
    `take_action` devuelve algo, asi que registrar antes desalinearia la lista en el primer frame
    invalido -- y una accion mal atribuida es evidencia falsa, que es lo que este modulo existe
    para no producir."""
    registradas: list[AccionRegistrada] = []
    emitir = agente.take_action

    def take_action(accion: Any) -> Any:
        frame = emitir(accion)
        if frame is not None:
            registradas.append(describir_accion(accion))
        return frame

    agente.take_action = take_action
    return registradas


@dataclass(frozen=True)
class FrameCapturado:
    """Un frame del harness local, normalizado al vocabulario de `arcReplayFrames`.

    `paso` es el indice del frame DENTRO de la partida (0 = frame inicial del framework), y es el
    que viaja como `stepNum`: se conservan los huecos entre ventanas a proposito, porque el hueco
    ES la informacion de "aca no capturamos nada"."""

    paso: int
    accion: str
    x: int | None
    y: int | None
    acciones_disponibles: list[int]
    grilla: list[list[int]]
    niveles_completados: int
    niveles_para_ganar: int
    estado: str
    reinicio_completo: bool
    #: BL.21794 -- clase de la transicion que produjo ESTE frame, decidida EN LA CAPTURA:
    #: `inerte` / `enAnimacion` / `informativo` para los frames de la maniobra, y `sinPrevio` /
    #: `elEvento` / `posteriorAlEvento` para los que quedan fuera de ella. Ver `clases_de_los_frames`.
    clase_de_paso: str = CLASE_SIN_PREVIO
    #: Firma de mecanica de BL.21741 de esa misma transicion, o "" si no aplica.
    firma_del_paso: str = ""

    def a_json(self) -> dict[str, Any]:
        return {
            "paso": self.paso,
            "accion": self.accion,
            "x": self.x,
            "y": self.y,
            "accionesDisponibles": list(self.acciones_disponibles),
            "grilla": [list(fila) for fila in self.grilla],
            "nivelesCompletados": self.niveles_completados,
            "nivelesParaGanar": self.niveles_para_ganar,
            "estado": self.estado,
            "reinicioCompleto": self.reinicio_completo,
            "claseDePaso": self.clase_de_paso,
            "firmaDelPaso": self.firma_del_paso,
        }


@dataclass(frozen=True)
class VentanaDeNivel:
    """Los frames alrededor de UN incremento de `levels_completed`. Es la unidad de evidencia de
    BL.21695: la respuesta a "que estaba pasando cuando el juego dijo que habiamos ganado"."""

    juego: str
    corrida: str
    modelo: str
    paso_del_evento: int
    nivel_previo: int
    nivel_nuevo: int
    frames: list[FrameCapturado]
    #: BL.21798 -- semilla DECLARADA de la partida (`--semilla` de `play_local.py`, que fija
    #: `MyAgent.SEMILLA`). Vacia = no declarada, y asi se persiste: el `runId` lleva el LOTE, que
    #: NO siembra nada desde e7f70322d1, asi que sin este campo el corpus no puede decir cuales de
    #: sus ventanas se pueden volver a producir -- que es justo lo que hizo falta saber cuando el
    #: veredicto de BL.21794 resulto depender de dos corridas concretas. NUNCA se rellena con el
    #: lote: una semilla inventada haria pasar por reproducible lo que no lo es.
    semilla: str = ""

    @property
    def frames_antes(self) -> int:
        return sum(1 for f in self.frames if f.paso < self.paso_del_evento)

    @property
    def frames_despues(self) -> int:
        return sum(1 for f in self.frames if f.paso > self.paso_del_evento)

    @property
    def clasificacion_de_frames(self) -> dict[str, int]:
        """Cuantos frames de esta ventana cayo en cada clase (BL.21794). Va en el JSONL como
        RESUMEN de lo que ya esta frame por frame: es lo que se lee sin decodificar la ventana
        entera, y lo que hace visible de un vistazo una ventana sin un solo frame informativo."""
        conteo: dict[str, int] = {}
        for frame in self.frames:
            conteo[frame.clase_de_paso] = conteo.get(frame.clase_de_paso, 0) + 1
        return dict(sorted(conteo.items()))

    def a_json(self) -> dict[str, Any]:
        return {
            "juego": self.juego,
            "corrida": self.corrida,
            "modelo": self.modelo,
            "semilla": self.semilla,
            "pasoDelEvento": self.paso_del_evento,
            "nivelPrevio": self.nivel_previo,
            "nivelNuevo": self.nivel_nuevo,
            "framesAntes": self.frames_antes,
            "framesDespues": self.frames_despues,
            "clasificacionDeFrames": self.clasificacion_de_frames,
            "frames": [f.a_json() for f in self.frames],
        }


def grilla_visible(frame: Any) -> list[list[int]]:
    """La grilla que el agente MIRA. `frame.frame` es una PILA de capas y la politica usa la
    ULTIMA (`policy.py`: `frame.frame[-1] if frame.frame else None`); capturar otra capa produciria
    un corpus que no describe lo que el agente vio. Devuelve `[]` si el frame no trae grilla (el
    framework oficial arranca `self.frames` con un FrameData vacio)."""
    capas = getattr(frame, "frame", None) or []
    if not capas:
        return []
    return [[int(celda) for celda in fila] for fila in capas[-1]]


def _entero(valor: Any, piso: int = 0) -> int:
    try:
        return max(piso, int(valor))
    except (TypeError, ValueError):
        return piso


def _accion_del_frame(frame: Any) -> tuple[str, int | None, int | None]:
    """Nombre de la accion que produjo el frame y, si fue un click, sus coordenadas. Las
    coordenadas de ACTION6 son EL dato que BL.21557 recupero del lado del runner online; aca se
    recuperan del lado del harness local por la misma razon."""
    entrada = getattr(frame, "action_input", None)
    if entrada is None:
        return ACCION_DESCONOCIDA, None, None
    identificador = getattr(entrada, "id", None)
    nombre = getattr(identificador, "name", None) or str(identificador or ACCION_DESCONOCIDA)
    datos = getattr(entrada, "data", None) or {}
    x = datos.get("x") if isinstance(datos, dict) else None
    y = datos.get("y") if isinstance(datos, dict) else None
    return str(nombre), (None if x is None else int(x)), (None if y is None else int(y))


def normalizar_frame(
    frame: Any, paso: int, registrada: AccionRegistrada | None = None
) -> FrameCapturado:
    """Convierte un FrameData del framework oficial al registro que se persiste.

    `registrada` (lo que el agente EMITIO) manda sobre `frame.action_input` (lo que el motor
    ECHO): el motor offline no informa la accion y su default miente."""
    if registrada is not None:
        accion, x, y = registrada.nombre, registrada.x, registrada.y
    else:
        accion, x, y = _accion_del_frame(frame)
    crudo = getattr(frame, "state", None)
    estado = getattr(crudo, "value", None) or str(crudo or "")
    disponibles = getattr(frame, "available_actions", None) or []
    return FrameCapturado(
        paso=paso,
        accion=accion,
        x=x,
        y=y,
        acciones_disponibles=sorted(_entero(a) for a in disponibles),
        grilla=grilla_visible(frame),
        niveles_completados=_entero(getattr(frame, "levels_completed", 0)),
        niveles_para_ganar=_entero(getattr(frame, "win_levels", 0)),
        estado=str(estado),
        reinicio_completo=bool(getattr(frame, "full_reset", False)),
    )


def clases_de_los_frames(
    capturados: Sequence[FrameCapturado], indice_del_evento: int
) -> list[FrameCapturado]:
    """BL.21794 -- CLASIFICA LOS FRAMES EN EL MOMENTO DE CAPTURARLOS y devuelve la lista con la
    clase y la firma puestas.

    POR QUE EN LA CAPTURA Y NO EN EL INFORME (medido, BL.21728/BL.21765). De 100 frames de contexto
    del corpus, 55 son informativos, 27 INERTES (la transicion no cambio ni una celda) y 18 son una
    ANIMACION EN LOOP (ft09: 9 pasos previos que cambian EXACTAMENTE 38 celdas con la ocupacion
    clavada en 0,4727 -- el juego animandose solo, no una maniobra). Esa contabilidad decidia
    cuantos frames REALES sostienen cada veredicto, y hasta este BL se reconstruia en cada corrida
    del informe: el corpus persistido no decia nada sobre sus propios frames, asi que dos informes
    con codigo distinto podian describir la misma muestra de dos maneras y nada lo detectaba.

    LA CLASIFICACION NO ES UNA SEGUNDA IMPLEMENTACION. Se calcula con `pasos_de_la_ventana` +
    `clasificar_pasos`, exactamente las mismas dos funciones que usa `medir_evento`. Por eso el
    informe puede LEER la clase guardada y ademas VERIFICARLA contra su propia re-derivacion: si
    alguna vez difieren, el corpus y el analisis dejaron de hablar de la misma maniobra, y eso tiene
    que romper y no pasar en silencio.

    LOS FRAMES QUE NO SON MANIOBRA SE NOMBRAN, NO SE OMITEN. El primero de la ventana no tiene
    transicion previa (`sinPrevio`), el del evento es el que DEFINE el evento y meterlo en la serie
    fue el defecto 1 de BL.21728 (`elEvento`), y los posteriores describen el tablero del nivel
    SIGUIENTE (`posteriorAlEvento`)."""
    # Import local: `caracterizacion_de_niveles` importa la percepcion objeto-centrica de
    # `arc_agent/`, y este modulo lo cargan tambien herramientas que no clasifican nada. Se paga el
    # import solo cuando se captura de verdad.
    from caracterizacion_de_niveles import pasos_de_la_ventana  # noqa: PLC0415
    from paso_de_la_maniobra import clasificar_pasos  # noqa: PLC0415

    if indice_del_evento <= 0:
        return list(capturados)
    frames_json = [{"paso": f.paso, "grilla": f.grilla} for f in capturados]
    pasos = pasos_de_la_ventana(frames_json, indice_del_evento)
    clases = clasificar_pasos(pasos)
    resultado: list[FrameCapturado] = []
    for i, frame in enumerate(capturados):
        if i == 0:
            resultado.append(replace(frame, clase_de_paso=CLASE_SIN_PREVIO, firma_del_paso=""))
        elif i < indice_del_evento:
            resultado.append(
                replace(
                    frame, clase_de_paso=clases[i - 1], firma_del_paso=pasos[i - 1].firma
                )
            )
        elif i == indice_del_evento:
            resultado.append(replace(frame, clase_de_paso=CLASE_DEL_EVENTO, firma_del_paso=""))
        else:
            resultado.append(
                replace(frame, clase_de_paso=CLASE_POSTERIOR_AL_EVENTO, firma_del_paso="")
            )
    return resultado


def pasos_de_subida_de_nivel(frames: Sequence[Any]) -> list[int]:
    """Indices de los frames donde `levels_completed` SUBIO respecto del frame anterior.

    Solo INCREMENTOS: tras un GAME_OVER + RESET el contador vuelve a 0, y esa BAJADA no es un
    evento. La subida 0 -> 1 posterior si lo es (es un nivel superado de nuevo, con su propia
    maniobra), y por eso el criterio es estrictamente local y no "maximo historico"."""
    eventos: list[int] = []
    for i in range(1, len(frames)):
        previo = _entero(getattr(frames[i - 1], "levels_completed", 0))
        actual = _entero(getattr(frames[i], "levels_completed", 0))
        if actual > previo:
            eventos.append(i)
    return eventos


def acciones_alineadas(
    frames: Sequence[Any], acciones: Sequence[AccionRegistrada] | None
) -> list[AccionRegistrada | None]:
    """Alinea las acciones registradas con los frames: `frames[k]` lo produjo `acciones[k-1]`.

    `frames[0]` es el frame sintetico con el que el framework inicializa la lista: no lo produjo
    ninguna accion. Si los largos NO cuadran (`len(frames) == len(acciones) + 1`), se descarta la
    lista ENTERA y se cae al `action_input` del wire: una lista corrida por uno le atribuye a cada
    frame la accion del anterior, que es evidencia falsa disfrazada de dato."""
    if not acciones or len(frames) != len(acciones) + 1:
        return [None] * len(frames)
    return [None, *acciones]


def ventanas_de_nivel(
    frames: Sequence[Any],
    *,
    juego: str,
    corrida: str,
    modelo: str,
    semilla: str = "",
    antes: int = VENTANA_POR_DEFECTO,
    despues: int = VENTANA_POR_DEFECTO,
    acciones: Sequence[AccionRegistrada] | None = None,
) -> list[VentanaDeNivel]:
    """Ventanas de `antes`+1+`despues` frames alrededor de cada subida de nivel.

    Los frames SIN grilla se descartan (no aportan evidencia visual y romperian el encadenado de
    diffs del corpus). El recorte en los bordes de la partida es real, no rellenado."""
    ancho_antes = max(0, int(antes))
    ancho_despues = max(0, int(despues))
    alineadas = acciones_alineadas(frames, acciones)
    ventanas: list[VentanaDeNivel] = []
    for indice in pasos_de_subida_de_nivel(frames):
        desde = max(0, indice - ancho_antes)
        hasta = min(len(frames) - 1, indice + ancho_despues)
        capturados = [
            normalizar_frame(frames[i], i, alineadas[i]) for i in range(desde, hasta + 1)
        ]
        capturados = [f for f in capturados if f.grilla]
        if not any(f.paso == indice for f in capturados):
            # Sin el frame del evento la ventana no describe el evento: se descarta entera.
            continue
        # BL.21794 -- la clasificacion se decide ACA, con la ventana ya recortada y filtrada, que es
        # exactamente la lista de frames que va a leer el informe. Clasificar antes del filtro
        # describiria una serie que nadie va a analizar.
        capturados = clases_de_los_frames(
            capturados, next(i for i, f in enumerate(capturados) if f.paso == indice)
        )
        ventanas.append(
            VentanaDeNivel(
                juego=juego,
                corrida=corrida,
                modelo=modelo,
                semilla=semilla,
                paso_del_evento=indice,
                nivel_previo=_entero(getattr(frames[indice - 1], "levels_completed", 0)),
                nivel_nuevo=_entero(getattr(frames[indice], "levels_completed", 0)),
                frames=capturados,
            )
        )
    return ventanas


def agregar_a_jsonl(ruta: Path, ventanas: Sequence[VentanaDeNivel]) -> int:
    """Agrega las ventanas al JSONL (una por linea) y devuelve cuantas escribio.

    APPEND y no overwrite: cada juego se corre por separado con su propio presupuesto, y el archivo
    acumula la captura del barrido entero. Una linea por ventana hace que un proceso muerto a mitad
    deje un archivo igualmente legible hasta la ultima linea completa."""
    if not ventanas:
        return 0
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as archivo:
        for ventana in ventanas:
            texto = json.dumps(ventana.a_json(), ensure_ascii=False, separators=(",", ":"))
            archivo.write(texto + "\n")
    return len(ventanas)


def leer_jsonl(ruta: Path) -> list[dict[str, Any]]:
    """Lee el JSONL de ventanas. Ignora lineas vacias y la ultima linea truncada (proceso muerto a
    mitad de una escritura): el resto de la captura sigue siendo evidencia valida."""
    if not ruta.exists():
        return []
    ventanas: list[dict[str, Any]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            ventanas.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    return ventanas


__all__ = [
    "ACCION_DESCONOCIDA",
    "AccionRegistrada",
    "CLASE_DEL_EVENTO",
    "CLASE_POSTERIOR_AL_EVENTO",
    "CLASE_SIN_PREVIO",
    "FrameCapturado",
    "VENTANA_POR_DEFECTO",
    "VentanaDeNivel",
    "acciones_alineadas",
    "clases_de_los_frames",
    "agregar_a_jsonl",
    "describir_accion",
    "grilla_visible",
    "leer_jsonl",
    "normalizar_frame",
    "pasos_de_subida_de_nivel",
    "registrar_acciones",
    "ventanas_de_nivel",
]
