"""[arc-agi3-kaggle-agent/scripts/fit_click_priors] BL.21560 -- ajusta los PRIORS DE CLICK contra el
corpus REAL de partidas y los emite a los dos puertos (`arc_agent/priors.py` y
`arc-agi-runner/src/worldModel/clickPriors.ts`).

QUE AJUSTA Y CON QUE ETIQUETA. Regresion logistica (descenso de gradiente, solo stdlib -- el
proyecto no tiene dependencias de runtime) sobre las features por celda de `click_targeting.py`.
La etiqueta es AUTO-SUPERVISADA: "el click cambio la grilla". No hace falta haber ganado nunca, que
es justamente lo que la hace utilizable hoy -- el agente todavia no gano una sola partida.

DE DONDE SALE EL DATO. Dos fixtures REALES, grabados contra la API oficial de ARC-AGI-3:
  * clickRealFrames.json  -- clicks con coordenada y resultado (pesos del ranker).
  * volatilityRealGames.json -- partidas con todas las acciones (orden de acciones por efectividad).
Los dos viven en `arc-agi-runner/src/worldModel/__fixtures__/` y se resuelven por ruta relativa: si
este proyecto se extrae del monorepo, el script avisa y no escribe nada (los priors ya generados
siguen siendo validos; lo que no se puede es re-ajustarlos sin el corpus).

QUE NO PUEDE ENTRAR EN LOS PRIORS. Ninguna clave con forma de game_id ni de firma de estado:
memorizar la partida no generaliza a los juegos de evaluacion. `submission/build_notebook.py` FALLA
el build si alguna se cuela -- este script no es la unica linea de defensa.

Correr: `cd projects/arc-agi3-kaggle-agent && python3 scripts/fit_click_priors.py`
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# BL.21590 -- tabla medida del prior de direcciones + emisor de su puerto TypeScript. Vive en su
# propio modulo: aca se AJUSTA una regresion, alla se TRANSCRIBE una medicion.
from direction_priors_source import (  # noqa: E402 -- sys.path se ajusta arriba
    DIRECCIONES_MEDIDAS,
    emitir_typescript_direcciones,
)
from arc_agent.click_targeting import (  # noqa: E402 -- sys.path se ajusta arriba
    CLICK_FEATURE_NAMES,
    ClickFeatureBoard,
    extraer_parche,
    region_que_cambio,
    similitud_de_parche,
)

FIXTURES = PROJECT_ROOT.parent / "arc-agi-runner" / "src" / "worldModel" / "__fixtures__"
FIXTURE_CLICKS = FIXTURES / "clickRealFrames.json"
FIXTURE_PARTIDAS = FIXTURES / "volatilityRealGames.json"
SALIDA_PY = PROJECT_ROOT / "arc_agent" / "priors.py"
SALIDA_TS = (
    PROJECT_ROOT.parent / "arc-agi-runner" / "src" / "worldModel" / "clickPriors.ts"
)
SALIDA_TS_DIRECCIONES = (
    PROJECT_ROOT.parent / "arc-agi-runner" / "src" / "worldModel" / "directionPriors.ts"
)

#: Version del CONTRATO de priors.py. Sube cuando cambia la forma del dict o el orden de features,
#: no cuando cambian los numeros: un consumidor pineado tiene que poder detectar la incompatibilidad.
VERSION_PRIORS = 1

#: Hiperparametros del ajuste. Fijos y sin busqueda: el corpus es chico y una busqueda sobre 346
#: muestras ajustaria el ruido.
ITERACIONES = 4000
TASA_APRENDIZAJE = 0.5

#: L2 sobre todos los pesos menos el sesgo. NO es cosmetico: con L2=1e-3 el ajuste sobre UN solo
#: juego le daba -5.79 a `componenteRodeadaDeFondo` (separa ft09 perfecto) y esa sola feature
#: mandaba la partida. Medido contra la API oficial en lp85-305b61c3, un juego que NO esta en el
#: corpus: el agente gasto 403 de 499 clicks en la cenefa decorativa -- que ahi es justo lo que NO
#: toca el fondo -- y acerto 0. Con L2=0.01 el AUC sobre ft09 sigue siendo 1,00 y el peso maximo
#: baja de 5,79 a 2,24: el prior sigue ordenando, pero ya no puede aplastar a la evidencia que el
#: agente junta DENTRO del episodio (plantillas y anti-plantillas, que valen +-6). Un prior de un
#: solo juego tiene que ser una sugerencia, no una orden.
L2 = 0.01

#: Un paso de la grabacion de partidas cuenta como "la accion movio el tablero" si cambio MAS de una
#: celda: la barra de progreso de ARC-AGI-3 avanza exactamente una celda por paso pase lo que pase
#: (BL.21558), asi que 1 celda es el piso de ruido, no evidencia.
CELDAS_MINIMAS_PARA_EFECTO = 1


def _aplicar_diff(grid: list[list[int]], diff: list[int]) -> list[list[int]]:
    nueva = [fila[:] for fila in grid]
    for i in range(0, len(diff), 3):
        y, x, valor = diff[i], diff[i + 1], diff[i + 2]
        nueva[y][x] = valor
    return nueva


def cargar_muestras() -> tuple[list[tuple[list[float], int]], int, int, list[dict]]:
    """Devuelve (muestras, n_partidas, n_transiciones, clicks_crudos).

    `clicks_crudos` conserva x, y, la etiqueta y el indice de partida para poder medir sobre las
    mismas coordenadas sin re-derivar nada."""
    datos = json.loads(FIXTURE_CLICKS.read_text(encoding="utf-8"))
    muestras: list[tuple[list[float], int]] = []
    crudos: list[dict] = []
    transiciones = 0

    for indice, partida in enumerate(datos["partidas"]):
        grid = [list(fila) for fila in partida["base"]]
        previa: list[list[int]] | None = None
        for paso in partida["pasos"]:
            siguiente = _aplicar_diff(grid, paso["diff"])
            transiciones += 1
            if paso.get("x") is not None:
                region = region_que_cambio(previa, grid)
                tablero = ClickFeatureBoard(grid, region)
                features = tablero.features(paso["x"], paso["y"])
                etiqueta = 1 if paso["diff"] else 0
                muestras.append((features, etiqueta))
                crudos.append(
                    {
                        "partida": indice,
                        "x": paso["x"],
                        "y": paso["y"],
                        "etiqueta": etiqueta,
                        "grid": grid,
                        "region": region,
                    }
                )
            previa = grid
            grid = siguiente

    return muestras, len(datos["partidas"]), transiciones, crudos


def ajustar(
    muestras: list[tuple[list[float], int]], n_features: int
) -> list[float]:
    """Descenso de gradiente batch sobre la log-verosimilitud logistica, con L2 sobre todos los
    pesos MENOS el sesgo (regularizar el sesgo desplazaria la tasa base aprendida)."""
    pesos = [0.0] * n_features
    n = len(muestras)
    if n == 0:
        return pesos
    for _ in range(ITERACIONES):
        gradiente = [0.0] * n_features
        for features, etiqueta in muestras:
            z = sum(f * p for f, p in zip(features, pesos))
            # sigmoide estable por rama
            pred = 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))
            error = pred - etiqueta
            for i, f in enumerate(features):
                gradiente[i] += error * f
        for i in range(n_features):
            reg = 0.0 if i == 0 else L2 * pesos[i]
            pesos[i] -= TASA_APRENDIZAJE * (gradiente[i] / n + reg)
    return pesos


def auc(muestras: list[tuple[list[float], int]], pesos: list[float]) -> float:
    """Area bajo la curva ROC por conteo de pares concordantes (empates = medio par)."""
    puntajes = [
        (sum(f * p for f, p in zip(features, pesos)), etiqueta)
        for features, etiqueta in muestras
    ]
    positivos = [s for s, e in puntajes if e == 1]
    negativos = [s for s, e in puntajes if e == 0]
    if not positivos or not negativos:
        return 0.5
    concordantes = 0.0
    for p in positivos:
        for n in negativos:
            concordantes += 1.0 if p > n else (0.5 if p == n else 0.0)
    return concordantes / (len(positivos) * len(negativos))


def mejor_umbral(muestras: list[tuple[list[float], int]], pesos: list[float]) -> float:
    """Probabilidad de corte que maximiza F1 sobre el corpus. Se transporta como
    `probabilidadMinimaDeClick`: es el punto donde el ranker deja de estar adivinando."""
    puntajes = sorted(
        (
            1 / (1 + math.exp(-sum(f * p for f, p in zip(features, pesos)))),
            etiqueta,
        )
        for features, etiqueta in muestras
    )
    total_positivos = sum(e for _, e in puntajes)
    mejor_f1 = -1.0
    mejor = 0.5
    for corte, _ in puntajes:
        tp = sum(1 for prob, e in puntajes if prob >= corte and e == 1)
        fp = sum(1 for prob, e in puntajes if prob >= corte and e == 0)
        if tp == 0 or total_positivos == 0:
            continue
        precision = tp / (tp + fp)
        recall = tp / total_positivos
        f1 = 2 * precision * recall / (precision + recall)
        if f1 > mejor_f1:
            mejor_f1 = f1
            mejor = corte
    return round(mejor, 6)


def umbral_de_parche(crudos: list[dict]) -> float:
    """Umbral de similitud de parche MEDIDO, no elegido: la similitud mas baja con la que cada click
    productivo sigue reconociendo a OTRO click productivo del corpus. Por encima de ese valor la
    plantilla dejaria de iluminar a sus gemelas; muy por debajo empezaria a iluminar cualquier cosa."""
    productivos = [c for c in crudos if c["etiqueta"] == 1]
    if len(productivos) < 2:
        return 1.0
    parches = [extraer_parche(c["grid"], c["x"], c["y"]) for c in productivos]
    peor = 1.0
    for i, parche in enumerate(parches):
        mejor_vecino = max(
            similitud_de_parche(parche, otro) for j, otro in enumerate(parches) if j != i
        )
        peor = min(peor, mejor_vecino)
    # Se redondea HACIA ABAJO al noveno mas cercano (el parche tiene 9 celdas): un umbral entre dos
    # valores alcanzables es un umbral que nadie puede cumplir exactamente.
    return math.floor(peor * 9) / 9


def orden_de_acciones() -> tuple[list[str], int, int]:
    """Acciones ordenadas por fraccion de pasos en que movieron el tablero, medida sobre las
    partidas reales completas. Devuelve (orden, n_partidas, n_transiciones)."""
    if not FIXTURE_PARTIDAS.exists():
        return [], 0, 0
    datos = json.loads(FIXTURE_PARTIDAS.read_text(encoding="utf-8"))
    efectivos: dict[str, int] = {}
    totales: dict[str, int] = {}
    transiciones = 0
    for juego in datos["juegos"]:
        for paso in juego["pasos"]:
            accion = paso["accion"]
            totales[accion] = totales.get(accion, 0) + 1
            transiciones += 1
            if len(paso["diff"]) // 3 > CELDAS_MINIMAS_PARA_EFECTO:
                efectivos[accion] = efectivos.get(accion, 0) + 1
    orden = sorted(
        totales,
        key=lambda a: (-(efectivos.get(a, 0) / totales[a]), a),
    )
    return orden, len(datos["juegos"]), transiciones


def _formato_numero(valor: float) -> str:
    return f"{valor:.6f}"


def emitir_python(priors: dict, direcciones: dict) -> str:
    cuerpo = json.dumps(priors, indent=4, ensure_ascii=False)
    cuerpo_direcciones = json.dumps(direcciones, indent=4, ensure_ascii=False)
    return (
        '"""[arc-agi3-kaggle-agent/priors] BL.21560 -- ARCHIVO GENERADO por\n'
        "scripts/fit_click_priors.py. NO editar a mano: regenerar con\n"
        "`python3 scripts/fit_click_priors.py` y volver a correr las dos suites.\n"
        "\n"
        "Es el UNICO conocimiento pre-computado que viaja al notebook de submission: pesos del ranker\n"
        "de coordenadas (regresion logistica contra clicks REALES etiquetados con 'el click cambio la\n"
        "grilla'), umbrales medidos de los detectores, orden de acciones por efectividad observada y\n"
        "-- BL.21590 -- el prior de DIRECCIONES indexado por CONJUNTO DE ACCIONES DISPONIBLES.\n"
        "\n"
        "QUE NO PUEDE CONTENER: claves con forma de game_id (`abcd-01234567`) ni de firma de estado\n"
        "(entero de 32 bits). Memorizar la partida no generaliza a los juegos de evaluacion, que son\n"
        "distintos por diseno. `submission/build_notebook.py` FALLA el build si alguna se cuela.\n"
        "\n"
        f"Orden de `pesosClick`: {', '.join(CLICK_FEATURE_NAMES)}.\n"
        "\n"
        "`DIRECTION_PRIORS` es una HIPOTESIS INICIAL refutable, no una certeza cableada: siembra la\n"
        "creencia y `direction_beliefs.py` la confirma, la remapea o la deja sin evidencia con lo que\n"
        "vea en la partida. Fija la DIRECCION, nunca la magnitud del paso (medida: 2 a 6 celdas segun\n"
        "el juego). Detalle de la medicion en el docstring de `scripts/fit_click_priors.py`.\n"
        '"""\n'
        "from __future__ import annotations\n"
        "\n"
        f"CLICK_PRIORS: dict = {cuerpo}\n"
        "\n"
        f"DIRECTION_PRIORS: dict = {cuerpo_direcciones}\n"
    )


