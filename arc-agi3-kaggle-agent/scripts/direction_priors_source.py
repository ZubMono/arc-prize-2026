"""[arc-agi3-kaggle-agent/scripts/direction_priors_source] BL.21590 -- FUENTE UNICA del prior de
DIRECCIONES: la tabla medida y el emisor del puerto TypeScript. Lo consume
`scripts/fit_click_priors.py`, que escribe los dos puertos (`arc_agent/priors.py` y
`arc-agi-runner/src/worldModel/directionPriors.ts`) en una sola corrida.

POR QUE VIVE SEPARADO DEL AJUSTE. Los pesos del ranker de clicks se AJUSTAN desde un corpus; esto
se TRANSCRIBE de una medicion. Mezclarlos en un archivo dejaba el generador arriba del limite de
500 lineas y confundia dos cosas distintas: una regresion y un experimento.

LA MEDICION. Sonda contra la API oficial de ARC-AGI-3 sobre los 25 juegos publicos: 72 runIds,
2.673 acciones de juego, 2.757 frames persistidos en `arcReplayFrames` (modelId `bl21590-probe`).
Detector `detectar_mecanica` de BL.21561 sin tocar (parametrico, nunca mira game_id) + mascara
`VolatilityTracker` de BL.21558. Cero LLM.

DOS LECCIONES DE METODO QUE EL PRIOR CODIFICA:

1. PANTALLA DE TITULO. Cinco juegos arrancan en un estado donde las flechas no tocan el tablero:
   sin clicks previos daban ACTION1 == ACTION3 y ACTION2 == ACTION4, o sea un mapeo imposible. Tras
   nueve clicks el mapeo canonico salio limpio. Quien mide sin clickear primero mide el menu.
2. EL ROUND-ROBIN FABRICA MAPEOS INVERTIDOS. Con protocolo 1,2,3,4 ciclico un juego dio ACTION4 ->
   izquierda 20 veces contra derecha 6. Con protocolo GUIONADO (la MISMA accion N veces seguidas,
   siguiendo la posicion absoluta del objeto) se cayo: A3 x8 movio minX 39->35->31->27 y A4 x14 lo
   devolvio. La inversion era la ambiguedad objeto/hueco de BL.21561, que bajo oscilacion desempata
   de forma SISTEMATICAMENTE equivocada. Por eso remapear exige contradicciones CONSECUTIVAS y
   coherentes entre si, y no una sola observacion.

QUE DICE LA MEDICION, sin adornos: CERO excepciones de MAPEO en 25 juegos. Pero SI hay excepciones
al supuesto "las flechas mueven": 6 de los 17 juegos con flechas no producen una sola traslacion
(flechas inertes, un eje muerto, o las cuatro acciones indistinguibles entre si). La universalidad
esta CONFIRMADA en 11 juegos y NO FALSIFICADA en 6 -- evidencia de "cero contraejemplos", no de
"verificado en los 17". Si un juego privado se comporta como esos 6, el prior degrada a
"sinEvidencia" y se sigue midiendo; no se da el mapeo por hecho.
"""
from __future__ import annotations

import json
import re

#: SE INDEXA POR CONJUNTO DE ACCIONES DISPONIBLES, JAMAS POR game_id: los juegos de la evaluacion
#: son privados y toda clave por partida vale cero ahi. `available_actions` viene en cada frame y
#: existe igual en los juegos privados.
#:
#: LA MAGNITUD NO ENTRA. Se midieron pasos de 2, 3, 4, 5 y 6 celdas segun el juego: el prior fija la
#: DIRECCION, la magnitud se mide en partida.
DIRECCIONES_MEDIDAS: dict = {
    "nJuegosMedidos": 25,
    "nJuegosConFlechas": 17,
    "nJuegosQueConfirman": 11,
    "nJuegosSinMovimientoObservable": 6,
    "nAccionesDeSonda": 2673,
    "traslacionesCanonicas": 528,
    "traslacionesContradictorias": 40,
    "contradiccionesSinExplicar": 0,
    "excepcionesDeMapeo": 0,
    # (dy, dx) NORMALIZADOS A SIGNO. y crece hacia abajo, x hacia la derecha.
    "mapeoCanonico": {
        "ACTION1": [-1, 0],
        "ACTION2": [1, 0],
        "ACTION3": [0, -1],
        "ACTION4": [0, 1],
    },
    "juegosQueConfirmanPorAccion": {
        "ACTION1": 10,
        "ACTION2": 10,
        "ACTION3": 9,
        "ACTION4": 9,
    },
    "juegosQueContradicenPorAccion": {
        "ACTION1": 0,
        "ACTION2": 0,
        "ACTION3": 0,
        "ACTION4": 0,
    },
    # clave = conjunto de acciones disponibles, numeros ordenados y separados por coma (la forma
    # canonica que produce `clave_de_conjunto`). `confirman` cuenta los juegos del conjunto donde al
    # menos una flecha dio traslacion canonica; `sinMovimiento`, los que no dieron ninguna.
    "conjuntosMedidos": {
        "1,2,3,4": {"juegos": 3, "confirman": 1, "sinMovimiento": 2},
        "1,2,3,4,5": {"juegos": 3, "confirman": 2, "sinMovimiento": 1},
        "1,2,3,4,5,6": {"juegos": 4, "confirman": 3, "sinMovimiento": 1},
        "1,2,3,4,5,6,7": {"juegos": 1, "confirman": 1, "sinMovimiento": 0},
        "1,2,3,4,6": {"juegos": 3, "confirman": 3, "sinMovimiento": 0},
        "1,2,3,4,6,7": {"juegos": 2, "confirman": 1, "sinMovimiento": 1},
        "3,4,6,7": {"juegos": 1, "confirman": 0, "sinMovimiento": 1},
        "5,6,7": {"juegos": 1, "confirman": 0, "sinMovimiento": 1},
        "6": {"juegos": 6, "confirman": 0, "sinMovimiento": 6},
        "6,7": {"juegos": 1, "confirman": 0, "sinMovimiento": 1},
    },
    # ACTION5/6/7 NO tienen prior de direccion y es un RESULTADO, no una omision: en 12 juegos
    # ACTION5 dio cuatro comportamientos distintos (inerte, toggle, recoloreo constante, cambio
    # masivo de escena) y en NINGUNO se comporto como una direccion repetible. ACTION7 igual: alias
    # de ACTION1 en un juego, teleport en otro, inerte en tres.
    "accionesSinPriorDeDireccion": ["ACTION5", "ACTION6", "ACTION7"],
    "semanticaAction5": {
        "juegosMedidos": 12,
        "comportamientosDistintos": 4,
        "juegosConDireccionConsistente": 0,
    },
    "magnitudesDePasoMedidas": [2, 3, 4, 5, 6],
}


