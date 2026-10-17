"""[arc-agi3-kaggle-agent/scripts/mapa_de_juegos] BL.21763 -- EL MAPA: la regla que asigna a cada
juego su categoria, el mapa VIEJO contra el que se compara, y la fusion de las corridas parciales.

Vive separado de `clasificacion_de_juegos.py` porque son dos responsabilidades distintas y con
ciclos de vida distintos: alla se MIDE (se juega, cuesta CPU, hay que correrlo en el box), aca se
INTERPRETA (es aritmetica sobre JSONs, corre en milisegundos y es lo unico que hace falta volver a
correr cuando se discute donde poner un umbral). Mezclarlas obligaba a pagar la medicion entera
para re-leer un corte.

La regla de categorizacion es EXPLICITA a proposito: dos lecturas del mismo JSON tienen que dar el
mismo mapa. Los contratos estan fijados en `tests/test_bl21763_clasificacion_de_juegos.py` y en
`tests/test_bl21783_corrida_truncada_y_semillas.py`.

BL.21783 corrige dos cosas mas, las dos del lado de la REANUDACION que este BL viene a habilitar:

 1. SEIS DE LOS 25 IDS DE `JUEGOS_PUBLICOS` NO EXISTIAN. La lista decia salir de
    `environment_files/`, pero nombraba `ns03 os34 vc72 wm09 ws70 zt11` -- que no estan en el
    dataset -- y le faltaban `bp35 cd82 re86 s5i5 tr87 wa30`, que si estan. Efecto medido: seis
    juegos REALES recibian `categoriaVieja = "desconocida"` y quedaban fuera del complemento. El
    guard no lo agarraba porque comparaba contra `environment_files/` SOLO si el directorio
    existia, y ese directorio es gitignoreado: en un checkout limpio y en CI el test pasaba sin
    comparar nada. Ahora la lista es la del dataset y el guard tiene una segunda pata que SIEMPRE
    corre, contra el banco versionado (`tests/support/mundos_medidos`).
 2. AL REANUDAR UN JUEGO, SU VOLCADO PARCIAL COMPETIA CON LA CORRIDA COMPLETA. Las dos filas son la
    misma `(juego, semilla)`, y el desempate `(niveles, -acciones)` hacia ganar a la MAS CORTA: un
    volcado de 1.750 acciones le ganaba a la corrida completa de 4.000 y mandaba el juego a
    `noMedible` teniendo la medicion completa en la mano; ademas la curva contaba el juego dos
    veces y `semillas` reportaba 2 donde habia 1. Lo cierra `una_fila_por_semilla()`.
"""
from __future__ import annotations

import glob
import json
import time
from pathlib import Path

#: Hitos de la curva de presupuesto. 400 y 1600 son los dos puntos que el mapa VIEJO midio
#: (400 -> 4,0 niveles totales; 1600 -> 8,5), asi que estan para que el numero nuevo se lea en la
#: misma escala que el viejo. 4000 es el tope del entregable de hoy (BL.21701). Vive ACA, junto a
#: la regla que los lee (`_clasificar` exige el hito 400): un hito que la regla no puede leer no
#: sirve de nada, y separarlos garantizaria que un dia dejen de coincidir.
HITOS_POR_DEFECTO = (100, 200, 400, 800, 1200, 1600, 2400, 3200, 4000)

#: Tope de acciones del ENTREGABLE de hoy (BL.21701). Es la vara contra la que se decide si una
#: corrida agoto el presupuesto que estaba bajo medicion: por debajo de esto, "no gano niveles"
#: no refuta "limitado por presupuesto", que es justo la hipotesis que este BL vino a probar.
COTA_DEL_ENTREGABLE = 4000

#: MAPA VIEJO -- el que este BL viene a revisar. Fuente: los briefs de BL.21701 y BL.21702 (mismo
#: barrido: "workflow de score y presupuesto, 25 juegos publicos, 2 semillas, 100 a 1600").
#: OJO: el brief describe 6 + 7 + 11 = 24 juegos sobre 25. Los seis que puntuaban y los siete que
#: ciclaban estan nombrados; la tercera categoria se deriva por COMPLEMENTO y da 12, no 11. La
#: discrepancia se declara en vez de taparse: el mapa viejo no teselaba los 25.
MAPA_VIEJO = {
    "limitadoPorPresupuesto": ("ft09", "g50t", "lp85", "m0r0", "sc25", "vc33"),
    "cicla": ("dc22", "lf52", "sb26", "sp80", "su15", "tn36", "tu93"),
}

