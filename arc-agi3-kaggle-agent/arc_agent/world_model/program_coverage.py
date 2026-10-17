"""[arc-agi3-kaggle-agent/world_model/program_coverage] BL.21561 -- cuanto de la evidencia explica
un programa del DSL. Puerto de arc-agi-runner/src/worldModel/programCoverage.ts; separado de
synthesis.py por el mismo motivo que alla (limite de tamano de archivo) pero conceptualmente parte
de la sintesis: es el criterio con el que se acepta o se descarta una hipotesis.

POR QUE DEJO DE SER UN BOOLEANO. `verify_program` exigia que TODAS las observaciones encajaran con
cero contradicciones, asi que una regla CORRECTA moria en la primera observacion que no encajaba
-- y en ARC-AGI-3 esa observacion llega siempre: es el choque contra la pared. "Mover a la
izquierda" explica 9 de cada 10 pasos y falla el decimo porque el cursor ya estaba pegado al borde;
con cero tolerancia el agente concluye que no entiende la accion y vuelve a explorar al azar. La
cobertura puntuada conserva la regla y manda los fallos a la Beta(alpha, beta), que es donde el
modelo de mundo ya representa la incertidumbre.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, NamedTuple

from .grid import Grid, grids_equal
from .primitive_ops import EMPTY_CONTEXT, PrimitiveContext, Program, apply_program

# Cobertura minima para aceptar un programa como hipotesis vigente. Por debajo, la "regla" no
# explica ni dos de cada tres observaciones: es ruido y conviene decir None.
MIN_PROGRAM_COVERAGE: Final[float] = 0.6


@dataclass(frozen=True)
class Observation:
    """Un par (pre, post) observado para una misma accion. Vive aca y no en synthesis.py porque
    este modulo es el que lo consume primero; synthesis.py lo re-exporta para no cambiarle el
    import a ningun consumidor."""

    pre: Grid
    post: Grid

    def to_dict(self) -> dict[str, Grid]:
        return {"pre": self.pre, "post": self.post}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Observation":
        return Observation(pre=raw["pre"], post=raw["post"])


class ProgramCoverage(NamedTuple):
    aciertos: int
    fallos: int
    # aciertos / (aciertos + fallos). Sin observaciones vale 1 (nada que contradiga).
    cobertura: float


def program_coverage(
    program: Program,
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
) -> ProgramCoverage:
    """Cuenta cuantas observaciones reproduce el programa y cuantas no -- la evidencia con la que
    se alimenta la Beta(alpha, beta) de la transicion."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    aciertos = 0
    fallos = 0
    for obs in observations:
        if grids_equal(apply_program(program, obs.pre, ctx), obs.post):
            aciertos += 1
        else:
            fallos += 1
    total = aciertos + fallos
    return ProgramCoverage(
        aciertos=aciertos, fallos=fallos, cobertura=1.0 if total == 0 else aciertos / total
    )


def cobertura_suficiente(
    program: Program,
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    min_coverage: float = MIN_PROGRAM_COVERAGE,
) -> ProgramCoverage | None:
    """Igual que `program_coverage` pero ABANDONA en cuanto el candidato ya no puede llegar a
    `min_coverage` (devuelve None). Es lo que mantiene el costo de la sintesis donde estaba: la
    verificacion de cero tolerancia cortaba en el PRIMER fallo, y contar siempre las N
    observaciones multiplicaba por N el precio de descartar un candidato malo.

    Recorre de la observacion MAS NUEVA a la mas vieja: tras una contradiccion, la evidencia que
    descarta al candidato suele ser la ultima, asi que el abandono llega en el primer paso."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    total = len(observations)
    if total == 0:
        return ProgramCoverage(aciertos=0, fallos=0, cobertura=1.0)
    fallos_tolerados = int(total * (1 - min_coverage))
    aciertos = 0
    fallos = 0
    for obs in reversed(observations):
        if grids_equal(apply_program(program, obs.pre, ctx), obs.post):
            aciertos += 1
        else:
            fallos += 1
            if fallos > fallos_tolerados:
                return None
    return ProgramCoverage(aciertos=aciertos, fallos=fallos, cobertura=aciertos / total)


def verify_program(
    program: Program,
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
) -> bool:
    """Verificacion de CERO tolerancia. Sigue siendo la regla dura para preguntas de "esto encaja
    exacto?" -- por ejemplo, si la hipotesis vigente sobrevive a la ultima observacion. La
    SELECCION de hipotesis ya no la usa: ver `synthesize_program_scored` en synthesis.py. Sin
    observaciones devuelve True, misma semantica que Array.every sobre una lista vacia."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    return all(grids_equal(apply_program(program, obs.pre, ctx), obs.post) for obs in observations)
