"""[arc-agi3-kaggle-agent/tests/support/mundos_medidos] BANCO DE LAZO CERRADO sobre
los 25 juegos publicos de ARC-AGI-3, reconstruidos PARAMETRICAMENTE desde la unica medicion
publicada del repo: notes/features/arc-prize-2026-mapeo-de-acciones-25-juegos.md (sonda de
BL.21590, 2.673 acciones contra la API oficial).

POR QUE UN SIMULADOR Y NO LA GRABACION. El fixture `volatilityRealGames.json` son 4 partidas
GRABADAS: sirven para reproducir la inferencia paso a paso (eso hace test_bl21593_real_games.py)
pero NO para medir una POLITICA, porque una politica distinta elige acciones distintas y la
grabacion no tiene respuesta para ellas. La metrica de BL.21594 -- ACCIONES AHORRADAS -- solo
existe en lazo cerrado: hay que dejar que el agente elija y que el mundo conteste.

QUE SE REPRODUCE, con la cita de la medicion al lado (ver `MUNDOS`):
  - los 10 CONJUNTOS de acciones disponibles y que juego trae cual (17/25 con flechas);
  - el mapeo canonico y la MAGNITUD por juego (2 a 6 celdas, "el prior fija la direccion, nunca
    la magnitud");
  - las flechas MUERTAS: lf52 (160 pulsaciones sin un solo cambio), cd82 (A1/A2 40/40 sinCambio,
    medio D-pad inerte), sk48 (A3/A4 74 intentos sin traslacion), re86 (mecanica no direccional),
    tr87 (ruido sub-objeto contradictorio), bp35 (una diagonal espuria). tu93 estuvo en esta lista
    hasta BL.21744 y ya NO esta: su "recoloreo de 1-2 celdas" se relee como un SELECTOR que se
    corre una celda por pulsacion (ver el comentario de su entrada en `MUNDOS`);
  - la PANTALLA DE TITULO de dc22/ka59/cd82/lf52/bp35: las flechas no tocan el tablero hasta que
    se clickea ("quien mide sin clickear primero mide el menu, no el juego");
  - ACTION5/ACTION7 con sus cuatro comportamientos medidos (inerte, toggle, disparo, cambio de
    escena) y el alias de A1 en sk48;
  - la BARRA DE PROGRESO que hace unica cada firma de estado (el ruido que BL.21558 enmascara).

Este archivo indexa por nombre de juego A PROPOSITO y no puede entrar nunca a `arc_agent/`: el
gate anti-memorizacion de submission/build_agent.py existe justamente para eso.

═══════════════════════════════════════════════════════════════════════════════════════════════
ESTE BANCO NO ES EL GATE DE MERGE DEL PROYECTO. NO LO USES PARA DECIDIR SI UN CAMBIO ENTRA.
═══════════════════════════════════════════════════════════════════════════════════════════════
Es un SIMULADOR PARAMETRICO: reproduce el MAPEO DE ACCIONES medido (que boton mueve, con que
magnitud, cual esta muerto, cual abre un menu), y para eso sirve. No reproduce los PUZZLES de los
25 juegos, asi que "subir de nivel" aca no es la misma magnitud que subir de nivel en el juego.

Y hubo un motivo mucho mas duro, que es la razon por la que esta advertencia existe (BL.21744).
El gate que varios BLs escribieron en su brief -- "se mergea SOLO si suben los NIVELES TOTALES en
los 25 juegos, medido con `scripts/medir_lazo_cerrado.py`" -- era INGANABLE POR CONSTRUCCION.
Medido con BFS sobre la geometria de este archivo: el objetivo estaba clavado a 54 celdas exactas
del avatar en linea recta vertical, y como el avatar solo se mueve de a `magnitud` celdas, solo lo
alcanzaban los mundos con magnitud divisora de 54 Y flecha vertical viva. Eran SEIS de 25 (ar25,
ka59, dc22, cn04, g50t, sk48); los otros 19 devolvian `niveles = 0` hiciera lo que hiciera la
politica. (Un BFS a secas cuenta OCHO, porque tr87 y bp35 tenian la celda en su reticula via las
flechas de RUIDO; no cuentan, porque el ruido dispara con probabilidad 0,07 y ademas sortea la
direccion: llegar salia ~3.086 pulsaciones esperadas contra 200 de presupuesto. Un gate mide
POLITICAS, asi que el numero que importa es seis.) Un gate que no puede subir no es un gate conservador: es un FALSO NEGATIVO SISTEMATICO
que rechaza toda mejora real y encima se lee como rigor. La geometria ya esta corregida (ver
`geometria_de_mundos.py` y el guard `tests/test_bl21744_alcanzabilidad_de_niveles.py`, que falla si
algun mundo vuelve a quedar sin nivel 1 alcanzable), pero la conclusion de fondo no cambia: para
decidir un merge se mide contra el HARNESS REAL.

EL GATE DE MERGE ES `scripts/gate_de_merge.py` (harness real `arc_agi` + `environment_files`).
Ahi la senal existe de verdad: hay subidas de nivel medidas con el agente actual en ft09, g50t,
lp85, m0r0, sc25 y vc33."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from arc_agent.types import ActionDecision, FrameData, GameState

# La GEOMETRIA (tablero, paredes, reticula alcanzable de cada mundo y colocacion del objetivo) vive
# en su propio modulo desde BL.21744: el guard de alcanzabilidad y este motor tienen que razonar
# sobre EXACTAMENTE la misma geometria, o el guard verifica un tablero que nadie juega.
from .geometria_de_mundos import (  # noqa: F401  (re-exportados: son la API del banco)
    ALIAS1,
    ALTO_TABLERO,
    ANCHO,
    CELDAS_POR_FIRMA,
    CLICS_PARA_SALIR_DEL_MENU,
    COLOR_AVATAR,
    COLOR_MENU,
    COLOR_OBJETIVO,
    COLOR_PARED,
    COLOR_PISO,
    COLOR_REPINTADO_A,
    COLOR_REPINTADO_B,
    DIRECCION_CANONICA,
    DISPARO,
    DPAD,
    ESCENA,
    INERTE,
    INICIO_DEL_AVATAR,
    NIVELES_PARA_GANAR,
    OTRA,
    PAREDES,
    PROB_DE_RUIDO,
    RUIDO,
    RUTA_CLICK,
    RUTA_MOVIMIENTO,
    RUTA_REPINTADO,
    TELEPORT,
    TOGGLE,
    celdas_de_repintado,
    orden_de_repintado,
    posicion_del_objetivo,
    ruta_de_nivel,
)


@dataclass(frozen=True)
class Mundo:
    """Un juego medido. `flechas` mapea boton -> `dpad` (mueve segun el mapeo canonico) o una de
    las firmas muertas; `magnitud` son las celdas por pulsacion medidas para ese juego."""

    nombre: str
    acciones: tuple[int, ...]
    magnitud: int = 0
    flechas: dict[str, str] = field(default_factory=dict)
    extras: dict[str, str] = field(default_factory=dict)
    menu: bool = False


def _dpad(*botones: str) -> dict[str, str]:
    return {b: DPAD for b in botones}


CUATRO = ("ACTION1", "ACTION2", "ACTION3", "ACTION4")

#: Los 25 juegos publicos. Cada entrada cita la medicion de la que sale.
MUNDOS: tuple[Mundo, ...] = (
    # -- Confirman las cuatro direcciones, 0 contradicciones (8 juegos) ------------------------
    Mundo("ar25", (1, 2, 3, 4, 5, 6, 7), 3, _dpad(*CUATRO), {"ACTION5": INERTE, "ACTION7": TELEPORT}),
    Mundo("ls20", (1, 2, 3, 4), 5, _dpad(*CUATRO)),
    Mundo("m0r0", (1, 2, 3, 4, 5, 6), 5, _dpad(*CUATRO), {"ACTION5": INERTE}),
    Mundo("ka59", (1, 2, 3, 4, 6), 3, _dpad(*CUATRO), menu=True),
    Mundo("dc22", (1, 2, 3, 4, 6), 2, _dpad(*CUATRO), menu=True),
    Mundo("wa30", (1, 2, 3, 4, 5), 4, _dpad(*CUATRO), {"ACTION5": INERTE}),
    Mundo("g50t", (1, 2, 3, 4, 5), 6, _dpad(*CUATRO), {"ACTION5": DISPARO}),
    Mundo("cn04", (1, 2, 3, 4, 5, 6), 3, _dpad(*CUATRO), {"ACTION5": ESCENA}),
    # -- Confirman parcial, sin contradicciones (3) --------------------------------------------
    #    sk48: A1/A2 confirmados (paso 6); A3/A4 con 74 intentos y 0 traslaciones. A7 alias de A1.
    Mundo("sk48", (1, 2, 3, 4, 6, 7), 6,
          {"ACTION1": "dpad", "ACTION2": "dpad", "ACTION3": INERTE, "ACTION4": INERTE},
          {"ACTION7": ALIAS1}),
    #    sp80: A1/A2 confirmados (paso 4); A3/A4 cambian 34 celdas en 3 clusters -- no direccional.
    Mundo("sp80", (1, 2, 3, 4, 5, 6), 4,
          {"ACTION1": "dpad", "ACTION2": "dpad", "ACTION3": OTRA, "ACTION4": OTRA},
          {"ACTION5": DISPARO}),
    #    sc25: eje horizontal confirmado; eje vertical INCONCLUSO (A1 y A2 dan el mismo evento).
    Mundo("sc25", (1, 2, 3, 4, 6), 3,
          {"ACTION1": TOGGLE, "ACTION2": TOGGLE, "ACTION3": "dpad", "ACTION4": "dpad"}),
    # -- Flechas disponibles que no mueven nada (6) --------------------------------------------
    Mundo("lf52", (1, 2, 3, 4, 6, 7), 0, {b: INERTE for b in CUATRO},
          {"ACTION7": INERTE}, menu=True),
    #    cd82: "A1/A2 40/40 sinCambio -- mitad del D-pad literalmente inerte". La otra mitad no
    #    produjo traslacion medible: entra como mecanica no direccional.
    Mundo("cd82", (1, 2, 3, 4, 5, 6), 0,
          {"ACTION1": INERTE, "ACTION2": INERTE, "ACTION3": OTRA, "ACTION4": OTRA},
          {"ACTION5": INERTE}, menu=True),
    Mundo("re86", (1, 2, 3, 4, 5), 0, {b: OTRA for b in CUATRO}, {"ACTION5": TOGGLE}),
    #    tu93: la sonda lo anoto como "solo recoloreo de 1-2 celdas: es un SELECTOR, no un
    #    jugador". Un selector que se corre UNA celda por pulsacion produce exactamente ese diff de
    #    1-2 celdas (se apaga donde estaba y se enciende donde queda), asi que se modela como d-pad
    #    de magnitud 1 -- que es lo que dice la medicion -- y no como mecanica no direccional, que
    #    era una lectura mas pobre de la MISMA linea (BL.21744).
    Mundo("tu93", (1, 2, 3, 4), 1, _dpad(*CUATRO)),
    Mundo("tr87", (1, 2, 3, 4), 0, {b: RUIDO for b in CUATRO}),
    Mundo("bp35", (3, 4, 6, 7), 0, {"ACTION3": RUIDO, "ACTION4": RUIDO},
          {"ACTION7": INERTE}, menu=True),
    # -- Sin acciones de movimiento (8) ---------------------------------------------------------
    Mundo("ft09", (6,)),
    Mundo("lp85", (6,)),
    Mundo("r11l", (6,)),
    Mundo("s5i5", (6,)),
    Mundo("tn36", (6,)),
    Mundo("vc33", (6,)),
    Mundo("su15", (6, 7), extras={"ACTION7": INERTE}),
    Mundo("sb26", (5, 6, 7), extras={"ACTION5": DISPARO, "ACTION7": INERTE}),
)

MUNDOS_POR_NOMBRE: dict[str, Mundo] = {m.nombre: m for m in MUNDOS}


class EntornoMedido:
    """Motor de UN juego medido. Contrato identico al de un juego real: `reset()` y luego
    `step(decision)` por cada decision de la politica."""

    def __init__(self, mundo: Mundo, seed: str = "bl21594") -> None:
        self.mundo = mundo
        self._rng = random.Random(f"{seed}:{mundo.nombre}")
        self._paso = 0
        self._guid = 0
        self._clics_menu = 0
        self._en_menu = mundo.menu
        self._niveles = 0
        self._ultimo_toggle = False
        #: Por donde va el BARRIDO del repintado. Antes el bloque no direccional pintaba siempre
        #: las mismas primeras celdas, asi que la SEGUNDA pulsacion del mismo boton no cambiaba
        #: nada -- lo contrario de lo medido, que vio el diff repetirse pulsacion tras pulsacion.
        self._barrido_de_repintado = 0
        #: Vueltas COMPLETAS que dio el barrido. El color destino alterna con cada vuelta para que
        #: la pasada siguiente siempre tenga algo que repintar; sin eso el tablero quedaba uniforme
        #: y el boton se volvia indistinguible de uno muerto a mitad de la partida (BL.21744).
        self._vueltas_de_repintado = 0
        self._tablero = [[COLOR_PISO] * ANCHO for _ in range(ALTO_TABLERO)]
        # Bordes mas UN muro interior contiguo, tal como los declara `geometria_de_mundos`: es la
        # misma geometria sobre la que el guard de alcanzabilidad corre su BFS.
        for (y, x) in PAREDES:
            self._tablero[y][x] = COLOR_PARED
        self._y, self._x = INICIO_DEL_AVATAR
        self._tablero[self._y][self._x] = COLOR_AVATAR
        #: La via por la que ESTE mundo puede subir de nivel (movimiento, click o repintado),
        #: derivada de su propia medicion. Ver `geometria_de_mundos.ruta_de_nivel`.
        self.ruta = ruta_de_nivel(mundo)
        self._oy, self._ox = posicion_del_objetivo(mundo)
        self._tablero[self._oy][self._ox] = COLOR_OBJETIVO
        #: Celdas del avatar recorridas: la metrica "distancia" del BL.
        self.distancia = 0
        #: Pasos en que el tablero cambio -- "pasos productivos".
        self.productivos = 0
        #: Clicks de ACTION6 que cambiaron el tablero -- "clicks productivos".
        self.clicks_productivos = 0

    # ── lectura ────────────────────────────────────────────────────────────────────────────────

    @property
    def en_menu(self) -> bool:
        return self._en_menu

    @property
    def niveles(self) -> int:
        return self._niveles

    def es_boton_muerto(self, accion: str) -> bool:
        """VERDAD DEL MUNDO: el boton no puede producir un solo cambio en el tablero. Es lo que la
        metrica del BL cuenta como accion desperdiciada."""
        firma = self.mundo.flechas.get(accion) or self.mundo.extras.get(accion)
        return firma == INERTE

    def _grilla(self) -> tuple[tuple[int, ...], ...]:
        filas = [tuple(fila) for fila in self._tablero]
        if self._en_menu:
            fila_menu = [COLOR_MENU] * ANCHO
            fila_menu[self._clics_menu % ANCHO] = COLOR_PISO
            filas = [tuple(fila_menu)] * ALTO_TABLERO
        aire = tuple(COLOR_PISO for _ in range(ANCHO))
        # Barra de progreso: un prefijo CONTIGUO que crece una celda por paso y cambia de color al
        # dar la vuelta (medido: 96 cambios en 96 transiciones, siempre de a una celda). Un solo
        # componente conexo. El HUD es una celda que cambia en TODOS los pasos.
        llenas = self._paso % ANCHO + 1
        color = 1 + (self._paso // ANCHO) % 3
        barra = [color if i < llenas else COLOR_PISO for i in range(ANCHO)]
        hud = [COLOR_PISO] * ANCHO
        hud[0] = 1 + self._paso % 11
        return tuple(filas) + (aire, tuple(barra), tuple(hud))

    def _frame(self, estado: GameState | None = None) -> FrameData:
        self._guid += 1
        if estado is None:
            # Ganar tiene consecuencia: un banco que deja seguir jugando despues de completar los
            # `win_levels` declarados sigue cobrando acciones de una partida que ya termino.
            estado = (
                GameState.WIN if self._niveles >= NIVELES_PARA_GANAR else GameState.NOT_FINISHED
            )
        return FrameData(
            game_id=self.mundo.nombre,
            guid=f"{self.mundo.nombre}-{self._guid}",
            frame=(self._grilla(),),
            state=estado,
            available_actions=self.mundo.acciones,
            levels_completed=self._niveles,
            win_levels=NIVELES_PARA_GANAR,
        )

    def reset(self) -> FrameData:
        return self._frame()

    # ── dinamica ───────────────────────────────────────────────────────────────────────────────

    def step(self, decision: ActionDecision) -> FrameData:
        antes = [fila[:] for fila in self._tablero]
        # Por NOMBRE y no por identidad de enum: el banco tiene que poder correr dos versiones del
        # agente (baseline y candidata) sobre el mismo mundo, y cada una trae su propio `GameAction`.
        accion = decision.action.value
        if accion == "RESET":
            self._paso += 1
            return self._frame()
        if accion == "ACTION6":
            self._click(decision.x, decision.y)
        elif not self._en_menu:
            self._aplicar(accion)
        self._paso += 1
        cambio = antes != self._tablero
        if cambio:
            self.productivos += 1
            if accion == "ACTION6":
                self.clicks_productivos += 1
        return self._frame()

    def _click(self, x: int | None, y: int | None) -> None:
        if self._en_menu:
            self._clics_menu += 1
            if self._clics_menu >= CLICS_PARA_SALIR_DEL_MENU:
                self._en_menu = False
            return
        if x is None or y is None:
            return
        if (y, x) == (self._oy, self._ox) and self.ruta == RUTA_CLICK:
            # Los 11 mundos sin flechas vivas suben de nivel CLICKEANDO el objetivo. Es la unica
            # mecanica que la sonda les midio, y es lo que convierte a `clicksProductivos` en una
            # medida de politica y no de PRNG (leccion 3 del rescate del banco de BL.21594).
            self._completar_nivel()
            return
        if 0 <= y < ALTO_TABLERO and 0 <= x < ANCHO and self._tablero[y][x] == COLOR_PISO:
            self._tablero[y][x] = 2 if self._paso % 2 == 0 else 4

    def _aplicar(self, accion: str) -> None:
        firma = self.mundo.flechas.get(accion) or self.mundo.extras.get(accion)
        if firma is None or firma == INERTE:
            return
        if firma == "dpad":
            self._mover(DIRECCION_CANONICA[accion], self.mundo.magnitud)
        elif firma == ALIAS1:
            self._mover(DIRECCION_CANONICA["ACTION1"], self.mundo.magnitud)
        elif firma == RUIDO:
            # tr87/bp35: "traslaciones de 1 celda mutuamente contradictorias" -- ruido sub-objeto,
            # raro y sin direccion estable. Nunca es un mapeo.
            if self._rng.random() < 0.07:
                self._mover(self._rng.choice(list(DIRECCION_CANONICA.values())), 1)
        elif firma in CELDAS_POR_FIRMA:
            # Cuantas celdas pinta cada firma sale de `CELDAS_POR_FIRMA` (fuente unica). El TOGGLE
            # alterna EN EL LUGAR -- eso es lo que lo hace un toggle; las demas BARREN el tablero.
            self._recolorear(CELDAS_POR_FIRMA[firma], alterna=firma == TOGGLE)
        elif firma == TELEPORT:
            self._teleportar()

    def _mover(self, direccion: tuple[int, int], magnitud: int) -> None:
        dy, dx = direccion
        ny, nx = self._y + dy * magnitud, self._x + dx * magnitud
        if not (0 <= ny < ALTO_TABLERO and 0 <= nx < ANCHO):
            return
        if self._tablero[ny][nx] == COLOR_PARED:
            return  # pared: el fallo OBSERVABLE que la verosimilitud de BL.21593 explica
        alcanzo = self._tablero[ny][nx] == COLOR_OBJETIVO
        self._tablero[self._y][self._x] = COLOR_PISO
        self._y, self._x = ny, nx
        self._tablero[ny][nx] = COLOR_AVATAR
        self.distancia += abs(dy * magnitud) + abs(dx * magnitud)
        if alcanzo:
            self._completar_nivel()

    def _completar_nivel(self) -> None:
        """Sube el contador y RECOLOCA el objetivo donde este mundo pueda volver a alcanzarlo.

        Antes de BL.21744 el objetivo se re-sorteaba en una celda cualquiera del tablero, o sea
        casi siempre FUERA de la reticula del mundo: aun el mundo que lograba el nivel 1 quedaba sin
        nivel 2. La recolocacion usa la misma regla que la colocacion inicial, pero desde la
        posicion ACTUAL del avatar y con el rng semillado del entorno."""
        self._niveles += 1
        if self._tablero[self._oy][self._ox] == COLOR_OBJETIVO:
            self._tablero[self._oy][self._ox] = COLOR_PISO
        self._oy, self._ox = posicion_del_objetivo(self.mundo, self._rng, (self._y, self._x))
        if (self._oy, self._ox) != (self._y, self._x):
            self._tablero[self._oy][self._ox] = COLOR_OBJETIVO

    def _recolorear(self, celdas: int, alterna: bool = False) -> None:
        """Mecanica NO direccional: pinta un bloque CONTIGUO (un solo objeto) de `celdas` celdas.
        Contiguo y no salpicado por el mismo motivo que el muro: el detector tiene que ver una
        mecanica, no cincuenta.

        El bloque BARRE el tablero (avanza `celdas` por pulsacion) salvo el toggle, que alterna en
        el lugar. Antes repintaba siempre las mismas primeras celdas y la segunda pulsacion del
        mismo boton no producia diff alguno -- justo lo contrario de lo medido, donde el diff se
        repite pulsacion tras pulsacion.

        Y EL COLOR CAMBIA EN CADA VUELTA (correccion de BL.21744, 2026-08-19). Con un color destino
        fijo el barrido se apagaba solo: medido, cn04/ACTION5 (bloque de 185 celdas) dejaba de
        producir diff a partir de la pulsacion 21 y sp80/cd82 (34 celdas) a partir de la 108 --
        dentro de los mismos 200 pasos de la partida, o sea que el 90% de la partida el boton volvia
        a ser indistinguible de uno muerto y el mundo mentia otra vez sobre su propia mecanica. Al
        alternar el destino por VUELTA completa, la segunda pasada repinta lo que la primera dejo y
        el diff se repite mientras dure la partida, que es lo que la sonda vio.

        El objetivo NUNCA se pisa: pisarlo le sacaba al mundo, en silencio, su unica via de nivel.
        En los mundos cuya UNICA mecanica es esta (`RUTA_REPINTADO`), cubrirlo ES subir de nivel."""
        orden = orden_de_repintado((self._y, self._x))
        desde = 0 if alterna else self._barrido_de_repintado % max(1, len(orden))
        if alterna:
            destino = COLOR_REPINTADO_A if not self._ultimo_toggle else COLOR_REPINTADO_B
            self._ultimo_toggle = not self._ultimo_toggle
        else:
            # Una VUELTA es haber recorrido `orden` entero. El destino alterna vuelta a vuelta para
            # que la pasada siguiente tenga siempre algo que repintar (ver el parrafo de arriba).
            vuelta = self._vueltas_de_repintado
            destino = COLOR_REPINTADO_A if vuelta % 2 == 0 else COLOR_REPINTADO_B
            fin = desde + celdas
            self._barrido_de_repintado = fin % max(1, len(orden))
            if fin >= len(orden):
                self._vueltas_de_repintado = vuelta + 1
        cubrio_el_objetivo = False
        for indice in range(desde, min(desde + celdas, len(orden))):
            y, x = orden[indice]
            if (y, x) == (self._oy, self._ox):
                cubrio_el_objetivo = True
                continue
            if self._tablero[y][x] != destino:
                self._tablero[y][x] = destino
        if cubrio_el_objetivo and self.ruta == RUTA_REPINTADO:
            self._completar_nivel()

    def _teleportar(self) -> None:
        for _ in range(12):
            ny = self._rng.randrange(1, ALTO_TABLERO - 1)
            nx = self._rng.randrange(1, ANCHO - 1)
            if self._tablero[ny][nx] == COLOR_PISO:
                self._tablero[self._y][self._x] = COLOR_PISO
                self._y, self._x = ny, nx
                self._tablero[ny][nx] = COLOR_AVATAR
                return
