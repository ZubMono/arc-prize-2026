"""[arc-agi3-kaggle-agent/tests/test_bl21763_clasificacion_de_juegos] Contratos de la re-medicion
del mapa de los 25 juegos.

POR QUE EXISTE. El mapa que sale de `scripts/clasificacion_de_juegos.py` es la entrada de todas las
decisiones del track: si su regla de categorizacion cambia en silencio, cambian de casillero juegos
que no se movieron, y nadie tiene forma de notarlo mirando el JSON. Estos tests FIJAN la regla y la
derivacion del corte por reloj, que es la parte del script que NO se ve en la salida (se calcula,
no se observa) y por lo tanto la que mas facil se rompe sin ruido.

Ademas fijan la propiedad que da sentido a la medicion entera: la curva de presupuesto sale de UNA
sola partida (los hitos son prefijos de la misma corrida), asi que un hito nunca puede reportar
menos niveles que un hito anterior."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from clasificacion_de_juegos import _cuota_de_reloj  # noqa: E402
from mapa_de_juegos import (  # noqa: E402
    COTA_DEL_ENTREGABLE,
    HITOS_POR_DEFECTO,
    JUEGOS_PUBLICOS,
    MAPA_VIEJO,
    UMBRAL_DE_NOVEDAD_MUERTA,
    _categoria_vieja,
    _clasificar,
    fusionar,
)
from reloj_derivado import (  # noqa: E402
    accion_de_corte,
    costo_por_accion_por_tramo,
    cruce_de_juegos,
    escenarios_de_corte,
    factor_pared_por_cpu,
    margen_de_cierre_para,
)


class _ModuloFalso:
    """Espejo minimo del modulo del entregable: solo la constante que la cuota necesita."""

    PRESUPUESTO_POR_DEFECTO_SEGUNDOS = 8.0 * 3600.0


def _medicion(**campos) -> dict:
    base = {
        "juego": "xx00",
        "semilla": "prueba",
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


# ── la cuota de reloj sale del entregable, no de un numero copiado ────────────────────────────
def test_la_cuota_de_reloj_es_el_presupuesto_entregado_dividido_el_batch():
    """1.152 s por partida con 25 juegos NO se escribe en el script: se deriva del presupuesto que
    vive en `reloj_presupuesto.py`. Si manana el presupuesto entregado cambia, la medicion tiene
    que moverse con el, no quedarse con el numero de hoy."""
    assert _cuota_de_reloj(_ModuloFalso(), 25) == pytest.approx(1152.0)
    assert _cuota_de_reloj(_ModuloFalso(), 75) == pytest.approx(384.0)


def test_la_cuota_nunca_divide_por_cero():
    assert _cuota_de_reloj(_ModuloFalso(), 0) == pytest.approx(28800.0)


# ── el mapa viejo, tal como se lo va a comparar ───────────────────────────────────────────────
def test_el_mapa_viejo_nombra_los_seis_que_puntuaban_y_los_siete_que_ciclaban():
    assert len(MAPA_VIEJO["limitadoPorPresupuesto"]) == 6
    assert len(MAPA_VIEJO["cicla"]) == 7
    assert set(MAPA_VIEJO["limitadoPorPresupuesto"]).isdisjoint(MAPA_VIEJO["cicla"])


def test_todo_juego_no_nombrado_cae_en_noConvierte_por_complemento():
    """El brief viejo describia 6 + 7 + 11 = 24 juegos sobre 25 y no teselaba el set. La regla por
    COMPLEMENTO es la unica que le da categoria vieja a los 25 sin inventar pertenencias."""
    assert _categoria_vieja("ft09") == "limitadoPorPresupuesto"
    assert _categoria_vieja("sb26") == "cicla"
    assert _categoria_vieja("r11l") == "noConvierte"


def test_un_id_que_no_es_de_los_25_no_recibe_categoria_vieja_inventada():
    """El complemento tiene que ser una LISTA, no un `return` por defecto. Con el fallback silencioso
    un `--juegos g50T` mal tipeado entraba al mapa con categoria vieja `noConvierte` y podia salir
    como un movimiento espurio o como un falso "sin cambio de casillero"."""
    assert _categoria_vieja("g50T") == "desconocida"
    assert _categoria_vieja("un-juego-que-no-existe") == "desconocida"


def test_los_juegos_publicos_teselan_el_mapa_viejo_y_coinciden_con_el_dataset():
    """Los 25 ids tienen que ser exactamente los del dataset.

    BL.21795 -- LA IDENTIDAD AHORA SE VERIFICA SIEMPRE. La version anterior de este test comparaba
    contra `environment_files/` SOLO `if entornos.is_dir()`, y ese directorio es gitignoreado: en CI
    y en todo checkout limpio el test pasaba sin comparar NADA, y lo unico que corria de verdad era
    el CONTEO -- que los seis ids inventados completaban igual (6 + 7 + 12 = 25). Un conteo sin
    identidad no verifica nada. La comparacion de identidad se hace ahora contra el banco de lazo
    cerrado, que SI esta versionado y trae los mismos 25 juegos por otra via (la sonda de BL.21590
    contra la API oficial), asi que corre en cualquier checkout. El dataset real queda como TERCERA
    fuente, opcional: cuando esta montado tambien se compara."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from support.mundos_medidos import MUNDOS_POR_NOMBRE  # noqa: PLC0415

    assert set(JUEGOS_PUBLICOS) == set(MUNDOS_POR_NOMBRE)
    assert len(JUEGOS_PUBLICOS) == 25
    assert len(set(JUEGOS_PUBLICOS)) == 25
    nombrados = set(MAPA_VIEJO["limitadoPorPresupuesto"]) | set(MAPA_VIEJO["cicla"])
    assert nombrados <= set(JUEGOS_PUBLICOS)
    # El defecto declarado del mapa viejo: 6 + 7 = 13 nombrados, complemento 12 (no 11).
    assert len(set(JUEGOS_PUBLICOS) - nombrados) == 12
    entornos = Path(__file__).resolve().parents[1] / "environment_files"
    if entornos.is_dir():  # @guard-condicional-ok: la identidad ya se verifico arriba contra el banco VERSIONADO; el dataset es una tercera fuente opcional, no el unico juez
        del_dataset = {d.name for d in entornos.iterdir() if d.is_dir()}
        assert del_dataset == set(JUEGOS_PUBLICOS)


