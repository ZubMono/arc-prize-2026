"""[arc-agi3-kaggle-agent/scripts/clasificacion_del_corpus] BL.21794 -- dos auditorias sobre el
corpus persistido que el informe imprime ANTES de hablar de candidatos.

1) DE DONDE SALIO CADA VENTANA. Desde este BL el corpus mezcla dos poblaciones que NO son
   intercambiables: las corridas de la politica entregada y las corridas de MEDICION con cobertura
   de fondo forzada, que puntuan peor a proposito. Un informe que las sume sin decirlo estaria
   describiendo el comportamiento del agente entregado con partidas que no son las suyas -- el
   mismo error de categoria que BL.21744 cerro del lado del gate ("una base de otra configuracion
   no es una base"). La marca viaja en el `runId` y se lee de ahi, no de un registro aparte que
   pueda desincronizarse.

2) LA CLASIFICACION DE FRAMES: DEL CORPUS O RECONSTRUIDA. BL.21794 hace que la captura decida y
   GUARDE la clase de cada frame (`informativo` / `inerte` / `enAnimacion`). Las ventanas anteriores
   -- las 14 que fundaron BL.21728 y BL.21765 -- no la traen, y el informe las sigue midiendo
   reconstruyendola. Las dos cosas son legitimas; confundirlas no. Esta auditoria dice cuantos
   frames vienen clasificados de origen y, sobre esos, en cuantos la clase guardada COINCIDE con la
   que el informe re-deriva.

   EL DESACUERDO NO SE ESCONDE NI TUMBA EL INFORME, SE DECLARA. Los veredictos del vocabulario los
   sigue calculando la RE-DERIVACION, que es lo que se venia haciendo y no depende de la plomeria
   del corpus. La clase guardada es un CHEQUEO, del mismo tipo que el censo del exportador: dos
   caminos que tienen que dar lo mismo. Y puede legitimamente no darlo -- el export reconstruye las
   ventanas por bloques contiguos de `stepNum`, asi que una ventana exportada puede tener frames que
   en la captura pertenecian a OTRA ventana y cuya clase se decidio en esa otra serie. Por eso el
   numero que se publica es el ACUERDO, no un booleano de "esta bien".

Stdlib pura. SOLO REPO."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from captura_de_niveles import (  # noqa: E402
    CLASE_DEL_EVENTO,
    CLASE_POSTERIOR_AL_EVENTO,
    CLASE_SIN_PREVIO,
)
from cobertura_de_fondo import es_corrida_con_fondo  # noqa: E402


def origen_de_la_muestra(ventanas: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Cuantas ventanas y cuantas transiciones distintas aporta cada poblacion.

    Las transiciones se cuentan por poblacion Y en total: una transicion que solo existe en las
    corridas de fondo es evidencia que la politica entregada no produjo, y un lector tiene que poder
    verlo sin recorrer el JSONL."""
    normales = [v for v in ventanas if not es_corrida_con_fondo(str(v.get("corrida", "")))]
    con_fondo = [v for v in ventanas if es_corrida_con_fondo(str(v.get("corrida", "")))]

    def _transiciones(grupo: Sequence[dict[str, Any]]) -> list[str]:
        return sorted({f"{v.get('juego', '?')}:nivel{v.get('nivelNuevo', 0)}" for v in grupo})

    def _juegos(grupo: Sequence[dict[str, Any]]) -> list[str]:
        return sorted({str(v.get("juego", "?")) for v in grupo})

    solo_de_fondo = sorted(set(_transiciones(con_fondo)) - set(_transiciones(normales)))
    # BL.21798 -- CUALES DE ESTAS VENTANAS SE PUEDEN VOLVER A PRODUCIR. La semilla declarada viaja
    # en el corpus desde este BL; las capturadas antes no la traen, y el `runId` NO sirve de
    # reemplazo (lleva el lote, y el lote dejo de sembrar en e7f70322d1). Sin este contador el
    # lector no puede distinguir "corpus reproducible" de "corpus que nadie puede regenerar", que
    # es exactamente lo que le paso a la receta de reproduccion de BL.21794.
    con_semilla = [v for v in ventanas if str(v.get("semilla") or "")]
    return {
        "ventanasConSemillaDeclarada": len(con_semilla),
        "ventanasSinSemillaDeclarada": len(ventanas) - len(con_semilla),
        "semillasDeclaradas": sorted({str(v.get("semilla")) for v in con_semilla}),
        "ventanasDePoliticaEntregada": len(normales),
        "ventanasConCoberturaDeFondo": len(con_fondo),
        "transicionesDePoliticaEntregada": _transiciones(normales),
        "transicionesConCoberturaDeFondo": _transiciones(con_fondo),
        "juegosDePoliticaEntregada": _juegos(normales),
        "juegosConCoberturaDeFondo": _juegos(con_fondo),
        # Lo que la muestra nueva agrego y la vieja no tenia. Es la unica forma de justificar el
        # costo de una fase que puntua peor a proposito.
        "transicionesQueSoloExistenConFondo": solo_de_fondo,
    }


#: Clases que NO describen una transicion de la maniobra y por lo tanto no se re-derivan: el
#: informe las conoce por posicion dentro de la ventana, no por medicion.
CLASES_FUERA_DE_LA_MANIOBRA = (CLASE_SIN_PREVIO, CLASE_DEL_EVENTO, CLASE_POSTERIOR_AL_EVENTO)


