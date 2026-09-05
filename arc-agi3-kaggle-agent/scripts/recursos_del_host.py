"""recursos_del_host.py — BL.21937: cuantos cores hay, cuantos se pueden usar, y el ratio de carga.

POR QUE EXISTE, MEDIDO (2026-08-21). `gate_de_merge.py` informaba `cpusDeLaMaquina` desde
`os.cpu_count()` = 8 y lo imprimia AL LADO de la carga. Quien leia "carga 7,69 en 8 CPUs" calculaba
ratio 0,96 y concluia que el box estaba holgado; el ratio REAL era 1,28, porque este host reserva
cores para SSH y los utiles son 6. El numero era cierto y enganoso a la vez -- la clase de defecto
que el checklist de revision llama "el gate mide una operacion y su mensaje induce a concluir sobre
OTRA" (RFM-24). Y el docstring del costo, por su lado, tenia "6 vCPU" escrito a mano en dos lugares:
un resize de EC2 lo deja mintiendo en silencio, que es exactamente lo que BL.21696 vino a eliminar
del lado de los umbrales de carga.

DE DONDE SALEN LOS NUMEROS. `os.cpu_count()` da los TOTALES del host; `os.sched_getaffinity(0)` da
los que ESTE proceso puede usar, que es la definicion cpuset-aware de "utiles". Es la MISMA fuente
del sistema operativo que lee la SSOT del repo `scripts/lib/host-capacity.cjs` -- `getTotalCores()`,
`getCores()`/`getWorkerCores()` y `getSshReservedCores()`, que tambien deriva los reservados como
total menos utiles. VERIFICADO que coinciden: la SSOT dijo 8 / 2 / 6 y este modulo dice 8 / 2 / 6.

POR QUE NO SE INVOCA A NODE PARA PREGUNTARSELO A LA SSOT. Seria un subproceso y un modo de falla
nuevo (node ausente, timeout, cwd raro) para leer un dato que el kernel ya expone en este proceso.
La regla de fuente unica prohibe duplicar un VALOR o una POLITICA; aca no se hace ninguna de las
dos: no hay ningun numero escrito ni ninguna decision propia, solo la misma lectura del SO. Lo que
si seria una violacion -- y es lo que este modulo elimina -- es tener el "6" escrito a mano.

ESTE PAQUETE NO VIAJA. Vive en `scripts/`, no en `arc_agent/`, asi que no entra en el entregable
que arma `submission/build_agent.py` y no rompe la regla de cero dependencias del agente.
"""

from __future__ import annotations

import os

__all__ = ["cores", "texto_de_cores", "metricas_de_carga"]


def cores() -> dict[str, int]:
    """Cores UTILES, TOTALES y RESERVADOS -- derivados, nunca escritos a mano.

    Un resize de EC2 o un cambio del cpuset reservado se reflejan solos.
    """
    totales = os.cpu_count() or 1
    try:
        utiles = len(os.sched_getaffinity(0))  # cpuset-aware; no existe fuera de Linux
    except AttributeError:
        # Fail-safe: sin affinity lo unico honesto es no afirmar que hay reserva alguna.
        utiles = totales
    utiles = max(1, min(utiles, totales))
    return {"utiles": utiles, "totales": totales, "reservados": max(0, totales - utiles)}


def texto_de_cores(c: dict[str, int] | None = None) -> str:
    """Una linea que no se puede malinterpretar: dice cuantos hay y cuantos se pueden usar."""
    c = c or cores()
    if c["reservados"] <= 0:
        return f"{c['utiles']} cores utiles"
    return f"{c['utiles']} cores utiles de {c['totales']} totales ({c['reservados']} reservados)"


def metricas_de_carga() -> dict[str, object]:
    """Claves de carga para un reporte, con el desglose completo y el ratio YA calculado.

    El ratio viaja junto al load1 a proposito: es la unica forma de que quien lea el JSON no tenga
    que elegir un divisor, y elegir el equivocado es justo el defecto que este BL cierra.
    `coresUtiles` es el divisor correcto -- el mismo que usa `host-capacity.cjs::loadRatio`.
    """
    c = cores()
    load1 = os.getloadavg()[0]
    return {
        "coresUtiles": c["utiles"],
        "coresTotales": c["totales"],
        "coresReservados": c["reservados"],
        "cargaAlMedir": round(load1, 2),
        "ratioDeCargaAlMedir": round(load1 / c["utiles"], 2),
    }
