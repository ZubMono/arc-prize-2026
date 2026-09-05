"""[arc-agi3-kaggle-agent/tests/test_volatility_mask] BL.21558 -- mascara de volatilidad: que
celdas aprende a ignorar el modelo de mundo, y la PARIDAD de la aritmetica con el motor TypeScript
canonico (projects/arc-agi-runner/src/worldModel).

Los dos errores posibles NO son simetricos: no enmascarar el HUD es el bug que este BL arregla (el
agente no detecta ningun no-op en toda la partida); enmascarar el TABLERO seria mucho peor, porque
lo dejaria ciego justo donde esta la señal. Por eso buena parte de este archivo prueba que celdas
del juego NO entran a la mascara.
"""
from __future__ import annotations

from arc_agent.world_model import (
    VOLATILITY_MIN_TRANSITIONS,
    VolatilityTracker,
    compute_state_signature,
    grids_equal,
    grids_equal_masked,
    hash_grid,
    hash_grid_masked,
    is_no_op_transition,
    neutralize_volatile_cells,
)

# Tablero 5x5 con un marcador + una fila de HUD con dos contadores de periodos coprimos (11 y 13),
# calcado del entorno sintetico del lado TypeScript.
_TAMANO = 5
_MARCADOR = 5
_FILA_HUD = _TAMANO
_ACCIONES = ["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5"]

# Valores de referencia emitidos por el motor CANONICO (ver los tests homonimos en
# arc-agi-runner/src/worldModel/__tests__/grid.test.ts y stateSignature.test.ts). Si alguno de los
# dos lados cambia la aritmetica del hash, uno de los dos archivos se pone en rojo -- es el mismo
# contrato ejecutable que dslParity.json, pero para la mascara.
_GRILLA_PARIDAD = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
_MASCARA_PARIDAD = [
    [False, False, False],
    [False, False, False],
    [False, True, True],
]
_HASH_SIN_MASCARA = 4166473219
_HASH_CON_MASCARA = 767370346
_FIRMA_CON_MASCARA = 3297065176


def _frame(x: int, y: int, contador: int, hud: bool) -> list[list[int]]:
    grid = [[0] * _TAMANO for _ in range(_TAMANO)]
    grid[y][x] = _MARCADOR
    if hud:
        fila = [0] * _TAMANO
        fila[0] = contador % 11
        fila[1] = contador % 13
        grid.append(fila)
    return grid


def _correr(tracker: VolatilityTracker, pasos: int, hud: bool) -> None:
    """Round-robin sobre las 5 acciones -- garantiza que TODAS aporten evidencia, incluida
    ACTION5, que en este entorno no mueve el marcador. Esa asimetria es lo que separa el HUD del
    tablero."""
    x, y = 2, 2
    for i in range(pasos):
        accion = _ACCIONES[i % len(_ACCIONES)]
        pre = _frame(x, y, i, hud)
        if accion == "ACTION1":
            x = min(_TAMANO - 1, x + 1)
        elif accion == "ACTION2":
            y = min(_TAMANO - 1, y + 1)
        elif accion == "ACTION3":
            x = max(0, x - 1)
        elif accion == "ACTION4":
            y = max(0, y - 1)
        tracker.observe(accion, pre, _frame(x, y, i + 1, hud))


def test_sin_evidencia_suficiente_no_enmascara_nada() -> None:
    """Comportamiento previo a BL.21558: ante la duda, se compara todo."""
    tracker = VolatilityTracker()
    _correr(tracker, VOLATILITY_MIN_TRANSITIONS - 1, hud=True)
    assert tracker.mask is None
    assert tracker.volatile_cell_count() == 0


