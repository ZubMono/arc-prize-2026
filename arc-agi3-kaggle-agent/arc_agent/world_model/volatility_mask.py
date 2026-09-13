"""[arc-agi3-kaggle-agent/world_model/volatility_mask] BL.21558 -- aprende, DURANTE el episodio,
que celdas del frame cambian sin relacion con la accion ejecutada (HUD, contador de pasos, barra de
progreso) para que el resto del modelo de mundo pueda ignorarlas. Puerto de
arc-agi-runner/src/worldModel/volatilityMask.ts.

EL PROBLEMA MEDIDO. Los juegos publicos de ARC-AGI-3 producen un frame distinto en cada paso pase
lo que pase: ar25-0c556536 = 76 firmas unicas / 78 pasos; lf52-271a04aa = 94/94; dc22-fdcac232 =
128/129; ka59 = 100/101. Con esas celdas dentro de la comparacion, `grids_equal` no devuelve True
nunca y se cae la cadena entera: no se detecta ningun no-op, `synthesize_program` tendria que
explicar tambien el contador (imposible con un DSL de tablero) y ninguna firma de estado se repite,
con lo cual la memoria por-estado de policy.py queda inerte.

DOS FAMILIAS DE RUIDO, PORQUE EL DATO REAL MOSTRO DOS FORMAS DISTINTAS. La primera version de este
modulo solo tenia la familia 1 y, medida contra frames REALES capturados de la API oficial,
enmascaraba CERO celdas en los cuatro juegos citados: el ruido de ARC-AGI-3 no es un digito que
parpadea, es una BARRA que avanza.

Familia 1 -- celda que cambia casi siempre, bajo TODAS las acciones. Se exige
VOLATILITY_MIN_TRANSITIONS transiciones, VOLATILITY_MIN_DISTINCT_ACTIONS acciones distintas y, para
CADA accion observada, un ratio de cambio >= VOLATILITY_ENTRY_RATIO en SUS transiciones. Esa ultima
condicion es la que protege el tablero: el marcador del jugador cambia bajo las acciones de
movimiento pero NO bajo una accion inerte, asi que basta una accion que no lo mueva para que nunca
entre; un contador de HUD, en cambio, cambia igual bajo todas.

Familia 2 -- CONTADOR DE BARRIDO: una barra donde se enciende UNA celda nueva por paso. Medido
sobre partidas reales completas (82-125 transiciones cada una): lf52 fila 0 (1x64, avanza en el 100%
de los pasos), ar25 columna 63 (78%), dc22 fila 63 (51%), ka59 fila 63 (64%). La familia 1 no puede
verlas: cada celda de la barra cambia UNA sola vez en todo el episodio. El criterio que si las ve
mira la REGION: una componente conexa de >= SWEEP_MIN_CELLS celdas con forma de LINEA de una celda
de ancho, cuyos cambios ocurrieron casi siempre en SOLEDAD (ninguna otra celda cambiando a distancia
SWEEP_ISOLATION_RADIUS) y que registro cambios en >= SWEEP_ENTRY_RATIO de las transiciones, bajo
>= 2 acciones distintas.

POR QUE ESE CRITERIO NO SE COME EL TABLERO. Un objeto que se mueve cambia SIEMPRE 2 celdas
adyacentes a la vez: no pasa el filtro de soledad. Un tablero que responde cambia en bloques
(mediana medida: 108 celdas por paso en ar25, 18 en ka59): tampoco. Y una region 2D de celdas que
se encienden de a una queda afuera por el requisito de forma de linea.

POR QUE CONSERVADOR. Enmascarar una celda del TABLERO es mucho peor que no enmascarar una del HUD:
el agente se volveria ciego justo donde esta la señal, y no enmascarar es exactamente el
comportamiento previo a este BL. De ahi los umbrales altos y el tope VOLATILITY_MAX_FRACTION.

HISTERESIS. Salir de la mascara pide un ratio mas bajo que entrar (VOLATILITY_EXIT_RATIO,
SWEEP_EXIT_RATIO). Sin esa banda muerta, algo parado en el umbral entraria y saldria paso a paso y
las firmas de estado volverian a ser irrepetibles -- el defecto que este modulo existe para
arreglar.
"""
from __future__ import annotations

from typing import Final

# Import relativo en UNA sola linea: submission/build_notebook.py los desmonta con el regex
# `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el notebook.
from .grid import Grid, VolatilityMask

