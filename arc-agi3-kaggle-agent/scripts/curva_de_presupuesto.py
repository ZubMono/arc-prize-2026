"""[arc-agi3-kaggle-agent/scripts/curva_de_presupuesto] BL.21783 -- LA PREGUNTA DEL BL, CONTESTADA
CON NUMEROS: cuantos niveles suman las 4.000 acciones, y si ese delta supera el ruido entre
semillas o esta adentro.

POR QUE ES UN MODULO Y NO UN PARRAFO DEL INFORME. La leccion de BL.21594 es que un delta metido
adentro del ruido NO es una mejora, y la unica forma de no volver a cometer ese error es que el
veredicto lo emita un ARTEFACTO con una regla escrita y fijada por tests, no una lectura a ojo del
mapa. `mapa_de_juegos.fusionar` ya publica la curva agregada, pero un promedio no distingue "0,3
niveles porque una semilla saco 1 y tres sacaron 0" de "0,3 niveles porque todas suben un poco":
lo primero es ruido y lo segundo es una mejora.

LA PROPIEDAD QUE HACE FACIL LA MITAD DEL PROBLEMA: EL DELTA ES PAREADO. `niveles` es MONOTONO
dentro de una partida y una corrida de 4.000 acciones CONTIENE sus propios hitos 400 y 1600, asi
que `niveles@4000 - niveles@1600` se mide sobre la MISMA partida, con la misma semilla y el mismo
mundo. Consecuencias que ordenan todo el analisis:
  - El delta pareado nunca es negativo. No hace falta ningun test de significancia para descartar
    que el presupuesto extra "empeore": no puede.
  - Si el delta pareado es CERO en todas las corridas, la respuesta es NO y la varianza entre
    semillas es IRRELEVANTE para esa conclusion. Cero niveles nuevos no es un promedio chico que
    podria ser ruido: es la ausencia literal del evento en cada partida medida.
  - Recien si el delta es POSITIVO en alguna corrida hay que preguntarse si generaliza, y ahi si
    entra la varianza entre semillas.

LA REGLA DEL VEREDICTO, explicita para que dos lecturas del mismo JSON den lo mismo:
  1. `noHayEvento`  -- ningun (juego, semilla) gano un nivel despues del hito de referencia. El
     delta es 0 exacto. NO es mejora, y no se apoya en ninguna estimacion de varianza.
  2. `dentroDelRuido` -- el delta medio entre semillas NO supera el desvio de los totales entre
     semillas al hito de referencia, o hay alguna semilla que no lo ve. Es el caso que BL.21594
     enseño a no vender como mejora.
  3. `superaElRuido` -- el delta medio supera el desvio ENTRE semillas y TODAS las semillas lo ven
     (`minimoEntreSemillas > 0`). Las dos condiciones juntas, porque cualquiera sola se deja
     enganar: la media sola la levanta un unico juego con suerte, y "todas lo ven" sin magnitud
     puede ser un nivel de mas contra un ruido de tres.
  4. `noConcluyente` -- una sola semilla: el desvio entre semillas no existe, y sin el no se puede
     decir si el delta lo supera. Se declara, no se rellena con un cero optimista.

QUE SE CUENTA Y QUE NO. Solo entran corridas que llegaron AL MENOS al hito de destino: una partida
cortada en 2.750 acciones no aporta un "delta a 4000 de cero", aporta la ausencia de un dato.
Contarla como cero es exactamente el defecto que BL.21783 corrigio en la regla de categorizacion,
y seria absurdo repetirlo aca.

Uso:

    .venv/bin/python scripts/curva_de_presupuesto.py \\
        --corridas 'runtime_reports/bl21783/*.json' --desde 1600 --hasta 4000
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapa_de_juegos import es_medicion, una_fila_por_semilla  # noqa: E402
from presupuesto_de_la_medicion import (  # noqa: E402
    FACTOR_DE_MAQUINA_KAGGLE,
    juegos_donde_el_reloj_corta_primero,
    quien_corta_primero,
)

#: Los dos hitos que el mapa VIEJO publico (400 -> 4,0 niveles; 1600 -> 8,5). El delta que el BL
#: pregunta es el del tramo NUEVO, 1600 -> 4000, pero el de 400 -> 1600 se reporta al lado porque
#: es la unica referencia de escala: sirve de poco saber que el tramo nuevo suma 0,2 niveles si no
#: se sabe cuanto sumaba el tramo que ya estaba pago.
HITO_VIEJO_CORTO = 400
HITO_VIEJO_LARGO = 1600
HITO_DEL_ENTREGABLE = 4000

#: Niveles TOTALES sobre los 25 juegos que el mapa viejo reporto en cada hito (briefs BL.21701 /
#: BL.21702, 2 semillas). Se guardan para que la comparacion con lo nuevo sea legitima y para que
#: nadie compare un total de 6 juegos contra uno de 25 sin decirlo.
MAPA_VIEJO_NIVELES_TOTALES = {"400": 4.0, "1600": 8.5}


def _llego_al_hito(fila: dict, hito: int) -> bool:
    """Una corrida aporta al hito solo si LO ALCANZO. Dos formas de alcanzarlo: consumir al menos
    esas acciones, o haber terminado sola antes (si la partida se gano en la accion 900, su valor
    en el hito 4000 esta definido y es el final: no va a subir mas)."""
    if int(fila["accionesConsumidas"]) >= hito:
        return True
    return str(fila.get("corteFue", "")) in ("gano", "solo")


def _niveles_en(fila: dict, hito: int) -> int:
    """Niveles al hito. Si la partida termino sola antes del hito, su valor ahi es el final."""
    hitos = fila["nivelesPorHito"]
    clave = str(hito)
    if clave in hitos:
        return int(hitos[clave])
    return int(fila["nivelesFinales"])


def cargar_corridas(patron: str) -> list[dict]:
    """Todas las mediciones de un patron glob, deduplicadas por `(juego, semilla)`.

    Reusa `una_fila_por_semilla` a proposito (BL.21783): si el analisis dedujera su propia forma de
    desempatar el volcado parcial contra su reanudacion, el mapa y la curva podrian contestar
    distinto sobre la misma corrida."""
    filas: list[dict] = []
    for ruta in sorted(glob.glob(patron)):
        crudo = json.loads(Path(ruta).read_text(encoding="utf-8"))
        filas.extend(fila for fila in crudo.get("mediciones", []) if es_medicion(fila))
    return una_fila_por_semilla(filas)


def _desvio(valores: list[float]) -> float:
    return float(statistics.stdev(valores)) if len(valores) >= 2 else 0.0


def _perfil_del_juego(filas: list[dict]) -> dict:
    """Las magnitudes que distinguen a un juego CARO de uno barato, tomadas de la corrida mas larga.

    Son las dos hipotesis del costo por accion, enfrentadas: la memoria de NOVEDAD (firmas de
    estado distintas) y el ranker de CLICKS (coordenadas distintas y plantillas aprendidas, que
    `_bono_de_plantilla` recorre por cada celda del tablero). Adentro de una sola partida las dos
    crecen con el tiempo y la correlacion no las separa; entre juegos si, porque un juego puede
    tener mucha de una y poca de la otra."""
    if not filas:
        return {}
    mejor = max(filas, key=lambda f: int(f.get("accionesConsumidas", 0)))
    costo = mejor.get("costo") or {}
    tramos = costo.get("cpuPorAccionPorTramo") or {}
    ordenados = sorted(tramos.items(), key=lambda kv: int(str(kv[0]).split("-")[0]))
    distribucion = mejor.get("distribucionDeAcciones") or {}
    plantillas = mejor.get("serieDePlantillasDeClick") or []
    return {
        "cpuPorAccionDelPrimerTramo": ordenados[0][1] if ordenados else None,
        "cpuPorAccionDelUltimoTramo": ordenados[-1][1] if ordenados else None,
        "clicks": int(distribucion.get("ACTION6", 0)),
        "coordenadasDistintas": mejor.get("coordenadasDistintas"),
        "firmasDeEstadoDistintas": mejor.get("firmasDeEstadoDistintas"),
        "plantillasAlTerminar": plantillas[-1] if plantillas else None,
    }


def costo_y_quien_corta(
    filas: list[dict],
    juegos_del_batch: int = 25,
    tope: int = HITO_DEL_ENTREGABLE,
    presupuesto_segundos: float = 8.0 * 3600.0,
) -> dict:
    """EL COSTO POR ACCION MEDIDO A FONDO, y que pasa con "quien corta primero" cuando se lo
    reemplaza por el numero real en vez del que se venia asumiendo.

    POR QUE ESTO VIVE AL LADO DEL VEREDICTO DE NIVELES. Toda la aritmetica de presupuesto del track
    -- la cuota por partida, el cruce de 47 juegos, el "en este box manda el tope" -- se apoya en
    UN costo por accion tomado como constante (0,1535 s, medido en los primeros cientos de pasos).
    Si el costo CRECE con la profundidad, ese numero no es una constante sino el valor del tramo
    barato, y una corrida hasta 4.000 acciones es la primera que puede decirlo. Medirlo no
    re-litiga la conclusion: le pone el numero que le faltaba.

    `costoDelTramoInicial` / `costoDelTramoFinal` salen de `cpuPorAccionPorTramo`, que la medicion
    ya emite por corrida: el primer tramo y el ultimo de cada partida, promediados entre corridas.
    """
    con_costo = [f for f in filas if "costo" in f and int(f["accionesConsumidas"]) > 0]
    if not con_costo:
        return {"corridasConCosto": 0}
    cpu_total = sum(float(f["costo"]["cpuSegundos"]) for f in con_costo)
    acciones_totales = sum(int(f["accionesConsumidas"]) for f in con_costo)
    agregado = cpu_total / max(1, acciones_totales)

    iniciales: list[float] = []
    finales: list[float] = []
    for f in con_costo:
        tramos = f["costo"].get("cpuPorAccionPorTramo") or {}
        if not tramos:
            continue
        # Las claves son "1-100", "101-400"...: el orden que importa es el del PRIMER numero.
        ordenados = sorted(tramos.items(), key=lambda kv: int(str(kv[0]).split("-")[0]))
        iniciales.append(float(ordenados[0][1]))
        finales.append(float(ordenados[-1][1]))

    def _corte(c: float) -> dict:
        return {
            "cpuPorAccion": round(c, 4),
            "cruceEnJuegos": juegos_donde_el_reloj_corta_primero(c, tope, presupuesto_segundos),
            "conElBatchDe25": quien_corta_primero(
                juegos_del_batch, c, tope, presupuesto_segundos
            ),
        }

    profundo = statistics.fmean(finales) if finales else agregado
    return {
        "corridasConCosto": len(con_costo),
        "cpuSegundosTotales": round(cpu_total, 1),
        "accionesTotales": acciones_totales,
        "cpuPorAccionAgregado": round(agregado, 4),
        "costoDelTramoInicial": round(statistics.fmean(iniciales), 4) if iniciales else None,
        "costoDelTramoFinal": round(profundo, 4),
        "creceConLaProfundidad": bool(
            iniciales and finales and statistics.fmean(finales) > statistics.fmean(iniciales)
        ),
        "quienCortaPrimero": {
            "localConElCostoAgregado": _corte(agregado),
            "localConElCostoDelTramoFinal": _corte(profundo),
            "kaggleConElCostoAgregado": _corte(agregado * FACTOR_DE_MAQUINA_KAGGLE),
            "kaggleConElCostoDelTramoFinal": _corte(profundo * FACTOR_DE_MAQUINA_KAGGLE),
        },
        "presupuestoSegundos": presupuesto_segundos,
        "topeDeAcciones": tope,
        "juegosDelBatch": juegos_del_batch,
    }


def curva(
    filas: list[dict],
    desde: int = HITO_VIEJO_LARGO,
    hasta: int = HITO_DEL_ENTREGABLE,
) -> dict:
    """El veredicto completo. Ver el docstring del modulo para la regla."""
    utiles = [f for f in filas if _llego_al_hito(f, hasta)]
    juegos = sorted({f["juego"] for f in utiles})
    semillas = sorted({f["semilla"] for f in utiles})

    por_juego: dict[str, dict] = {}
    for juego in juegos:
        suyas = [f for f in utiles if f["juego"] == juego]
        deltas = [_niveles_en(f, hasta) - _niveles_en(f, desde) for f in suyas]
        por_juego[juego] = {
            "semillas": sorted(f["semilla"] for f in suyas),
            "nivelesPorHito": {
                str(hito): [_niveles_en(f, hito) for f in suyas]
                for hito in (HITO_VIEJO_CORTO, desde, hasta)
            },
            "deltaPorSemilla": deltas,
            "deltaMedio": round(statistics.fmean(deltas), 3) if deltas else 0.0,
            "deltaMaximo": max(deltas) if deltas else 0,
            # El rango entre semillas al hito de PARTIDA es el ruido de base del juego: es cuanto
            # cambia el resultado sin tocar el presupuesto.
            "rangoEntreSemillasEnElHitoDePartida": [
                min(_niveles_en(f, desde) for f in suyas),
                max(_niveles_en(f, desde) for f in suyas),
            ]
            if suyas
            else [0, 0],
            # QUE HACE CARO A UN JUEGO, en la misma fila que sus niveles. Una atribucion DENTRO de
            # una partida no puede separar dos estructuras que crecen juntas con el tiempo; entre
            # juegos si, porque cada uno mueve una y no la otra. Sin esta tabla, la explicacion del
            # costo queda en la prosa del informe y nadie la puede re-derivar.
            **_perfil_del_juego(suyas),
        }

    # AGREGADO POR SEMILLA, SOLO SOBRE LOS JUEGOS QUE TODAS LAS SEMILLAS MIDIERON. El plan
    # adaptativo gasta semillas de refuerzo unicamente donde salio cero, asi que las semillas altas
    # cubren MENOS juegos: sumar el total de cada semilla sobre su propio conjunto compararia una
    # semilla de seis juegos contra una de dos, y la diferencia se leeria como varianza cuando es
    # el plan. El total se calcula sobre el nucleo BALANCEADO y los que quedan afuera se nombran.
    juegos_balanceados = [
        juego
        for juego in juegos
        if {f["semilla"] for f in utiles if f["juego"] == juego} == set(semillas)
    ]
    fuera_del_balance = [juego for juego in juegos if juego not in juegos_balanceados]
    totales_por_semilla: dict[str, dict] = {}
    for semilla in semillas:
        suyas = [
            f for f in utiles if f["semilla"] == semilla and f["juego"] in juegos_balanceados
        ]
        totales_por_semilla[semilla] = {
            "juegos": sorted(f["juego"] for f in suyas),
            # El hito 400 va SIEMPRE aunque no sea ninguna de las dos puntas del delta: es el
            # presupuesto con el que se definio la categoria "limitado por presupuesto", y sin el
            # no se puede leer si el tramo nuevo agrega algo distinto de lo que ya agregaba el
            # tramo viejo.
            f"nivelesEn{HITO_VIEJO_CORTO}": sum(
                _niveles_en(f, HITO_VIEJO_CORTO) for f in suyas
            ),
            f"nivelesEn{desde}": sum(_niveles_en(f, desde) for f in suyas),
            f"nivelesEn{hasta}": sum(_niveles_en(f, hasta) for f in suyas),
            "delta": sum(_niveles_en(f, hasta) - _niveles_en(f, desde) for f in suyas),
        }

    # El ruido se mide sobre los juegos que TIENEN mas de una semilla, comparando el mismo juego
    # consigo mismo. Sumar totales de semillas que cubren juegos distintos mediria el plan
    # adaptativo, no la varianza.
    ruido_por_juego = [
        _desvio([_niveles_en(f, desde) for f in utiles if f["juego"] == juego])
        for juego in juegos_balanceados
        if len({f["semilla"] for f in utiles if f["juego"] == juego}) >= 2
    ]
    juegos_con_varianza_medible = len(ruido_por_juego)
    # Desvio del TOTAL: los juegos son independientes entre si (mundos distintos, partidas
    # distintas), asi que las varianzas se suman y el desvio del total es la raiz de esa suma.
    desvio_del_total = math.sqrt(sum(d * d for d in ruido_por_juego))

    deltas_de_todas = [
        _niveles_en(f, hasta) - _niveles_en(f, desde) for f in utiles
    ]
    delta_total_medio = (
        statistics.fmean(
            [totales_por_semilla[s]["delta"] for s in semillas]
        )
        if semillas
        else 0.0
    )
    minimo_entre_semillas = (
        min(totales_por_semilla[s]["delta"] for s in semillas) if semillas else 0
    )

    if not utiles:
        veredicto = "sinMedicion"
        motivo = f"ninguna corrida llego al hito {hasta}"
    elif not any(d > 0 for d in deltas_de_todas):
        veredicto = "noHayEvento"
        motivo = (
            f"ninguna de las {len(utiles)} corrida(s) que llegaron a {hasta} gano un solo nivel "
            f"despues de la accion {desde}: el delta es 0 exacto, no un promedio chico. La "
            f"varianza entre semillas no cambia esta lectura porque no hay evento que atribuir "
            f"al ruido."
        )
    elif juegos_con_varianza_medible == 0:
        veredicto = "noConcluyente"
        motivo = (
            f"el delta medio es {delta_total_medio:.2f} nivel(es) pero ningun juego tiene 2+ "
            f"semillas completas: el ruido entre semillas no esta medido, y sin el no se puede "
            f"decir si el delta lo supera."
        )
    elif delta_total_medio > desvio_del_total and minimo_entre_semillas > 0:
        veredicto = "superaElRuido"
        motivo = (
            f"delta medio {delta_total_medio:.2f} > desvio entre semillas {desvio_del_total:.2f}, "
            f"y la semilla PEOR tambien lo ve ({minimo_entre_semillas} nivel(es))."
        )
    else:
        veredicto = "dentroDelRuido"
        motivo = (
            f"delta medio {delta_total_medio:.2f} contra desvio entre semillas "
            f"{desvio_del_total:.2f} y minimo entre semillas {minimo_entre_semillas}: no cumple "
            f"las dos condiciones (superar el desvio Y que todas las semillas lo vean), asi que "
            f"no se puede llamar mejora (leccion de BL.21594)."
        )

    return {
        "hitoDePartida": desde,
        "hitoDeLlegada": hasta,
        "corridasQueLlegaronAlHito": len(utiles),
        "corridasDescartadasPorNoLlegar": len(filas) - len(utiles),
        "juegos": juegos,
        "semillas": semillas,
        # El nucleo sobre el que se comparan los totales entre semillas, y quien quedo afuera. Con
        # el plan adaptativo esto NO es una formalidad: es la diferencia entre medir varianza y
        # medir el plan.
        "juegosEnTodasLasSemillas": juegos_balanceados,
        "juegosFueraDelBalance": fuera_del_balance,
        "porJuego": por_juego,
        "totalesPorSemilla": totales_por_semilla,
        "deltaTotalMedioEntreSemillas": round(delta_total_medio, 3),
        "deltaTotalMinimoEntreSemillas": minimo_entre_semillas,
        "desvioEntreSemillasDelTotalEnElHitoDePartida": round(desvio_del_total, 3),
        "juegosConVarianzaMedible": juegos_con_varianza_medible,
        "veredicto": veredicto,
        "porQue": motivo,
        "mapaViejoNivelesTotales": MAPA_VIEJO_NIVELES_TOTALES,
        # QUE CUESTA la respuesta, medido sobre TODAS las filas (tambien las truncadas: una
        # corrida cortada no dice cuantos niveles da el presupuesto, pero si dice perfectamente
        # cuanto costo cada una de las acciones que alcanzo a jugar).
        "costoYQuienCorta": costo_y_quien_corta(filas),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BL.21783 -- la curva de presupuesto y su ruido")
    parser.add_argument("--corridas", required=True, help="Patron glob de los JSON por corrida.")
    parser.add_argument("--desde", type=int, default=HITO_VIEJO_LARGO)
    parser.add_argument("--hasta", type=int, default=HITO_DEL_ENTREGABLE)
    parser.add_argument("--json", default=None, help="Ruta de salida.")
    args = parser.parse_args()

    filas = cargar_corridas(args.corridas)
    if not filas:
        raise SystemExit(f"[curva] el patron {args.corridas!r} no encontro mediciones.")
    salida = curva(filas, args.desde, args.hasta)
    print(json.dumps(salida, indent=1, sort_keys=True, ensure_ascii=False))
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(salida, indent=1, sort_keys=True), encoding="utf-8")
        print(f"Curva escrita en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