def test_aprende_exactamente_las_celdas_del_hud_y_ninguna_del_tablero() -> None:
    tracker = VolatilityTracker()
    _correr(tracker, 40, hud=True)

    mask = tracker.mask
    assert mask is not None
    assert mask[_FILA_HUD][0] is True
    assert mask[_FILA_HUD][1] is True
    assert tracker.volatile_cell_count() == 2

    for y in range(_TAMANO):
        for x in range(_TAMANO):
            assert mask[y][x] is False, f"celda de tablero ({x},{y}) enmascarada"
    for x in range(2, _TAMANO):
        assert mask[_FILA_HUD][x] is False


def test_sin_hud_no_inventa_volatilidad() -> None:
    tracker = VolatilityTracker()
    _correr(tracker, 40, hud=False)
    assert tracker.mask is None


def test_una_sola_accion_nunca_alcanza() -> None:
    """No se puede distinguir "cambia siempre" de "esta accion la cambia siempre"."""
    tracker = VolatilityTracker()
    for i in range(20):
        tracker.observe("ACTION1", [[i % 10, 3]], [[(i + 1) % 10, 3]])
    assert tracker.mask is None


def test_una_celda_que_cambia_bajo_todas_las_acciones_si_entra() -> None:
    tracker = VolatilityTracker()
    for i in range(20):
        accion = "ACTION1" if i % 2 == 0 else "ACTION2"
        tracker.observe(accion, [[i % 10, 3]], [[(i + 1) % 10, 3]])
    mask = tracker.mask
    assert mask is not None
    assert mask[0][0] is True
    assert mask[0][1] is False  # la celda constante queda comparable


def test_fail_safe_si_lo_volatil_superara_medio_frame() -> None:
    """Un frame que muta entero pase lo que pase no es un HUD ruidoso: no es observable con este
    modelo, y enmascararlo dejaria al agente decidiendo sobre nada."""
    tracker = VolatilityTracker()
    for i in range(20):
        accion = "ACTION1" if i % 2 == 0 else "ACTION2"
        tracker.observe(accion, [[i % 10, i % 7]], [[(i + 1) % 10, (i + 1) % 7]])
    assert tracker.mask is None
    assert tracker.volatile_cell_count() == 0


def test_la_version_solo_cambia_cuando_cambia_el_conjunto_volatil() -> None:
    tracker = VolatilityTracker()
    _correr(tracker, 40, hud=True)
    version = tracker.version
    assert version > 0
    _correr(tracker, 20, hud=True)
    assert tracker.version == version


def test_tolera_grillas_que_cambian_de_forma() -> None:
    tracker = VolatilityTracker()
    tracker.observe("ACTION1", [[1]], [[1, 2]])
    tracker.observe("ACTION2", [[1, 2], [3, 4]], [[9]])
    tracker.observe("ACTION1", [], [])
    assert tracker.mask is None or tracker.volatile_cell_count() >= 0


# ── Comparacion / hash enmascarados ───────────────────────────────────────────────────────────


def test_dos_frames_que_solo_difieren_en_el_hud_son_el_mismo_estado() -> None:
    antes = [[1, 2, 3], [4, 5, 6], [7, 0, 0]]
    despues = [[1, 2, 3], [4, 5, 6], [7, 4, 9]]
    # Este es el nucleo del BL: sin mascara `grids_equal` no da True nunca.
    assert grids_equal(antes, despues) is False
    assert grids_equal_masked(antes, despues, _MASCARA_PARIDAD) is True
    assert is_no_op_transition(antes, despues) is False
    assert is_no_op_transition(antes, despues, _MASCARA_PARIDAD) is True


def test_un_cambio_en_celda_estable_sigue_siendo_cambio_de_estado() -> None:
    antes = [[1, 2, 3], [4, 5, 6], [7, 0, 0]]
    despues = [[1, 2, 3], [4, 9, 6], [7, 4, 9]]
    assert grids_equal_masked(antes, despues, _MASCARA_PARIDAD) is False


def test_un_cambio_de_forma_nunca_es_ruido_de_hud() -> None:
    assert grids_equal_masked([[1, 2]], [[1, 2, 3]], [[True, True, True]]) is False
    assert grids_equal_masked([[1]], [[1], [1]], [[True], [True]]) is False


