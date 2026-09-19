"""[arc-agi3-kaggle-agent/tests/test_bl21702_palancas] BL.21702 -- contrato y EFECTO de las cuatro
palancas de exploracion, cada una MEDIDA POR SEPARADO con su bandera. El RESET voluntario tiene
archivo propio: `test_bl21702_reset_congelado.py`.

POR QUE CADA TEST ENCIENDE UNA SOLA PALANCA. BL.21594 midio tres mecanismos juntos y el neto fue
ruido alrededor de cero: no se supo cual pagaba. Aca cada test de efecto construye la politica con
`Banderas((PALANCA,))` -- solo esa encendida -- y compara contra `Banderas(())`. Un test que
enciende dos no puede atribuir su resultado a ninguna.

LOS ENTORNOS DE JUGUETE REPRODUCEN LA PATOLOGIA MEDIDA, no una generica:
El menu que anima (dc22) se simula aca mismo en `_gastar_warmup`; el resto de los entornos de
juguete vive en `tests/support/entornos_bl21702.py`, compartido con el archivo del RESET.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arc_agent.banderas import (
    BANDERAS_CONOCIDAS,
    BANDERAS_POR_DEFECTO,
    MACRO_CAMBIO_INFORMATIVO,
    MASCARA_DE_ACCION_UNICA,
    MEMORIA_TRANSVERSAL_DE_CLICKS,
    WARMUP_DE_CLICKS_SEGUIDOS,
    BanderaDesconocida,
    Banderas,
)
from arc_agent.click_targeting import (
    BONO_POR_PLANTILLA,
    CLICKS_PARA_JUZGAR_LA_SENAL,
    PENALIZACION_POR_ANTI_PLANTILLA,
    PENALIZACION_POR_REPETICION_DE_CELDA,
    TOPE_DE_REPETICIONES_POR_CELDA,
    ClickMemory,
    region_que_cambio,
)
from arc_agent.direction_beliefs import CreenciaDeDirecciones
from arc_agent.exploration_memory import MACRO_MAX_STEPS, MacroCommitment
from arc_agent.opening_book import CLICS_DE_WARMUP, LibroDeAperturas
from arc_agent.types import GameAction
from arc_agent.world_model import VolatilityTracker, compute_state_signature
from tests.support.entornos_bl21702 import AccionCosmetica, ClickConFirmaSiempreNueva, correr

SIN_PALANCAS = Banderas(())
SOLO_CLICKS = Banderas((MEMORIA_TRANSVERSAL_DE_CLICKS,))
SOLO_MASCARA = Banderas((MASCARA_DE_ACCION_UNICA,))
SOLO_MACRO = Banderas((MACRO_CAMBIO_INFORMATIVO,))
SOLO_WARMUP = Banderas((WARMUP_DE_CLICKS_SEGUIDOS,))


# ============================================================================================
# banderas.py -- el registro, que es lo que hace medible todo lo demas
# ============================================================================================


def test_por_defecto_rigen_las_palancas_ENTREGADAS_no_todas_las_conocidas() -> None:
    """En Kaggle no hay variable de entorno, asi que rige `BANDERAS_POR_DEFECTO`: las que el gate
    de merge APROBO contra el harness real, que no son necesariamente todas las que existen. QUE SE
    ENTREGA LO DECIDE LA MEDICION, no la intencion de quien escribio la palanca."""
    assert Banderas().activas == BANDERAS_POR_DEFECTO
    assert Banderas.desde_texto(None).activas == BANDERAS_POR_DEFECTO
    assert Banderas.desde_texto("   ").activas == BANDERAS_POR_DEFECTO
    assert Banderas.desde_texto("entregadas").activas == BANDERAS_POR_DEFECTO
    assert Banderas.todas().activas == BANDERAS_CONOCIDAS
    assert set(BANDERAS_POR_DEFECTO) <= set(BANDERAS_CONOCIDAS)


def test_ninguna_apaga_todo_y_es_la_linea_base_del_gate() -> None:
    banderas = Banderas.desde_texto("ninguna")
    assert banderas.activas == ()
    assert banderas.resumen() == "ninguna"
    for nombre in BANDERAS_CONOCIDAS:
        assert banderas.activa(nombre) is False


def test_se_puede_apagar_una_sola_palanca_para_atribuirle_el_delta() -> None:
    """La forma del leave-one-out del barrido de ablacion. `todas,` explicito: la base de la
    gramatica son las ENTREGADAS, y sin el prefijo esto mediria otra cosa."""
    banderas = Banderas.desde_texto(f"todas,-{MACRO_CAMBIO_INFORMATIVO}")
    assert banderas.activa(MACRO_CAMBIO_INFORMATIVO) is False
    assert all(banderas.activa(n) for n in BANDERAS_CONOCIDAS if n != MACRO_CAMBIO_INFORMATIVO)


def test_se_puede_encender_una_sola_palanca() -> None:
    banderas = Banderas.desde_texto(f"ninguna,+{MASCARA_DE_ACCION_UNICA}")
    assert banderas.activas == (MASCARA_DE_ACCION_UNICA,)


def test_una_bandera_mal_escrita_explota_en_vez_de_medir_una_linea_base_falsa() -> None:
    """Un silencio aca produciria una medicion que dice otra cosa de la que el operador cree."""
    with pytest.raises(BanderaDesconocida):
        Banderas.desde_texto("macroCambioSignificativo")
    with pytest.raises(BanderaDesconocida):
        Banderas.desde_texto("-noExiste")
    with pytest.raises(BanderaDesconocida):
        Banderas(("noExiste",))


def test_resumen_declara_la_configuracion_de_la_corrida() -> None:
    assert Banderas((MEMORIA_TRANSVERSAL_DE_CLICKS, MACRO_CAMBIO_INFORMATIVO)).resumen() == (
        f"{MEMORIA_TRANSVERSAL_DE_CLICKS},{MACRO_CAMBIO_INFORMATIVO}"
    )
    assert Banderas.todas().sin(MEMORIA_TRANSVERSAL_DE_CLICKS).activa(
        MEMORIA_TRANSVERSAL_DE_CLICKS
    ) is False
    assert Banderas.todas().con(MACRO_CAMBIO_INFORMATIVO).activas == (MACRO_CAMBIO_INFORMATIVO,)


# ============================================================================================
# PALANCA 1 -- memoria de coordenadas TRANSVERSAL al estado
# ============================================================================================

FONDO = 0
MARCO = 3
FICHA = 9


def _grilla_con_fichas() -> list[list[int]]:
    """Marco con dos fichas identicas adentro -- da un ranking de celdas con maximo claro."""
    grid = [[FONDO] * 12 for _ in range(12)]
    for y in range(3, 9):
        for x in range(1, 11):
            grid[y][x] = MARCO
    for x0 in (2, 7):
        for y in range(5, 7):
            for x in range(x0, x0 + 2):
                grid[y][x] = FICHA
    return grid


def _recorrer_firmas(
    banderas: Banderas, hubo_cambio: bool, firmas: int = 3 * CLICKS_PARA_JUZGAR_LA_SENAL
) -> list[tuple[int, int]]:
    """Una firma NUEVA por paso -- el escenario medido: la memoria por `(firma,x,y)` no bloquea
    nada porque la firma nunca se repite."""
    grid = _grilla_con_fichas()
    memoria = ClickMemory(banderas=banderas)
    elegidas: list[tuple[int, int]] = []
    for firma in range(firmas):
        x, y = memoria.elegir_objetivo(grid, firma, lambda: 0.0)
        memoria.registrar_resultado(firma, x, y, hubo_cambio, grid)
        elegidas.append((x, y))
    return elegidas


def test_sin_la_palanca_una_firma_nueva_devuelve_la_misma_celda() -> None:
    """EL DEFECTO MEDIDO, reproducido: `_probadas` se indexa por (firma,x,y), asi que cambiar de
    firma vacia la cobertura y el ranker vuelve a la celda de mayor puntaje. Se realimenta
    `hubo_cambio=True` porque es lo que el frame animado de estos juegos produce SIEMPRE."""
    elegidas = _recorrer_firmas(SIN_PALANCAS, hubo_cambio=True)
    assert len(set(elegidas)) == 1, "sin la palanca, todas las firmas distintas dan la misma celda"


def test_con_la_palanca_la_cobertura_avanza_aunque_la_firma_cambie() -> None:
    """La palanca necesita `CLICKS_PARA_JUZGAR_LA_SENAL` clicks para declarar degenerada la senal de
    cambio -- antes de eso no castiga nada, que es lo correcto: con dos o tres clicks "todos
    cambiaron" es coincidencia."""
    elegidas = _recorrer_firmas(SOLO_CLICKS, hubo_cambio=True)
    assert len(set(elegidas)) > 1


