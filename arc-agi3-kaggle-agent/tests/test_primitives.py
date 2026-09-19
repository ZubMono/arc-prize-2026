"""[arc-agi3-kaggle-agent/tests] -- tests de los generadores de candidatos DATA-DRIVEN de
arc_agent/world_model/primitives.py (propose_all_steps y los diez propose_* que concatena). La
mitad CIEGA del modulo (enumerate_structural_steps), las invariantes sobre corpus aleatorio y los
re-exports viven en test_primitives_structural.py -- se separaron por responsabilidad.

Porta los casos de arc-agi-runner/src/worldModel/__tests__/primitives.test.ts (fuente canonica) y
agrega los casos borde propios de Python -- sobre todo INDICES NEGATIVOS, donde el TS lee
`undefined` (inofensivo) y Python envolveria la grilla leyendo desde el final en silencio.

El grueso de las aserciones es sobre el ORDEN de las propuestas, no solo sobre su contenido: aguas
arriba synthesis.py rankea con desempate determinista y consume esta enumeracion tal cual sale, asi
que un reordenamiento silencioso cambiaria que programa aprende el agente sin romper nada visible.
"""
from __future__ import annotations

from arc_agent.world_model.grid import Grid
from arc_agent.world_model.primitives import (
    EMPTY_CONTEXT,
    PrimitiveContext,
    apply_step,
    propose_all_steps,
)


def _names(steps: list[dict]) -> list[str]:
    return [step["name"] for step in steps]


# --- propose_all_steps -- casos portados de primitives.test.ts ----------------


def test_propone_translate_cuando_el_foreground_se_desplazo() -> None:
    pre: Grid = [[0, 5, 0], [0, 0, 0]]
    post: Grid = [[0, 0, 5], [0, 0, 0]]
    proposals = propose_all_steps(pre, post)
    assert {"name": "translate", "params": {"dx": 1, "dy": 0}} in proposals


def test_toda_propuesta_explica_post_exactamente_al_aplicarse_sobre_pre() -> None:
    pares: list[tuple[Grid, Grid]] = [
        ([[0, 5, 0], [0, 0, 0]], [[0, 0, 5], [0, 0, 0]]),
        ([[1, 2, 1]], [[9, 2, 9]]),
        ([[1, 1, 0], [1, 0, 0]], [[7, 7, 0], [7, 0, 0]]),
        ([[1, 2], [2, 1]], [[2, 1], [1, 2]]),
        ([[1, 2]], [[1, 2, 1, 2], [1, 2, 1, 2]]),
        ([[0, 0, 0], [0, 5, 0], [0, 0, 0]], [[5]]),
    ]
    for pre, post in pares:
        proposals = propose_all_steps(pre, post)
        assert proposals, f"se esperaba al menos una propuesta para {pre} -> {post}"
        for step in proposals:
            assert apply_step(step, pre, EMPTY_CONTEXT) == post


def test_propone_recolor_con_mapping_consistente_celda_a_celda() -> None:
    proposals = propose_all_steps([[1, 2, 1]], [[9, 2, 9]])
    assert {"name": "recolor", "params": {"mapping": {1: 9}}} in proposals


def test_no_propone_recolor_si_un_origen_mapea_a_dos_destinos() -> None:
    proposals = propose_all_steps([[1, 1]], [[9, 8]])
    assert "recolor" not in _names(proposals)
    # Ningun primitivo del DSL explica ese par: la lista completa queda vacia.
    assert proposals == []


def test_propone_flood_fill_cuando_el_cambio_es_una_region_4_conexa_completa() -> None:
    pre: Grid = [[1, 1, 0], [1, 0, 0]]
    post: Grid = [[7, 7, 0], [7, 0, 0]]
    proposals = propose_all_steps(pre, post)
    assert "floodFill" in _names(proposals)


