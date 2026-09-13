"""[arc-agi3-kaggle-agent/tests/synthesis.budget] -- el presupuesto de sintesis es lo que hace
jugable el benchmark. Medido contra la API oficial sobre tr87-cd924810: sin el, una decision
tardaba 40-110 SEGUNDOS sobre grillas 64x64 y el tiempo CRECIA con los pasos (el agente se volvia
mas lento cuanto mas aprendia). Puerto de arc-agi-runner/src/worldModel/__tests__/
synthesis.budget.test.ts (BL.20861 + BL.21026/BL.21029).

Estos tests fijan las propiedades que producen ese resultado. Si alguien las afloja "porque la
busqueda encuentra mas", el benchmark vuelve a ser injugable en silencio -- el sintoma es lentitud,
no un fallo.

Se afirman en UNIDADES DE PRESUPUESTO, nunca en milisegundos: un umbral de tiempo pasa aislado y
falla bajo contencion de CPU ajena, sin que haya regresion alguna. Un contador de unidades mide el
TRABAJO, que es lo que el presupuesto acota, y no depende de la maquina que lo corra."""
from __future__ import annotations

from dataclasses import replace

from arc_agent.world_model.grid import Grid
from arc_agent.world_model.synthesis import (
    DEFAULT_SYNTHESIS_BUDGET,
    Observation,
    SynthesisBudget,
    search_programs,
    search_programs_with_usage,
    synthesize_program_with_usage,
)


def grid_denso(n: int, offset: int = 0) -> Grid:
    """Grilla NxN con contenido pseudo-aleatorio estable -- densa a proposito: una grilla uniforme
    haria que los proposers cierren en el primer intento y el test no mediria la busqueda."""
    return [[(x * 7 + y * 13 + offset) % 16 for x in range(n)] for y in range(n)]


def par_inexplicable(n: int) -> tuple[Grid, Grid]:
    """Par pre/post que NINGUN paso unico del DSL explica -- fuerza el peor caso: profundidad 1
    falla y la busqueda tiene que decidir si escala a la BFS ciega. Es el caso COMUN en juego real.

    Construccion: reflejo horizontal MAS un cambio local. El reflejo solo no cierra (queda una
    celda distinta); floodFill/recolor tampoco, porque las posiciones cambiaron. Un solo cambio de
    celda NO sirve para este test: floodFill lo explica en profundidad 1, barato y correcto."""
    pre = grid_denso(n, 0)
    post = [list(reversed(row)) for row in pre]
    post[1][1] = (post[1][1] + 1) % 16
    return pre, post


def test_una_grilla_64x64_no_entra_en_la_bfs_ciega() -> None:
    pre, post = par_inexplicable(64)
    resultado = search_programs_with_usage(pre, post, None, 3)

    assert resultado.programs == []
    # La afirmacion fuerte: la BFS no corrio NADA. Un cronometro no distingue "no expandio" de
    # "expandio poco en una maquina rapida".
    assert resultado.usage.expansions_used == 0
    assert resultado.usage.cells_used == 0
    # El unico trabajo pagado es el barrido de entrada de profundidad 1, donde SI puede haber
    # señal.
    assert resultado.usage.proposer_sweeps == 1


def test_una_grilla_chica_si_usa_la_busqueda_completa() -> None:
    """8x8 esta muy por debajo del umbral: aca las transformaciones globales del DSL son la
    respuesta (caso ARC-AGI-1/2 y entornos sinteticos), y la busqueda debe correr entera."""
    pre = grid_denso(8, 0)
    post = [list(reversed(row)) for row in pre]  # reflect horizontal: explicable
    assert len(search_programs(pre, post, None, 3)) > 0


def test_una_grilla_30x30_inexplicable_si_expande_la_bfs() -> None:
    """Contracara del test de 64x64: donde la BFS vale lo que cuesta, tiene que correr de verdad.
    Con un tope chico de expansiones alcanza para demostrar que la BFS ARRANCA, que es la
    propiedad -- correrla entera solo agregaria segundos de CPU."""
    pre, post = par_inexplicable(30)
    usage = search_programs_with_usage(
        pre, post, None, 3, replace(DEFAULT_SYNTHESIS_BUDGET, max_node_expansions=5)
    ).usage

    assert usage.expansions_used > 0
    assert usage.cells_used > 0
    # Los finishers de adentro de la BFS NO se cobran contra max_seed_sweep_cells: si se cobraran,
    # el credito se agotaria en un puñado de nodos y la busqueda quedaria ~40x mas corta.
    assert usage.proposer_sweeps > 1
    assert usage.seed_sweep_cells_used == 30 * 30 * 10  # un solo barrido de entrada


