"""[arc-agi3-kaggle-agent/click_targeting] BL.21560 -- DONDE clickear (ACTION6): plantillas de parche
y memoria de clicks del episodio, sobre el ranker de click_features.py.

EL PROBLEMA, medido sobre el corpus real (`arcReplayFrames`, corrida ft09-0d8bbf25): 346 clicks,
32 productivos (9,2%). La heuristica previa (`pick_click_target`) elegia UNIFORMEMENTE entre el decil
superior de celdas "borde de color" -- unos 410 candidatos de 4096, de los cuales solo ~36 son las
esquinas de las fichas del tablero jugable. 36/410 = 8,8%: la tasa medida no era mala suerte, era
exactamente lo que predice tirar al azar dentro de ese conjunto. Y sin memoria: 117 de esos 346
clicks repitieron una coordenada ya probada.

TRES CAPAS, en el orden en que actuan sobre una decision:
  1. PRIOR (offline): puntaje lineal de features de la celda, con pesos ajustados por regresion
     logistica contra clicks reales etiquetados con "el click cambio la grilla" (auto-supervisado,
     no exige haber ganado nunca). Ver scripts/fit_click_priors.py.
  2. PLANTILLA (en vivo): al detectar un click CON efecto se guarda el parche 3x3 que lo rodeaba;
     toda celda con un parche parecido sube al frente. Es lo que convierte un acierto en una
     politica: en ft09 las nueve fichas del tablero tienen el mismo parche en sus esquinas.
  3. MEMORIA (en vivo): mapa (firma, x, y) -> ya probado / produjo cambio. La clave lleva la FIRMA
     del estado y no solo la coordenada -- es exactamente lo que policy.py documentaba como "la
     clave correcta, que hoy no existe": si el tablero cambio, la misma coordenada vuelve a ser
     informativa; si no cambio, repetirla es puro costo.

LA JERARQUIA IMPORTA, y esta medida. El prior sale de UN solo juego, asi que sus pesos estan
regularizados a |2,3| como maximo mientras que plantillas y anti-plantillas valen +-6: la evidencia
que el agente junta DENTRO del episodio manda sobre la que trajo de afuera. Sin eso, en
lp85-305b61c3 -- un juego que no esta en el corpus -- el prior mandaba al agente a la cenefa
decorativa y gasto 403 de 499 clicks ahi.
"""
from __future__ import annotations

from typing import Callable, Sequence

# Import a UN solo nivel: el builder del notebook desmonta los imports relativos con el regex
# `^from \.\w* import .+$`, que no cubre un segundo punto.
# Se re-exportan `CLICK_FEATURE_NAMES`, `ClickFeatureBoard`, `puntuar_celda` y `sigmoide`:
# son la superficie publica de 'donde clickear' y viven aca desde que el modulo existe; el
# split en dos archivos es por limite de tamano, no un cambio de contrato.
from .click_features import CLICK_FEATURE_NAMES, ClickFeatureBoard  # noqa: F401
from .click_features import puntuar_celda, sigmoide  # noqa: F401
from .banderas import MEMORIA_TRANSVERSAL_DE_CLICKS, Banderas, bandera_activa
from .priors import CLICK_PRIORS
from .types import GRID_MAX_COORD
from .world_model import Grid, hash_grid

#: Radio del parche que se guarda como plantilla al detectar un click con efecto (3x3 = radio 1).
RADIO_PARCHE = 1

#: Valor de una celda del parche que cae FUERA de la grilla. -1 no colisiona con ningun color ARC.
PARCHE_FUERA_DE_GRILLA = -1

#: Cuanto suma al logit que el parche de la celda se parezca a una plantilla aprendida. Grande a
#: proposito: una plantilla es evidencia DE ESTA PARTIDA (algo que ya funciono aca), y tiene que
#: pesar mas que cualquier prior aprendido en otras -- los pesos ajustados no pasan de |2,3|.
#: Sigue siendo finito: la memoria de coordenadas probadas se aplica ANTES, asi que una plantilla
#: nunca reancla el agente sobre la misma celda.
BONO_POR_PLANTILLA = 6.0

