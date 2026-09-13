"""[arc-agi3-kaggle-agent/priors] BL.21560 -- ARCHIVO GENERADO por
scripts/fit_click_priors.py. NO editar a mano: regenerar con
`python3 scripts/fit_click_priors.py` y volver a correr las dos suites.

Es el UNICO conocimiento pre-computado que viaja al notebook de submission: pesos del ranker
de coordenadas (regresion logistica contra clicks REALES etiquetados con 'el click cambio la
grilla'), umbrales medidos de los detectores, orden de acciones por efectividad observada y
-- BL.21590 -- el prior de DIRECCIONES indexado por CONJUNTO DE ACCIONES DISPONIBLES.

QUE NO PUEDE CONTENER: claves con forma de game_id (`abcd-01234567`) ni de firma de estado
(entero de 32 bits). Memorizar la partida no generaliza a los juegos de evaluacion, que son
distintos por diseno. `submission/build_notebook.py` FALLA el build si alguna se cuela.

Orden de `pesosClick`: sesgo, bordeDeColor, tamanoComponente, esBordeDeComponente, rarezaDeColor, esColorDeFondo, distanciaAlBboxDeForeground, componenteRodeadaDeFondo, enRegionQueCambio.

`DIRECTION_PRIORS` es una HIPOTESIS INICIAL refutable, no una certeza cableada: siembra la
creencia y `direction_beliefs.py` la confirma, la remapea o la deja sin evidencia con lo que
vea en la partida. Fija la DIRECCION, nunca la magnitud del paso (medida: 2 a 6 celdas segun
el juego). Detalle de la medicion en el docstring de `scripts/fit_click_priors.py`.
"""
from __future__ import annotations

CLICK_PRIORS: dict = {
    "version": 1,
    "generatedAt": "2026-08-17T20:24:51Z",
    "nJuegosObservados": 5,
    "nTransicionesObservadas": 749,
    "pesosClick": [
        -2.241823,
        0.267326,
        0.23182,
        1.012707,
        -0.070761,
        -1.012849,
        -0.006758,
        -2.185072,
        -0.135375
    ],
    "umbralesDetectores": {
        "probabilidadMinimaDeClick": 0.245268,
        "similitudDeParcheMinima": 1.0
    },
    "ordenAcciones": [
        "ACTION2",
        "ACTION4",
        "ACTION3",
        "ACTION1",
        "ACTION7",
        "ACTION6",
        "ACTION5"
    ]
}

DIRECTION_PRIORS: dict = {
    "nJuegosMedidos": 25,
    "nJuegosConFlechas": 17,
    "nJuegosQueConfirman": 11,
    "nJuegosSinMovimientoObservable": 6,
    "nAccionesDeSonda": 2673,
    "traslacionesCanonicas": 528,
    "traslacionesContradictorias": 40,
    "contradiccionesSinExplicar": 0,
    "excepcionesDeMapeo": 0,
    "mapeoCanonico": {
        "ACTION1": [
            -1,
            0
        ],
        "ACTION2": [
            1,
            0
        ],
        "ACTION3": [
            0,
            -1
        ],
        "ACTION4": [
            0,
            1
        ]
    },
    "juegosQueConfirmanPorAccion": {
        "ACTION1": 10,
        "ACTION2": 10,
        "ACTION3": 9,
        "ACTION4": 9
    },
    "juegosQueContradicenPorAccion": {
        "ACTION1": 0,
        "ACTION2": 0,
        "ACTION3": 0,
        "ACTION4": 0
    },
    "conjuntosMedidos": {
        "1,2,3,4": {
            "juegos": 3,
            "confirman": 1,
            "sinMovimiento": 2
        },
        "1,2,3,4,5": {
            "juegos": 3,
            "confirman": 2,
            "sinMovimiento": 1
        },
        "1,2,3,4,5,6": {
            "juegos": 4,
            "confirman": 3,
            "sinMovimiento": 1
        },
        "1,2,3,4,5,6,7": {
            "juegos": 1,
            "confirman": 1,
            "sinMovimiento": 0
        },
        "1,2,3,4,6": {
            "juegos": 3,
            "confirman": 3,
            "sinMovimiento": 0
        },
        "1,2,3,4,6,7": {
            "juegos": 2,
            "confirman": 1,
            "sinMovimiento": 1
        },
        "3,4,6,7": {
            "juegos": 1,
            "confirman": 0,
            "sinMovimiento": 1
        },
        "5,6,7": {
            "juegos": 1,
            "confirman": 0,
            "sinMovimiento": 1
        },
        "6": {
            "juegos": 6,
            "confirman": 0,
            "sinMovimiento": 6
        },
        "6,7": {
            "juegos": 1,
            "confirman": 0,
            "sinMovimiento": 1
        }
    },
    "accionesSinPriorDeDireccion": [
        "ACTION5",
        "ACTION6",
        "ACTION7"
    ],
    "semanticaAction5": {
        "juegosMedidos": 12,
        "comportamientosDistintos": 4,
        "juegosConDireccionConsistente": 0
    },
    "magnitudesDePasoMedidas": [
        2,
        3,
        4,
        5,
        6
    ]
}