#: Fraccion final de la partida sobre la que se mide si la novedad se murio. Un cuarto, para que
#: el tramo tenga suficientes acciones como para que la tasa no sea ruido.
FRACCION_DEL_TRAMO_FINAL = 0.25

#: Firmas de estado NUEVAS por accion en el tramo final por debajo de las cuales se llama "cicla".
#: Calibrado con la evidencia del mapa viejo (BL.21702, tramo 1200-1600 = 400 acciones): sb26 17
#: firmas nuevas (0,043/accion), r11l 18 (0,045), tn36 30 (0,075), dc22 52 (0,13). El corte se pone
#: en 0,05 -- entre los dos pares.
#:
#: LIMITE DECLARADO DE ESTE UMBRAL: esas cuatro observaciones son del agente y del instrumento
#: VIEJOS, que es justo lo que este BL declara no comparable. La escala no coincide -- 17 a 52
#: firmas nuevas por 400 acciones entonces contra centenares por un tramo equivalente hoy -- asi
#: que el umbral hereda una calibracion de otra epoca. Por eso NO es una constante escondida: la
#: tasa medida se REPORTA por juego en cada fila y el corte entra por `--umbral-novedad`, de modo
#: que re-cortar cuesta milisegundos y no una re-medicion. Cualquier fila cuya categoria dependa
#: de estar a menos de un factor 2 del umbral queda marcada con `cercaDelUmbral` para que nadie la
#: cite como si fuera un veredicto robusto.
UMBRAL_DE_NOVEDAD_MUERTA = 0.05

#: Factor dentro del cual una tasa se considera DEMASIADO CERCA del umbral como para que la
#: distincion cicla/noConvierte se lea como firme.
FACTOR_DE_CERCANIA_AL_UMBRAL = 2.0


#: Los 25 juegos publicos que el mapa tiene que teselar. Sin esta lista, `_categoria_vieja` no
#: puede distinguir "pertenece a la tercera categoria del mapa viejo" de "este id no existe", y un
#: `--juegos` con un typo entraria al mapa con una categoria vieja inventada.
#:
#: CORREGIDA EN BL.21783, y vale contar por que: la lista anterior decia salir de
#: `environment_files/` pero nombraba seis ids que NO estan en el dataset (`ns03 os34 vc72 wm09
#: ws70 zt11`) y omitia seis que SI estan (`bp35 cd82 re86 s5i5 tr87 wa30`), o sea que seis juegos
#: reales salian `desconocida` y quedaban fuera del complemento. Nadie lo vio porque el guard
#: comparaba contra `environment_files/` **solo si el directorio existia**, y es gitignoreado: en
#: CI el test pasaba sin comparar nada. Estos son los directorios que el dataset trae de verdad, y
#: el guard ahora tiene ademas una pata versionada que corre siempre.
JUEGOS_PUBLICOS = (
    "ar25", "bp35", "cd82", "cn04", "dc22", "ft09", "g50t", "ka59", "lf52", "lp85",
    "ls20", "m0r0", "r11l", "re86", "s5i5", "sb26", "sc25", "sk48", "sp80", "su15",
    "tn36", "tr87", "tu93", "vc33", "wa30",
)


def _categoria_vieja(juego: str) -> str:
    """Categoria del mapa VIEJO. Los 13 nombrados salen de `MAPA_VIEJO`; los 12 restantes del set
    publico caen en la tercera categoria por complemento. Un id que NO es de los 25 no recibe
    categoria inventada: se declara `desconocida` y la fusion no lo cuenta como movimiento."""
    for categoria, juegos in MAPA_VIEJO.items():
        if juego in juegos:
            return categoria
    if juego in JUEGOS_PUBLICOS:
        return "noConvierte"
    return "desconocida"