_IDENTIFICADOR_TS = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _clave_ts(clave: str) -> str:
    """Clave de objeto en el estilo de Prettier (`quoteProps: as-needed`, que es lo que el hook de
    pre-commit aplica sobre el archivo emitido): sin comillas si es un identificador valido,
    entre comillas si no (`'1,2,3,4'` no compila sin ellas)."""
    return clave if _IDENTIFICADOR_TS.match(clave) else f"'{clave}'"


def _ts_desde_json(valor: object, sangria: int) -> str:
    """Serializa un valor JSON como literal TypeScript, byte a byte igual a lo que Prettier deja:
    si el emisor y el formateador difieren, cada regeneracion ensucia el diff."""
    espacios = " " * sangria
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        lineas = [
            f"{espacios}  {_clave_ts(clave)}: {_ts_desde_json(sub, sangria + 2)},"
            for clave, sub in valor.items()
        ]
        return "{\n" + "\n".join(lineas) + f"\n{espacios}}}"
    if isinstance(valor, list):
        return "[" + ", ".join(_ts_desde_json(v, sangria) for v in valor) + "]"
    if isinstance(valor, str):
        return f"'{valor}'"
    return json.dumps(valor)


def emitir_typescript_direcciones(direcciones: dict, generado_en: str, version: int) -> str:
    cuerpo = _ts_desde_json(
        {"version": version, "generatedAt": generado_en, **direcciones}, 0
    )
    return (
        "/* [arc-agi-runner/worldModel/directionPriors] BL.21590 -- ARCHIVO GENERADO por\n"
        "   arc-agi3-kaggle-agent/scripts/fit_click_priors.py. NO editar a mano.\n"
        "\n"
        "   Los MISMOS numeros que `DIRECTION_PRIORS` de `arc_agent/priors.py`: un solo lugar los\n"
        "   emite, dos puertos los consumen. Prior de direcciones indexado por CONJUNTO DE ACCIONES\n"
        "   DISPONIBLES -- jamas por game_id, que en la evaluacion privada vale cero.\n"
        "\n"
        "   Es una HIPOTESIS INICIAL REFUTABLE: `directionBeliefs.ts` la confirma o la remapea con\n"
        "   una CORRIDA MONOTONA (traslaciones del mismo signo en pulsaciones consecutivas de la\n"
        "   misma accion -- la macro de BL.21559 la produce gratis), y la deja en 'sinEvidencia'\n"
        "   cuando la flecha no mueve nada. Fija la DIRECCION, nunca la magnitud. */\n"
        "\n"
        "export interface ConfianzaDeConjunto {\n"
        "  juegos: number;\n"
        "  confirman: number;\n"
        "  sinMovimiento: number;\n"
        "}\n"
        "\n"
        "export interface DirectionPriors {\n"
        "  version: number;\n"
        "  generatedAt: string;\n"
        "  nJuegosMedidos: number;\n"
        "  nJuegosConFlechas: number;\n"
        "  nJuegosQueConfirman: number;\n"
        "  nJuegosSinMovimientoObservable: number;\n"
        "  nAccionesDeSonda: number;\n"
        "  traslacionesCanonicas: number;\n"
        "  traslacionesContradictorias: number;\n"
        "  contradiccionesSinExplicar: number;\n"
        "  excepcionesDeMapeo: number;\n"
        "  /** (dy, dx) normalizados a SIGNO -- y crece hacia abajo, x hacia la derecha. */\n"
        "  mapeoCanonico: Readonly<Record<string, readonly number[]>>;\n"
        "  juegosQueConfirmanPorAccion: Readonly<Record<string, number>>;\n"
        "  juegosQueContradicenPorAccion: Readonly<Record<string, number>>;\n"
        "  /** Clave = numeros de accion disponibles, ordenados y separados por coma. */\n"
        "  conjuntosMedidos: Readonly<Record<string, ConfianzaDeConjunto>>;\n"
        "  accionesSinPriorDeDireccion: readonly string[];\n"
        "  semanticaAction5: {\n"
        "    juegosMedidos: number;\n"
        "    comportamientosDistintos: number;\n"
        "    juegosConDireccionConsistente: number;\n"
        "  };\n"
        "  magnitudesDePasoMedidas: readonly number[];\n"
        "}\n"
        "\n"
        f"export const DIRECTION_PRIORS: DirectionPriors = {cuerpo};\n"
    )
