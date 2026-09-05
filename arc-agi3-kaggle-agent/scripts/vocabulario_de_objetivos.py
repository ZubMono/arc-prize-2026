"""[arc-agi3-kaggle-agent/scripts/vocabulario_de_objetivos] BL.21728 + BL.21765 -- los CANDIDATOS a
vocabulario de objetivos, sus criterios ejecutables y los gates que deciden cual entra.

Vive aparte de `caracterizar_completados.py` (que IMPRIME el informe) por tamano: ese modulo cruzo
el limite al agregarsele los candidatos objeto-centricos de BL.21765. Aca esta la DECISION; alla,
la presentacion. Ningun import en sentido contrario, para que no haya ciclo.

LAS CUATRO REGLAS DE BL.21728 SIGUEN VIGENTES Y NINGUNA SE AFLOJA (ver `caracterizar_completados`).
BL.21765 agrega, sin tocar ninguna:
  - dos candidatos que miden `recolectarTodo` y `pintarRegion` POR OBJETOS en vez de por
    `fraccion_no_fondo`, usando las firmas de BL.21741 que hasta este BL no llegaban a NINGUN
    criterio de tipo objetivo (la vista de la maniobra no tenia un solo campo de firma);
  - `juegosDistintos` / `sostenidoPorUnSoloJuego` en cada veredicto y un segundo escalon del
    vocabulario (`sobrevivenYGeneralizanEntreJuegos`), porque los juegos de evaluacion son OTROS y
    dos niveles del MISMO mundo no son evidencia de que la categoria transfiera;
  - `cobertura_de_transiciones`, que contesta con numeros cuantas transiciones distintas quedan
    cubiertas por un tipo que sobrevive y cuantas COMPARTEN tipo.

Stdlib pura. SOLO REPO."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from caracterizacion_de_niveles import MedicionDeEvento  # noqa: E402
from maniobra_previa import VistaDeLaManiobra  # noqa: E402

# El CATALOGO vive aparte (por tamano) y se re-exporta: los llamadores lo siguen importando desde
# aca, que es el punto de entrada de la decision.
from catalogo_de_candidatos import (  # noqa: E402,F401
    CANDIDATOS,
    MECANICAS_DE_OBJETO_UNICA,
    NO_MEDIBLES,
    Candidato,
)


#: Transiciones DISTINTAS (juego, nivel) minimas para postular un candidato como categoria del
#: vocabulario. DOS y no una: con una sola transicion no hay forma de distinguir "asi se gana en
#: estos juegos" de "asi se gana en ESTE juego", y el anti-objetivo explicito del skill
#: world-learning es inventar una categoria que el dato no sostiene. El contador es de transiciones
#: y no de juegos ni de eventos: cuatro semillas que superan el nivel 1 de lp85 capturan CUATRO
#: veces la MISMA transicion del MISMO mundo.
MINIMO_DE_TRANSICIONES = 2




def transiciones_distintas(mediciones: list[MedicionDeEvento]) -> set[tuple[str, int]]:
    """Pares (juego, nivel alcanzado) distintos. ES EL TAMANO REAL DE LA MUESTRA.

    Cuatro semillas que superan el nivel 1 de lp85 capturan CUATRO veces la misma transicion del
    mismo mundo: no son cuatro observaciones independientes, son una repetida. Reportar "6 de 14
    eventos" sin este contador al lado es la forma mas facil de sobrevender una muestra chica, y en
    un BL cuyo riesgo principal es "el agente persigue la meta equivocada con total confianza" eso
    no es un detalle de presentacion."""
    return {(m.juego, m.nivel_nuevo) for m in mediciones}


def prueba_de(nombre: str) -> Callable[[Any], bool]:
    """Criterio ejecutable de un candidato. OJO con el argumento: los de tipo objetivo esperan una
    `VistaDeLaManiobra` (usar `sujeto_de(nombre, medicion)`), no la medicion completa."""
    return CANDIDATOS[nombre].prueba


def sujeto_de(nombre: str, medicion: MedicionDeEvento) -> Any:
    """Lo que recibe el criterio de `nombre`: la vista de la maniobra si es un objetivo, la medicion
    entera si es un descriptor. UN SOLO lugar decide esto, para que ningun llamador pueda pasarle
    por error la medicion completa a un criterio de objetivo."""
    return medicion.maniobra if CANDIDATOS[nombre].tipo == "objetivo" else medicion


def se_sostiene(nombre: str, medicion: MedicionDeEvento) -> bool:
    return bool(CANDIDATOS[nombre].prueba(sujeto_de(nombre, medicion)))


def cuenta_como_observacion(tipo: str, medicion: MedicionDeEvento) -> bool:
    """UNA sola regla decide si un evento que satisface un criterio CUENTA como observacion suya.

    ES LA REGLA DE BL.21728 (defensa 4) Y AHORA SU FUENTE UNICA (correccion de BL.21798). Una
    afirmacion sobre la MANIOBRA necesita frames de maniobra que no sean inertes ni parte de una
    animacion en loop; un descriptor habla del frame del evento y ese siempre existe.

    POR QUE EXISTE ESTA FUNCION Y NO LA CONDICION EN LINEA. La regla estaba escrita solo dentro de
    `_veredicto`, asi que `cobertura_de_transiciones` -- que llama `se_sostiene` directo -- contaba
    eventos que el veredicto ya habia decidido que no cuentan. Medido sobre el corpus de 33
    ventanas: el informe publicaba `resueltoTocandoUnObjeto` con 2 transiciones en `candidatos` y
    con 3 (`ft09:nivel1` incluida, cuyos dos eventos tienen 0 pasos informativos) en
    `coberturaDeTransiciones`. Dos conteos incompatibles de la MISMA pregunta en el mismo JSON:
    RFM-06 del checklist, y el filtro tiene que salir de aca o vuelve a divergir."""
    return tipo != "objetivo" or medicion.maniobra.pasos_informativos > 0


def _varianza_de_los_insumos(
    nombre: str, mediciones: list[MedicionDeEvento]
) -> dict[str, int]:
    """Cuantos valores DISTINTOS tomo cada insumo del criterio en toda la muestra.

    POR QUE EXISTE (correccion de BL.21728). El cierre del BL presentaba "`recolectarTodo` y
    `alcanzarDestino` caen a 0/14" como dos refutaciones del mismo arreglo. Solo la primera lo es:
    `recolectarTodo` pasa de 6/14 a 0/14 al sacar el frame del evento -- ahi hubo varianza y el
    criterio la perdio. `alcanzarDestino` nunca tuvo un evento a favor NI en contra: su tercer
    insumo (`aproximacion_monotona_en_la_maniobra`) esta VACIO en los 14 eventos, o sea que el
    corpus no contiene ninguna aproximacion monotona de 3 puntos y el criterio no pudo evaluarse.
    Presentar un 0/14 sin varianza como resultado del arreglo infla lo que el BL demostro: para el
    proximo paso la diferencia es RECAPTURAR contra DESCARTAR."""
    candidato = CANDIDATOS.get(nombre)
    if candidato is None or not candidato.insumos:
        return {}
    distintos: dict[str, int] = {}
    for campo in candidato.insumos:
        valores = set()
        for medicion in mediciones:
            sujeto = sujeto_de(nombre, medicion)
            valor = getattr(sujeto, campo, None)
            valores.add(tuple(valor) if isinstance(valor, (list, tuple)) else valor)
        distintos[campo] = len(valores)
    return distintos


def _evidencia(sostenidos: list[MedicionDeEvento]) -> dict[str, int]:
    """Frames REALES detras de un veredicto, en las tres categorias que no valen lo mismo."""
    vistas: list[VistaDeLaManiobra] = [m.maniobra for m in sostenidos]
    return {
        "framesInformativos": sum(v.pasos_informativos for v in vistas),
        "framesInertes": sum(v.pasos_inertes for v in vistas),
        "framesEnAnimacion": sum(v.pasos_en_animacion for v in vistas),
        "eventosConVentanaTruncada": sum(1 for v in vistas if v.ventana_truncada),
        "eventosConAnimacionEnLoop": sum(1 for v in vistas if v.animacion_en_loop),
        # BL.21765: eventos cuyos pasos informativos NO traen firma medida. Un criterio de firma
        # que da False sobre estos lo hace por AUSENCIA DE PERCEPCION, no por ausencia del rasgo;
        # sin este contador las dos cosas se leen igual, que es exactamente el error que hizo
        # falta corregir cuando la firma valia "desconocida" en los 14 eventos.
        "eventosSinFirmasMedidas": sum(1 for v in vistas if v.maniobra_sin_firmas_medidas),
        # ...y su vecino, que ANTES se confundia con el anterior: no hay pasos informativos que
        # mirar (todos inertes, o la serie entera es un loop). Medido: los 2 eventos de ft09 salian
        # marcados "sin firmas medidas" teniendo las 9 firmas medidas.
        "eventosSinPasosInformativos": sum(1 for v in vistas if v.sin_pasos_informativos),
        # FRAMES QUE SON UN CICLO DE DOS ESTADOS y que la deteccion de loop no puede alcanzar
        # porque cambian 265 o 266 celdas segun el paso. Se declaran para que "18 frames
        # informativos" no se lea como 18 frames de maniobra.
        "framesEnOscilacion": sum(v.pasos_en_oscilacion for v in vistas),
        "eventosConOscilacionDeFirmas": sum(1 for v in vistas if v.oscilacion_de_firmas),
        # Agujeros DECLARADOS: pasos que el detector se nego a mirar (`sobreElTope` /
        # `formaIncompatible`). Cero clusters ahi no es evidencia de quietud.
        "framesNoMirados": sum(v.pasos_no_mirados_en_la_maniobra for v in vistas),
        "eventosConPasosNoMirados": sum(
            1 for v in vistas if v.pasos_no_mirados_en_la_maniobra > 0
        ),
    }


def _veredicto(
    nombre: str,
    tipo: str,
    criterio: str,
    sostenidos: list[MedicionDeEvento],
    mediciones: list[MedicionDeEvento],
) -> dict[str, Any]:
    """Conteos + los DOS gates que deciden si el candidato entra al vocabulario.

    `muestraChica` mira TRANSICIONES DISTINTAS y no juegos ni eventos, y NO es decorativo: pone
    `sobrevive` en False. `sinFramesReales` solo aplica a los de tipo objetivo -- una afirmacion
    sobre la MANIOBRA necesita frames de maniobra que no sean inertes ni parte de una animacion;
    un descriptor habla del frame del evento y ese siempre existe.

    LA MUESTRA SE CUENTA SOBRE LOS EVENTOS QUE TIENEN EVIDENCIA PROPIA (correccion de BL.21728).
    `sinFramesReales` era una SUMA sobre todos los sostenidos: con `MINIMO_DE_TRANSICIONES = 2`, un
    candidato entraba al vocabulario con 1 observacion real + 1 VACIA, porque la vacia igual sumaba
    una transicion distinta y la suma de frames informativos daba > 0 gracias a la otra. O sea que
    la mitad de la evidencia podia ser una maniobra con CERO frames informativos -- justo la
    categoria que este BL creo para decir "esto no sostiene ningun veredicto". Ahora un evento sin
    un solo frame informativo NO cuenta para `transicionesDistintas` de un objetivo: no se lo saca
    del informe (sigue en `eventos`, en la evidencia y en `eventosSinFramesReales`), se lo deja de
    contar como observacion."""
    # Un objetivo habla de la MANIOBRA: un evento cuya maniobra no tiene un solo frame informativo
    # no puede sostenerlo, ni siquiera como "la segunda transicion". Los descriptores hablan del
    # frame del evento, que siempre existe, asi que para ellos la poblacion es la misma.
    con_frames = [m for m in sostenidos if cuenta_como_observacion(tipo, m)]
    distintas = len(transiciones_distintas(con_frames))
    juegos = sorted({m.juego for m in con_frames})
    evidencia = _evidencia(sostenidos)
    muestra_chica = 0 < distintas < MINIMO_DE_TRANSICIONES
    # BL.21765: NO gatea `sobrevive` -- el gate sigue siendo el de BL.21728, transiciones distintas,
    # y aflojarlo o endurecerlo en silencio seria cambiar la vara despues de ver el resultado. Se
    # REPORTA porque es la pregunta que decide si el vocabulario sirve: los juegos de evaluacion
    # son OTROS, y dos niveles del mismo mundo pueden compartir mecanica por ser el mismo mundo.
    un_solo_juego = len(juegos) == 1
    # Los dos gates solo tienen sentido si hay algo que gatear: con cero eventos el motivo es
    # "nadie lo sostiene" y agregarle "ademas no tiene frames" seria ruido.
    sin_frames = bool(sostenidos) and tipo == "objetivo" and not con_frames
    motivos: list[str] = []
    if not sostenidos:
        motivos.append("ningun evento lo sostiene")
    if muestra_chica:
        motivos.append(
            f"muestra chica: {distintas} transicion(es) distinta(s), hacen falta "
            f"{MINIMO_DE_TRANSICIONES}"
        )
    if sin_frames:
        motivos.append(
            "ninguno de los eventos que lo sostienen tiene un solo frame informativo (todos "
            "inertes o parte de una animacion en loop)"
        )
    elif len(con_frames) < len(sostenidos):
        motivos.append(
            f"{len(sostenidos) - len(con_frames)} de {len(sostenidos)} evento(s) que lo sostienen "
            "no tienen frames informativos y NO cuentan para la muestra"
        )
    # SIN MEDIR != REFUTADO. Con CERO eventos a favor y AL MENOS UN insumo que no vario en toda la
    # muestra, el veredicto lo fija esa constante y no se puede distinguir "el rasgo no esta" de
    # "el corpus no tiene con que evaluarlo". El caso que lo motiva:
    # `aproximacion_monotona_en_la_maniobra` esta VACIO en los 14 eventos, asi que `alcanzarDestino`
    # da 0/14 sin una sola observacion en contra -- y el cierre del BL lo presentaba como una
    # refutacion al mismo nivel que `recolectarTodo`, que si paso de 6/14 a 0/14.
    varianza = _varianza_de_los_insumos(nombre, mediciones)
    constantes = sorted(campo for campo, valores in varianza.items() if valores <= 1)
    sin_varianza = bool(mediciones) and not sostenidos and bool(constantes)
    if sin_varianza:
        motivos.append(
            "SIN MEDIR, no refutado: "
            f"{', '.join(constantes)} no tomo mas de un valor en los {len(mediciones)} eventos, "
            "asi que el criterio no tuvo con que dar True ni False"
        )
    return {
        "tipo": tipo,
        "criterio": criterio,
        "varianzaDeLosInsumos": varianza,
        "insumosSinVarianza": constantes,
        "sinVarianzaEnLosInsumos": sin_varianza,
        "evaluadoSobre": CANDIDATOS[nombre].se_evalua_sobre if nombre in CANDIDATOS else "maniobra",
        "eventos": len(sostenidos),
        # Sostenidos cuya maniobra no tiene NI UN frame informativo: no cuentan como observacion de
        # un objetivo (ver el docstring de `_veredicto`). Se publican para que la resta se lea.
        "eventosSinFramesReales": len(sostenidos) - len(con_frames),
        "deEventos": len(mediciones),
        "transicionesDistintas": distintas,
        "deTransiciones": len(transiciones_distintas(mediciones)),
        "juegos": juegos,
        "juegosDistintos": len(juegos),
        **evidencia,
        "muestraChica": muestra_chica,
        "sinFramesReales": sin_frames,
        "sostenidoPorUnSoloJuego": un_solo_juego,
        "sobrevive": bool(sostenidos) and not muestra_chica and not sin_frames,
        "generalizaEntreJuegos": (
            bool(sostenidos) and not muestra_chica and not sin_frames and not un_solo_juego
        ),
        "porQueNoSobrevive": motivos,
    }


def resumen_de_candidatos(mediciones: list[MedicionDeEvento]) -> dict[str, dict[str, Any]]:
    """Para cada candidato: cuantos eventos lo sostienen, sobre cuantas transiciones distintas, con
    cuantos frames reales, y si SOBREVIVE al gate de muestra."""
    resumen: dict[str, dict[str, Any]] = {}
    for nombre, candidato in CANDIDATOS.items():
        sostenidos = [m for m in mediciones if se_sostiene(nombre, m)]
        resumen[nombre] = _veredicto(
            nombre, candidato.tipo, candidato.criterio, sostenidos, mediciones
        )

    # Solo los candidatos de tipo OBJETIVO cuentan para "conocido": un evento que unicamente
    # satisface descriptores no tiene objetivo identificado. Y ojo -- un objetivo que NO SOBREVIVE
    # al gate tampoco identifica nada, asi que su masa vuelve al desconocido: contar como "conocido"
    # un evento sostenido por una categoria que el informe acaba de rechazar seria inflar la
    # cobertura por la puerta de atras.
    # Y la MISMA regla que el veredicto y que la cobertura (BL.21798): un evento cuya maniobra no
    # tiene un solo frame informativo no puede sostener una afirmacion sobre la maniobra, asi que
    # tampoco tiene objetivo IDENTIFICADO -- su masa vuelve al desconocido. Antes de esta correccion
    # los 2 eventos de ft09:nivel1 salian del residuo por un criterio que el propio informe no
    # contaba como evidencia: la tercera copia de la misma divergencia.
    con_objetivo_valido = {
        nombre for nombre, datos in resumen.items() if datos["tipo"] == "objetivo" and datos["sobrevive"]
    }
    sin_objetivo = [
        m
        for m in mediciones
        if not any(
            se_sostiene(nombre, m) and cuenta_como_observacion(CANDIDATOS[nombre].tipo, m)
            for nombre in con_objetivo_valido
        )
    ]
    resumen["objetivoDesconocido"] = {
        **_veredicto("objetivoDesconocido", "objetivo", "", sin_objetivo, mediciones),
        "criterio": "ningun candidato de tipo objetivo que SOBREVIVA al gate de muestra se sostiene; "
        "es la masa que el posterior debe reservar con piso, igual que hace mechanics_posterior.py "
        "con las mecanicas",
        # El residuo no es una categoria postulada: no se le exige superar el gate para "existir".
        "sobrevive": bool(sin_objetivo),
        "porQueNoSobrevive": [],
    }
    return resumen


def vocabulario_rederivado(resumen: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Que tipos de OBJETIVO quedan en pie y cuales se cayeron. `objetivoDesconocido` no participa:
    es el residuo, no una categoria candidata."""
    objetivos = [
        n for n, d in resumen.items() if d["tipo"] == "objetivo" and n != "objetivoDesconocido"
    ]
    # TRES ESTADOS Y NO DOS (correccion de BL.21728): un candidato cuyos insumos nunca variaron no
    # esta refutado -- esta SIN MEDIR, igual que los de `NO_MEDIBLES`, y la diferencia decide si el
    # proximo paso es recapturar o descartar. `seCayeron` se conserva como la union de los dos para
    # no romper a los llamadores que ya lo leen.
    sin_medir = [n for n in objetivos if resumen[n].get("sinVarianzaEnLosInsumos")]
    return {
        "sobreviven": [n for n in objetivos if resumen[n]["sobrevive"]],
        "sinMedir": sin_medir,
        "refutados": [
            n for n in objetivos if not resumen[n]["sobrevive"] and n not in sin_medir
        ],
        # SEGUNDO ESCALON (BL.21765). Sobrevivir al gate de muestra y transferir a otro mundo no
        # son la misma afirmacion: `MINIMO_DE_TRANSICIONES` fue puesto para distinguir "asi se gana
        # en estos juegos" de "asi se gana en ESTE juego", y dos niveles del mismo juego pasan ese
        # gate sin resolver esa duda. Un planner que quiera apostar en un mundo NO VISTO tiene que
        # mirar esta lista, no la de arriba.
        "sobrevivenYGeneralizanEntreJuegos": [
            n for n in objetivos if resumen[n]["generalizaEntreJuegos"]
        ],
        "seCayeron": [n for n in objetivos if not resumen[n]["sobrevive"]],
    }


