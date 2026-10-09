"""[arc-agi3-kaggle-agent/scripts/metricas_densas] BL.22856 -- las metricas DENSAS candidatas,
calculadas POST-PARTIDA desde `agente.frames`, sin tocar una linea del agente.

POR QUE EXISTEN. El conteo de niveles es estructuralmente incapaz de ver el tamano de mejora que se
esta haciendo: BL.22236 y BL.22237 cambiaron comportamiento probado por tests unitarios y el gate
los vio IDENTICOS al baseline (14 niveles, mismo desglose juego por juego en los 25). Y 5 corridas
del MISMO codigo dieron 11/9/9/8/7 niveles (BL.22395): delta=+1 esta dentro del ruido. Una mejora
que no completa un nivel nuevo es delta=0 POR CONSTRUCCION.

QUE SE CALCULA, y de donde sale cada numero. `FrameData.frame` es una tupla hasheable de grillas
64x64 (arc_agent/types.py), asi que igualdad y set son exactos, no aproximados:

  framesConCambio   cuantas acciones CAMBIARON la grilla respecto del frame anterior. Una politica
                    que clickea paredes produce menos que una que interactua con el mundo.
  estadosDistintos  cuantas grillas DISTINTAS se visitaron. Cobertura de exploracion: dar vueltas
                    en circulo y explorar se ven iguales en niveles, distintos aca.
  pasoPrimerAvance  indice del primer frame con levels_completed > 0, o None si nunca. None y NO
                    cero: "no avanzo" y "avanzo en el paso 0" son dos estados distintos y un cero
                    los fundiria (RFM-61).
  avanceTemprano    cuantos frames quedaron DESPUES del primer avance (0 si nunca avanzo). Denso
                    solo en los juegos donde ya hay nivel; complementa, no reemplaza.
  framesSinGrilla   cuantos frames NO traian grilla. El instrumento declara lo que no pudo mirar
                    en vez de contarlo como "sin cambio" -- el mismo cero con dos lecturas.

LO QUE NO SE CALCULA, dicho con su numero (el BL exige las descartadas declaradas): la tasa de
acierto de las hipotesis del world-model NO es medible hoy -- grep medido 2026-08-27 sobre
agent/my_agent.py: 0 contadores expuestos (self.aciertos/prediccion/hipotesis/hits). Exponer uno
es tocar el agente, que es exactamente lo que este instrumento promete no hacer.

EL CRITERIO DE ADMISION no vive aca: una candidata ENTRA solo si separa el par conocidamente
distinto (baseline vs BL.22236) -- eso lo decide `scripts/calibracion_de_metricas.py` con corridas
reales, nunca este modulo. Este modulo solo mide.

Stdlib pura. SOLO REPO -- el entregable de Kaggle no lo incluye."""
from __future__ import annotations

CLAVES_DENSAS_AGREGABLES = ("framesConCambio", "estadosDistintos", "avanceTemprano")


def _grilla_canonica(grilla):
    """Tuplas anidadas, o None si la forma no es la esperada. Hace falta porque hay DOS FrameData
    con el mismo nombre: el mirror del repo (arc_agent/types.py) trae tuplas hasheables, pero el
    que el gate ve corriendo el agente inlineado es el del framework y trae LISTAS -- medido
    2026-08-27, el primer smoke de la calibracion murio con `unhashable type: 'list'`. Una grilla
    inconvertible NO se cuenta como "sin cambio": se cuenta como no mirada (framesSinGrilla)."""
    try:
        return tuple(tuple(tuple(int(c) for c in fila) for fila in capa) for capa in grilla)
    except (TypeError, ValueError):
        return None


def metricas_de_partida(frames) -> dict:
    """Efecto: ninguno. Deriva las metricas densas de la lista de frames de UNA partida.

    `getattr` con default en cada campo: el agente inlineado del entregable tambien tiene que
    poder pasar por aca aunque su FrameData no exponga la propiedad -- y la ausencia se CUENTA
    (framesSinGrilla), no se disimula.
    """
    grillas = [getattr(f, "frame", None) for f in frames]
    validas = [g for g in (_grilla_canonica(g) for g in grillas if g is not None) if g is not None]

    cambios = sum(1 for previa, actual in zip(validas, validas[1:]) if previa != actual)
    estados = len(set(validas))

    paso_primer = None
    for indice, frame in enumerate(frames):
        if int(getattr(frame, "levels_completed", 0) or 0) > 0:
            paso_primer = indice
            break

    return {
        "framesConCambio": cambios,
        "estadosDistintos": estados,
        "pasoPrimerAvance": paso_primer,
        "avanceTemprano": (len(frames) - 1 - paso_primer) if paso_primer is not None else 0,
        "framesSinGrilla": len(grillas) - len(validas),
    }


def agregar_densas(por_semilla: dict) -> dict:
    """Efecto: ninguno. Totaliza las densas de todas las (semilla, juego) en la fila unica.

    `partidasMedidas` existe por la misma razon que `juegosMedidos` en el config del gate: un
    total sumado sobre MENOS partidas se leeria como una caida del agente. Un lector que compara
    dos totales tiene que poder ver primero que salieron de la misma cantidad de partidas.
    """
    totales = {clave: 0 for clave in CLAVES_DENSAS_AGREGABLES}
    partidas_medidas = 0
    sin_grilla = 0
    for medicion in por_semilla.values():
        for fila in medicion.values():
            densas = fila.get("densas")
            if not isinstance(densas, dict):
                continue
            partidas_medidas += 1
            sin_grilla += int(densas.get("framesSinGrilla") or 0)
            for clave in CLAVES_DENSAS_AGREGABLES:
                totales[clave] += int(densas.get(clave) or 0)
    totales["partidasMedidas"] = partidas_medidas
    totales["framesSinGrilla"] = sin_grilla
    return totales
