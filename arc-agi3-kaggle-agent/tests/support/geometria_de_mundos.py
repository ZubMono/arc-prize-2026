"""[arc-agi3-kaggle-agent/tests/support/geometria_de_mundos] BL.21744 -- LA GEOMETRIA del banco
parametrico, separada del motor para que haya UNA sola fuente de verdad sobre que celda es
alcanzable en cada mundo.

QUE PROBLEMA RESUELVE. Hasta BL.21744 el objetivo estaba clavado en `(ALTO_TABLERO - 4, 3)` para
los 25 mundos, o sea a 54 celdas EXACTAS del avatar en linea recta vertical. Como el avatar solo
se traslada de a `magnitud` celdas, la coordenada vertical alcanzable es siempre `3 + k*magnitud`:
el objetivo solo existia para los mundos cuya magnitud divide a 54 (2, 3 y 6) Y que ademas tuvieran
una flecha VERTICAL viva. Medido con BFS sobre esa geometria: 6 mundos de 25 podian llegar al
nivel 1, y los otros 19 daban `niveles = 0` hiciera lo que hiciera la politica. El objetivo no
estaba lejos: estaba FUERA DE LA RETICULA.

LA REGLA QUE LO REEMPLAZA. El objetivo NO se clava: se DERIVA de la mecanica de cada mundo, y
siempre queda a `PROFUNDIDAD_DEL_OBJETIVO` acciones correctas del arranque. Cada mundo se clasifica
en la unica ruta de nivel que su medicion le permite:

  - `RUTA_MOVIMIENTO` -- tiene alguna flecha que TRASLADA al avatar. El objetivo se coloca en una
    celda de su PROPIA reticula (BFS sobre magnitud y paredes), nunca fuera.
  - `RUTA_CLICK` -- no traslada nada pero tiene ACTION6. El objetivo es una celda de piso y el
    click encima sube el nivel. Es la ruta de los 11 mundos sin flechas vivas, y es ademas la
    leccion 3 que dejo abierta el rescate del banco de BL.21594 ("el banco necesita clicks
    productivos para que los juegos sin flechas midan politica y no PRNG").
  - `RUTA_REPINTADO` -- ni traslada ni tiene ACTION6: su unica mecanica medida es el repintado no
    direccional. El bloque repintado BARRE el tablero y cubrir el objetivo sube el nivel.

INVARIANTE que el guard `tests/test_bl21744_alcanzabilidad_de_niveles.py` verifica con BFS: los 25
mundos tienen nivel 1 alcanzable, y a un costo que entra en el presupuesto de la partida."""
from __future__ import annotations

import random
from collections import deque
from typing import Iterable, Protocol

#: 64x64 -- el TAMANO REAL de un frame de ARC-AGI-3. Las tres ultimas filas del frame son aire,
#: barra de progreso y HUD, asi que el TABLERO ocupa 61.
ALTO_TABLERO = 61
ANCHO = 64

COLOR_PISO = 0
COLOR_PARED = 3
COLOR_AVATAR = 5
COLOR_OBJETIVO = 7
COLOR_MENU = 9

#: Los dos colores con los que barre una mecanica NO direccional. Son DOS y no uno porque el
#: barrido alterna vuelta a vuelta: con un color unico el tablero quedaba uniforme y el boton dejaba
#: de producir diff dentro de la misma partida (medido en BL.21744: cn04 se apagaba en la pulsacion
#: 21 de 200). Tambien son los dos estados del TOGGLE, que alterna en el lugar.
COLOR_REPINTADO_A = 6
COLOR_REPINTADO_B = 8

#: Esquina del avatar al arrancar. Fija y compartida: el BFS del guard y el motor tienen que
#: partir del MISMO lugar o la reachability medida no es la del banco.
INICIO_DEL_AVATAR = (3, 3)

#: Clicks de ACTION6 que destraban la pantalla de titulo. Medido: "tras 9 clics ACTION6, dc22 y
#: ka59 dieron 5/5 el mapeo canonico limpio".
CLICS_PARA_SALIR_DEL_MENU = 9

#: Niveles que declara `FrameData.win_levels`. Al alcanzarlos la partida reporta WIN: un banco que
#: deja seguir jugando despues de ganar tampoco esta calibrado.
NIVELES_PARA_GANAR = 8