#: Penalizacion simetrica de una ANTI-PLANTILLA: un parche que ya fallo varias veces. Misma
#: magnitud que el bono porque es la misma clase de evidencia, con el signo dado vuelta.
PENALIZACION_POR_ANTI_PLANTILLA = 6.0

#: Clicks muertos con el MISMO parche antes de descartar toda la clase.
#:
#: POR QUE EXISTE, medido contra la API oficial. Sin esto, el agente recorre las 4096 celdas en
#: orden de prior y, si el prior apunta a una region grande e inerte, se la barre entera: en
#: lp85-305b61c3 gasto 403 de 499 clicks en la cenefa decorativa del borde. Con anti-plantillas esa
#: region completa se descarta a los dos fallos, porque todas sus celdas comparten el mismo parche.
#: Es la mitad negativa de la misma idea que ya hacia falta para la positiva: lo que importa no es
#: la coordenada, es el TIPO DE LUGAR.
#:
#: 2 y no 1 por el mismo criterio que `NO_OP_CONFIRMATIONS`: un solo frame identico puede ser ruido
#: del entorno. Una plantilla POSITIVA sobre el mismo parche gana siempre -- evidencia de efecto
#: real le gana a "aca no paso nada", igual que una accion premiada nunca se trata como no-op.
ANTI_PLANTILLA_MIN_FALLOS = 2

#: BL.21702 -- cuanto BAJA el puntaje de una celda por cada vez que se la REPITE en el episodio,
#: MIRE LA FIRMA QUE MIRE. El primer click de cada celda es gratis; el segundo y los siguientes
#: pagan.
#:
#: POR QUE, medido en los entornos reales (151 acciones por juego, semilla bl21702a): la memoria de
#: clicks se indexa por `(firma, x, y)`, asi que una firma nueva vacia la cobertura y
#: `elegir_objetivo` devuelve OTRA VEZ la celda de mayor puntaje. En los juegos donde el frame
#: nunca se repite -- que son justo aquellos donde la mascara de volatilidad quedo en 0 celdas --
#: eso degenera en clickear siempre el mismo punado de celdas: tn36 9 coordenadas distintas en 149
#: clicks, su15 5 en 138, dc22 5 en 8, sb26 13 en 16. Cobertura del orden del 0,2% de las 4.096
#: celdas del frame. La decision que importa en un juego de click no es QUE accion sino DONDE, y
#: esa dimension no tenia ninguna memoria transversal al estado.
#:
#: QUE SE CUENTA DEPENDE DE SI LA SENAL DE CAMBIO INFORMA ALGO, y las dos variantes se MIDIERON,
#: cada una gana en un regimen y pierde en el otro:
#:
#:   | penalizar por...        | ft09 (corpus real, senal util) | juguete su15/tn36 (senal muerta) |
#:   | ----------------------- | ------------------------------ | -------------------------------- |
#:   | clicks ESTERILES        | 232 -> 293 productivos         | 16 -> 16 celdas (nada)           |
#:   | REPETICIONES a secas    | 232 -> 210 productivos         | 16 -> 36 celdas                  |
#:
#: La lectura: donde el cambio DISCRIMINA (ft09: muchos clicks no mueven nada), castigar fallos es
#: estrictamente mejor -- el agente vuelve gratis a la celda que funciona. Donde el cambio NO
#: discrimina -- que es el caso de los siete juegos atascados, con la mascara en 0 celdas y el
#: frame animando en cada paso, asi que `hubo_cambio` es SIEMPRE verdadero -- una memoria de fallos
#: no acumula nada y la unica senal que queda es la repeticion misma.
#:
#: Por eso `penalizacion_transversal` elige el contador segun el REGIMEN OBSERVADO (ver
#: `senal_de_cambio_degenerada`), en vez de apostar a uno de los dos.
#:
#: LA MAGNITUD NO ES LIBRE: `TOPE_DE_REPETICIONES_POR_CELDA` repeticiones saturan la penalizacion
#: justo en `PENALIZACION_POR_ANTI_PLANTILLA` -- y tambien en `BONO_POR_PLANTILLA`, que es la parte
#: importante: una celda que YA FUNCIONO conserva su bono de plantilla y sale empatada consigo
#: misma en el peor caso, nunca por debajo del fondo. El castigo mueve al agente de una celda
#: gastada; no lo ciega frente a un boton que sirve.
PENALIZACION_POR_REPETICION_DE_CELDA = 2.0

