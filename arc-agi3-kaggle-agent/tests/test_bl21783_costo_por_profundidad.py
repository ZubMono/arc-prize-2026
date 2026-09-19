"""[arc-agi3-kaggle-agent/tests/test_bl21783_costo_por_profundidad] El costo por accion contra la
profundidad, y hasta que accion alcanza la plata.

POR QUE IMPORTA QUE ESTO ESTE FIJADO. El numero que sale de aca -- "con la cuota del entregable
esta partida llega hasta la accion N" -- contradice la lectura comoda de que el tope de 4.000 es un
presupuesto alcanzable. Si el calculo se hace a mano en un informe, el proximo que lo repita puede
darle otro. Los casos limite que se clavan son los dos que se prestan a confusion: cuando la serie
REAL ya cruza la cuota (no hay que extrapolar nada) y cuando no (hay que extrapolar, y decirlo).
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from costo_por_profundidad import (  # noqa: E402
    acciones_que_entran_en_la_cuota,
    atribucion,
    incrementos_de_cpu,
    informe,
    perfil_de_costo,
)
from partida_instrumentada import plantillas_de_click, reparto_de_cpu  # noqa: E402


def fila_con_serie(
    costos: list[float],
    firmas: list[int] | None = None,
    plantillas: list[int] | None = None,
) -> dict:
    """Una fila con la serie de CPU ACUMULADO, que es como la guarda la medicion."""
    acumulado: list[float] = []
    total = 0.0
    for costo in costos:
        total += costo
        acumulado.append(round(total, 6))
    return {
        "juego": "lp85",
        "semilla": "mapa-1",
        "accionesConsumidas": len(costos),
        "parcial": True,
        "cuotaDeRelojSegundos": 1152.0,
        "nivelesPorHito": {"400": 0},
        "serieDeCpuAcumulado": acumulado,
        "serieDeFirmasDeEstado": firmas if firmas is not None else list(range(1, len(costos) + 1)),
        "serieDePlantillasDeClick": plantillas
        if plantillas is not None
        else list(range(1, len(costos) + 1)),
    }


def test_los_incrementos_se_reconstruyen_de_la_serie_acumulada():
    fila = fila_con_serie([0.1, 0.2, 0.4])
    assert incrementos_de_cpu(fila) == [0.1, 0.2, 0.4]


def test_el_perfil_muestra_el_crecimiento_y_su_factor():
    # 250 acciones a 0,1 y 250 a 0,5: factor 5 exacto entre el primer tramo y el ultimo.
    fila = fila_con_serie([0.1] * 250 + [0.5] * 250)
    perfil = perfil_de_costo(fila)
    assert perfil["porTramo"] == {"1-250": 0.1, "251-500": 0.5}
    assert perfil["factorUltimoSobrePrimero"] == 5.0
    assert perfil["crece"] is True


def test_un_costo_plano_no_se_reporta_como_creciente():
    perfil = perfil_de_costo(fila_con_serie([0.15] * 600))
    assert perfil["crece"] is False
    assert perfil["factorUltimoSobrePrimero"] == 1.0


def test_si_la_serie_real_cruza_la_cuota_no_se_extrapola_nada():
    # 1.000 acciones a 2 s: la cuota de 1.152 s se agota en la accion 576 y esta MEDIDA.
    fila = fila_con_serie([2.0] * 1000)
    salida = acciones_que_entran_en_la_cuota(fila, 1152.0)
    assert salida["extrapolado"] is False
    assert salida["acciones"] == 576


def test_si_la_serie_se_queda_corta_se_extrapola_y_se_declara():
    # 500 acciones a 1 s = 500 s de CPU; faltan 652 s a 1 s/accion = 652 acciones mas.
    fila = fila_con_serie([1.0] * 500)
    salida = acciones_que_entran_en_la_cuota(fila, 1152.0)
    assert salida["extrapolado"] is True
    assert salida["acciones"] == 1152
    assert salida["costoDeColaUsado"] == 1.0
    assert "extrapola" in salida["porQue"]


def test_la_extrapolacion_usa_el_ULTIMO_tramo_que_es_el_caro_no_el_promedio():
    # 250 acciones baratas y 250 caras. El promedio (0,55) diria que entran muchas mas acciones
    # que el costo de cola (1,0), que es el unico honesto si el costo viene creciendo.
    fila = fila_con_serie([0.1] * 250 + [1.0] * 250)
    salida = acciones_que_entran_en_la_cuota(fila, 1152.0)
    assert salida["costoDeColaUsado"] == 1.0
    # 25 + 250 = 275 s consumidos; faltan 877 s a 1,0 -> 877 acciones mas sobre las 500.
    assert salida["acciones"] == 1377


def test_sin_serie_no_se_inventa_un_numero():
    salida = acciones_que_entran_en_la_cuota({"juego": "lp85"}, 1152.0)
    assert salida["acciones"] is None


def test_la_atribucion_no_se_calcula_sobre_una_serie_constante():
    fila = fila_con_serie([0.2] * 300, firmas=[7] * 300, plantillas=[3] * 300)
    salida = atribucion(fila)
    assert salida["correlacionCostoContra_memoriaDeNovedad"] is None
    assert salida["correlacionCostoContra_plantillasDeClick"] is None


def test_la_atribucion_distingue_cual_de_las_dos_memorias_acompana_al_costo():
    # El costo escala con las PLANTILLAS (correlacion 1) y no con la memoria de novedad, que aca
    # se queda quieta. Con una sola memoria medida, este caso se leeria como "no se sabe".
    costos = [0.01 * n for n in range(1, 301)]
    fila = fila_con_serie(costos, firmas=[5] * 300, plantillas=list(range(1, 301)))
    salida = atribucion(fila)
    assert salida["correlacionCostoContra_plantillasDeClick"] == 1.0
    assert salida["correlacionCostoContra_memoriaDeNovedad"] is None
    assert salida["plantillasDeClick_alTerminar"] == 300
    assert "NO es causa" in salida["porQue"]


def test_una_corrida_vieja_sin_la_serie_de_plantillas_lo_declara_en_vez_de_fallar():
    fila = fila_con_serie([0.01 * n for n in range(1, 301)], plantillas=[])
    fila.pop("serieDePlantillasDeClick")
    salida = atribucion(fila)
    assert salida["correlacionCostoContra_plantillasDeClick"] is None
    assert "no trae" in salida["plantillasDeClick_porQue"]
    assert salida["correlacionCostoContra_memoriaDeNovedad"] == 1.0


def test_el_reparto_separa_el_paso_del_entorno_del_resto():
    salida = reparto_de_cpu(100.0, 25.0)
    assert salida["cpuSegundosDelEntorno"] == 25.0
    assert salida["cpuSegundosDelAgente"] == 75.0
    assert salida["fraccionDelEntorno"] == 0.25


def test_el_redondeo_del_cronometro_no_puede_dar_un_agente_negativo():
    # El cronometro del entorno se toma DENTRO del total, asi que solo un error de medicion puede
    # hacerlo mayor. Si pasa, el reparto se satura en vez de publicar un absurdo.
    salida = reparto_de_cpu(10.0, 10.4)
    assert salida["cpuSegundosDelAgente"] == 0.0
    assert salida["fraccionDelEntorno"] == 1.0


def test_una_partida_sin_cpu_no_divide_por_cero():
    assert reparto_de_cpu(0.0, 0.0)["fraccionDelEntorno"] is None


class _RankerFalso:
    plantillas_aprendidas = 7


class _PoliticaConRanker:
    _clicks = _RankerFalso()


class _PoliticaSinRanker:
    pass


def test_la_serie_de_plantillas_sale_del_ranker_de_coordenadas():
    assert plantillas_de_click(_PoliticaConRanker()) == 7


def test_una_politica_sin_ranker_no_tira_abajo_la_medicion_de_niveles():
    # La medicion espia estructuras INTERNAS del agente. Si una se renombra, lo que corresponde es
    # perder la atribucion del costo -- no la partida entera, que es el dato que el BL vino a
    # buscar y el unico que cuesta horas de CPU.
    assert plantillas_de_click(_PoliticaSinRanker()) == 0


def test_el_informe_junta_las_tres_respuestas_de_una_corrida():
    salida = informe(fila_con_serie([0.1] * 250 + [0.5] * 250), 1152.0)
    assert salida["juego"] == "lp85"
    assert salida["parcial"] is True
    assert salida["perfilDeCosto"]["crece"] is True
    assert salida["accionesQueEntranEnLaCuota"]["extrapolado"] is True
    assert "correlacionCostoContra_plantillasDeClick" in salida["atribucion"]
