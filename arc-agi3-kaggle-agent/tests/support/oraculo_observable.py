"""[arc-agi3-kaggle-agent/tests/support/oraculo_observable] BL.21744 (correccion 2026-08-19) -- EL
ORACULO DEL GUARD DE ALCANZABILIDAD, con la misma informacion que tiene una politica: el FRAME.

POR QUE EXISTE ESTE MODULO. La primera version del guard resolvia la ruta de click asi:

    _click_en(entorno, entorno._ox, entorno._oy)   # <- las coordenadas PRIVADAS del objetivo

o sea que acertaba en UNA accion porque le habian dado la respuesta. Un oraculo con acceso al
estado privado del entorno no verifica alcanzabilidad: verifica que el motor cobre el nivel cuando
se le indica la celda exacta. Su veredicto seguiria en verde aunque el objetivo dejara de dibujarse
en el frame -- es decir, aunque NINGUNA politica pudiera encontrarlo nunca --, que es la definicion
misma de un guard que da confianza falsa. Y ademas no cobraba el COSTO: la rama de click solo
exigia que el objetivo estuviera a >= 8 celdas del avatar, sin verificar en cuantas pulsaciones se
llega, que es la nocion DEBIL de alcanzabilidad que este proyecto rechaza explicitamente.

DONDE ESTA LA LINEA entre lo que el oraculo puede saber y lo que no:

  - PUEDE saber el MAPEO DE ACCIONES del mundo (que boton traslada, con que magnitud, cual esta
    muerto). Eso es exactamente lo que una politica aprende jugando, y lo que el banco mide en
    `juegosConMapeoResuelto`. Un oraculo que ya resolvio el mapeo es la COTA SUPERIOR razonable de
    lo que una politica puede lograr.
  - NO PUEDE saber donde esta el objetivo, ni donde esta el avatar, ni si esta en la pantalla de
    titulo. Todo eso se LEE DEL FRAME, con las mismas tres funciones que usaria una politica.

`_SoloElFrame` hace que la linea sea imposible de cruzar por accidente: cualquier lectura de un
atributo del entorno explota con `AttributeError`."""
from __future__ import annotations

from collections import deque

from arc_agent.types import ActionDecision, GameAction

from .geometria_de_mundos import (
    ALIAS1,
    ALTO_TABLERO,
    CELDAS_POR_FIRMA,
    COLOR_AVATAR,
    COLOR_MENU,
    COLOR_OBJETIVO,
    COLOR_PARED,
    DIRECCION_CANONICA,
    DPAD,
    PASOS_RESERVADOS_PARA_LLEGAR,
    RUIDO,
    RUTA_CLICK,
    RUTA_MOVIMIENTO,
    celdas_de_repintado,
    ruta_de_nivel,
    trasladores,
)

#: Tope de pulsaciones cuando el mundo NO es dirigible (tr87: su unica mecanica es ruido con
#: probabilidad 0,07 y direccion sorteada). El azar no se puede acotar por pulsaciones de una
#: corrida: se acota en ESPERANZA, y de eso se ocupa la rama BFS del guard
#: (`costo_esperado_por_movimiento`). Aca solo hace falta un tope que no cuelgue el test.
PULSACIONES_SI_MANDA_EL_AZAR = 4000


class SoloElFrame:
    """El entorno TAL COMO LO VE UNA POLITICA: `reset`, `step` y nada mas.

    Cualquier otro atributo explota. `pulsaciones` es contabilidad del guard (cuantas veces se
    llamo a `step`), no informacion del mundo."""

    def __init__(self, entorno) -> None:
        self.__dict__["_entorno"] = entorno
        self.__dict__["pulsaciones"] = 0

    def reset(self):
        return self.__dict__["_entorno"].reset()

    def step(self, decision: ActionDecision):
        self.__dict__["pulsaciones"] += 1
        return self.__dict__["_entorno"].step(decision)

    def __getattr__(self, nombre: str):
        raise AttributeError(
            f"el oraculo del guard intento leer `{nombre}` del entorno. Solo puede usar el frame: "
            "un oraculo con acceso al estado privado aprueba mundos que ninguna politica podria "
            "resolver, que es el falso positivo que la primera version de BL.21744 dejo vivo"
        )

    def __setattr__(self, nombre: str, valor) -> None:  # pragma: no cover - simetria del bloqueo
        raise AttributeError(f"el oraculo del guard intento escribir `{nombre}` en el entorno")


