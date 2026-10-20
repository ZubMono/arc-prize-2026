"""[arc-agi3-kaggle-agent/scripts/presupuesto_de_la_medicion] BL.21783 -- CUANTO CUESTA LA PROXIMA
MEDICION Y CUANTAS SEMILLAS NECESITA, con numeros y no a ojo.

Este modulo no juega ni interpreta el mapa: solo hace la aritmetica de PLANIFICACION que hoy se
venia haciendo de memoria en los briefs. Son dos preguntas, las dos cerradas aca:

1) QUIEN CORTA PRIMERO, EL RELOJ O EL TOPE. Es la pregunta que BL.21763 dejo contestada y que
   conviene no volver a litigar: la cuota del reloj es `presupuesto / N` y las acciones del tope
   cuestan `tope * c`, asi que el reloj corta antes solo si `N > presupuesto / (tope * c)`. Con el
   costo local medido (0,1535 s de CPU/accion a profundidad 500) el cruce esta en 47 juegos, o sea
   que EN ESTE BOX Y CON 25 JUEGOS MANDA EL TOPE. En la maquina de Kaggle depende de la
   profundidad, y el informe de BL.21763 lo daba por cerrado con un unico 0,325 s/accion que no es
   ninguno de los dos costos MEDIDOS: 0,1535 x 1,8 = 0,276 -> cruce en 27, manda el tope; 0,20 x
   1,8 = 0,360 -> cruce en 21, manda el reloj. El umbral exacto es 0,16 s/accion local. Corolario
   que hay que leer bien:
   `accionEnQueElRelojHabriaCortado` sale `null` en TODA corrida local -- es el resultado, no un
   bug del instrumento.

2) CUANTAS SEMILLAS. El mapa decide por la semilla MEJOR (`max`), asi que su unico error posible es
   el FALSO NEGATIVO: un juego que SI puede puntuar y al que ninguna semilla le salio. Si un juego
   puntua con probabilidad `p` por semilla, N semillas independientes lo pierden con probabilidad
   `(1-p)^N`, de donde `N >= ln(riesgo) / ln(1-p)`. Eso convierte "N=1 no alcanza" (que es una
   opinion) en un numero con dos perillas declaradas: cual es el juego mas dificil que queremos
   NO perder (`p`) y cuanto riesgo de perderlo aceptamos (`riesgo`).
   Y como el error es de un solo lado, el plan barato es ADAPTATIVO: la primera semilla se corre en
   todos, y las semillas de refuerzo se gastan SOLO en los juegos que salieron en cero. Un juego
   que ya puntuo no puede cambiar de casillero por correr mas semillas -- el `max` ya esta ganado.

Uso:

    .venv/bin/python scripts/presupuesto_de_la_medicion.py \\
        --mapa mediciones/BL21763_clasificacion_de_juegos.json \\
        --juegos ft09,g50t,lp85,m0r0,sc25,vc33
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapa_de_juegos import es_medicion, una_fila_por_semilla  # noqa: E402

#: Costo por accion MEDIDO en este box sobre el harness real, a profundidad 500 en g50t (BL.21763).
#: El costo crece con la profundidad: BL.21701 midio 0,154 s en los pasos 0-400 y 0,202 s en los
#: 1200-1600, asi que este numero es la cota OPTIMISTA y `CPU_POR_ACCION_PROFUNDO` la pesimista.
CPU_POR_ACCION_LOCAL = 0.1535
CPU_POR_ACCION_PROFUNDO = 0.20

#: Factor de maquina local -> Kaggle, estimado en BL.21701.
FACTOR_DE_MAQUINA_KAGGLE = 1.8

#: Tope de acciones del entregable de hoy (BL.21701). Se repite como DEFAULT del planificador, no
#: como definicion: la definicion vive en `COTA_DE_SEGURIDAD_DE_ACCIONES` del agente y la medicion
#: la lee de ahi (`aplicar_tope_de_pasos`).
TOPE_DE_ACCIONES_POR_DEFECTO = 4000

#: Las dos perillas del calculo de semillas, con su justificacion.
#: `p` = probabilidad por semilla de que un juego CAPAZ efectivamente puntue. No se puede estimar
#: de los datos de hoy: la unica evidencia es g50t, 0 exitos en 1 semilla, y 0/1 no acota `p` por
#: abajo (el intervalo exacto al 90% es [0, 0,90]). O sea que el numero NO sale de la muestra: sale
#: de declarar cual es el juego mas dificil que no queremos perder. Se fija en 0,5 -- "un juego que
#: puntua la mitad de las veces" -- porque es exactamente el regimen que el mapa viejo no podia
#: distinguir de "no puntua nunca", y es el que explica la discordancia de g50t (el mapa viejo lo
#: tenia subiendo en la accion 154 y la corrida nueva le dio 0 hasta 1600).
PROBABILIDAD_OBJETIVO_POR_SEMILLA = 0.5
#: `riesgo` = probabilidad tolerada de mandar a un juego capaz al casillero equivocado. 0,10 es el
#: mismo orden que el 0,05-0,10 con el que el track ya decide (umbral de novedad, gate de merge).
RIESGO_MAXIMO_DE_FALSO_NEGATIVO = 0.10


def _techo_estable(valor: float) -> int:
    """`ceil` que no se deja llevar por el error de coma flotante, con piso en 1.

    Todas las cuentas de este modulo caen JUSTO en un entero en los casos de manual -- `ln(0,01) /
    ln(0,1)` son 2 semillas exactas, `(2*1/1)^2` son 4 -- y ahi el `ceil` a secas devuelve uno de
    mas cuando la division da 2,0000000000000004. Un plan que pide una partida extra de 4.000
    acciones por un epsilon no es conservador: es irreproducible."""
    entero = round(valor)
    if math.isclose(valor, entero, rel_tol=1e-9, abs_tol=1e-12):
        return max(1, entero)
    return max(1, math.ceil(valor))


def juegos_donde_el_reloj_corta_primero(
    cpu_por_accion: float, tope_de_acciones: int, presupuesto_segundos: float
) -> int:
    """Cantidad MINIMA de juegos en el batch a partir de la cual el reloj corta antes que el tope.

    `presupuesto_segundos` entra por parametro y no se escribe aca: la fuente unica es
    `PRESUPUESTO_POR_DEFECTO_SEGUNDOS` del modulo del entregable, igual que en `_cuota_de_reloj`.
    """
    if cpu_por_accion <= 0 or tope_de_acciones <= 0:
        raise ValueError("el costo por accion y el tope tienen que ser positivos")
    cruce = presupuesto_segundos / (tope_de_acciones * cpu_por_accion)
    # `floor + 1` y no `ceil`: en el cruce exacto hay EMPATE (el reloj corta justo en la ultima
    # accion del tope), y un empate no es "el reloj corta primero".
    # El `isclose` NO es cosmetico: 0,20 x 1,8 da 0,36000000000000004 en coma flotante, y sin el
    # redondeo el cruce exacto de 20,0 se lee como 19,9999... y devuelve 20 en vez de 21. Un
    # cruce que se corre un juego segun como se haya calculado el costo es exactamente el tipo de
    # numero que despues nadie puede reproducir.
    entero = round(cruce)
    if math.isclose(cruce, entero, rel_tol=1e-9):
        return entero + 1
    return math.floor(cruce) + 1


def costo_por_accion_en_kaggle(cpu_por_accion_local: float) -> float:
    """El mismo costo, trasladado a la maquina del entregable. La conversion vive en UN lugar
    porque de ella depende de que lado del cruce cae el batch de 25: con el costo optimista
    (0,1535 -> 0,276) sigue mandando el TOPE, y con el profundo (0,20 -> 0,36) manda el RELOJ. El
    umbral exacto es 0,288 s/accion en Kaggle, o sea 0,16 s/accion local."""
    return cpu_por_accion_local * FACTOR_DE_MAQUINA_KAGGLE


def quien_corta_primero(
    juegos_del_batch: int,
    cpu_por_accion: float,
    tope_de_acciones: int,
    presupuesto_segundos: float,
) -> str:
    """"reloj", "tope" o "empate" para un batch de N juegos. Lo que decide es la comparacion entre
    la cuota de CPU por partida y lo que cuestan las acciones del tope."""
    if juegos_del_batch <= 0:
        raise ValueError("el batch tiene que tener al menos un juego")
    cuota = presupuesto_segundos / juegos_del_batch
    costo_del_tope = tope_de_acciones * cpu_por_accion
    if math.isclose(cuota, costo_del_tope, rel_tol=1e-9):
        return "empate"
    return "reloj" if cuota < costo_del_tope else "tope"


def semillas_para_no_perder_un_juego(
    probabilidad_por_semilla: float, riesgo_maximo: float
) -> int:
    """N semillas tal que `(1-p)^N <= riesgo`. Es el unico error que el mapa puede cometer, porque
    decide por la semilla mejor: un falso POSITIVO (declarar que puntua un juego que no puntua)
    exigiria que el harness reporte un nivel que no ocurrio."""
    if not 0.0 < probabilidad_por_semilla <= 1.0:
        raise ValueError("la probabilidad por semilla tiene que estar en (0, 1]")
    if not 0.0 < riesgo_maximo < 1.0:
        raise ValueError("el riesgo tiene que estar en (0, 1)")
    if probabilidad_por_semilla == 1.0:
        return 1
    return _techo_estable(
        math.log(riesgo_maximo) / math.log(1.0 - probabilidad_por_semilla)
    )


def semillas_para_media(desvio: float, semiancho: float, z: float = 1.96) -> int:
    """N semillas para que el intervalo de la MEDIA tenga semiancho `e`: `N >= (z*s/e)^2`.

    Es la otra pregunta, y no la misma: el `max` sobre semillas contesta "de que es capaz", pero la
    curva de presupuesto (niveles totales por semilla) es un PROMEDIO y su incertidumbre depende de
    la dispersion medida. Hoy esa dispersion NO existe -- N=1 por juego -- asi que esta funcion se
    usa DESPUES de la primera pasada, con el desvio observado, y no antes con uno inventado."""
    if desvio < 0 or semiancho <= 0 or z <= 0:
        raise ValueError("desvio >= 0, semiancho > 0 y z > 0")
    return _techo_estable((z * desvio / semiancho) ** 2)


def corridas_esperadas_del_plan_adaptativo(
    juegos: int, probabilidad_por_semilla: float, tope_de_semillas: int
) -> float:
    """Partidas esperadas si se corta al PRIMER exito de cada juego: `n * (1-(1-p)^N)/p`.

    El plan fijo cuesta `n * N` partidas y da la misma garantia de falso negativo. La diferencia es
    la que hace viable la medicion en este box."""
    if not 0.0 < probabilidad_por_semilla <= 1.0:
        raise ValueError("la probabilidad por semilla tiene que estar en (0, 1]")
    if juegos < 0 or tope_de_semillas < 1:
        raise ValueError("juegos >= 0 y tope de semillas >= 1")
    fallar_todas = (1.0 - probabilidad_por_semilla) ** tope_de_semillas
    return juegos * (1.0 - fallar_todas) / probabilidad_por_semilla


#: Acciones minimas para que el costo de un tramo no sea ruido. Los cortes del perfil son fijos
#: (100, 400, 800, 1200...) y la corrida termina donde la cortaron: el tramo final puede tener 50
#: acciones, y con 50 acciones el promedio se mueve con un solo hipo del scheduler.
ANCHO_MINIMO_DEL_TRAMO = 100


def _ancho_del_tramo(clave: str) -> int:
    """Acciones que cubre una clave de la forma "401-800"."""
    partes = str(clave).split("-")
    try:
        return int(partes[1]) - int(partes[0]) + 1
    except (IndexError, ValueError):
        return 0


#: Los dos criterios de "este juego ya mostro lo que se estaba buscando", que NO son el mismo y que
#: llevan a planes distintos:
#:   `niveles` -- de que es capaz el juego. Es la pregunta del MAPA: un juego que ya puntuo no puede
#:     cambiar de casillero por correr mas semillas, asi que no gasta refuerzos.
#:   `delta`   -- si el presupuesto EXTRA paga. Es la pregunta de la CURVA, y no se contesta con la
#:     anterior: sc25 puntua tres veces antes de la accion 800 y su delta 1.600->4.000 es CERO, o
#:     sea que con el criterio del mapa se lo daria por resuelto y la pregunta del BL se quedaria
#:     con UNA sola semilla justo en el juego que ya demostro que puntua.
CRITERIOS = ("niveles", "delta")


def _ya_mostro_lo_que_se_busca(
    medidas: list[dict], criterio: str, hito_de_partida: int
) -> bool:
    if criterio not in CRITERIOS:
        raise ValueError(f"criterio desconocido: {criterio!r} (validos: {CRITERIOS})")
    if criterio == "niveles":
        return any(int(f.get("nivelesFinales", 0)) > 0 for f in medidas)
    # `delta`: gano al menos un nivel DESPUES del hito de partida. Se lee de la curva de la propia
    # corrida y no del total, que es lo que distingue "puntua" de "el presupuesto extra paga".
    for fila in medidas:
        hitos = fila.get("nivelesPorHito") or {}
        clave = str(hito_de_partida)
        if clave not in hitos:
            continue
        if int(fila.get("nivelesFinales", 0)) > int(hitos[clave]):
            return True
    return False


def costo_por_accion_medido(medidas: list[dict], por_defecto: float) -> tuple[float, str]:
    """Cuanto cuesta UNA accion mas en ESE juego, medido, y de donde salio el numero.

    POR QUE NO ALCANZA UNA CONSTANTE, y es el error que este mismo BL cometio al planificar. El
    plan se calculaba con 0,1535 s de CPU por accion para todos los juegos por igual, y con ese
    numero el estrato A completo daban 4,1 h de CPU. Medido: g50t promedia 0,151 s a lo largo de
    1.750 acciones, pero lp85 arranca en 0,151 y llega a 0,83 en la accion 1.000 -- o sea que las
    acciones que FALTAN, que son las profundas, cuestan cinco veces mas que las que ya se pagaron.
    Un plan que subestima el costo por un factor 5 es como se planifica mal una ventana de maquina.

    EL NUMERO QUE SE USA ES EL DEL ULTIMO TRAMO, no el promedio de la corrida: lo que falta correr
    empieza donde la corrida se quedo, y ahi el costo ya es el caro. El promedio mezcla las
    acciones baratas del principio, que no se van a volver a pagar."""
    if not medidas:
        return por_defecto, f"sin medicion de este juego: {por_defecto:g} s/accion por defecto"
    # La corrida mas larga es la que llego mas profundo, o sea la que mejor conoce el costo de lo
    # que falta.
    mejor = max(medidas, key=lambda f: int(f.get("accionesConsumidas", 0)))
    costo = mejor.get("costo") or {}
    tramos = costo.get("cpuPorAccionPorTramo") or {}
    if tramos:
        ordenados = sorted(tramos.items(), key=lambda kv: int(str(kv[0]).split("-")[0]))
        # EL ULTIMO TRAMO SUELE SER UN PEDAZO. Los cortes son fijos (100, 400, 800, 1200...) y la
        # corrida termina donde la cortaron, asi que el tramo final puede tener 50 acciones y ser
        # puro ruido. Se usa el mas profundo que tenga cuerpo; si ninguno lo tiene, el que haya.
        con_cuerpo = [kv for kv in ordenados if _ancho_del_tramo(kv[0]) >= ANCHO_MINIMO_DEL_TRAMO]
        ultimo = (con_cuerpo or ordenados)[-1]
        return float(ultimo[1]), (
            f"costo MEDIDO del tramo mas profundo de la corrida mas larga ({ultimo[0]} acciones): "
            f"{float(ultimo[1]):g} s/accion"
        )
    if costo.get("cpuSegundosPorAccion"):
        return float(costo["cpuSegundosPorAccion"]), (
            f"promedio MEDIDO de la corrida mas larga: {float(costo['cpuSegundosPorAccion']):g} "
            "s/accion (la corrida no trae el costo por tramo)"
        )
    return por_defecto, f"la medicion no trae costo: {por_defecto:g} s/accion por defecto"


def plan_de_semillas(
    filas: list[dict],
    juegos_objetivo: tuple[str, ...] | list[str],
    probabilidad_por_semilla: float = PROBABILIDAD_OBJETIVO_POR_SEMILLA,
    riesgo_maximo: float = RIESGO_MAXIMO_DE_FALSO_NEGATIVO,
    tope_de_acciones: int = TOPE_DE_ACCIONES_POR_DEFECTO,
    cpu_por_accion: float = CPU_POR_ACCION_LOCAL,
    criterio: str = "niveles",
    hito_de_partida: int = 1600,
) -> dict:
    """Que partidas faltan, juego por juego, para que el mapa tenga la garantia declarada.

    `filas` son las mediciones crudas (la lista `mediciones` de una corrida o de una fusion), no el
    mapa: hace falta el detalle POR SEMILLA -- una semilla truncada no cuenta como semilla hecha,
    y el mapa solo guarda la marca de la mejor."""
    tope_de_semillas = semillas_para_no_perder_un_juego(probabilidad_por_semilla, riesgo_maximo)
    por_juego: dict[str, list[dict]] = {}
    # La MISMA deduplicacion que la fusion, importada y no reimplementada: si el planificador
    # contara el volcado parcial y su reanudacion como dos semillas, pediria una partida de menos
    # justo en el juego que mas la necesita.
    for fila in una_fila_por_semilla([f for f in filas if es_medicion(f)]):
        por_juego.setdefault(fila["juego"], []).append(fila)

    plan: dict[str, dict] = {}
    for juego in juegos_objetivo:
        medidas = por_juego.get(juego, [])
        completas = [f for f in medidas if not f.get("parcial", False)]
        truncadas = [f for f in medidas if f.get("parcial", False)]
        # Un exito cuenta AUNQUE la corrida este truncada: los niveles ganados no se pierden, y el
        # mapa decide por el maximo. Es la misma asimetria que la guarda de truncamiento de
        # `_clasificar`: la presencia sobrevive al corte, la ausencia no.
        puntuo = _ya_mostro_lo_que_se_busca(medidas, criterio, hito_de_partida)
        if puntuo:
            faltan = 0
            que_mostro = (
                "ya puntua"
                if criterio == "niveles"
                else f"ya gano un nivel DESPUES de la accion {hito_de_partida}"
            )
            motivo = (
                f"{que_mostro} con {len(medidas)} semilla(s): la decision es por el maximo y mas "
                "semillas no pueden dar vuelta un exito ya ganado"
            )
        else:
            faltan = max(0, tope_de_semillas - len(completas))
            que_falta = (
                "puntuar"
                if criterio == "niveles"
                else f"ganar un nivel despues de la accion {hito_de_partida}"
            )
            motivo = (
                f"{len(completas)} semilla(s) COMPLETA(s) y {len(truncadas)} truncada(s) sin "
                f"{que_falta}: hacen falta {tope_de_semillas} completas para que el riesgo de "
                f"perder un juego que lo logra con p={probabilidad_por_semilla:g} baje a "
                f"{riesgo_maximo:g}"
            )
        acciones = faltan * tope_de_acciones
        costo_del_juego, de_donde = costo_por_accion_medido(medidas, cpu_por_accion)
        plan[juego] = {
            "semillasCompletas": len(completas),
            "semillasTruncadas": len(truncadas),
            "yaPuntua": puntuo,
            "partidasQueFaltan": faltan,
            "accionesQueFaltan": acciones,
            "cpuPorAccionUsado": round(costo_del_juego, 4),
            "deDondeSaleElCosto": de_donde,
            "cpuSegundosQueFaltan": round(acciones * costo_del_juego, 1),
            "porQue": motivo,
        }

    acciones_totales = sum(f["accionesQueFaltan"] for f in plan.values())
    cpu_total_medido = sum(f["cpuSegundosQueFaltan"] for f in plan.values())
    sin_puntuar = sum(1 for f in plan.values() if not f["yaPuntua"])
    return {
        "probabilidadObjetivoPorSemilla": probabilidad_por_semilla,
        "riesgoMaximoDeFalsoNegativo": riesgo_maximo,
        "semillasPorJuegoEnElPlanFijo": tope_de_semillas,
        "partidasDelPlanFijo": len(list(juegos_objetivo)) * tope_de_semillas,
        "partidasEsperadasDelPlanAdaptativo": round(
            corridas_esperadas_del_plan_adaptativo(
                len(list(juegos_objetivo)), probabilidad_por_semilla, tope_de_semillas
            ),
            2,
        ),
        "juegosSinPuntuarTodavia": sin_puntuar,
        "accionesQueFaltanEnElPeorCaso": acciones_totales,
        # EL NUMERO QUE HAY QUE MIRAR es el que suma el costo MEDIDO de cada juego. Los otros dos
        # quedan como referencia historica: son lo que costaria si todos los juegos costaran lo
        # mismo, que es justo el supuesto que la medicion de este BL rompio.
        "cpuHorasQueFaltanConElCostoMedido": round(cpu_total_medido / 3600.0, 2),
        "cpuHorasQueFaltanOptimista": round(acciones_totales * CPU_POR_ACCION_LOCAL / 3600.0, 2),
        "cpuHorasQueFaltanPesimista": round(acciones_totales * CPU_POR_ACCION_PROFUNDO / 3600.0, 2),
        "porJuego": plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BL.21783 -- cuantas semillas y cuanto CPU falta para cerrar el mapa"
    )
    parser.add_argument("--mapa", required=True, help="JSON con la lista `mediciones`.")
    parser.add_argument(
        "--juegos",
        default="ft09,g50t,lp85,m0r0,sc25,vc33",
        help="Ids del estrato a planificar. Por defecto, los 6 que puntuaban en el mapa viejo.",
    )
    parser.add_argument("--probabilidad", type=float, default=PROBABILIDAD_OBJETIVO_POR_SEMILLA)
    parser.add_argument("--riesgo", type=float, default=RIESGO_MAXIMO_DE_FALSO_NEGATIVO)
    parser.add_argument("--acciones", type=int, default=TOPE_DE_ACCIONES_POR_DEFECTO)
    parser.add_argument(
        "--criterio",
        default="niveles",
        choices=list(CRITERIOS),
        help="Que cuenta como 'este juego ya mostro lo que se buscaba'. `niveles` (default) es la "
        "pregunta del MAPA; `delta` es la de la CURVA -- gano un nivel DESPUES del hito -- y son "
        "planes distintos: un juego que puntua temprano y no vuelve a subir esta resuelto para el "
        "mapa y sin medir para la curva.",
    )
    parser.add_argument("--hito-de-partida", type=int, default=1600)
    parser.add_argument("--presupuesto", type=float, default=8.0 * 3600.0,
                        help="Segundos de CPU del entregable, para la tabla de quien corta "
                             "primero. El default espeja PRESUPUESTO_POR_DEFECTO_SEGUNDOS.")
    args = parser.parse_args()

    crudo = json.loads(Path(args.mapa).read_text(encoding="utf-8"))
    juegos = tuple(j.strip() for j in args.juegos.split(",") if j.strip())
    plan = plan_de_semillas(
        crudo.get("mediciones", []),
        juegos,
        probabilidad_por_semilla=args.probabilidad,
        riesgo_maximo=args.riesgo,
        tope_de_acciones=args.acciones,
        criterio=args.criterio,
        hito_de_partida=args.hito_de_partida,
    )
    print(json.dumps(plan, indent=1, sort_keys=True, ensure_ascii=False))

    print("\nQUIEN CORTA PRIMERO (presupuesto {:.0f} s, tope {} acciones):".format(
        args.presupuesto, args.acciones))
    # Las cuatro esquinas del rectangulo de incertidumbre: dos costos MEDIDOS (profundidad 500 y
    # profundidad 1200-1600) por dos maquinas (esta y Kaggle). Ninguna interpolacion: el informe de
    # BL.21763 usaba un unico 0,325 s/accion que no es ninguno de los dos medidos.
    for etiqueta, costo in (
        ("local, profundidad 500", CPU_POR_ACCION_LOCAL),
        ("local, profundidad 1200-1600", CPU_POR_ACCION_PROFUNDO),
        ("Kaggle, profundidad 500", costo_por_accion_en_kaggle(CPU_POR_ACCION_LOCAL)),
        ("Kaggle, profundidad 1200-1600", costo_por_accion_en_kaggle(CPU_POR_ACCION_PROFUNDO)),
    ):
        cruce = juegos_donde_el_reloj_corta_primero(costo, args.acciones, args.presupuesto)
        manda = quien_corta_primero(25, costo, args.acciones, args.presupuesto)
        print(f"  {etiqueta}: {costo:.4f} s/accion -> el reloj manda desde {cruce} juegos; "
              f"con los 25 publicos manda el {manda.upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
