"""[arc-agi3-kaggle-agent/tests/transition_memory] -- modelo de mundo tipo STRIPS aprendido: por
cada accion mantiene observaciones (pre, post), sintetiza el programa DSL que las explica y trackea
confianza Beta (exitos/fracasos, NO booleano). El campo `program` de una KnownTransition ES el
programa verificado -- no un sistema paralelo. Puerto de arc-agi-runner/src/worldModel/__tests__/
transitionMemory.test.ts + casos borde propios de Python (ventana FIFO, presupuesto inyectado,
aliasing de la grilla predicha)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arc_agent.world_model.grid import Grid
from arc_agent.world_model.primitive_ops import PrimitiveContext
from arc_agent.world_model.synthesis import SynthesisBudget
from arc_agent.world_model.transition_memory import (
    MAX_OBSERVATIONS_PER_ACTION,
    KnownTransition,
    TransitionMemory,
)


def test_sin_observaciones_no_hay_transicion_y_la_confianza_es_neutra() -> None:
    mem = TransitionMemory()
    assert mem.get_transition("ACTION1") is None
    assert mem.get_confidence("ACTION1") == 0.5
    assert mem.predict("ACTION1", [[1]]) is None
    assert mem.get_observation_count("ACTION1") == 0
    assert mem.is_known_no_op("ACTION1") is False


def test_confirma_un_programa_tras_observaciones_consistentes_y_predice_con_el() -> None:
    mem = TransitionMemory()
    mem.record_observation("ACTION1", [[1, 2]], [[9, 2]])
    mem.record_observation("ACTION1", [[2, 1]], [[2, 9]])
    mem.record_observation("ACTION1", [[1, 1]], [[9, 9]])

    transition = mem.get_transition("ACTION1")
    assert transition is not None and transition.program is not None
    assert mem.predict("ACTION1", [[1, 3]]) == [[9, 3]]
    assert mem.get_confidence("ACTION1") > 0.5


def test_detecta_un_no_op_consistente() -> None:
    mem = TransitionMemory()
    mem.record_observation("ACTION5", [[1, 2]], [[1, 2]])
    mem.record_observation("ACTION5", [[3, 3]], [[3, 3]])
    # BL.21501: la SINTESIS ya concluye identidad con estas 2 observaciones -- eso no cambio, y
    # `predict` lo refleja. Lo que ahora exige MIN_OBSERVATIONS_FOR_NO_OP=3 es `is_known_no_op`,
    # que es la puerta que habilita a EXCLUIR la accion de la exploracion.
    assert mem.predict("ACTION5", [[7]]) == [[7]]
    assert mem.is_known_no_op("ACTION5") is False

    mem.record_observation("ACTION5", [[5, 5]], [[5, 5]])
    assert mem.is_known_no_op("ACTION5") is True


def test_bl21501_una_sola_observacion_no_marca_no_op() -> None:
    """Port del fix de BL.21500 (runner TS): con 1 observacion pre==post, `synthesize_program`
    devuelve el programa vacio y antes eso bastaba para descartar la accion PARA SIEMPRE."""
    mem = TransitionMemory()
    mem.record_observation("ACTION6", [[0]], [[0]])
    assert mem.is_known_no_op("ACTION6") is False
    # La sintesis SI concluyo identidad -- lo que no alcanza es la evidencia para excluirla.
    assert mem.predict("ACTION6", [[4]]) == [[4]]


def test_una_contradiccion_incrementa_beta_y_contradiction_count_y_resintetiza() -> None:
    mem = TransitionMemory()
    mem.record_observation("ACTION2", [[1, 2]], [[9, 2]])
    mem.record_observation("ACTION2", [[1, 1]], [[9, 9]])
    before = mem.get_transition("ACTION2")
    assert before is not None and before.program is not None

    # Contradice el mapping 1->9 confirmado.
    mem.record_observation("ACTION2", [[1, 1]], [[8, 8]])

    after = mem.get_transition("ACTION2")
    assert after is not None
    assert after.beta > before.beta
    assert after.contradiction_count > before.contradiction_count
    # BL.21561 -- la hipotesis SOBREVIVE con cobertura 2/3 en vez de morir. Antes, una sola
    # observacion discordante dejaba `program` en None; en ARC-AGI-3 esa observacion es el choque
    # contra la pared y llega siempre, asi que ninguna regla de movimiento podia confirmarse. La
    # contradiccion no se pierde: se contabiliza en beta y en `coverage`.
    assert after.program == [{"name": "recolor", "params": {"mapping": {1: 9}}}]
    assert abs(after.coverage - 2 / 3) < 1e-9
    assert mem.get_confidence("ACTION2") < before.alpha / (before.alpha + before.beta)


def test_bl21561_cobertura_por_debajo_del_minimo_no_deja_hipotesis() -> None:
    """1/2 = 0.5 < MIN_PROGRAM_COVERAGE: aceptar eso seria llamar regla a una moneda."""
    mem = TransitionMemory()
    mem.record_observation("ACTION4", [[1, 1]], [[9, 9]])
    mem.record_observation("ACTION4", [[1, 1]], [[8, 8]])
    t = mem.get_transition("ACTION4")
    assert t is not None and t.program is None and t.coverage == 0.0


def test_observation_count_crece_mas_alla_de_la_ventana_capada() -> None:
    mem = TransitionMemory()
    grid: Grid = [[4, 4]]
    for _ in range(25):
        mem.record_observation("ACTION3", grid, grid)  # no-op consistente
    transition = mem.get_transition("ACTION3")
    assert transition is not None and transition.observation_count == 25
    assert mem.get_observation_count("ACTION3") == 25
    assert mem.is_known_no_op("ACTION3") is True


def test_get_known_transitions_devuelve_todas_las_acciones_registradas() -> None:
    mem = TransitionMemory()
    mem.record_observation("ACTION1", [[1]], [[1]])
    mem.record_observation("ACTION2", [[1]], [[2]])
    all_transitions = mem.get_known_transitions()
    # Orden de PRIMERA insercion (dict de Python == Map de JS), no alfabetico ni de actualizacion.
    assert [t.action for t in all_transitions] == ["ACTION1", "ACTION2"]


# --- casos borde propios ------------------------------------------------------------------------


def test_la_confianza_sube_con_cada_confirmacion_sin_re_sintetizar() -> None:
    """alpha/beta son una Beta, no un booleano: dos acciones "conocidas" tienen que poder ordenarse
    entre si por cuanta evidencia las respalda."""
    mem = TransitionMemory()
    mem.record_observation("ACTION1", [[1, 2]], [[9, 2]])
    primera = mem.get_confidence("ACTION1")
    mem.record_observation("ACTION1", [[1, 3]], [[9, 3]])
    assert mem.get_confidence("ACTION1") > primera


def test_la_ventana_de_observaciones_es_fifo() -> None:
    """La mas nueva reemplaza a la mas vieja: una contradiccion antigua tiene que poder salir de la
    ventana y dejar de bloquear la sintesis para siempre."""
    mem = TransitionMemory(max_observations=2)
    mem.record_observation("ACTION1", [[1, 1]], [[8, 8]])  # sale de la ventana
    mem.record_observation("ACTION1", [[1, 2]], [[9, 2]])
    mem.record_observation("ACTION1", [[1, 3]], [[9, 3]])
    transition = mem.get_transition("ACTION1")
    assert transition is not None
    assert transition.observation_count == 3
    # Las 2 retenidas son consistentes con 1->9, aunque la evicta las contradecia.
    assert mem.predict("ACTION1", [[1, 4]]) == [[9, 4]]


def test_el_presupuesto_de_sintesis_es_inyectable() -> None:
    """El motor no puede tener el presupuesto enterrado: el harness offline de Kaggle (9h, sin red)
    tiene que poder aflojarlo y una corrida en vivo apretarlo."""
    hambriento = SynthesisBudget(max_node_expansions=0, max_seed_sweep_cells=0)
    mem = TransitionMemory(budget=hambriento)
    mem.record_observation("ACTION1", [[1, 2]], [[9, 2]])
    transition = mem.get_transition("ACTION1")
    assert transition is not None and transition.program is None
    # Sin hipotesis confirmada no hay ni prediccion ni confianza acumulada.
    assert mem.predict("ACTION1", [[1, 2]]) is None
    assert mem.get_confidence("ACTION1") == 0.5


def test_el_contexto_se_usa_al_sintetizar_y_al_predecir() -> None:
    """El ancla de overlay es del EPISODIO: la memoria tiene que llevarla a la sintesis y a la
    prediccion, o el programa aprendido no seria reproducible."""
    ancla: Grid = [[7, 7], [7, 7]]
    mem = TransitionMemory(ctx=PrimitiveContext(anchor_grid=ancla))
    mem.record_observation("ACTION1", [[0, 0], [0, 0]], [[7, 7], [7, 7]])
    transition = mem.get_transition("ACTION1")
    assert transition is not None and transition.program is not None
    assert mem.predict("ACTION1", [[0, 0], [0, 0]]) == [[7, 7], [7, 7]]


def test_predict_no_devuelve_la_grilla_de_entrada() -> None:
    """Caso borde propio de Python: apply_program clona, asi que el llamador puede mutar la
    prediccion sin corromper el estado desde el que planifico."""
    mem = TransitionMemory()
    mem.record_observation("ACTION5", [[1, 2]], [[1, 2]])  # no-op: el programa es la identidad
    entrada: Grid = [[3, 4]]
    predicha = mem.predict("ACTION5", entrada)
    assert predicha == entrada
    assert predicha is not entrada
    predicha[0][0] = 9
    assert entrada == [[3, 4]]


def test_known_transition_serializa_en_camel_case() -> None:
    """KnownTransition esta espejada a proposito del futuro prometheusActivityMemory.
    knownTransitions[]: las claves que viajan al JSON son las del TS, no las de Python."""
    mem = TransitionMemory()
    mem.record_observation("ACTION1", [[1, 2]], [[9, 2]])
    transition = mem.get_transition("ACTION1")
    assert transition is not None
    assert transition.to_dict() == {
        "action": "ACTION1",
        "program": [{"name": "recolor", "params": {"mapping": {1: 9}}}],
        "alpha": 2,
        "beta": 1,
        "observationCount": 1,
        "contradictionCount": 0,
        "coverage": 1.0,
    }


def test_el_default_de_la_ventana_es_el_del_motor_original() -> None:
    assert MAX_OBSERVATIONS_PER_ACTION == 20


def test_bl22237_cobertura_se_recalcula_contra_la_ventana_no_se_acumula_a_ciegas() -> None:
    """BL.22237 -- antes, una vez que `beta` subia por una contradiccion, quedaba CONGELADO ahi
    para siempre: `still_holds` solo miraba la ULTIMA observacion, asi que aunque la observacion
    que caus la contradiccion saliera de la ventana FIFO, `coverage` nunca volvia a 1.0 (subia
    asintoticamente: 0.75, 0.8, 0.833... sin tocar nunca el techo). Reproducido a mano contra la
    logica vieja (verify_program contra solo la ultima): tras 3 confirmaciones despues de la
    contradiccion evictada, la vieja daba (alpha=6, beta=2, coverage=0.833...); esta prueba fija
    el comportamiento NUEVO, que se revalida contra la ventana COMPLETA cada vez."""
    mem = TransitionMemory(max_observations=3)
    mem.record_observation("ACTION1", [[1]], [[9]])
    mem.record_observation("ACTION1", [[1]], [[9]])
    mem.record_observation("ACTION1", [[1]], [[9]])
    confirmada = mem.get_transition("ACTION1")
    assert confirmada is not None and confirmada.coverage == 1.0

    # Contradice el mapping 1->9 -- la hipotesis SOBREVIVE con cobertura parcial (BL.21561).
    mem.record_observation("ACTION1", [[1]], [[2]])
    tras_contradiccion = mem.get_transition("ACTION1")
    assert tras_contradiccion is not None
    assert abs(tras_contradiccion.coverage - 2 / 3) < 1e-9

    # 3 confirmaciones mas: la ventana (cap=3) termina expulsando la observacion contradictoria.
    mem.record_observation("ACTION1", [[1]], [[9]])
    mem.record_observation("ACTION1", [[1]], [[9]])
    mem.record_observation("ACTION1", [[1]], [[9]])
    t = mem.get_transition("ACTION1")
    assert t is not None
    # La ventana retenida es [9,9,9] otra vez -- coverage tiene que volver a 1.0 EXACTO, no
    # acercarse asintoticamente.
    assert t.coverage == 1.0
    assert (t.alpha, t.beta) == (4, 1)


def test_known_transition_es_inmutable() -> None:
    """Frozen a proposito: la transicion vigente se reemplaza entera en cada observacion, nunca se
    parchea in situ -- si se pudiera mutar, alpha/beta describirian otra hipotesis."""
    transition = KnownTransition(
        action="A", program=None, alpha=1, beta=1, observation_count=0, contradiction_count=0
    )
    with pytest.raises(FrozenInstanceError):
        transition.alpha = 5  # type: ignore[misc]