# ── lectura del frame (lo unico que el oraculo tiene permitido mirar) ─────────────────────────


def tablero_del_frame(frame) -> tuple[tuple[int, ...], ...]:
    """Las filas JUGABLES del frame. Las tres ultimas (aire, barra de progreso y HUD) NO son
    tablero: clickearlas no puede producir nada. Es justo ahi donde la politica de hoy tira 36 de
    cada 40 clicks -- medido 2026-08-19, ver el docstring del guard."""
    return tuple(frame.frame[0])[:ALTO_TABLERO]


def buscar_color(frame, color: int) -> tuple[int, int] | None:
    for y, fila in enumerate(tablero_del_frame(frame)):
        for x, valor in enumerate(fila):
            if valor == color:
                return (y, x)
    return None


def parece_menu(frame) -> bool:
    """Pantalla de titulo vista DESDE EL FRAME: la pinta entera del color de menu. Una politica la
    reconoce asi, no consultando un atributo del entorno."""
    return COLOR_MENU in tablero_del_frame(frame)[0]


def decision(boton: str, x: int | None = None, y: int | None = None) -> ActionDecision:
    return ActionDecision(action=GameAction[boton], x=x, y=y)


# ── los tres oraculos ────────────────────────────────────────────────────────────────────────


def alcanza_el_nivel(mundo, semilla: str, crear_entorno) -> tuple[bool, int]:
    """Corre el oraculo de la ruta declarada por el mundo. Devuelve `(llego, pulsaciones)`.

    `crear_entorno(mundo, semilla)` lo inyecta el guard para no importar el motor desde aca."""
    entorno = SoloElFrame(crear_entorno(mundo, semilla))
    frame = _salir_del_menu(entorno)
    ruta = ruta_de_nivel(mundo)
    if ruta == RUTA_MOVIMIENTO:
        frame = _oraculo_de_movimiento(entorno, mundo, frame)
    elif ruta == RUTA_CLICK:
        frame = _oraculo_de_click(entorno, frame)
    else:
        frame = _oraculo_de_repintado(entorno, mundo, frame)
    return int(frame.levels_completed) >= 1, entorno.pulsaciones


def tope_de_pulsaciones(mundo) -> int:
    """Cuantas pulsaciones puede gastar el oraculo antes de que el mundo se declare inalcanzable
    EN LA PRACTICA. Para los mundos dirigibles es el presupuesto que el banco reserva para llegar;
    para el mundo de ruido puro el tope solo evita que el test cuelgue (su cota real es la de la
    esperanza, que verifica el guard con BFS)."""
    movimientos = trasladores(mundo)
    dirigible = any(not azar for _d, _m, azar in movimientos)
    if ruta_de_nivel(mundo) == RUTA_MOVIMIENTO and movimientos and not dirigible:
        return PULSACIONES_SI_MANDA_EL_AZAR
    return PASOS_RESERVADOS_PARA_LLEGAR


def _salir_del_menu(entorno: SoloElFrame):
    """Clickea a ciegas hasta que la pantalla de titulo se va. Es lo que hace el agente real (y lo
    que la sonda midio: "tras 9 clics ACTION6"), y cuenta contra el presupuesto del oraculo."""
    frame = entorno.reset()
    for _ in range(20):
        if not parece_menu(frame):
            return frame
        frame = entorno.step(decision("ACTION6", None, None))
    return frame


def _oraculo_de_click(entorno: SoloElFrame, frame):
    """UNA accion: busca el objetivo EN EL FRAME y lo clickea. Si el objetivo no esta dibujado, no
    hay nada que clickear y el mundo queda declarado inalcanzable -- que es exactamente lo que hay
    que detectar, y lo que la version con `entorno._ox` no podia."""
    objetivo = buscar_color(frame, COLOR_OBJETIVO)
    if objetivo is None:
        return frame
    y, x = objetivo
    return entorno.step(decision("ACTION6", x, y))


