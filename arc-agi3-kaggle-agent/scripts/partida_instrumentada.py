"""[arc-agi3-kaggle-agent/scripts/partida_instrumentada] BL.21763 -- UNA PARTIDA MEDIDA, con la
disciplina de carga y la derivacion del corte por reloj adentro.

Vive separado de `clasificacion_de_juegos.py` (que queda como la CLI y el barrido) y de
`mapa_de_juegos.py` (que es la interpretacion) porque son tres ciclos de vida distintos: aca se
JUEGA -- cuesta CPU y hay que correrlo en el box --, alla se decide DONDE cortar un umbral, y en la
CLI se elige que juegos y con que semillas. La separacion no es estetica: permite re-derivar el
corte por reloj o re-cortar el umbral sin volver a jugar ni una accion.

LA DISCIPLINA DE CARGA SE EJERCE DURANTE LA PARTIDA. La primera version de este BL miraba la carga
UNA vez por juego, antes de empezar; con partidas de miles de acciones eso no cede el box en ningun
momento util (medido: la carga subio de 2,8 a 35 durante una partida sin que la medicion se
enterara, y el cron horario de partidas reales perdio cuatro ticks). Aca la carga se re-mira cada
`ACCIONES_ENTRE_MIRADAS_DE_CARGA` acciones y la partida se SUSPENDE de verdad mientras el box esta
saturado; los segundos cedidos se contabilizan aparte para que el factor PARED/CPU siga midiendo la
contencion de la maquina y no la cortesia de la medicion.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from captura_de_niveles import describir_accion  # noqa: E402
from mapa_de_juegos import FRACCION_DEL_TRAMO_FINAL  # noqa: E402
from reloj_derivado import (  # noqa: E402
    costo_por_accion_por_tramo,
    escenarios_de_corte,
    factor_pared_por_cpu,
)

#: Acciones entre volcados PARCIALES de la fila en curso. 250 y no 4000: en el box compartido una
#: partida de 4000 acciones son horas de reloj, y sin volcado intermedio una corrida interrumpida
#: perdia el juego entero. 250 acciones son ~50 s de CPU -- lo que se puede perder como maximo.
ACCIONES_ENTRE_VOLCADOS = 250

#: Ratio de carga (loadavg de 1 min / vCPU) por encima del cual esta medicion ESPERA antes de
#: empezar el juego siguiente. El box comparte 6 vCPU con el cron horario de partidas reales
#: contra la API oficial, que se SALTEA si el ratio pasa de 1,5 -- y esa es la unica recoleccion de
#: datos reales del track. Preferir tardar mas a robarle el box al cron.
CARGA_MAXIMA_POR_DEFECTO = 4.0

#: Cada cuanto se vuelve a mirar la carga mientras se espera, y cuanto se espera como maximo antes
#: de seguir igual. El tope existe para que la medicion no quede colgada para siempre en un box que
#: nunca se descarga: si se agota, se sigue -- con `nice -n 19` el proceso ya cede ante todo.
SEGUNDOS_ENTRE_MIRADAS_DE_CARGA = 30
ESPERA_MAXIMA_SEGUNDOS = 20 * 60

#: Acciones entre RE-MIRADAS de la carga DENTRO de una partida. Existe por un defecto medido: mirar
#: la carga una sola vez, antes de arrancar el juego, no cede el box -- una partida de 4000 acciones
#: son horas, y en ese lapso la carga puede subir de 2,8 a 35 sin que la medicion se entere. Con
#: esto la partida se auto-suspende mientras el box esta saturado y el cron horario puede correr.
#: 100 acciones son ~15 s de CPU: la reaccion es rapida y el sondeo no cuesta nada medible.
ACCIONES_ENTRE_MIRADAS_DE_CARGA = 100


def plantillas_de_click(politica) -> int:
    """Cuantas plantillas de click lleva aprendidas la politica, o 0 si esta version no tiene el
    ranker de coordenadas.

    LEE CON `getattr` A PROPOSITO. La medicion espia estructuras INTERNAS del agente (`_clicks`,
    `_novedad`), que son las que explican el costo por accion; si una de ellas se renombra o una
    variante de la politica no la tiene, lo que corresponde es que la serie salga en cero y la
    atribucion lo declare -- no que se caiga la partida entera y se pierda la medicion de niveles,
    que es lo que el BL vino a buscar."""
    ranker = getattr(politica, "_clicks", None)
    return int(getattr(ranker, "plantillas_aprendidas", 0) or 0)


def reparto_de_cpu(cpu_total: float, cpu_del_entorno: float) -> dict:
    """Como se reparte el CPU de la partida entre el paso del ENTORNO y todo lo demas (el agente).

    Vive como funcion aparte, y no en linea dentro del diccionario, porque es la unica parte del
    reparto que se puede testear sin el harness: el cronometro depende de `arc_agi` y de
    `environment_files` (gitignoreado, o sea que en CI no existe), pero la aritmetica -- que la
    resta no de negativo por el redondeo del cronometro, y que no se divida por cero en una
    partida que no gasto CPU -- si, y es donde estan los dos errores posibles.

    POR QUE IMPORTA EL NUMERO: "el agente se puso caro" y "el entorno es caro" llevan a decisiones
    OPUESTAS. Lo primero se arregla optimizando la politica y COMPRA presupuesto; lo segundo no se
    arregla desde el agente y convierte al tope de acciones en inalcanzable por diseno."""
    del_entorno = max(0.0, min(cpu_del_entorno, cpu_total))
    return {
        "cpuSegundosDelEntorno": round(del_entorno, 2),
        "cpuSegundosDelAgente": round(cpu_total - del_entorno, 2),
        "fraccionDelEntorno": round(del_entorno / cpu_total, 4) if cpu_total > 0 else None,
    }


def ratio_de_carga() -> float:
    """Carga de 1 minuto por vCPU. Es la misma magnitud con la que el cron decide saltearse."""
    return os.getloadavg()[0] / max(1, os.cpu_count() or 1)


def esperar_a_que_baje_la_carga(maxima: float, espera_maxima: float = ESPERA_MAXIMA_SEGUNDOS):
    """Bloquea hasta que el ratio de carga baje de `maxima` (o hasta agotar `espera_maxima`).
    Devuelve `(ratio con el que finalmente sigue, segundos efectivamente esperados)`.

    Los segundos esperados SE DEVUELVEN, no se descartan: el tiempo de pared de una partida que se
    auto-suspendio no mide la contencion de la maquina, y usarlo para calcular el factor PARED/CPU
    daria un factor inflado por la propia cortesia de la medicion."""
    if maxima <= 0:
        return (ratio_de_carga(), 0.0)
    esperado = 0.0
    ratio = ratio_de_carga()
    while ratio > maxima and esperado < espera_maxima:
        print(
            f"  [carga] ratio {ratio:.2f} sobre el maximo {maxima:.2f}: cedo el box "
            f"({esperado:.0f}s esperados)",
            flush=True,
        )
        arranque = time.monotonic()
        time.sleep(SEGUNDOS_ENTRE_MIRADAS_DE_CARGA)
        esperado += time.monotonic() - arranque
        ratio = ratio_de_carga()
    return (ratio, esperado)


def medir_partida(
    arcade,
    modulo,
    juego: str,
    semilla: str,
    hitos,
    cuota: float,
    al_avanzar=None,
    *,
    presupuesto: float = 0.0,
    juegos_del_batch: int = 25,
    carga_maxima: float = 0.0,
) -> dict:
    """Una partida instrumentada. Devuelve la fila del juego para esa semilla.

    `al_avanzar` recibe una fila PARCIAL cada `ACCIONES_ENTRE_VOLCADOS` acciones. Existe por una
    razon medida en este mismo BL: en el box compartido una partida de 4000 acciones son horas de
    reloj, y una corrida interrumpida a mitad perdia el juego ENTERO -- todo o nada. Con el volcado
    parcial, una partida cortada en la accion 2750 igual entrega su curva hasta 2400, que es
    informacion real y comparable con el mapa viejo."""
    clase_agente = modulo.MyAgent
    entorno = arcade.make(juego, render_mode=None)
    if entorno is None:
        raise SystemExit(f"[clasificacion] no se pudo crear el entorno de {juego!r}.")
    clase_agente.SEMILLA = semilla

    # BL.21741 EN SITU: se cuentan las firmas de mecanica que la partida produce DE VERDAD, no las
    # que el corpus offline produjo. El corpus tenia 14 eventos de subida de nivel; una partida
    # tiene miles de transiciones, y si la firma compuesta solo apareciera en el corpus habria que
    # decirlo. Se espia el modulo del entregable, que es donde el lazo la busca.
    firmas_de_mecanica: dict[str, int] = {}
    firma_original = modulo.firma_de_mecanica

    def firma_espiada(mecanica):
        etiqueta = firma_original(mecanica)
        firmas_de_mecanica[etiqueta] = firmas_de_mecanica.get(etiqueta, 0) + 1
        return etiqueta

    modulo.firma_de_mecanica = firma_espiada
    agente = clase_agente(
        card_id="bl21763",
        game_id=juego,
        agent_name=f"MyAgent.bl21763.{juego}",
        ROOT_URL="http://localhost",
        record=False,
        arc_env=entorno,
        tags=["bl21763"],
    )

    serie: list[dict] = []
    distribucion: dict[str, int] = {}
    coordenadas: set[tuple[int, int]] = set()
    game_overs = 0
    # Segundos que la partida paso SUSPENDIDA cediendole el box al cron. Se descuentan del pared
    # antes de calcular el factor PARED/CPU: si no, la propia cortesia de la medicion se leeria
    # como contencion de la maquina.
    esperado_por_carga = [0.0]
    #: CPU gastado DENTRO del paso del entorno. El resto del CPU de la partida es del agente.
    cpu_del_entorno = [0.0]
    ratios_vistos: list[float] = []
    emitir = agente.take_action
    politica = agente._politica
    cpu0 = time.process_time()
    reloj0 = time.monotonic()
    # Caja de una sola posicion: `take_action` se define antes que `resumir` (necesita cerrar sobre
    # `serie`), asi que la referencia se completa despues. Una funcion no puede llamar a otra que
    # todavia no existe, y partir el orden ensuciaria las dos.
    volcar: list = [None]

    def take_action(accion):
        nonlocal game_overs
        # Las coordenadas se leen AL VUELO: `GameAction` es un Enum y `set_data` muta el miembro
        # global, asi que leerlas despues devolveria las del click siguiente (captura_de_niveles).
        descripcion = describir_accion(accion)
        # DE QUIEN ES EL CPU (BL.21783). El costo por accion crece con la profundidad, y "el agente
        # se puso caro" y "el entorno es caro" llevan a decisiones OPUESTAS: lo primero se arregla
        # optimizando la politica y compra presupuesto; lo segundo NO se arregla desde el agente y
        # convierte el tope de 4.000 acciones en inalcanzable por diseno. La unica forma de
        # distinguirlas es cronometrar el paso del ENTORNO aparte, que es justo esta llamada.
        antes_del_entorno = time.process_time()
        frame = emitir(accion)
        cpu_del_entorno[0] += time.process_time() - antes_del_entorno
        if frame is None:
            return frame
        distribucion[descripcion.nombre] = distribucion.get(descripcion.nombre, 0) + 1
        if descripcion.x is not None and descripcion.y is not None:
            coordenadas.add((descripcion.x, descripcion.y))
        estado = str(getattr(frame, "state", ""))
        if estado.endswith("GAME_OVER"):
            game_overs += 1
        serie.append(
            {
                "accion": len(serie) + 1,
                "niveles": int(frame.levels_completed),
                "firmas": int(politica._novedad.firmas_distintas()),
                # PLANTILLAS DE CLICK, accion por accion (BL.21783). Es la otra estructura que
                # crece monotona con la partida, y a diferencia de la memoria de novedad se lee en
                # el costo de CADA accion: `_bono_de_plantilla` compara el parche de CADA CELDA
                # contra TODAS las plantillas, asi que el ranking de coordenadas cuesta
                # O(celdas x plantillas). Sin esta serie, "el costo por accion crece" no se puede
                # atribuir a nada y queda como una curiosidad del informe.
                "plantillas": plantillas_de_click(politica),
                "cpu": round(time.process_time() - cpu0, 4),
            }
        )
        # LA CORTESIA SE EJERCE DURANTE LA PARTIDA, no solo antes de empezarla. Una partida de 4000
        # acciones dura horas: mirar la carga una vez al arrancar no cede el box en ningun momento
        # util. Aca la partida se suspende de verdad si el ratio se paso mientras jugaba.
        if carga_maxima > 0 and len(serie) % ACCIONES_ENTRE_MIRADAS_DE_CARGA == 0:
            ratio, esperado = esperar_a_que_baje_la_carga(carga_maxima)
            ratios_vistos.append(round(ratio, 2))
            esperado_por_carga[0] += esperado
        if (
            al_avanzar is not None
            and volcar[0] is not None
            and len(serie) % ACCIONES_ENTRE_VOLCADOS == 0
        ):
            al_avanzar(volcar[0](estado, parcial=True))
        return frame

    def resumir(estado_final: str, parcial: bool) -> dict:
        """La fila del juego con lo que hay HASTA AHORA. La misma funcion arma el volcado parcial
        y el final: dos calculos separados divergirian y el parcial dejaria de ser comparable."""
        cpu = time.process_time() - cpu0
        reloj = time.monotonic() - reloj0
        acciones = len(serie)
        niveles_finales = int(serie[-1]["niveles"]) if serie else 0
        # Solo hitos DENTRO del tope pedido y, si la fila es PARCIAL, solo los ya alcanzados:
        # informar el hito 4000 en una corrida que va por la accion 2750 seria repetir el valor de
        # 2400 con otra etiqueta, o sea inventar una medicion que no se hizo.
        tope_vigente = int(clase_agente.MAX_ACTIONS)
        techo = min(tope_vigente, acciones) if parcial else tope_vigente
        por_hito = {
            str(hito): int(serie[min(hito, acciones) - 1]["niveles"]) if acciones else 0
            for hito in hitos
            if hito <= techo
        }
        subidas = [
            fila["accion"]
            for indice, fila in enumerate(serie)
            if fila["niveles"] > (serie[indice - 1]["niveles"] if indice else 0)
        ]

        # DERIVACION DEL CORTE POR RELOJ, con el PREDICADO REAL (`reloj_derivado`), no con una
        # cuota fija: el reloj mezcla CPU de la partida con pared restante del batch, y colapsarlo
        # a una sola moneda daba una respuesta falsa en cuanto la maquina esta contendida.
        serie_de_cpu = [f["cpu"] for f in serie]
        reloj_sin_espera = max(0.0, reloj - esperado_por_carga[0])
        factor = factor_pared_por_cpu(reloj_sin_espera, cpu)
        escenarios = (
            escenarios_de_corte(
                serie_de_cpu,
                presupuesto_segundos=presupuesto,
                total_de_juegos=juegos_del_batch,
                factor_medido=factor,
            )
            if serie_de_cpu and presupuesto > 0
            else {}
        )
        # EL numero que el entregable necesita es el de la maquina DEDICADA: Kaggle da el notebook
        # entero. El del box compartido viaja al lado, declarado, para que nadie lo confunda.
        dedicado = escenarios.get("maquinaDedicada", {})
        accion_del_reloj = dedicado.get("corteDeLaPrimeraPartida")
        niveles_al_corte = (
            int(serie[accion_del_reloj - 1]["niveles"]) if accion_del_reloj else niveles_finales
        )
        # BL.21800 -- `corteFue` dice COMO TERMINO LA PARTIDA, nunca donde habria cortado un reloj
        # que estaba apagado. Antes la rama `elif accion_del_reloj is not None: corte = "reloj"` iba
        # ANTES de `tope` y de `solo`, y `accion_del_reloj` sale de
        # `escenarios_de_corte(...)['maquinaDedicada']['corteDeLaPrimeraPartida']`, que es una
        # SIMULACION: esta partida corre con el reloj apagado, esa es la premisa del modulo. Con el
        # costo por accion REAL de lp85 (0,7255 s/accion, mediciones/BL21783_estrato_a.json) y el
        # batch por defecto de 25, el corte simulado cae en la accion 1.588: una partida que TERMINA
        # SOLA en la accion 2.000 se escribia con corteFue="reloj". Y hay tres consumidores que lo
        # leen como hecho -- mapa_de_juegos.py:140 (`termino_sola`, decide si el juego recibe
        # casillero), mapa_de_juegos.py:207 y curva_de_presupuesto.py:86 (`_llego_al_hito`) --, asi
        # que el efecto era una categoria falsa (`noMedible`) sobre una medicion concluyente y una
        # curva que perdia puntos legitimos. El contrafactual sigue publicandose, en su propio campo
        # (`accionEnQueElRelojHabriaCortado`) y ahora tambien como booleano explicito.
        if parcial:
            corte = "sinTerminar"
        elif estado_final.endswith("WIN"):
            corte = "gano"
        elif acciones >= tope_vigente:
            corte = "tope"
        else:
            corte = "solo"

        corte_del_tramo = max(1, int(acciones * (1.0 - FRACCION_DEL_TRAMO_FINAL)))
        firmas_al_empezar_el_tramo = serie[corte_del_tramo - 1]["firmas"] if serie else 0
        firmas_finales = serie[-1]["firmas"] if serie else 0
        acciones_del_tramo = max(1, acciones - corte_del_tramo)

        return {
            "juego": juego,
            "semilla": semilla,
            "parcial": parcial,
            "accionesConsumidas": acciones,
            "topeDeAcciones": tope_vigente,
            "nivelesFinales": niveles_finales,
            "nivelesPorHito": por_hito,
            "accionesDeCadaSubidaDeNivel": subidas,
            "corteFue": corte,
            "estadoFinal": estado_final,
            "cuotaDeRelojSegundos": round(cuota, 1),
            "presupuestoDelBatchSegundos": round(presupuesto, 1),
            "accionEnQueElRelojHabriaCortado": accion_del_reloj,
            # BL.21800: el contrafactual, explicito y separado de `corteFue`. True = el reloj del
            # entregable habria cortado ESTA partida antes de donde llego de verdad.
            "elRelojHabriaCortadoAntes": bool(
                accion_del_reloj is not None and accion_del_reloj <= acciones
            ),
            "escenariosDeCorteDelReloj": {
                nombre: {
                    clave: valor for clave, valor in datos.items() if clave != "posiciones"
                }
                for nombre, datos in escenarios.items()
            },
            "posicionesDeCorteEnElBatch": {
                nombre: [p["accionDeCorte"] for p in datos["posiciones"]]
                for nombre, datos in escenarios.items()
            },
            "nivelesAlCorteDelReloj": niveles_al_corte,
            "gameOvers": game_overs,
            "distribucionDeAcciones": dict(sorted(distribucion.items())),
            "coordenadasDistintas": len(coordenadas),
            "firmasDeEstadoDistintas": firmas_finales,
            "firmasDeMecanicaDistintas": len(firmas_de_mecanica),
            "firmasDeMecanicaCompuestas": sum(
                1 for etiqueta in firmas_de_mecanica if etiqueta.startswith("compuesta:")
            ),
            "firmasDeMecanicaMasVistas": dict(
                sorted(firmas_de_mecanica.items(), key=lambda par: -par[1])[:5]
            ),
            "novedadDelTramoFinal": firmas_finales - firmas_al_empezar_el_tramo,
            "novedadDelTramoFinalPorAccion": round(
                (firmas_finales - firmas_al_empezar_el_tramo) / acciones_del_tramo, 4
            ),
            "costo": {
                "cpuSegundos": round(cpu, 2),
                "relojSegundos": round(reloj, 2),
                # PARED SIN LA ESPERA VOLUNTARIA: es el unico pared que mide contencion de la
                # maquina. Mezclarlo con el tiempo que la partida se auto-suspendio cediendo el box
                # daria un factor de contencion inventado por la propia cortesia de la medicion.
                "relojSegundosSinEsperaDeCarga": round(reloj_sin_espera, 2),
                "segundosCedidosPorCarga": round(esperado_por_carga[0], 2),
                "factorParedPorCpu": round(factor, 2),
                "cpuSegundosPorAccion": round(cpu / max(1, acciones), 4),
                # EL REPARTO ENTORNO / AGENTE. Optimizar el agente compra acciones solo en la
                # medida en que el CPU sea suyo: si el paso del entorno se lleva la mayor parte,
                # el tope de 4.000 no se alcanza por mas rapida que se haga la politica.
                **reparto_de_cpu(cpu, cpu_del_entorno[0]),
                # LA CURVA DE COSTO, DERIVABLE. El informe anterior afirmaba "el costo crece con la
                # profundidad" con un numero que no estaba en ningun artefacto. Aca esta el costo
                # MARGINAL por tramo, calculado sobre la serie que se versiona abajo.
                "cpuPorAccionPorTramo": costo_por_accion_por_tramo(
                    serie_de_cpu, (100, 400, 800, 1200, 1600, 2400, 3200, 4000, acciones)
                ),
            },
            "ratiosDeCargaDurante": ratios_vistos[-20:],
            "ratioDeCargaMaximoVisto": round(max(ratios_vistos), 2) if ratios_vistos else None,
            # LA SERIE CRUDA, VERSIONADA. Sin esto, cualquier tabla del informe que hable de costo
            # por accion o de corte por reloj es un numero que nadie puede re-derivar -- que es
            # exactamente lo que el verificador encontro en la primera version de este BL. Con la
            # serie, `reloj_derivado.py` re-calcula todo sin volver a jugar.
            "serieDeCpuAcumulado": [round(c, 4) for c in serie_de_cpu],
            "serieDeFirmasDeEstado": [f["firmas"] for f in serie],
            "serieDePlantillasDeClick": [f["plantillas"] for f in serie],
        }

    volcar[0] = resumir
    agente.take_action = take_action
    try:
        agente.main()
    finally:
        # El espia se saca SIEMPRE: si una partida explota, la siguiente tiene que empezar con el
        # modulo limpio y no con una cadena de envoltorios encima.
        modulo.firma_de_mecanica = firma_original

    return resumir(str(agente.frames[-1].state), parcial=False)