# ── la regla de categorizacion nueva ──────────────────────────────────────────────────────────
def test_gana_niveles_despues_de_la_accion_400_es_limitado_por_presupuesto():
    categoria, motivo = _clasificar(
        _medicion(nivelesFinales=3, nivelesPorHito={"400": 1, "4000": 3}),
        UMBRAL_DE_NOVEDAD_MUERTA,
    )
    assert categoria == "limitadoPorPresupuesto"
    assert "1 -> 3" in motivo


def test_gana_todo_antes_de_400_no_es_limitado_por_presupuesto():
    """El caso que el mapa viejo NO podia distinguir: un juego que puntua puede estar limitado por
    presupuesto o haber sacado todo lo suyo en las primeras acciones. Con el tope viejo de 400 los
    dos se veian igual."""
    categoria, _ = _clasificar(
        _medicion(nivelesFinales=1, nivelesPorHito={"400": 1, "4000": 1}),
        UMBRAL_DE_NOVEDAD_MUERTA,
    )
    assert categoria == "puntuaTemprano"


def test_una_corrida_que_no_llego_al_hito_400_no_se_clasifica():
    """El agujero que encontro la primera fusion de prueba: con `nivelesPorHito` vacio, un
    `get("400", 0)` daba 0 y un juego que gano su unico nivel en la accion 3 salia clasificado como
    "limitado por presupuesto". Una corrida corta tiene que decir que no alcanza, no inventar."""
    categoria, motivo = _clasificar(
        _medicion(nivelesFinales=1, nivelesPorHito={}, accionesConsumidas=61),
        UMBRAL_DE_NOVEDAD_MUERTA,
    )
    assert categoria == "noMedible"
    assert "400" in motivo


