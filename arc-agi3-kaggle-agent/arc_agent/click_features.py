"""[arc-agi3-kaggle-agent/click_features] BL.21560 -- vector de features POR CELDA para decidir donde
clickear (ACTION6) y su combinacion lineal con los pesos de priors.py. Espejo de
arc-agi-runner/src/worldModel/clickFeatures.ts.

POR QUE ESTAS FEATURES. Todas salen de helpers que YA existen (`grid.py` + `_find_components`): es la
misma segmentacion que ve el modelo de mundo, no una vision paralela. Y ninguna mira coordenadas
absolutas ni identificadores de partida -- un peso aprendido en un juego tiene que poder servir en
otro, que es la unica razon para transportar pesos.

La feature que mas separa en el corpus real es `componenteRodeadaDeFondo`: el mismo dibujo (una ficha
6x6 de color 9) aparece DOS veces en pantalla de ft09 -- como panel decorativo rodeado por el fondo, y
como ficha jugable rodeada por el marco del tablero. Clickear la primera no hace nada (62 clicks
muertos medidos); clickear la segunda funciono 32 de 32 veces. Nada del color ni del tamano las
distingue: lo hace el VECINDARIO de su componente. OJO con generalizar de mas -- en lp85-305b61c3 la
relacion es la inversa, y por eso el peso de esta feature esta regularizado y la evidencia del
episodio (plantillas de click_targeting.py) pesa mas que el prior.
"""
from __future__ import annotations

import math
from typing import Sequence

# Import a UN solo nivel (`.world_model`): el builder del notebook desmonta los imports relativos
# con el regex `^from \.\w* import .+$`, que no cubre un segundo punto.
from .world_model import Grid, detect_background_color, foreground_bounding_box
from .world_model import _find_components


CLICK_FEATURE_NAMES: tuple[str, ...] = (
    "sesgo",
    "bordeDeColor",
    "tamanoComponente",
    "esBordeDeComponente",
    "rarezaDeColor",
    "esColorDeFondo",
    "distanciaAlBboxDeForeground",
    "componenteRodeadaDeFondo",
    "enRegionQueCambio",
)

CLICK_FEATURE_COUNT = len(CLICK_FEATURE_NAMES)

#: Normalizador de `tamanoComponente`. 256 celdas = 1/16 de un frame 64x64: por encima de eso la
#: "componente" ya es una region de fondo o un panel entero, no un objeto clickeable.
TAMANO_COMPONENTE_SATURACION = 256


def _bbox_contiene(bbox: tuple[int, int, int, int], x: int, y: int) -> bool:
    min_x, min_y, max_x, max_y = bbox
    return min_x <= x <= max_x and min_y <= y <= max_y


def _distancia_al_bbox(bbox: tuple[int, int, int, int], x: int, y: int) -> int:
    """Distancia Chebyshev al rectangulo, 0 si (x,y) esta adentro."""
    min_x, min_y, max_x, max_y = bbox
    dx = max(min_x - x, 0, x - max_x)
    dy = max(min_y - y, 0, y - max_y)
    return max(dx, dy)