def test_la_penalizacion_satura_en_la_magnitud_de_una_anti_plantilla() -> None:
    """Que sature es deliberado: sin tope, la memoria transversal seria el lockout absorbente que
    BL.21518 tuvo que desarmar del lado de los no-ops. El techo coincide con el bono de plantilla:
    una celda que YA FUNCIONO nunca cae por debajo de su puntaje base."""
    memoria = ClickMemory(banderas=SOLO_CLICKS)
    grid = _grilla_con_fichas()
    for i in range(TOPE_DE_REPETICIONES_POR_CELDA + 4):
        memoria.registrar_resultado(i, 4, 4, False, grid)
    assert memoria.clicks_esteriles_en(4, 4) == TOPE_DE_REPETICIONES_POR_CELDA + 4
    assert memoria.penalizacion_transversal(4, 4) == pytest.approx(
        PENALIZACION_POR_REPETICION_DE_CELDA * TOPE_DE_REPETICIONES_POR_CELDA
    )
    assert memoria.penalizacion_transversal(4, 4) == pytest.approx(
        PENALIZACION_POR_ANTI_PLANTILLA
    )
    assert memoria.penalizacion_transversal(4, 4) == pytest.approx(BONO_POR_PLANTILLA)


def test_con_senal_util_se_castiga_el_fallo_y_se_vuelve_gratis_a_lo_que_funciona() -> None:
    """REGIMEN 1 -- el cambio DISCRIMINA. Ahi el contador que manda es el de clicks esteriles, y
    un click con efecto borra el historial de esa celda: evidencia de efecto real desmiente el
    historial de fallos, igual que una plantilla positiva desmiente su anti-plantilla."""
    memoria = ClickMemory(banderas=SOLO_CLICKS)
    grid = _grilla_con_fichas()
    for i in range(CLICKS_PARA_JUZGAR_LA_SENAL):
        memoria.registrar_resultado(i, 4, 4, False, grid)
    assert memoria.senal_de_cambio_degenerada is False
    assert memoria.penalizacion_transversal(4, 4) > 0
    memoria.registrar_resultado(99, 4, 4, True, grid)
    assert memoria.clicks_esteriles_en(4, 4) == 0
    assert memoria.penalizacion_transversal(4, 4) == 0.0
    assert memoria.clicks_en(4, 4) == CLICKS_PARA_JUZGAR_LA_SENAL + 1


