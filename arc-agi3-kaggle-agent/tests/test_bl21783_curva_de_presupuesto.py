"""[arc-agi3-kaggle-agent/tests/test_bl21783_curva_de_presupuesto] La regla que decide si las 4.000
acciones PAGAN, fijada contra casos construidos a mano.

POR QUE EXISTE ESTE ARCHIVO Y NO UN PARRAFO EN EL INFORME. El error que BL.21594 dejo documentado
es vender como mejora un delta que estaba adentro del ruido. La unica defensa estructural es que el
veredicto salga de una regla ejecutable con sus casos limite clavados: delta cero, delta grande con
ruido mas grande, delta con una sola semilla, y corridas que no llegaron al hito.

Los fixtures son sinteticos A PROPOSITO -- son la tabla de verdad de la regla, no una medicion. La
medicion real se fija aparte, contra el JSON versionado, en `test_la_medicion_real_...`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from curva_de_presupuesto import (  # noqa: E402
    MAPA_VIEJO_NIVELES_TOTALES,
    cargar_corridas,
    costo_y_quien_corta,
    curva,
)

#: La medicion del estrato A que produjo este BL. El test que la lee se saltea si todavia no
#: existe, para que el archivo sirva mientras la corrida esta a mitad de camino.
MEDICION_DEL_ESTRATO_A = RAIZ / "mediciones" / "BL21783_estrato_a.json"


def fila(
    juego: str,
    semilla: str,
    hitos: dict[str, int],
    acciones: int = 4000,
    corte: str = "tope",
    parcial: bool = False,
) -> dict:
    """Una fila con la forma minima que la curva consume. `nivelesFinales` sale del hito mas alto:
    inventar un final que no coincida con la curva seria fabricar un dato imposible (los niveles
    son monotonos dentro de la partida)."""
    return {
        "juego": juego,
        "semilla": semilla,
        "accionesConsumidas": acciones,
        "nivelesFinales": max(hitos.values()) if hitos else 0,
        "nivelesPorHito": dict(hitos),
        "corteFue": corte,
        "parcial": parcial,
    }


def hitos(en400: int, en1600: int, en4000: int) -> dict[str, int]:
    return {"400": en400, "1600": en1600, "4000": en4000}


# --------------------------------------------------------------------------------------------
# 1. El caso que NO necesita hablar de varianza: el evento no ocurrio
# --------------------------------------------------------------------------------------------
def test_delta_cero_en_todas_las_corridas_es_noHayEvento_y_no_invoca_la_varianza():
    filas = [
        fila("lp85", f"mapa-{n}", hitos(1, 1, 1)) for n in range(1, 5)
    ] + [fila("sc25", f"mapa-{n}", hitos(0, 0, 0)) for n in range(1, 5)]
    salida = curva(filas)
    assert salida["veredicto"] == "noHayEvento"
    assert salida["deltaTotalMedioEntreSemillas"] == 0.0
    # El motivo tiene que decir POR QUE la varianza no aplica: si no lo dice, el proximo lector
    # vuelve a preguntar "y el ruido?" y la conclusion se ablanda sola.
    assert "no hay evento" in salida["porQue"]


def test_el_delta_pareado_nunca_es_negativo_porque_los_niveles_son_monotonos():
    filas = [fila("lp85", "mapa-1", hitos(3, 5, 5))]
    salida = curva(filas)
    assert all(d >= 0 for d in salida["porJuego"]["lp85"]["deltaPorSemilla"])


# --------------------------------------------------------------------------------------------
# 2. Con una sola semilla no se puede concluir, y se dice
# --------------------------------------------------------------------------------------------
def test_una_sola_semilla_con_delta_positivo_es_noConcluyente_no_mejora():
    salida = curva([fila("lp85", "mapa-1", hitos(0, 1, 4))])
    assert salida["veredicto"] == "noConcluyente"
    assert salida["juegosConVarianzaMedible"] == 0
    assert "no esta medido" in salida["porQue"]


# --------------------------------------------------------------------------------------------
# 3. El error de BL.21594: delta adentro del ruido
# --------------------------------------------------------------------------------------------
def test_delta_chico_contra_ruido_grande_es_dentroDelRuido():
    # El mismo juego oscila entre 0 y 6 niveles a 1600 segun la semilla (ruido enorme) y el tramo
    # nuevo agrega 1 nivel en una sola de las cuatro.
    filas = [
        fila("lp85", "mapa-1", hitos(0, 0, 0)),
        fila("lp85", "mapa-2", hitos(0, 6, 6)),
        fila("lp85", "mapa-3", hitos(0, 0, 1)),
        fila("lp85", "mapa-4", hitos(0, 3, 3)),
    ]
    salida = curva(filas)
    assert salida["veredicto"] == "dentroDelRuido"
    assert salida["deltaTotalMinimoEntreSemillas"] == 0
    assert "BL.21594" in salida["porQue"]


def test_delta_que_solo_ve_una_semilla_no_alcanza_aunque_supere_el_desvio():
    # Ruido de base CERO (todas las semillas dan 2 a 1600) y una sola semilla gana 1 nivel en el
    # tramo nuevo. El delta medio (0,25) supera al desvio (0,0) pero el minimo es 0: la regla pide
    # las dos condiciones justamente para no dejar pasar esto.
    filas = [
        fila("lp85", "mapa-1", hitos(2, 2, 3)),
        fila("lp85", "mapa-2", hitos(2, 2, 2)),
        fila("lp85", "mapa-3", hitos(2, 2, 2)),
        fila("lp85", "mapa-4", hitos(2, 2, 2)),
    ]
    salida = curva(filas)
    assert salida["veredicto"] == "dentroDelRuido"
    assert salida["deltaTotalMedioEntreSemillas"] == 0.25


def test_el_plan_adaptativo_no_se_puede_leer_como_varianza():
    # lp85 corrio con las cuatro semillas; sc25 puntuo en la primera y por eso no gasto refuerzos.
    # Si el total de cada semilla se sumara sobre su propio conjunto, mapa-1 tendria los dos juegos
    # y las otras uno solo: esa diferencia es el PLAN, no el ruido, y arruinaria la comparacion.
    filas = [fila("lp85", f"mapa-{n}", hitos(1, 2, 2)) for n in range(1, 5)]
    filas.append(fila("sc25", "mapa-1", hitos(3, 5, 9)))
    salida = curva(filas)
    assert salida["juegosEnTodasLasSemillas"] == ["lp85"]
    assert salida["juegosFueraDelBalance"] == ["sc25"]
    assert all(t["juegos"] == ["lp85"] for t in salida["totalesPorSemilla"].values())
    # sc25 sigue estando en el detalle por juego: se lo excluye del AGREGADO, no de la medicion.
    assert salida["porJuego"]["sc25"]["deltaPorSemilla"] == [4]


# --------------------------------------------------------------------------------------------
# 4. El caso positivo: pagan, y todas las semillas lo ven
# --------------------------------------------------------------------------------------------
def test_delta_que_todas_las_semillas_ven_y_supera_el_desvio_es_superaElRuido():
    filas = [
        fila("lp85", "mapa-1", hitos(1, 2, 5)),
        fila("lp85", "mapa-2", hitos(1, 2, 6)),
        fila("lp85", "mapa-3", hitos(1, 3, 6)),
        fila("lp85", "mapa-4", hitos(1, 2, 5)),
    ]
    salida = curva(filas)
    assert salida["veredicto"] == "superaElRuido"
    assert salida["deltaTotalMinimoEntreSemillas"] >= 1
    assert salida["deltaTotalMedioEntreSemillas"] > salida[
        "desvioEntreSemillasDelTotalEnElHitoDePartida"
    ]


# --------------------------------------------------------------------------------------------
# 5. Lo que NO cuenta: corridas que no llegaron al hito
# --------------------------------------------------------------------------------------------
def test_una_corrida_truncada_no_aporta_un_delta_de_cero_sino_la_ausencia_del_dato():
    truncada = fila(
        "g50t", "mapa-1", {"400": 0, "1600": 0}, acciones=2750, corte="sinTerminar", parcial=True
    )
    salida = curva([truncada])
    assert salida["veredicto"] == "sinMedicion"
    assert salida["corridasQueLlegaronAlHito"] == 0
    assert salida["corridasDescartadasPorNoLlegar"] == 1
    assert "g50t" not in salida["porJuego"]


def test_una_partida_que_gano_antes_del_hito_si_cuenta_con_su_valor_final():
    # Termino sola en la accion 900 con 7 niveles: su valor en 4000 esta DEFINIDO (no va a subir
    # mas), asi que descartarla perderia una medicion buena.
    gano = fila("vc33", "mapa-1", {"400": 3, "1600": 7}, acciones=900, corte="gano")
    salida = curva([gano])
    assert salida["corridasQueLlegaronAlHito"] == 1
    assert salida["porJuego"]["vc33"]["nivelesPorHito"]["4000"] == [7]
    assert salida["porJuego"]["vc33"]["deltaPorSemilla"] == [0]


# --------------------------------------------------------------------------------------------
# 6. La reanudacion no puede duplicar ni degradar (mismo defecto que cerro el mapa)
# --------------------------------------------------------------------------------------------
def test_el_volcado_parcial_y_su_reanudacion_son_una_sola_semilla(tmp_path):
    # Se ejercita el camino REAL (`cargar_corridas` sobre archivos), que es donde vive el defecto:
    # el volcado parcial queda escrito en su JSON y la reanudacion escribe otro.
    volcado = fila(
        "g50t", "mapa-1", {"400": 0, "1600": 0}, acciones=1750, corte="sinTerminar", parcial=True
    )
    completa = fila("g50t", "mapa-1", hitos(0, 0, 2))
    (tmp_path / "g50t.parcial.json").write_text(
        json.dumps({"mediciones": [volcado]}), encoding="utf-8"
    )
    (tmp_path / "g50t.mapa-1.json").write_text(
        json.dumps({"mediciones": [completa]}), encoding="utf-8"
    )
    salida = curva(cargar_corridas(str(tmp_path / "*.json")))
    assert salida["semillas"] == ["mapa-1"]
    assert salida["porJuego"]["g50t"]["deltaPorSemilla"] == [2]


def test_una_partida_interrumpida_antes_de_su_primer_volcado_no_aparece_como_juego_medido(tmp_path):
    # El barrido con tope de reloj corta con SIGINT y la medicion escribe igual, para que conste
    # que el juego se intento. Esa fila es una RANURA RESERVADA, no una medicion de cero: si se
    # colara, el mapa mostraria un juego con 0 niveles que nunca se llego a jugar.
    (tmp_path / "vc33.mapa-1.json").write_text(
        json.dumps({"mediciones": [{"juego": "vc33", "semilla": "mapa-1", "parcial": True}]}),
        encoding="utf-8",
    )
    assert cargar_corridas(str(tmp_path / "*.json")) == []


def test_la_curva_agregada_no_cuenta_como_cero_un_hito_que_la_corrida_no_alcanzo(tmp_path):
    # Medido en vivo: con una corrida cortada en 1.250 y otra en 1.750, la curva agregada daba 3,0
    # niveles en el hito 1.200 y 0,0 en el 1.600 -- un imposible aritmetico, porque los niveles son
    # monotonos dentro de la partida. El cero salia de contar a la corrida corta como si hubiera
    # llegado al hito y no hubiera ganado nada.
    from mapa_de_juegos import fusionar

    corta = fila("sc25", "mapa-1", {"400": 0, "800": 3, "1200": 3}, acciones=1250,
                 corte="sinTerminar", parcial=True)
    corta["novedadDelTramoFinalPorAccion"] = 0.5
    larga = fila("lp85", "mapa-1", {"400": 0, "800": 0, "1200": 0, "1600": 0}, acciones=1750,
                 corte="sinTerminar", parcial=True)
    larga["novedadDelTramoFinalPorAccion"] = 0.01
    for nombre, f in (("sc25", corta), ("lp85", larga)):
        f.update({"gameOvers": 0, "coordenadasDistintas": 0, "firmasDeEstadoDistintas": 0,
                  "distribucionDeAcciones": {}, "accionEnQueElRelojHabriaCortado": None,
                  "nivelesAlCorteDelReloj": 0, "topeDeAcciones": 4000,
                  "costo": {"cpuSegundos": 1.0, "relojSegundos": 1.0, "cpuSegundosPorAccion": 0.1}})
        (tmp_path / f"{nombre}.json").write_text(json.dumps({"mediciones": [f]}), encoding="utf-8")
    salida = fusionar(str(tmp_path / "*.json"), 0.05)
    # El hito 1.600 lo alcanzo UNA sola corrida, y el soporte lo dice en vez de esconderlo detras
    # de un promedio que mezcla dos conjuntos de juegos distintos.
    assert salida["soporteDeLaCurva"]["1600"]["juegos"] == ["lp85"]
    assert salida["soporteDeLaCurva"]["1200"]["juegos"] == ["lp85", "sc25"]
    assert salida["soporteDeLaCurva"]["1600"]["corridas"] == 1


def _dedup(filas: list[dict]) -> list[dict]:
    """La curva consume filas YA deduplicadas (lo hace `cargar_corridas`). El test replica ese paso
    con la misma funcion del mapa para no fijar una segunda forma de desempatar."""
    from mapa_de_juegos import una_fila_por_semilla

    return una_fila_por_semilla(filas)


# --------------------------------------------------------------------------------------------
# 7. La escala vieja viaja con el resultado
# --------------------------------------------------------------------------------------------
def test_el_veredicto_publica_los_totales_del_mapa_viejo_para_que_la_escala_sea_comparable():
    salida = curva([fila("lp85", "mapa-1", hitos(1, 1, 1))])
    assert salida["mapaViejoNivelesTotales"] == MAPA_VIEJO_NIVELES_TOTALES
    assert MAPA_VIEJO_NIVELES_TOTALES["1600"] == 8.5


# --------------------------------------------------------------------------------------------
# 8. El costo por accion: lo que la aritmetica del presupuesto venia asumiendo constante
# --------------------------------------------------------------------------------------------
def con_costo(f: dict, cpu_por_accion: float, tramos: dict[str, float] | None = None) -> dict:
    f = dict(f)
    f["costo"] = {
        "cpuSegundos": round(cpu_por_accion * f["accionesConsumidas"], 2),
        "cpuSegundosPorAccion": cpu_por_accion,
    }
    if tramos:
        f["costo"]["cpuPorAccionPorTramo"] = tramos
    return f


def test_con_el_costo_barato_asumido_manda_el_tope_y_el_cruce_esta_en_47_juegos():
    # Reproduce la conclusion que BL.21763 dejo cerrada, para que se vea que la regla no cambio:
    # lo que cambia mas abajo es el NUMERO que se le mete, no la cuenta.
    salida = costo_y_quien_corta([con_costo(fila("lp85", "mapa-1", hitos(0, 0, 0)), 0.1535)])
    assert salida["quienCortaPrimero"]["localConElCostoAgregado"]["cruceEnJuegos"] == 47
    assert salida["quienCortaPrimero"]["localConElCostoAgregado"]["conElBatchDe25"] == "tope"


def test_si_el_costo_crece_con_la_profundidad_el_veredicto_del_corte_se_da_vuelta():
    # Mismo tope, mismo presupuesto, mismo batch: lo unico distinto es que el costo por accion
    # medido a fondo es 3x el del tramo barato.
    fondo = con_costo(
        fila("lp85", "mapa-1", hitos(0, 0, 0)),
        0.30,
        {"1-100": 0.1089, "401-500": 0.4967},
    )
    salida = costo_y_quien_corta([fondo])
    assert salida["creceConLaProfundidad"] is True
    assert salida["costoDelTramoInicial"] == 0.1089
    assert salida["costoDelTramoFinal"] == 0.4967
    assert salida["quienCortaPrimero"]["localConElCostoAgregado"]["conElBatchDe25"] == "reloj"
    assert salida["quienCortaPrimero"]["kaggleConElCostoDelTramoFinal"]["cruceEnJuegos"] < 25


def test_una_corrida_truncada_no_aporta_niveles_pero_si_aporta_costo():
    # Es la asimetria que hace util medir aunque la partida se corte: el costo de cada accion que
    # SI se jugo esta perfectamente medido, y es el insumo de toda la aritmetica de presupuesto.
    truncada = con_costo(
        fila("g50t", "mapa-1", {"400": 0}, acciones=1750, corte="sinTerminar", parcial=True), 0.151
    )
    salida = curva([truncada])
    assert salida["veredicto"] == "sinMedicion"
    assert salida["costoYQuienCorta"]["accionesTotales"] == 1750
    assert salida["costoYQuienCorta"]["cpuPorAccionAgregado"] == 0.151


def test_el_detalle_por_juego_trae_las_dos_hipotesis_del_costo_enfrentadas():
    # Es la comparacion que adentro de una sola partida no se puede hacer: ahi la memoria de
    # novedad y las plantillas de click crecen las dos con el tiempo. Entre juegos se separan.
    caro = con_costo(
        fila("lp85", "mapa-1", hitos(0, 0, 0)), 0.7, {"1-100": 0.1089, "1601-1750": 1.1275}
    )
    caro.update(
        {
            "distribucionDeAcciones": {"ACTION6": 1674, "RESET": 76},
            "coordenadasDistintas": 515,
            "firmasDeEstadoDistintas": 76,
        }
    )
    barato = con_costo(
        fila("sc25", "mapa-1", hitos(0, 3, 3)), 0.15, {"1-100": 0.0867, "1601-1750": 0.1754}
    )
    barato.update(
        {
            "distribucionDeAcciones": {"ACTION1": 500, "ACTION6": 170},
            "coordenadasDistintas": 29,
            "firmasDeEstadoDistintas": 1300,
            "serieDePlantillasDeClick": [0, 1, 2, 3],
        }
    )
    salida = curva([caro, barato])
    lp85, sc25 = salida["porJuego"]["lp85"], salida["porJuego"]["sc25"]
    # El juego CARO es el que clickea, no el que ve mas estados: sc25 tiene 17x mas firmas y cuesta
    # 6x menos por accion. La tabla deja el contraste medido en el artefacto, no en la prosa.
    assert lp85["cpuPorAccionDelUltimoTramo"] > sc25["cpuPorAccionDelUltimoTramo"]
    assert lp85["clicks"] > sc25["clicks"]
    assert lp85["firmasDeEstadoDistintas"] < sc25["firmasDeEstadoDistintas"]
    assert sc25["plantillasAlTerminar"] == 3
    assert lp85["plantillasAlTerminar"] is None  # corrida vieja, sin la serie


def test_sin_bloque_de_costo_no_se_inventa_uno():
    assert costo_y_quien_corta([fila("lp85", "mapa-1", hitos(0, 0, 0))]) == {"corridasConCosto": 0}


# --------------------------------------------------------------------------------------------
# 9. La medicion REAL de este BL, clavada contra el JSON versionado
# --------------------------------------------------------------------------------------------
@pytest.mark.skipif(
    not MEDICION_DEL_ESTRATO_A.exists(), reason="la corrida del estrato A todavia no se persistio"
)
def test_la_medicion_real_del_estrato_a_conserva_su_veredicto():
    datos = json.loads(MEDICION_DEL_ESTRATO_A.read_text(encoding="utf-8"))
    veredicto = datos["curvaDePresupuesto"]
    filas = [f for f in datos["mediciones"] if "nivelesPorHito" in f]
    recalculado = curva(_dedup(filas), veredicto["hitoDePartida"], veredicto["hitoDeLlegada"])
    assert recalculado["veredicto"] == veredicto["veredicto"]
    assert (
        recalculado["deltaTotalMedioEntreSemillas"]
        == veredicto["deltaTotalMedioEntreSemillas"]
    )
    # El informe se apoya en que el numero del JSON se puede REPRODUCIR desde las mediciones que el
    # mismo archivo trae. Si algun dia divergen, esto lo agarra antes que un lector.
