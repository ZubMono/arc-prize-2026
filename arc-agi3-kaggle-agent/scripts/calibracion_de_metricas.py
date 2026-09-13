#!/usr/bin/env python3
"""calibracion_de_metricas.py — BL.22856. EL CRITERIO DE ADMISION de una metrica densa, medido.

Una metrica candidata ENTRA solo si DISTINGUE dos versiones conocidamente distintas. El par de
calibracion es el que BL.22395 dejo servido: baseline (b1dbfed1c7~1) vs BL.22236 (b1dbfed1c7) son
INDISTINGUIBLES para el instrumento actual —mismo total de niveles y mismo desglose juego por
juego en los 25— y sin embargo BL.22236 cambia comportamiento probado por tests unitarios. Si una
candidata tampoco los separa, NO SIRVE, y este script lo dice con esas palabras en vez de
adoptarla igual.

COMO SEPARA señal de ruido, con N chico y sin teoria prestada: por RANGOS. Una metrica separa el
par si el rango de sus valores en un lado NO SE SOLAPA con el del otro. Es la misma vara que
BL.22395 le aplico a los niveles (rango 4 sobre 5 corridas identicas = delta +1 es ruido), ahora
aplicada a cada candidata. La banda de ruido de cada lado se publica JUNTO al veredicto: una densa
con banda gigante repite el problema con otra cara.

DISEÑO EMPAREJADO: la corrida i de los DOS lados usa la MISMA tanda de semillas (cal<i>-1..3), asi
que el delta emparejado descuenta la parte del ruido que viene de la semilla. Los lados se corren
ALTERNADOS (base-0, cand-0, base-1, ...) para que la deriva de carga del host no se cargue toda a
un lado.

EL INSTRUMENTO ES EL MISMO EN LOS DOS LADOS, por construccion: los arboles de cada ref se extraen
con `git archive` y encima se copian `gate_de_merge.py` + `metricas_densas.py` DE ESTE checkout.
Lo unico que difiere entre lados es el agente. `.venv`, `environment_files` y `vendor` se toman
del checkout principal por symlink — la misma resolucion (y por la misma razon) que
`resolucion_del_gate.resolver_proyecto`.

CONTROLES:
  negativo  nivelesTotales viaja en el mismo analisis y se ESPERA que no separe (el par se eligio
            por eso). Si separa, la premisa no se reprodujo en estas corridas y el veredicto de
            las densas queda bajo sospecha — se dice, no se esconde.
  positivo  del analizador: exige >=2 corridas por lado y partidasMedidas identicas en todas; con
            menos, "no pude medir" (exit 2), nunca un veredicto.

LO QUE NO SE MIDIO, con su motivo (el BL exige las descartadas declaradas): la tasa de acierto de
las hipotesis del world-model — 0 contadores expuestos en agent/my_agent.py (grep 2026-08-27);
exponer uno es tocar el agente. Queda en el JSON bajo `descartadasSinMedir`.

Uso:
    # correr la calibracion completa (6 corridas de gate ≈ 4-5 h de reloj con carga tipica):
    python3 scripts/calibracion_de_metricas.py --correr \
        --base b1dbfed1c7~1 --candidato b1dbfed1c7 --corridas 3

    # re-analizar corridas ya hechas (barato, re-ejecutable):
    python3 scripts/calibracion_de_metricas.py --analizar \
        --dir-base runtime_reports/calibracion_densas/base \
        --dir-candidato runtime_reports/calibracion_densas/candidato

Stdlib pura. SOLO REPO."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metricas_densas import CLAVES_DENSAS_AGREGABLES  # noqa: E402
from resolucion_del_gate import resolver_proyecto, resolver_python  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
# Rutas RELATIVAS al proyecto. arc_agent/veredicto_de_merge.py entro el 2026-08-28: el gate de hoy
# lo importa, y un arbol viejo del par de calibracion no lo trae — sin copiarlo, el preflight del
# lado base muere con ModuleNotFoundError (medido en el relanzamiento de la calibracion BL.22856).
ARCHIVOS_DEL_INSTRUMENTO = (
    "scripts/gate_de_merge.py",
    "scripts/metricas_densas.py",
    "arc_agent/veredicto_de_merge.py",
)
#: La candidata que NO se pudo medir, declarada con su motivo (no borrada en silencio).
DESCARTADAS_SIN_MEDIR = [
    {
        "metrica": "tasaDeAciertoDeHipotesisDelWorldModel",
        "motivo": (
            "el agente no expone ningun contador de hipotesis (grep 2026-08-27 sobre "
            "agent/my_agent.py: 0 matches de self.aciertos/prediccion/hipotesis/hits); "
            "exponer uno es tocar el agente, que es lo que este instrumento promete no hacer"
        ),
    }
]


def _monorepo() -> Path:
    """La raiz del monorepo que contiene este proyecto (donde viven los refs de git)."""
    salida = subprocess.run(
        ["git", "-C", str(RAIZ), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=30,
    )
    if salida.returncode != 0:
        raise SystemExit(f"[calibracion] no hay repo git sobre {RAIZ}: {salida.stderr.strip()}")
    return Path(salida.stdout.strip())


def preparar_arbol(ref: str, destino: Path, monorepo: Path, principal: Path) -> None:
    """Efecto: deja en `destino` el proyecto tal como estaba en `ref`, con el instrumento de ESTE
    checkout encima y los recursos pesados (.venv, dataset, vendor) symlinkeados del principal."""
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar") as tmp:
        proc = subprocess.run(
            ["git", "-C", str(monorepo), "archive", ref, "--", "projects/arc-agi3-kaggle-agent"],
            stdout=tmp, stderr=subprocess.PIPE, timeout=300,
        )
        if proc.returncode != 0:
            raise SystemExit(f"[calibracion] git archive {ref} fallo: {proc.stderr.decode()[-400:]}")
        tmp.flush()
        with tarfile.open(tmp.name) as tar:
            for miembro in tar.getmembers():
                partes = Path(miembro.name).parts
                if len(partes) <= 2:
                    continue
                miembro.name = str(Path(*partes[2:]))
                tar.extract(miembro, destino)

    for archivo in ARCHIVOS_DEL_INSTRUMENTO:
        (destino / archivo).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RAIZ / archivo, destino / archivo)

    for recurso in (".venv", "environment_files", "vendor"):
        origen = principal / recurso
        enlace = destino / recurso
        if origen.exists() and not enlace.exists():
            enlace.symlink_to(origen)


def preflight(destino: Path, py: str) -> None:
    """Fail-fast ANTES de gastar CPU: el gate instrumentado tiene que poder importarse en el arbol
    del ref. Si el ref no exporta algo que el gate de hoy necesita, esto revienta en segundos y no
    a la hora de corrida."""
    proc = subprocess.run(
        [py, "-c", "import gate_de_merge"],
        cwd=str(destino / "scripts"), capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"[calibracion] preflight fallo en {destino.name}: el gate instrumentado no importa "
            f"sobre ese ref.\n{proc.stderr[-600:]}"
        )


def tanda_de_semillas(corrida: int, por_corrida: int = 3) -> str:
    """Semillas de la corrida i — IDENTICAS para los dos lados (diseño emparejado)."""
    return ",".join(f"cal{corrida}-{k}" for k in range(1, por_corrida + 1))


def una_corrida(destino: Path, py: str, semillas: str, pasos: int, salida_json: Path) -> dict:
    """Efecto: una corrida completa del gate instrumentado en `destino`. Fail-closed: sin JSON no
    hay medicion, y el motivo se devuelve en vez de un cero (RFM-61)."""
    cmd = [
        py, str(destino / "scripts" / "gate_de_merge.py"),
        "--pasos", str(pasos), "--semillas", semillas, "--json", str(salida_json),
    ]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(destino), capture_output=True, text=True, timeout=10800)
    dur = round(time.time() - t0, 1)
    if not salida_json.exists():
        return {"pudoMedir": False, "duracionSeg": dur,
                "motivo": f"el gate no dejo JSON (exit={proc.returncode}): {proc.stderr[-400:]}"}
    return {"pudoMedir": True, "duracionSeg": dur}


def leer_corridas(directorio: Path) -> list[dict]:
    """Los JSON de gate de un lado, ordenados por nombre para que el indice empareje."""
    corridas = []
    for ruta in sorted(directorio.glob("*.json")):
        doc = json.loads(ruta.read_text(encoding="utf-8"))
        totales = doc.get("totales") or {}
        densas = totales.get("densasTotales") or {}
        corridas.append({
            "archivo": ruta.name,
            "config": doc.get("config") or {},
            "nivelesTotales": totales.get("nivelesTotales"),
            "partidasMedidas": densas.get("partidasMedidas"),
            "framesSinGrilla": densas.get("framesSinGrilla"),
            "densas": {clave: densas.get(clave) for clave in CLAVES_DENSAS_AGREGABLES},
        })
    return corridas


def _veredicto_de_metrica(nombre: str, lado_a: list, lado_b: list) -> dict:
    """Rango, banda y separacion de UNA metrica. Separa = rangos disjuntos, la misma vara que
    BL.22395 le aplico a los niveles."""
    rango_a = (min(lado_a), max(lado_a))
    rango_b = (min(lado_b), max(lado_b))
    return {
        "metrica": nombre,
        "base": lado_a, "candidato": lado_b,
        "rangoBase": rango_a, "rangoCandidato": rango_b,
        "bandaDeRuidoBase": rango_a[1] - rango_a[0],
        "bandaDeRuidoCandidato": rango_b[1] - rango_b[0],
        "deltasEmparejados": [b - a for a, b in zip(lado_a, lado_b)],
        "separa": rango_a[1] < rango_b[0] or rango_b[1] < rango_a[0],
    }


def analizar(dir_base: Path, dir_candidato: Path) -> tuple[dict, int]:
    """El veredicto de admision. Devuelve (informe, exit_code). exit 2 = no se pudo medir —
    nunca un veredicto fabricado sobre datos insuficientes."""
    base, candidato = leer_corridas(dir_base), leer_corridas(dir_candidato)
    if len(base) < 2 or len(candidato) < 2:
        return ({"pudoAnalizar": False,
                 "motivo": f"hacen falta >=2 corridas por lado (base={len(base)}, "
                           f"candidato={len(candidato)})"}, 2)

    partidas = {c["partidasMedidas"] for c in base + candidato}
    if len(partidas) != 1 or None in partidas:
        return ({"pudoAnalizar": False,
                 "motivo": f"partidasMedidas no es identico en todas las corridas ({sorted(partidas, key=str)}): "
                           "un total sumado sobre menos partidas no es comparable"}, 2)

    pares = min(len(base), len(candidato))
    candidatas = [
        _veredicto_de_metrica(
            clave,
            [int(c["densas"][clave]) for c in base[:pares]],
            [int(c["densas"][clave]) for c in candidato[:pares]],
        )
        for clave in CLAVES_DENSAS_AGREGABLES
    ]
    control = _veredicto_de_metrica(
        "nivelesTotales",
        [int(c["nivelesTotales"]) for c in base[:pares]],
        [int(c["nivelesTotales"]) for c in candidato[:pares]],
    )

    admitidas = [c["metrica"] for c in candidatas if c["separa"]]
    informe = {
        "pudoAnalizar": True,
        "corridasPorLado": {"base": len(base), "candidato": len(candidato), "emparejadas": pares},
        "candidatas": candidatas,
        "admitidas": admitidas,
        "ningunaSepara": not admitidas,
        "controlNegativo": {
            **control,
            "esperado": "NO separar (el par se eligio porque el instrumento actual los ve identicos)",
            "premisaReproducida": not control["separa"],
        },
        "descartadasSinMedir": DESCARTADAS_SIN_MEDIR,
    }
    return informe, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--correr", action="store_true")
    parser.add_argument("--analizar", action="store_true")
    parser.add_argument("--base", default="b1dbfed1c7~1")
    parser.add_argument("--candidato", default="b1dbfed1c7")
    parser.add_argument("--corridas", type=int, default=3)
    parser.add_argument("--pasos", type=int, default=200)
    parser.add_argument("--dir-base", type=Path)
    parser.add_argument("--dir-candidato", type=Path)
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args()

    principal = resolver_proyecto()
    salida_raiz = args.salida or principal / "runtime_reports" / "calibracion_densas"

    if args.correr:
        monorepo = _monorepo()
        py = resolver_python(principal)
        arboles = {}
        with tempfile.TemporaryDirectory(prefix="calibracion-densas-") as tmp:
            for lado, ref in (("base", args.base), ("candidato", args.candidato)):
                destino = Path(tmp) / lado
                print(f"[calibracion] preparando arbol {lado} <- {ref}", flush=True)
                preparar_arbol(ref, destino, monorepo, principal)
                preflight(destino, py)
                arboles[lado] = destino
                (salida_raiz / lado).mkdir(parents=True, exist_ok=True)

            for i in range(args.corridas):
                semillas = tanda_de_semillas(i)
                for lado in ("base", "candidato"):
                    destino_json = salida_raiz / lado / f"corrida-{i}.json"
                    print(f"[calibracion] corrida {i} lado={lado} semillas={semillas}", flush=True)
                    resultado = una_corrida(arboles[lado], py, semillas, args.pasos, destino_json)
                    print(f"[calibracion]   -> {json.dumps(resultado)}", flush=True)
                    if not resultado["pudoMedir"]:
                        print("[calibracion] corrida fallida: se corta ANTES de gastar mas CPU "
                              "sobre un instrumento roto.", flush=True)
                        return 2

    if args.correr or args.analizar:
        dir_base = args.dir_base or salida_raiz / "base"
        dir_candidato = args.dir_candidato or salida_raiz / "candidato"
        informe, codigo = analizar(dir_base, dir_candidato)
        destino = salida_raiz / "veredicto.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(informe, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(informe, indent=1, sort_keys=True))
        if informe.get("pudoAnalizar"):
            if informe["ningunaSepara"]:
                print("\nVEREDICTO: NINGUNA candidata separa el par conocido. No se adopta "
                      "ninguna: su verde no significaria nada.")
            else:
                print(f"\nVEREDICTO: separan {informe['admitidas']} — candidatas a reemplazar el "
                      "umbral del gate (eso es BL.22855, no este script).")
            if not informe["controlNegativo"]["premisaReproducida"]:
                print("AVISO: nivelesTotales SEPARO el par en estas corridas — la premisa de "
                      "BL.22395 no se reprodujo aca y el veredicto queda bajo sospecha.")
        return codigo

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