def test_con_senal_degenerada_manda_la_repeticion_y_el_primer_click_es_gratis() -> None:
    """REGIMEN 2 -- el cambio NO discrimina: con la mascara en 0 celdas y el frame animando,
    `hubo_cambio` es SIEMPRE verdadero y una memoria de fallos no acumularia nada. Medido: sin este
    regimen la cobertura no se movia (16 celdas en 80 clicks con y sin palanca)."""
    memoria = ClickMemory(banderas=SOLO_CLICKS)
    grid = _grilla_con_fichas()
    for i in range(CLICKS_PARA_JUZGAR_LA_SENAL):
        memoria.registrar_resultado(i, 4, 4, True, grid)
    assert memoria.senal_de_cambio_degenerada is True
    assert memoria.clicks_esteriles_en(4, 4) == 0
    assert memoria.penalizacion_transversal(4, 4) == pytest.approx(
        PENALIZACION_POR_REPETICION_DE_CELDA * TOPE_DE_REPETICIONES_POR_CELDA
    )
    # El PRIMER click de una celda nunca se cobra: lo que se castiga es volver, no llegar.
    memoria.registrar_resultado(500, 7, 7, True, grid)
    assert memoria.penalizacion_transversal(7, 7) == 0.0


def test_un_solo_click_sin_cambio_alcanza_para_declarar_util_la_senal() -> None:
    """El regimen degenerado exige que NINGUN click haya fallado: alcanza un contraejemplo para
    volver al contador de fallos, que es el mas informativo de los dos."""
    memoria = ClickMemory(banderas=SOLO_CLICKS)
    grid = _grilla_con_fichas()
    for i in range(CLICKS_PARA_JUZGAR_LA_SENAL):
        memoria.registrar_resultado(i, 4, 4, True, grid)
    assert memoria.senal_de_cambio_degenerada is True
    memoria.registrar_resultado(600, 9, 9, False, grid)
    assert memoria.senal_de_cambio_degenerada is False