def _oraculo_de_movimiento(entorno: SoloElFrame, mundo, frame):
    """Camina hacia el objetivo bajando un mapa de distancias calculado sobre el TABLERO OBSERVADO.

    Ni la posicion del avatar ni la del objetivo ni las paredes vienen del entorno: se leen del
    frame. El mapa se recalcula solo cuando el objetivo cambia de lugar (al cobrar un nivel se
    recoloca), no en cada pulsacion: un BFS por paso volveria el guard un test de minutos."""
    botones = [b for b in DIRECCION_CANONICA if _traslada(mundo, b)]
    magnitud = max(1, mundo.magnitud)
    tope = tope_de_pulsaciones(mundo)
    faltan: dict[tuple[int, int], int] = {}
    objetivo_visto: tuple[int, int] | None = None
    while entorno.pulsaciones < tope:
        if int(frame.levels_completed) >= 1:
            return frame
        aqui = buscar_color(frame, COLOR_AVATAR)
        objetivo = buscar_color(frame, COLOR_OBJETIVO)
        if aqui is None or objetivo is None:
            return frame
        if objetivo != objetivo_visto:
            objetivo_visto = objetivo
            faltan = _distancias_observadas(frame, objetivo, botones, magnitud)
        elegido = botones[0] if botones else "ACTION1"
        for boton in botones:
            dy, dx = DIRECCION_CANONICA[boton]
            paso = (aqui[0] + dy * magnitud, aqui[1] + dx * magnitud)
            if faltan.get(paso, 10**9) < faltan.get(aqui, 10**9):
                elegido = boton
                break
        frame = entorno.step(decision(elegido))
    return frame


def _oraculo_de_repintado(entorno: SoloElFrame, mundo, frame):
    """Insiste con el boton cuyo bloque BARRE el tablero hasta cubrir el objetivo. Que boton es sale
    del mapeo de acciones (permitido); cuando el objetivo quedo cubierto lo dice el frame."""
    boton = next(
        b
        for b, f in list(mundo.flechas.items()) + list(mundo.extras.items())
        if CELDAS_POR_FIRMA.get(f) == celdas_de_repintado(mundo)
    )
    tope = tope_de_pulsaciones(mundo)
    while entorno.pulsaciones < tope:
        if int(frame.levels_completed) >= 1:
            return frame
        frame = entorno.step(decision(boton))
    return frame


def _traslada(mundo, boton: str) -> bool:
    """Botones que el MAPEO dice que trasladan. Las flechas de RUIDO entran: existen y trasladan,
    solo que su direccion la sortea el mundo -- por eso su mundo tiene un tope de pulsaciones
    distinto y una cota en esperanza."""
    firma = mundo.flechas.get(boton) or mundo.extras.get(boton)
    return firma in (DPAD, ALIAS1, RUIDO)


def _distancias_observadas(frame, objetivo, botones, magnitud) -> dict[tuple[int, int], int]:
    """BFS hacia atras desde el objetivo sobre el tablero QUE SE VE: pared es lo que esta pintado
    de `COLOR_PARED`, no lo que declara `geometria_de_mundos`. Asi el guard tambien se pone rojo si
    el motor y la geometria dejan de coincidir."""
    tablero = tablero_del_frame(frame)
    ancho = len(tablero[0])
    saltos = []
    for boton in botones:
        dy, dx = DIRECCION_CANONICA[boton]
        saltos.append((dy * magnitud, dx * magnitud))
    if not saltos:  # mundo sin trasladores: el BFS no tiene aristas
        saltos = [(0, 0)]
    distancias = {objetivo: 0}
    cola = deque([objetivo])
    while cola:
        y, x = cola.popleft()
        for dy, dx in saltos:
            origen = (y - dy, x - dx)
            if origen in distancias:
                continue
            oy, ox = origen
            if not (0 <= oy < len(tablero) and 0 <= ox < ancho):
                continue
            if tablero[oy][ox] == COLOR_PARED or tablero[y][x] == COLOR_PARED:
                continue
            distancias[origen] = distancias[(y, x)] + 1
            cola.append(origen)
    return distancias
