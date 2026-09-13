"""[arc-agi3-kaggle-agent/tests/test_bl21560_click_targeting] BL.21560 -- las tres capas que deciden
DONDE clickear, cada una probada por separado: features de celda, plantilla de parche y memoria por
(firma, x, y). El efecto agregado sobre dato REAL vive en test_bl21560_real_clicks.py.

Las grillas de aca son MINIATURAS del caso real (una ficha rodeada por el marco de un tablero contra
la misma ficha rodeada por el fondo), no inventos: reproducen a escala la unica estructura que
separa un click productivo de uno muerto en las partidas medidas.
"""
from __future__ import annotations

from arc_agent.banderas import Banderas
from arc_agent.click_targeting import (
    BONO_POR_PLANTILLA,
    PENALIZACION_POR_ANTI_PLANTILLA,
    CLICK_FEATURE_NAMES,
    ClickFeatureBoard,
    ClickMemory,
    extraer_parche,
    puntuar_celda,
    region_que_cambio,
    similitud_de_parche,
)
from arc_agent.exploration_memory import prioridad_por_priors, rank_candidates
from arc_agent.priors import CLICK_PRIORS
from arc_agent.types import GameAction

FONDO = 5
MARCO = 4
FICHA = 9


#: Lado de las miniaturas. 12x12 y no 8x8 para que el FONDO siga siendo el color mayoritario con el
#: marco puesto (108 celdas contra 36): `detect_background_color` elige el mas frecuente, y en una
#: grilla chica el marco lo destronaba -- exactamente el tipo de detalle que solo se ve corriendo.
LADO = 12


def _grilla_con_ficha_en_marco() -> list[list[int]]:
    """12x12 de fondo con un marco 6x6 en (3,3)-(8,8) y una ficha 2x2 adentro, en (4,4)."""
    grid = [[FONDO] * LADO for _ in range(LADO)]
    for y in range(3, 9):
        for x in range(3, 9):
            grid[y][x] = MARCO
    for y in range(4, 6):
        for x in range(4, 6):
            grid[y][x] = FICHA
    return grid


def _grilla_con_ficha_suelta() -> list[list[int]]:
    """La MISMA ficha 2x2, pero flotando sobre el fondo: el panel decorativo del caso real."""
    grid = [[FONDO] * LADO for _ in range(LADO)]
    for y in range(4, 6):
        for x in range(4, 6):
            grid[y][x] = FICHA
    return grid


def _indice(nombre: str) -> int:
    return CLICK_FEATURE_NAMES.index(nombre)


def test_el_vector_de_features_tiene_el_largo_de_los_pesos() -> None:
    """El orden de las features es un CONTRATO posicional con priors.py: si se desincronizan, cada
    peso pasa a multiplicar otra cosa y nadie se entera."""
    assert len(CLICK_FEATURE_NAMES) == len(CLICK_PRIORS["pesosClick"])
    assert CLICK_FEATURE_NAMES[0] == "sesgo"


def test_la_feature_de_vecindario_separa_la_ficha_del_tablero_del_panel_decorativo() -> None:
    dentro = ClickFeatureBoard(_grilla_con_ficha_en_marco())
    suelta = ClickFeatureBoard(_grilla_con_ficha_suelta())
    i = _indice("componenteRodeadaDeFondo")
    # Misma ficha, mismo color, mismo tamano: lo unico que cambia es que toca el fondo.
    assert dentro.features(4, 4)[i] == 0.0
    assert suelta.features(4, 4)[i] == 1.0
    assert dentro.tamano_de_componente(4, 4) == suelta.tamano_de_componente(4, 4) == 4


def test_las_features_describen_borde_fondo_y_region_que_cambio() -> None:
    grid = _grilla_con_ficha_en_marco()
    tablero = ClickFeatureBoard(grid, region_cambiada=(4, 4, 5, 5))
    esquina = tablero.features(4, 4)
    assert esquina[_indice("esBordeDeComponente")] == 1.0
    assert esquina[_indice("bordeDeColor")] == 0.5  # dos vecinos ortogonales distintos
    assert esquina[_indice("enRegionQueCambio")] == 1.0
    assert tablero.features(0, 0)[_indice("esColorDeFondo")] == 1.0
    assert tablero.features(0, 0)[_indice("enRegionQueCambio")] == 0.0