def test_hash_sin_mascara_reproduce_hash_grid() -> None:
    assert hash_grid_masked(_GRILLA_PARIDAD, None) == hash_grid(_GRILLA_PARIDAD)


def test_hash_colapsa_el_contenido_volatil() -> None:
    a = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    b = [[1, 2, 3], [4, 5, 6], [7, 0, 1]]
    assert hash_grid(a) != hash_grid(b)
    assert hash_grid_masked(a, _MASCARA_PARIDAD) == hash_grid_masked(b, _MASCARA_PARIDAD)


def test_el_placeholder_no_colisiona_con_ningun_color_real() -> None:
    """Si el relleno de una celda volatil fuera un color legitimo (0-15), una grilla enmascarada
    podria hashear igual que otra que ahi tiene ese color de verdad."""
    for color in range(16):
        assert hash_grid_masked([[0, 0]], [[True, True]]) != hash_grid([[color, color]])


def test_paridad_de_hash_y_firma_con_el_motor_typescript() -> None:
    assert hash_grid(_GRILLA_PARIDAD) == _HASH_SIN_MASCARA
    assert hash_grid_masked(_GRILLA_PARIDAD, _MASCARA_PARIDAD) == _HASH_CON_MASCARA
    assert (
        compute_state_signature(_GRILLA_PARIDAD, [1, 2, 6], _MASCARA_PARIDAD)
        == _FIRMA_CON_MASCARA
    )


def test_firma_sin_mascara_es_exactamente_la_historica() -> None:
    assert compute_state_signature(_GRILLA_PARIDAD, [1, 2, 6], None) == compute_state_signature(
        _GRILLA_PARIDAD, [1, 2, 6]
    )


def test_las_acciones_disponibles_siguen_distinguiendo_estados() -> None:
    mask = [[True, True]]
    assert compute_state_signature([[1, 2]], [1], mask) != compute_state_signature(
        [[1, 2]], [1, 2], mask
    )


def test_neutralize_copia_el_pre_en_las_celdas_volatiles() -> None:
    pre = [[1, 2, 3], [4, 5, 6], [7, 0, 0]]
    post = [[1, 2, 3], [4, 9, 6], [7, 4, 8]]
    assert neutralize_volatile_cells(pre, post, _MASCARA_PARIDAD) == [
        [1, 2, 3],
        [4, 9, 6],  # el cambio real del tablero se conserva
        [7, 0, 0],  # el HUD queda igual al de `pre`
    ]


def test_neutralize_sin_mascara_devuelve_un_clon() -> None:
    post = [[1, 2]]
    resultado = neutralize_volatile_cells([[0, 0]], post, None)
    assert resultado == post
    assert resultado is not post
    assert resultado[0] is not post[0]


def test_neutralize_conserva_celdas_sin_equivalente_en_el_pre() -> None:
    assert neutralize_volatile_cells([[1]], [[1, 7]], [[True, True]]) == [[1, 7]]


# --- Familia 2 del criterio: la BARRA DE PROGRESO -----------------------------------------------
# Existe porque la familia 1, medida contra frames REALES de ARC-AGI-3, enmascaraba CERO celdas en
# los cuatro juegos del BL: el ruido real es una barra que avanza una celda por paso, y cada celda
# suya cambia una sola vez por vuelta. Los casos negativos son la mitad importante -- enmascarar
# tablero deja al agente ciego. Espejo de los tests homonimos de
# arc-agi-runner/src/worldModel/__tests__/volatilityMask.test.ts.
_BARRA_ANCHO = 24
_BARRA_ALTO = 4


def _con_barra(hasta: int, marcador: tuple[int, int] | None = None) -> list[list[int]]:
    grilla = [[0] * _BARRA_ANCHO for _ in range(_BARRA_ALTO)]
    for x in range(hasta):
        grilla[0][x] = 1
    if marcador is not None:
        grilla[marcador[0]][marcador[1]] = 5
    return grilla


