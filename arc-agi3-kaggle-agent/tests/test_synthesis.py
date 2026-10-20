"""[arc-agi3-kaggle-agent/tests/synthesis] -- sintesis bottom-up de programas DSL: busqueda acotada
(profundidad <=3-4), verificacion contra TODOS los pares observados, y ranking por prior de Occam
(longitud + simplicidad de params). Puerto de arc-agi-runner/src/worldModel/__tests__/
synthesis.test.ts + casos borde propios de Python (indices negativos, grillas vacias, mutacion de
la lista de entrada). El presupuesto tiene su propio archivo: test_synthesis_budget.py."""
from __future__ import annotations

from arc_agent.world_model.grid import Grid
from arc_agent.world_model.primitive_ops import PrimitiveContext, apply_program, program_key
from arc_agent.world_model.synthesis import (
    DEFAULT_MAX_DEPTH,
    Observation,
    SynthesisBudget,
    program_complexity,
    rank_programs,
    search_programs,
    search_programs_with_usage,
    synthesize_program,
    synthesize_program_with_usage,
    verify_program,
)

RECOLOR_1_A_9 = {"name": "recolor", "params": {"mapping": {1: 9}}}


# --- program_complexity: la ley de Occam, afirmada sin pasar por una busqueda -----------------


def test_program_complexity_programa_vacio_es_cero() -> None:
    assert program_complexity([]) == 0


def test_program_complexity_la_longitud_domina() -> None:
    """Un programa de 2 pasos baratos SIEMPRE cuesta mas que uno de 1 paso caro: el factor 1000
    por paso es mayor que cualquier penalizacion de params que el DSL pueda generar."""
    corto = [{"name": "replicate", "params": {"timesX": 6, "timesY": 6}}]
    largo = [{"name": "reflect", "params": {"axis": "horizontal"}}] * 2
    assert program_complexity(corto) < program_complexity(largo)


def test_program_complexity_translate_usa_valor_absoluto_con_negativos() -> None:
    """Caso borde propio de Python: dx/dy negativos deben costar lo mismo que sus opuestos, o el
    ranking preferiria sistematicamente los desplazamientos hacia la izquierda/arriba."""
    izquierda = [{"name": "translate", "params": {"dx": -2, "dy": -1}}]
    derecha = [{"name": "translate", "params": {"dx": 2, "dy": 1}}]
    assert program_complexity(izquierda) == program_complexity(derecha) == 1003


def test_program_complexity_penaliza_predicate_all_mas_que_border() -> None:
    """`all` es redundante con recolor para un swap de un solo color; border/interior expresan
    semantica POSICIONAL que recolor no captura."""
    todos = [{"name": "conditionalRecolor", "params": {"from": 1, "to": 2, "predicate": "all"}}]
    borde = [{"name": "conditionalRecolor", "params": {"from": 1, "to": 2, "predicate": "border"}}]
    assert program_complexity(todos) == 1005
    assert program_complexity(borde) == 1003


def test_program_complexity_recolor_gana_el_desempate_a_conditional_recolor() -> None:
    """Con una sola observacion border/interior pueden coincidir con "todas las celdas"; el prior
    tiene que elegir el primitivo mas general."""
    recolor = [RECOLOR_1_A_9]
    condicional = [
        {"name": "conditionalRecolor", "params": {"from": 1, "to": 9, "predicate": "border"}}
    ]
    assert program_complexity(recolor) < program_complexity(condicional)


def test_program_complexity_object_extract_sin_color_es_mas_general() -> None:
    """La clave `color` AUSENTE (no None) distingue el candidato general del especifico."""
    assert program_complexity([{"name": "objectExtract", "params": {}}]) == 1000
    assert program_complexity([{"name": "objectExtract", "params": {"color": 3}}]) == 1001


def test_program_complexity_primitivos_de_costo_fijo() -> None:
    assert program_complexity([{"name": "floodFill", "params": {"x": 0, "y": 0, "to": 1}}]) == 1003
    assert program_complexity([{"name": "rotate", "params": {"quarterTurns": 3}}]) == 1001
    assert program_complexity([{"name": "cropToBBox", "params": {"backgroundColor": 0}}]) == 1001
    assert program_complexity([{"name": "overlay", "params": {}}]) == 1001
    replicate = [{"name": "replicate", "params": {"timesX": 2, "timesY": 3}}]
    assert program_complexity(replicate) == 1005
    assert program_complexity([{"name": "recolor", "params": {"mapping": {1: 9, 2: 3}}}]) == 1002


# --- rank_programs ------------------------------------------------------------------------------


def test_rank_programs_ordena_por_complejidad_ascendente() -> None:
    dos_pasos = [RECOLOR_1_A_9, RECOLOR_1_A_9]
    uno = [RECOLOR_1_A_9]
    assert rank_programs([dos_pasos, [], uno]) == [[], uno, dos_pasos]