def test_devuelve_lista_vacia_si_pre_y_post_son_identicos() -> None:
    grid: Grid = [[1, 2]]
    assert propose_all_steps(grid, grid) == []
    # Tambien con dos objetos distintos de igual contenido (el corte es por VALOR, no por
    # identidad de objeto): si comparara referencias, un post reconstruido no se detectaria.
    assert propose_all_steps(grid, [[1, 2]]) == []


# --- propose_all_steps -- orden normativo de enumeracion ---------------------


def test_orden_normativo_translate_reflect_rotate_recolor() -> None:
    # Una columna de 2 celdas que se invierte admite CUATRO explicaciones distintas de un paso;
    # el orden en que salen es el contrato con synthesis.py.
    pre: Grid = [[0], [5]]
    post: Grid = [[5], [0]]
    proposals = propose_all_steps(pre, post)
    assert _names(proposals) == ["translate", "reflect", "rotate", "recolor"]
    assert proposals[0]["params"] == {"dx": 0, "dy": -1}
    assert proposals[1]["params"] == {"axis": "vertical"}
    assert proposals[2]["params"] == {"quarterTurns": 2}
    assert proposals[3]["params"] == {"mapping": {0: 5, 5: 0}}


def test_orden_normativo_recolor_flood_fill_conditional_recolor() -> None:
    pre: Grid = [[1, 1], [1, 1]]
    post: Grid = [[9, 9], [9, 9]]
    proposals = propose_all_steps(pre, post)
    assert _names(proposals) == ["recolor", "floodFill", "conditionalRecolor", "conditionalRecolor"]
    assert proposals[0]["params"] == {"mapping": {1: 9}}
    assert proposals[1]["params"] == {"x": 0, "y": 0, "to": 9}
    # Predicados en orden "all" -> "border" -> "interior"; "interior" no aplica en una 2x2 (todas
    # las celdas tocan el borde de la grilla).
    assert proposals[2]["params"] == {"from": 1, "to": 9, "predicate": "all"}
    assert proposals[3]["params"] == {"from": 1, "to": 9, "predicate": "border"}


def test_orden_normativo_reflect_y_rotate_enumeran_sus_variantes_en_orden() -> None:
    # Grilla anti-simetrica 2x2: los dos ejes de reflect y dos de los tres giros explican el par.
    pre: Grid = [[1, 2], [2, 1]]
    post: Grid = [[2, 1], [1, 2]]
    proposals = propose_all_steps(pre, post)
    assert _names(proposals) == ["reflect", "reflect", "rotate", "rotate", "recolor"]
    assert [p["params"] for p in proposals[:4]] == [
        {"axis": "horizontal"},
        {"axis": "vertical"},
        {"quarterTurns": 1},
        {"quarterTurns": 3},
    ]


def test_orden_normativo_crop_to_bbox_antes_que_object_extract() -> None:
    pre: Grid = [[0, 0, 0], [0, 5, 0], [0, 0, 0]]
    post: Grid = [[5]]
    proposals = propose_all_steps(pre, post)
    assert _names(proposals) == ["cropToBBox", "objectExtract", "objectExtract"]
    assert proposals[0]["params"] == {"backgroundColor": 0}
    # Candidato mas GENERAL primero (sin color) y despues los especificos, ascendente por color.
    assert proposals[1]["params"] == {}
    assert proposals[2]["params"] == {"color": 5}


def test_object_extract_sin_color_omite_la_clave_en_vez_de_ponerla_en_none() -> None:
    # {"color": None} seria un JSON distinto de {} y romperia la clave canonica del programa.
    proposals = propose_all_steps([[0, 0, 0], [0, 5, 0], [0, 0, 0]], [[5]])
    generico = [s for s in proposals if s["name"] == "objectExtract"][0]
    assert "color" not in generico["params"]


# --- floodFill -- la region tiene que ser EXACTAMENTE el diff ----------------


def test_no_propone_flood_fill_si_el_diff_es_solo_una_parte_de_la_region() -> None:
    pre: Grid = [[1, 1], [0, 0]]
    post: Grid = [[7, 1], [0, 0]]
    proposals = propose_all_steps(pre, post)
    assert "floodFill" not in _names(proposals)
    # Nada mas lo explica tampoco: un recolor global contradiria la celda (1,0), que no cambio.
    assert proposals == []