def test_una_barra_que_avanza_una_celda_por_paso_entra_a_la_mascara() -> None:
    tracker = VolatilityTracker()
    for i in range(_BARRA_ANCHO):
        accion = f"ACTION{(i % 3) + 1}"
        tracker.observe(accion, _con_barra(i, (2, 3)), _con_barra(i + 1, (2, 3)))

    mask = tracker.mask
    assert mask is not None
    assert tracker.volatile_cell_count() == _BARRA_ANCHO
    assert all(mask[0][x] for x in range(_BARRA_ANCHO))
    # Ni una celda fuera de la barra: el marcador quieto y el fondo siguen siendo comparables.
    for y in range(1, _BARRA_ALTO):
        assert not any(mask[y][x] for x in range(_BARRA_ANCHO))


def test_un_objeto_que_se_mueve_nunca_entra() -> None:
    # El falso positivo mas caro: dos celdas ADYACENTES cambian juntas (de donde sale y a donde
    # llega), asi que ningun cambio ocurre en soledad y la region nunca califica.
    tracker = VolatilityTracker()
    for i in range(_BARRA_ANCHO):
        accion = f"ACTION{(i % 3) + 1}"
        columna = i % (_BARRA_ANCHO - 1)
        tracker.observe(accion, _con_barra(0, (2, columna)), _con_barra(0, (2, columna + 1)))
    assert tracker.mask is None


def test_una_region_2d_que_se_enciende_de_a_una_celda_no_entra() -> None:
    # Caso "simon dice": cada cambio ocurre en soledad, pero la forma delata que no es una barra.
    tracker = VolatilityTracker()
    encendidas = [(y, x) for y in range(5) for x in range(5)]

    def con_bloque(n: int) -> list[list[int]]:
        grilla = [[0] * 8 for _ in range(8)]
        for y, x in encendidas[:n]:
            grilla[y][x] = 3
        return grilla

    for i in range(len(encendidas)):
        tracker.observe(f"ACTION{(i % 3) + 1}", con_bloque(i), con_bloque(i + 1))
    assert tracker.mask is None


def test_una_barra_demasiado_corta_no_entra() -> None:
    tracker = VolatilityTracker()

    def corta(hasta: int) -> list[list[int]]:
        grilla = [[0] * _BARRA_ANCHO for _ in range(_BARRA_ALTO)]
        for x in range(hasta):
            grilla[0][x] = 1
        return grilla

    for i in range(10):
        tracker.observe(f"ACTION{(i % 3) + 1}", corta(i), corta(i + 1))
    assert tracker.mask is None


def test_una_sola_accion_no_alcanza_tampoco_para_la_barra() -> None:
    tracker = VolatilityTracker()
    for i in range(_BARRA_ANCHO):
        tracker.observe("ACTION1", _con_barra(i), _con_barra(i + 1))
    assert tracker.mask is None


def test_la_barra_sobrevive_a_una_racha_sin_avanzar() -> None:
    tracker = VolatilityTracker()
    for i in range(_BARRA_ANCHO):
        tracker.observe(f"ACTION{(i % 3) + 1}", _con_barra(i, (2, 3)), _con_barra(i + 1, (2, 3)))
    assert tracker.volatile_cell_count() == _BARRA_ANCHO
    version_estable = tracker.version

    # Mientras el ratio siga por encima de SWEEP_EXIT_RATIO la mascara NO se mueve: si oscilara,
    # las firmas volverian a ser irrepetibles, que es el defecto que este modulo existe para
    # arreglar.
    for i in range(20):
        tracker.observe(
            f"ACTION{(i % 3) + 1}",
            _con_barra(_BARRA_ANCHO, (2, 3)),
            _con_barra(_BARRA_ANCHO, (2, 3)),
        )
    assert tracker.volatile_cell_count() == _BARRA_ANCHO
    assert tracker.version == version_estable