def test_sin_niveles_y_sin_novedad_es_cicla():
    categoria, motivo = _clasificar(
        _medicion(nivelesFinales=0, novedadDelTramoFinalPorAccion=0.01),
        UMBRAL_DE_NOVEDAD_MUERTA,
    )
    assert categoria == "cicla"
    assert "0.0100" in motivo


def test_sin_niveles_pero_con_novedad_viva_es_noConvierte():
    """La distincion que importa: seguir descubriendo estados y no convertirlos en nivel es un
    problema DISTINTO de estar atrapado en un bucle, y la palanca que lo arregla es otra."""
    categoria, _ = _clasificar(
        _medicion(nivelesFinales=0, novedadDelTramoFinalPorAccion=0.40),
        UMBRAL_DE_NOVEDAD_MUERTA,
    )
    assert categoria == "noConvierte"


def test_el_umbral_de_novedad_es_un_parametro_y_no_una_constante_escondida():
    """Quien lea el informe tiene que poder re-cortar sin re-medir: la tasa se reporta y el umbral
    entra por argumento."""
    medicion = _medicion(nivelesFinales=0, novedadDelTramoFinalPorAccion=0.10)
    assert _clasificar(medicion, 0.05)[0] == "noConvierte"
    assert _clasificar(medicion, 0.20)[0] == "cicla"


# ── la fusion de corridas parciales ───────────────────────────────────────────────────────────
def _escribir(tmp_path: Path, nombre: str, mediciones: list[dict]) -> None:
    import json

    (tmp_path / nombre).write_text(json.dumps({"mediciones": mediciones}), encoding="utf-8")


def test_la_fusion_decide_con_la_mejor_semilla_y_no_con_el_promedio(tmp_path):
    """La pregunta del mapa es de que ES CAPAZ el agente en ese juego. Promediar semillas
    convertiria un 'puede' en un 'a veces' y borraria justo el caso que interesa -- ademas, el mapa
    viejo tampoco promediaba."""
    _escribir(
        tmp_path,
        "a.json",
        [
            _medicion(juego="lp85", semilla="s1", nivelesFinales=0, nivelesPorHito={"400": 0}),
            _medicion(
                juego="lp85", semilla="s2", nivelesFinales=4, nivelesPorHito={"400": 1, "4000": 4}
            ),
        ],
    )
    mapa = fusionar(str(tmp_path / "*.json"), UMBRAL_DE_NOVEDAD_MUERTA)["mapa"]
    assert mapa["lp85"]["categoriaNueva"] == "limitadoPorPresupuesto"
    assert mapa["lp85"]["niveles"] == [0, 4]
    assert mapa["lp85"]["semillas"] == 2


def test_la_fusion_declara_cuando_el_juego_no_se_movio_de_casillero(tmp_path):
    _escribir(
        tmp_path,
        "a.json",
        [_medicion(juego="sb26", semilla="s1", nivelesFinales=0, novedadDelTramoFinalPorAccion=0.0)],
    )
    fila = fusionar(str(tmp_path / "*.json"), UMBRAL_DE_NOVEDAD_MUERTA)["mapa"]["sb26"]
    assert fila["categoriaVieja"] == "cicla"
    assert fila["categoriaNueva"] == "cicla"
    assert fila["queNumeroLoMovio"] == "sin cambio de casillero"


def test_la_fusion_suma_los_game_overs_de_todas_las_semillas(tmp_path):
    """BL.21767 depende de este conteo: se cuenta SIEMPRE y sobre TODAS las semillas, no sobre la
    mejor -- un GAME_OVER que solo aparece en una semilla sigue siendo un GAME_OVER observado."""
    _escribir(
        tmp_path,
        "a.json",
        [
            _medicion(juego="ls20", semilla="s1", gameOvers=3),
            _medicion(juego="ls20", semilla="s2", gameOvers=5),
        ],
    )
    assert fusionar(str(tmp_path / "*.json"), UMBRAL_DE_NOVEDAD_MUERTA)["mapa"]["ls20"][
        "gameOvers"
    ] == 8