def test_no_propone_flood_fill_ni_conditional_recolor_con_dos_colores_de_origen() -> None:
    # Dos colores de origen distintos colapsando al mismo destino: ni floodFill (pinta UNA region
    # de UN color) ni conditionalRecolor (filtra por UN `from`) saben expresar eso. recolor si.
    proposals = propose_all_steps([[1, 0, 2]], [[7, 0, 7]])
    assert _names(proposals) == ["recolor"]
    assert proposals[0]["params"] == {"mapping": {1: 7, 2: 7}}


def test_no_propone_flood_fill_si_el_diff_son_dos_blobs_disconexos_del_mismo_color() -> None:
    pre: Grid = [[1, 0, 1]]
    post: Grid = [[7, 0, 7]]
    proposals = propose_all_steps(pre, post)
    assert "floodFill" not in _names(proposals)
    # recolor SI lo explica -- el par es real, lo que no es cierto es que sea un flood fill.
    assert "recolor" in _names(proposals)


def test_la_semilla_de_flood_fill_es_la_primera_celda_en_row_major() -> None:
    pre: Grid = [[0, 1, 1], [1, 1, 0]]
    post: Grid = [[0, 7, 7], [7, 7, 0]]
    proposals = propose_all_steps(pre, post)
    flood = [s for s in proposals if s["name"] == "floodFill"]
    assert len(flood) == 1
    # (1,0) es la primera celda que cambio recorriendo y externo / x interno -- NO la esquina del
    # bounding box ni la primera celda de la region en orden de descubrimiento del DFS.
    assert flood[0]["params"] == {"x": 1, "y": 0, "to": 7}


def test_la_region_de_flood_fill_no_envuelve_la_grilla_por_indices_negativos() -> None:
    # La semilla esta en (0,0): el DFS empuja (-1,0) y (0,-1). Con indices negativos sin guarda,
    # Python leeria la ULTIMA fila/columna y la region se contaminaria con celdas del extremo
    # opuesto, inflando su tamano y haciendo que la propuesta se descarte (o peor, que pinte de
    # mas). El color 1 aparece a proposito tambien en el extremo opuesto.
    pre: Grid = [[1, 1, 0], [1, 0, 1]]
    post: Grid = [[7, 7, 0], [7, 0, 1]]
    proposals = propose_all_steps(pre, post)
    flood = [s for s in proposals if s["name"] == "floodFill"]
    assert len(flood) == 1
    assert flood[0]["params"] == {"x": 0, "y": 0, "to": 7}
    assert apply_step(flood[0], pre, EMPTY_CONTEXT) == post


# --- translate con desplazamientos negativos --------------------------------


def test_propone_translate_negativo_en_x_sin_envolver_la_grilla() -> None:
    pre: Grid = [[0, 0, 5]]
    post: Grid = [[0, 5, 0]]
    proposals = propose_all_steps(pre, post)
    assert proposals == [{"name": "translate", "params": {"dx": -1, "dy": 0}}]
    assert apply_step(proposals[0], pre, EMPTY_CONTEXT) == post


def test_no_propone_translate_cuando_el_foreground_cambio_de_forma() -> None:
    # Mismo desplazamiento aparente del bbox pero distinto tamano: no es una traslacion.
    pre: Grid = [[0, 5, 0, 0]]
    post: Grid = [[0, 0, 5, 5]]
    assert "translate" not in _names(propose_all_steps(pre, post))


def test_no_propone_translate_cuando_no_hay_foreground() -> None:
    # Grilla uniforme: no hay bounding box de foreground contra el cual medir un desplazamiento.
    assert "translate" not in _names(propose_all_steps([[3, 3]], [[4, 4]]))