def test_rank_programs_desempata_por_clave_serializada() -> None:
    """A igual complejidad el orden NO puede depender del orden de llegada: dos corridas del mismo
    episodio elegirian programas distintos y el agente dejaria de ser reproducible."""
    a = [{"name": "reflect", "params": {"axis": "horizontal"}}]
    b = [{"name": "rotate", "params": {"quarterTurns": 1}}]
    assert program_complexity(a) == program_complexity(b)
    assert rank_programs([a, b]) == rank_programs([b, a])


def test_rank_programs_no_muta_la_entrada() -> None:
    entrada = [[RECOLOR_1_A_9], []]
    copia = list(entrada)
    rank_programs(entrada)
    assert entrada == copia


# --- search_programs (puerto de synthesis.test.ts) ----------------------------------------------


def test_search_programs_encuentra_identidad_cuando_pre_igual_post() -> None:
    grid: Grid = [[1, 2]]
    assert [] in search_programs(grid, grid)


def test_search_programs_un_paso_recolor_cuando_alcanza() -> None:
    pre: Grid = [[1, 2, 1]]
    post: Grid = [[9, 2, 9]]
    programs = search_programs(pre, post)
    assert len(programs) > 0
    assert programs[0] == [RECOLOR_1_A_9]


def test_search_programs_compone_dos_pasos_cuando_ninguno_solo_alcanza() -> None:
    pre: Grid = [[0, 5, 0]]
    post: Grid = [[0, 0, 9]]
    programs = search_programs(pre, post, None, 3)
    assert len(programs) > 0
    assert apply_program(programs[0], pre) == post
    assert len(programs[0]) == 2


def test_search_programs_vacio_si_ninguna_composicion_explica_el_par() -> None:
    """El mismo color de origen (1) mapea a DOS destinos distintos segun la fila -- ningun
    primitivo del DSL expresa un recolor dependiente de posicion."""
    pre: Grid = [[1, 2], [1, 3]]
    post: Grid = [[9, 2], [8, 3]]
    assert search_programs(pre, post, None, 1) == []


def test_search_programs_rankea_la_identidad_primero() -> None:
    grid: Grid = [[1, 1]]
    assert search_programs(grid, grid)[0] == []


def test_search_programs_sin_duplicados_por_clave() -> None:
    """found es un dict indexado por program_key: dos ramas de la BFS que llegan al MISMO programa
    no pueden devolverlo dos veces (el ranking tendria empates espurios)."""
    pre: Grid = [[0, 5, 0]]
    post: Grid = [[0, 0, 9]]
    programs = search_programs(pre, post, None, 2)
    claves = [program_key(p) for p in programs]
    assert len(claves) == len(set(claves))


def test_search_programs_usa_el_ancla_del_contexto_para_overlay() -> None:
    """overlay es el UNICO proposer que mira el ctx: sin ancla degrada a identidad y nunca se
    propone."""
    pre: Grid = [[0, 0], [0, 0]]
    post: Grid = [[7, 7], [7, 7]]
    ctx = PrimitiveContext(anchor_grid=[[7, 7], [7, 7]])
    con_ancla = search_programs(pre, post, ctx)
    assert [{"name": "overlay", "params": {}}] in con_ancla
    assert [{"name": "overlay", "params": {}}] not in search_programs(pre, post)


def test_search_programs_grillas_vacias_son_iguales_y_dan_identidad() -> None:
    """Caso borde propio de Python: [] no puede explotar en _area_of (grid[0] no existe)."""
    assert search_programs([], []) == [[]]


def test_search_programs_con_usage_devuelve_ambos_campos() -> None:
    grid: Grid = [[1, 2]]
    resultado = search_programs_with_usage(grid, grid)
    assert resultado.programs == [[]]
    assert resultado.usage.expansions_used == 0
    # pre == post corta ANTES del barrido de entrada: no se paga nada.
    assert resultado.usage.proposer_sweeps == 0


# --- verify_program -----------------------------------------------------------------------------


def test_verify_program_true_cuando_reproduce_todas_las_observaciones() -> None:
    observations = [
        Observation(pre=[[1, 2]], post=[[9, 2]]),
        Observation(pre=[[1, 1]], post=[[9, 9]]),
    ]
    assert verify_program([RECOLOR_1_A_9], observations) is True


def test_verify_program_false_si_una_sola_observacion_contradice() -> None:
    observations = [
        Observation(pre=[[1, 2]], post=[[9, 2]]),
        Observation(pre=[[1, 1]], post=[[8, 8]]),  # contradice el mapping 1->9
    ]
    assert verify_program([RECOLOR_1_A_9], observations) is False


def test_verify_program_sin_observaciones_es_true() -> None:
    """Semantica de Array.every sobre una lista vacia -- no hay contradicciones que encontrar."""
    assert verify_program([RECOLOR_1_A_9], []) is True


def test_verify_program_no_muta_las_observaciones() -> None:
    """apply_program clona: una verificacion no puede ensuciar la evidencia que verifica."""
    obs = Observation(pre=[[1, 2]], post=[[9, 2]])
    verify_program([RECOLOR_1_A_9], [obs])
    assert obs.pre == [[1, 2]]