#: Transiciones minimas antes de afirmar nada. Por debajo, cualquier ratio es ruido.
VOLATILITY_MIN_TRANSITIONS: Final[int] = 6

#: Acciones distintas minimas. Con una sola, "cambia siempre" y "esta accion la cambia siempre" son
#: indistinguibles -- y confundirlas enmascararia justo el efecto que hay que aprender.
VOLATILITY_MIN_DISTINCT_ACTIONS: Final[int] = 2

#: BL.21702 -- MODO DE ACCION UNICA. `VOLATILITY_MIN_DISTINCT_ACTIONS` = 2 vuelve la mascara
#: IMPOSIBLE POR CONSTRUCCION en los juegos que exponen un solo boton, y SEIS de los 25 publicos
#: exponen `availableActions=[6]`: ft09, lp85, r11l, s5i5, tn36, vc33. Medido en los siete juegos
#: atascados, la mascara termino en CERO celdas en todos -- y sin mascara ninguna firma de estado
#: se repite, con lo cual la memoria por estado de `policy.py` queda inerte de punta a punta.
#:
#: EL ARGUMENTO ORIGINAL SIGUE EN PIE, y por eso el modo no relaja el criterio sino que lo CAMBIA:
#: cuando hay un solo boton no queda ninguna accion de control con la que contrastar, asi que lo
#: unico que puede separar el HUD del tablero es cuan ABSOLUTA es la regularidad. De ahi los
#: umbrales de abajo, mucho mas altos que los normales. Y la familia 2 (barra de barrido) nunca
#: dependio del conteo de acciones: su criterio es de FORMA (linea de una celda de ancho, sobre un
#: borde) y de SOLEDAD (>=90% de los cambios sin compania alrededor), que un tablero que responde
#: no cumple -- ahi el minimo de acciones era una salvaguarda redundante.
#:
#: El modo se activa SOLO cuando el juego declara un vocabulario de una accion
#: (`declarar_vocabulario`), no cuando todavia no se observo una segunda: en un juego de varias
#: acciones una macro puede dejar 8 transiciones seguidas del mismo boton, y ahi el contraste
#: existe, solo que aun no se midio.
VOLATILITY_MIN_TRANSITIONS_ACCION_UNICA: Final[int] = 12

#: Fraccion de transiciones en las que la celda debe cambiar para entrar a la mascara en modo de
#: accion unica. 0.98 y no 0.85: sin una segunda accion con la que contrastar, lo unico que
#: distingue un contador de HUD de una celda del tablero es que el contador cambia en CASI TODAS
#: las transiciones sin excepcion. Una celda del tablero de un juego de click cambia cuando se
#: clickea cerca, no en 49 de cada 50 pasos; y si el frame entero se moviera asi,
#: `VOLATILITY_MAX_FRACTION` desactiva la mascara igual.
VOLATILITY_ENTRY_RATIO_ACCION_UNICA: Final[float] = 0.98

#: Salida de la mascara en modo de accion unica (HISTERESIS). Mas alta que `VOLATILITY_EXIT_RATIO`
#: en la misma proporcion en que la entrada es mas alta: la banda muerta conserva su ancho relativo.
VOLATILITY_EXIT_RATIO_ACCION_UNICA: Final[float] = 0.85

#: Fraccion de transiciones DE CADA ACCION en las que la celda debe cambiar para entrar. Alto a
#: proposito, pero no 1.0: un digito dibujado con sprites comparte pixeles entre glifos
#: consecutivos (8 -> 9), asi que con 1.0 el contador quedaria a medio enmascarar.
VOLATILITY_ENTRY_RATIO: Final[float] = 0.85

#: Fraccion por debajo de la cual una celda ya enmascarada vuelve a contar (ver HISTERESIS).
VOLATILITY_EXIT_RATIO: Final[float] = 0.6

#: Si el conjunto volatil superara esta fraccion del frame, la mascara se desactiva por completo.
#: Un frame que muta en mas de la mitad de sus celdas pase lo que pase no tiene un HUD ruidoso: no
#: es observable con este modelo, y enmascararlo dejaria al agente decidiendo sobre casi nada.
VOLATILITY_MAX_FRACTION: Final[float] = 0.5

#: Celdas minimas de una barra de progreso. Las cuatro medidas en juego real tienen 64 (un borde
#: entero del frame); el piso tolera barras mas cortas sin que un par de celdas sueltas del tablero
#: alcancen a formar una.
SWEEP_MIN_CELLS: Final[int] = 16

