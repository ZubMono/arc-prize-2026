"""[arc-agi3-kaggle-agent/tests/test_object_mechanics] BL.21561 -- los cinco detectores de
mecanicas objeto-centricas, incluidos los casos exactos que el DSL grilla-a-grilla NO podia
resolver (sonda del BL: objeto 2x2 que se mueve en 64x64 con paredes -> `propose_all_steps` vacio;
una sola celda que cambia de color -> vacio). Espejo de
arc-agi-runner/src/worldModel/__tests__/objectMechanics.test.ts.
"""
from __future__ import annotations

from arc_agent.world_model import (
    Grid,
    MechanicsMemory,
    detectar_mecanica,
    firma_de_mecanica,
    propose_all_steps,
)


def tablero() -> Grid:
    """Tablero 64x64 con paredes en el borde (color 4) y piso 2 -- la forma real de los juegos."""
    return [
        [4 if (y in (0, 63) or x in (0, 63)) else 2 for x in range(64)] for y in range(64)
    ]


def pintar(grid: Grid, y0: int, x0: int, alto: int, ancho: int, color: int) -> None:
    for y in range(y0, y0 + alto):
        for x in range(x0, x0 + ancho):
            grid[y][x] = color


def cursor(y: int, x: int) -> Grid:
    g = tablero()
    pintar(g, y, x, 2, 2, 7)
    return g


# --- 1. traslacion (cursor/jugador) -----------------------------------------


def test_objeto_2x2_que_se_mueve_una_celda_el_caso_que_el_dsl_daba_vacio() -> None:
    pre = tablero()
    pintar(pre, 30, 30, 2, 2, 7)
    post = tablero()
    pintar(post, 30, 31, 2, 2, 7)

    # La sonda del BL, ejecutable: el analizador viejo no propone NADA para este par.
    assert propose_all_steps(pre, post) == []

    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "traslacion"
    assert (mecanica.traslacion_principal.dy, mecanica.traslacion_principal.dx) == (0, 1)
    assert (mecanica.traslacion_principal.alto, mecanica.traslacion_principal.ancho) == (2, 2)
    assert firma_de_mecanica(mecanica) == "traslacion:0,1"


def test_recupera_la_direccion_en_los_cuatro_sentidos_con_el_signo_correcto() -> None:
    for dy, dx in ((-3, 0), (3, 0), (0, -3), (0, 3)):
        pre = tablero()
        pintar(pre, 30, 30, 3, 3, 7)
        post = tablero()
        pintar(post, 30 + dy, 30 + dx, 3, 3, 7)
        t = detectar_mecanica(pre, post).traslacion_principal
        assert t is not None and (t.dy, t.dx) == (dy, dx), f"d=({dy},{dx})"


def test_no_invierte_la_direccion_cuando_el_objeto_se_mueve_a_un_hueco() -> None:
    """Es el bug que la version ingenua tenia sobre dc22: "el hueco se movio al reves" satisface
    las mismas ecuaciones. Se prueba con el objeto pegado a la pared, que es donde el fondo local
    deja de ser el piso y solo la cobertura por componente contenida rompe el empate."""
    pre = tablero()
    pintar(pre, 61, 30, 2, 2, 7)
    post = tablero()
    pintar(post, 61, 32, 2, 2, 7)
    t = detectar_mecanica(pre, post).traslacion_principal
    assert t is not None and (t.dy, t.dx) == (0, 2)


def test_un_objeto_que_se_mueve_sobre_otro_color_sigue_siendo_traslacion() -> None:
    pre = tablero()
    pintar(pre, 20, 20, 2, 2, 7)
    pintar(pre, 20, 22, 2, 2, 5)  # baldosa de destino de otro color
    post = tablero()
    pintar(post, 20, 22, 2, 2, 7)
    pintar(post, 20, 20, 2, 2, 2)  # deja piso
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "traslacion"
    assert (mecanica.traslacion_principal.dy, mecanica.traslacion_principal.dx) == (0, 2)


def test_ignora_las_celdas_volatiles_la_barra_no_rompe_la_deteccion() -> None:
    pre = tablero()
    pintar(pre, 30, 30, 2, 2, 7)
    post = tablero()
    pintar(post, 30, 31, 2, 2, 7)
    post[0][10] = 9  # avance de la barra, fuera del tablero de juego
    assert detectar_mecanica(pre, post).tipo == "desconocida"

    mask = [[y == 0 for _ in range(64)] for y in range(64)]
    t = detectar_mecanica(pre, post, mask).traslacion_principal
    assert t is not None and (t.dy, t.dx) == (0, 1)


# --- 2 y 3: recoloreo, aparicion, desaparicion -------------------------------


def test_una_celda_que_cambia_de_color_el_otro_caso_que_el_dsl_daba_vacio() -> None:
    pre = tablero()
    post = tablero()
    post[30][30] = 6
    assert propose_all_steps(pre, post) == []
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "aparicion"
    c = mecanica.cambio_de_color_principal
    assert (c.desde, c.hasta, c.celdas) == (2, 6, 1)
    assert firma_de_mecanica(mecanica) == "aparicion:2>6"


