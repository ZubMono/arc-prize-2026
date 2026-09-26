"""[arc-agi3-kaggle-agent/world_model/synthesis] -- sintesis bottom-up de programas del DSL:
busqueda de composiciones cortas (profundidad <=3-4) que expliquen TODAS las observaciones
(pre, post) sin contradicciones, rankeadas por prior de Occam (longitud + simplicidad de params).
Puerto de arc-agi-runner/src/worldModel/synthesis.ts (BL.20860 + BL.20861 + BL.21026/BL.21029).

Estrategia de busqueda (2 niveles, ver enumerate_structural_steps en primitives.py para el
razonamiento completo):
1. Tier "finisher": los propose_* de primitives.py ya se auto-verifican contra UN par -- si alguno
   explica pre->post en un solo paso, listo (camino rapido, cubre la mayoria de transformaciones
   ARC reales).
2. Si ningun paso unico alcanza: busqueda en anchura acotada que expande con pasos
   "estructurales" ciegos (enumerate_structural_steps, sin necesitar el post) y en CADA nodo nuevo
   reintenta el finisher data-driven para cerrar la brecha con un ultimo paso "semantico"
   (recolor/floodFill/overlay/conditionalRecolor/cropToBBox/objectExtract).

Por que los presupuestos estan en unidades de CELDAS y no de nodos: el costo de un nodo es
proporcional al AREA de su grilla intermedia, y `replicate` (hasta 3x3) la infla -- una 64x64 pasa
a 192x192, y compuesta a profundidad 2 a 576x576 (331k celdas). Medido contra la API oficial de
ARC-AGI-3: 40-110 SEGUNDOS por decision, creciendo con los pasos. Un tope de expansiones solo NO
acota nada porque los nodos no cuestan igual entre si.

Por que el barrido de ENTRADA se cobra aparte (max_seed_sweep_cells) y los finishers de adentro de
la BFS no: sobre una grilla por encima de max_structural_search_area la busqueda retorna ANTES de
descontar expansiones o celdas, asi que el contador compartido de synthesize_program nunca bajaba y
cada semilla del historial pagaba un barrido entero -- medido en 64x64, 22ms con 1 observacion y
1861ms con 100, crecimiento LINEAL con lo aprendido (BL.21026). Los finishers, en cambio, ya estan
acotados por expansiones y celdas: cobrarlos contra la misma perilla recortaria la busqueda en
grillas chicas ~40x (un finisher sobre una intermedia inflada cuesta 10x lo que el nodo).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any, Final, NamedTuple

# Cada import relativo va en UNA sola linea, nunca partido entre parentesis: el builder del
# notebook de Kaggle los desmonta con una regex de LINEA (^from \.\w* import .+$) y un import
# multilinea dejaria las lineas de adentro sueltas, rompiendo el .ipynb de submission.
from .grid import Grid, grids_equal
from .primitive_ops import EMPTY_CONTEXT, PrimitiveContext, Program, ProgramStep
from .primitive_ops import apply_program, apply_step, compare_program_keys, program_key
from .primitives import enumerate_structural_steps, propose_all_steps
from .program_coverage import MIN_PROGRAM_COVERAGE, Observation, ProgramCoverage
from .program_coverage import cobertura_suficiente, program_coverage, verify_program

# Profundidad de pasos ESTRUCTURALES ciegos antes del finisher final -- combinada con el finisher
# da una profundidad total de programa de hasta max_depth+1 (3 structural + 1 finisher = 4).
DEFAULT_MAX_DEPTH: Final[int] = 3

# Tope duro de expansiones de nodos. NO alcanza por si solo (ver docstring de modulo): los
# presupuestos que de verdad acotan el tiempo estan en celdas.
MAX_NODE_EXPANSIONS: Final[int] = 2000

# Trabajo total permitido por busqueda, en celdas de grillas intermedias procesadas.
DEFAULT_MAX_CELLS_TOUCHED: Final[int] = 2_000_000

# Un nodo cuya grilla intermedia supera este multiplo del area objetivo se poda. Multiplo generoso
# a proposito: una composicion valida PUEDE necesitar agrandar y despues recortar (replicate ->
# cropToBBox). 4x deja pasar replicate 2x2 y corta el 3x3 y los encadenamientos, que son los que
# explotan. La busqueda ya era incompleta por diseno; esto la hace incompleta de forma ACOTADA Y
# MEDIBLE en vez de lenta.
DEFAULT_MAX_INTERMEDIATE_AREA_RATIO: Final[int] = 4

# Area maxima de grilla para la que se intenta la BFS estructural CIEGA. Por encima solo corre el
# tier data-driven de profundidad 1. No es una heuristica de escritorio: medido contra la API
# oficial sobre tr87-cd924810, en 10 transiciones reales de 64x64 la BFS profunda explico CERO y
# costo entre 6 y 56 segundos cada vez (profundidad 1: 12-196ms, tambien cero). El motivo es de
# dominio -- en ARC-AGI-3 una accion produce un cambio LOCAL y semantico (un cursor que se mueve,
# una celda que cambia), no una transformacion geometrica de la grilla entera, que es lo unico que
# la enumeracion ciega sabe expresar. 1024 = 32x32 deja pasar entera la busqueda para ARC-AGI-1/2
# (<=30x30), donde las transformaciones globales SI son la respuesta.
DEFAULT_MAX_STRUCTURAL_SEARCH_AREA: Final[int] = 1024

# Cuantas pasadas sobre la grilla cuesta UN barrido de propose_all_steps -- una por proposer
# data-driven. Cobra el barrido en las MISMAS unidades (celdas) que max_cells_touched, de modo que
# las dos perillas sean comparables entre si.
PROPOSER_PASSES_PER_SWEEP: Final[int] = 10

# Trabajo total permitido en barridos de ENTRADA (ver docstring de modulo, BL.21026/BL.21029).
# 500k celdas ~= 12 semillas de 64x64 (4096 celdas x 10 proposers = 40960 c/u), o sea ~225ms de
# techo por decision. Las semillas se prueban de la mas reciente a la mas vieja -- que es donde
# suele estar la evidencia util -- asi que lo que se corta es la cola larga del historial.
DEFAULT_MAX_SEED_SWEEP_CELLS: Final[int] = 500_000


@dataclass(frozen=True)
class SynthesisBudget:
    """Presupuesto de una busqueda. Inyectable para que el harness offline de Kaggle (9h totales,
    sin internet) pueda aflojarlo y una corrida en vivo contra la API pueda apretarlo, sin tocar
    la logica de busqueda."""

    max_node_expansions: int = MAX_NODE_EXPANSIONS
    max_cells_touched: int = DEFAULT_MAX_CELLS_TOUCHED
    max_intermediate_area_ratio: int = DEFAULT_MAX_INTERMEDIATE_AREA_RATIO
    max_structural_search_area: int = DEFAULT_MAX_STRUCTURAL_SEARCH_AREA
    max_seed_sweep_cells: int = DEFAULT_MAX_SEED_SWEEP_CELLS

    def to_dict(self) -> dict[str, int]:
        return {
            "maxNodeExpansions": self.max_node_expansions,
            "maxCellsTouched": self.max_cells_touched,
            "maxIntermediateAreaRatio": self.max_intermediate_area_ratio,
            "maxStructuralSearchArea": self.max_structural_search_area,
            "maxSeedSweepCells": self.max_seed_sweep_cells,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "SynthesisBudget":
        return SynthesisBudget(
            max_node_expansions=raw.get("maxNodeExpansions", MAX_NODE_EXPANSIONS),
            max_cells_touched=raw.get("maxCellsTouched", DEFAULT_MAX_CELLS_TOUCHED),
            max_intermediate_area_ratio=raw.get(
                "maxIntermediateAreaRatio", DEFAULT_MAX_INTERMEDIATE_AREA_RATIO
            ),
            max_structural_search_area=raw.get(
                "maxStructuralSearchArea", DEFAULT_MAX_STRUCTURAL_SEARCH_AREA
            ),
            max_seed_sweep_cells=raw.get("maxSeedSweepCells", DEFAULT_MAX_SEED_SWEEP_CELLS),
        )


DEFAULT_SYNTHESIS_BUDGET: Final[SynthesisBudget] = SynthesisBudget()


@dataclass(frozen=True)
class SynthesisUsage:
    """Consumo REAL de una busqueda, en unidades de presupuesto. Existe para que el costo se pueda
    afirmar de forma DETERMINISTA: medir milisegundos contra umbrales fijos falla bajo contencion
    de CPU ajena sin que haya regresion alguna (BL.21029). Un contador de unidades mide el TRABAJO,
    que es lo que el presupuesto acota, y no depende de la maquina que lo corra."""

    expansions_used: int
    cells_used: int
    # Celdas de barridos de ENTRADA -- lo que se cobra contra max_seed_sweep_cells.
    seed_sweep_cells_used: int
    # Barridos data-driven totales, de entrada y finishers. Observabilidad, no se cobra.
    proposer_sweeps: int
    # Alguna perilla corto la busqueda antes de agotar el espacio alcanzable.
    budget_exhausted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "expansionsUsed": self.expansions_used,
            "cellsUsed": self.cells_used,
            "seedSweepCellsUsed": self.seed_sweep_cells_used,
            "proposerSweeps": self.proposer_sweeps,
            "budgetExhausted": self.budget_exhausted,
        }


def _area_of(grid: Grid) -> int:
    return len(grid) * (len(grid[0]) if grid else 0)


@dataclass
class _BudgetCounter:
    """Contador MUTABLE de presupuesto restante. Existe para que synthesize_program pueda repartir
    UN unico presupuesto entre todas sus semillas en vez de darle uno entero a cada una. Nunca se
    expone: los callers pasan un SynthesisBudget inmutable y cada uno arranca con el suyo."""

    expansions_left: int
    cells_left: int
    seed_sweep_cells_left: int
    max_intermediate_area_ratio: int
    max_structural_search_area: int
    expansions_used: int = 0
    cells_used: int = 0
    seed_sweep_cells_used: int = 0
    proposer_sweeps: int = 0


@dataclass
class _SynthesisNode:
    """Nodo de la frontera de la BFS estructural: el programa acumulado y la grilla que produce.

    El nombre lleva el modulo adentro y NO es un generico "nodo de busqueda": planner.py tiene su
    propio nodo de busqueda (grid/path/g) y el builder del notebook de Kaggle aplana los modulos
    en UN solo namespace, donde el ultimo en definirse le pisaria la clase al otro y el
    constructor del perdedor explotaria en runtime dentro de la submission."""

    program: Program
    grid: Grid


def _counter_from(budget: SynthesisBudget) -> _BudgetCounter:
    return _BudgetCounter(
        expansions_left=budget.max_node_expansions,
        cells_left=budget.max_cells_touched,
        seed_sweep_cells_left=budget.max_seed_sweep_cells,
        max_intermediate_area_ratio=budget.max_intermediate_area_ratio,
        max_structural_search_area=budget.max_structural_search_area,
    )


def _usage_from(counter: _BudgetCounter) -> SynthesisUsage:
    return SynthesisUsage(
        expansions_used=counter.expansions_used,
        cells_used=counter.cells_used,
        seed_sweep_cells_used=counter.seed_sweep_cells_used,
        proposer_sweeps=counter.proposer_sweeps,
        budget_exhausted=_sin_credito_para_otra_semilla(counter),
    )


def _sin_credito_para_la_bfs(counter: _BudgetCounter) -> bool:
    """Corte de la BFS ciega: solo las perillas que ella consume. NO mira el credito de semillas --
    si lo hiciera, el barrido de entrada que se acaba de cobrar podria apagar la BFS de esa misma
    semilla, que tiene expansiones y celdas de sobra."""
    return counter.expansions_left <= 0 or counter.cells_left <= 0


def _sin_credito_para_otra_semilla(counter: _BudgetCounter) -> bool:
    """Corte del loop de semillas de synthesize_program. Suma el credito de barridos de entrada:
    sin eso, sobre una grilla por encima de max_structural_search_area la BFS retorna sin gastar
    nada, el contador queda intacto para siempre y el historial entero se recorre a costo lineal
    (BL.21026)."""
    return _sin_credito_para_la_bfs(counter) or counter.seed_sweep_cells_left <= 0


def _sweep_seed_proposers(
    pre: Grid, post: Grid, ctx: PrimitiveContext, counter: _BudgetCounter
) -> list[ProgramStep]:
    """Barrido de ENTRADA (profundidad 1), cobrado contra el presupuesto compartido de la sintesis.
    Devuelve vacio -- sin recorrer la grilla -- cuando ya no queda credito: eso es lo que corta la
    cola larga del historial de observaciones."""
    if counter.seed_sweep_cells_left <= 0:
        return []
    costo = max(_area_of(pre), _area_of(post)) * PROPOSER_PASSES_PER_SWEEP
    counter.seed_sweep_cells_left -= costo
    counter.seed_sweep_cells_used += costo
    counter.proposer_sweeps += 1
    return propose_all_steps(pre, post, ctx)


def _sweep_finisher_proposers(
    pre: Grid, post: Grid, ctx: PrimitiveContext, counter: _BudgetCounter
) -> list[ProgramStep]:
    """Barrido "finisher" dentro de la BFS. No se cobra -- ya lo acotan expansiones y celdas --
    pero se cuenta para poder afirmar el trabajo total sin cronometro."""
    counter.proposer_sweeps += 1
    return propose_all_steps(pre, post, ctx)


def program_complexity(program: Program) -> int:
    """Puntaje de complejidad para el ranking Occam: la LONGITUD domina (menos pasos = mejor), y a
    igual longitud se prefiere el programa mas "general" -- menos parametros hardcodeados
    (mappings chicos, desplazamientos cortos, predicados simples)."""
    score = len(program) * 1000
    for step in program:
        name = step["name"]
        params = step["params"]
        if name == "translate":
            score += abs(params["dx"]) + abs(params["dy"])
        elif name == "recolor":
            # Primitivo mas general para un swap de color puro (sin dependencia posicional) --
            # costo bajo para que gane el desempate frente a conditionalRecolor cuando ambos
            # explican el mismo par (border/interior coinciden con "todas las celdas" cuando esas
            # celdas resultan estar todas en el borde, ambiguedad tipica con una sola observacion).
            score += len(params["mapping"])
        elif name == "floodFill":
            score += 3
        elif name == "conditionalRecolor":
            # predicate 'all' es redundante con recolor(mapping) para un swap de un solo color --
            # se penaliza mas fuerte. border/interior expresan semantica POSICIONAL que recolor no
            # puede capturar; siguen costando mas que recolor para que este gane los empates, pero
            # se eligen igual cuando son la UNICA explicacion disponible (recolor no sobrevive).
            score += 5 if params["predicate"] == "all" else 3
        elif name == "objectExtract":
            score += 1 if "color" in params else 0
        elif name == "replicate":
            score += params["timesX"] + params["timesY"]
        elif name in ("reflect", "rotate", "cropToBBox", "overlay"):
            score += 1
    return score


def rank_programs(programs: list[Program]) -> list[Program]:
    """Ordena por Occam (complejidad ascendente) con desempate deterministico por clave
    serializada. No muta la entrada. sorted() es estable, igual que Array.prototype.sort en V8."""

    def comparar(a: Program, b: Program) -> int:
        diff = program_complexity(a) - program_complexity(b)
        if diff != 0:
            return diff
        return compare_program_keys(program_key(a), program_key(b))

    return sorted(programs, key=cmp_to_key(comparar))


def search_programs(
    pre: Grid,
    post: Grid,
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> list[Program]:
    """Busca programas (composiciones bottom-up, profundidad acotada) que expliquen pre -> post
    para UN par observado -- devuelve todos los sobrevivientes encontrados, rankeados por Occam.
    Semilla de candidatos para synthesize_program, que despues verifica contra el historial
    COMPLETO de observaciones."""
    return search_programs_with_usage(pre, post, ctx, max_depth, budget).programs


class SearchResult(NamedTuple):
    programs: list[Program]
    usage: SynthesisUsage


def search_programs_with_usage(
    pre: Grid,
    post: Grid,
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> SearchResult:
    """Igual que search_programs pero devuelve ademas el consumo de presupuesto. Es la unica forma
    de afirmar el costo sin cronometro (BL.21029). Arranca con un contador PROPIO (presupuesto
    fresco); synthesize_program*, en cambio, comparte el suyo entre semillas."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    counter = _counter_from(budget)
    programs = _search_with_counter(pre, post, ctx, max_depth, counter)
    return SearchResult(programs=programs, usage=_usage_from(counter))