#: Transiciones minimas para evaluar la familia 2: el estadistico se calcula sobre la REGION, y con
#: pocas transiciones cualquier region chica pasaria el ratio por casualidad.
SWEEP_MIN_TRANSITIONS: Final[int] = 12

#: Fraccion de las transiciones del episodio en las que la barra tiene que haber avanzado para
#: entrar. Medido: 1.00 (lf52), 0.78 (ar25), 0.64 (ka59), 0.51 (dc22).
SWEEP_ENTRY_RATIO: Final[float] = 0.4

#: Ratio por debajo del cual una barra ya enmascarada vuelve a contar (ver HISTERESIS).
SWEEP_EXIT_RATIO: Final[float] = 0.25

#: Radio (Chebyshev) dentro del cual NO puede haber otra celda cambiando en la misma transicion para
#: considerar que el cambio ocurrio en soledad.
SWEEP_ISOLATION_RADIUS: Final[int] = 2

#: Fraccion de los cambios de la REGION que tuvieron que ocurrir en soledad. Se mide sobre la region
#: entera y no celda por celda: si un cambio del tablero pasa cerca de la barra, la celda afectada
#: no puede quedar descalificada para siempre.
SWEEP_MIN_ISOLATION_RATIO: Final[float] = 0.9


class _ContadoresDeAccion:
    """Transiciones observadas de una accion y, por celda, en cuantas de ellas cambio."""

    __slots__ = ("transiciones", "cambios")

    def __init__(self) -> None:
        self.transiciones: int = 0
        self.cambios: list[list[int]] = []


def _crecer_matriz(matriz: list[list[int]], height: int, width: int) -> None:
    while len(matriz) < height:
        matriz.append([])
    for row in matriz:
        while len(row) < width:
            row.append(0)


def _crecer_matriz_bool(matriz: list[list[bool]], height: int, width: int) -> None:
    while len(matriz) < height:
        matriz.append([])
    for row in matriz:
        while len(row) < width:
            row.append(False)


