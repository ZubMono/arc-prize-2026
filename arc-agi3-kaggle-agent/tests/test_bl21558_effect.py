"""[arc-agi3-kaggle-agent/tests/test_bl21558_effect] BL.21558 -- TESTS DE EFECTO, no de humo.

Leccion explicita de BL.21500/BL.21518, que este archivo existe para no repetir: un fix anterior
"pasaba los tests" y tuvo efecto CERO sobre 400 decisiones reales, porque los tests verificaban que
la funcion no explotara en vez de verificar que la accion volviera a elegirse. Aca cada test mide
una MAGNITUD OBSERVABLE -- cuantas firmas distintas produce un episodio, cuantos no-ops se
detectan, si la sintesis llega a concluir la identidad -- sobre la MISMA trayectoria con y sin
mascara.

El escenario reproduce la patologia medida en `prometheusEvaluationRuns` (ar25-0c556536 = 76 firmas
unicas / 78 pasos; lf52-271a04aa = 94/94; dc22-fdcac232 = 128/129; ka59 = 100/101): un HUD que
avanza en CADA frame pase lo que pase.
"""
from __future__ import annotations

from arc_agent.policy import ExplorationPolicy, compute_signature
from arc_agent.prng import create_seeded_random
from arc_agent.types import FrameData, GameState
from arc_agent.world_model import Observation, TransitionMemory, synthesize_program

_PASOS = 40
_ACCIONES_DISPONIBLES = (1, 2, 3)


def _grid_con_hud(contador: int) -> tuple[tuple[int, ...], ...]:
    """Tablero 3x3 CONSTANTE + fila de HUD con dos contadores de periodos coprimos (11 y 13). El
    tablero no cambia nunca: todos los pasos son, de verdad, el mismo estado -- y sin mascara
    ninguna firma lo dice."""
    return (
        (0, 0, 0),
        (0, 5, 0),
        (contador % 11, contador % 13, 0),
    )


def _frame_con_hud(contador: int) -> FrameData:
    return FrameData(
        game_id="g-hud",
        guid="guid-1",
        frame=(_grid_con_hud(contador),),
        state=GameState.NOT_FINISHED,
        available_actions=_ACCIONES_DISPONIBLES,
    )


def test_las_firmas_de_estado_vuelven_a_repetirse() -> None:
    """Sin mascara: una firma nueva por paso, igual que los 94/94 medidos en lf52-271a04aa. Con
    mascara: UNA sola, porque el tablero no cambio en todo el episodio."""
    frames = [_frame_con_hud(i) for i in range(_PASOS)]
    sin_mascara = {compute_signature(f) for f in frames}
    assert len(sin_mascara) == _PASOS

    policy = ExplorationPolicy(create_seeded_random("bl21558-firmas"))
    for frame in frames:
        policy.decide(frame)

    mask = policy._world_model.get_volatility_mask()  # noqa: SLF001
    assert mask is not None
    con_mascara = {compute_signature(f, mask) for f in frames}
    assert len(con_mascara) == 1


def test_la_memoria_por_estado_deja_de_ser_un_estado_por_paso() -> None:
    """Consecuencia directa: `_memory` esta indexada por firma. Con una firma nueva por paso nunca
    acumula evidencia sobre ningun estado y la deteccion de no-ops no puede disparar."""
    policy = ExplorationPolicy(create_seeded_random("bl21558-memoria"))
    for i in range(_PASOS):
        policy.decide(_frame_con_hud(i))

    # Hay una entrada por firma; las primeras (previas a la mascara) son irrepetibles, pero a
    # partir de ahi el episodio entero colapsa a un unico estado.
    assert len(policy._memory) < _PASOS / 2  # noqa: SLF001
    # Y con evidencia repetida sobre el MISMO estado, la politica por fin marca no-ops.
    marcados = {a for entry in policy._memory.values() for a in entry.no_op_actions}  # noqa: SLF001
    assert marcados, "ninguna accion se marco no-op pese a que ninguna cambia el tablero"


def test_resucita_la_sintesis_de_identidad() -> None:
    """Sobre el par CRUDO la sintesis no puede explicar nada (tendria que reproducir el contador,
    que ningun programa del DSL de tablero genera). A traves de TransitionMemory -- que aprende la
    mascara y sintetiza sobre el diff enmascarado -- concluye la identidad."""
    pares = [
        ([list(f) for f in _grid_con_hud(i)], [list(f) for f in _grid_con_hud(i + 1)])
        for i in range(_PASOS)
    ]

    crudo = synthesize_program(
        [Observation(pre=pre, post=post) for pre, post in pares[:3]], None, 3
    )
    assert crudo is None

    memory = TransitionMemory()
    for i, (pre, post) in enumerate(pares):
        memory.record_observation(f"ACTION{1 + i % 3}", pre, post)

    assert memory.get_volatile_cell_count() == 2  # exactamente las dos celdas del contador
    transicion = memory.get_transition("ACTION1")
    assert transicion is not None
    assert transicion.program == []  # identidad, no None
    assert memory.is_known_no_op("ACTION1") is True


def test_una_hipotesis_previa_a_la_mascara_se_rehace_cuando_la_mascara_aparece() -> None:
    """La mascara es una PREMISA de la hipotesis. Una accion observada ANTES de que existiera se
    queda con un programa que "explica" el avance del contador, y ese programa no trivial la manda
    al fondo del ranking de exploracion -- con lo cual nunca se vuelve a observar ni a corregir."""
    memory = TransitionMemory()

    def grid(contador: int) -> list[list[int]]:
        return [list(fila) for fila in _grid_con_hud(contador)]

    memory.record_observation("INERTE", grid(0), grid(1))
    assert memory.get_volatility_mask() is None
    hipotesis_previa = memory.get_transition("INERTE").program

    # La accion INERTE no se vuelve a observar en todo el tramo: es justo el caso que dejaba la
    # hipotesis vieja congelada.
    for i in range(1, 13):
        memory.record_observation("OTRA_A" if i % 2 == 0 else "OTRA_B", grid(i), grid(i + 1))
    assert memory.get_volatility_mask() is not None

    assert memory.get_transition("INERTE").program == []
    assert hipotesis_previa != []


def test_sin_hud_la_mascara_no_se_activa() -> None:
    """Nada cambia respecto del comportamiento previo a este BL cuando no hay celdas no
    estacionarias: `None` significa "compara todo"."""
    memory = TransitionMemory()
    tablero = [[0, 0], [0, 5]]
    movido = [[0, 5], [0, 0]]
    for i in range(20):
        accion = "ACTION1" if i % 2 == 0 else "ACTION2"
        memory.record_observation(accion, tablero, movido if accion == "ACTION1" else tablero)
    assert memory.get_volatility_mask() is None
