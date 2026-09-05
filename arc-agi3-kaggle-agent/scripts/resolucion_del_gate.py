#!/usr/bin/env python3
"""resolucion_del_gate.py — BL.22395. ¿El gate de merge MIDE algo, o mide ruido?

EL PROBLEMA, MEDIDO 2026-08-24. BL.22236 (usar todas las capas de frame.frame) y BL.22237
(revalidar still_holds contra la ventana FIFO completa) se implementaron por separado, en
subsistemas DISTINTOS, con tests unitarios que prueban que cada uno cambia el comportamiento que
dice cambiar. Contra `make gate`:

    baseline  -> 14        desglose: ar25=2 ft09=3 lp85=3 m0r0=1 vc33=5, resto 0
    BL.22236  -> 14 (+0)   desglose: ar25=2 ft09=3 lp85=3 m0r0=1 vc33=5, resto 0   <- IDENTICO
    BL.22237  -> 14 (+0)

Dos cambios independientes produciendo exactamente la misma particion de niveles en LOS 25 JUEGOS
no es evidencia de que las mejoras no sirvan: es la firma de que EL INSTRUMENTO NO LAS VE.

Y el instrumento tiene PODER DE VETO: `gate_de_merge.py` rechaza (exit 1) todo delta<=0. O sea que
cualquier mejora real que no complete un nivel nuevo se rechaza automaticamente.

QUE MIDE ESTE SCRIPT, y por que es el que decide todo lo demas (punto 2 del BL): corre el MISMO
codigo N veces con tandas de semillas DISTINTAS y reporta la dispersion de `nivelesTotales`. Es el
control que separa dos estados que hoy se ven iguales:

    Estado A: "delta=+1 significa que el agente mejoro."
    Estado B: "delta=+1 es lo que este instrumento hace solo, sin que nada cambie."

Si el rango entre corridas IDENTICAS es >= 1 nivel, entonces delta=+1 NO es señal y el umbral
actual del gate es ruido — y eso no se arregla mirando mas fuerte, hay que cambiar el instrumento.

NO TOCA EL AGENTE. Es puramente medicion, y su salida es un JSON re-ejecutable: el numero que
reporta se puede volver a producir con el mismo comando.

Uso:
    python3 scripts/resolucion_del_gate.py --corridas 5 --pasos 200
    python3 scripts/resolucion_del_gate.py --corridas 3 --pasos 200 --salida runtime_reports/resolucion.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
GATE = RAIZ / "scripts" / "gate_de_merge.py"


def resolver_proyecto() -> Path:
    """La raiz del proyecto donde el gate PUEDE correr de verdad.

    Un worktree de `.claude/worktrees/<x>/` no es autosuficiente para esto: ni el `.venv` ni el
    dataset de la competencia (`vendor/ARC-AGI-3-Agents`, `environment_files`) se replican por rama
    -- pesan demasiado, y es lo mismo que GATE-ARC-ALCANZABILIDAD ya declara al usar el `.venv` del
    principal. Correr desde el worktree a ciegas da dos fallas distintas y las dos las vimos en los
    primeros intentos de este script: FileNotFoundError del interprete, y "[play_local] Falta el
    dataset de la competencia".

    Que ESTE experimento corra contra el checkout principal es correcto y no una concesion: mide la
    dispersion del INSTRUMENTO corriendo el MISMO codigo N veces. Lo unico que importa es que las N
    corridas sean sobre el mismo arbol, no cual arbol.
    """
    def sirve(p: Path) -> bool:
        return (p / ".venv" / "bin" / "python").exists() and (
            (p / "environment_files").exists() or (p / "vendor" / "ARC-AGI-3-Agents").exists()
        )

    if sirve(RAIZ):
        return RAIZ
    partes = RAIZ.parts
    if ".claude" in partes and "worktrees" in partes:
        principal = Path(*partes[: partes.index(".claude")]) / "projects" / RAIZ.name
        if sirve(principal):
            return principal
    return RAIZ  # no sirve, pero el fail-closed de una_corrida lo reporta con su motivo


def resolver_python(proyecto: Path) -> str:
    """El interprete del venv del proyecto resuelto."""
    p = proyecto / ".venv" / "bin" / "python"
    return str(p) if p.exists() else sys.executable


def tanda_de_semillas(i: int, por_corrida: int = 3) -> str:
    """Semillas DISTINTAS por corrida. El punto del experimento es variar solo la semilla."""
    base = i * por_corrida + 1
    return ",".join(f"res-{base + k}" for k in range(por_corrida))


def una_corrida(i: int, pasos: int, py: str, tmp: Path, proyecto: Path) -> dict:
    """Efecto: una corrida completa del gate. Devuelve lo medido, o el motivo de no haber podido."""
    destino = tmp / f"corrida-{i}.json"
    semillas = tanda_de_semillas(i)
    cmd = [
        py, str(proyecto / "scripts" / "gate_de_merge.py"),
        "--pasos", str(pasos),
        "--semillas", semillas,
        "--json", str(destino),
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(proyecto), capture_output=True, text=True, timeout=7200)
    dur = round(time.time() - t0, 1)

    if not destino.exists():
        # Fail-closed: sin el JSON no se sabe que paso. NO se asume 0 -- un cero por no poder medir
        # no es un cero medido (RFM-61), y aca ese error seria el mismo que el BL viene a cerrar.
        return {
            "corrida": i, "semillas": semillas, "duracionSeg": dur, "pudoMedir": False,
            "motivo": f"el gate no dejo JSON (exit={proc.returncode}): {proc.stderr[-400:]}",
        }

    doc = json.loads(destino.read_text(encoding="utf-8"))
    # La forma real del JSON de gate_de_merge.py (LEIDA, no supuesta): {config, costo, porSemilla,
    # totales:{accionesTotales, juegosConNivel, nivelesPorJuego, nivelesTotales}}. Un `.get` sobre
    # el nivel superior devuelve None sin avisar, y ese None se leeria como "no completo ningun
    # nivel" cuando en realidad es "busque la clave en el lugar equivocado" -- el mismo par de
    # estados indistinguibles que este BL viene a cerrar, un nivel mas abajo.
    totales = doc.get("totales") or {}
    total = totales.get("nivelesTotales")
    por_juego = totales.get("nivelesPorJuego") or {}
    if not isinstance(total, int):
        return {
            "corrida": i, "semillas": semillas, "duracionSeg": dur, "pudoMedir": False,
            "motivo": f"el JSON no trae totales.nivelesTotales entero (claves: {sorted(doc)} / {sorted(totales)})",
        }
    return {
        "corrida": i, "semillas": semillas, "duracionSeg": dur, "pudoMedir": True,
        "nivelesTotales": total,
        "accionesTotales": totales.get("accionesTotales"),
        "juegosConNivel": totales.get("juegosConNivel"),
        "nivelesPorJuego": {k: v for k, v in sorted(por_juego.items()) if v},
    }


def veredicto(totales: list[int]) -> dict:
    """PURA. Lo que la dispersion dice sobre el umbral del gate."""
    if len(totales) < 2:
        return {
            "concluyente": False,
            "texto": "INDETERMINADO: con menos de 2 corridas validas no hay dispersion que medir. "
                     "No se puede afirmar ni que el gate mida ni que no mida.",
        }
    rango = max(totales) - min(totales)
    desvio = round(statistics.pstdev(totales), 3)
    if rango >= 1:
        texto = (
            f"EL UMBRAL ES RUIDO: el MISMO codigo, corrido {len(totales)} veces cambiando solo la "
            f"semilla, dio entre {min(totales)} y {max(totales)} niveles (rango {rango}, sigma {desvio}). "
            f"El gate exige delta>0 para aceptar un cambio, y su propio instrumento se mueve {rango} "
            f"nivel(es) sin que NADA cambie: un delta=+1 es indistinguible de una corrida afortunada, "
            f"y un delta=0 de una mejora real que el instrumento no ve. Con esta resolucion el veto "
            f"delta<=0 rechaza mejoras legitimas y acepta ruido."
        )
    else:
        texto = (
            f"EL UMBRAL SOBREVIVE: {len(totales)} corridas del MISMO codigo dieron siempre "
            f"{totales[0]} niveles (rango 0, sigma {desvio}). La metrica es estable ante la semilla, "
            f"asi que un delta=+1 SI es señal. Eso NO explica el desglose identico de BL.22236 -- si "
            f"el instrumento no tiene ruido, entonces el problema es de RESOLUCION: es demasiado "
            f"grueso para ver mejoras que no completan un nivel nuevo, y sigue haciendo falta una "
            f"metrica densa."
        )
    return {
        "concluyente": True, "rango": rango, "sigma": desvio,
        "min": min(totales), "max": max(totales), "texto": texto,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corridas", type=int, default=5)
    ap.add_argument("--pasos", type=int, default=200)
    ap.add_argument("--python", default=None, help="Interprete; por defecto el venv resuelto (ver resolver_python).")
    ap.add_argument("--salida", default=str(RAIZ / "runtime_reports" / "resolucion_del_gate.json"))
    args = ap.parse_args()
    proyecto = resolver_proyecto()
    py = args.python or resolver_python(proyecto)

    tmp = proyecto / "runtime_reports" / "resolucion"
    tmp.mkdir(parents=True, exist_ok=True)

    print(f"[resolucion-gate] {args.corridas} corrida(s) del MISMO codigo, {args.pasos} pasos, semillas distintas.")
    print(f"[resolucion-gate] proyecto: {proyecto}")
    print(f"[resolucion-gate] interprete: {py}")
    print("[resolucion-gate] cada corrida son 25 juegos: esperar decenas de minutos por corrida.\n", flush=True)

    resultados = []
    for i in range(args.corridas):
        r = una_corrida(i, args.pasos, py, tmp, proyecto)
        resultados.append(r)
        if r["pudoMedir"]:
            print(f"[resolucion-gate] corrida {i}: {r['nivelesTotales']} niveles "
                  f"({r['semillas']}, {r['duracionSeg']}s)", flush=True)
        else:
            print(f"[resolucion-gate] corrida {i}: NO PUDO MEDIR — {r['motivo']}", flush=True)

    validas = [r["nivelesTotales"] for r in resultados if r["pudoMedir"] and isinstance(r["nivelesTotales"], int)]
    v = veredicto(validas)

    doc = {
        "_doc": "BL.22395 — resolucion del gate de merge: dispersion de nivelesTotales corriendo el "
                "MISMO codigo con semillas distintas. Re-ejecutable: mismo comando, mismo experimento.",
        "proyecto": str(proyecto),
        "interprete": py,
        "pasos": args.pasos,
        "corridasPedidas": args.corridas,
        "corridasValidas": len(validas),
        "totales": validas,
        "veredicto": v,
        "corridas": resultados,
    }
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(args.salida).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n[resolucion-gate] {v['texto']}")
    print(f"[resolucion-gate] escrito en {args.salida}")
    # 0 = pudo concluir. 2 = no pudo medir lo suficiente. NUNCA se devuelve 0 sin veredicto.
    return 0 if v["concluyente"] else 2


if __name__ == "__main__":
    sys.exit(main())