def test_el_ranker_prefiere_la_ficha_del_tablero_antes_que_la_suelta() -> None:
    """Con los pesos ajustados, la MISMA ficha puntua mas alto dentro del tablero que flotando."""
    pesos = CLICK_PRIORS["pesosClick"]
    dentro = puntuar_celda(ClickFeatureBoard(_grilla_con_ficha_en_marco()).features(4, 4), pesos)
    suelta = puntuar_celda(ClickFeatureBoard(_grilla_con_ficha_suelta()).features(4, 4), pesos)
    assert dentro > suelta


def test_la_memoria_no_repite_una_coordenada_en_el_mismo_estado() -> None:
    grid = _grilla_con_ficha_en_marco()
    memoria = ClickMemory()
    elegidas = []
    for _ in range(6):
        x, y = memoria.elegir_objetivo(grid, firma=1, rng=lambda: 0.0)
        elegidas.append((x, y))
        memoria.registrar_resultado(1, x, y, False, grid)
    assert len(set(elegidas)) == len(elegidas)


def test_la_misma_coordenada_vuelve_a_ser_elegible_si_cambia_la_firma() -> None:
    """La clave lleva la FIRMA a proposito: si el tablero cambio, lo que ahi no hacia nada puede
    empezar a hacerlo (ARC-AGI-3 depende del estado global).

    BL.21702 midio el reverso de esta moneda: cuando NINGUNA firma se repite (mascara de
    volatilidad en 0 celdas, que es el caso de los siete juegos atascados) esta regla degenera en
    clickear siempre la misma celda. La palanca `memoriaTransversalDeClicks` corrige eso y por eso
    aca se mide APAGADA -- este test afirma el contrato de BL.21560, no el de BL.21702."""
    grid = _grilla_con_ficha_en_marco()
    memoria = ClickMemory(banderas=Banderas(()))
    primera = memoria.elegir_objetivo(grid, firma=1, rng=lambda: 0.0)
    memoria.registrar_resultado(1, primera[0], primera[1], False, grid)
    assert memoria.elegir_objetivo(grid, firma=1, rng=lambda: 0.0) != primera
    assert memoria.elegir_objetivo(grid, firma=2, rng=lambda: 0.0) == primera


def test_un_click_con_efecto_ilumina_las_celdas_con_el_mismo_parche() -> None:
    """La capa de plantilla: UN acierto convierte al resto de las celdas gemelas en candidatas
    prioritarias. Es lo que en el caso real hace que el primer acierto ilumine las otras ocho
    fichas del tablero."""
    ancho = 12
    grid = [[FONDO] * ancho for _ in range(14)]
    for y in range(3, 7):
        for x in range(1, 11):
            grid[y][x] = MARCO
    # Dos fichas 2x2 IDENTICAS dentro del marco, separadas.
    for x0 in (2, 7):
        for y in range(4, 6):
            for x in range(x0, x0 + 2):
                grid[y][x] = FICHA

    memoria = ClickMemory()
    # Esquina INFERIOR DERECHA de la segunda ficha: otro parche, no deberia recibir el bono nunca.
    otra_esquina = 5 * ancho + 8
    sin_plantilla = memoria.puntajes_por_celda(grid)[otra_esquina]
    memoria.registrar_resultado(1, 2, 4, True, grid)
    assert memoria.plantillas_aprendidas == 1
    # La esquina HOMOLOGA de la otra ficha (misma orientacion) sube exactamente el bono.
    con_plantilla = memoria.puntajes_por_celda(grid)[4 * ancho + 7]
    solo_prior = puntuar_celda(ClickFeatureBoard(grid).features(7, 4), CLICK_PRIORS["pesosClick"])
    assert con_plantilla == solo_prior + BONO_POR_PLANTILLA
    assert memoria.puntajes_por_celda(grid)[otra_esquina] == sin_plantilla


def test_dos_clicks_muertos_con_el_mismo_parche_descartan_toda_la_clase() -> None:
    """Es lo que evita barrer una region grande e inerte celda por celda: medido contra la API
    oficial en lp85-305b61c3, sin esto el agente gasto 403 de 499 clicks en la cenefa decorativa del
    borde. Con anti-plantillas la misma partida acerto 13 de 79 (16,5% contra el 4,2% grabado)."""
    grid = _grilla_con_ficha_en_marco()
    memoria = ClickMemory()
    antes = memoria.puntajes_por_celda(grid)[9 * LADO + 0]
    memoria.registrar_resultado(1, 0, 5, False, grid)
    assert memoria.anti_plantillas_aprendidas == 0  # un solo fallo puede ser ruido
    memoria.registrar_resultado(1, 0, 7, False, grid)
    assert memoria.anti_plantillas_aprendidas == 1
    # Una TERCERA celda con el mismo parche, nunca clickeada, ya quedo descartada.
    assert memoria.puntajes_por_celda(grid)[9 * LADO + 0] == antes - PENALIZACION_POR_ANTI_PLANTILLA