def test_con_la_palanca_apagada_la_penalizacion_es_cero_exacto() -> None:
    """La identidad en coma flotante es lo que permite medir la linea base con la MISMA build:
    `puntaje - 0.0 == puntaje`."""
    memoria = ClickMemory(banderas=SIN_PALANCAS)
    grid = _grilla_con_fichas()
    for i in range(5):
        memoria.registrar_resultado(i, 4, 4, False, grid)
    assert memoria.penalizacion_transversal(4, 4) == 0.0
    assert memoria.memoria_transversal_activa is False


# --- efecto sobre el corpus REAL de ft09 -----------------------------------------------------

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "arc-agi-runner"
    / "src"
    / "worldModel"
    / "__fixtures__"
    / "clickRealFrames.json"
)


def _clicks_reales() -> list[dict]:
    datos = json.loads(FIXTURE.read_text(encoding="utf-8"))
    salida: list[dict] = []
    for partida in datos["partidas"]:
        grid = [list(fila) for fila in partida["base"]]
        previa: list[list[int]] | None = None
        for paso in partida["pasos"]:
            siguiente = _aplicar_diff(grid, paso["diff"])
            if paso.get("x") is not None:
                salida.append(
                    {
                        "grid": grid,
                        "previa": previa,
                        "x": paso["x"],
                        "y": paso["y"],
                        "productivo": bool(paso["diff"]),
                    }
                )
            previa = grid
            grid = siguiente
    return salida


def _aplicar_diff(grid: list[list[int]], diff: list[int]) -> list[list[int]]:
    nueva = [fila[:] for fila in grid]
    for i in range(0, len(diff), 3):
        nueva[diff[i]][diff[i + 1]] = diff[i + 2]
    return nueva


def _recorrer_corpus(banderas: Banderas) -> dict[str, int]:
    clicks = _clicks_reales()
    oraculo: dict[tuple[int, int], bool] = {}
    for c in clicks:
        clave = (c["x"], c["y"])
        oraculo[clave] = oraculo.get(clave, False) or c["productivo"]

    memoria = ClickMemory(banderas=banderas)
    conteo = {"productivos": 0, "muertos": 0, "desconocidos": 0}
    for c in clicks:
        firma = compute_state_signature(c["grid"], (6,), None)
        x, y = memoria.elegir_objetivo(
            c["grid"], firma, lambda: 0.5, region_que_cambio(c["previa"], c["grid"])
        )
        etiqueta = oraculo.get((x, y))
        if etiqueta is None:
            conteo["desconocidos"] += 1
        elif etiqueta:
            conteo["productivos"] += 1
        else:
            conteo["muertos"] += 1
        memoria.registrar_resultado(firma, x, y, etiqueta is True, c["grid"])
    return conteo


@pytest.mark.skipif(not FIXTURE.exists(), reason="corpus de clicks ausente")
def test_efecto_de_la_memoria_transversal_sobre_el_corpus_real_de_ft09() -> None:
    """EVALUACION OFF-POLICY sobre la partida REAL grabada (ft09-0d8bbf25, 346 clicks), misma
    metodologia conservadora que BL.21560: una coordenada nunca observada cuenta como DESCONOCIDA
    y se le realimenta "no hubo cambio", que castiga a la politica nueva.

    232 -> 293 clicks productivos, y los muertos NO suben (1 en los dos casos): la palanca no gana
    cobertura a costa de precision, gana lo que el ranker ya sabia y la memoria por firma le
    impedia gastar."""
    apagada = _recorrer_corpus(SIN_PALANCAS)
    encendida = _recorrer_corpus(SOLO_CLICKS)
    assert apagada["productivos"] == 232
    assert encendida["productivos"] == 293
    assert apagada["muertos"] == 1
    assert encendida["muertos"] == 1
    assert encendida["desconocidos"] < apagada["desconocidos"]


