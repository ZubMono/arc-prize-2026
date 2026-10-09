"""[arc-agi3-kaggle-agent/tests/world_model/grid] -- utilidades puras sobre grillas ARC. Porta
los casos de arc-agi-runner/src/worldModel/__tests__/grid.test.ts y agrega los bordes propios de
Python (indices negativos, grilla de filas vacias, rango sin signo del hash).

Los vectores de PARIDAD (hashes, bbox, cell_diff) se generaron ejecutando el TS canonico con
`node_modules/.bin/tsx` sobre projects/arc-agi-runner/src/worldModel/grid.ts: son el valor que
produce la implementacion de referencia, no un valor recalculado desde el Python."""
from __future__ import annotations

import pytest

from arc_agent.world_model.grid import (
    BoundingBox,
    FNV_OFFSET_BASIS,
    GridDimensions,
    cell_diff_count,
    clone_grid,
    detect_background_color,
    foreground_bounding_box,
    grid_dimensions,
    grids_equal,
    hash_grid,
)

# Valor exacto que devuelve hashGrid() del TS para cada grilla (paridad bit a bit).
HASH_PARITY = [
    ([], 2166136261),
    ([[]], 2047574606),
    ([[], []], 3508452515),
    ([[0]], 3531065248),
    ([[1, 2]], 1120868399),
    ([[2, 1]], 2306690953),
    ([[1], [2]], 2145893098),
    ([[1, 2], [3, 4]], 2802852909),
    ([[0, 0, 0], [0, 5, 0], [0, 0, 0]], 2996678767),
    ([[15, 15], [15, 15]], 1106335151),
]


class TestCloneGrid:
    def test_copia_profunda_independiente_de_filas(self) -> None:
        original = [[1, 2], [3, 4]]
        clone = clone_grid(original)
        clone[0][0] = 99
        assert original[0][0] == 1
        assert clone == [[99, 2], [3, 4]]

    def test_grilla_vacia(self) -> None:
        assert clone_grid([]) == []


class TestGridDimensions:
    def test_devuelve_height_width_correctos(self) -> None:
        assert grid_dimensions([[1, 2, 3], [4, 5, 6]]) == GridDimensions(width=3, height=2)

    def test_width_cero_en_grilla_vacia(self) -> None:
        assert grid_dimensions([]) == GridDimensions(width=0, height=0)

    def test_filas_vacias_dan_area_cero_con_alto_real(self) -> None:
        dims = grid_dimensions([[], []])
        assert (dims.width, dims.height) == (0, 2)

    def test_orden_posicional_es_width_height(self) -> None:
        # El orden de campos es load-bearing: coincide con la declaracion del tipo TS.
        assert tuple(grid_dimensions([[1, 2, 3]])) == (3, 1)


class TestGridsEqual:
    def test_true_para_grillas_identicas(self) -> None:
        assert grids_equal([[1, 2], [3, 4]], [[1, 2], [3, 4]]) is True

    def test_false_si_una_celda_difiere(self) -> None:
        assert grids_equal([[1, 2], [3, 4]], [[1, 2], [3, 9]]) is False

    def test_false_si_difiere_el_alto(self) -> None:
        assert grids_equal([[1, 2]], [[1, 2], [3, 4]]) is False

    def test_false_si_difiere_el_ancho_de_una_fila(self) -> None:
        assert grids_equal([[1, 2]], [[1, 2, 3]]) is False

    def test_grillas_irregulares_devuelven_false_sin_lanzar(self) -> None:
        # El TS compara fila a fila y devuelve false; nunca excepcion.
        assert grids_equal([[1, 2], [3]], [[1, 2], [3, 4]]) is False

    def test_true_para_grillas_vacias(self) -> None:
        assert grids_equal([], []) is True