def emitir_typescript(priors: dict) -> str:
    pesos = ", ".join(_formato_numero(p) for p in priors["pesosClick"])
    acciones = ", ".join(f"'{a}'" for a in priors["ordenAcciones"])
    return (
        "/* [arc-agi-runner/worldModel/clickPriors] BL.21560 -- ARCHIVO GENERADO por\n"
        "   arc-agi3-kaggle-agent/scripts/fit_click_priors.py. NO editar a mano.\n"
        "\n"
        "   Los MISMOS numeros se emiten a `arc_agent/priors.py`: un solo ajuste, dos puertos, para que\n"
        "   la politica que juega contra la API oficial y la que va al notebook de Kaggle no diverjan en\n"
        "   silencio. Orden de `pesosClick`: el de `CLICK_FEATURE_NAMES` en clickFeatures.ts. */\n"
        "\n"
        "export interface ClickPriors {\n"
        "  version: number;\n"
        "  generatedAt: string;\n"
        "  nJuegosObservados: number;\n"
        "  nTransicionesObservadas: number;\n"
        "  /** Pesos posicionales, en el orden de `CLICK_FEATURE_NAMES` (clickFeatures.ts). */\n"
        "  pesosClick: readonly number[];\n"
        "  umbralesDetectores: {\n"
        "    probabilidadMinimaDeClick: number;\n"
        "    similitudDeParcheMinima: number;\n"
        "  };\n"
        "  ordenAcciones: readonly string[];\n"
        "}\n"
        "\n"
        "export const CLICK_PRIORS: ClickPriors = {\n"
        f"  version: {priors['version']},\n"
        f"  generatedAt: '{priors['generatedAt']}',\n"
        f"  nJuegosObservados: {priors['nJuegosObservados']},\n"
        f"  nTransicionesObservadas: {priors['nTransicionesObservadas']},\n"
        f"  pesosClick: [{pesos}],\n"
        "  umbralesDetectores: {\n"
        "    probabilidadMinimaDeClick: "
        f"{_formato_numero(priors['umbralesDetectores']['probabilidadMinimaDeClick'])},\n"
        "    similitudDeParcheMinima: "
        f"{_formato_numero(priors['umbralesDetectores']['similitudDeParcheMinima'])},\n"
        "  },\n"
        f"  ordenAcciones: [{acciones}],\n"
        "};\n"
    )