#: Clicks minimos antes de juzgar si la senal de cambio DISCRIMINA. Con menos, "todos cambiaron"
#: es una coincidencia esperable y no una propiedad del juego.
CLICKS_PARA_JUZGAR_LA_SENAL = 8

#: Repeticiones que acumula UNA celda antes de saturar la penalizacion. Que sature es deliberado:
#: sin tope, una celda castigada mil veces quedaria por debajo de cualquier otra para siempre y la
#: memoria transversal se volveria el lockout absorbente que BL.21518 tuvo que desarmar del lado de
#: los no-ops. En ARC-AGI-3 el efecto de un click depende del estado global: un boton inerte
#: empieza a servir cuando se abre una puerta.
TOPE_DE_REPETICIONES_POR_CELDA = 3

Coordenada = tuple[int, int]


def extraer_parche(grid: Grid, x: int, y: int) -> tuple[int, ...]:
    """Parche cuadrado de lado 2*RADIO_PARCHE+1 centrado en (x,y), aplanado en orden row-major.
    Las celdas fuera de la grilla valen PARCHE_FUERA_DE_GRILLA."""
    alto = len(grid)
    ancho = len(grid[0]) if alto > 0 else 0
    parche: list[int] = []
    for dy in range(-RADIO_PARCHE, RADIO_PARCHE + 1):
        for dx in range(-RADIO_PARCHE, RADIO_PARCHE + 1):
            px, py = x + dx, y + dy
            dentro = 0 <= px < ancho and 0 <= py < alto
            parche.append(grid[py][px] if dentro else PARCHE_FUERA_DE_GRILLA)
    return tuple(parche)