def test_el_umbral_de_area_es_el_que_decide_no_el_tamano_absoluto() -> None:
    """Se usa 33x33 (1089 celdas) justamente porque es MUCHO mas chica que la grilla del juego real
    y aun asi queda afuera: lo que decide es el AREA contra el umbral, no el tamano absoluto. De
    paso mantiene el test barato -- en Python un barrido de 64x64 cuesta ~30x uno de 33x33."""
    pre, post = par_inexplicable(33)

    # Con el default, 1089 > max_structural_search_area: la BFS ni arranca.
    con_default = search_programs_with_usage(pre, post, None, 3).usage
    assert con_default.expansions_used == 0

    # MISMA grilla, mismo todo: lo unico que se mueve es el umbral de area. Las expansiones se
    # acotan a 2 porque lo que se afirma es que la BFS arranca, no cuanto corre.
    generoso = replace(
        DEFAULT_SYNTHESIS_BUDGET, max_structural_search_area=10_000, max_node_expansions=2
    )
    con_umbral_alto = search_programs_with_usage(pre, post, None, 3, generoso).usage
    assert con_umbral_alto.expansions_used > 0


def test_el_presupuesto_de_celdas_corta_aunque_queden_expansiones() -> None:
    pre, post = par_inexplicable(30)
    sin_celdas = replace(
        DEFAULT_SYNTHESIS_BUDGET, max_node_expansions=100_000, max_cells_touched=1
    )
    resultado = search_programs_with_usage(pre, post, None, 3, sin_celdas)

    assert resultado.programs == []
    assert resultado.usage.budget_exhausted is True
    # Corto por celdas, no por expansiones: quedaron 100k disponibles y uso un puñado. Es la
    # propiedad real -- las expansiones solas no acotan, porque un nodo inflado cuesta 300x uno
    # normal.
    assert resultado.usage.expansions_used < 100


def test_el_costo_no_crece_con_el_historial_en_30x30() -> None:
    """Antes del presupuesto compartido cada semilla recibia uno entero, asi que sintetizar con 20
    observaciones costaba ~20x lo que con 1: el agente se degradaba a medida que aprendia."""
    pre, post = par_inexplicable(30)
    acotado = replace(DEFAULT_SYNTHESIS_BUDGET, max_node_expansions=5)

    def uso(k: int):
        return synthesize_program_with_usage(
            [Observation(pre=pre, post=post) for _ in range(k)], None, 3, acotado
        ).usage

    una = uso(1)
    muchas = uso(8)

    # El presupuesto es de la sintesis ENTERA: 8 observaciones identicas no pueden costar un
    # multiplo de lo que cuesta 1. Se afirma sobre el trabajo, no sobre el reloj.
    assert muchas.expansions_used == una.expansions_used
    assert muchas.cells_used == una.cells_used
    assert muchas.proposer_sweeps == una.proposer_sweeps


def test_el_costo_no_crece_con_el_historial_en_64x64() -> None:
    """La regresion que el test de 30x30 NO podia ver, y que por eso vivio hasta BL.21026: sobre
    una grilla por encima de max_structural_search_area la BFS retorna sin gastar expansiones ni
    celdas, asi que el contador compartido nunca bajaba y el loop de semillas recorria el historial
    ENTERO pagando un barrido de entrada por observacion. Medido antes del fix: 22ms con 1
    observacion y 1861ms con 100 -- lineal, justo en el unico tamaño de grilla que ARC-AGI-3 usa en
    vivo."""
    pre, post = par_inexplicable(64)
    costo_barrido = 64 * 64 * 10
    # Credito para 2 barridos en vez de los ~12 del default: la propiedad afirmada es que el
    # consumo se DETIENE en el credito, y se demuestra igual de bien con 2 -- pagar 12 barridos de
    # 64x64 solo agrega CPU a un test que ya no mide tiempo (en Python un barrido de 64x64 cuesta
    # ~0.9s, ~30x lo que en Node).
    acotado = replace(DEFAULT_SYNTHESIS_BUDGET, max_seed_sweep_cells=costo_barrido * 2)

    def uso(k: int):
        return synthesize_program_with_usage(
            [Observation(pre=pre, post=post) for _ in range(k)], None, 3, acotado
        ).usage

    pocas = uso(3)
    muchas = uso(20)

    # 3x el historial no puede costar mas trabajo: el techo lo pone el presupuesto, no el largo.
    assert muchas.proposer_sweeps == pocas.proposer_sweeps
    assert muchas.seed_sweep_cells_used == pocas.seed_sweep_cells_used
    assert muchas.budget_exhausted is True

    # Y el techo es el declarado: nunca se pasa de un barrido por encima del credito (el que lo
    # agota). Sin esto, "no crece" podria cumplirse en un numero absurdamente alto.
    assert muchas.seed_sweep_cells_used <= acotado.max_seed_sweep_cells + costo_barrido