def test_la_fusion_ignora_las_ranuras_reservadas_de_juegos_que_no_alcanzaron_a_medir(tmp_path):
    """La corrida crea la ranura del juego apenas arranca la partida y recien la llena a las 250
    acciones. Si el proceso muere antes, esa ranura queda con `juego` y nada mas: contarla seria
    meter un juego que nunca se jugo como si hubiera sacado cero."""
    _escribir(
        tmp_path,
        "a.json",
        [
            {"juego": "ft09", "semilla": "s1", "parcial": True},
            _medicion(juego="vc33", semilla="s1", nivelesFinales=2, nivelesPorHito={"400": 2}),
        ],
    )
    salida = fusionar(str(tmp_path / "*.json"), UMBRAL_DE_NOVEDAD_MUERTA)
    assert list(salida["mapa"]) == ["vc33"]
    assert salida["juegosMedidos"] == 1


def test_una_corrida_truncada_que_YA_subio_despues_de_400_si_se_puede_clasificar(tmp_path):
    """La mitad MONOTONA de la regla. Si el juego ya gano niveles despues de la accion 400, correr
    mas acciones solo puede confirmarlo: `limitadoPorPresupuesto` se sostiene aunque la corrida se
    haya cortado en 2750 de 4000. La marca `parcial` viaja igual, para que nadie lea el renglon
    como 'esto es lo que da con 4000'."""
    _escribir(
        tmp_path,
        "a.json",
        [
            _medicion(
                juego="lp85",
                semilla="s1",
                parcial=True,
                corteFue="sinTerminar",
                nivelesFinales=3,
                nivelesPorHito={"400": 1, "2400": 3},
                accionesConsumidas=2750,
            )
        ],
    )
    fila = fusionar(str(tmp_path / "*.json"), UMBRAL_DE_NOVEDAD_MUERTA)["mapa"]["lp85"]
    assert fila["parcial"] is True
    assert fila["corteFue"] == "sinTerminar"
    assert fila["categoriaNueva"] == "limitadoPorPresupuesto"


def test_una_corrida_truncada_SIN_subir_despues_de_400_no_recibe_casillero(tmp_path):
    """EL DEFECTO QUE ESTE TEST FIJA CERRADO, y que la primera version del BL tenia al reves. Una
    corrida cortada en 1750 de 4000 con 0 niveles NO refuta 'limitado por presupuesto': el tramo
    que faltaba correr es EXACTAMENTE donde esa hipotesis podia confirmarse. Con la regla vieja
    esta fila salia `noConvierte` y era el unico movimiento de categoria de todo el mapa."""
    _escribir(
        tmp_path,
        "a.json",
        [
            _medicion(
                juego="g50t",
                semilla="s1",
                parcial=True,
                corteFue="sinTerminar",
                nivelesFinales=0,
                nivelesPorHito={"400": 0, "1600": 0},
                accionesConsumidas=1750,
                novedadDelTramoFinalPorAccion=0.6073,
            )
        ],
    )
    fila = fusionar(str(tmp_path / "*.json"), UMBRAL_DE_NOVEDAD_MUERTA)["mapa"]["g50t"]
    assert fila["categoriaNueva"] == "noMedible"
    assert "1750" in fila["queNumeroLoMovio"]