def similitud_de_parche(a: Sequence[int], b: Sequence[int]) -> float:
    """Fraccion de celdas iguales entre dos parches, en [0,1]."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(1 for i in range(n) if a[i] == b[i]) / n


def region_que_cambio(
    pre: Grid | None, post: Grid | None
) -> tuple[int, int, int, int] | None:
    """Rectangulo que cambio entre dos grillas, o None si no cambio nada / no son comparables."""
    if pre is None or post is None:
        return None
    min_x = min_y = 1 << 30
    max_x = max_y = -1
    for y in range(min(len(pre), len(post))):
        for x in range(min(len(pre[y]), len(post[y]))):
            if pre[y][x] == post[y][x]:
                continue
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
    if max_x < min_x:
        return None
    return (min_x, min_y, max_x, max_y)


def _random_coord(rng: Callable[[], float]) -> int:
    return int(rng() * (GRID_MAX_COORD + 1))


def pick_click_target(
    grid: tuple[tuple[int, ...], ...], rng: Callable[[], float]
) -> tuple[int, int]:
    """HEURISTICA PREVIA a BL.21560, conservada como CAMINO DE RESPALDO: elige (x, y) priorizando
    celdas en el BORDE de una region de color distinto, uniformemente dentro del decil superior.

    Ya no decide una partida -- decide `ClickMemory.elegir_objetivo`, que la contiene como caso
    particular (la feature `bordeDeColor` sigue en el vector) y le agrega prior aprendido, plantillas
    y memoria. Se mantiene porque es la referencia contra la que se mide la mejora: su tasa de
    acierto sobre la partida real grabada es 9,2%, y ese numero solo se puede volver a medir si la
    funcion existe. Vive en este modulo y no en policy.py porque comparte dominio (donde clickear) y
    porque policy.py esta en su limite de tamano."""
    if not grid or not grid[0]:
        return _random_coord(rng), _random_coord(rng)

    height = len(grid)
    width = len(grid[0])
    scored: list[tuple[int, int, int]] = []
    for y in range(height):
        row = grid[y]
        for x in range(width):
            value = row[x]
            score = 0
            if x > 0 and row[x - 1] != value:
                score += 1
            if x + 1 < width and row[x + 1] != value:
                score += 1
            if y > 0 and grid[y - 1][x] != value:
                score += 1
            if y + 1 < height and grid[y + 1][x] != value:
                score += 1
            if score > 0:
                scored.append((score, x, y))

    if not scored:
        return _random_coord(rng), _random_coord(rng)

    scored.sort(key=lambda item: item[0], reverse=True)
    top_k = scored[: max(1, len(scored) // 10)]
    choice_index = int(rng() * len(top_k))
    _, x, y = top_k[choice_index]
    return x, y


class ClickMemory:
    """Memoria de clicks de UN episodio (capas 2 y 3). Una instancia por partida, igual que la
    politica que la contiene."""

    __slots__ = (
        "_probadas",
        "_clicks_por_celda",
        "_esteriles_por_celda",
        "_clicks_totales",
        "_clicks_sin_cambio",
        "_celdas_clickeadas",
        "_transversal",
        "_plantillas",
        "_anti_plantillas",
        "_fallos_por_parche",
        "_centros_de_plantilla",
        "_pesos",
        "_umbral_similitud",
        "_cache_clave",
        "_cache_puntajes",
        "_cache_orden",
    )

    def __init__(
        self,
        pesos: Sequence[float] | None = None,
        umbral_similitud: float | None = None,
        banderas: Banderas | None = None,
    ) -> None:
        # (firma, x, y) -> el click produjo cambio.
        self._probadas: dict[tuple[int, int, int], bool] = {}
        # BL.21702 -- COBERTURA TRANSVERSAL AL ESTADO: (x, y) -> clicks acumulados en el episodio,
        # sin importar desde que firma. Es la memoria que faltaba; `_probadas` la tenia solo DENTRO
        # de una firma y en estos juegos la firma no se repite nunca.
        self._clicks_por_celda: dict[Coordenada, int] = {}
        # Clicks esteriles por celda, tambien transversal. Es el contador PREFERIDO cuando la senal
        # de cambio discrimina: castiga lo que no sirvio sin castigar lo que si.
        self._esteriles_por_celda: dict[Coordenada, int] = {}
        # Totales del episodio, para decidir el regimen (ver `senal_de_cambio_degenerada`).
        self._clicks_totales = 0
        self._clicks_sin_cambio = 0
        # Coordenadas distintas clickeadas en el episodio -- la METRICA de la palanca (medido antes:
        # 9 en 149 clicks, 5 en 138, 5 en 8, 13 en 16).
        self._celdas_clickeadas: set[Coordenada] = set()
        self._transversal = bandera_activa(MEMORIA_TRANSVERSAL_DE_CLICKS, banderas)
        self._plantillas: list[tuple[int, ...]] = []
        # Parches que ya fallaron `ANTI_PLANTILLA_MIN_FALLOS` veces, y el conteo que lleva a serlo.
        self._anti_plantillas: set[tuple[int, ...]] = set()
        self._fallos_por_parche: dict[tuple[int, ...], int] = {}
        # Valores centrales presentes entre las plantillas -- rechazo rapido: una celda cuyo color no
        # es el centro de NINGUNA plantilla no puede parecerse a ninguna con un umbral alto, y
        # saltearla evita extraer su parche. Es lo que hace que puntuar 4096 celdas sea barato.
        self._centros_de_plantilla: set[int] = set()
        self._pesos = tuple(pesos if pesos is not None else CLICK_PRIORS["pesosClick"])
        self._umbral_similitud = (
            umbral_similitud
            if umbral_similitud is not None
            else CLICK_PRIORS["umbralesDetectores"]["similitudDeParcheMinima"]
        )
        # Cache de UNA entrada de los puntajes por celda. En ARC-AGI-3 la mayoria de los clicks no
        # cambian nada, asi que la MISMA grilla se puntua muchos pasos seguidos: sin cache, cada
        # decision re-segmenta el frame entero (medido: 33 grillas distintas en 346 pasos de ft09).
        self._cache_clave: tuple[int, object, int] | None = None
        self._cache_puntajes: list[float] = []
        self._cache_orden: list[int] = []

    @property
    def plantillas_aprendidas(self) -> int:
        return len(self._plantillas)

    @property
    def anti_plantillas_aprendidas(self) -> int:
        return len(self._anti_plantillas)

    @property
    def coordenadas_probadas(self) -> int:
        return len(self._probadas)

    @property
    def celdas_distintas_clickeadas(self) -> int:
        """BL.21702 -- coordenadas DISTINTAS clickeadas en el episodio, sin importar la firma. Es
        la magnitud que la palanca de memoria transversal existe para mover; los tests de efecto y
        el reporte de corrida la afirman."""
        return len(self._celdas_clickeadas)

    @property
    def memoria_transversal_activa(self) -> bool:
        """Observabilidad: si la palanca de BL.21702 esta encendida en esta partida."""
        return self._transversal

    def clicks_en(self, x: int, y: int) -> int:
        """Clicks que acumulo esa celda en el episodio, mire la firma que mire."""
        return self._clicks_por_celda.get((x, y), 0)

    def clicks_esteriles_en(self, x: int, y: int) -> int:
        """Clicks sin cambio que acumulo esa celda en el episodio, mire la firma que mire."""
        return self._esteriles_por_celda.get((x, y), 0)

    @property
    def senal_de_cambio_degenerada(self) -> bool:
        """La senal `hubo_cambio` dejo de distinguir: TODOS los clicks del episodio "cambiaron el
        tablero".

        Es exactamente el estado de los siete juegos atascados -- mascara de volatilidad en 0
        celdas y frame que anima en cada paso -- y es lo que decide cual de los dos contadores
        transversales manda. Se exigen `CLICKS_PARA_JUZGAR_LA_SENAL` clicks antes de afirmarlo:
        con dos o tres, "todos cambiaron" es coincidencia."""
        return (
            self._clicks_totales >= CLICKS_PARA_JUZGAR_LA_SENAL
            and self._clicks_sin_cambio == 0
        )

    def penalizacion_transversal(self, x: int, y: int) -> float:
        """Cuanto baja el puntaje de una celda por su historial en CUALQUIER estado.

        Cuando la senal de cambio discrimina se cuentan los clicks ESTERILES de la celda: el agente
        vuelve gratis a lo que funciona. Cuando la senal es degenerada se cuentan las REPETICIONES
        (el primer click de cada celda sigue siendo gratis), porque ahi "no fallo nunca" no
        significa nada. Los dos regimenes estan medidos en el encabezado de las constantes.

        Con la palanca apagada devuelve 0.0 exacto -- y `puntaje - 0.0 == puntaje` en coma
        flotante, asi que el orden de seleccion queda IDENTICO al previo a BL.21702. Esa identidad
        es lo que permite medir la linea base con la misma build."""
        if not self._transversal or not self._clicks_por_celda:
            return 0.0
        if self.senal_de_cambio_degenerada:
            unidades = self._clicks_por_celda.get((x, y), 0) - 1
        else:
            unidades = self._esteriles_por_celda.get((x, y), 0)
        if unidades <= 0:
            return 0.0
        return PENALIZACION_POR_REPETICION_DE_CELDA * min(
            unidades, TOPE_DE_REPETICIONES_POR_CELDA
        )

    def registrar_resultado(
        self, firma: int, x: int, y: int, hubo_cambio: bool, grid_previa: Grid | None
    ) -> None:
        """Atribuye el resultado del click anterior. `grid_previa` es la grilla SOBRE LA QUE se
        clickeo: el parche de la plantilla tiene que describir lo que se veia al decidir, no lo que
        quedo despues (que ya cambio justamente por el click)."""
        self._probadas[(firma, x, y)] = hubo_cambio
        self._celdas_clickeadas.add((x, y))
        # BL.21702 -- se llevan LOS DOS contadores transversales porque `penalizacion_transversal`
        # elige entre ellos segun el regimen: clicks totales (repeticion) y clicks esteriles. Un
        # click con efecto BORRA el historial esteril de esa celda -- evidencia de efecto real
        # desmiente el historial de fallos, igual que una plantilla positiva desmiente su
        # anti-plantilla -- pero NO borra el conteo de repeticiones, que es puro presupuesto.
        self._clicks_por_celda[(x, y)] = self._clicks_por_celda.get((x, y), 0) + 1
        self._clicks_totales += 1
        if hubo_cambio:
            self._esteriles_por_celda.pop((x, y), None)
        else:
            self._clicks_sin_cambio += 1
            self._esteriles_por_celda[(x, y)] = self._esteriles_por_celda.get((x, y), 0) + 1
        if grid_previa is None:
            return
        parche = extraer_parche(grid_previa, x, y)

        if not hubo_cambio:
            fallos = self._fallos_por_parche.get(parche, 0) + 1
            self._fallos_por_parche[parche] = fallos
            if fallos >= ANTI_PLANTILLA_MIN_FALLOS and parche not in self._anti_plantillas:
                self._anti_plantillas.add(parche)
                self._centros_de_plantilla.add(parche[len(parche) // 2])
                self._cache_clave = None  # la anti-plantilla nueva cambia los puntajes
            return

        if parche in self._plantillas:
            return
        self._plantillas.append(parche)
        self._centros_de_plantilla.add(parche[len(parche) // 2])
        # Evidencia de efecto real desmiente cualquier marca de "aca no pasa nada" sobre ese parche.
        self._anti_plantillas.discard(parche)
        self._fallos_por_parche.pop(parche, None)
        self._cache_clave = None  # la plantilla nueva cambia los puntajes

    def _bono_de_plantilla(self, grid: Grid, x: int, y: int) -> float:
        """Ajuste del puntaje por evidencia DE ESTA PARTIDA: +bono si el parche de la celda coincide
        con uno que ya funciono, -penalizacion si coincide con uno que ya fallo varias veces. La
        positiva gana: haber visto un efecto real le gana a no haber visto nada."""
        if not self._centros_de_plantilla or grid[y][x] not in self._centros_de_plantilla:
            return 0.0
        parche = extraer_parche(grid, x, y)
        if self._plantillas:
            mejor = max(similitud_de_parche(parche, p) for p in self._plantillas)
            if mejor >= self._umbral_similitud:
                return BONO_POR_PLANTILLA
        if self._anti_plantillas:
            peor = max(similitud_de_parche(parche, p) for p in self._anti_plantillas)
            if peor >= self._umbral_similitud:
                return -PENALIZACION_POR_ANTI_PLANTILLA
        return 0.0

    def puntajes_por_celda(
        self, grid: Grid, region_cambiada: tuple[int, int, int, int] | None = None
    ) -> list[float]:
        """Puntaje (logit + bono de plantilla) de cada celda, row-major. Cacheado por grilla y por
        cantidad de plantillas: es puro, depende solo de esos dos."""
        clave = (
            hash_grid(grid),
            region_cambiada,
            len(self._plantillas) * 1000 + len(self._anti_plantillas),
        )
        if self._cache_clave == clave:
            return self._cache_puntajes

        tablero = ClickFeatureBoard(grid, region_cambiada)
        pesos = self._pesos
        puntajes: list[float] = []
        for y in range(tablero.alto):
            for x in range(tablero.ancho):
                puntajes.append(
                    puntuar_celda(tablero.features(x, y), pesos)
                    + self._bono_de_plantilla(grid, x, y)
                )
        self._cache_clave = clave
        self._cache_puntajes = puntajes
        self._cache_orden = sorted(range(len(puntajes)), key=lambda i: -puntajes[i])
        return puntajes

    def elegir_objetivo(
        self,
        grid: Grid,
        firma: int,
        rng: Callable[[], float],
        region_cambiada: tuple[int, int, int, int] | None = None,
    ) -> Coordenada:
        """Coordenada a clickear: la celda NO PROBADA en este estado con mayor puntaje EFECTIVO. Si
        todas se probaron, se prefiere una que YA produjo cambio (un boton que funciono vuelve a
        funcionar) antes que una muerta.

        BL.21702 -- puntaje EFECTIVO = puntaje de la celda menos su `penalizacion_transversal`, o
        sea su historial en CUALQUIER estado (fallos o repeticiones, segun el regimen). Sin ese
        termino, en los juegos donde la firma nunca se repite la memoria por firma no bloquea nada
        y el ranker devuelve siempre la misma celda (medido: 5 coordenadas en 138 clicks). Con la
        palanca apagada la penalizacion es 0.0 exacto y la seleccion es identica a la previa.

        Recorre las celdas en orden de puntaje BASE descendente (precalculado junto con los
        puntajes) y corta apenas el puntaje base ya no puede superar al mejor efectivo encontrado
        -- la penalizacion solo RESTA, asi que ese corte es exacto, no una aproximacion.

        Consume EXACTAMENTE un numero del rng, igual que la heuristica que reemplaza: la
        reproducibilidad de una partida dado su seed depende de que la secuencia del rng no varie
        con el contenido de la memoria."""
        alto = len(grid)
        ancho = len(grid[0]) if alto > 0 else 0
        if ancho == 0 or alto == 0:
            return 0, 0

        puntajes = self.puntajes_por_celda(grid, region_cambiada)
        orden = self._cache_orden
        probadas = self._probadas
        sorteo = rng()

        # Primera pasada: el mejor puntaje EFECTIVO entre las celdas no probadas en esta firma.
        mejor: float | None = None
        for i in orden:
            if mejor is not None and puntajes[i] <= mejor:
                break  # ninguna celda posterior puede superarlo: la penalizacion nunca suma
            x, y = i % ancho, i // ancho
            if (firma, x, y) in probadas:
                continue
            efectivo = puntajes[i] - self.penalizacion_transversal(x, y)
            if mejor is None or efectivo > mejor:
                mejor = efectivo

        # Segunda pasada: TODAS las empatadas en ese maximo, para que el sorteo elija entre ellas
        # sin sesgo posicional (mismo criterio que antes de BL.21702).
        empatadas: list[int] = []
        if mejor is not None:
            for i in orden:
                if puntajes[i] < mejor:
                    break
                x, y = i % ancho, i // ancho
                if (firma, x, y) in probadas:
                    continue
                if puntajes[i] - self.penalizacion_transversal(x, y) == mejor:
                    empatadas.append(i)
        if not empatadas:
            # Todas probadas en este estado: se prefiere la de mayor puntaje que YA produjo cambio.
            for productiva in (True, False):
                for i in orden:
                    if probadas.get((firma, i % ancho, i // ancho)) is productiva:
                        empatadas = [i]
                        break
                if empatadas:
                    break
        if not empatadas:
            return 0, 0
        elegida = empatadas[int(sorteo * len(empatadas)) % len(empatadas)]
        return elegida % ancho, elegida // ancho
