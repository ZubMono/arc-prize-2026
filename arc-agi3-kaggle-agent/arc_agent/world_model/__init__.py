"""[arc-agi3-kaggle-agent/world_model] -- motor de modelo de mundo: DSL de transformaciones
grilla-a-grilla, sintesis bottom-up de programas y planificacion sobre lo aprendido. Puerto
auto-contenido (solo stdlib) de projects/arc-agi-runner/src/worldModel.

Barrel sin logica: solo re-exporta la superficie publica de los 11 modulos. NO entra en
MODULE_ORDER de submission/build_notebook.py -- en el notebook de Kaggle todo vive en un unico
namespace plano y un barrel no aporta nada ahi (igual que local_harness.py, que tampoco viaja).
"""
from __future__ import annotations

from .grid import FNV_OFFSET_BASIS, FNV_PRIME, MASK32, ROW_SEPARATOR
from .grid import VOLATILE_CELL_HASH_PLACEHOLDER
from .grid import BoundingBox, Grid, GridDimensions, VolatilityMask
from .grid import cell_diff_count, clone_grid, detect_background_color
from .grid import foreground_bounding_box, grid_dimensions, grids_equal, hash_grid
from .grid import grids_equal_masked, hash_grid_masked, is_volatile_cell
from .grid import neutralize_volatile_cells
from .volatility_mask import SWEEP_ENTRY_RATIO, SWEEP_EXIT_RATIO, SWEEP_ISOLATION_RADIUS
from .volatility_mask import SWEEP_MIN_CELLS, SWEEP_MIN_ISOLATION_RATIO, SWEEP_MIN_TRANSITIONS
from .volatility_mask import VOLATILITY_ENTRY_RATIO, VOLATILITY_EXIT_RATIO
from .volatility_mask import VOLATILITY_MAX_FRACTION, VOLATILITY_MIN_DISTINCT_ACTIONS
from .volatility_mask import VOLATILITY_MIN_TRANSITIONS, VolatilityTracker
from .primitive_ops import EMPTY_CONTEXT, PARAM_KEY_ORDER, PROGRAM_STEP_NAMES
from .primitive_ops import ConditionalRecolorParams, CropToBBoxParams, FloodFillParams
from .primitive_ops import ObjectExtractParams, OverlayParams, PrimitiveContext
from .primitive_ops import Program, ProgramStep, RecolorParams, ReflectParams
from .primitive_ops import ReplicateParams, RotateParams, TranslateParams
from .primitive_ops import apply_program, apply_step, compare_program_keys
from .primitive_ops import make_conditional_recolor, make_crop_to_bbox, make_flood_fill
from .primitive_ops import make_object_extract, make_overlay, make_recolor, make_reflect
from .primitive_ops import make_replicate, make_rotate, make_translate
from .primitive_ops import program_key, program_to_json, step_to_json
# BL.21560 -- segmentacion en componentes 4-conexas. Se re-exporta (con su nombre privado intacto,
# para no duplicar identidad) porque click_targeting.py deriva de ella el tamano de la componente de
# cada celda: es la MISMA segmentacion que usa el DSL, no una copia paralela. El import tiene que
# ser de UN solo nivel (`.world_model`) para que el builder del notebook lo desmonte.
from .primitive_ops import _find_components
from .primitives import enumerate_structural_steps, propose_all_steps
from .object_geometry import RADIO_DE_FONDO_LOCAL, agrupar_en_clusters, caja_de_celdas
from .object_geometry import cobertura_de_objetos, fondo_local
from .object_geometry import MAX_CELDAS_DE_OBJETO_ENTERO, MAX_PARES_DE_OBJETO
from .object_geometry import forma_con_color, objetos_que_tocan, traslacion_de_objeto_entero
from .object_mechanics import MAX_AREA_CAJA_DE_CAMBIOS, MAX_CELDAS_CAMBIADAS
from .object_mechanics import MAX_TAMANO_OBJETO, MIN_EVIDENCIA_DE_OBJETO, TIPOS_DE_MECANICA
from .object_mechanics import TIPOS_DE_NO_MIRE, TIPO_SIN_MEDICION
from .object_mechanics import TIPO_SIN_NOMBRAR
from .object_mechanics import CambioDeColor, Mecanica, MecanicaDeCluster, Traslacion
from .object_mechanics import detectar_mecanica
# BL.21741 (correccion): la capa de VOCABULARIO vive en `mechanics_signature`, no en
# `object_mechanics` -- detectar y nombrar son dos responsabilidades y el archivo cruzaba el
# limite de 500 lineas del repo.
from .mechanics_signature import CORTES_DE_CUBO, PREFIJO_DE_FIRMA_COMPUESTA
from .mechanics_signature import conteo_de_tipos_de_cluster, es_firma_de_silencio
from .mechanics_signature import firma_compuesta, firma_de_mecanica
from .mechanics_memory import MIN_CAMBIOS_DE_CONTADOR, MIN_COBERTURA_DE_MECANICA
from .mechanics_memory import MIN_OBSERVACIONES_DE_MECANICA
from .mechanics_memory import ContadorDeColor, HipotesisDeMecanica, MechanicsMemory
# BL.21704 -- causa a distancia. Va DESPUES de object_mechanics porque la exclusion por
# detectores locales corre con `detectar_mecanica` (el detector REAL, nunca una aproximacion).
from .regiones_de_cambio import FRACCION_DE_PASO_MASIVO, JACCARD_DE_FUSION, MAX_REGIONES
from .regiones_de_cambio import MAX_PASOS_RETENIDOS, SEPARACION_CHEBYSHEV_MINIMA
from .regiones_de_cambio import HistorialDeCambios, PasoObservado, RegionDeCambio
from .regiones_de_cambio import MAX_GRUPOS_A_FUSIONAR, MAX_PARTES_POR_FIRMA
from .regiones_de_cambio import cajas_explicadas_por_locales, separacion_chebyshev
from .estadistica_de_coocurrencia import ALFA_BH, BARAJAS_DEL_NULO, DIRECCIONES_POR_PAR
from .estadistica_de_coocurrencia import MIN_SOPORTE, PERCENTIL_DEL_NULO
from .estadistica_de_coocurrencia import cola_binomial, coocurrencias, desplazamientos_del_nulo
from .estadistica_de_coocurrencia import indice_de_corte_bh, rotar_circular
from .estadistica_de_coocurrencia import umbral_del_nulo_empirico
from .evidencia_relacional import APORTE_INTERVENCIONAL, APORTE_OBSERVACIONAL
from .evidencia_relacional import CASTIGO_INTERVENCIONAL, CONFIRMACIONES_REQUERIDAS
from .evidencia_relacional import INTENTOS_DE_CONFIRMACION, LOG_ODDS_INICIAL
from .evidencia_relacional import PISO_DE_EVIDENCIA_PARA_SUBMETA, TOPE_DE_APORTE_OBSERVACIONAL
from .evidencia_relacional import Candidato, RelacionNoLocal, SubMeta, clave_de_relacion
from .relaciones_no_locales import FRACCION_EXPLICADA_POR_LOCALES, INTERVALO_DE_MINERIA
from .relaciones_no_locales import MAX_INTERVENCIONES_POR_PARTIDA, PASOS_MINIMOS_PARA_MINAR
from .relaciones_no_locales import PUREZA_MINIMA_DE_ACCION, TOPE_DE_VOCABULARIO
from .relaciones_no_locales import MAX_EXPLOTACIONES_DE_SUBMETA
from .relaciones_no_locales import PASOS_SIN_CAMBIO_PARA_SUBMETA
from .relaciones_no_locales import AlmacenDeRelaciones
from .program_coverage import MIN_PROGRAM_COVERAGE, ProgramCoverage, program_coverage
from .program_coverage import cobertura_suficiente
from .synthesis import DEFAULT_MAX_CELLS_TOUCHED, DEFAULT_MAX_DEPTH
from .synthesis import DEFAULT_MAX_INTERMEDIATE_AREA_RATIO, DEFAULT_MAX_SEED_SWEEP_CELLS
from .synthesis import DEFAULT_MAX_STRUCTURAL_SEARCH_AREA, DEFAULT_SYNTHESIS_BUDGET
from .synthesis import MAX_NODE_EXPANSIONS, PROPOSER_PASSES_PER_SWEEP
from .synthesis import Observation, SearchResult, SynthesisBudget, SynthesisResult
from .synthesis import SynthesisUsage, program_complexity, rank_programs, search_programs
from .synthesis import search_programs_with_usage, synthesize_program
from .synthesis import synthesize_program_with_usage, verify_program
from .synthesis import ScoredProgram, synthesize_program_scored
from .transition_memory import MAX_MASK_REVISIONS_RESYNTHESIZED
from .transition_memory import MAX_OBSERVATIONS_PER_ACTION, SYNTHESIS_MAX_DEPTH
from .transition_memory import KnownTransition, TransitionMemory
from .planner import PlanOptions, PlanResult, TransitionPredictor
from .planner import estimate_distance, plan_actions
from .state_signature import FrameLike, compute_frame_signature, compute_state_signature
from .state_signature import extract_grid, extraer_grid_multicapa, is_no_op_transition