# ============================================================================================
# PALANCA 2 -- mascara de volatilidad construible con UNA sola accion
# ============================================================================================

ALTO_HUD = 8
ANCHO_HUD = 8


def _par_con_hud(paso: int, mover_tablero: bool) -> tuple[list[list[int]], list[list[int]]]:
    """Pre/post de una transicion: la celda (0,0) es un contador de HUD que cambia SIEMPRE; el
    tablero cambia solo si `mover_tablero`."""
    pre = [[0] * ANCHO_HUD for _ in range(ALTO_HUD)]
    pre[0][0] = paso % 9 + 1
    pre[4][4] = 7
    post = [fila[:] for fila in pre]
    post[0][0] = (paso + 1) % 9 + 1
    if mover_tablero:
        post[4][4] = 2
    return pre, post


def test_sin_la_palanca_un_juego_de_una_sola_accion_no_puede_construir_mascara() -> None:
    """EL DEFECTO MEDIDO: `VOLATILITY_MIN_DISTINCT_ACTIONS`=2 vuelve la mascara imposible por
    construccion en los SEIS juegos publicos que exponen `availableActions=[6]`, y en los siete
    juegos atascados `maskCeldasFinal` fue 0 de punta a punta."""
    tracker = VolatilityTracker(permitir_accion_unica=False)
    tracker.declarar_vocabulario(1)
    for paso in range(40):
        pre, post = _par_con_hud(paso, mover_tablero=paso % 5 == 0)
        tracker.observe("ACTION6", pre, post)
    assert tracker.mask is None
    assert tracker.volatile_cell_count() == 0


def test_con_la_palanca_la_mascara_ve_el_hud_de_un_juego_de_un_solo_boton() -> None:
    tracker = VolatilityTracker(permitir_accion_unica=True)
    tracker.declarar_vocabulario(1)
    for paso in range(40):
        pre, post = _par_con_hud(paso, mover_tablero=paso % 5 == 0)
        tracker.observe("ACTION6", pre, post)
    assert tracker.modo_de_accion_unica is True
    mask = tracker.mask
    assert mask is not None
    assert mask[0][0] is True, "el contador que cambia en todas las transiciones entra"
    assert mask[4][4] is False, "la celda del tablero NO entra: no cambia siempre"


def test_el_modo_de_accion_unica_no_se_come_una_celda_del_tablero_que_casi_siempre_cambia() -> None:
    """El umbral de accion unica es 0,98 justamente porque sin un segundo boton con el que
    contrastar lo unico que separa el HUD del tablero es que el HUD cambie SIEMPRE. Una celda que
    cambia en 9 de cada 10 pasos -- muchisimo para un tablero -- sigue afuera."""
    tracker = VolatilityTracker(permitir_accion_unica=True)
    tracker.declarar_vocabulario(1)
    for paso in range(40):
        pre = [[0] * ANCHO_HUD for _ in range(ALTO_HUD)]
        pre[0][0] = paso % 9 + 1
        pre[4][4] = paso % 3
        post = [fila[:] for fila in pre]
        post[0][0] = (paso + 1) % 9 + 1
        if paso % 10 != 0:
            post[4][4] = (paso + 1) % 3
        tracker.observe("ACTION6", pre, post)
    mask = tracker.mask
    assert mask is not None
    assert mask[0][0] is True
    assert mask[4][4] is False


def test_el_modo_no_se_activa_por_haber_observado_un_solo_boton_todavia() -> None:
    """Una macro deja hasta 8 transiciones seguidas de la misma accion en un juego de varias: ahi
    el contraste existe, solo que aun no se midio. El modo mira el vocabulario DECLARADO."""
    tracker = VolatilityTracker(permitir_accion_unica=True)
    tracker.declarar_vocabulario(5)
    for paso in range(40):
        pre, post = _par_con_hud(paso, mover_tablero=False)
        tracker.observe("ACTION1", pre, post)
    assert tracker.modo_de_accion_unica is False
    assert tracker.mask is None


