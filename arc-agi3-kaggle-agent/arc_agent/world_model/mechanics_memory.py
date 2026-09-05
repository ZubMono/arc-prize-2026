"""[arc-agi3-kaggle-agent/world_model/mechanics_memory] BL.21561 -- memoria de mecanicas POR ACCION
y por EPISODIO, construida sobre `detectar_mecanica`. Puerto de
arc-agi-runner/src/worldModel/mechanicsMemory.ts.

POR ACCION acumula la firma de mecanica observada como distribucion Beta -- alpha son las veces que
la accion volvio a hacer LO MISMO, beta las veces que hizo otra cosa. Nunca un booleano: en
ARC-AGI-3 una accion de movimiento choca contra la pared cada tantos pasos y ahi no mueve nada, y
con verificacion de cero tolerancia esa unica observacion mataba la regla correcta.

POR EPISODIO implementa los dos detectores que no son de transicion:
4. MARCO/HUD: las celdas que no cambiaron NUNCA. Su complemento -- el bbox de lo que si cambio
   alguna vez -- es la ARENA: todo lo de afuera es decorado.
5. CONTADOR: un color cuya cantidad de celdas se mueve siempre en el mismo sentido es puntaje o
   vidas: senal densa de progreso.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .grid import BoundingBox, Grid, VolatilityMask, is_volatile_cell
from .object_mechanics import Mecanica, Traslacion, detectar_mecanica
from .mechanics_signature import firma_de_mecanica

# Observaciones minimas de una accion antes de afirmar que su mecanica es conocida. 2 y no 1: una
# sola coincidencia no distingue una regla de una casualidad.
MIN_OBSERVACIONES_DE_MECANICA: Final[int] = 2

# Fraccion minima de observaciones que tienen que coincidir con la firma dominante. 0.6 deja pasar
# la regla de movimiento que falla contra la pared un tercio de las veces, y no la que acierta la
# mitad.
MIN_COBERTURA_DE_MECANICA: Final[float] = 0.6

# Cambios minimos de la cuenta de un color para llamarlo contador.
MIN_CAMBIOS_DE_CONTADOR: Final[int] = 3


@dataclass(frozen=True)
class HipotesisDeMecanica:
    action: str
    firma: str
    traslacion: Traslacion | None
    alpha: int
    beta: int
    observaciones: int
    cobertura: float


@dataclass(frozen=True)
class ContadorDeColor:
    color: int
    direccion: str
    cambios: int
    delta: int


class MechanicsMemory:
    def __init__(self) -> None:
        self._por_accion: dict[str, dict[str, object]] = {}
        self._cambio_alguna_vez: list[list[bool]] | None = None
        self._alto = 0
        self._ancho = 0
        self._observaciones_totales = 0
        self._conteo_anterior: dict[int, int] | None = None
        self._contadores: dict[int, dict[str, object]] = {}

    def observe(
        self, action: str, pre: Grid, post: Grid, mask: VolatilityMask | None = None
    ) -> Mecanica:
        """Registra el efecto de `action` y devuelve la mecanica detectada (logs y tests)."""
        mecanica = self._registrar_por_accion(action, pre, post, mask)
        self._registrar_celdas_cambiadas(pre, post, mask)
        self._registrar_contadores(post, mask)
        self._observaciones_totales += 1
        return mecanica

    def observe_evidencia_adicional(
        self, action: str, pre: Grid, post: Grid, mask: VolatilityMask | None = None
    ) -> Mecanica:
        """BL.22236 -- variante de `observe()` para evidencia INTERMEDIA: una transicion entre dos
        capas de animacion del MISMO frame (`state_signature.extraer_grid_multicapa`), no el
        pre/post asentado de la accion.

        Actualiza SOLO el detector 3 (hipotesis de mecanica por-accion, via
        `_registrar_por_accion`) y NO los detectores 4/5 (arena / contador), que son POR EPISODIO
        y describen el tablero ASENTADO: una celda que aparece y desaparece durante una animacion
        de "pouring" no es parte de la arena jugable ni de un contador de progreso monotono -- es
        evidencia de la MECANICA de la accion, que es justo lo que 13/25 juegos publicos esconden
        en capas intermedias. La hipotesis por-accion ya tolera evidencia ruidosa por diseno
        (Beta + `MIN_COBERTURA_DE_MECANICA=0.6`), asi que sumar observaciones intermedias no puede
        voltear una regla bien establecida por una minoria de capas transitorias."""
        return self._registrar_por_accion(action, pre, post, mask)

    def _registrar_por_accion(
        self, action: str, pre: Grid, post: Grid, mask: VolatilityMask | None
    ) -> Mecanica:
        mecanica = detectar_mecanica(pre, post, mask)
        firma = firma_de_mecanica(mecanica)

        registro = self._por_accion.setdefault(
            action, {"conteo": {}, "traslaciones": {}, "observaciones": 0}
        )
        registro["observaciones"] = int(registro["observaciones"]) + 1
        conteo: dict[str, int] = registro["conteo"]  # type: ignore[assignment]
        conteo[firma] = conteo.get(firma, 0) + 1
        if mecanica.traslacion_principal is not None:
            traslaciones: dict[str, Traslacion] = registro["traslaciones"]  # type: ignore[assignment]
            traslaciones[firma] = mecanica.traslacion_principal
        return mecanica

    def get_hypothesis(self, action: str) -> HipotesisDeMecanica | None:
        """Firma mas observada de `action` con su Beta. None si la accion nunca se observo."""
        registro = self._por_accion.get(action)
        if registro is None:
            return None
        conteo: dict[str, int] = registro["conteo"]  # type: ignore[assignment]
        # Desempate por firma (orden lexicografico) y no por orden de insercion: dos firmas
        # empatadas tienen que resolver igual aca y en el motor TypeScript.
        firma = sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        aciertos = conteo[firma]
        observaciones = int(registro["observaciones"])
        traslaciones: dict[str, Traslacion] = registro["traslaciones"]  # type: ignore[assignment]
        return HipotesisDeMecanica(
            action=action,
            firma=firma,
            traslacion=traslaciones.get(firma),
            alpha=1 + aciertos,
            beta=1 + observaciones - aciertos,
            observaciones=observaciones,
            cobertura=aciertos / observaciones,
        )

    def get_direction(self, action: str) -> tuple[int, int] | None:
        """Direccion (dy,dx) CONFIRMADA de `action`, o None si no mueve nada / falta evidencia. Es
        el mapeo ACTION1..5 -> direccion que el DSL global nunca pudo dar sobre dato real."""
        h = self.get_hypothesis(action)
        if h is None or h.traslacion is None:
            return None
        if not h.firma.startswith("traslacion:"):
            return None
        if h.observaciones < MIN_OBSERVACIONES_DE_MECANICA:
            return None
        if h.cobertura < MIN_COBERTURA_DE_MECANICA:
            return None
        return (h.traslacion.dy, h.traslacion.dx)

    def get_movement_actions(self) -> list[str]:
        return [a for a in self._por_accion if self.get_direction(a) is not None]

    def is_inert_action(self, action: str) -> bool:
        """Accion cuya mecanica dominante es `sinCambio` con evidencia suficiente -- no-op
        observacional, sin pasar por la sintesis DSL."""
        h = self.get_hypothesis(action)
        if h is None:
            return False
        return (
            h.firma == "sinCambio"
            and h.observaciones >= MIN_OBSERVACIONES_DE_MECANICA
            and h.cobertura >= MIN_COBERTURA_DE_MECANICA
        )

    def get_active_bounding_box(self) -> BoundingBox | None:
        """DETECTOR 4 -- caja de lo que cambio alguna vez: la ARENA. Todo lo de afuera es marco
        estatico. None mientras no se observo ningun cambio."""
        if self._cambio_alguna_vez is None:
            return None
        ys: list[int] = []
        xs: list[int] = []
        for y in range(self._alto):
            for x in range(self._ancho):
                if self._cambio_alguna_vez[y][x]:
                    ys.append(y)
                    xs.append(x)
        if not ys:
            return None
        return BoundingBox(min_y=min(ys), max_y=max(ys), min_x=min(xs), max_x=max(xs))

    def get_static_cell_count(self) -> int:
        """DETECTOR 4 -- celdas que no cambiaron NUNCA en todo lo observado."""
        if self._cambio_alguna_vez is None:
            return 0
        return sum(1 for fila in self._cambio_alguna_vez for c in fila if not c)

    def is_static_cell(self, y: int, x: int) -> bool:
        if self._cambio_alguna_vez is None:
            return True
        if y < 0 or x < 0 or y >= self._alto or x >= self._ancho:
            return True
        return not self._cambio_alguna_vez[y][x]

    def get_counters(self) -> list[ContadorDeColor]:
        """DETECTOR 5 -- colores cuya cantidad de celdas se movio SIEMPRE en el mismo sentido."""
        salida: list[ContadorDeColor] = []
        for color in sorted(self._contadores):
            c = self._contadores[color]
            if c["roto"] or c["direccion"] is None:
                continue
            if int(c["cambios"]) < MIN_CAMBIOS_DE_CONTADOR:
                continue
            salida.append(
                ContadorDeColor(
                    color=color,
                    direccion=str(c["direccion"]),
                    cambios=int(c["cambios"]),
                    delta=int(c["delta"]),
                )
            )
        salida.sort(key=lambda c: (-c.cambios, c.color))
        return salida

    def get_observation_count(self) -> int:
        return self._observaciones_totales

    def _registrar_celdas_cambiadas(
        self, pre: Grid, post: Grid, mask: VolatilityMask | None
    ) -> None:
        alto = len(pre)
        ancho = len(pre[0]) if pre else 0
        if alto == 0 or ancho == 0:
            return
        # Un cambio de forma del frame reinicia el mapa: las coordenadas viejas ya no describen el
        # mismo tablero, y mezclarlas produciria una arena inventada.
        if self._cambio_alguna_vez is None or self._alto != alto or self._ancho != ancho:
            self._cambio_alguna_vez = [[False] * ancho for _ in range(alto)]
            self._alto = alto
            self._ancho = ancho
        for y in range(alto):
            fila = pre[y]
            fila_post = post[y] if y < len(post) else []
            for x in range(min(len(fila), ancho)):
                valor_post = fila_post[x] if x < len(fila_post) else None
                if fila[x] != valor_post and not is_volatile_cell(mask, y, x):
                    self._cambio_alguna_vez[y][x] = True

    def _registrar_contadores(self, post: Grid, mask: VolatilityMask | None) -> None:
        conteo: dict[int, int] = {}
        for y in range(len(post)):
            fila = post[y]
            for x in range(len(fila)):
                if is_volatile_cell(mask, y, x):
                    continue
                conteo[fila[x]] = conteo.get(fila[x], 0) + 1
        anterior = self._conteo_anterior
        self._conteo_anterior = conteo
        if anterior is None:
            return
        for color in set(anterior) | set(conteo):
            antes = anterior.get(color, 0)
            ahora = conteo.get(color, 0)
            if antes == ahora:
                continue
            direccion = "sube" if ahora > antes else "baja"
            estado = self._contadores.setdefault(
                color, {"direccion": None, "cambios": 0, "delta": 0, "roto": False}
            )
            if estado["direccion"] is not None and estado["direccion"] != direccion:
                estado["roto"] = True
            if estado["direccion"] is None:
                estado["direccion"] = direccion
            estado["cambios"] = int(estado["cambios"]) + 1
            estado["delta"] = int(estado["delta"]) + (ahora - antes)