def test_no_propone_translate_cuando_el_post_se_quedo_sin_foreground() -> None:
    # El foreground de `pre` desaparecio (post entero del color de fondo de pre): el bbox del post
    # es None y no hay desplazamiento que medir. Los proposers de color SI explican el par.
    pre: Grid = [[0, 5], [0, 0]]
    post: Grid = [[0, 0], [0, 0]]
    proposals = propose_all_steps(pre, post)
    assert "translate" not in _names(proposals)
    assert _names(proposals) == ["recolor", "floodFill", "conditionalRecolor", "conditionalRecolor"]


# --- overlay -- unico proposer que depende del contexto ---------------------


def test_no_propone_overlay_sin_grilla_ancla() -> None:
    pre: Grid = [[0, 3], [0, 0]]
    post: Grid = [[1, 3], [1, 1]]
    assert "overlay" not in _names(propose_all_steps(pre, post))
    # El default de `ctx` es None y se resuelve a EMPTY_CONTEXT: ambas llamadas son equivalentes.
    assert propose_all_steps(pre, post) == propose_all_steps(pre, post, EMPTY_CONTEXT)


def test_propone_overlay_con_ancla_y_en_su_posicion_del_orden() -> None:
    pre: Grid = [[0, 3], [0, 0]]
    post: Grid = [[1, 3], [1, 1]]
    ctx = PrimitiveContext(anchor_grid=[[1, 1], [1, 1]])
    proposals = propose_all_steps(pre, post, ctx)
    # overlay va en la posicion 7 del orden canonico: despues de cropToBBox, antes de replicate.
    assert _names(proposals) == [
        "recolor",
        "floodFill",
        "overlay",
        "conditionalRecolor",
        "conditionalRecolor",
    ]
    assert proposals[2] == {"name": "overlay", "params": {}}
    for step in proposals:
        assert apply_step(step, pre, ctx) == post


def test_propone_overlay_con_un_ancla_mas_chica_que_la_grilla() -> None:
    # El ancla puede ser mas chica que la grilla (`anchor[y]?.[x] ?? cell` del TS): las celdas de
    # fondo sin cobertura del ancla se quedan como estaban, no se leen fuera de rango ni envuelven.
    pre: Grid = [[0, 3], [0, 0]]
    post: Grid = [[1, 3], [0, 0]]
    ctx = PrimitiveContext(anchor_grid=[[1]])
    proposals = propose_all_steps(pre, post, ctx)
    assert proposals == [{"name": "overlay", "params": {}}]


# --- replicate --------------------------------------------------------------


def test_propone_replicate_cuando_post_es_un_tileo_exacto_de_pre() -> None:
    pre: Grid = [[1, 2]]
    post: Grid = [[1, 2, 1, 2], [1, 2, 1, 2]]
    proposals = propose_all_steps(pre, post)
    assert {"name": "replicate", "params": {"timesX": 2, "timesY": 2}} in proposals


def test_replicate_acepta_factor_6_y_descarta_7() -> None:
    pre: Grid = [[1]]
    assert _names(propose_all_steps(pre, [[1]] * 6)) == ["replicate"]
    # 7 tileos ya no es una regla de tileo plausible sino una coincidencia numerica.
    assert propose_all_steps(pre, [[1]] * 7) == []


def test_no_propone_replicate_cuando_las_dimensiones_no_son_multiplos() -> None:
    assert "replicate" not in _names(propose_all_steps([[1, 2]], [[1, 2, 1]]))


def test_replicate_de_factor_cero_explica_un_post_vacio_igual_que_el_ts() -> None:
    # Paridad deliberada con una rareza del TS, verificada contra el motor canonico: un `post`
    # vacio divide exacto (0 % preH == 0), da timesX=timesY=0 y el tileo de factor 0 produce []
    # -- asi que la propuesta se AUTO-VERIFICA y sale. No "arreglarlo": el port replica la
    # semantica del TS, y filtrarlo aca haria divergir la sintesis del lado Python.
    assert propose_all_steps([[1]], []) == [
        {"name": "replicate", "params": {"timesX": 0, "timesY": 0}}
    ]


