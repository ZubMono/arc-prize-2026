"""[arc-agi3-kaggle-agent/tests] BL.21798 -- los cuatro contratos que faltaban alrededor del numero
que decide de BL.21794, cada uno contra un defecto MEDIDO en ese informe.

1. PARIDAD VEREDICTO / COBERTURA (RFM-06). El mismo JSON publicaba `resueltoTocandoUnObjeto` con 2
   transiciones en `candidatos` y con 3 en `coberturaDeTransiciones`: el veredicto filtra los
   eventos sin un solo frame informativo (defensa 4 de BL.21728) y la cobertura llamaba
   `se_sostiene` sin ese filtro. Dos conteos incompatibles de la misma pregunta. Ahora la regla es
   UNA (`cuenta_como_observacion`) y este test la fija por PARIDAD, no repitiendo el numero.

2. FALLA CERRADO SIN LAS VENTANAS (RFM-02). `imprimir_informe` aceptaba `ventanas=None` y las dos
   auditorias de BL.21794 se volvian un no-op silencioso que imprimia ceros: "0/0 frames traen la
   clase decidida EN LA CAPTURA", "0 sin clasificar", "ACUERDO = None". Una auditoria que existe
   para decir si un dato es del corpus o reconstruido no puede dar verde cuando su fuente no esta.

3. LA FIRMA PERSISTIDA TIENE LECTOR (RFM-08 suave). `firmaDelPaso` se escribia, viajaba a Mongo y
   volvia por el export sin un solo consumidor -- 18 apariciones en el repo, todas de escritura,
   plomeria o tests -- mientras el informe la listaba junto a `claseDePaso` como "lo que la captura
   persiste", que se lee como que las dos se chequean.

4. DE QUE CORRIDAS DEPENDE EL VEREDICTO. El "de CERO a UNO" de BL.21794 salia integro de tres
   ventanas de dos corridas: quitandolas, el gate volvia a CERO. El informe no lo decia porque nadie
   lo calculaba. Ahora hay leave-one-run-out y este test fija que detecta la corrida critica.

5. LA SEMILLA VIAJA CON LA VENTANA. Sin ella, desde el corpus no se puede saber que ventanas son
   reproducibles: el `runId` lleva el LOTE y el lote dejo de sembrar en e7f70322d1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from caracterizar_completados import imprimir_informe  # noqa: E402
from captura_de_niveles import ventanas_de_nivel  # noqa: E402,F401
from clasificacion_del_corpus import (  # noqa: E402
    auditoria_de_la_clasificacion,
    origen_de_la_muestra,
)
from corpus_persistido import Procedencia  # noqa: E402
from fragilidad_del_veredicto import fragilidad_del_veredicto  # noqa: E402
from maniobra_previa import VistaDeLaManiobra  # noqa: E402
from medicion_de_evento import MedicionDeEvento  # noqa: E402
from captura_de_niveles import (  # noqa: E402
    CLASE_DEL_EVENTO,
    CLASE_SIN_PREVIO,
)
from paso_de_la_maniobra import (  # noqa: E402
    CLASE_INERTE,
    CLASE_INFORMATIVO,
    PasoPrevio,
)
from vocabulario_de_objetivos import (  # noqa: E402
    cobertura_de_transiciones,
    cuenta_como_observacion,
    resumen_de_candidatos,
)

LADO = 8


def _tablero(pintadas: dict[tuple[int, int], int]) -> list[list[int]]:
    grilla = [[0 for _ in range(LADO)] for _ in range(LADO)]
    for (x, y), color in pintadas.items():
        grilla[y][x] = color
    return grilla


def _medicion(juego: str, celdas_por_paso: list[int], corrida: str | None = None):
    """Una medicion cuyo unico rasgo relevante son los frames de la maniobra. `celdas_por_paso` en
    cero = maniobra sin un solo frame informativo, que es la categoria que no sostiene veredictos."""
    pasos = tuple(
        PasoPrevio(paso=i, celdas_cambiadas=c, ocupacion=0.5)
        for i, c in enumerate(celdas_por_paso, start=1)
    )
    vista = VistaDeLaManiobra(
        frames_previos=10,
        pasos=pasos,
        ocupacion=tuple([0.5] * len(celdas_por_paso)),
        llenado_monotono_en_la_maniobra=True,
    )
    return MedicionDeEvento(
        juego=juego,
        corrida=corrida or f"harness-local:{juego}:lote1",
        paso_del_evento=20,
        nivel_previo=0,
        nivel_nuevo=1,
        frames_antes=10,
        frames_despues=0,
        celdas_cambiadas=10,
        fraccion_cambiada=0.01,
        pantalla_nueva=False,
        firma_del_evento="compuesta:aparicion=1",
        maniobra=vista,
    )


# --- 1. paridad entre el veredicto y la cobertura -----------------------------------------------


def _muestra_con_una_transicion_vacia():
    """Dos transiciones con frames propios (el tipo SOBREVIVE) mas una tercera que satisface el
    criterio sin un solo frame informativo. Es la forma exacta de ft09:nivel1 en el corpus real."""
    return [
        _medicion("jA", [5, 7, 9]),
        _medicion("jB", [4, 6]),
        _medicion("jC", [0, 0, 0]),
    ]


def test_la_cobertura_cuenta_con_la_MISMA_regla_que_el_veredicto():
    """PARIDAD, no un numero repetido: si manana cambia la regla, los dos lados cambian juntos o
    este test se pone rojo. El defecto medido publicaba 3 transiciones en un lado y 2 en el otro."""
    mediciones = _muestra_con_una_transicion_vacia()
    resumen = resumen_de_candidatos(mediciones)
    datos = resumen["pintarRegion"]
    assert datos["sobrevive"] is True

    cobertura = cobertura_de_transiciones(mediciones, resumen)
    cubiertas_por_el_tipo = cobertura["transicionesPorTipo"]["pintarRegion"]
    assert len(cubiertas_por_el_tipo) == datos["transicionesDistintas"]
    assert "jC:nivel1" not in cubiertas_por_el_tipo


def test_la_transicion_sin_frames_informativos_no_se_borra_del_informe_se_declara():
    """El error simetrico seria esconderla: "el juego se gana asi pero su ventana no tiene con que
    demostrarlo" es informacion, y el informe la publica en su propio campo."""
    cobertura = cobertura_de_transiciones(
        _muestra_con_una_transicion_vacia(),
        resumen_de_candidatos(_muestra_con_una_transicion_vacia()),
    )
    detalle = cobertura["porTransicion"]["jC:nivel1"]
    assert detalle["tiposQueLaCubren"] == []
    assert detalle["tiposQueLaSostienenSinFramesInformativos"] == ["pintarRegion"]
    assert cobertura["transicionesSostenidasSinFramesInformativos"] == 1
    assert cobertura["transicionesCubiertas"] == 2


