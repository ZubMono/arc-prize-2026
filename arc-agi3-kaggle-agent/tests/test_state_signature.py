"""[arc-agi3-kaggle-agent/tests/state_signature] -- firma hasheable de un estado (grilla + acciones
disponibles) y deteccion de no-ops entre dos frames sucesivos. Puerto de
arc-agi-runner/src/worldModel/__tests__/stateSignature.test.ts + casos borde propios de Python
(conversion tupla->lista del wire format, paridad numerica bit a bit con el TS, ausencia de
dependencia de PYTHONHASHSEED)."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from arc_agent.types import FrameData, GameState
from arc_agent.world_model.grid import Grid
from arc_agent.world_model.state_signature import (
    compute_frame_signature,
    compute_state_signature,
    extract_grid,
    is_no_op_transition,
)

# Valores producidos por el TS canonico (grid.ts::hashGrid + stateSignature.ts::
# computeStateSignature, ejecutados en Node). Estan pineados como LITERALES a proposito: son la
# unica forma de detectar una divergencia de aritmetica de 32 bits entre los dos motores -- Python
# tiene enteros de precision arbitraria y una mascara olvidada no rompe nada visible del lado
# Python, pero produce otra firma que la del runner.
GRID_2X2: Grid = [[1, 2], [3, 4]]
FIRMA_2X2_SIN_ACCIONES = 2802852909
FIRMA_2X2_ACCIONES_123 = 3109483130
FIRMA_2X2_ACCION_7 = 722774566
FIRMA_15S_OCHO_ACCIONES = 969627862


@dataclass(frozen=True)
class _FrameFalso:
    """Doble estructural del Protocol FrameLike -- no hereda de nada ni se registra en ningun
    lado."""

    frame: Sequence[Sequence[Sequence[int]]]
    available_actions: Sequence[int]


# --- extract_grid -------------------------------------------------------------------------------


def test_extract_grid_devuelve_la_ultima_capa() -> None:
    """La API devuelve UNA O MAS capas consecutivas y la ultima es el estado visible tras aplicar
    el comando."""
    frame = _FrameFalso(frame=(((1, 1), (1, 1)), ((2, 2), (2, 2))), available_actions=(1,))
    assert extract_grid(frame) == [[2, 2], [2, 2]]


def test_extract_grid_none_sin_capas_o_con_la_ultima_vacia() -> None:
    """Ningun consumidor debe asumir grilla presente."""
    assert extract_grid(_FrameFalso(frame=(), available_actions=())) is None
    assert extract_grid(_FrameFalso(frame=(((1,),), ()), available_actions=())) is None


def test_extract_grid_convierte_tuplas_a_listas_mutables() -> None:
    """Frontera unica de conversion: FrameData guarda tuplas (para ser hasheable) y el world model
    muta celdas por indice. Sin la copia, los primitivos no podrian escribir."""
    frame = _FrameFalso(frame=(((1, 2), (3, 4)),), available_actions=())
    grid = extract_grid(frame)
    assert grid is not None
    grid[0][0] = 9
    assert grid == [[9, 2], [3, 4]]
    # Y el frame original queda intacto: la copia protege su inmutabilidad.
    assert frame.frame == (((1, 2), (3, 4)),)


def test_extract_grid_acepta_el_frame_data_real_estructuralmente() -> None:
    """arc_agent.types.FrameData satisface FrameLike SIN import ni herencia -- es la razon por la
    que este modulo no importa `..types` (el builder del notebook no desmonta ese import)."""
    frame = FrameData(
        game_id="g1",
        guid="guid-1",
        frame=(((1, 2), (3, 4)),),
        state=GameState.NOT_FINISHED,
        available_actions=(1, 2, 3),
    )
    assert extract_grid(frame) == GRID_2X2


# --- compute_state_signature (puerto de stateSignature.test.ts) ---------------------------------


def test_compute_state_signature_es_deterministica() -> None:
    assert compute_state_signature(GRID_2X2, [1, 2, 3]) == compute_state_signature(
        GRID_2X2, [1, 2, 3]
    )


def test_compute_state_signature_distingue_grillas_distintas() -> None:
    assert compute_state_signature([[1, 2]], [1]) != compute_state_signature([[2, 1]], [1])


def test_compute_state_signature_distingue_las_acciones_disponibles() -> None:
    grid: Grid = [[1, 2]]
    assert compute_state_signature(grid, [1, 2]) != compute_state_signature(grid, [1, 2, 3])


def test_compute_state_signature_normaliza_el_orden_de_las_acciones() -> None:
    assert compute_state_signature(GRID_2X2, [3, 1, 2]) == compute_state_signature(
        GRID_2X2, [1, 2, 3]
    )


def test_compute_state_signature_coincide_bit_a_bit_con_el_ts() -> None:
    assert compute_state_signature(GRID_2X2, []) == FIRMA_2X2_SIN_ACCIONES
    assert compute_state_signature(GRID_2X2, [1, 2, 3]) == FIRMA_2X2_ACCIONES_123
    assert compute_state_signature(GRID_2X2, [7]) == FIRMA_2X2_ACCION_7
    assert compute_state_signature([[15, 15, 15]], list(range(8))) == FIRMA_15S_OCHO_ACCIONES


def test_compute_state_signature_es_un_entero_sin_signo_de_32_bits() -> None:
    """Caso borde propio de Python: sin la mascara, el corrimiento << 6 crece sin limite (enteros
    de precision arbitraria) y la firma dejaria de ser comparable con la del runner."""
    for acciones in ([], [0], [7], list(range(8))):
        firma = compute_state_signature([[15, 15], [15, 0]], acciones)
        assert 0 <= firma < 2**32


def test_compute_state_signature_acepta_cualquier_secuencia() -> None:
    """El wire format entrega tuplas; el planner y los tests, listas. Ninguna conversion previa
    debe ser necesaria."""
    assert compute_state_signature(GRID_2X2, (3, 1, 2)) == FIRMA_2X2_ACCIONES_123


# --- compute_frame_signature --------------------------------------------------------------------


def test_compute_frame_signature_es_el_decimal_de_la_firma_del_estado() -> None:
    frame = _FrameFalso(frame=(((1, 2), (3, 4)),), available_actions=(1, 2, 3))
    assert compute_frame_signature(frame) == str(FIRMA_2X2_ACCIONES_123)


def test_compute_frame_signature_none_sin_grilla() -> None:
    """Un frame sin grilla devuelve None, no una firma inventada: el campo ausente es "sin
    evidencia", no "no hubo cambio" -- afirmar una firma falsa marcaria transiciones reales como
    no-ops."""
    assert compute_frame_signature(_FrameFalso(frame=(), available_actions=(1,))) is None


def test_compute_frame_signature_tolera_acciones_disponibles_vacias() -> None:
    frame = _FrameFalso(frame=(((1, 2), (3, 4)),), available_actions=())
    assert compute_frame_signature(frame) == str(FIRMA_2X2_SIN_ACCIONES)


# --- is_no_op_transition ------------------------------------------------------------------------


def test_is_no_op_transition_true_cuando_el_frame_no_cambio() -> None:
    assert is_no_op_transition([[1, 2]], [[1, 2]]) is True


def test_is_no_op_transition_false_cuando_el_frame_cambio() -> None:
    assert is_no_op_transition([[1, 2]], [[1, 9]]) is False


def test_is_no_op_transition_none_en_cualquier_lado_nunca_afirma_no_op() -> None:
    assert is_no_op_transition(None, [[1, 2]]) is False
    assert is_no_op_transition([[1, 2]], None) is False
    assert is_no_op_transition(None, None) is False


def test_is_no_op_transition_distingue_formas_con_el_mismo_contenido() -> None:
    """Caso borde propio de Python: `a == b` de listas tambien lo distingue, pero la comparacion
    explicita de grids_equal es la normativa (misma tolerancia que el TS ante filas desparejas)."""
    assert is_no_op_transition([[1, 2]], [[1], [2]]) is False