def test_una_sola_observacion_en_64x64_paga_un_solo_barrido() -> None:
    pre, post = par_inexplicable(64)
    usage = synthesize_program_with_usage([Observation(pre=pre, post=post)], None, 3).usage

    assert usage.proposer_sweeps == 1
    assert usage.budget_exhausted is False


def test_el_default_expone_las_cinco_perillas() -> None:
    assert DEFAULT_SYNTHESIS_BUDGET.to_dict() == {
        "maxNodeExpansions": DEFAULT_SYNTHESIS_BUDGET.max_node_expansions,
        "maxCellsTouched": DEFAULT_SYNTHESIS_BUDGET.max_cells_touched,
        "maxIntermediateAreaRatio": DEFAULT_SYNTHESIS_BUDGET.max_intermediate_area_ratio,
        "maxStructuralSearchArea": DEFAULT_SYNTHESIS_BUDGET.max_structural_search_area,
        "maxSeedSweepCells": DEFAULT_SYNTHESIS_BUDGET.max_seed_sweep_cells,
    }
    # 64x64 (la grilla de ARC-AGI-3 en vivo) DEBE quedar fuera de la BFS ciega.
    assert DEFAULT_SYNTHESIS_BUDGET.max_structural_search_area < 64 * 64
    # 30x30 (ARC-AGI-1/2) DEBE seguir adentro.
    assert DEFAULT_SYNTHESIS_BUDGET.max_structural_search_area >= 30 * 30
    # El credito de barridos de entrada tiene que alcanzar para varias semillas de 64x64 -- si
    # cayera por debajo de un barrido, la sintesis quedaria muerta en el juego real -- pero tiene
    # que seguir siendo un TECHO: aflojarlo a cientos de barridos devolveria el costo lineal con el
    # historial que BL.21026 encontro (100 observaciones = 1861ms).
    barrido_de_64 = 64 * 64 * 10
    assert DEFAULT_SYNTHESIS_BUDGET.max_seed_sweep_cells > barrido_de_64 * 3
    assert DEFAULT_SYNTHESIS_BUDGET.max_seed_sweep_cells < barrido_de_64 * 40


def test_los_valores_por_defecto_son_exactamente_los_del_motor_original() -> None:
    """Los numeros no son redondeos de escritorio: cada uno se midio contra la API oficial. Un
    cambio silencioso aca es un cambio de comportamiento del agente en vivo."""
    assert DEFAULT_SYNTHESIS_BUDGET == SynthesisBudget(
        max_node_expansions=2000,
        max_cells_touched=2_000_000,
        max_intermediate_area_ratio=4,
        max_structural_search_area=1024,
        max_seed_sweep_cells=500_000,
    )


def test_budget_round_trip_por_dict() -> None:
    """to_dict/from_dict son la frontera con el JSON del fixture: camelCase afuera, snake_case
    adentro, y el round-trip tiene que ser la identidad."""
    apretado = SynthesisBudget(
        max_node_expansions=7,
        max_cells_touched=8,
        max_intermediate_area_ratio=9,
        max_structural_search_area=10,
        max_seed_sweep_cells=11,
    )
    assert SynthesisBudget.from_dict(apretado.to_dict()) == apretado
    # Claves ausentes caen al default del campo, no a None.
    assert SynthesisBudget.from_dict({}) == DEFAULT_SYNTHESIS_BUDGET


def test_usage_serializa_en_camel_case() -> None:
    usage = search_programs_with_usage([[1, 2]], [[9, 2]]).usage
    assert set(usage.to_dict()) == {
        "expansionsUsed",
        "cellsUsed",
        "seedSweepCellsUsed",
        "proposerSweeps",
        "budgetExhausted",
    }
    assert usage.to_dict()["proposerSweeps"] == 1