def test_el_residuo_desconocido_usa_la_misma_regla_que_los_otros_dos():
    """Tercera copia de la divergencia: un evento sin frames informativos salia del residuo por un
    criterio que el propio informe no contaba como evidencia. No se puede afirmar que se conoce el
    objetivo de una ventana que no tiene un solo frame que lo respalde."""
    mediciones = _muestra_con_una_transicion_vacia()
    resumen = resumen_de_candidatos(mediciones)
    desconocidos = resumen["objetivoDesconocido"]
    # jC vuelve al residuo: antes de la correccion salia de el porque `se_sostiene` daba True.
    assert desconocidos["eventos"] == 1
    assert desconocidos["framesInformativos"] == 0
    # Y `juegos` sigue aplicando la MISMA regla (un evento sin frames informativos no es una
    # observacion ni siquiera del residuo), asi que la lista queda vacia: es coherente, no un bug.
    assert desconocidos["juegos"] == []


def test_la_regla_unica_no_toca_a_los_descriptores():
    """Un descriptor habla del frame del EVENTO, que siempre existe: filtrarlo por frames de
    maniobra lo volveria imposible de sostener. La funcion tiene que distinguir los dos tipos."""
    vacia = _medicion("jC", [0, 0, 0])
    assert cuenta_como_observacion("objetivo", vacia) is False
    assert cuenta_como_observacion("descriptor", vacia) is True


# --- 2. el informe falla cerrado si no recibe las ventanas --------------------------------------


