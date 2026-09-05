"""[arc-agi3-kaggle-agent/wall_perception] BL.21593 -- PERCEPCION del termino observable de la
verosimilitud del fallo: `P(pared | grilla)`. La pared se VE -- este modulo la mira. Espejo exacto
de la seccion homonima de arc-agi-runner/src/worldModel/mechanicsPosterior.ts.

Dos piezas, ambas capa de percepcion (consumen grilla y mecanicas de BL.21561, nunca game_id):

  - `RastreadorDeAvatar`: el avatar es el ultimo objeto que se TRASLADO (el cursor que BL.21561
    ya detecta) y el PISO es el color que dejan las celdas que desaloja -- la misma evidencia
    `relleno` que el detector de traslaciones exige. Sin esto la pared no es evaluable: saber si
    hay pared "adelante" exige saber donde esta el avatar y de que color es el suelo.
  - `contexto_de_pared`: para cada direccion, mira la franja de celdas por delante de la caja del
    avatar; borde del tablero o cualquier celda que no sea piso = pared presente.

El consumidor es la capa de creencia (mechanics_posterior.py): un fallo de movimiento con pared
presente en la direccion de la hipotesis queda TOTALMENTE explicado y no mueve el posterior."""
from __future__ import annotations

from typing import Final

from .priors import DIRECTION_PRIORS
# Import a UN solo nivel (`.world_model`): el builder del notebook desmonta los imports relativos
# con el regex `^from \.\w* import .+$` -- la forma anidada romperia el entregable.
from .world_model import Grid, Mecanica

MECANICA_ARRIBA: Final[str] = "arriba"
MECANICA_ABAJO: Final[str] = "abajo"
MECANICA_IZQUIERDA: Final[str] = "izquierda"
MECANICA_DERECHA: Final[str] = "derecha"

#: Signo (dy,dx) de cada mecanica direccional -- y crece hacia abajo, x hacia la derecha. Vive en
#: la capa de percepcion porque el contexto de pared se evalua POR DIRECCION; la capa de creencia
#: lo importa como parte del vocabulario.
DIRECCIONES: Final[dict[str, tuple[int, int]]] = {
    MECANICA_ARRIBA: (-1, 0),
    MECANICA_ABAJO: (1, 0),
    MECANICA_IZQUIERDA: (0, -1),
    MECANICA_DERECHA: (0, 1),
}

PARED_PRESENTE: Final[str] = "presente"
PARED_AUSENTE: Final[str] = "ausente"
PARED_DESCONOCIDA: Final[str] = "desconocida"


def profundidad_de_sondeo(magnitud: tuple[int, int] | None, prior: dict | None = None) -> int:
    """Cuantas celdas por delante del avatar se inspeccionan buscando pared. Si la magnitud del
    paso del boton ya se midio, el camino que el paso necesita libre es exactamente esa; si no,
    la maxima magnitud medida en los 25 juegos (conservador: ante la duda, mas fallos quedan
    explicados por pared y el posterior se mueve menos -- el lado seguro del error)."""
    if magnitud is not None:
        return max(1, abs(magnitud[0]) + abs(magnitud[1]))
    p = prior if prior is not None else DIRECTION_PRIORS
    magnitudes = [int(m) for m in p.get("magnitudesDePasoMedidas", [])]
    return max(magnitudes) if magnitudes else 1


def contexto_de_pared(
    grilla: Grid | None,
    caja: tuple[int, int, int, int] | None,
    piso: int | None,
    profundidad: int,
) -> dict[str, str]:
    """`presente`/`ausente` por direccion, mirando la franja de `profundidad` celdas por delante
    de la caja del avatar: cualquier celda que no sea del color del piso (o el borde del tablero)
    es pared. Sin avatar o sin piso conocidos, todo es `desconocida` -- el fallo inexplicable que
    aporta poco pero no cero."""
    if grilla is None or caja is None or piso is None or not grilla or not grilla[0]:
        return {nombre: PARED_DESCONOCIDA for nombre in DIRECCIONES}
    alto, ancho = len(grilla), len(grilla[0])
    min_y, min_x, alto_caja, ancho_caja = caja
    contexto: dict[str, str] = {}
    for nombre, (dy, dx) in DIRECCIONES.items():
        hay_pared = False
        for paso in range(1, profundidad + 1):
            if dy != 0:
                fila = (min_y - paso) if dy < 0 else (min_y + alto_caja - 1 + paso)
                celdas = [(fila, x) for x in range(min_x, min_x + ancho_caja)]
            else:
                columna = (min_x - paso) if dx < 0 else (min_x + ancho_caja - 1 + paso)
                celdas = [(y, columna) for y in range(min_y, min_y + alto_caja)]
            for y, x in celdas:
                if y < 0 or x < 0 or y >= alto or x >= ancho or grilla[y][x] != piso:
                    hay_pared = True
                    break
            if hay_pared:
                break
        contexto[nombre] = PARED_PRESENTE if hay_pared else PARED_AUSENTE
    return contexto


class RastreadorDeAvatar:
    """Posicion vigente del objeto controlado y el color del PISO que deja al moverse.

    El avatar es el ultimo objeto que se traslado (el cursor de BL.21561); el piso se lee de las
    celdas que DESALOJO. Es la percepcion que vuelve observable a `P(pared | grilla)`."""

    def __init__(self) -> None:
        self.caja: tuple[int, int, int, int] | None = None
        self.piso: int | None = None

    def observar(self, mecanica: Mecanica | None, post: Grid | None) -> None:
        if mecanica is None or mecanica.traslacion_principal is None or post is None:
            return
        t = mecanica.traslacion_principal
        self.caja = (t.min_y + t.dy, t.min_x + t.dx, t.alto, t.ancho)
        conteo: dict[int, int] = {}
        for y in range(t.min_y, t.min_y + t.alto):
            for x in range(t.min_x, t.min_x + t.ancho):
                en_destino = (
                    t.min_y + t.dy <= y < t.min_y + t.dy + t.alto
                    and t.min_x + t.dx <= x < t.min_x + t.dx + t.ancho
                )
                if en_destino or y < 0 or x < 0 or y >= len(post) or x >= len(post[0]):
                    continue
                color = post[y][x]
                conteo[color] = conteo.get(color, 0) + 1
        if conteo:
            # Desempate por color menor: identico en el puerto TS (orden estable, sin depender
            # del orden de insercion del diccionario).
            self.piso = max(sorted(conteo), key=lambda c: conteo[c])
