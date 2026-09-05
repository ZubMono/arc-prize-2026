"""[arc-agi3-kaggle-agent/world_model/transition_memory] -- modelo de mundo tipo STRIPS aprendido
POR ACCION: mantiene observaciones (pre, post) capadas y sintetiza (synthesis.py) el programa DSL
que las explica sin contradicciones. Confianza como distribucion Beta (alpha=exitos, beta=fracasos)
-- NUNCA un booleano. Puerto de arc-agi-runner/src/worldModel/transitionMemory.ts (BL.20860).

Shape de KnownTransition espejado a proposito del futuro `prometheusActivityMemory.
knownTransitions[]`: el campo `program` de una KnownTransition ES el programa verificado de
synthesis.py, no un sistema paralelo. Esta clase vive SOLO en memoria del proceso (un episodio de
juego) -- la persistencia entre episodios es responsabilidad de una wave posterior.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

# Imports relativos en UNA sola linea a proposito: submission/build_notebook.py los desmonta con
# `^from \.\w* import .+$` (regex de una linea) y la forma con parentesis dejaria los nombres
# sueltos y un `)` colgando dentro del notebook de Kaggle -- SyntaxError en la submission.
from .grid import Grid, VolatilityMask, neutralize_volatile_cells
from .mechanics_memory import HipotesisDeMecanica, MechanicsMemory
from .object_mechanics import Mecanica, detectar_mecanica
from .primitive_ops import EMPTY_CONTEXT, PrimitiveContext, Program, apply_program
from .synthesis import DEFAULT_SYNTHESIS_BUDGET, MIN_PROGRAM_COVERAGE, Observation, SynthesisBudget
from .synthesis import cobertura_suficiente, synthesize_program_scored, verify_program
from .volatility_mask import VolatilityTracker

# Tope de observaciones retenidas POR ACCION -- eviction FIFO simple (la mas nueva reemplaza a la
# mas vieja). Analogo acotado a la eviction por confidence x recencia x generalidad prevista para
# la coleccion persistente; aca alcanza con no crecer sin cota dentro de un episodio.
MAX_OBSERVATIONS_PER_ACTION: Final[int] = 20

# Profundidad de sintesis usada al re-sintetizar tras cada observacion -- ver synthesis.py.
SYNTHESIS_MAX_DEPTH: Final[int] = 3

# BL.21501 -- observaciones minimas antes de que un programa-identidad cuente como no-op a efectos
# de EXCLUIR la accion (ver `is_known_no_op`). Port del fix de BL.21500 en el runner TS, hecho
# ANTES de cablear este motor a la inferencia: con 1 sola observacion, `synthesize_program`
# devuelve el programa vacio en cuanto ve un pre==post (la identidad explica esa unica observacion
# a la perfeccion) y la accion quedaba descartada para siempre. Medido en juego real con el motor
# TS: ACTION6 -- el click -- se probo una vez en el paso 2 y no volvio a usarse en 76 pasos.
MIN_OBSERVATIONS_FOR_NO_OP: Final[int] = 3

# BL.21558 -- cuantas REVISIONES de la mascara de volatilidad disparan una re-sintesis completa
# (todas las acciones, no solo la observada). Hace falta porque la mascara es una PREMISA de cada
# hipotesis: un programa sintetizado antes de saber que el contador del HUD era ruido explica ese
# ruido, y queda congelado si la accion no vuelve a observarse -- que es exactamente lo que pasa,
# porque un programa no trivial la manda al fondo del ranking de exploracion. El tope acota el
# costo (una sintesis por accion y por revision); la mascara converge en las primeras decenas de
# pasos, asi que 10 revisiones cubren de sobra el arranque.
MAX_MASK_REVISIONS_RESYNTHESIZED: Final[int] = 10


def _mask_observations(
    window: list[Observation], mask: VolatilityMask | None
) -> list[Observation]:
    """Aplica la mascara a una ventana: cada `post` pasa a tener, en las celdas volatiles, el mismo
    valor que su `pre`. Asi la sintesis solo tiene que explicar el cambio REAL del tablero -- y un
    paso que solo movio el contador queda como identidad, que es justo lo que habilita a detectar
    el no-op. Sin mascara devuelve la ventana tal cual (cero copias)."""
    if mask is None:
        return window
    return [
        Observation(pre=obs.pre, post=neutralize_volatile_cells(obs.pre, obs.post, mask))
        for obs in window
    ]


def _cobertura_de_beta(alpha: int, beta: int) -> float:
    """BL.21561 -- cobertura de la hipotesis VIGENTE derivada de su propia Beta: `alpha-1` son sus
    aciertos y `beta-1` sus fallos, contados desde que se sintetizo. Esta funcion en si NUNCA
    reaplica el programa a ninguna grilla -- es aritmetica pura sobre alpha/beta. BL.22237 corrigio
    la parte que si evitaba pagar ese costo: `record_observation` ahora SI reverifica la hipotesis
    vigente contra la ventana retenida completa (`cobertura_suficiente` sobre `masked_window`) antes
    de aceptar que "sigue vigente" -- verificar contra el registro ya grabado cuesta cero acciones
    reales, a diferencia de descubrir la misma contradiccion jugando en vivo."""
    aciertos = alpha - 1
    fallos = beta - 1
    total = aciertos + fallos
    return 1.0 if total <= 0 else aciertos / total


@dataclass(frozen=True)
class KnownTransition:
    """`program`: programa DSL verificado contra TODAS las observaciones retenidas -- None si aun
    no hay una hipotesis sin contradicciones (accion todavia no comprendida).
    `alpha`/`beta`: Beta(alpha, beta), exitos/fracasos de la hipotesis ACTUAL, no un booleano.
    `observation_count`: total de veces que se observo esta accion (crece mas alla de la ventana).
    `contradiction_count`: cuantas veces una hipotesis confirmada fue contradicha por evidencia
    nueva.
    `coverage` (BL.21561): fraccion de las observaciones RETENIDAS que el programa vigente
    reproduce. 1 = la regla no falla nunca (lo unico que antes se aceptaba); 0.8 = falla una de
    cada cinco, tipico de una regla de movimiento que choca contra la pared. 0 si no hay
    programa."""

    action: str
    program: Program | None
    alpha: int
    beta: int
    observation_count: int
    contradiction_count: int
    coverage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "program": self.program,
            "alpha": self.alpha,
            "beta": self.beta,
            "observationCount": self.observation_count,
            "contradictionCount": self.contradiction_count,
            "coverage": self.coverage,
        }


class TransitionMemory:
    """`budget`, `max_observations` y `max_depth` son parametros aditivos con defaults que
    reproducen el TS exacto (alla son constantes de modulo). Estan expuestos porque el presupuesto
    de sintesis DEBE ser inyectable para el harness offline de Kaggle: dejarlos cerrados obligaria
    a tocar el motor mas tarde."""

    def __init__(
        self,
        ctx: PrimitiveContext | None = None,
        budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
        max_observations: int = MAX_OBSERVATIONS_PER_ACTION,
        max_depth: int = SYNTHESIS_MAX_DEPTH,
        mascara_de_accion_unica: bool = False,
    ) -> None:
        self._observations: dict[str, list[Observation]] = {}
        self._transitions: dict[str, KnownTransition] = {}
        self._ctx: PrimitiveContext = ctx if ctx is not None else EMPTY_CONTEXT
        self._budget = budget
        self._max_observations = max_observations
        self._max_depth = max_depth
        # BL.21558 -- que celdas del frame cambian sin relacion con la accion (HUD/contador). Vive
        # aca y no en la politica porque se aprende del MISMO flujo de observaciones que alimenta
        # la sintesis: una sola fuente, imposible que las dos se desincronicen.
        # BL.21702 -- `mascara_de_accion_unica` viaja por parametro desde `policy.py` (la palanca
        # `mascaraDeAccionUnica` de banderas.py): world_model/ no importa banderas, ver el
        # comentario en VolatilityTracker.__init__.
        self._volatility = VolatilityTracker(permitir_accion_unica=mascara_de_accion_unica)
        # BL.21561 -- analizador OBJETO-CENTRICO. Corre sobre el MISMO flujo de observaciones que
        # la sintesis DSL y es el que de verdad nombra la mecanica de la accion: en dato real el
        # DSL confirma la identidad y nada mas, mientras que este recupera el mapeo ACTION1..4 ->
        # arriba/abajo/izquierda/derecha en los cuatro juegos medidos.
        self._mechanics = MechanicsMemory()
        self._mask_version_sincronizada = 0
        self._revisiones_resintetizadas = 0

    def record_observation(self, action: str, pre: Grid, post: Grid) -> Mecanica:
        """Registra el efecto observado de `action`: pre -> post. Actualiza (o sintetiza desde
        cero) la KnownTransition de esa accion, y DEVUELVE la mecanica de objetos detectada en esa
        transicion (BL.21590: la creencia de direcciones la necesita y calcularla de nuevo en la
        politica seria correr el mismo detector dos veces por paso). Las grillas se guardan POR
        REFERENCIA, sin clonar (igual que el TS): quien llama no debe mutar las grillas que entrego,
        o la ventana de observaciones describiria un pasado que nunca ocurrio.

        BL.21558 -- la ventana guarda las grillas CRUDAS y el enmascarado se aplica recien al
        sintetizar/verificar. Guardar ya neutralizado seria un bug sutil: la mascara CRECE durante
        el episodio y las observaciones viejas habrian quedado congeladas con una mascara mas
        chica, o sea con ruido de HUD adentro que ninguna hipotesis puede explicar."""
        self._volatility.observe(action, pre, post)

        window = self._observations.get(action, [])
        window.append(Observation(pre=pre, post=post))
        if len(window) > self._max_observations:
            window.pop(0)
        self._observations[action] = window

        mask = self._volatility.mask
        # BL.21561 -- el analizador objeto-centrico ve el par CRUDO con la mascara vigente: no
        # necesita que le neutralicen nada porque ya ignora las celdas volatiles el mismo.
        mecanica = self._mechanics.observe(action, pre, post, mask)

        masked_window = _mask_observations(window, mask)
        last_observation = masked_window[-1]

        # La mascara cambio: toda hipotesis vigente se dedujo bajo OTRAS premisas y hay que
        # rehacerla. Sin esto el fix no llega a la partida -- una accion observada antes de que la
        # mascara existiera se queda con un programa que "explica" el avance del contador, y ese
        # programa no trivial la manda al fondo del ranking de exploracion.
        mascara_cambio = self._volatility.version != self._mask_version_sincronizada
        if mascara_cambio:
            self._mask_version_sincronizada = self._volatility.version
            if self._revisiones_resintetizadas < MAX_MASK_REVISIONS_RESYNTHESIZED:
                self._revisiones_resintetizadas += 1
                self._resintetizar_otras_acciones(action, mask)

        previous = self._transitions.get(action)
        observation_count = (previous.observation_count if previous else 0) + 1
        alpha = previous.alpha if previous else 1
        beta = previous.beta if previous else 1
        contradiction_count = previous.contradiction_count if previous else 0
        program = previous.program if previous else None
        coverage = previous.coverage if previous else 0.0

        had_confirmed = previous is not None and previous.program is not None
        # Con la mascara recien cambiada NO se acepta la hipotesis previa aunque verifique contra
        # la ultima observacion: se dedujo mirando celdas que ahora se sabe que son ruido.
        coincide_con_la_ultima = (
            had_confirmed
            and not mascara_cambio
            and verify_program(previous.program, [last_observation], self._ctx)
        )
        # BL.22237 -- coincidir con la ultima observacion YA NO ALCANZA: una hipotesis puede pasar
        # ese chequeo y sin embargo contradecir una observacion MAS VIEJA que sigue retenida en la
        # ventana, sin que nada lo detecte hasta que falle de nuevo EN VIVO -- gastando una accion
        # real para descubrir una contradiccion que ya estaba en la propia memoria. Es la capacidad
        # que la ablacion aislada de Rodionov/SingularityNET mide con MAYOR impacto (~99% RHAE,
        # tambien nombrada "Retrodict"): verificar contra el registro YA GRABADO cuesta cero
        # acciones reales. Se revalida entonces contra la VENTANA RETENIDA COMPLETA
        # (`masked_window`, hasta MAX_OBSERVATIONS_PER_ACTION), con la MISMA tolerancia que ya usa
        # la sintesis puntuada (BL.21561): identidad EXACTA -- aceptarla a medias equivale a
        # declarar no-op una accion que a veces SI hace algo -- y el resto hasta
        # MIN_PROGRAM_COVERAGE, el mismo umbral, fuente de la verdad unica. `cobertura_suficiente`
        # abandona temprano (recorre de la mas nueva a la mas vieja), asi que el costo de este
        # chequeo extra no es sistematicamente 20x -- solo lo paga completo una hipotesis que de
        # verdad sigue siendo buena.
        cobertura_retenida = (
            cobertura_suficiente(
                previous.program,
                masked_window,
                self._ctx,
                1.0 if len(previous.program) == 0 else MIN_PROGRAM_COVERAGE,
            )
            if coincide_con_la_ultima
            else None
        )
        still_holds = cobertura_retenida is not None

        if still_holds:
            # alpha/beta se recalculan contra la ventana COMPLETA en vez de incrementarse a
            # ciegas: antes `beta` quedaba CONGELADO en el valor de la ultima resintesis y
            # `coverage` nunca podia volver a 1.0 aunque la observacion que la contradijo ya
            # hubiera salido de la ventana por FIFO -- `is_known_no_op` excluia esa accion de la
            # exploracion PARA SIEMPRE por una contradiccion que la propia memoria ya olvido.
            alpha = 1 + cobertura_retenida.aciertos
            beta = 1 + cobertura_retenida.fallos
        else:
            # Una hipotesis descartada por CAMBIO DE PREMISAS (la mascara) no es una contradiccion
            # de la evidencia: no dice nada sobre lo predecible que es la accion, y contarla como
            # fracaso hundiria la confianza de acciones que nunca fallaron.
            if had_confirmed and not mascara_cambio:
                contradiction_count += 1
            # BL.21561 -- se acepta el programa de MAYOR cobertura y sus fallos se contabilizan en
            # beta en vez de matar la hipotesis. alpha/beta describen la hipotesis VIGENTE, y esta
            # es NUEVA: se recalculan desde su propia evidencia, con prior Beta(1,1).
            puntuado = synthesize_program_scored(
                masked_window, self._ctx, self._max_depth, self._budget
            )
            program = puntuado.program
            alpha = 1 + puntuado.aciertos
            beta = 1 + puntuado.fallos
        coverage = 0.0 if program is None else _cobertura_de_beta(alpha, beta)

        self._transitions[action] = KnownTransition(
            action=action,
            program=program,
            alpha=alpha,
            beta=beta,
            observation_count=observation_count,
            contradiction_count=contradiction_count,
            coverage=coverage,
        )
        return mecanica

    def get_transition(self, action: str) -> KnownTransition | None:
        return self._transitions.get(action)

    def get_known_transitions(self) -> list[KnownTransition]:
        # Orden de primera insercion: el dict de Python se comporta como el Map de JS.
        return list(self._transitions.values())

    def get_confidence(self, action: str) -> float:
        """Confianza actual (0-1) en la hipotesis vigente de `action`. Prior uniforme (0.5) si
        nunca se observo."""
        t = self._transitions.get(action)
        if t is None:
            return 0.5
        return t.alpha / (t.alpha + t.beta)

    def predict(self, action: str, grid: Grid) -> Grid | None:
        """Predice el resultado de aplicar `action` sobre `grid` usando el programa confirmado --
        None si la accion aun no tiene una hipotesis sin contradicciones."""
        t = self._transitions.get(action)
        if t is None or t.program is None:
            return None
        return apply_program(t.program, grid, self._ctx)

    def is_known_no_op(self, action: str) -> bool:
        """True si la accion tiene un programa confirmado que es la identidad (no cambia nada) Y
        hay evidencia suficiente -- no-op conocido, el equivalente de `no_op_actions` en policy.py
        pero derivado del MISMO mecanismo de sintesis, no de un chequeo separado.

        BL.21501: exige MIN_OBSERVATIONS_FOR_NO_OP observaciones. La SINTESIS sigue concluyendo
        identidad con una sola (y `predict` lo refleja); lo que cambia es cuando esa conclusion
        habilita a EXCLUIR la accion de la exploracion. Sin esto, cablear este motor a la politica
        reintroduciria el lockout que BL.21500 (runner TS) y BL.21518 (politica Python) acaban de
        eliminar -- en ARC-AGI-3 una accion parametrizada por coordenada es no-op donde no hay
        nada y significativa en otro lado."""
        t = self._transitions.get(action)
        if t is None or t.program is None or len(t.program) != 0:
            return False
        # BL.21561 -- con cobertura puntuada, un programa puede ser "el que mejor explica" sin
        # explicar todo. Para EXCLUIR una accion se sigue exigiendo evidencia exacta: una identidad
        # que falla una de cada cinco veces significa que la accion SI hace algo a veces.
        if t.coverage < 1:
            return False
        # Y si el analizador objeto-centrico vio a esta accion mover un objeto, no es un no-op por
        # mas que la ventana retenida de la sintesis diga identidad.
        if self._mechanics.get_direction(action) is not None:
            return False
        return t.observation_count >= MIN_OBSERVATIONS_FOR_NO_OP

    def get_observation_count(self, action: str) -> int:
        t = self._transitions.get(action)
        return t.observation_count if t is not None else 0

    def declarar_acciones_disponibles(self, cantidad_de_acciones: int) -> None:
        """BL.21702 -- le informa al rastreador de volatilidad cuantos botones OFRECE el juego. Es
        lo que habilita el modo de accion unica de la mascara en los seis juegos publicos que
        exponen `availableActions=[6]`."""
        self._volatility.declarar_vocabulario(cantidad_de_acciones)

    def get_volatility_mask(self) -> VolatilityMask | None:
        """BL.21558 -- mascara de volatilidad vigente (None mientras no haya evidencia suficiente).
        La expone la politica para firmar estados y comparar frames sobre las MISMAS celdas que el
        modelo de mundo considera informativas."""
        return self._volatility.mask

    def get_volatility_version(self) -> int:
        """Version del conjunto de celdas volatiles -- cambia cuando la mascara cambia. Quien
        compare dos firmas calculadas en momentos distintos tiene que verificar que sean de la
        MISMA version, o estaria comparando hashes de dos definiciones de "estado"."""
        return self._volatility.version

    def get_volatile_cell_count(self) -> int:
        """Celdas actualmente enmascaradas -- solo para observabilidad (logs y tests de efecto)."""
        return self._volatility.volatile_cell_count()

    def get_mechanic(self, action: str) -> HipotesisDeMecanica | None:
        """BL.21561 -- mecanica de objetos dominante de `action` (traslacion / recoloreo /
        aparicion / desaparicion / sinCambio) con su Beta. None si nunca se observo."""
        return self._mechanics.get_hypothesis(action)

    def get_movement_direction(self, action: str) -> tuple[int, int] | None:
        """BL.21561 -- direccion (dy,dx) que `action` imprime al objeto controlado, o None si no
        mueve nada / falta evidencia. ES el mapeo ACTION1..5 -> direccion que el DSL global nunca
        pudo dar sobre dato real."""
        return self._mechanics.get_direction(action)

    def get_mechanics_memory(self) -> MechanicsMemory:
        """BL.21561 -- analizador objeto-centrico completo: detectores de marco estatico (4) y de
        contadores monotonos (5), ademas de las hipotesis por accion."""
        return self._mechanics

    def analyze_transition(self, pre: Grid, post: Grid) -> Mecanica:
        """BL.21561 -- mecanica detectada para un par suelto, sin registrarla."""
        return detectar_mecanica(pre, post, self._volatility.mask)

    def _resintetizar_otras_acciones(
        self, actual: str, mask: VolatilityMask | None
    ) -> None:
        """Rehace la hipotesis de todas las acciones MENOS la observada (esa la rehace el flujo
        normal de `record_observation`, que ya tiene la ventana actualizada). Se sintetiza sobre la
        ventana cruda reenmascarada, y la confianza vuelve al prior: alpha y beta describen los
        exitos/fracasos de la hipotesis VIGENTE, y esta es otra."""
        for accion, window in self._observations.items():
            if accion == actual:
                continue
            previa = self._transitions.get(accion)
            if previa is None:
                continue
            puntuado = synthesize_program_scored(
                _mask_observations(window, mask), self._ctx, self._max_depth, self._budget
            )
            alpha = 1 + puntuado.aciertos
            beta = 1 + puntuado.fallos
            self._transitions[accion] = KnownTransition(
                action=previa.action,
                program=puntuado.program,
                alpha=alpha,
                beta=beta,
                observation_count=previa.observation_count,
                contradiction_count=previa.contradiction_count,
                coverage=0.0 if puntuado.program is None else _cobertura_de_beta(alpha, beta),
            )