def _search_with_counter(
    pre: Grid,
    post: Grid,
    ctx: PrimitiveContext,
    max_depth: int,
    counter: _BudgetCounter,
) -> list[Program]:
    # dict preserva orden de insercion, igual que un Map de JS.
    found: dict[str, Program] = {}

    if grids_equal(pre, post):
        found[program_key([])] = []
        return rank_programs(list(found.values()))

    for step in _sweep_seed_proposers(pre, post, ctx, counter):
        found[program_key([step])] = [step]
    if found:
        return rank_programs(list(found.values()))

    area_base = max(_area_of(pre), _area_of(post))

    # Grilla demasiado grande para que la BFS ciega valga lo que cuesta (ver
    # DEFAULT_MAX_STRUCTURAL_SEARCH_AREA). Devolver vacio aca NO es una perdida de capacidad: el
    # resultado con BFS sobre estas grillas tambien era vacio, solo que 40 segundos despues.
    if area_base > counter.max_structural_search_area:
        return []

    # Area maxima tolerada para una grilla intermedia. Se toma sobre el MAYOR entre pre y post: si
    # la transformacion buscada agranda (post > pre), el margen se mide contra el destino real.
    max_intermediate_area = area_base * counter.max_intermediate_area_ratio

    frontier: list[_SynthesisNode] = [_SynthesisNode(program=[], grid=pre)]

    depth = 0
    while depth < max_depth and not found and not _sin_credito_para_la_bfs(counter):
        next_frontier: list[_SynthesisNode] = []
        for node in frontier:
            if _sin_credito_para_la_bfs(counter):
                break
            for structural_step in enumerate_structural_steps(node.grid):
                if _sin_credito_para_la_bfs(counter):
                    break
                counter.expansions_left -= 1
                counter.expansions_used += 1

                next_grid = apply_step(structural_step, node.grid, ctx)
                next_area = _area_of(next_grid)
                # Poda ANTES de pagar el finisher: propose_all_steps recorre la grilla diez veces
                # (una por proposer), asi que un nodo inflado cuesta un orden de magnitud mas que
                # uno normal.
                if next_area > max_intermediate_area:
                    continue
                counter.cells_left -= next_area
                counter.cells_used += next_area

                next_program: Program = [*node.program, structural_step]

                for finisher_step in _sweep_finisher_proposers(next_grid, post, ctx, counter):
                    full_program: Program = [*next_program, finisher_step]
                    found[program_key(full_program)] = full_program

                next_frontier.append(_SynthesisNode(program=next_program, grid=next_grid))
        frontier = next_frontier
        depth += 1

    return rank_programs(list(found.values()))