def _procedencia_de(ventanas: int) -> Procedencia:
    return Procedencia(
        origen="arcReplayFrames",
        host="test",
        base_de_datos="test",
        filtro_run_id="^harness-local:",
        documentos_leidos=10,
        documentos_con_nivel=5,
        corridas=("harness-local:jA:lote1",),
        juegos=("jA",),
        transiciones_distintas=("jA:nivel1",),
        ventanas=ventanas,
        exportado_en="2026-08-19T22:00:00Z",
        sha256="0" * 64,
        censo={},
    )


def test_el_informe_revienta_si_le_faltan_las_ventanas_crudas():
    """RFM-02: el verde de la auditoria y el verde de "no habia nada que auditar" eran
    indistinguibles. Ahora lo segundo es una excepcion, no un cero impreso."""
    with pytest.raises(ValueError) as error:
        imprimir_informe([_medicion("jA", [5, 7])], _procedencia_de(1), [])
    assert "auditorias" in str(error.value)


def test_una_lista_de_ventanas_PARCIAL_tampoco_pasa():
    """El chequeo es contra el MANIFIESTO y no "la lista no esta vacia": auditar 1 de 33 ventanas
    daria numeros perfectamente creibles sobre una muestra que no es la que se midio."""
    with pytest.raises(ValueError) as error:
        imprimir_informe([_medicion("jA", [5, 7])], _procedencia_de(33), [{"juego": "jA"}])
    assert "33" in str(error.value)


# --- 3. la firma persistida tiene lector --------------------------------------------------------


def _frame_json(paso: int, grilla: list[list[int]], clase: str, firma: str | None = None) -> dict:
    salida: dict = {"paso": paso, "grilla": grilla, "accion": "ACTION6", "claseDePaso": clase}
    if firma is not None:
        salida["firmaDelPaso"] = firma
    return salida


def _ventana_json(frames: list[dict]) -> dict:
    return {
        "juego": "ft09",
        "corrida": "harness-local:ft09:lote1",
        "nivelNuevo": 1,
        "pasoDelEvento": frames[-1]["paso"],
        "frames": frames,
    }


def test_la_auditoria_compara_la_FIRMA_del_paso_y_no_solo_la_clase():
    quieto = _tablero({(1, 1): 5})
    movido = _tablero({(2, 1): 5})
    auditoria = auditoria_de_la_clasificacion(
        [
            _ventana_json(
                [
                    _frame_json(0, quieto, CLASE_SIN_PREVIO),
                    _frame_json(1, quieto, CLASE_INERTE, "sinCambio"),
                    _frame_json(2, movido, CLASE_INFORMATIVO, "traslacion:0,1"),
                    _frame_json(3, movido, CLASE_DEL_EVENTO),
                ]
            )
        ]
    )
    assert auditoria["framesDeManiobraConFirmaComparable"] == 2
    assert auditoria["acuerdoDeFirmas"] == 1.0
    assert auditoria["cantidadDeDiscrepanciasDeFirma"] == 0


def test_una_firma_del_corpus_que_no_coincide_se_declara():
    """La mitad que importa: si el campo no tuviera lector, una firma inventada pasaria igual --
    que es exactamente lo que pasaba hasta este BL."""
    quieto = _tablero({(1, 1): 5})
    auditoria = auditoria_de_la_clasificacion(
        [
            _ventana_json(
                [
                    _frame_json(0, quieto, CLASE_SIN_PREVIO),
                    _frame_json(1, quieto, CLASE_INERTE, "recoloreo:1>2"),  # miente: no cambio nada
                    _frame_json(2, quieto, CLASE_DEL_EVENTO),
                ]
            )
        ]
    )
    assert auditoria["cantidadDeDiscrepanciasDeFirma"] == 1
    assert auditoria["discrepanciasDeFirma"][0]["enElCorpus"] == "recoloreo:1>2"
    assert auditoria["acuerdoDeFirmas"] == 0.0


# --- 4. de que corridas depende el veredicto ----------------------------------------------------