def _clasificar(
    medicion: dict, umbral: float, cota: int = COTA_DEL_ENTREGABLE
) -> tuple[str, str]:
    """Categoria NUEVA de un juego y EL NUMERO que la justifica. Reglas explicitas para que dos
    lecturas del mismo JSON den lo mismo.

    LA ASIMETRIA DE UNA CORRIDA TRUNCADA, que es el defecto que esta version corrige. `niveles` es
    MONOTONO dentro de una partida, asi que las dos mitades de la regla no valen igual sobre una
    corrida que no agoto el presupuesto BAJO MEDICION:
      - `limitadoPorPresupuesto` (ya subio DESPUES de 400) SI se sostiene truncada: mas presupuesto
        ya pago, y correr mas acciones solo puede confirmarlo.
      - `puntuaTemprano`, `cicla` y `noConvierte` NO se sostienen truncadas: todas afirman que el
        juego NO gano nada mas despues de 400, y el tramo que faltaba correr es exactamente donde
        eso podia pasar. Declararlas sobre una corrida corta es afirmar la hipotesis que la
        medicion se quedo sin medir.

    QUE CUENTA COMO "AGOTO EL PRESUPUESTO". No alcanza con `parcial is False`: una corrida lanzada
    con `--acciones 2000` termina completa y sigue sin decir nada sobre lo que pasa entre 2000 y
    4000. El criterio es doble: o la partida TERMINO SOLA (gano, o el agente dejo de jugar), o
    llego al tope del ENTREGABLE (`cota`, 4000 por BL.21701). Con eso la misma regla protege los
    dos bordes -- abajo el hito 400, arriba la cota -- y no hay forma de fabricar un casillero
    corriendo menos acciones."""
    final = int(medicion["nivelesFinales"])
    hitos = medicion["nivelesPorHito"]
    tasa = float(medicion["novedadDelTramoFinalPorAccion"])
    acciones = int(medicion["accionesConsumidas"])
    tope = int(medicion.get("topeDeAcciones", acciones))
    corte = str(medicion.get("corteFue", ""))
    termino_sola = corte in ("gano", "solo")
    agoto_el_presupuesto = termino_sola or acciones >= cota
    # SIN EL HITO 400 NO HAY CATEGORIA. La regla entera se apoya en comparar el presupuesto viejo
    # con el nuevo; si la corrida no llego a 400 acciones, un `get("400", 0)` haria pasar por
    # "gano niveles despues de 400" a un juego que gano en la accion 3. Preferible declarar que no
    # se puede clasificar antes que fabricar un casillero.
    if "400" not in hitos:
        return ("noMedible", "la corrida no llego al hito 400: sin base de comparacion")
    en400 = int(hitos["400"])
    if final > en400:
        return (
            "limitadoPorPresupuesto",
            f"niveles 400->{acciones} acciones: {en400} -> {final}",
        )
    if not agoto_el_presupuesto:
        return (
            "noMedible",
            f"corrida de {acciones} acciones (tope pedido {tope}, cota del entregable {cota}) sin "
            f"subir despues de 400 y sin terminar sola: el tramo que falta es justo donde "
            f"'limitadoPorPresupuesto' podia confirmarse, asi que 0 niveles nuevos aca no refutan "
            f"nada (tasa de novedad {tasa:.4f}/accion)",
        )
    if final > 0:
        return ("puntuaTemprano", f"{final} nivel(es), todos antes de la accion 400")
    if tasa < umbral:
        return ("cicla", f"{tasa:.4f} firmas de estado nuevas por accion en el tramo final")
    return ("noConvierte", f"{tasa:.4f} firmas nuevas por accion y 0 niveles")


def es_medicion(fila: dict) -> bool:
    """Una fila RESERVADA no es una medicion. La corrida crea la ranura del juego apenas arranca la
    partida y recien la llena en el primer volcado (250 acciones): una ranura vacia no es una
    medicion de cero, es la ausencia de una -- y contarla como cero bajaria la curva con un juego
    que nunca se jugo."""
    return "nivelesPorHito" in fila


def una_fila_por_semilla(filas: list[dict]) -> list[dict]:
    """Deduplica por `(juego, semilla)` quedandose con la corrida MAS COMPLETA de cada una.

    ESTO NO ES COSMETICA (BL.21783): es el defecto que dispara el flujo REANUDABLE. Cuando una
    partida se corta, su volcado parcial queda escrito; al reanudarla, la corrida nueva escribe OTRA
    fila para el mismo juego y la misma semilla. Sin deduplicar pasaban tres cosas, las tres malas:
    la curva sumaba el mismo juego dos veces, `semillas` reportaba 2 donde habia 1, y el desempate
    `(niveles, -acciones)` hacia ganar a la corrida MAS CORTA -- o sea que el volcado parcial de
    1.750 acciones le ganaba a la corrida completa de 4.000 y mandaba el juego a `noMedible`
    teniendo la medicion completa en la mano.

    El orden de preferencia es: primero la que TERMINO, y entre dos del mismo tipo la que llego mas
    lejos. Nunca al reves: una corrida completa siempre le gana a su propio volcado.
    """
    mejor_por_semilla: dict[tuple[str, str], dict] = {}
    for fila in filas:
        clave = (fila["juego"], fila["semilla"])
        rival = mejor_por_semilla.get(clave)
        if rival is None or _rango_de_completitud(fila) > _rango_de_completitud(rival):
            mejor_por_semilla[clave] = fila
    return list(mejor_por_semilla.values())