# --- synthesize_program (puerto de synthesis.test.ts) -------------------------------------------


def test_synthesize_program_null_sin_observaciones() -> None:
    assert synthesize_program([]) is None


def test_synthesize_program_consistente_con_multiples_observaciones() -> None:
    observations = [
        Observation(pre=[[1, 2]], post=[[9, 2]]),
        Observation(pre=[[2, 1]], post=[[2, 9]]),
        Observation(pre=[[1, 1]], post=[[9, 9]]),
    ]
    program = synthesize_program(observations)
    assert program is not None
    for obs in observations:
        assert apply_program(program, obs.pre) == obs.post


def test_synthesize_program_detecta_no_op_consistente() -> None:
    observations = [
        Observation(pre=[[3, 3]], post=[[3, 3]]),
        Observation(pre=[[1, 2]], post=[[1, 2]]),
    ]
    assert synthesize_program(observations) == []


def test_synthesize_program_null_si_las_observaciones_se_contradicen() -> None:
    observations = [
        Observation(pre=[[1, 1]], post=[[9, 9]]),  # sugiere 1->9
        Observation(pre=[[1, 1]], post=[[8, 8]]),  # mismo pre, post distinto
    ]
    assert synthesize_program(observations) is None


def test_synthesize_program_siembra_desde_la_observacion_mas_reciente() -> None:
    """El orden de semillas es de la mas NUEVA a la mas vieja: tras una contradiccion la evidencia
    util esta al final del historial, y lo que se corta por presupuesto es la cola larga.

    Se afirma por el COSTO, que es lo unico que distingue una semilla de la otra: la observacion
    vieja es 4x4 (barrido de 160 celdas) y la nueva 1x2 (barrido de 20). Si el loop arrancara por
    la vieja, el consumo seria 160."""
    vieja = Observation(
        pre=[[1] * 4 for _ in range(4)], post=[[9] * 4 for _ in range(4)]
    )
    nueva = Observation(pre=[[1, 2]], post=[[9, 2]])
    resultado = synthesize_program_with_usage([vieja, nueva])
    assert resultado.program == [RECOLOR_1_A_9]
    assert resultado.usage.seed_sweep_cells_used == 2 * 10
    # Un solo barrido: la primera semilla ya dio un sobreviviente y el loop corto.
    assert resultado.usage.proposer_sweeps == 1


def test_synthesize_program_with_usage_devuelve_programa_y_consumo() -> None:
    resultado = synthesize_program_with_usage([Observation(pre=[[1, 2]], post=[[9, 2]])])
    assert resultado.program == [RECOLOR_1_A_9]
    assert resultado.usage.proposer_sweeps == 1
    assert resultado.usage.budget_exhausted is False


def test_synthesize_program_respeta_max_depth_cero() -> None:
    """max_depth 0 apaga la BFS estructural: solo sobrevive lo que el tier data-driven explica en
    un paso."""
    dos_pasos = [Observation(pre=[[0, 5, 0]], post=[[0, 0, 9]])]
    assert synthesize_program(dos_pasos, None, 0) is None
    assert synthesize_program(dos_pasos, None, DEFAULT_MAX_DEPTH) is not None


def test_synthesize_program_sin_credito_de_barridos_no_mira_ninguna_semilla() -> None:
    """El credito de barridos de entrada es el corte MAESTRO del loop de semillas: se evalua ANTES
    de mirar el par, asi que ni siquiera un no-op (que adentro de la busqueda seria gratis) llega a
    detectarse. Es exactamente lo que frena el recorrido del historial en 64x64 (BL.21026)."""
    sin_barridos = SynthesisBudget(max_seed_sweep_cells=0)
    cambio = [Observation(pre=[[1, 2]], post=[[9, 2]])]
    no_op = [Observation(pre=[[1, 2]], post=[[1, 2]])]
    assert synthesize_program(cambio, None, 3, sin_barridos) is None
    assert synthesize_program(no_op, None, 3, sin_barridos) is None


def test_synthesize_program_acepta_presupuesto_inyectado() -> None:
    """El presupuesto es un parametro, no una constante enterrada en la busqueda. Con una sola
    expansion el tier data-driven de profundidad 1 sigue entero (nunca la gasta) y lo unico que se
    apaga es la BFS ciega, que es la que necesita componer dos pasos."""
    apretado = SynthesisBudget(max_node_expansions=1)
    un_paso = [Observation(pre=[[1, 2]], post=[[9, 2]])]
    dos_pasos = [Observation(pre=[[0, 5, 0]], post=[[0, 0, 9]])]
    assert synthesize_program(un_paso, None, 3, apretado) == [RECOLOR_1_A_9]
    assert synthesize_program(dos_pasos, None, 3, apretado) is None
    assert synthesize_program(dos_pasos, None, 3) is not None