def test_un_objeto_que_desaparece() -> None:
    pre = tablero()
    pintar(pre, 30, 30, 2, 2, 6)
    mecanica = detectar_mecanica(pre, tablero())
    assert mecanica.tipo == "desaparicion"
    c = mecanica.cambio_de_color_principal
    assert (c.desde, c.hasta, c.celdas) == (6, 2, 4)


def test_un_objeto_que_cambia_de_color_en_el_lugar() -> None:
    pre = tablero()
    pintar(pre, 30, 30, 2, 2, 6)
    post = tablero()
    pintar(post, 30, 30, 2, 2, 8)
    mecanica = detectar_mecanica(pre, post)
    assert mecanica.tipo == "recoloreo"
    c = mecanica.cambio_de_color_principal
    assert (c.desde, c.hasta, c.celdas) == (6, 8, 4)


def test_sin_cambios_es_sin_cambio_no_desconocida() -> None:
    grid = tablero()
    assert detectar_mecanica(grid, [list(f) for f in grid]).tipo == "sinCambio"


def test_grillas_de_forma_distinta_forma_incompatible_sin_lanzar() -> None:
    # BL.21741: ya no es "desconocida". "Desconocida" es "mire los clusters y no supe nombrarlos";
    # esto es "ni siquiera pude comparar las dos grillas", y confundirlos hacia que el silencio del
    # detector se leyera como quietud.
    assert detectar_mecanica([[1, 2]], [[1], [2]]).tipo == "formaIncompatible"


# --- MechanicsMemory: evidencia Beta por accion ------------------------------


def test_confirma_la_direccion_tras_dos_observaciones_coherentes() -> None:
    memoria = MechanicsMemory()
    assert memoria.get_direction("ACTION3") is None
    memoria.observe("ACTION3", cursor(30, 30), cursor(30, 28))
    assert memoria.get_direction("ACTION3") is None, "una sola observacion no confirma"
    memoria.observe("ACTION3", cursor(30, 28), cursor(30, 26))
    assert memoria.get_direction("ACTION3") == (0, -2)
    assert memoria.get_movement_actions() == ["ACTION3"]


def test_un_choque_contra_la_pared_no_mata_la_regla_solo_mueve_la_beta() -> None:
    """Es el caso que rompia verify_program: la regla correcta moria en la primera observacion que
    no encajaba. Aca sobrevive con cobertura 3/4 y el fallo queda contabilizado en beta."""
    memoria = MechanicsMemory()
    memoria.observe("ACTION3", cursor(30, 30), cursor(30, 28))
    memoria.observe("ACTION3", cursor(30, 28), cursor(30, 26))
    memoria.observe("ACTION3", cursor(30, 26), cursor(30, 24))
    pegado = cursor(30, 1)
    memoria.observe("ACTION3", pegado, pegado)  # choque: no se mueve nada
    h = memoria.get_hypothesis("ACTION3")
    assert h is not None
    assert h.firma == "traslacion:0,-2"
    assert (h.alpha, h.beta) == (4, 2)
    assert abs(h.cobertura - 0.75) < 1e-9
    assert memoria.get_direction("ACTION3") == (0, -2)


def test_una_accion_inerte_se_reconoce_sin_pasar_por_la_sintesis_dsl() -> None:
    memoria = MechanicsMemory()
    g = cursor(30, 30)
    memoria.observe("ACTION5", g, g)
    memoria.observe("ACTION5", g, g)
    assert memoria.is_inert_action("ACTION5") is True
    assert memoria.get_direction("ACTION5") is None


def test_detector_4_la_arena_es_el_bbox_de_lo_que_cambio() -> None:
    memoria = MechanicsMemory()
    memoria.observe("ACTION3", cursor(30, 30), cursor(30, 28))
    memoria.observe("ACTION3", cursor(30, 28), cursor(30, 26))
    caja = memoria.get_active_bounding_box()
    assert caja is not None
    assert (caja.min_y, caja.max_y, caja.min_x, caja.max_x) == (30, 31, 26, 31)
    assert memoria.is_static_cell(0, 0) is True
    assert memoria.is_static_cell(30, 30) is False
    assert memoria.get_static_cell_count() == 64 * 64 - 12


def test_detector_5_un_color_que_solo_crece_es_un_contador() -> None:
    memoria = MechanicsMemory()
    anterior = tablero()
    for i in range(1, 5):
        siguiente = tablero()
        pintar(siguiente, 5, 5, 1, i, 3)  # la barra de vidas crece una celda por paso
        memoria.observe("ACTION1", anterior, siguiente)
        anterior = siguiente
    contadores = {c.color: c for c in memoria.get_counters()}
    assert 3 in contadores
    assert contadores[3].direccion == "sube"
    assert contadores[3].cambios >= 3
    # 4 frames observados = 3 deltas (+1 cada uno): el primero solo fija la linea de base.
    assert contadores[3].delta == 3


def test_detector_5_un_color_que_sube_y_baja_no_es_un_contador() -> None:
    memoria = MechanicsMemory()
    chico = tablero()
    pintar(chico, 5, 5, 1, 1, 3)
    grande = tablero()
    pintar(grande, 5, 5, 1, 4, 3)
    for _ in range(4):
        memoria.observe("ACTION1", chico, grande)
        memoria.observe("ACTION1", grande, chico)
    assert all(c.color != 3 for c in memoria.get_counters())