class ClickFeatureBoard:
    """Features de TODAS las celdas de una grilla, calculadas una sola vez por frame: segmentar en
    componentes es O(celdas) y rehacerlo por candidato seria cuadratico."""

    __slots__ = (
        "_grid",
        "ancho",
        "alto",
        "color_de_fondo",
        "_etiqueta",
        "_tamanos",
        "_rodeada_de_fondo",
        "_conteo_de_color",
        "_fg_bbox",
        "_region_cambiada",
        "_total",
    )

    def __init__(
        self, grid: Grid, region_cambiada: tuple[int, int, int, int] | None = None
    ) -> None:
        self._grid = grid
        self.alto = len(grid)
        self.ancho = len(grid[0]) if self.alto > 0 else 0
        self._total = self.ancho * self.alto
        self.color_de_fondo = detect_background_color(grid)
        caja = foreground_bounding_box(grid, self.color_de_fondo)
        self._fg_bbox = (
            None if caja is None else (caja.min_x, caja.min_y, caja.max_x, caja.max_y)
        )
        self._region_cambiada = region_cambiada

        conteo: dict[int, int] = {}
        for fila in grid:
            for celda in fila:
                conteo[celda] = conteo.get(celda, 0) + 1
        self._conteo_de_color = conteo

        etiqueta = [-1] * self._total
        componentes = _find_components(grid, self.color_de_fondo)
        tamanos = [len(c) for c in componentes]
        for i, celdas in enumerate(componentes):
            for cx, cy in celdas:
                etiqueta[cy * self.ancho + cx] = i
        self._etiqueta = etiqueta
        self._tamanos = tamanos

        # Fraccion del CONTORNO de cada componente que toca el color de fondo. Es lo que separa un
        # panel decorativo (flotando sobre el fondo) de una ficha dentro de un tablero (rodeada por
        # el marco): en ft09 el MISMO dibujo aparece de las dos formas y solo la segunda responde al
        # click -- 32 de 32 productivos contra 62 muertos sobre el dibujo gemelo.
        rodeada = [0.0] * len(componentes)
        for i, celdas in enumerate(componentes):
            contorno = 0
            contorno_de_fondo = 0
            for cx, cy in celdas:
                for vx, vy in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    dentro = 0 <= vx < self.ancho and 0 <= vy < self.alto
                    if dentro and etiqueta[vy * self.ancho + vx] == i:
                        continue
                    contorno += 1
                    if dentro and grid[vy][vx] == self.color_de_fondo:
                        contorno_de_fondo += 1
            rodeada[i] = contorno_de_fondo / contorno if contorno > 0 else 0.0
        self._rodeada_de_fondo = rodeada

    def tamano_de_componente(self, x: int, y: int) -> int:
        if not (0 <= x < self.ancho and 0 <= y < self.alto):
            return 0
        ident = self._etiqueta[y * self.ancho + x]
        return 0 if ident < 0 else self._tamanos[ident]

    def features(self, x: int, y: int) -> list[float]:
        if not (0 <= x < self.ancho and 0 <= y < self.alto):
            return [0.0] * CLICK_FEATURE_COUNT
        grid = self._grid
        valor = grid[y][x]
        ident = self._etiqueta[y * self.ancho + x]

        borde_de_color = 0
        if x > 0 and grid[y][x - 1] != valor:
            borde_de_color += 1
        if x + 1 < self.ancho and grid[y][x + 1] != valor:
            borde_de_color += 1
        if y > 0 and grid[y - 1][x] != valor:
            borde_de_color += 1
        if y + 1 < self.alto and grid[y + 1][x] != valor:
            borde_de_color += 1

        tamano = 0 if ident < 0 else self._tamanos[ident]
        # Borde de la COMPONENTE, no de la grilla: una celda cuya componente se corta contra el
        # limite del frame tambien cuenta (el vecino inexistente no pertenece a la componente).
        es_borde = ident >= 0 and (
            x == 0
            or y == 0
            or x == self.ancho - 1
            or y == self.alto - 1
            or self._etiqueta[y * self.ancho + (x - 1)] != ident
            or self._etiqueta[y * self.ancho + (x + 1)] != ident
            or self._etiqueta[(y - 1) * self.ancho + x] != ident
            or self._etiqueta[(y + 1) * self.ancho + x] != ident
        )

        conteo = self._conteo_de_color.get(valor, 0)
        rareza = 1 - conteo / self._total if self._total > 0 else 0.0
        max_distancia = max(self.ancho, self.alto, 1)

        return [
            1.0,
            borde_de_color / 4,
            min(1.0, tamano / TAMANO_COMPONENTE_SATURACION),
            1.0 if es_borde else 0.0,
            rareza,
            1.0 if valor == self.color_de_fondo else 0.0,
            1.0
            if self._fg_bbox is None
            else _distancia_al_bbox(self._fg_bbox, x, y) / max_distancia,
            0.0 if ident < 0 else self._rodeada_de_fondo[ident],
            1.0
            if self._region_cambiada is not None
            and _bbox_contiene(self._region_cambiada, x, y)
            else 0.0,
        ]


def puntuar_celda(features: Sequence[float], pesos: Sequence[float]) -> float:
    """Producto punto features x pesos (logit). Largos distintos se recortan al minimo comun: unos
    priors regenerados con una feature de mas nunca deben tumbar una partida."""
    return sum(f * p for f, p in zip(features, pesos))


def sigmoide(logit: float) -> float:
    """Probabilidad logistica -- solo para reportar/umbralar; el ranking usa el logit directo.
    Formulada por rama para no desbordar `exp` con logits grandes."""
    if logit >= 0:
        return 1 / (1 + math.exp(-logit))
    e = math.exp(logit)
    return e / (1 + e)