def test_la_barra_de_barrido_tambien_se_ve_con_un_solo_boton() -> None:
    """La familia 2 nunca dependio del contraste entre acciones: su criterio es de FORMA (linea de
    una celda de ancho sobre un borde) y de SOLEDAD. El minimo de acciones era redundante ahi."""
    ancho = 40
    alto = 6
    tracker = VolatilityTracker(permitir_accion_unica=True)
    tracker.declarar_vocabulario(1)

    def grilla(contador: int) -> list[list[int]]:
        filas = [[0] * ancho for _ in range(alto)]
        for i in range(min(contador, ancho)):
            filas[alto - 1][i] = 4
        return filas

    for paso in range(30):
        tracker.observe("ACTION6", grilla(paso), grilla(paso + 1))
    mask = tracker.mask
    assert mask is not None
    assert mask[alto - 1][0] is True
    assert mask[0][0] is False


# ============================================================================================
# PALANCA 3 -- cortar la amplificacion de MacroCommitment
# ============================================================================================

DISPONIBLES_MACRO = ["ACTION5", "ACTION6", "ACTION7"]


def test_sin_la_palanca_la_macro_llega_al_tope_con_cambios_repetidos() -> None:
    """EL DEFECTO: `continuar()` solo cortaba con `hubo_cambio=False`, asi que una accion cosmetica
    siempre-cambiante se llevaba x8 la cuota de una que no-opea (sb26: ACTION5 82,8%)."""
    macro = MacroCommitment(SIN_PALANCAS)
    macro.iniciar("ACTION5")
    emitidas = 1
    while macro.continuar("ACTION5", True, DISPONIBLES_MACRO, estado_ya_visitado=True) is not None:
        emitidas += 1
    assert emitidas == MACRO_MAX_STEPS
    assert macro.cortes_por_estado_repetido == 0


def test_con_la_palanca_la_macro_corta_al_caer_en_un_estado_ya_visitado() -> None:
    macro = MacroCommitment(SOLO_MACRO)
    macro.iniciar("ACTION5")
    assert macro.continuar("ACTION5", True, DISPONIBLES_MACRO, estado_ya_visitado=True) is None
    assert macro.cortes_por_estado_repetido == 1
    assert macro.accion_vigente is None


def test_la_macro_sigue_avanzando_mientras_el_estado_sea_nuevo() -> None:
    """La macro existe para "avanzar hasta chocar": recorrer un tablero produce estados nuevos y
    ahi el compromiso tiene que sostenerse igual que antes."""
    macro = MacroCommitment(SOLO_MACRO)
    macro.iniciar("ACTION1")
    emitidas = 1
    while macro.continuar("ACTION1", True, ["ACTION1"], estado_ya_visitado=False) is not None:
        emitidas += 1
    assert emitidas == MACRO_MAX_STEPS
    assert macro.cortes_por_estado_repetido == 0


# --- efecto sobre un juego con una accion cosmetica -------------------------------------------

def _cuota_de_accion5(banderas: Banderas, pasos: int = 120) -> float:
    _politica, acciones = correr(
        AccionCosmetica(), banderas, pasos=pasos, semilla="bl21702-cosmetico"
    )
    return sum(1 for a in acciones if a is GameAction.ACTION5) / pasos


def test_efecto_la_palanca_le_saca_a_la_accion_cosmetica_su_monopolio() -> None:
    apagada = _cuota_de_accion5(SIN_PALANCAS)
    encendida = _cuota_de_accion5(SOLO_MACRO)
    assert apagada > 0.5, "sin la palanca la accion cosmetica domina, como se midio en sb26"
    assert encendida < apagada


# ============================================================================================
# PALANCA 4 -- warmup del libro de aperturas con los clicks SEGUIDOS
# ============================================================================================


def _gastar_warmup(banderas: Banderas, pasos: int = 60) -> tuple[int, list[str]]:
    """Simula el bucle libro<->politica de un juego que arranca en un MENU QUE ANIMA: las flechas
    nunca mueven el tablero (resultado inconcluso) y cada click cambia pixeles porque el menu se
    anima. Devuelve los clicks de warmup gastados y la secuencia sugerida."""
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4, 6))
    libro = LibroDeAperturas(creencia, banderas=banderas)
    disponibles = ["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION6"]
    secuencia: list[str] = []
    for paso in range(pasos):
        sugerida = libro.sugerir(disponibles, paso)
        if sugerida is None:
            break
        secuencia.append(sugerida)
        # El menu ANIMA: cualquier accion cambia pixeles, y ninguna flecha resuelve nada.
        libro.registrar(sugerida, "inconcluso", True, paso)
    return libro.clics_de_warmup_gastados, secuencia