def _llego_al_hito(fila: dict, hito: int) -> bool:
    """Si esa corrida tiene algo que decir sobre ese hito. Dos formas de tenerlo: haber consumido
    al menos esas acciones, o haber terminado sola antes (una partida que se gano en la accion 900
    tiene su valor definido en el hito 4.000, y es el final: no va a subir mas)."""
    if int(fila["accionesConsumidas"]) >= hito:
        return True
    return str(fila.get("corteFue", "")) in ("gano", "solo")


def _rango_de_completitud(fila: dict) -> tuple[int, int]:
    return (0 if fila.get("parcial", False) else 1, int(fila["accionesConsumidas"]))


def fusionar(patron: str, umbral: float, cota: int = COTA_DEL_ENTREGABLE) -> dict:
    """Junta las corridas parciales (una por juego y semilla) en el mapa comparado."""
    filas: list[dict] = []
    for ruta in sorted(glob.glob(patron)):
        crudo = json.loads(Path(ruta).read_text(encoding="utf-8"))
        filas.extend(fila for fila in crudo.get("mediciones", []) if es_medicion(fila))
    if not filas:
        raise SystemExit(f"[clasificacion] el patron {patron!r} no encontro mediciones.")
    filas = una_fila_por_semilla(filas)

    por_juego: dict[str, list[dict]] = {}
    for fila in filas:
        por_juego.setdefault(fila["juego"], []).append(fila)

    mapa: dict[str, dict] = {}
    for juego, mediciones in sorted(por_juego.items()):
        # La categoria se decide sobre la semilla MEJOR (la que mas niveles saco): la pregunta del
        # mapa es de que es capaz el agente en ese juego, y promediar semillas convertiria un
        # "puede" en un "a veces" -- el mapa viejo tampoco promediaba.
        # El desempate mira la COMPLETITUD antes que las acciones (BL.21783): con `(niveles,
        # -acciones)` a secas, entre dos corridas de 0 niveles ganaba la mas corta, o sea el
        # volcado parcial por encima de la corrida completa.
        mejor = max(
            mediciones,
            key=lambda m: (
                m["nivelesFinales"],
                0 if m.get("parcial", False) else 1,
                -m["accionesConsumidas"],
            ),
        )
        categoria, motivo = _clasificar(mejor, umbral, cota)
        vieja = _categoria_vieja(juego)
        niveles = [m["nivelesFinales"] for m in mediciones]
        tasa = float(mejor["novedadDelTramoFinalPorAccion"])
        mapa[juego] = {
            "categoriaVieja": vieja,
            "categoriaNueva": categoria,
            "queNumeroLoMovio": motivo if categoria != vieja else "sin cambio de casillero",
            # Semillas DISTINTAS, no filas (BL.21783): tras `una_fila_por_semilla` son lo mismo,
            # y escribirlo asi hace que `varianzaEntreSemillasEsMedible` no pueda volver a leer
            # como "medible" a un volcado parcial y su reanudacion.
            "semillas": len({m["semilla"] for m in mediciones}),
            # EL RUIDO ENTRE SEMILLAS, MEDIDO O DECLARADO AUSENTE. Con una sola semilla la varianza
            # no es cero: es DESCONOCIDA, y un mapa que no lo diga invita a leer un delta de una
            # corrida como si fuera una propiedad del juego.
            "rangoDeNivelesEntreSemillas": [min(niveles), max(niveles)] if niveles else [0, 0],
            # CUANTAS semillas faltan para que el casillero deje de ser una apuesta lo calcula
            # `scripts/presupuesto_de_la_medicion.py` (BL.21783), que importa de aca y no al reves:
            # el mapa INTERPRETA lo medido, el planificador decide lo que falta medir.
            "varianzaEntreSemillasEsMedible": len({m["semilla"] for m in mediciones}) >= 2,
            # La distincion cicla/noConvierte se apoya en un umbral heredado del mapa viejo. Si la
            # tasa esta a menos de un factor 2 del corte, el casillero es fragil y se declara.
            "cercaDelUmbral": categoria in ("cicla", "noConvierte")
            and (umbral / FACTOR_DE_CERCANIA_AL_UMBRAL)
            <= tasa
            <= (umbral * FACTOR_DE_CERCANIA_AL_UMBRAL),
            # Que la fila sea PARCIAL viaja al mapa: un juego cortado a la accion 2750 midio de
            # verdad hasta 2400, pero nadie puede leer su renglon como "esto es lo que da con 4000".
            "parcial": bool(mejor.get("parcial", False)),
            "niveles": [m["nivelesFinales"] for m in mediciones],
            "nivelesPorHito": mejor["nivelesPorHito"],
            "accionesConsumidas": mejor["accionesConsumidas"],
            "corteFue": mejor["corteFue"],
            # El corte por reloj viaja CON su escenario: `accionEnQueElRelojHabriaCortado` es el de
            # la maquina DEDICADA (Kaggle). El del box compartido va al lado y nunca se confunde.
            "accionEnQueElRelojHabriaCortado": mejor["accionEnQueElRelojHabriaCortado"],
            "escenariosDeCorteDelReloj": mejor.get("escenariosDeCorteDelReloj", {}),
            "nivelesAlCorteDelReloj": mejor["nivelesAlCorteDelReloj"],
            "gameOvers": sum(m["gameOvers"] for m in mediciones),
            "coordenadasDistintas": mejor["coordenadasDistintas"],
            "firmasDeEstadoDistintas": mejor["firmasDeEstadoDistintas"],
            "novedadDelTramoFinalPorAccion": mejor["novedadDelTramoFinalPorAccion"],
            "distribucionDeAcciones": mejor["distribucionDeAcciones"],
            "cpuSegundos": mejor["costo"]["cpuSegundos"],
        }

    # LA CURVA SOLO SUMA LAS CORRIDAS QUE LLEGARON AL HITO (BL.21783). Con `get(hito, 0)`, una
    # corrida cortada en la accion 1.250 aportaba un CERO al hito 1.600, y bastaba una sola para
    # que la curva agregada BAJARA -- medido: 3,0 niveles en el hito 1.200 y 0,0 en el 1.600, un
    # imposible aritmetico, porque los niveles son monotonos dentro de la partida. Una corrida que
    # no llego al hito no aporta un cero: no aporta nada, y el denominador tiene que saberlo.
    # `soporteDeLaCurva` publica cuantas corridas y cuantas semillas hay detras de cada punto,
    # porque sin eso dos puntos de la misma curva pueden no ser comparables entre si.
    hitos = sorted({int(h) for fila in filas for h in fila["nivelesPorHito"]})
    curva: dict[str, float] = {}
    soporte: dict[str, dict] = {}
    for hito in hitos:
        llegaron = [f for f in filas if _llego_al_hito(f, hito)]
        semillas_del_hito = {f["semilla"] for f in llegaron}
        curva[str(hito)] = sum(
            int(f["nivelesPorHito"].get(str(hito), f["nivelesFinales"])) for f in llegaron
        ) / max(1, len(semillas_del_hito))
        soporte[str(hito)] = {
            "corridas": len(llegaron),
            "semillas": len(semillas_del_hito),
            "juegos": sorted({f["juego"] for f in llegaron}),
        }
    return {
        "generadoEn": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "umbralDeNovedadMuerta": umbral,
        "juegosMedidos": len(mapa),
        "semillas": sorted({f["semilla"] for f in filas}),
        "curvaDePresupuestoNivelesPorSemilla": {k: round(v, 2) for k, v in curva.items()},
        "soporteDeLaCurva": soporte,
        "nivelesTotalesPorSemilla": {
            semilla: sum(f["nivelesFinales"] for f in filas if f["semilla"] == semilla)
            for semilla in sorted({f["semilla"] for f in filas})
        },
        "cpuSegundosTotales": round(sum(f["costo"]["cpuSegundos"] for f in filas), 1),
        # EL FACTOR DE CONTENCION, UNO SOLO Y DERIVADO. El informe anterior citaba tres factores
        # distintos (8,3x, 17,6x, 18,8x) para la misma corrida. Aca se calcula del agregado de las
        # filas -- pared SIN la espera voluntaria sobre CPU -- y es el unico que se puede citar.
        "factorParedPorCpuAgregado": round(
            max(
                1.0,
                sum(
                    f["costo"].get("relojSegundosSinEsperaDeCarga", f["costo"]["relojSegundos"])
                    for f in filas
                )
                / max(1e-9, sum(f["costo"]["cpuSegundos"] for f in filas)),
            ),
            2,
        ),
        "cpuSegundosPorAccionAgregado": round(
            sum(f["costo"]["cpuSegundos"] for f in filas)
            / max(1, sum(f["accionesConsumidas"] for f in filas)),
            4,
        ),
        "mapa": mapa,
        # Las series crudas NO se copian al mapa: viven en los JSON por corrida (`--fusionar` las
        # lee de ahi). Copiarlas multiplicaria el archivo por diez sin agregar informacion, y el
        # mapa es el artefacto que se cita, no el que se re-procesa.
        "mediciones": [
            {k: v for k, v in fila.items() if not k.startswith("serieDe")} for fila in filas
        ],
    }


