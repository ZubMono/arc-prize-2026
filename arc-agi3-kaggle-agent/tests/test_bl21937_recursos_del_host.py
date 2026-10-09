"""BL.21937 — cuantos cores hay, cuantos se pueden usar, y contra cual se divide la carga.

QUE CUIDAN ESTOS TESTS. El defecto que cierra el BL no era un crash: era un numero CIERTO puesto al
lado de otro, que inducia a dividir por el divisor equivocado. Asi que lo que se afirma aca no es
"la funcion devuelve algo", sino las tres cosas que hacen que el reporte no se pueda malinterpretar:
el ratio se calcula contra los cores UTILES y no contra los totales, los tres numeros son
consistentes entre si, y el texto nombra los dos cuando hay reserva.

El caso que mas importa —`ratio se calcula contra los UTILES`— es exactamente el que se ponia en
verde con el codigo viejo, porque el codigo viejo ni siquiera calculaba un ratio: lo dejaba para
que lo hiciera quien leyera.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from recursos_del_host import cores, metricas_de_carga, texto_de_cores  # noqa: E402


def test_los_tres_numeros_son_consistentes_entre_si() -> None:
    c = cores()
    assert c["utiles"] >= 1, "siempre hay al menos un core utilizable"
    assert c["totales"] >= c["utiles"], "no puede haber mas utiles que totales"
    assert c["reservados"] == c["totales"] - c["utiles"], "los reservados son la diferencia, no un dato aparte"
    assert c["reservados"] >= 0


def test_los_utiles_salen_de_la_affinity_y_NO_de_cpu_count() -> None:
    """La distincion es el BL entero: `os.cpu_count()` son los del host, la affinity los de ESTE
    proceso. En un host con cores reservados por cpuset, confundirlos es el defecto."""
    c = cores()
    assert c["totales"] == (os.cpu_count() or 1)
    if hasattr(os, "sched_getaffinity"):
        assert c["utiles"] == len(os.sched_getaffinity(0))


def test_el_RATIO_se_divide_por_los_UTILES_no_por_los_TOTALES(monkeypatch: pytest.MonkeyPatch) -> None:
    """EL CASO QUE ORIGINA EL BL. Con 6 utiles de 8 y load1 7.69, el ratio real es 1.28; dividir por
    los 8 totales da 0.96 y hace concluir que el box esta holgado cuando no lo esta."""
    monkeypatch.setattr("recursos_del_host.os.getloadavg", lambda: (7.69, 0.0, 0.0))
    monkeypatch.setattr("recursos_del_host.os.cpu_count", lambda: 8)
    monkeypatch.setattr("recursos_del_host.os.sched_getaffinity", lambda _pid: set(range(6)))

    m = metricas_de_carga()
    assert m["coresUtiles"] == 6
    assert m["coresTotales"] == 8
    assert m["coresReservados"] == 2
    assert m["cargaAlMedir"] == 7.69
    assert m["ratioDeCargaAlMedir"] == 1.28, "1.28 es 7.69/6; 0.96 seria 7.69/8 y es la lectura equivocada"


def test_el_texto_nombra_los_dos_numeros_cuando_hay_reserva(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("recursos_del_host.os.cpu_count", lambda: 8)
    monkeypatch.setattr("recursos_del_host.os.sched_getaffinity", lambda _pid: set(range(6)))
    t = texto_de_cores()
    assert "6 cores utiles" in t
    assert "8 totales" in t
    assert "2 reservados" in t


def test_sin_reserva_el_texto_no_inventa_un_desglose(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un box sin cpuset no tiene cores reservados: decir '(0 reservados)' seria ruido que sugiere
    que hay una politica de reserva donde no la hay."""
    monkeypatch.setattr("recursos_del_host.os.cpu_count", lambda: 4)
    monkeypatch.setattr("recursos_del_host.os.sched_getaffinity", lambda _pid: set(range(4)))
    t = texto_de_cores()
    assert t == "4 cores utiles"
    assert "totales" not in t


def test_sin_sched_getaffinity_NO_se_afirma_reserva(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-safe de portabilidad: fuera de Linux no hay affinity. Lo honesto es no afirmar que hay
    cores reservados, no inventar una reserva de cero informacion."""
    monkeypatch.setattr("recursos_del_host.os.cpu_count", lambda: 8)
    monkeypatch.delattr("recursos_del_host.os.sched_getaffinity", raising=False)
    c = cores()
    assert c["utiles"] == 8
    assert c["reservados"] == 0


def test_una_affinity_mayor_que_los_totales_se_acota(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensivo: si las dos lecturas se contradijeran, `utiles` nunca puede superar a `totales`
    porque eso produciria `reservados` negativo y un ratio menor que el real."""
    monkeypatch.setattr("recursos_del_host.os.cpu_count", lambda: 4)
    monkeypatch.setattr("recursos_del_host.os.sched_getaffinity", lambda _pid: set(range(16)))
    c = cores()
    assert c["utiles"] == 4
    assert c["reservados"] == 0


def test_coincide_con_la_SSOT_del_repo() -> None:
    """LA AFIRMACION QUE VUELVE HONESTO AL DOCSTRING. El modulo dice que lee la MISMA fuente del SO
    que `scripts/lib/host-capacity.cjs`; esto lo COMPRUEBA en vez de prometerlo. Se saltea si no hay
    node o si el repo no esta al alcance (el paquete tiene que poder testearse aislado)."""
    ssot = Path(__file__).resolve().parents[3] / "scripts" / "lib" / "host-capacity.cjs"
    if not ssot.exists():
        pytest.skip("SSOT del repo no alcanzable desde este checkout")
    try:
        salida = subprocess.run(
            [
                "node",
                "-e",
                f"const h=require({str(ssot)!r});"
                "process.stdout.write(JSON.stringify({utiles:h.getWorkerCores(),"
                "totales:h.getTotalCores(),reservados:h.getSshReservedCores()}));",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("node no disponible")
    if salida.returncode != 0 or not salida.stdout.strip():
        pytest.skip(f"la SSOT no respondio: {salida.stderr[-200:]}")

    import json

    esperado = json.loads(salida.stdout)
    assert cores() == esperado, "si esto se rompe, una de las dos lecturas dejo de ser la misma fuente"