class TestCellDiffCount:
    def test_cero_para_grillas_identicas(self) -> None:
        assert cell_diff_count([[1, 2]], [[1, 2]]) == 0

    def test_cuenta_celdas_distintas(self) -> None:
        assert cell_diff_count([[1, 2, 3]], [[1, 9, 9]]) == 2

    def test_penaliza_celdas_fuera_de_la_interseccion(self) -> None:
        assert cell_diff_count([[1, 1]], [[1, 1, 1]]) == 1

    def test_penaliza_filas_faltantes(self) -> None:
        assert cell_diff_count([[1, 1]], [[1, 1], [2, 2]]) == 2

    def test_es_simetrico(self) -> None:
        assert cell_diff_count([[1, 1, 1]], [[1, 1]]) == 1

    def test_filas_irregulares_cuentan_por_celda_ausente(self) -> None:
        # Cada lado tiene una fila mas corta que el otro: 1 celda ausente por fila.
        assert cell_diff_count([[1], [2, 2]], [[1, 1], [2]]) == 2

    def test_dos_ausencias_enfrentadas_no_cuentan_como_diferencia(self) -> None:
        # El centinela -1 se compara contra si mismo: dos huecos alineados son "iguales", igual
        # que los dos `undefined` del TS.
        assert cell_diff_count([[1], []], [[1], []]) == 0


class TestDetectBackgroundColor:
    def test_elige_el_color_mas_frecuente(self) -> None:
        assert detect_background_color([[0, 0, 0], [0, 5, 0], [0, 0, 0]]) == 0

    def test_desempata_por_menor_indice_de_color(self) -> None:
        assert detect_background_color([[1, 1], [2, 2]]) == 1

    def test_desempata_por_menor_indice_aunque_aparezca_despues(self) -> None:
        # El color 9 se ve primero en row-major, pero el empate lo gana el indice mas bajo.
        assert detect_background_color([[9, 9], [3, 3]]) == 3

    def test_grilla_vacia_devuelve_cero(self) -> None:
        assert detect_background_color([]) == 0

    def test_filas_vacias_devuelven_cero(self) -> None:
        assert detect_background_color([[], []]) == 0


class TestForegroundBoundingBox:
    def test_none_en_grilla_uniforme(self) -> None:
        assert foreground_bounding_box([[0, 0], [0, 0]], 0) is None

    def test_none_en_grilla_vacia(self) -> None:
        assert foreground_bounding_box([], 0) is None

    def test_calcula_el_bbox_de_las_celdas_distintas_del_fondo(self) -> None:
        grid = [[0, 0, 0, 0], [0, 5, 5, 0], [0, 0, 0, 0]]
        assert foreground_bounding_box(grid, 0) == BoundingBox(
            min_x=1, min_y=1, max_x=2, max_y=1
        )

    def test_bbox_cubre_la_grilla_entera_si_no_hay_fondo(self) -> None:
        assert foreground_bounding_box([[1, 2], [3, 4]], 0) == BoundingBox(
            min_x=0, min_y=0, max_x=1, max_y=1
        )

    def test_celda_unica(self) -> None:
        assert foreground_bounding_box([[0, 0], [0, 7]], 0) == BoundingBox(
            min_x=1, min_y=1, max_x=1, max_y=1
        )


class TestHashGrid:
    def test_es_deterministico(self) -> None:
        assert hash_grid([[1, 2], [3, 4]]) == hash_grid([[1, 2], [3, 4]])

    def test_distingue_contenido_distinto(self) -> None:
        assert hash_grid([[1, 2]]) != hash_grid([[2, 1]])

    def test_distingue_misma_celda_con_distinta_forma_de_filas(self) -> None:
        # [[1],[2]] vs [[1,2]] no deben colisionar solo por concatenar valores.
        assert hash_grid([[1], [2]]) != hash_grid([[1, 2]])

    def test_grilla_vacia_es_el_offset_basis_fnv(self) -> None:
        assert hash_grid([]) == FNV_OFFSET_BASIS

    @pytest.mark.parametrize("grid,expected", HASH_PARITY)
    def test_paridad_bit_a_bit_con_el_typescript(self, grid, expected) -> None:
        assert hash_grid(grid) == expected

    @pytest.mark.parametrize("grid,_expected", HASH_PARITY)
    def test_siempre_entero_sin_signo_de_32_bits(self, grid, _expected) -> None:
        # Python tiene enteros de precision arbitraria: sin la mascara de 32 bits el hash
        # divergiria del TS al primer overflow.
        value = hash_grid(grid)
        assert isinstance(value, int)
        assert 0 <= value < 2**32