def auditoria_de_la_clasificacion(ventanas: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Frames que traen clase DEL CORPUS, y cuantos de esos coinciden con la re-derivacion.

    Se recorre cada ventana, se re-deriva la clasificacion de su maniobra exactamente como lo hace
    `medir_evento` (misma `pasos_de_la_ventana` + `clasificar_pasos`) y se compara frame a frame
    contra lo que trae el corpus. Los frames fuera de la maniobra se cuentan aparte: su clase es
    posicional y compararla no mide nada.

    LA FIRMA TAMBIEN SE CHEQUEA (BL.21798). La captura persiste DOS campos por frame -- `claseDePaso`
    y `firmaDelPaso` -- y hasta este BL esta auditoria comparaba solo el primero: `firmaDelPaso`
    viajaba a Mongo, volvia por el export y no lo leia NADIE (18 apariciones en el repo, todas de
    escritura, plomeria o tests). Era RFM-08 en version suave -- el informe listaba los dos campos
    como "lo que la captura persiste", lo que se lee como que los dos se chequean. Ahora el segundo
    tiene un lector real y su acuerdo se publica al lado del otro."""
    # Import local por el mismo motivo que en `captura_de_niveles`: arrastra la percepcion de
    # `arc_agent/` y este modulo tambien lo importan herramientas que solo miran procedencia.
    from caracterizacion_de_niveles import indice_del_evento, pasos_de_la_ventana  # noqa: PLC0415
    from paso_de_la_maniobra import clasificar_pasos  # noqa: PLC0415

    frames_totales = 0
    con_clase = 0
    de_maniobra_con_clase = 0
    coinciden = 0
    discrepancias: list[dict[str, Any]] = []
    ventanas_clasificadas = 0
    conteo_por_clase: dict[str, int] = {}
    con_firma = 0
    de_maniobra_con_firma = 0
    coinciden_firmas = 0
    discrepancias_de_firma: list[dict[str, Any]] = []

    for ventana in ventanas:
        frames = ventana.get("frames") or []
        frames_totales += len(frames)
        traen = [f for f in frames if isinstance(f.get("claseDePaso"), str) and f["claseDePaso"]]
        con_clase += len(traen)
        con_firma += sum(
            1 for f in frames if isinstance(f.get("firmaDelPaso"), str) and f["firmaDelPaso"]
        )
        if traen:
            ventanas_clasificadas += 1
        for frame in traen:
            clase = str(frame["claseDePaso"])
            conteo_por_clase[clase] = conteo_por_clase.get(clase, 0) + 1

        indice = indice_del_evento(frames, ventana.get("pasoDelEvento", -1))
        if indice <= 0:
            continue
        pasos = pasos_de_la_ventana(frames, indice)
        rederivadas = clasificar_pasos(pasos)
        for i in range(1, indice):
            guardada = frames[i].get("claseDePaso")
            firma_guardada = frames[i].get("firmaDelPaso")
            if isinstance(firma_guardada, str) and firma_guardada:
                de_maniobra_con_firma += 1
                firma_esperada = pasos[i - 1].firma
                if firma_guardada == firma_esperada:
                    coinciden_firmas += 1
                else:
                    discrepancias_de_firma.append(
                        {
                            "corrida": ventana.get("corrida"),
                            "paso": frames[i].get("paso"),
                            "enElCorpus": firma_guardada,
                            "reDerivada": firma_esperada,
                        }
                    )
            if not isinstance(guardada, str) or not guardada:
                continue
            de_maniobra_con_clase += 1
            esperada = rederivadas[i - 1]
            if guardada == esperada:
                coinciden += 1
            else:
                discrepancias.append(
                    {
                        "corrida": ventana.get("corrida"),
                        "paso": frames[i].get("paso"),
                        "enElCorpus": guardada,
                        "reDerivada": esperada,
                    }
                )

    return {
        "framesDelCorpus": frames_totales,
        "framesConClaseDeLaCaptura": con_clase,
        "ventanasConClaseDeLaCaptura": ventanas_clasificadas,
        "ventanasSinClasificar": len(ventanas) - ventanas_clasificadas,
        "framesDeManiobraComparables": de_maniobra_con_clase,
        "framesDeManiobraQueCoinciden": coinciden,
        "acuerdo": (
            round(coinciden / de_maniobra_con_clase, 4) if de_maniobra_con_clase else None
        ),
        "conteoPorClase": dict(sorted(conteo_por_clase.items())),
        # Se publican las primeras, no todas: si hay muchas el problema no es el detalle sino que
        # el corpus y el analisis dejaron de hablar de la misma maniobra.
        "discrepancias": discrepancias[:10],
        "cantidadDeDiscrepancias": len(discrepancias),
        # BL.21798 -- el segundo campo que la captura persiste, con su propio lector.
        "framesConFirmaDeLaCaptura": con_firma,
        "framesDeManiobraConFirmaComparable": de_maniobra_con_firma,
        "framesDeManiobraConFirmaQueCoincide": coinciden_firmas,
        "acuerdoDeFirmas": (
            round(coinciden_firmas / de_maniobra_con_firma, 4) if de_maniobra_con_firma else None
        ),
        "discrepanciasDeFirma": discrepancias_de_firma[:10],
        "cantidadDeDiscrepanciasDeFirma": len(discrepancias_de_firma),
    }


__all__ = [
    "CLASES_FUERA_DE_LA_MANIOBRA",
    "auditoria_de_la_clasificacion",
    "origen_de_la_muestra",
]