def main() -> int:
    if not FIXTURE_CLICKS.exists():
        print(
            f"[priors] falta el corpus de clicks ({FIXTURE_CLICKS}). Generarlo con "
            "`npx tsx scripts/exportClickCorpus.ts` desde projects/arc-agi-runner.",
            file=sys.stderr,
        )
        return 1

    muestras, n_partidas_click, n_transiciones_click, crudos = cargar_muestras()
    n_features = len(CLICK_FEATURE_NAMES)
    pesos = ajustar(muestras, n_features)
    acciones, n_partidas_accion, n_transiciones_accion = orden_de_acciones()

    priors = {
        "version": VERSION_PRIORS,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nJuegosObservados": n_partidas_click + n_partidas_accion,
        "nTransicionesObservadas": n_transiciones_click + n_transiciones_accion,
        "pesosClick": [round(p, 6) for p in pesos],
        "umbralesDetectores": {
            "probabilidadMinimaDeClick": mejor_umbral(muestras, pesos),
            "similitudDeParcheMinima": round(umbral_de_parche(crudos), 6),
        },
        "ordenAcciones": acciones,
    }

    # BL.21590 -- el prior de direcciones no se ajusta aca: se transcribe de la sonda contra la API
    # oficial (`scripts/direction_priors_source.py`). Se emite en la MISMA corrida para que los dos
    # puertos no puedan quedar con versiones distintas del prior.
    direcciones = dict(DIRECCIONES_MEDIDAS)

    SALIDA_PY.write_text(emitir_python(priors, direcciones), encoding="utf-8")
    escrito = [str(SALIDA_PY)]
    if SALIDA_TS.parent.exists():
        SALIDA_TS.write_text(emitir_typescript(priors), encoding="utf-8")
        escrito.append(str(SALIDA_TS))
        SALIDA_TS_DIRECCIONES.write_text(
            emitir_typescript_direcciones(
                direcciones, priors["generatedAt"], VERSION_PRIORS
            ),
            encoding="utf-8",
        )
        escrito.append(str(SALIDA_TS_DIRECCIONES))

    positivos = sum(e for _, e in muestras)
    print(f"[priors] muestras={len(muestras)} productivas={positivos} AUC={auc(muestras, pesos):.4f}")
    for nombre, peso in zip(CLICK_FEATURE_NAMES, pesos):
        print(f"[priors]   {nombre:<28} {peso:+.4f}")
    print(f"[priors] umbrales={priors['umbralesDetectores']}")
    print(f"[priors] ordenAcciones={acciones}")
    for ruta in escrito:
        print(f"[priors] escrito {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
