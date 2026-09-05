"""[arc-agi3-kaggle-agent/tests/support/entornos_bl21702] BL.21702 -- entornos de juguete que
reproducen la PATOLOGIA MEDIDA de cada uno de los siete juegos atascados, compartidos por los dos
archivos de tests del BL (`test_bl21702_palancas.py` y `test_bl21702_reset_congelado.py`).

No son "un juego generico": cada clase esta calcada de un modo de falla que el diagnostico midio
contra los entornos REALES (arcengine offline, 151 acciones por juego, semilla bl21702a).

  `_AccionCosmetica`            sb26  -- ACTION5 mueve pixeles SIEMPRE pero recorre un ciclo
                                        cerrado. Medido: 125 de 151 acciones (82,8%).
  `ClickConFirmaSiempreNueva`   su15/tn36 -- un contador anima el frame, asi que NINGUNA firma se
                                        repite y la memoria por `(firma,x,y)` no bloquea nada.
                                        Medido: 5 coordenadas distintas en 138 clicks, 9 en 149.
  `TableroCongelado`            lf52  -- el frame es IDENTICO paso a paso y no hay game-over que
                                        rescate. Medido: 47 revisitas con gap=1, 2 game-over.
  `CicloLargo`                  tn36/tu93/sb26/su15 -- revisitas de periodo FIJO con el frame
                                        cambiando en cada paso. Es el CONTRAEJEMPLO del RESET.
"""
from __future__ import annotations

from arc_agent.banderas import Banderas
from arc_agent.policy import ExplorationPolicy
from arc_agent.prng import create_seeded_random
from arc_agent.types import FrameData, GameAction, GameState

#: Largo del ciclo cerrado de la accion cosmetica.
CICLO_COSMETICO = 6


class AccionCosmetica:
    """sb26: ACTION5 SIEMPRE mueve pixeles, pero recorre un ciclo cerrado de `CICLO_COSMETICO`
    estados. ACTION6 y ACTION7 no hacen nada."""

    DISPONIBLES = (5, 6, 7)

    def __init__(self) -> None:
        self._fase = 0
        self._guid = 0

    def _grilla(self) -> tuple[tuple[int, ...], ...]:
        filas = [[0] * 8 for _ in range(8)]
        filas[0][self._fase % CICLO_COSMETICO] = 5
        return tuple(tuple(f) for f in filas)

    def frame(self) -> FrameData:
        self._guid += 1
        return FrameData(
            game_id="cosmetico",
            guid=f"g{self._guid}",
            frame=(self._grilla(),),
            state=GameState.NOT_FINISHED,
            available_actions=self.DISPONIBLES,
        )

    def step(self, accion: GameAction) -> FrameData:
        if accion is GameAction.ACTION5:
            self._fase = (self._fase + 1) % CICLO_COSMETICO
        return self.frame()


class ClickConFirmaSiempreNueva:
    """su15/tn36: un contador anima el frame en cada paso, asi que ninguna firma se repite y la
    memoria por `(firma,x,y)` no bloquea NADA."""

    DISPONIBLES = (6,)
    LADO = 16

    def __init__(self) -> None:
        self._guid = 0
        self._contador = 0

    def frame(self) -> FrameData:
        self._guid += 1
        filas = [[0] * self.LADO for _ in range(self.LADO)]
        # Marco: le da al ranker un maximo de puntaje estable, igual que un tablero real.
        for x in range(2, self.LADO - 2):
            filas[2][x] = 3
            filas[self.LADO - 3][x] = 3
        # Contador que cambia SIEMPRE -- el ruido que rompe la firma.
        filas[0][self._contador % self.LADO] = 1 + (self._contador // self.LADO) % 8
        return FrameData(
            game_id="clickruidoso",
            guid=f"g{self._guid}",
            frame=(tuple(tuple(f) for f in filas),),
            state=GameState.NOT_FINISHED,
            available_actions=self.DISPONIBLES,
        )

    def step(self, _accion: GameAction) -> FrameData:
        self._contador += 1
        return self.frame()


class TableroCongelado:
    """lf52: el frame es IDENTICO paso a paso, haga el agente lo que haga, y no hay game-over que
    rescate. Solo ofrece ACTION6, que es donde la decision es DONDE y no QUE."""

    DISPONIBLES = (6,)

    def __init__(self) -> None:
        self._guid = 0
        self._grid = tuple(tuple(0 for _ in range(16)) for _ in range(16))

    def frame(self) -> FrameData:
        self._guid += 1
        return FrameData(
            game_id="congelado",
            guid=f"g{self._guid}",
            frame=(self._grid,),
            state=GameState.NOT_FINISHED,
            available_actions=self.DISPONIBLES,
        )

    def step(self, _accion: GameAction) -> FrameData:
        return self.frame()


class CicloLargo:
    """tn36/tu93: el frame cambia en CADA paso y el juego recorre un ciclo cerrado de periodo fijo.
    Contraejemplo del RESET voluntario: revisitar no es congelarse."""

    DISPONIBLES = (6,)
    PERIODO = 11

    def __init__(self) -> None:
        self._guid = 0
        self._fase = 0

    def frame(self) -> FrameData:
        self._guid += 1
        filas = [[0] * 16 for _ in range(16)]
        filas[0][self._fase] = 3
        return FrameData(
            game_id="ciclo",
            guid=f"g{self._guid}",
            frame=(tuple(tuple(f) for f in filas),),
            state=GameState.NOT_FINISHED,
            available_actions=self.DISPONIBLES,
        )

    def step(self, _accion: GameAction) -> FrameData:
        self._fase = (self._fase + 1) % self.PERIODO
        return self.frame()


def correr(
    entorno, banderas: Banderas, pasos: int = 90, semilla: str = "bl21702"
) -> tuple[ExplorationPolicy, list[GameAction]]:
    """Juega `pasos` decisiones contra el entorno y devuelve la politica (para leerle las metricas
    de las palancas) y la secuencia de acciones emitidas."""
    politica = ExplorationPolicy(create_seeded_random(semilla), banderas)
    frame = entorno.frame()
    acciones: list[GameAction] = []
    for _ in range(pasos):
        decision = politica.decide(frame)
        acciones.append(decision.action)
        frame = entorno.step(decision.action)
    return politica, acciones