DPAD = "dpad"
INERTE = "inerte"
OTRA = "otra"
RUIDO = "ruido"
TOGGLE = "toggle"
DISPARO = "disparo"
ESCENA = "escena"
TELEPORT = "teleport"
ALIAS1 = "alias1"

DIRECCION_CANONICA: dict[str, tuple[int, int]] = {
    "ACTION1": (-1, 0),
    "ACTION2": (1, 0),
    "ACTION3": (0, -1),
    "ACTION4": (0, 1),
}

#: Celdas que repinta cada mecanica NO direccional, con la cita de la medicion al lado. FUENTE
#: UNICA: antes estos cuatro numeros vivian sueltos en las llamadas a `_recolorear`.
CELDAS_POR_FIRMA: dict[str, int] = {
    OTRA: 34,      # sp80: "34 celdas en 3 clusters"
    ESCENA: 185,   # cn04: "cambio masivo de escena, 180-190 celdas"
    TOGGLE: 12,
    DISPARO: 12,
}

#: Probabilidad de que una pulsacion de una flecha de RUIDO produzca una traslacion de 1 celda
#: (tr87/bp35: "traslaciones de 1 celda mutuamente contradictorias", raras y sin direccion
#: estable). Sale de la implementacion original del motor y ahora es constante nombrada porque el
#: calculo del presupuesto de la partida la necesita.
PROB_DE_RUIDO = 0.07

#: Rango de MAGNITUD que la sonda midio de verdad: "el mapeo canonico y la MAGNITUD por juego (2 a
#: 6 celdas)", mas el 1 de tu93 (el SELECTOR que se corre una celda por pulsacion, relectura de
#: BL.21744). Son cotas de la MEDICION, no de la implementacion: el guard las verifica para que una
#: magnitud inventada -- una que haga que el objetivo quede a una sola pulsacion, o que vacie la
#: reticula del mundo -- no pueda entrar en la tabla sin que nadie se entere. La refutacion del
#: 2026-08-19 mostro que sin esta cota se podia mutar ls20 de 5 a 7, ar25 de 3 a 11 y sk48 de 6 a 13
#: sin poner ni un test en rojo.
MAGNITUD_MINIMA_MEDIDA = 1
MAGNITUD_MAXIMA_MEDIDA = 6

#: A cuantas ACCIONES CORRECTAS del arranque queda el objetivo. Ocho es el ancho de una
#: macro-accion del proyecto (`scripts/play_local.py`: "una macro-accion completa de 8 pasos"), asi
#: que el nivel 1 cuesta exactamente una macro-accion bien elegida: ni regalado ni inalcanzable.
PROFUNDIDAD_DEL_OBJETIVO = 8

#: Pasos del presupuesto de la partida (200) que el banco reserva para LLEGAR al objetivo. El resto
#: es para IDENTIFICAR el mundo, que es lo que el banco mide de verdad. Un objetivo que cuesta mas
#: que esto es inalcanzable EN LA PRACTICA aunque el BFS diga que hay camino -- y ese, exactamente,
#: es el falso negativo que BL.21744 vino a corregir.
PASOS_RESERVADOS_PARA_LLEGAR = 60

RUTA_MOVIMIENTO = "movimiento"
RUTA_CLICK = "click"
RUTA_REPINTADO = "repintado"


class MundoLike(Protocol):
    """Lo unico que la geometria necesita de un mundo. Se tipa por PROTOCOLO y no importando
    `Mundo` para que `mundos_medidos` pueda importar este modulo sin ciclo."""

    nombre: str
    acciones: tuple[int, ...]
    magnitud: int
    flechas: dict[str, str]
    extras: dict[str, str]
    menu: bool