def cobertura_de_transiciones(
    mediciones: list[MedicionDeEvento], resumen: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """LAS DOS PREGUNTAS DE BL.21765, contestadas con numeros sobre TRANSICIONES y no sobre eventos.

    1. Cuantas de las transiciones distintas quedan cubiertas por un tipo de objetivo que SOBREVIVE.
    2. Cuantas COMPARTEN tipo con otra transicion -- que es la unica evidencia de que el vocabulario
       generaliza en vez de tener una etiqueta por evento. Un tipo que cubre UNA sola transicion no
       es vocabulario: es un nombre propio.

    Se agrega ademas la firma DOMINANTE de la maniobra de cada transicion, que es la lectura directa
    de la percepcion de BL.21741 sobre los frames previos, para poder ver si dos transiciones se
    resolvieron repitiendo la misma mecanica aunque ningun candidato las cubra.

    LA COBERTURA SE CUENTA CON LA MISMA REGLA QUE EL VEREDICTO (correccion de BL.21798). Hasta este
    BL esta funcion llamaba `se_sostiene` sin el filtro de `cuenta_como_observacion`, asi que una
    transicion cuyos eventos no tienen UN SOLO frame informativo entraba como "cubierta" mientras el
    veredicto del mismo tipo, en el mismo JSON, no la contaba. Medido: 3/9 publicado contra 2/9 con
    la regla del veredicto (`ft09:nivel1`, 2 eventos con 0 pasos informativos). Lo que sostienen
    esos eventos NO se borra -- se reporta aparte, en `tiposQueLaSostienenSinFramesInformativos`:
    "ft09 se gana clickeando un objeto pero su ventana no tiene con que demostrarlo" es informacion,
    y esconderla seria el error simetrico al que se esta corrigiendo."""
    vivos = [
        n
        for n, d in resumen.items()
        if d["tipo"] == "objetivo" and n != "objetivoDesconocido" and d["sobrevive"]
    ]
    por_transicion: dict[tuple[str, int], dict[str, Any]] = {}
    for medicion in mediciones:
        clave = (medicion.juego, medicion.nivel_nuevo)
        entrada = por_transicion.setdefault(
            clave,
            {
                "tipos": set(),
                "sinEvidenciaPropia": set(),
                "firmasDominantes": set(),
                "firmasDelEvento": set(),
            },
        )
        sostenidos_aca = {n for n in vivos if se_sostiene(n, medicion)}
        entrada["tipos"].update(
            n for n in sostenidos_aca if cuenta_como_observacion(CANDIDATOS[n].tipo, medicion)
        )
        entrada["sinEvidenciaPropia"].update(
            n for n in sostenidos_aca if not cuenta_como_observacion(CANDIDATOS[n].tipo, medicion)
        )
        dominante = medicion.maniobra.firma_dominante_en_la_maniobra
        entrada["firmasDominantes"].add(dominante if dominante is not None else "sinPasosInformativos")
        entrada["firmasDelEvento"].add(medicion.firma_del_evento)

    transiciones_por_tipo: dict[str, list[str]] = {n: [] for n in vivos}
    for (juego, nivel), entrada in por_transicion.items():
        for tipo in entrada["tipos"]:
            transiciones_por_tipo[tipo].append(f"{juego}:nivel{nivel}")
    compartidos = {n for n, ts in transiciones_por_tipo.items() if len(ts) >= 2}

    detalle = {
        f"{juego}:nivel{nivel}": {
            "tiposQueLaCubren": sorted(entrada["tipos"]),
            # Tipos que SI satisfacen su criterio en esta transicion pero sobre eventos sin un solo
            # frame informativo: no cuentan como cobertura (misma regla que el veredicto) y se
            # publican para no perder la observacion.
            "tiposQueLaSostienenSinFramesInformativos": sorted(
                entrada["sinEvidenciaPropia"] - entrada["tipos"]
            ),
            "firmaDominanteDeLaManiobra": sorted(entrada["firmasDominantes"]),
            "firmaDelEvento": sorted(entrada["firmasDelEvento"]),
            "comparteTipoConOtraTransicion": any(t in compartidos for t in entrada["tipos"]),
        }
        for (juego, nivel), entrada in sorted(por_transicion.items())
    }
    return {
        "transicionesDistintas": len(por_transicion),
        "transicionesCubiertas": sum(1 for d in detalle.values() if d["tiposQueLaCubren"]),
        "transicionesSostenidasSinFramesInformativos": sum(
            1 for d in detalle.values() if d["tiposQueLaSostienenSinFramesInformativos"]
        ),
        "transicionesQueComparten": sum(
            1 for d in detalle.values() if d["comparteTipoConOtraTransicion"]
        ),
        "tiposQueCubrenMasDeUnaTransicion": sorted(compartidos),
        "transicionesPorTipo": {n: sorted(ts) for n, ts in sorted(transiciones_por_tipo.items())},
        "porTransicion": detalle,
    }