def synthesize_program(
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> Program | None:
    """Sintetiza el MEJOR programa que explica las observaciones de una accion, o None si ninguna
    composicion de profundidad acotada llega al minimo de cobertura (BL.21561). Siembra la busqueda
    desde cada observacion, empezando por las mas recientes."""
    return synthesize_program_with_usage(observations, ctx, max_depth, budget).program


class SynthesisResult(NamedTuple):
    program: Program | None
    usage: SynthesisUsage


def synthesize_program_with_usage(
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> SynthesisResult:
    """Igual que synthesize_program pero devuelve ademas el consumo de presupuesto de la sintesis
    COMPLETA -- la unidad en la que se afirma que el costo no crece con el historial (BL.21029)."""
    scored = synthesize_program_scored(observations, ctx, max_depth, budget)
    return SynthesisResult(program=scored.program, usage=scored.usage)


def _sin_hipotesis(counter: "_BudgetCounter") -> "ScoredProgram":
    """Ningun candidato aceptable: cobertura 0 y el presupuesto ya consumido."""
    return ScoredProgram(None, 0, 0, 0.0, _usage_from(counter))


class ScoredProgram(NamedTuple):
    program: Program | None
    aciertos: int
    fallos: int
    cobertura: float
    usage: SynthesisUsage


def synthesize_program_scored(
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
    min_coverage: float = MIN_PROGRAM_COVERAGE,
) -> ScoredProgram:
    """BL.21561 -- sintesis por COBERTURA PUNTUADA en vez de por verificacion de cero tolerancia:
    se acepta el programa que explica MAS observaciones (por encima de `min_coverage`) y se
    devuelven sus aciertos/fallos para que quien lo use los contabilice en alpha/beta.

    El presupuesto de busqueda NO cambia: el recorrido de semillas se sigue cortando en cuanto
    aparece un candidato de cobertura 1, la misma condicion de antes; los candidatos parciales se
    puntuan al pasar, sin gastar una expansion de mas.

    La IDENTIDAD (programa vacio) es la unica que se exige exacta: aceptarla parcialmente equivale
    a declarar no-op una accion que a veces SI hace algo, y eso la borra de la exploracion -- el
    lockout que BL.21500/BL.21501 tuvieron que desarmar."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    # El presupuesto es de la SINTESIS entera, no de cada semilla: si no fuera asi, el costo
    # creceria linealmente con el historial de observaciones (medido: 51s en el paso 2 y 110s en el
    # paso 8) y el agente se volveria mas lento cuanto mas aprende -- exactamente al reves.
    counter = _counter_from(budget)
    if not observations:
        return _sin_hipotesis(counter)

    # DOS PASADAS, y la primera es identica a la de antes de este BL. Pasada 1: verificacion de
    # cero tolerancia con corte en el primer fallo -- si hay un programa que explica TODO se
    # devuelve sin pagar un centavo mas que el codigo viejo (es el caso comun). Pasada 2, SOLO si
    # la pasada 1 no encontro nada -- o sea, exactamente cuando el codigo viejo devolvia None --:
    # se puntua por cobertura a los candidatos YA enumerados, sin volver a buscar.
    candidatos: dict[str, Program] = {}
    exactos: dict[str, Program] = {}
    seed_order = list(reversed(observations))

    for seed in seed_order:
        # Corta tambien por el tier data-driven: en grillas por encima de
        # max_structural_search_area la BFS retorna sin gastar expansiones ni celdas, asi que ESTA
        # es la unica perilla que frena el recorrido del historial (BL.21026).
        if _sin_credito_para_otra_semilla(counter):
            break
        for candidate in _search_with_counter(seed.pre, seed.post, ctx, max_depth, counter):
            key = program_key(candidate)
            if key in candidatos:
                continue
            candidatos[key] = candidate
            if verify_program(candidate, observations, ctx):
                exactos[key] = candidate
        if exactos:
            break

    if exactos:
        program = rank_programs(list(exactos.values()))[0]
        return ScoredProgram(
            program=program,
            aciertos=len(observations),
            fallos=0,
            cobertura=1.0,
            usage=_usage_from(counter),
        )

    parciales: dict[str, tuple[Program, ProgramCoverage]] = {}
    for key, program in candidatos.items():
        # La IDENTIDAD no se acepta parcialmente: equivale a declarar no-op una accion que a veces
        # SI hace algo (el lockout de BL.21500/BL.21501). Si fuera exacta ya habria salido arriba.
        if len(program) == 0:
            continue
        puntaje = cobertura_suficiente(program, observations, ctx, min_coverage)
        if puntaje is not None:
            parciales[key] = (program, puntaje)
    if not parciales:
        return _sin_hipotesis(counter)

    mejor_cobertura = max(p.cobertura for _, p in parciales.values())
    mejores = [prog for prog, p in parciales.values() if p.cobertura == mejor_cobertura]
    program = rank_programs(mejores)[0]
    puntaje = parciales[program_key(program)][1]
    return ScoredProgram(
        program=program,
        aciertos=puntaje.aciertos,
        fallos=puntaje.fallos,
        cobertura=puntaje.cobertura,
        usage=_usage_from(counter),
    )