def test_un_click_con_efecto_desmiente_la_anti_plantilla_del_mismo_parche() -> None:
    grid = _grilla_con_ficha_en_marco()
    memoria = ClickMemory()
    memoria.registrar_resultado(1, 0, 5, False, grid)
    memoria.registrar_resultado(1, 0, 7, False, grid)
    assert memoria.anti_plantillas_aprendidas == 1
    memoria.registrar_resultado(1, 0, 9, True, grid)
    assert memoria.anti_plantillas_aprendidas == 0
    assert memoria.plantillas_aprendidas == 1


def test_la_plantilla_se_toma_de_la_grilla_PREVIA_al_click() -> None:
    """El parche tiene que describir lo que se veia AL DECIDIR: la grilla posterior ya cambio
    justamente por el click, y guardarla haria buscar un patron que solo existe despues."""
    grid = _grilla_con_ficha_en_marco()
    memoria = ClickMemory()
    memoria.registrar_resultado(1, 4, 4, True, grid)
    assert memoria.plantillas_aprendidas == 1
    esperado = extraer_parche(grid, 4, 4)
    assert similitud_de_parche(esperado, extraer_parche(grid, 4, 4)) == 1.0
    # Sin cambio no se aprende ninguna plantilla: solo el exito ensena donde clickear.
    memoria.registrar_resultado(1, 7, 7, False, grid)
    assert memoria.plantillas_aprendidas == 1


def test_region_que_cambio_devuelve_el_rectangulo_o_none() -> None:
    a = _grilla_con_ficha_en_marco()
    b = [fila[:] for fila in a]
    assert region_que_cambio(a, b) is None
    b[3][4] = FICHA
    b[5][6] = FICHA
    assert region_que_cambio(a, b) == (4, 3, 6, 5)
    assert region_que_cambio(None, b) is None


def test_elegir_objetivo_consume_exactamente_un_numero_del_rng() -> None:
    """La reproducibilidad de una partida dado su seed depende de que la secuencia del rng no varie
    con el contenido de la memoria."""
    grid = _grilla_con_ficha_en_marco()
    memoria = ClickMemory()
    consumidos = 0

    def rng() -> float:
        nonlocal consumidos
        consumidos += 1
        return 0.5

    memoria.elegir_objetivo(grid, firma=1, rng=rng)
    assert consumidos == 1
    memoria.registrar_resultado(1, 4, 4, True, grid)
    memoria.elegir_objetivo(grid, firma=1, rng=rng)
    assert consumidos == 2


def test_el_prior_de_acciones_solo_desempata_en_el_arranque() -> None:
    """`ordenAcciones` es un prior de arranque en frio. Aplicado siempre convierte la exploracion en
    una sola accion repetida (medido en el escenario de desplazamiento de BL.21559)."""
    orden = CLICK_PRIORS["ordenAcciones"]
    assert orden, "los priors tienen que traer un orden de acciones medido"
    mejor = GameAction(orden[0])
    peor = GameAction(orden[-1])
    assert prioridad_por_priors(mejor) < prioridad_por_priors(peor)

    disponibles = tuple(int(a.value.removeprefix("ACTION")) for a in (peor, mejor))
    sin_prior = rank_candidates(disponibles, {}, set(), lambda: 0.9)
    con_prior = rank_candidates(disponibles, {}, set(), lambda: 0.9, prior_de_arranque=True)
    assert con_prior[0] is mejor
    # Sin arranque el orden lo sigue decidiendo el barajado, no los priors: el comportamiento previo
    # queda intacto paso a paso.
    assert set(sin_prior) == set(con_prior)


def test_una_accion_fuera_de_los_priors_no_se_adelanta() -> None:
    fuera = GameAction("ACTION5") if "ACTION5" not in CLICK_PRIORS["ordenAcciones"] else None
    if fuera is None:
        # Todas las acciones estan rankeadas: se verifica el default para un nombre desconocido.
        assert prioridad_por_priors(GameAction("RESET")) == len(CLICK_PRIORS["ordenAcciones"])