__all__ = [
    # grid
    "Grid",
    "BoundingBox",
    "GridDimensions",
    "MASK32",
    "FNV_OFFSET_BASIS",
    "FNV_PRIME",
    "ROW_SEPARATOR",
    "clone_grid",
    "grid_dimensions",
    "grids_equal",
    "cell_diff_count",
    "detect_background_color",
    "foreground_bounding_box",
    "hash_grid",
    # grid -- BL.21558, comparacion/hash enmascarados por volatilidad
    "VolatilityMask",
    "VOLATILE_CELL_HASH_PLACEHOLDER",
    "is_volatile_cell",
    "grids_equal_masked",
    "hash_grid_masked",
    "neutralize_volatile_cells",
    # volatility_mask -- BL.21558
    "VolatilityTracker",
    "VOLATILITY_MIN_TRANSITIONS",
    "VOLATILITY_MIN_DISTINCT_ACTIONS",
    "VOLATILITY_ENTRY_RATIO",
    "VOLATILITY_EXIT_RATIO",
    "VOLATILITY_MAX_FRACTION",
    "SWEEP_MIN_CELLS",
    "SWEEP_MIN_TRANSITIONS",
    "SWEEP_ENTRY_RATIO",
    "SWEEP_EXIT_RATIO",
    "SWEEP_ISOLATION_RADIUS",
    "SWEEP_MIN_ISOLATION_RATIO",
    # primitive_ops -- tipos del DSL
    "ProgramStep",
    "Program",
    "TranslateParams",
    "ReflectParams",
    "RotateParams",
    "RecolorParams",
    "FloodFillParams",
    "CropToBBoxParams",
    "ReplicateParams",
    "ObjectExtractParams",
    "OverlayParams",
    "ConditionalRecolorParams",
    "PROGRAM_STEP_NAMES",
    "PARAM_KEY_ORDER",
    # primitive_ops -- constructores, contexto, serializacion y ejecucion
    "make_translate",
    "make_reflect",
    "make_rotate",
    "make_recolor",
    "make_flood_fill",
    "make_crop_to_bbox",
    "make_overlay",
    "make_replicate",
    "make_object_extract",
    "make_conditional_recolor",
    "PrimitiveContext",
    "EMPTY_CONTEXT",
    "step_to_json",
    "program_to_json",
    "program_key",
    "compare_program_keys",
    "apply_step",
    "apply_program",
    "_find_components",
    # primitives
    "propose_all_steps",
    "enumerate_structural_steps",
    # object_geometry / object_mechanics / mechanics_memory -- BL.21561
    "RADIO_DE_FONDO_LOCAL",
    "MAX_CELDAS_DE_OBJETO_ENTERO",
    "MAX_PARES_DE_OBJETO",
    "forma_con_color",
    "objetos_que_tocan",
    "traslacion_de_objeto_entero",
    "agrupar_en_clusters",
    "caja_de_celdas",
    "cobertura_de_objetos",
    "fondo_local",
    "MAX_AREA_CAJA_DE_CAMBIOS",
    "MAX_CELDAS_CAMBIADAS",
    "MAX_TAMANO_OBJETO",
    "MIN_EVIDENCIA_DE_OBJETO",
    "TIPOS_DE_MECANICA",
    "TIPOS_DE_NO_MIRE",
    "TIPO_SIN_MEDICION",
    "CORTES_DE_CUBO",
    "PREFIJO_DE_FIRMA_COMPUESTA",
    "TIPO_SIN_NOMBRAR",
    "es_firma_de_silencio",
    "Traslacion",
    "CambioDeColor",
    "MecanicaDeCluster",
    "Mecanica",
    "detectar_mecanica",
    "firma_de_mecanica",
    "firma_compuesta",
    "conteo_de_tipos_de_cluster",
    "MIN_OBSERVACIONES_DE_MECANICA",
    "MIN_COBERTURA_DE_MECANICA",
    "MIN_CAMBIOS_DE_CONTADOR",
    "HipotesisDeMecanica",
    "ContadorDeColor",
    "MechanicsMemory",
    # regiones_de_cambio / estadistica_de_coocurrencia / evidencia_relacional /
    # relaciones_no_locales -- BL.21704 (causa a distancia)
    "FRACCION_DE_PASO_MASIVO",
    "JACCARD_DE_FUSION",
    "MAX_REGIONES",
    "MAX_PARTES_POR_FIRMA",
    "MAX_GRUPOS_A_FUSIONAR",
    "MAX_PASOS_RETENIDOS",
    "SEPARACION_CHEBYSHEV_MINIMA",
    "RegionDeCambio",
    "PasoObservado",
    "HistorialDeCambios",
    "cajas_explicadas_por_locales",
    "separacion_chebyshev",
    "MIN_SOPORTE",
    "ALFA_BH",
    "DIRECCIONES_POR_PAR",
    "BARAJAS_DEL_NULO",
    "PERCENTIL_DEL_NULO",
    "cola_binomial",
    "indice_de_corte_bh",
    "desplazamientos_del_nulo",
    "rotar_circular",
    "coocurrencias",
    "umbral_del_nulo_empirico",
    "CONFIRMACIONES_REQUERIDAS",
    "INTENTOS_DE_CONFIRMACION",
    "LOG_ODDS_INICIAL",
    "APORTE_OBSERVACIONAL",
    "TOPE_DE_APORTE_OBSERVACIONAL",
    "APORTE_INTERVENCIONAL",
    "CASTIGO_INTERVENCIONAL",
    "PISO_DE_EVIDENCIA_PARA_SUBMETA",
    "clave_de_relacion",
    "Candidato",
    "RelacionNoLocal",
    "SubMeta",
    "PUREZA_MINIMA_DE_ACCION",
    "FRACCION_EXPLICADA_POR_LOCALES",
    "TOPE_DE_VOCABULARIO",
    "INTERVALO_DE_MINERIA",
    "PASOS_MINIMOS_PARA_MINAR",
    "MAX_INTERVENCIONES_POR_PARTIDA",
    "AlmacenDeRelaciones",
    "MAX_EXPLOTACIONES_DE_SUBMETA",
    "PASOS_SIN_CAMBIO_PARA_SUBMETA",
    # synthesis
    "DEFAULT_MAX_DEPTH",
    "MAX_NODE_EXPANSIONS",
    "DEFAULT_MAX_CELLS_TOUCHED",
    "DEFAULT_MAX_INTERMEDIATE_AREA_RATIO",
    "DEFAULT_MAX_STRUCTURAL_SEARCH_AREA",
    "PROPOSER_PASSES_PER_SWEEP",
    "DEFAULT_MAX_SEED_SWEEP_CELLS",
    "SynthesisBudget",
    "DEFAULT_SYNTHESIS_BUDGET",
    "SynthesisUsage",
    "Observation",
    "program_complexity",
    "rank_programs",
    "search_programs",
    "SearchResult",
    "search_programs_with_usage",
    "verify_program",
    "MIN_PROGRAM_COVERAGE",
    "ProgramCoverage",
    "program_coverage",
    "cobertura_suficiente",
    "ScoredProgram",
    "synthesize_program_scored",
    "synthesize_program",
    "SynthesisResult",
    "synthesize_program_with_usage",
    # transition_memory
    "MAX_OBSERVATIONS_PER_ACTION",
    "SYNTHESIS_MAX_DEPTH",
    "MAX_MASK_REVISIONS_RESYNTHESIZED",
    "KnownTransition",
    "TransitionMemory",
    # planner
    "TransitionPredictor",
    "PlanOptions",
    "PlanResult",
    "estimate_distance",
    "plan_actions",
    # state_signature
    "FrameLike",
    "extract_grid",
    "extraer_grid_multicapa",
    "compute_frame_signature",
    "compute_state_signature",
    "is_no_op_transition",
]