def test_detecta_la_corrida_CRITICA_que_sostiene_sola_el_veredicto():
    """La forma exacta del corpus real: lp85:nivel2 la produjo UNA sola corrida, y sin ella el tipo
    se queda con una transicion y deja de sobrevivir."""
    mediciones = [
        _medicion("jA", [5, 7, 9], corrida="harness-local:jA:critica"),
        _medicion("jB", [4, 6], corrida="harness-local:jB:uno"),
        _medicion("jB", [4, 6], corrida="harness-local:jB:dos"),
    ]
    fragilidad = fragilidad_del_veredicto(mediciones)
    assert fragilidad["tiposQueDecidenHoy"] == ["pintarRegion"]
    assert fragilidad["elNumeroCaeQuitandoUnaSolaCorrida"] is True
    assert fragilidad["corridasCriticas"] == {"harness-local:jA:critica": ["pintarRegion"]}
    assert fragilidad["observacionesSinReplica"] == ["jA:nivel1"]


def test_un_veredicto_con_replica_no_se_marca_como_fragil():
    """El riesgo simetrico: la auditoria no puede gritar siempre, o deja de significar algo. Con
    dos corridas por transicion, quitar UNA no tumba nada."""
    mediciones = [
        _medicion("jA", [5, 7, 9], corrida="harness-local:jA:uno"),
        _medicion("jA", [5, 7, 9], corrida="harness-local:jA:dos"),
        _medicion("jB", [4, 6], corrida="harness-local:jB:uno"),
        _medicion("jB", [4, 6], corrida="harness-local:jB:dos"),
    ]
    fragilidad = fragilidad_del_veredicto(mediciones)
    assert fragilidad["tiposQueDecidenHoy"] == ["pintarRegion"]
    assert fragilidad["elNumeroCaeQuitandoUnaSolaCorrida"] is False
    assert fragilidad["corridasCriticas"] == {}
    assert fragilidad["observacionesSinReplica"] == []


def test_sin_veredicto_positivo_la_auditoria_no_inventa_fragilidad():
    fragilidad = fragilidad_del_veredicto([_medicion("jA", [0, 0])])
    assert fragilidad["tiposQueDecidenHoy"] == []
    assert fragilidad["elNumeroCaeQuitandoUnaSolaCorrida"] is False


# --- 5. la semilla viaja con la ventana ---------------------------------------------------------


class _FrameFalso:
    def __init__(self, niveles: int, valor: int = 0):
        self.frame = [[[valor for _ in range(4)] for _ in range(4)]]
        self.levels_completed = niveles
        self.win_levels = 3
        self.available_actions = [1, 2, 3, 4]
        self.state = "NOT_FINISHED"
        self.full_reset = False


def test_la_captura_persiste_la_semilla_declarada():
    ventanas = ventanas_de_nivel(
        [_FrameFalso(0), _FrameFalso(0, 1), _FrameFalso(1, 2)],
        juego="lp85",
        corrida="harness-local:lp85:20260819T163029Z-fondo30",
        modelo="harness-local",
        semilla="bl21794-f1",
    )
    assert len(ventanas) == 1
    assert ventanas[0].a_json()["semilla"] == "bl21794-f1"


def test_sin_semilla_declarada_el_campo_queda_VACIO_y_no_se_rellena_con_el_lote():
    """Rellenarlo con el lote haria pasar por reproducible una partida que no lo es: el lote lleva
    la hora y dejo de sembrar en e7f70322d1."""
    ventanas = ventanas_de_nivel(
        [_FrameFalso(0), _FrameFalso(0, 1), _FrameFalso(1, 2)],
        juego="lp85",
        corrida="harness-local:lp85:20260819T163029Z-fondo30",
        modelo="harness-local",
    )
    assert ventanas[0].a_json()["semilla"] == ""


def test_el_corpus_cuenta_cuantas_ventanas_se_pueden_regenerar():
    quieto = _tablero({(1, 1): 5})
    con_semilla = _ventana_json([_frame_json(0, quieto, CLASE_SIN_PREVIO)])
    con_semilla["semilla"] = "bl21794-f1"
    sin_semilla = _ventana_json([_frame_json(0, quieto, CLASE_SIN_PREVIO)])
    origen = origen_de_la_muestra([con_semilla, sin_semilla])
    assert origen["ventanasConSemillaDeclarada"] == 1
    assert origen["ventanasSinSemillaDeclarada"] == 1
    assert origen["semillasDeclaradas"] == ["bl21794-f1"]