def test_una_corrida_completa_pero_con_tope_bajo_tampoco_recibe_casillero():
    """`parcial is False` NO alcanza. Una corrida lanzada con `--acciones 2000` termina limpia y
    sigue sin decir nada sobre el tramo 2000-4000, que es el que el BL vino a medir. El criterio es
    haber agotado la COTA del entregable o haber terminado sola."""
    categoria, motivo = _clasificar(
        _medicion(
            nivelesFinales=0,
            accionesConsumidas=2000,
            topeDeAcciones=2000,
            corteFue="tope",
            nivelesPorHito={"400": 0, "1600": 0},
        ),
        UMBRAL_DE_NOVEDAD_MUERTA,
    )
    assert categoria == "noMedible"
    assert str(COTA_DEL_ENTREGABLE) in motivo


def test_una_partida_que_TERMINO_SOLA_si_se_clasifica_aunque_no_llegue_a_la_cota():
    """El otro lado del mismo criterio: si el agente dejo de jugar por su cuenta en la accion 900,
    no hay tramo que falte correr -- el juego no daba mas. Ahi 'no gano niveles' SI es un
    resultado, y exigir 4000 acciones seria exigir acciones que la partida no tenia."""
    categoria, _ = _clasificar(
        _medicion(
            nivelesFinales=0,
            accionesConsumidas=900,
            topeDeAcciones=4000,
            corteFue="solo",
            nivelesPorHito={"400": 0, "800": 0},
            novedadDelTramoFinalPorAccion=0.01,
        ),
        UMBRAL_DE_NOVEDAD_MUERTA,
    )
    assert categoria == "cicla"


def test_la_fusion_explota_si_no_hay_nada_que_fusionar(tmp_path):
    with pytest.raises(SystemExit):
        fusionar(str(tmp_path / "no-hay-nada-*.json"), UMBRAL_DE_NOVEDAD_MUERTA)


# ── invariantes de la curva de presupuesto ────────────────────────────────────────────────────
def test_los_hitos_cubren_los_dos_puntos_del_mapa_viejo_y_el_tope_de_hoy():
    """400 y 1600 son los puntos que midio el barrido viejo (4,0 y 8,5 niveles totales) y 4000 es
    el tope entregado hoy. Sin los tres, el numero nuevo no se puede leer en la escala del viejo."""
    assert 400 in HITOS_POR_DEFECTO
    assert 1600 in HITOS_POR_DEFECTO
    assert 4000 in HITOS_POR_DEFECTO
    assert list(HITOS_POR_DEFECTO) == sorted(HITOS_POR_DEFECTO)


# ── por que la firma compuesta no discrimina NINGUNA decision DE LA PARTIDA ───────────────────
def test_una_firma_compuesta_nunca_satisface_a_los_dos_lectores_del_lazo():
    """CONTRATO QUE EXPLICA EL HALLAZGO DE CABLEADO de BL.21763. Los dos unicos predicados que leen
    la firma acumulada por accion DENTRO DEL LAZO son `get_direction` (exige el prefijo
    `traslacion:`) e `is_inert_action` (exige la igualdad con `sinCambio`). Una etiqueta
    `compuesta:...` no puede cumplir ninguno de los dos. Este test fija la FORMA de la etiqueta, no
    la ausencia de consumidores: si manana alguien cablea un lector de verdad, sigue pasando."""
    from arc_agent.world_model.grid import BoundingBox
    from arc_agent.world_model.object_mechanics import Mecanica, MecanicaDeCluster
    from arc_agent.world_model.mechanics_signature import firma_compuesta

    caja = BoundingBox(min_x=0, min_y=0, max_x=2, max_y=2)
    mezcla = Mecanica(
        tipo="desconocida",
        celdas_cambiadas=30,
        clusters=[
            MecanicaDeCluster(
                tipo=tipo, celdas=3, caja=caja, traslacion=None, cambio_de_color=None
            )
            for tipo in ("aparicion", "desaparicion", "recoloreo")
        ],
        traslacion_principal=None,
        cambio_de_color_principal=None,
    )
    etiqueta = firma_compuesta(mezcla)
    assert etiqueta.startswith("compuesta:")
    assert not etiqueta.startswith("traslacion:")
    assert etiqueta != "sinCambio"


