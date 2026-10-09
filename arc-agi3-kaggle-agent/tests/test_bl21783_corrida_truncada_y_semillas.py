"""[arc-agi3-kaggle-agent/tests/test_bl21783_corrida_truncada_y_semillas] Lo que BL.21783 agrega
sobre la regla del mapa, y por que cada cosa esta.

La guarda de truncamiento y la teselacion ya viven en
`tests/test_bl21763_clasificacion_de_juegos.py`; aca NO se repiten. Lo que se fija aca es:

1. LA RE-EVALUACION DE g50t SOBRE SU JSON REAL. El unico movimiento de categoria que reporto
   BL.21763 salia de una corrida truncada en 1.750 de 4.000. Con la regla corregida NO SE
   SOSTIENE, y eso tiene que quedar clavado contra la medicion versionada -- no contra un fixture,
   que se puede acomodar para que diga lo que uno quiere.
2. LOS 25 IDS SON LOS DEL DATASET, con un guard que CORRE SIEMPRE. La lista anterior nombraba seis
   juegos que no existen (`ns03 os34 vc72 wm09 ws70 zt11`) y omitia seis que si (`bp35 cd82 re86
   s5i5 tr87 wa30`): seis juegos reales salian con categoria vieja `desconocida`. El guard de
   entonces comparaba contra `environment_files/` **solo si el directorio existia**, y es
   gitignoreado -- o sea que en CI pasaba sin comparar nada. Un guard que no puede fallar no es un
   guard: es un comentario que corre.
3. LA REANUDACION. El flujo reanudable que este BL habilita escribe DOS filas para el mismo
   `(juego, semilla)` -- el volcado parcial y la corrida completa -- y el desempate hacia ganar a
   la mas corta.
4. CUANTAS SEMILLAS HACEN FALTA, con la aritmetica del falso negativo en vez de a ojo, y QUIEN
   CORTA PRIMERO (reloj o tope) como cuenta ejecutable en vez de una tabla de memoria.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from mapa_de_juegos import (  # noqa: E402
    JUEGOS_PUBLICOS,
    MAPA_VIEJO,
    UMBRAL_DE_NOVEDAD_MUERTA,
    fusionar,
    una_fila_por_semilla,
)
from presupuesto_de_la_medicion import (  # noqa: E402
    CPU_POR_ACCION_LOCAL,
    CPU_POR_ACCION_PROFUNDO,
    corridas_esperadas_del_plan_adaptativo,
    costo_por_accion_en_kaggle,
    juegos_donde_el_reloj_corta_primero,
    plan_de_semillas,
    quien_corta_primero,
    semillas_para_media,
    semillas_para_no_perder_un_juego,
)

#: La medicion REAL de BL.21763 que este BL viene a re-leer: g50t, 1.750 de 4.000 acciones.
MEDICION_DE_BL21763 = RAIZ / "mediciones" / "BL21763_clasificacion_de_juegos.json"

#: Los seis del estrato A: los unicos que el mapa viejo tenia puntuando, o sea los unicos que
#: pueden contestar "cuanto sube el score con 4000 acciones".
ESTRATO_A = ("ft09", "g50t", "lp85", "m0r0", "sc25", "vc33")

#: Presupuesto del entregable (8 h de 9). Entra como constante del test y no importado del agente a
#: proposito: si manana el entregable lo cambia, estos numeros de referencia siguen describiendo el
#: escenario que el informe cita, y el que tiene que leerlo del agente es `_cuota_de_reloj`.
PRESUPUESTO_DEL_ENTREGABLE = 8.0 * 3600.0


def _medicion(**campos) -> dict:
    base = {
        "juego": "g50t",
        "semilla": "prueba",
        "parcial": False,
        "accionesConsumidas": 4000,
        "topeDeAcciones": 4000,
        "nivelesFinales": 0,
        "nivelesPorHito": {"400": 0, "1600": 0, "4000": 0},
        "novedadDelTramoFinalPorAccion": 0.5,
        "gameOvers": 0,
        "corteFue": "tope",
        "accionEnQueElRelojHabriaCortado": None,
        "nivelesAlCorteDelReloj": 0,
        "coordenadasDistintas": 0,
        "firmasDeEstadoDistintas": 0,
        "distribucionDeAcciones": {},
        "costo": {
            "cpuSegundos": 1.0,
            "relojSegundos": 1.0,
            "relojSegundosSinEsperaDeCarga": 1.0,
            "cpuSegundosPorAccion": 0.0,
        },
    }
    base.update(campos)
    return base


def _fusionar_filas(tmp_path: Path, filas: list[dict]) -> dict:
    (tmp_path / "a.json").write_text(json.dumps({"mediciones": filas}), encoding="utf-8")
    return fusionar(str(tmp_path / "*.json"), UMBRAL_DE_NOVEDAD_MUERTA)


# ── 1. la re-evaluacion de g50t sobre la medicion REAL ────────────────────────────────────────
def test_g50t_con_la_regla_corregida_NO_se_mueve_de_casillero():
    """RE-EVALUACION DEL UNICO RESULTADO DE BL.21763, sobre su JSON versionado y no sobre un
    fixture. Con la regla corregida la re-categorizacion de g50t NO SE SOSTIENE: la corrida se
    corto en 1.750 de 4.000 y el casillero al que lo mandaba (`noConvierte`) afirma una ausencia
    que el tramo sin correr podia refutar. g50t vuelve a quedar SIN MEDIR, igual que los otros 24.
    """
    salida = fusionar(str(MEDICION_DE_BL21763), UMBRAL_DE_NOVEDAD_MUERTA)
    fila = salida["mapa"]["g50t"]
    assert fila["categoriaVieja"] == "limitadoPorPresupuesto"
    assert fila["categoriaNueva"] == "noMedible"
    assert fila["parcial"] is True
    assert fila["accionesConsumidas"] == 1750
    # Y el mapa entero queda sin UN SOLO juego re-categorizado.
    movidos = [
        juego
        for juego, f in salida["mapa"].items()
        if f["categoriaNueva"] not in (f["categoriaVieja"], "noMedible")
    ]
    assert movidos == []


def test_la_medicion_real_tiene_una_sola_semilla_y_el_mapa_lo_declara():
    """N=1 no sostiene ninguna afirmacion sobre varianza, y el renglon tiene que decirlo solo."""
    fila = fusionar(str(MEDICION_DE_BL21763), UMBRAL_DE_NOVEDAD_MUERTA)["mapa"]["g50t"]
    assert fila["semillas"] == 1
    assert fila["varianzaEntreSemillasEsMedible"] is False


def test_el_reloj_no_corta_en_las_corridas_locales_y_por_eso_el_campo_viene_en_null():
    """`accionEnQueElRelojHabriaCortado = null` es EL RESULTADO, no un bug: con 25 juegos y el
    costo local, la cuota de 1.152 s de CPU no se agota antes de las 4.000 acciones."""
    fila = fusionar(str(MEDICION_DE_BL21763), UMBRAL_DE_NOVEDAD_MUERTA)["mapa"]["g50t"]
    assert fila["accionEnQueElRelojHabriaCortado"] is None
    assert quien_corta_primero(25, CPU_POR_ACCION_LOCAL, 4000, PRESUPUESTO_DEL_ENTREGABLE) == "tope"


# ── 2. los 25 ids son los del dataset, y el guard corre SIEMPRE ───────────────────────────────
def test_el_set_publico_no_puede_divergir_del_banco_versionado():
    """EL GUARD QUE FALTABA. El que habia comparaba contra `environment_files/` solo si el
    directorio existia -- y es gitignoreado --, asi que en CI pasaba sin comparar nada y dejo
    entrar seis ids inexistentes. El banco de lazo cerrado SI esta versionado y trae los mismos 25
    juegos por otra via (la sonda de BL.21590 contra la API oficial), asi que sirve de segunda
    fuente: si las dos listas dejan de coincidir, esto falla en cualquier checkout."""
    sys.path.insert(0, str(RAIZ / "tests"))
    from support.mundos_medidos import MUNDOS_POR_NOMBRE

    assert set(JUEGOS_PUBLICOS) == set(MUNDOS_POR_NOMBRE)


@pytest.mark.parametrize("juego", ["bp35", "cd82", "re86", "s5i5", "tr87", "wa30"])
def test_los_seis_juegos_que_la_lista_anterior_perdia_estan_en_el_set(juego):
    """Los seis que la lista rota omitia. Cada uno recibia `categoriaVieja = "desconocida"` y
    quedaba fuera del complemento, o sea que el mapa no teselaba de verdad aunque el test de
    teselacion pasara: contaba 12 en el complemento porque tambien habia colado seis ids falsos."""
    assert juego in JUEGOS_PUBLICOS


@pytest.mark.parametrize("juego", ["ns03", "os34", "vc72", "wm09", "ws70", "zt11"])
def test_los_seis_ids_inventados_ya_no_estan_en_el_set(juego):
    assert juego not in JUEGOS_PUBLICOS


def test_la_teselacion_sigue_dando_6_mas_7_mas_12_con_la_lista_corregida():
    nombrados = set(MAPA_VIEJO["limitadoPorPresupuesto"]) | set(MAPA_VIEJO["cicla"])
    assert len(JUEGOS_PUBLICOS) == len(set(JUEGOS_PUBLICOS)) == 25
    assert nombrados < set(JUEGOS_PUBLICOS)
    assert len(set(JUEGOS_PUBLICOS) - nombrados) == 12


# ── 3. la reanudacion: un volcado parcial y su corrida completa son UNA semilla ───────────────
def test_la_corrida_reanudada_le_gana_a_su_propio_volcado_parcial(tmp_path):
    """EL DEFECTO QUE DISPARA EL FLUJO REANUDABLE. El desempate era `(niveles, -acciones)`, asi que
    entre dos corridas de 0 niveles ganaba la MAS CORTA: el volcado parcial de 1.750 acciones le
    ganaba a la corrida completa de 4.000 y dejaba el juego en `noMedible` teniendo la medicion
    completa en la mano. Justo el escenario que este BL viene a habilitar."""
    fila = _fusionar_filas(
        tmp_path,
        [
            _medicion(juego="g50t", semilla="mapa-1", parcial=True, accionesConsumidas=1750,
                      corteFue="sinTerminar", nivelesPorHito={"400": 0, "1600": 0}),
            _medicion(juego="g50t", semilla="mapa-1", parcial=False, accionesConsumidas=4000),
        ],
    )["mapa"]["g50t"]
    assert fila["parcial"] is False
    assert fila["accionesConsumidas"] == 4000
    assert fila["categoriaNueva"] == "noConvierte"
    # Y es UNA sola semilla, no dos: el volcado no es una corrida aparte.
    assert fila["semillas"] == 1
    assert fila["varianzaEntreSemillasEsMedible"] is False


def test_la_curva_no_cuenta_dos_veces_el_juego_reanudado(tmp_path):
    """Sin deduplicar, el volcado parcial y su reanudacion sumaban los dos a la curva de
    presupuesto: un juego valia por dos y el promedio por semilla quedaba inflado."""
    salida = _fusionar_filas(
        tmp_path,
        [
            _medicion(juego="lp85", semilla="s1", parcial=True, accionesConsumidas=800,
                      corteFue="sinTerminar", nivelesFinales=1,
                      nivelesPorHito={"400": 1, "800": 1}),
            _medicion(juego="lp85", semilla="s1", parcial=False, accionesConsumidas=4000,
                      nivelesFinales=3, nivelesPorHito={"400": 1, "4000": 3}),
        ],
    )
    assert salida["curvaDePresupuestoNivelesPorSemilla"]["400"] == 1.0
    assert salida["nivelesTotalesPorSemilla"]["s1"] == 3
    assert salida["mapa"]["lp85"]["categoriaNueva"] == "limitadoPorPresupuesto"


def test_dos_semillas_distintas_del_mismo_juego_siguen_contando_como_dos(tmp_path):
    """La deduplicacion es por `(juego, semilla)` y no por juego: si borrara semillas distintas,
    todo el plan de N semillas dejaria de tener sentido."""
    fila = _fusionar_filas(
        tmp_path,
        [
            _medicion(juego="vc33", semilla="s1", nivelesFinales=0),
            _medicion(juego="vc33", semilla="s2", nivelesFinales=2,
                      nivelesPorHito={"400": 1, "4000": 2}),
        ],
    )["mapa"]["vc33"]
    assert fila["semillas"] == 2
    assert fila["varianzaEntreSemillasEsMedible"] is True
    assert sorted(fila["niveles"]) == [0, 2]
    assert fila["categoriaNueva"] == "limitadoPorPresupuesto"


def test_la_completa_le_gana_a_la_parcial_aunque_haya_llegado_menos_lejos():
    """Una partida que TERMINA antes del tope (gano, o el agente dejo de jugar) es una medicion
    cerrada; un volcado parcial mas largo sigue sin serlo. El orden es primero completa, despues
    distancia -- nunca al reves."""
    parcial = _medicion(juego="sc25", semilla="s1", parcial=True, accionesConsumidas=2750,
                        corteFue="sinTerminar")
    completa = _medicion(juego="sc25", semilla="s1", parcial=False, accionesConsumidas=2000,
                         corteFue="gano")
    assert una_fila_por_semilla([parcial, completa])[0]["accionesConsumidas"] == 2000
    assert una_fila_por_semilla([completa, parcial])[0]["accionesConsumidas"] == 2000


def test_el_plan_cuenta_la_semilla_reanudada_como_completa():
    """Si el planificador contara el volcado y su reanudacion como dos filas, pediria una partida
    de menos justo en el juego que mas la necesita."""
    filas = [
        _medicion(juego="g50t", semilla="mapa-1", parcial=True, accionesConsumidas=1750,
                  corteFue="sinTerminar"),
        _medicion(juego="g50t", semilla="mapa-1", parcial=False, accionesConsumidas=4000),
    ]
    fila = plan_de_semillas(filas, ("g50t",))["porJuego"]["g50t"]
    assert fila["semillasCompletas"] == 1
    assert fila["semillasTruncadas"] == 0
    assert fila["partidasQueFaltan"] == 3


def test_el_plan_ignora_las_ranuras_reservadas_igual_que_la_fusion():
    """Una ranura sin `nivelesPorHito` es un juego que nunca se jugo: contarla como semilla hecha
    dejaria al juego con una semilla menos de las que necesita."""
    plan = plan_de_semillas([{"juego": "vc33", "semilla": "s1", "parcial": True}], ("vc33",))
    assert plan["porJuego"]["vc33"]["semillasCompletas"] == 0
    assert plan["porJuego"]["vc33"]["semillasTruncadas"] == 0
    assert plan["porJuego"]["vc33"]["partidasQueFaltan"] == 4


# ── 4. cuantas semillas, con numeros ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "probabilidad, esperadas",
    [(0.8, 2), (0.5, 4), (0.3, 7), (0.2, 11), (0.1, 22)],
)
def test_las_semillas_salen_de_la_probabilidad_de_perder_un_juego_que_si_puntua(
    probabilidad, esperadas
):
    """El unico error que el mapa puede cometer es el FALSO NEGATIVO, porque decide por la semilla
    mejor: `(1-p)^N <= riesgo`. Con riesgo 0,10, un juego que puntua la mitad de las veces exige 4
    semillas -- y con N=1, como corrio BL.21763, el riesgo de mandarlo al casillero equivocado es
    del 50%."""
    assert semillas_para_no_perder_un_juego(probabilidad, 0.10) == esperadas


def test_con_una_sola_semilla_el_riesgo_declarado_es_del_50_por_ciento():
    """La afirmacion "N=1 no sostiene nada" deja de ser una opinion: 1 semilla solo alcanza el
    riesgo de 0,10 si el juego puntua con probabilidad 0,9 o mas."""
    assert semillas_para_no_perder_un_juego(0.50, 0.50) == 1
    assert semillas_para_no_perder_un_juego(0.90, 0.10) == 1
    assert semillas_para_no_perder_un_juego(0.89, 0.10) == 2


def test_una_probabilidad_de_uno_necesita_una_sola_semilla():
    assert semillas_para_no_perder_un_juego(1.0, 0.10) == 1


def test_el_numero_de_semillas_no_se_va_de_uno_por_la_coma_flotante():
    """`ln(0,01)/ln(0,1)` son 2 semillas EXACTAS y en coma flotante da 2,0000000000000004: con un
    `ceil` a secas el plan pedia 3. Una partida extra de 4.000 acciones por un epsilon no es
    conservadurismo, es un numero que no se puede reproducir."""
    assert semillas_para_no_perder_un_juego(0.90, 0.01) == 2
    assert semillas_para_no_perder_un_juego(0.75, 0.25) == 1
    assert semillas_para_media(1.0, 0.5, z=1.0) == 4


@pytest.mark.parametrize(
    "probabilidad, riesgo",
    [(0.0, 0.1), (-0.1, 0.1), (1.1, 0.1), (0.5, 0.0), (0.5, 1.0)],
)
def test_las_perillas_fuera_de_rango_explotan_en_vez_de_devolver_un_numero(probabilidad, riesgo):
    with pytest.raises(ValueError):
        semillas_para_no_perder_un_juego(probabilidad, riesgo)


def test_el_plan_adaptativo_da_la_misma_garantia_a_la_mitad_del_costo():
    """Cortar al PRIMER exito no debilita la garantia -- el juego que ya puntuo no puede cambiar de
    casillero -- y ahorra casi la mitad de las partidas. Es lo que vuelve viable la medicion."""
    fijo = 6 * semillas_para_no_perder_un_juego(0.5, 0.10)
    adaptativo = corridas_esperadas_del_plan_adaptativo(6, 0.5, 4)
    assert fijo == 24
    assert adaptativo == pytest.approx(11.25)
    assert adaptativo < fijo / 2 + 1


def test_las_semillas_para_la_media_salen_del_desvio_medido_y_no_de_uno_inventado():
    """La otra pregunta: la curva de presupuesto es un PROMEDIO. Su N depende de la dispersion
    OBSERVADA, que hoy no existe (N=1 por juego), asi que la formula se usa despues de la primera
    pasada. Con un desvio de 1 nivel y un semiancho de 1 nivel hacen falta 4 semillas."""
    assert semillas_para_media(1.0, 1.0, z=1.96) == 4
    assert semillas_para_media(2.0, 1.0, z=1.96) == 16
    assert semillas_para_media(0.0, 1.0) == 1
    with pytest.raises(ValueError):
        semillas_para_media(1.0, 0.0)


def test_el_plan_sobre_la_medicion_real_pide_cuatro_semillas_completas_por_juego():
    """El plan concreto sobre el JSON de BL.21763: g50t tiene UNA semilla TRUNCADA, que no cuenta
    como semilla hecha, asi que los seis del estrato A arrancan de cero."""
    crudo = json.loads(MEDICION_DE_BL21763.read_text(encoding="utf-8"))
    plan = plan_de_semillas(crudo["mediciones"], ESTRATO_A)
    assert plan["semillasPorJuegoEnElPlanFijo"] == 4
    assert plan["porJuego"]["g50t"]["semillasTruncadas"] == 1
    assert plan["porJuego"]["g50t"]["semillasCompletas"] == 0
    assert plan["porJuego"]["g50t"]["partidasQueFaltan"] == 4
    assert plan["porJuego"]["lp85"]["partidasQueFaltan"] == 4
    assert plan["accionesQueFaltanEnElPeorCaso"] == 24 * 4000
    assert plan["partidasEsperadasDelPlanAdaptativo"] == pytest.approx(11.25)
    # El peor caso son ~4 h de CPU; el plan adaptativo esperado, menos de 2.
    assert 3.9 < plan["cpuHorasQueFaltanOptimista"] < 4.2


def test_el_plan_cotiza_lo_que_falta_con_el_costo_MEDIDO_del_tramo_profundo():
    """El error de planificacion que cometio este mismo BL: cotizar las 16.000 acciones que faltan
    de lp85 a 0,1535 s -- el costo de las acciones baratas del principio -- cuando el tramo
    profundo ya costaba cinco veces mas. Lo que falta correr empieza donde la corrida se quedo."""
    filas = [
        _medicion(
            juego="lp85",
            semilla="mapa-1",
            parcial=True,
            accionesConsumidas=1250,
            corteFue="sinTerminar",
            costo={
                "cpuSegundos": 750.0,
                "cpuSegundosPorAccion": 0.6,
                "cpuPorAccionPorTramo": {"1-100": 0.1089, "801-1200": 0.7859, "1201-1250": 1.03},
            },
        )
    ]
    fila = plan_de_semillas(filas, ("lp85",))["porJuego"]["lp85"]
    # 0,7859 y no 1,03: el tramo final de 50 acciones es ruido, y no 0,1535, que es el precio de
    # unas acciones que ya se pagaron y no se vuelven a pagar.
    assert fila["cpuPorAccionUsado"] == 0.7859
    assert "801-1200" in fila["deDondeSaleElCosto"]
    assert fila["cpuSegundosQueFaltan"] == pytest.approx(16000 * 0.7859, rel=1e-6)


def test_el_criterio_del_mapa_y_el_de_la_curva_dan_planes_distintos():
    """sc25 puntua tres veces antes de la accion 800 y no vuelve a subir. Para el MAPA esta
    resuelto -- ya demostro de que es capaz -- y no gasta refuerzos. Para la CURVA no midio nada:
    su delta 1.600->4.000 es cero con UNA sola semilla, que es exactamente el caso que hay que
    repetir. Con un solo criterio, la pregunta del BL se quedaba sin semillas justo en el juego que
    ya habia demostrado que puntua."""
    fila = _medicion(
        juego="sc25",
        semilla="mapa-1",
        parcial=False,
        accionesConsumidas=4001,
        nivelesFinales=3,
        nivelesPorHito={"400": 0, "1600": 3, "4000": 3},
    )
    por_niveles = plan_de_semillas([fila], ("sc25",), criterio="niveles")["porJuego"]["sc25"]
    por_delta = plan_de_semillas([fila], ("sc25",), criterio="delta")["porJuego"]["sc25"]
    assert por_niveles["yaPuntua"] is True and por_niveles["partidasQueFaltan"] == 0
    assert por_delta["yaPuntua"] is False and por_delta["partidasQueFaltan"] == 3
    assert "despues de la accion 1600" in por_delta["porQue"]


def test_con_el_criterio_de_la_curva_una_subida_tardia_si_cierra_el_juego():
    # g50t sube en la accion 1939: eso SI contesta la pregunta de la curva, y un exito ganado no se
    # pierde por correr mas semillas.
    fila = _medicion(
        juego="g50t",
        semilla="mapa-1",
        parcial=False,
        accionesConsumidas=4001,
        nivelesFinales=1,
        nivelesPorHito={"400": 0, "1600": 0, "4000": 1},
    )
    plan = plan_de_semillas([fila], ("g50t",), criterio="delta")["porJuego"]["g50t"]
    assert plan["yaPuntua"] is True
    assert plan["partidasQueFaltan"] == 0


def test_un_criterio_desconocido_no_se_interpreta_como_el_default():
    with pytest.raises(ValueError):
        plan_de_semillas([], ("sc25",), criterio="loQueSea")


def test_sin_medicion_del_juego_el_plan_cotiza_con_la_constante_y_lo_declara():
    fila = plan_de_semillas([], ("sc25",))["porJuego"]["sc25"]
    assert fila["cpuPorAccionUsado"] == CPU_POR_ACCION_LOCAL
    assert "sin medicion" in fila["deDondeSaleElCosto"]


def test_un_juego_que_ya_puntuo_no_gasta_mas_semillas():
    """La asimetria del mapa, ahora en el planificador: un exito ya ganado no se puede perder, ni
    siquiera si la corrida que lo produjo quedo truncada."""
    filas = [
        _medicion(juego="lp85", semilla="s1", parcial=True, accionesConsumidas=900,
                  corteFue="sinTerminar", nivelesFinales=2, nivelesPorHito={"400": 1, "800": 2}),
    ]
    plan = plan_de_semillas(filas, ("lp85",))
    assert plan["porJuego"]["lp85"]["yaPuntua"] is True
    assert plan["porJuego"]["lp85"]["partidasQueFaltan"] == 0
    assert plan["accionesQueFaltanEnElPeorCaso"] == 0


# ── quien corta primero: la conclusion cerrada, ahora ejecutable ──────────────────────────────
@pytest.mark.parametrize(
    "cpu_por_accion, cruce",
    [(0.1535, 47), (0.20, 37), (0.288, 26), (0.325, 23), (0.36, 21)],
)
def test_el_cruce_entre_el_reloj_y_el_tope_es_una_cuenta_y_no_una_opinion(cpu_por_accion, cruce):
    """`N > presupuesto / (tope * c)`. Con el costo local medido el cruce esta en 47 juegos, muy
    por encima de los 25 publicos: EN ESTE BOX MANDA EL TOPE."""
    assert juegos_donde_el_reloj_corta_primero(
        cpu_por_accion, 4000, PRESUPUESTO_DEL_ENTREGABLE
    ) == cruce


def test_el_cruce_no_se_corre_un_juego_por_la_coma_flotante():
    """0,20 x 1,8 da 0,36000000000000004, y con eso el cruce exacto de 20 juegos se leia como
    19,9999... y devolvia 20 en vez de 21: el mismo cruce daba dos numeros distintos segun como se
    hubiera calculado el costo. El caso aparece de verdad en la tabla de Kaggle del CLI."""
    assert juegos_donde_el_reloj_corta_primero(
        costo_por_accion_en_kaggle(CPU_POR_ACCION_PROFUNDO), 4000, PRESUPUESTO_DEL_ENTREGABLE
    ) == 21
    assert juegos_donde_el_reloj_corta_primero(0.36, 4000, PRESUPUESTO_DEL_ENTREGABLE) == 21


def test_en_el_cruce_exacto_hay_empate_y_no_gana_el_reloj():
    """0,288 s/accion x 4000 = 1.152 s = la cuota exacta de 25 juegos. El reloj cortaria justo en
    la ultima accion del tope: eso es un empate, no "el reloj corta primero"."""
    assert quien_corta_primero(25, 0.288, 4000, PRESUPUESTO_DEL_ENTREGABLE) == "empate"
    assert quien_corta_primero(26, 0.288, 4000, PRESUPUESTO_DEL_ENTREGABLE) == "reloj"
    assert quien_corta_primero(24, 0.288, 4000, PRESUPUESTO_DEL_ENTREGABLE) == "tope"


def test_en_kaggle_quien_manda_depende_de_la_profundidad_y_las_dos_puntas_estan_medidas():
    """El informe de BL.21763 usaba un unico 0,325 s/accion para Kaggle que no es ninguno de los
    dos costos MEDIDOS. Con los dos extremos reales el resultado se parte: al costo de profundidad
    500 sigue mandando el tope incluso en Kaggle, y recien al de profundidad 1200-1600 manda el
    reloj. El umbral exacto es 0,16 s/accion local."""
    optimista = costo_por_accion_en_kaggle(CPU_POR_ACCION_LOCAL)
    pesimista = costo_por_accion_en_kaggle(CPU_POR_ACCION_PROFUNDO)
    assert quien_corta_primero(25, optimista, 4000, PRESUPUESTO_DEL_ENTREGABLE) == "tope"
    assert quien_corta_primero(25, pesimista, 4000, PRESUPUESTO_DEL_ENTREGABLE) == "reloj"
    assert costo_por_accion_en_kaggle(0.16) == pytest.approx(0.288)


def test_un_costo_por_accion_no_positivo_explota():
    with pytest.raises(ValueError):
        juegos_donde_el_reloj_corta_primero(0.0, 4000, PRESUPUESTO_DEL_ENTREGABLE)
    with pytest.raises(ValueError):
        quien_corta_primero(0, 0.15, 4000, PRESUPUESTO_DEL_ENTREGABLE)
