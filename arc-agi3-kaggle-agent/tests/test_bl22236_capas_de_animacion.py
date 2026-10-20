"""[arc-agi3-kaggle-agent/tests] BL.22236 -- usar TODAS las capas de `frame.frame` (animacion), no
solo la ultima. El wire oficial acumula una capa por `step()` interno mientras la accion anima
antes de asentarse; 13/25 juegos publicos (hilo Kaggle discussion/734369) esconden informacion que
SOLO existe en una capa intermedia. Cubre las tres piezas nuevas: `extraer_grid_multicapa`
(state_signature.py), `MechanicsMemory.observe_evidencia_adicional` (mechanics_memory.py) y
`ExplorationPolicy._feed_capas_intermedias` (policy.py) -- sin tocar la firma de estado ni la
sintesis DSL, que deben seguir viendo solo la ultima capa."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from arc_agent.policy import ExplorationPolicy
from arc_agent.prng import create_seeded_random
from arc_agent.types import FrameData, GameAction, GameState
from arc_agent.world_model import Grid, MechanicsMemory, extraer_grid_multicapa
from arc_agent.world_model.state_signature import extract_grid


@dataclass(frozen=True)
class _FrameFalso:
    frame: Sequence[Sequence[Sequence[int]]]
    available_actions: Sequence[int]


# --- extraer_grid_multicapa ----------------------------------------------------------------------


def test_extraer_grid_multicapa_devuelve_todas_las_capas_en_orden() -> None:
    frame = _FrameFalso(
        frame=(((1, 1), (1, 1)), ((2, 2), (2, 2)), ((3, 3), (3, 3))), available_actions=(1,)
    )
    assert extraer_grid_multicapa(frame) == [
        [[1, 1], [1, 1]],
        [[2, 2], [2, 2]],
        [[3, 3], [3, 3]],
    ]


def test_extraer_grid_multicapa_descarta_capas_vacias() -> None:
    frame = _FrameFalso(frame=(((1,),), (), ((2,),)), available_actions=())
    assert extraer_grid_multicapa(frame) == [[[1]], [[2]]]


def test_extraer_grid_multicapa_vacia_sin_capas() -> None:
    assert extraer_grid_multicapa(_FrameFalso(frame=(), available_actions=())) == []


def test_extraer_grid_multicapa_una_sola_capa_una_sola_entrada() -> None:
    frame = _FrameFalso(frame=(((5, 6), (7, 8)),), available_actions=())
    assert extraer_grid_multicapa(frame) == [[[5, 6], [7, 8]]]


def test_extraer_grid_multicapa_devuelve_listas_mutables_sin_afectar_el_frame_original() -> None:
    frame = _FrameFalso(frame=(((1, 2),), ((3, 4),)), available_actions=())
    capas = extraer_grid_multicapa(frame)
    capas[0][0][0] = 99
    assert frame.frame == (((1, 2),), ((3, 4),))


def test_extraer_grid_multicapa_no_reemplaza_extract_grid_la_ultima_capa_sigue_siendo_la_firma() -> None:
    """La firma de estado se sigue calculando SOLO con la ultima capa -- extract_grid no cambia."""
    frame = _FrameFalso(frame=(((1, 1),), ((9, 9),)), available_actions=())
    assert extract_grid(frame) == [[9, 9]]
    assert extraer_grid_multicapa(frame)[-1] == [[9, 9]]
    assert extraer_grid_multicapa(frame)[0] == [[1, 1]]


# --- MechanicsMemory.observe_evidencia_adicional --------------------------------------------------


def test_observe_evidencia_adicional_registra_la_hipotesis_por_accion() -> None:
    memoria = MechanicsMemory()
    pre: Grid = [[0, 0], [0, 0]]
    post: Grid = [[0, 0], [0, 0]]
    memoria.observe_evidencia_adicional("ACTION1", pre, post)
    memoria.observe_evidencia_adicional("ACTION1", pre, post)
    hipotesis = memoria.get_hypothesis("ACTION1")
    assert hipotesis is not None
    assert hipotesis.observaciones == 2
    assert hipotesis.firma == "sinCambio"


def test_observe_evidencia_adicional_no_toca_los_detectores_por_episodio() -> None:
    """Detectores 4 (arena) y 5 (contador) son POR EPISODIO y describen el tablero ASENTADO: una
    celda que aparece y desaparece durante la animacion no debe contarlos."""
    memoria = MechanicsMemory()
    pre: Grid = [[0, 0], [0, 0]]
    post: Grid = [[7, 7], [7, 7]]  # cambio grande, tipico de un frame intermedio de animacion
    memoria.observe_evidencia_adicional("ACTION1", pre, post)
    assert memoria.get_observation_count() == 0
    assert memoria.get_active_bounding_box() is None
    assert memoria.get_counters() == []


def test_observe_evidencia_adicional_y_observe_comparten_la_misma_hipotesis_por_accion() -> None:
    """Ambos alimentan el MISMO registro por-accion (fuente unica): evidencia intermedia y
    evidencia asentada de la misma accion se combinan en una sola hipotesis."""
    memoria = MechanicsMemory()
    pre: Grid = [[1, 1], [1, 1]]
    post: Grid = [[1, 1], [1, 1]]
    memoria.observe_evidencia_adicional("ACTION2", pre, post)
    memoria.observe("ACTION2", pre, post)
    hipotesis = memoria.get_hypothesis("ACTION2")
    assert hipotesis is not None
    assert hipotesis.observaciones == 2
    # observe() SI actualiza el contador por-episodio; observe_evidencia_adicional() no aporto nada.
    assert memoria.get_observation_count() == 1


# --- ExplorationPolicy._feed_capas_intermedias (integracion vía decide()) ------------------------


def _frame_multicapa(
    capas: tuple[tuple[tuple[int, ...], ...], ...],
    available_actions: tuple[int, ...] = (1, 2, 3),
    state: GameState = GameState.NOT_FINISHED,
) -> FrameData:
    return FrameData(
        game_id="g1",
        guid="guid-1",
        frame=capas,
        state=state,
        available_actions=available_actions,
    )


def _grilla_uniforme(valor: int, lado: int = 4) -> tuple[tuple[int, ...], ...]:
    fila = tuple(valor for _ in range(lado))
    return tuple(fila for _ in range(lado))


def test_decide_alimenta_la_memoria_de_mecanica_con_capas_intermedias() -> None:
    """Un frame con 3 capas de animacion deja evidencia en `mechanics_memory` para la accion
    PREVIA -- no solo la transicion macro (primera capa -> ultima capa)."""
    policy = ExplorationPolicy(create_seeded_random("bl22236-1"))
    primero = _frame_multicapa((_grilla_uniforme(0),))
    decision1 = policy.decide(primero)
    assert decision1.action != GameAction.RESET

    # El siguiente frame trae 3 capas de animacion (misma accion previa produjo las tres).
    segundo = _frame_multicapa((_grilla_uniforme(1), _grilla_uniforme(2), _grilla_uniforme(3)))
    policy.decide(segundo)

    accion_previa = decision1.action.value
    hipotesis = policy._world_model.get_mechanics_memory().get_hypothesis(accion_previa)
    assert hipotesis is not None
    # 1 observacion "asentada" (_feed_world_model, primera capa->ultima capa) + 2 intermedias
    # (capa0->capa1, capa1->capa2) = 3 en total para la accion previa.
    assert hipotesis.observaciones == 3


def test_decide_con_una_sola_capa_no_agrega_evidencia_intermedia() -> None:
    """Sin capas de animacion (respuesta de una sola capa, el caso comun) el comportamiento es
    identico al de antes de BL.22236: cero observaciones adicionales."""
    policy = ExplorationPolicy(create_seeded_random("bl22236-2"))
    primero = _frame_multicapa((_grilla_uniforme(0),))
    decision1 = policy.decide(primero)

    segundo = _frame_multicapa((_grilla_uniforme(1),))
    policy.decide(segundo)

    accion_previa = decision1.action.value
    hipotesis = policy._world_model.get_mechanics_memory().get_hypothesis(accion_previa)
    assert hipotesis is not None
    assert hipotesis.observaciones == 1


def test_decide_no_alimenta_capas_intermedias_en_el_primer_paso_sin_accion_previa() -> None:
    """Fail-open: sin `_prev_action` (primera decision del episodio) no hay a quien atribuirle la
    animacion -- no debe lanzar ni registrar nada."""
    policy = ExplorationPolicy(create_seeded_random("bl22236-3"))
    frame = _frame_multicapa((_grilla_uniforme(0), _grilla_uniforme(1), _grilla_uniforme(2)))
    decision = policy.decide(frame)
    assert decision.action != GameAction.RESET
    # Nada que atribuir todavia: la memoria de mecanica arranca vacia para toda accion.
    for accion in ("ACTION1", "ACTION2", "ACTION3"):
        assert policy._world_model.get_mechanics_memory().get_hypothesis(accion) is None


def test_decide_determinista_con_capas_intermedias_no_consume_rng_extra() -> None:
    """`_feed_capas_intermedias` es analisis puro (sin `self._rng`): dos policies con la misma
    semilla deben seguir decidiendo identico aunque el frame traiga capas de animacion."""
    frames = [
        _frame_multicapa((_grilla_uniforme(0),)),
        _frame_multicapa((_grilla_uniforme(1), _grilla_uniforme(2), _grilla_uniforme(3))),
        _frame_multicapa((_grilla_uniforme(4), _grilla_uniforme(5))),
    ]
    policy_a = ExplorationPolicy(create_seeded_random("bl22236-determinismo"))
    policy_b = ExplorationPolicy(create_seeded_random("bl22236-determinismo"))
    for frame in frames:
        assert policy_a.decide(frame) == policy_b.decide(frame)