def _racha_maxima_de_clicks(secuencia: list[str]) -> int:
    maxima = actual = 0
    for accion in secuencia:
        actual = actual + 1 if accion == "ACTION6" else 0
        maxima = max(maxima, actual)
    return maxima


def _pasos_hasta_gastar_el_warmup(secuencia: list[str]) -> int | None:
    """Indice (1-based) del paso en que sale el noveno click, o None si nunca sale."""
    vistos = 0
    for i, accion in enumerate(secuencia, 1):
        if accion == "ACTION6":
            vistos += 1
            if vistos == CLICS_DE_WARMUP:
                return i
    return None


def test_sin_la_palanca_el_menu_que_anima_salpica_los_clicks_de_warmup() -> None:
    """EL DEFECTO MEDIDO EN dc22: `_registrar_warmup` limpiaba `_tanteadas` con cada click que
    cambiara el tablero, y la pantalla de titulo ANIMA -- asi que el libro volvia a tantear las
    cuatro flechas entre click y click. La medicion de BL.21590 fijo que hacen falta NUEVE clicks
    SEGUIDOS para salir del menu, y asi nunca salen seguidos: en el entorno real fueron 8 ACTION6
    en 151 acciones."""
    _clics, secuencia = _gastar_warmup(SIN_PALANCAS)
    assert _racha_maxima_de_clicks(secuencia) < CLICS_DE_WARMUP
    # Y los clicks salen SALPICADOS entre tanteos de flecha, no seguidos.
    indices = [i for i, a in enumerate(secuencia) if a == "ACTION6"]
    assert any(b - a > 1 for a, b in zip(indices, indices[1:]))


def test_con_la_palanca_los_clicks_de_warmup_salen_seguidos_y_mas_temprano() -> None:
    clics, secuencia = _gastar_warmup(SOLO_WARMUP)
    assert clics >= CLICS_DE_WARMUP
    assert _racha_maxima_de_clicks(secuencia) >= CLICS_DE_WARMUP, (
        "los clicks de warmup tienen que salir CONSECUTIVOS: la medicion de BL.21590 fijo que "
        "hacen falta 9 seguidos para salir del menu"
    )
    # Y el presupuesto se gasta ANTES, porque no se intercalan rondas de tanteo de flechas.
    _clics_sin, secuencia_sin = _gastar_warmup(SIN_PALANCAS)
    assert _pasos_hasta_gastar_el_warmup(secuencia) < _pasos_hasta_gastar_el_warmup(secuencia_sin)


def test_con_la_palanca_el_retanteo_diferido_igual_ocurre_al_agotar_los_clicks() -> None:
    """Diferir no es cancelar: cuando el presupuesto se agota, las flechas se vuelven a medir UNA
    vez, ya del otro lado del menu."""
    _, secuencia = _gastar_warmup(SOLO_WARMUP)
    indices = [i for i, a in enumerate(secuencia) if a == "ACTION6"]
    assert any(a != "ACTION6" for a in secuencia[indices[-1] + 1 :]), (
        "tras gastar los clicks el libro vuelve a tantear flechas"
    )


# ============================================================================================
# EFECTO DE COBERTURA (palanca 1) -- juego de click donde NINGUNA firma se repite (su15/tn36)
# ============================================================================================


def test_efecto_la_memoria_transversal_multiplica_la_cobertura_de_coordenadas() -> None:
    """LA MAGNITUD AFIRMADA es la cobertura, que es lo que el diagnostico midio: sin la palanca el
    agente reusa un punado de celdas aunque la firma cambie en cada paso."""
    sin_palanca, _ = correr(ClickConFirmaSiempreNueva(), SIN_PALANCAS, pasos=80)
    con_palanca, _ = correr(ClickConFirmaSiempreNueva(), SOLO_CLICKS, pasos=80)
    celdas_sin = sin_palanca.memoria_de_clicks.celdas_distintas_clickeadas
    celdas_con = con_palanca.memoria_de_clicks.celdas_distintas_clickeadas
    assert celdas_con > celdas_sin * 2, (
        f"cobertura de coordenadas: {celdas_sin} sin la palanca contra {celdas_con} con ella"
    )


# ============================================================================================