def test_la_auditoria_estatica_encuentra_los_lectores_reales_de_la_firma():
    """El instrumento que produjo el hallazgo tiene que seguir funcionando. Si manana alguien mueve
    `mechanics_memory.py` o renombra los predicados y la auditoria devuelve una lista vacia, el
    informe diria "nadie la lee" por un defecto del buscador y no por un defecto del agente -- que
    es exactamente el error de medicion que este BL vino a evitar."""
    from auditoria_de_cableado import _auditar_consumidores_estaticos

    salida = _auditar_consumidores_estaticos()
    assert salida["archivosRevisados"] > 20
    # BL.21783: el test citaba `lecturasDeLaFirmaEnProduccion` y
    # `lasUnicasLecturasDeProduccionSonTraslacionYSinCambio`, dos claves que la auditoria dejo de
    # emitir cuando se partio el veredicto por CAPA -- o sea que reventaba con KeyError en vez de
    # verificar nada. Se re-apunta a las claves que la auditoria emite HOY, sin aflojar lo que
    # verificaba: que el buscador sigue encontrando lecturas de la firma en el lazo de la partida.
    por_capa = salida["lecturasDeLaFirmaPorCapa"]
    assert por_capa["lazoDeLaPartida"], "el buscador dejo de encontrar los predicados"

    # BL.21800: los dos asserts que habia aca eran `... in (True, False)`. Un bool SIEMPRE esta en
    # (True, False): pasaban con cualquier valor, incluido el veredicto INVERTIDO que la auditoria
    # devolvia (`firmaCompuestaDiscriminaEnElLazoDeLaPartida = True`, con 14 supuestas
    # discriminantes que en realidad eran lecturas del bitmask `RegionDeCambio.firma: int`, ni una
    # de la firma de mecanica). El arreglo de BL.21783 al test rojo lo dejo verificando la FORMA del
    # resultado en vez de su contenido, que es el modo RFM-03. Ahora se fija el VEREDICTO medido.
    assert salida["clasesQueDeclaranFirma"]["HipotesisDeMecanica"] == "str"
    assert salida["clasesQueDeclaranFirma"]["RegionDeCambio"] == "int", (
        "hay dos atributos `.firma` de tipos distintos en el arbol: si esto cambia, revisar el "
        "filtro por tipo de la auditoria antes de creerle el veredicto"
    )
    assert salida["firmaCompuestaDiscriminaEnElLazoDeLaPartida"] is False, (
        "el hallazgo de BL.21763 es que la firma compuesta NO discrimina ninguna decision DE LA "
        "PARTIDA. Si esto da True, o el agente cambio (y hay que re-medir el BL) o la auditoria "
        f"volvio a contar otra firma: {salida['lecturasQueDiscriminanFirmasCompuestasPorCapa']['lazoDeLaPartida']}"
    )
    assert salida["firmaCompuestaDiscriminaEnElAnalisisOffline"] is True, (
        "offline SI discrimina (`es_animacion_en_loop`). Si esto da False, el buscador se rompio: "
        "es el fail-open que BL.21763 ya tuvo que corregir una vez"
    )
    # Y la prueba de que la segunda no se cuela en la primera.
    assert salida["elAnalisisOfflineNoCorreDuranteLaPartida"] is True, (
        f"el lazo importa modulos de scripts/: {salida['modulosDeScriptsImportadosPorElLazo']}"
    )


def test_la_curva_de_una_partida_no_puede_bajar():
    """`levels_completed` es monotono dentro de una partida, asi que un hito posterior nunca puede
    reportar menos niveles que uno anterior. Si esto se rompe, los hitos dejaron de ser prefijos de
    la MISMA corrida -- que es la propiedad que hace barata a toda la medicion."""
    medicion = _medicion(nivelesPorHito={"400": 1, "1600": 2, "4000": 2}, nivelesFinales=2)
    valores = [medicion["nivelesPorHito"][str(h)] for h in (400, 1600, 4000)]
    assert valores == sorted(valores)
