# @vendored-from: BL.21800 rescate del huerfano d477d75c9576 (Orphan-Sha del propio commit): este
# archivo ES el trabajo rescatado del worktree del agente muerto wf_e71685dc; la exencion de linaje
# del gate no aplico por el wt-push.lock residual de ese agente.
"""[tests/test_bl21800_reloj_derivado] BL.21800 -- el banco que le faltaba a `scripts/reloj_derivado.py`.

QUE SE MIDIO. `reloj_derivado.py` (162 lineas) es el modulo del que sale EL numero de BL.21763
("en que accion habria cortado el reloj"), y la conclusion que el entregable usa ("manda el tope, no
el reloj") sale de ahi. Cobertura real al revisar el rescate: CERO. La unica mencion del modulo en
toda la suite era el bloque de imports de `test_bl21763_clasificacion_de_juegos.py:33-39`, que trae
sus SEIS funciones y no usa NINGUNA. Demostrado ejecutando la suite con un plugin de pytest que
reemplazaba las seis por bombas (`AssertionError` al ser llamadas) y ademas saboteaba las constantes
espejo: `25 passed`. Ninguna bomba estallo. Es el modo RFM-09 en el setup: el bloque de imports hace
que el archivo PAREZCA cubierto.

Y ADEMAS una sobreafirmacion medida (RFM-07): el docstring de `margen_de_cierre_para` justifica
duplicar dos constantes del entregable diciendo que "el test `test_el_margen_de_cierre_espeja_al_del_entregable`
fija que los dos den lo mismo, asi que no hay dos fuentes de verdad que puedan divergir en silencio".
`grep -rn espeja_al_del_entregable` devolvia UNA sola linea: la cita misma. Ese test no existia.
Aca esta escrito, con ese nombre exacto, y compara las DOS implementaciones sobre una matriz de
presupuestos en vez de comparar solo las constantes -- que es lo que pide RFM-06 cuando una frontera
real obliga a portar una regla.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from reloj_derivado import (  # noqa: E402
    FACTOR_DEDICADO,
    FRACCION_MAXIMA_DEL_MARGEN,
    TOPE_DEL_MARGEN_SEGUNDOS,
    accion_de_corte,
    costo_por_accion_por_tramo,
    cruce_de_juegos,
    escenarios_de_corte,
    factor_pared_por_cpu,
    margen_de_cierre_para,
)


def serie(costo_por_accion: float, acciones: int) -> list[float]:
    """CPU ACUMULADO despues de cada accion, a costo constante."""
    return [costo_por_accion * (i + 1) for i in range(acciones)]


# ─── El test que el docstring prometia y no existia ──────────────────────────────────────────────


def test_el_margen_de_cierre_espeja_al_del_entregable():
    """RFM-06: la copia de la regla se admite solo CON un test de paridad que corra las dos
    implementaciones sobre la misma matriz. Compara la funcion, no las constantes: dos constantes
    iguales con formulas distintas divergirian igual."""
    from arc_agent.reloj_presupuesto import (
        FRACCION_MAXIMA_DEL_MARGEN as FRACCION_ENTREGABLE,
    )
    from arc_agent.reloj_presupuesto import MARGEN_DE_CIERRE_SEGUNDOS as TOPE_ENTREGABLE
    from arc_agent.reloj_presupuesto import margen_de_cierre_para as margen_entregable

    assert TOPE_DEL_MARGEN_SEGUNDOS == TOPE_ENTREGABLE
    assert FRACCION_MAXIMA_DEL_MARGEN == FRACCION_ENTREGABLE
    for presupuesto in (-1.0, 0.0, 1.0, 100.0, 5_999.0, 6_000.0, 6_001.0, 28_800.0, 1e6):
        assert margen_de_cierre_para(presupuesto) == margen_entregable(presupuesto), presupuesto


# ─── accion_de_corte: el predicado real, sus dos frenos y el caso en que NO corta ────────────────


def test_sin_corte_cuando_la_serie_se_agota_antes():
    accion, motivo = accion_de_corte(
        serie(0.01, 50), presupuesto_segundos=28_800.0, total_de_juegos=25
    )
    assert accion is None
    assert "tope" in motivo


def test_corta_por_cuota_de_la_partida_en_maquina_dedicada():
    """Con f=1 y el primer juego de N, la cuota es `presupuesto / N` -- 28.800/25 = 1.152 s."""
    accion, motivo = accion_de_corte(
        serie(1.0, 4_000), presupuesto_segundos=28_800.0, total_de_juegos=25
    )
    assert motivo == "cuotaDeLaPartida"
    assert accion == 1_152


def test_corta_por_deadline_global_cuando_la_pared_se_come_el_presupuesto():
    """Un solo juego (pendientes=1) nunca dispara la cuota: el unico freno posible es el deadline."""
    accion, motivo = accion_de_corte(
        serie(1.0, 4_000), presupuesto_segundos=100.0, total_de_juegos=1
    )
    assert motivo == "deadlineGlobal"
    # margen = min(60, 100*0.01) = 1.0  =>  corta en la primera accion con 100 - pared <= 1
    assert accion == 99


def test_el_factor_de_contencion_adelanta_el_corte():
    """La razon de ser del modulo: con f grande el corte cae MUCHO antes, y por eso 'manda el tope'
    vale en una maquina dedicada y es falso en un box contendido."""
    dedicada, _ = accion_de_corte(
        serie(1.0, 4_000), presupuesto_segundos=28_800.0, total_de_juegos=25, factor=1.0
    )
    contendido, _ = accion_de_corte(
        serie(1.0, 4_000), presupuesto_segundos=28_800.0, total_de_juegos=25, factor=17.6
    )
    assert contendido < dedicada


def test_la_pared_previa_reduce_lo_que_le_queda_a_la_partida():
    sin_previa, _ = accion_de_corte(
        serie(1.0, 4_000), presupuesto_segundos=28_800.0, total_de_juegos=25
    )
    con_previa, _ = accion_de_corte(
        serie(1.0, 4_000),
        presupuesto_segundos=28_800.0,
        total_de_juegos=25,
        pared_previa_segundos=10_000.0,
    )
    assert con_previa < sin_previa


def test_pendientes_baja_con_la_posicion_en_el_batch():
    """`pendientes(k) = N - (k-1)`: la ultima partida del batch se queda con todo el pool restante,
    asi que su cuota es la mas holgada de todas si nadie gasto antes."""
    primera, _ = accion_de_corte(
        serie(1.0, 40_000), presupuesto_segundos=28_800.0, total_de_juegos=25, indice_del_juego=1
    )
    ultima, _ = accion_de_corte(
        serie(1.0, 40_000), presupuesto_segundos=28_800.0, total_de_juegos=25, indice_del_juego=25
    )
    assert primera is not None
    assert ultima is None or ultima > primera


# ─── factor_pared_por_cpu ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pared, cpu, esperado",
    [
        (0.0, 0.0, FACTOR_DEDICADO),  # sin CPU medido: dedicada por defecto
        (10.0, 0.0, FACTOR_DEDICADO),
        (5.0, 10.0, FACTOR_DEDICADO),  # nunca menos de 1: un hilo no gasta mas CPU que pared
        (100.0, 10.0, 10.0),
        (176.0, 10.0, 17.6),
    ],
)
def test_factor_pared_por_cpu(pared, cpu, esperado):
    assert factor_pared_por_cpu(pared, cpu) == pytest.approx(esperado)


# ─── escenarios_de_corte ─────────────────────────────────────────────────────────────────────────


def test_escenarios_reporta_los_dos_factores_y_el_barrido_completo():
    salida = escenarios_de_corte(
        serie(0.7255, 4_000),
        presupuesto_segundos=28_800.0,
        total_de_juegos=25,
        factor_medido=17.6,
    )
    assert set(salida) == {"maquinaDedicada", "boxCompartido"}
    assert salida["maquinaDedicada"]["factorParedPorCpu"] == 1.0
    assert salida["boxCompartido"]["factorParedPorCpu"] == 17.6
    for escenario in salida.values():
        assert len(escenario["posiciones"]) == 25
        assert [p["posicionEnElBatch"] for p in escenario["posiciones"]] == list(range(1, 26))
    # El box contendido corta ANTES que la maquina dedicada: es el hallazgo que motivo el modulo.
    assert (
        salida["boxCompartido"]["primeraPosicionQueCortaPorReloj"]
        <= salida["maquinaDedicada"]["primeraPosicionQueCortaPorReloj"]
    )


def test_escenarios_con_serie_vacia_no_revienta():
    salida = escenarios_de_corte(
        [], presupuesto_segundos=28_800.0, total_de_juegos=3, factor_medido=2.0
    )
    for escenario in salida.values():
        assert escenario["primeraPosicionQueCortaPorReloj"] is None
        assert escenario["corteDeLaPrimeraPartida"] is None


# ─── cruce_de_juegos ─────────────────────────────────────────────────────────────────────────────


def test_cruce_de_juegos_es_la_forma_cerrada_de_la_tabla():
    # presupuesto / (tope * costo) = 28800 / (4000 * 0.7255)
    assert cruce_de_juegos(0.7255, 4_000, 28_800.0) == pytest.approx(28_800.0 / (4_000 * 0.7255))


@pytest.mark.parametrize("costo, tope", [(0.0, 4_000), (-1.0, 4_000), (0.7255, 0), (0.7255, -3)])
def test_cruce_de_juegos_degenerado_es_infinito(costo, tope):
    """Sin costo o sin tope el reloj no puede ganarle nunca: infinito, no una division por cero."""
    assert cruce_de_juegos(costo, tope, 28_800.0) == float("inf")


# ─── costo_por_accion_por_tramo ──────────────────────────────────────────────────────────────────


def test_costo_por_tramo_es_marginal_no_promedio():
    # 100 acciones a 1.0 y despues 100 a 3.0 (acumulado)
    s = [1.0 * i for i in range(1, 101)] + [100.0 + 3.0 * i for i in range(1, 101)]
    salida = costo_por_accion_por_tramo(s, [100, 200])
    assert salida["1-100"] == pytest.approx(1.0)
    assert salida["101-200"] == pytest.approx(3.0), "si diera ~2.0 estaria promediando, no midiendo el tramo"


def test_costo_por_tramo_ignora_cortes_fuera_de_la_serie():
    salida = costo_por_accion_por_tramo(serie(0.5, 10), [5, 10, 99, 0, -3])
    assert list(salida) == ["1-5", "6-10"]
