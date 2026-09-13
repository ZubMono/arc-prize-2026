"""[arc-agi3-kaggle-agent/scripts/fragilidad_del_veredicto] BL.21798 -- DE QUE CORRIDAS DEPENDE el
numero que decide, medido quitando corridas y volviendo a decidir.

POR QUE EXISTE. BL.21794 publico "de CERO a UNO" como resultado del barrido. Medido despues, el UNO
salia INTEGRO de tres ventanas de DOS corridas de fondo: quitando esas dos corridas del mismo corpus
de 33 ventanas el gate vuelve a CERO (30 eventos medibles, 9 transiciones, 6 juegos). El informe no
tenia como decirlo porque nadie lo calculaba: la fragilidad de un veredicto no es una propiedad de
la prosa, es una medicion, y esta es.

QUE MIDE, EXACTAMENTE. Leave-one-run-out sobre el MISMO corpus: para cada corrida presente se
recalculan los veredictos sin ella y se anota que tipos dejan de sostenerse. Una corrida cuya
ausencia tumba el numero que decide es CRITICA, y con una sola corrida critica el resultado es una
observacion, no una replica. Se agrega ademas, por transicion sostenedora, CUANTAS corridas
distintas la produjeron: una transicion producida por UNA sola corrida no tiene replica -- el repo
ya midio que el desvio entre semillas es 1,58 (BL.21594/BL.21783) y que `presupuesto_de_la_medicion`
pide N=4 para riesgo 0,10 con p=0,5.

LIMITE DECLARADO. La corrida es el proxy de la semilla porque el corpus persistido guarda el LOTE en
el `runId` y no la semilla: dos corridas distintas pueden haber corrido con la misma semilla y una
misma semilla en distinto lote pudo producir partidas distintas (la semilla de la redireccion salio
del lote hasta el commit e7f70322d1). O sea que este modulo mide dependencia de CORRIDAS, que es una
cota INFERIOR de la fragilidad frente a semillas; no la confunde con una medicion de varianza entre
semillas, que sigue sin hacerse.

Stdlib pura. SOLO REPO."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from medicion_de_evento import MedicionDeEvento  # noqa: E402
from vocabulario_de_objetivos import (  # noqa: E402
    CANDIDATOS,
    cuenta_como_observacion,
    resumen_de_candidatos,
    se_sostiene,
    vocabulario_rederivado,
)


def _tipos_que_deciden(mediciones: Sequence[MedicionDeEvento]) -> list[str]:
    """Los tipos de objetivo que SOBREVIVEN Y GENERALIZAN ENTRE JUEGOS -- el numero que decide de
    BL.21794, recalculado por el mismo camino que el informe."""
    return list(
        vocabulario_rederivado(resumen_de_candidatos(list(mediciones)))[
            "sobrevivenYGeneralizanEntreJuegos"
        ]
    )


def _sostiene_contando(nombre: str, medicion: MedicionDeEvento) -> bool:
    """El evento satisface el criterio Y cuenta como observacion suya (regla unica de BL.21728)."""
    return se_sostiene(nombre, medicion) and cuenta_como_observacion(
        CANDIDATOS[nombre].tipo, medicion
    )


def fragilidad_del_veredicto(mediciones: Sequence[MedicionDeEvento]) -> dict[str, Any]:
    """Leave-one-run-out sobre el corpus + de que corridas sale cada tipo que decide."""
    mediciones = list(mediciones)
    base = _tipos_que_deciden(mediciones)
    corridas = sorted({m.corrida for m in mediciones})

    criticas: dict[str, list[str]] = {}
    for corrida in corridas:
        sin_ella = [m for m in mediciones if m.corrida != corrida]
        perdidos = sorted(set(base) - set(_tipos_que_deciden(sin_ella)))
        if perdidos:
            criticas[corrida] = perdidos

    por_tipo: dict[str, Any] = {}
    for nombre in base:
        cuentan = [m for m in mediciones if _sostiene_contando(nombre, m)]
        por_transicion: dict[str, list[str]] = {}
        for medicion in cuentan:
            clave = f"{medicion.juego}:nivel{medicion.nivel_nuevo}"
            if medicion.corrida not in por_transicion.setdefault(clave, []):
                por_transicion[clave].append(medicion.corrida)
        por_tipo[nombre] = {
            "eventosQueCuentan": len(cuentan),
            "corridasQueLoSostienen": sorted({m.corrida for m in cuentan}),
            "corridasPorTransicion": {k: sorted(v) for k, v in sorted(por_transicion.items())},
            # Una transicion producida por UNA sola corrida es una observacion sin replica: si esa
            # corrida no se puede volver a producir, el veredicto tampoco.
            "transicionesConUnaSolaCorrida": sorted(
                k for k, v in por_transicion.items() if len(v) == 1
            ),
        }

    return {
        "tiposQueDecidenHoy": base,
        "corridasDelCorpus": len(corridas),
        "corridasCriticas": dict(sorted(criticas.items())),
        # LA PREGUNTA DE UNA LINEA: alcanza quitar UNA corrida para que el numero que decide caiga?
        "elNumeroCaeQuitandoUnaSolaCorrida": bool(criticas),
        "porTipo": por_tipo,
        "observacionesSinReplica": sorted(
            {t for datos in por_tipo.values() for t in datos["transicionesConUnaSolaCorrida"]}
        ),
    }


def lineas_de_fragilidad(fragilidad: dict[str, Any]) -> list[str]:
    """El informe imprime ESTO debajo del numero que decide. Si no hay nada que decidir tambien se
    dice: un veredicto en cero no tiene fragilidad que medir, y callar la seccion se leeria como que
    la medicion no se hizo."""
    lineas = [
        f"  corridas del corpus: {fragilidad['corridasDelCorpus']} | tipos que deciden hoy: "
        f"{fragilidad['tiposQueDecidenHoy'] or 'ninguno'}"
    ]
    if not fragilidad["tiposQueDecidenHoy"]:
        lineas.append("  no hay veredicto positivo que pueda caerse: nada que medir aca.")
        return lineas
    if fragilidad["elNumeroCaeQuitandoUnaSolaCorrida"]:
        lineas.append(
            "  EL NUMERO QUE DECIDE CAE QUITANDO UNA SOLA CORRIDA. No es una replica: es una"
        )
        lineas.append("  observacion que depende de partidas concretas.")
        for corrida, perdidos in fragilidad["corridasCriticas"].items():
            lineas.append(f"    sin {corrida} se pierde: {perdidos}")
    else:
        lineas.append(
            "  ninguna corrida sola tumba el veredicto (hace falta quitar mas de una)."
        )
    for nombre, datos in fragilidad["porTipo"].items():
        lineas.append(
            f"  {nombre}: {datos['eventosQueCuentan']} evento(s) que cuentan, de "
            f"{len(datos['corridasQueLoSostienen'])} corrida(s)"
        )
        for transicion, corridas in datos["corridasPorTransicion"].items():
            lineas.append(f"    {transicion} <- {corridas}")
        if datos["transicionesConUnaSolaCorrida"]:
            lineas.append(
                f"    SIN REPLICA (una sola corrida las produjo): "
                f"{datos['transicionesConUnaSolaCorrida']}"
            )
    return lineas


__all__ = ["fragilidad_del_veredicto", "lineas_de_fragilidad"]