# --- conditionalRecolor -----------------------------------------------------


def test_conditional_recolor_enumera_los_predicados_en_orden_all_border_interior() -> None:
    # 5x5 de color 5 con el interior 3x3 recoloreado: solo "interior" explica el par.
    pre: Grid = [[5] * 5 for _ in range(5)]
    post: Grid = [row[:] for row in pre]
    for y in range(1, 4):
        for x in range(1, 4):
            post[y][x] = 9
    proposals = propose_all_steps(pre, post)
    condicionales = [s for s in proposals if s["name"] == "conditionalRecolor"]
    assert [s["params"]["predicate"] for s in condicionales] == ["interior"]
    assert condicionales[0]["params"] == {"from": 5, "to": 9, "predicate": "interior"}


def test_no_propone_conditional_recolor_con_dos_colores_de_destino() -> None:
    assert "conditionalRecolor" not in _names(propose_all_steps([[1, 1]], [[9, 8]]))


# --- formas incompatibles y grillas degeneradas (no deben lanzar) -----------


def test_formas_incompatibles_no_lanzan_y_no_proponen_pasos_locales() -> None:
    # Distinta cantidad de filas: ningun proposer celda-a-celda puede pronunciarse.
    proposals = propose_all_steps([[1, 2]], [[1, 2], [1, 2], [1, 2]])
    assert "recolor" not in _names(proposals)
    assert "floodFill" not in _names(proposals)
    assert "conditionalRecolor" not in _names(proposals)


def test_filas_de_distinto_ancho_con_igual_cantidad_de_filas_tampoco_proponen() -> None:
    # Mismo alto pero una fila mas ancha: los proposers celda-a-celda (recolor, floodFill,
    # conditionalRecolor) cortan al comparar el ancho de ESA fila, no solo el de la fila 0. Sin ese
    # chequeo Python lanzaria IndexError donde el TS lee `undefined`.
    #
    # ALCANCE de esta asercion: cubre la guarda del camino de diff, NO una promesa general de que
    # toda grilla irregular sea segura. La rectangularidad es un INVARIANTE del world model
    # (contrato 0.2: las grillas irregulares son comportamiento indefinido y no se validan por
    # celda, porque el costo caeria en el camino caliente de la BFS). En la practica el invariante
    # se cumple siempre: la grilla entra por state_signature.extract_grid desde un frame
    # rectangular de la API, y todo primitivo del DSL emite grillas rectangulares (afirmado en
    # test_primitives_structural.py). Un par irregular con la MISMA forma en pre y post pasa esta
    # guarda y termina dentro de apply_step, que es donde vive el comportamiento indefinido.
    proposals = propose_all_steps([[1, 2], [3, 4]], [[1, 2, 5], [3, 4]])
    assert proposals == []


def test_grilla_vacia_y_filas_vacias_no_lanzan() -> None:
    assert propose_all_steps([], []) == []
    assert propose_all_steps([[], []], [[], []]) == []
    assert propose_all_steps([], [[1]]) == []
    assert propose_all_steps([[], []], [[1], [2]]) == []


def test_propose_all_steps_no_muta_sus_entradas() -> None:
    pre: Grid = [[1, 1, 0], [1, 0, 0]]
    post: Grid = [[7, 7, 0], [7, 0, 0]]
    pre_copia = [row[:] for row in pre]
    post_copia = [row[:] for row in post]
    propose_all_steps(pre, post)
    assert pre == pre_copia
    assert post == post_copia


def test_cada_llamada_devuelve_pasos_frescos_no_compartidos() -> None:
    # Los pasos son dicts mutables: si se compartieran entre llamadas, un consumidor que edite un
    # params contaminaria la enumeracion de la siguiente busqueda.
    pre: Grid = [[1, 2, 1]]
    post: Grid = [[9, 2, 9]]
    primera = propose_all_steps(pre, post)
    primera[0]["params"]["mapping"] = {7: 7}
    assert propose_all_steps(pre, post)[0]["params"] == {"mapping": {1: 9}}