def _es_linea(celdas: list[int], width: int) -> bool:
    """True si la componente es una linea de UNA celda de ancho (fila o columna). Es la forma de una
    barra de progreso y NO la de una region del tablero que se enciende de a una celda -- el falso
    positivo mas peligroso, porque dejaria al agente ciego justo donde esta la señal."""
    min_y = min(indice // width for indice in celdas)
    max_y = max(indice // width for indice in celdas)
    min_x = min(indice % width for indice in celdas)
    max_x = max(indice % width for indice in celdas)
    return min_y == max_y or min_x == max_x


class VolatilityTracker:
    """Acumula evidencia transicion a transicion y expone la mascara vigente. UNA instancia por
    episodio: la volatilidad es una propiedad del juego EN CURSO, no del agente."""

    def __init__(self, permitir_accion_unica: bool = False) -> None:
        # BL.21702 -- `permitir_accion_unica` llega por PARAMETRO y no leyendo `banderas.py`: este
        # modulo vive en el subpaquete `world_model/` y el builder del notebook solo desmonta
        # imports relativos de UN punto, asi que importar `banderas` desde aca (dos puntos) dejaria
        # el entregable con un ImportError. La palanca la resuelve `policy.py` y la baja hasta aca.
        self._permitir_accion_unica = permitir_accion_unica
        #: Acciones que el juego DECLARA (no las que se observaron todavia). 0 = sin declarar.
        self._vocabulario = 0
        self._por_accion: dict[str, _ContadoresDeAccion] = {}
        self._volatile: list[list[bool]] = []
        # Familia 1 y familia 2 se guardan por separado: comparten el tope y la version, pero cada
        # una tiene su histeresis y mezclarlas haria que una celda que entro por barrido saliera por
        # el umbral de frecuencia (y al reves).
        self._volatil_frecuencia: list[list[bool]] = []
        self._volatil_barrido: list[list[bool]] = []
        self._cambios_totales: list[list[int]] = []
        self._cambios_aislados: list[list[int]] = []
        self._height = 0
        self._width = 0
        self._transiciones = 0
        self._volatile_count = 0
        self._desactivada_por_tope = False
        self._version = 0

    def declarar_vocabulario(self, cantidad_de_acciones: int) -> None:
        """BL.21702 -- cuantas acciones OFRECE el juego. Es lo que habilita el modo de accion
        unica: que solo se haya observado un boton no significa que el juego tenga uno solo."""
        self._vocabulario = max(self._vocabulario, int(cantidad_de_acciones))

    @property
    def modo_de_accion_unica(self) -> bool:
        """El juego declara UN solo boton y la palanca de BL.21702 esta encendida."""
        return self._permitir_accion_unica and self._vocabulario == 1

    def observe(self, action: str, pre: Grid, post: Grid) -> None:
        """Registra una transicion observada `pre -> post` bajo `action`. No muta ni retiene las
        grillas."""
        height = max(len(pre), len(post))
        width = max(
            max((len(row) for row in pre), default=0),
            max((len(row) for row in post), default=0),
        )
        if height == 0 or width == 0:
            return

        self._crecer_hasta(height, width)
        self._transiciones += 1

        contadores = self._contadores_de(action)
        contadores.transiciones += 1
        _crecer_matriz(contadores.cambios, self._height, self._width)

        cambiadas: list[int] = []
        for y in range(self._height):
            fila_pre = pre[y] if y < len(pre) else []
            fila_post = post[y] if y < len(post) else []
            for x in range(self._width):
                # Celda ausente en un lado: se compara contra el centinela -1 (mismo criterio que
                # cell_diff_count), asi que aparecer/desaparecer cuenta como cambio.
                valor_pre = fila_pre[x] if x < len(fila_pre) else -1
                valor_post = fila_post[x] if x < len(fila_post) else -1
                if valor_pre != valor_post:
                    contadores.cambios[y][x] += 1
                    self._cambios_totales[y][x] += 1
                    cambiadas.append(y * self._width + x)

        self._registrar_soledad(cambiadas)
        self._recomputar()

    @property
    def mask(self) -> VolatilityMask | None:
        """Mascara vigente, o None si todavia no hay evidencia suficiente (o si se desactivo por el
        tope de fraccion). None significa "compara todo", el comportamiento previo a este BL."""
        if self._volatile_count == 0 or self._desactivada_por_tope:
            return None
        return self._volatile

    @property
    def version(self) -> int:
        """Cambia cada vez que cambia el conjunto de celdas volatiles. Quien cachee algo derivado de
        la mascara (una firma de estado, por ejemplo) compara esta version para saber que lo
        cacheado dejo de ser comparable."""
        return self._version

    def volatile_cell_count(self) -> int:
        return 0 if self._desactivada_por_tope else self._volatile_count

    def observed_transitions(self) -> int:
        return self._transiciones

    def _contadores_de(self, action: str) -> _ContadoresDeAccion:
        existente = self._por_accion.get(action)
        if existente is not None:
            return existente
        nuevo = _ContadoresDeAccion()
        _crecer_matriz(nuevo.cambios, self._height, self._width)
        self._por_accion[action] = nuevo
        return nuevo

    def _crecer_hasta(self, height: int, width: int) -> None:
        if height <= self._height and width <= self._width:
            return
        self._height = max(self._height, height)
        self._width = max(self._width, width)
        _crecer_matriz_bool(self._volatile, self._height, self._width)
        _crecer_matriz_bool(self._volatil_frecuencia, self._height, self._width)
        _crecer_matriz_bool(self._volatil_barrido, self._height, self._width)
        _crecer_matriz(self._cambios_totales, self._height, self._width)
        _crecer_matriz(self._cambios_aislados, self._height, self._width)
        for contadores in self._por_accion.values():
            _crecer_matriz(contadores.cambios, self._height, self._width)

    def _registrar_soledad(self, cambiadas: list[int]) -> None:
        """Marca cuales de los cambios de ESTA transicion ocurrieron sin compania alrededor. Es la
        unica parte del criterio de barrido que no se puede recalcular despues: depende de que
        cambio JUNTO con que, y eso se pierde al acumular los contadores."""
        if not cambiadas:
            return
        en_diff = set(cambiadas)
        for indice in cambiadas:
            y = indice // self._width
            x = indice % self._width
            solo = True
            for dy in range(-SWEEP_ISOLATION_RADIUS, SWEEP_ISOLATION_RADIUS + 1):
                if not solo:
                    break
                for dx in range(-SWEEP_ISOLATION_RADIUS, SWEEP_ISOLATION_RADIUS + 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny = y + dy
                    nx = x + dx
                    if ny < 0 or nx < 0 or ny >= self._height or nx >= self._width:
                        continue
                    if ny * self._width + nx in en_diff:
                        solo = False
                        break
            if solo:
                self._cambios_aislados[y][x] += 1

    def _recomputar(self) -> None:
        """Reevalua las dos familias contra los contadores acumulados y publica la union."""
        cambio_frecuencia = self._recomputar_por_frecuencia()
        cambio_barrido = self._recomputar_por_barrido()
        if not cambio_frecuencia and not cambio_barrido:
            return

        volatiles = 0
        for y in range(self._height):
            for x in range(self._width):
                es_volatil = self._volatil_frecuencia[y][x] or self._volatil_barrido[y][x]
                self._volatile[y][x] = es_volatil
                if es_volatil:
                    volatiles += 1

        self._volatile_count = volatiles
        tope = self._height * self._width * VOLATILITY_MAX_FRACTION
        self._desactivada_por_tope = volatiles > tope
        self._version += 1

    def _recomputar_por_frecuencia(self) -> bool:
        """Familia 1: celdas que cambian casi siempre bajo TODAS las acciones.

        BL.21702 -- en MODO DE ACCION UNICA alcanza con una accion observada, pero se exigen mas
        transiciones y una regularidad casi total (ver los umbrales `_ACCION_UNICA`): sin un
        segundo boton con el que contrastar, lo unico que separa el HUD del tablero es que el HUD
        cambia SIEMPRE."""
        acciones = list(self._por_accion.values())
        accion_unica = self.modo_de_accion_unica
        minimo_transiciones = (
            VOLATILITY_MIN_TRANSITIONS_ACCION_UNICA if accion_unica else VOLATILITY_MIN_TRANSITIONS
        )
        minimo_acciones = 1 if accion_unica else VOLATILITY_MIN_DISTINCT_ACTIONS
        entrada = VOLATILITY_ENTRY_RATIO_ACCION_UNICA if accion_unica else VOLATILITY_ENTRY_RATIO
        salida = VOLATILITY_EXIT_RATIO_ACCION_UNICA if accion_unica else VOLATILITY_EXIT_RATIO
        if self._transiciones < minimo_transiciones:
            return False
        if len(acciones) < minimo_acciones:
            return False

        cambio = False
        for y in range(self._height):
            for x in range(self._width):
                era_volatil = self._volatil_frecuencia[y][x]
                umbral = salida if era_volatil else entrada
                es_volatil = all(
                    c.transiciones == 0 or c.cambios[y][x] >= c.transiciones * umbral
                    for c in acciones
                )
                if es_volatil != era_volatil:
                    self._volatil_frecuencia[y][x] = es_volatil
                    cambio = True
        return cambio

    def _recomputar_por_barrido(self) -> bool:
        """Familia 2: barras de progreso / contadores de barrido. Ver el encabezado del modulo."""
        # BL.21702 -- el criterio de la familia 2 es de FORMA y de SOLEDAD, no de contraste entre
        # acciones: el minimo de acciones distintas era una salvaguarda redundante que, en los seis
        # juegos publicos de un solo boton, apagaba la unica familia que si podia verles el HUD.
        minimo_acciones = 1 if self.modo_de_accion_unica else VOLATILITY_MIN_DISTINCT_ACTIONS
        if self._transiciones < SWEEP_MIN_TRANSITIONS:
            return False
        if len(self._por_accion) < minimo_acciones:
            return False

        nuevo = [[False] * self._width for _ in range(self._height)]
        for celdas in self._componentes_de_cambio():
            if len(celdas) < SWEEP_MIN_CELLS:
                continue
            if not _es_linea(celdas, self._width):
                continue
            if self._acciones_que_tocaron(celdas) < minimo_acciones:
                continue

            cambios = 0
            aislados = 0
            for indice in celdas:
                cambios += self._cambios_totales[indice // self._width][indice % self._width]
                aislados += self._cambios_aislados[indice // self._width][indice % self._width]
            # Que los cambios ocurran de a UNO es lo que separa una barra de un objeto que se mueve
            # (dos celdas adyacentes por paso) o de un tablero que responde (bloques enteros).
            if aislados < cambios * SWEEP_MIN_ISOLATION_RATIO:
                continue

            ya_enmascarada = any(
                self._volatil_barrido[indice // self._width][indice % self._width]
                for indice in celdas
            )
            umbral = SWEEP_EXIT_RATIO if ya_enmascarada else SWEEP_ENTRY_RATIO
            if cambios < self._transiciones * umbral:
                continue

            for indice in self._celdas_de_la_barra(celdas):
                nuevo[indice // self._width][indice % self._width] = True

        cambio = False
        for y in range(self._height):
            for x in range(self._width):
                if nuevo[y][x] != self._volatil_barrido[y][x]:
                    self._volatil_barrido[y][x] = nuevo[y][x]
                    cambio = True
        return cambio

    def _celdas_de_la_barra(self, celdas: list[int]) -> list[int]:
        """BL.21559 -- celdas a enmascarar por una barra YA reconocida.

        EL PROBLEMA QUE RESUELVE, medido en vivo. La componente crece de a UNA celda por paso (esa
        es la definicion de barra de barrido), asi que enmascarar solo lo ya observado hace que el
        conjunto volatil -- y con el la VERSION de la mascara y toda firma calculada con ella --
        cambie en cada paso durante ~48 pasos, hasta que la barra completa su primera vuelta.
        Medido reproduciendo las cuatro partidas reales con la mascara VIVA (no la final): 50
        versiones de mascara por partida y firmas unicas 78/83 en ar25, 95/100 en ka59, 123/128 en
        dc22 -- practicamente lo mismo que SIN mascara. La mejora que BL.21558 midio era
        RETROSPECTIVA (mascara final aplicada a toda la trayectoria); durante la partida no existia,
        y sin firmas que se repitan la memoria por-estado de `ExplorationPolicy` no puede disparar.

        LA REGLA. Si la barra vive sobre un BORDE del frame se enmascara la linea ENTERA desde que
        se la reconoce, no solo las celdas ya encendidas: las que faltan son las que la barra va a
        encender en los proximos pasos, y adelantarse es lo que vuelve la mascara ESTABLE. Las
        cuatro barras medidas contra la API oficial estan justo ahi (lf52 fila 0, ar25 columna 63,
        ka59 y dc22 fila 63) y ocupan el borde completo, asi que sobre dato real la extension no
        agrega NI UNA celda que la barra no vaya a ocupar igual.

        POR QUE SOLO EN EL BORDE. Extender una linea interior barreria una fila o columna entera del
        TABLERO por las dudas, que es el error que este modulo mas evita. Una barra que no este en
        un borde conserva el comportamiento previo: de a una celda, mas lento pero nunca de mas."""
        primera_y = celdas[0] // self._width
        primera_x = celdas[0] % self._width
        if all(indice // self._width == primera_y for indice in celdas) and primera_y in (
            0,
            self._height - 1,
        ):
            return [primera_y * self._width + x for x in range(self._width)]
        if all(indice % self._width == primera_x for indice in celdas) and primera_x in (
            0,
            self._width - 1,
        ):
            return [y * self._width + primera_x for y in range(self._height)]
        return celdas

    def _componentes_de_cambio(self) -> list[list[int]]:
        """Componentes conexas (8-conectividad) de TODAS las celdas que cambiaron alguna vez.
        Agrupar por region y no por celda sostiene el criterio cuando el tablero roza la barra: una
        interferencia puntual no puede sacar celdas del medio y partirla en pedazos
        irreconocibles."""
        visitada = [[False] * self._width for _ in range(self._height)]
        componentes: list[list[int]] = []
        for y0 in range(self._height):
            for x0 in range(self._width):
                if self._cambios_totales[y0][x0] == 0 or visitada[y0][x0]:
                    continue
                celdas: list[int] = []
                pila = [(y0, x0)]
                visitada[y0][x0] = True
                while pila:
                    y, x = pila.pop()
                    celdas.append(y * self._width + x)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny = y + dy
                            nx = x + dx
                            if ny < 0 or nx < 0 or ny >= self._height or nx >= self._width:
                                continue
                            if self._cambios_totales[ny][nx] == 0 or visitada[ny][nx]:
                                continue
                            visitada[ny][nx] = True
                            pila.append((ny, nx))
                componentes.append(celdas)
        return componentes

    def _acciones_que_tocaron(self, celdas: list[int]) -> int:
        """Cuantas acciones distintas provocaron al menos un cambio dentro de la componente."""
        acciones = 0
        for contadores in self._por_accion.values():
            if any(
                contadores.cambios[indice // self._width][indice % self._width] > 0
                for indice in celdas
            ):
                acciones += 1
        return acciones