def celdas_de_pared() -> frozenset[tuple[int, int]]:
    """Borde del tablero mas UN muro interior contiguo en la columna del medio. Contiguo y no
    salpicado a proposito: produce fallos con pared observable sin fabricar decenas de objetos."""
    paredes = set()
    for x in range(ANCHO):
        paredes.add((0, x))
        paredes.add((ALTO_TABLERO - 1, x))
    for y in range(ALTO_TABLERO):
        paredes.add((y, 0))
        paredes.add((y, ANCHO - 1))
    for y in range(10, ALTO_TABLERO - 10):
        paredes.add((y, ANCHO // 2))
    return frozenset(paredes)


PAREDES = celdas_de_pared()


def es_piso(celda: tuple[int, int]) -> bool:
    y, x = celda
    return 0 <= y < ALTO_TABLERO and 0 <= x < ANCHO and celda not in PAREDES


def _firmas(mundo: MundoLike) -> Iterable[tuple[str, str]]:
    yield from mundo.flechas.items()
    yield from mundo.extras.items()


def trasladores(mundo: MundoLike) -> list[tuple[tuple[int, int], int, bool]]:
    """Los desplazamientos que el mundo puede aplicarle al avatar: `(direccion, magnitud, azar)`.

    `azar=True` marca los de RUIDO: existen, pero la politica no elige su direccion, asi que
    cuestan muchisimas mas pulsaciones por celda recorrida."""
    salida: list[tuple[tuple[int, int], int, bool]] = []
    for boton, firma in _firmas(mundo):
        if firma == DPAD and boton in DIRECCION_CANONICA and mundo.magnitud > 0:
            salida.append((DIRECCION_CANONICA[boton], mundo.magnitud, False))
        elif firma == ALIAS1 and mundo.magnitud > 0:
            salida.append((DIRECCION_CANONICA["ACTION1"], mundo.magnitud, False))
        elif firma == RUIDO:
            for direccion in DIRECCION_CANONICA.values():
                salida.append((direccion, 1, True))
    return salida


def alcanzables_desde(
    mundo: MundoLike, origen: tuple[int, int] | None = None
) -> dict[tuple[int, int], int]:
    """BFS sobre la reticula PROPIA del mundo: celda -> movimientos minimos para pisarla.

    Es el mismo recorrido que hace `EntornoMedido._mover` (fuera de tablero y pared bloquean, el
    resto no), asi que lo que este BFS declara alcanzable el motor lo alcanza de verdad."""
    inicio = origen or INICIO_DEL_AVATAR
    movimientos = trasladores(mundo)
    profundidades = {inicio: 0}
    if not movimientos:
        return profundidades
    cola = deque([inicio])
    while cola:
        y, x = cola.popleft()
        for (dy, dx), magnitud, _azar in movimientos:
            destino = (y + dy * magnitud, x + dx * magnitud)
            if destino in profundidades or not es_piso(destino):
                continue
            profundidades[destino] = profundidades[(y, x)] + 1
            cola.append(destino)
    return profundidades


def costo_esperado_por_movimiento(mundo: MundoLike) -> float:
    """Pulsaciones esperadas para conseguir UN movimiento en la direccion que uno quiere. 1 si el
    mundo tiene una flecha determinista; con RUIDO hay que esperar a que el azar dispare Y elija
    esa direccion."""
    movimientos = trasladores(mundo)
    if any(not azar for _d, _m, azar in movimientos):
        return 1.0
    if movimientos:
        return len(DIRECCION_CANONICA) / PROB_DE_RUIDO
    return float("inf")


def profundidad_maxima(mundo: MundoLike) -> int:
    """Movimientos que el banco acepta cobrar por el nivel 1 en ESTE mundo, dado lo que cuesta cada
    movimiento y los clicks que se van en la pantalla de titulo."""
    costo = max(1, round(costo_esperado_por_movimiento(mundo)))
    presupuesto = PASOS_RESERVADOS_PARA_LLEGAR
    if mundo.menu:
        presupuesto -= CLICS_PARA_SALIR_DEL_MENU
    return max(1, min(PROFUNDIDAD_DEL_OBJETIVO, presupuesto // costo))


def ruta_de_nivel(mundo: MundoLike) -> str:
    """La UNICA via por la que este mundo puede subir de nivel, derivada de lo que se le midio.

    El orden importa: un mundo con flechas deterministas se mide por movimiento aunque tenga
    ACTION6 (es lo que distingue una politica que aprendio el mapeo de una que no); si no las
    tiene, el click es la via mas medible que le queda; y solo si tampoco hay click se cae al
    repintado."""
    movimientos = trasladores(mundo)
    if any(not azar for _d, _m, azar in movimientos):
        return RUTA_MOVIMIENTO
    if 6 in mundo.acciones:
        return RUTA_CLICK
    if movimientos:
        return RUTA_MOVIMIENTO
    return RUTA_REPINTADO


def orden_de_repintado(avatar: tuple[int, int] | None = None) -> list[tuple[int, int]]:
    """El orden EXACTO en que `EntornoMedido._recolorear` recorre las celdas pintables. Vive aca
    porque la colocacion del objetivo de los mundos de repintado depende de el."""
    posicion = avatar or INICIO_DEL_AVATAR
    return [
        (y, x)
        for y in range(1, ALTO_TABLERO - 1)
        for x in range(1, ANCHO - 1)
        if (y, x) != posicion and (y, x) not in PAREDES
    ]


def celdas_de_repintado(mundo: MundoLike) -> int:
    """Cuantas celdas pinta de una vez la mecanica no direccional MAS GRANDE de este mundo. Se
    elige la mas grande y no la mas chica para que el objetivo NO quede al alcance de cualquier
    boton: asi el mundo sigue discriminando entre politicas."""
    tamanos = [CELDAS_POR_FIRMA[f] for _b, f in _firmas(mundo) if f in CELDAS_POR_FIRMA]
    return max(tamanos) if tamanos else 0


def posicion_del_objetivo(
    mundo: MundoLike, rng: random.Random | None = None, avatar: tuple[int, int] | None = None
) -> tuple[int, int]:
    """Donde va el objetivo en ESTE mundo. Siempre dentro de lo que el mundo puede alcanzar."""
    ruta = ruta_de_nivel(mundo)
    origen = avatar or INICIO_DEL_AVATAR
    if ruta == RUTA_MOVIMIENTO:
        return _objetivo_por_movimiento(mundo, origen, rng)
    if ruta == RUTA_CLICK:
        return _objetivo_por_click(mundo, origen, rng)
    return _objetivo_por_repintado(mundo, origen, rng)


def _objetivo_por_movimiento(
    mundo: MundoLike, origen: tuple[int, int], rng: random.Random | None
) -> tuple[int, int]:
    profundidades = alcanzables_desde(mundo, origen)
    tope = min(profundidad_maxima(mundo), max(profundidades.values()))
    candidatas = sorted(c for c, d in profundidades.items() if d == tope)
    if not candidatas:  # solo si la reticula es un unico punto, que el guard prohibe
        candidatas = sorted(c for c in profundidades if c != origen) or [origen]
    if rng is not None:
        return rng.choice(candidatas)
    # Sin rng (colocacion inicial): la celda mas lejana del arranque, deterministica.
    return max(candidatas, key=lambda c: (abs(c[0] - origen[0]) + abs(c[1] - origen[1]), c))


def _objetivo_por_click(
    mundo: MundoLike, origen: tuple[int, int], rng: random.Random | None
) -> tuple[int, int]:
    """Una celda de piso que el click alcanza en UNA accion. La dificultad de estos mundos no es
    llegar sino ELEGIR donde clickear entre 3.657 celdas, que es justo lo que mide
    `clicksProductivos`. Se exige distancia >= PROFUNDIDAD_DEL_OBJETIVO del avatar para que no
    caiga pegada a el y la encuentre cualquier barrido local."""
    sorteo = rng or random.Random(f"objetivo:{mundo.nombre}")
    candidatas = [
        c
        for c in orden_de_repintado(origen)
        if abs(c[0] - origen[0]) + abs(c[1] - origen[1]) >= PROFUNDIDAD_DEL_OBJETIVO
    ]
    return sorteo.choice(candidatas)


def _objetivo_por_repintado(
    mundo: MundoLike, origen: tuple[int, int], rng: random.Random | None
) -> tuple[int, int]:
    """El bloque no direccional BARRE el tablero de a `celdas_de_repintado` por pulsacion, asi que
    el objetivo se pone al final del bloque numero PROFUNDIDAD_DEL_OBJETIVO: cuesta las mismas ocho
    acciones correctas que en los otros dos caminos."""
    orden = orden_de_repintado(origen)
    celdas = celdas_de_repintado(mundo)
    if celdas <= 0:  # el guard lo prohibe; ante la duda, la primera celda pintable
        return orden[0]
    # `max(2, ...)`: si algun mundo futuro pintara mas de medio tablero de una, el barrido daria
    # una sola pulsacion y `randrange(1, 1)` explotaria. Un bloque = una pulsacion, siempre >= 1.
    bloques = max(2, len(orden) // celdas)
    saltos = PROFUNDIDAD_DEL_OBJETIVO if rng is None else rng.randrange(1, bloques)
    return orden[min(celdas * saltos, len(orden)) - 1]
