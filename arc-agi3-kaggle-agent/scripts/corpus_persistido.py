"""[arc-agi3-kaggle-agent/scripts/corpus_persistido] BL.21728 -- lector UNICO del corpus de subidas
de nivel, con verificacion de procedencia.

POR QUE EXISTE (defecto MEDIDO, BL.21728 defecto 2). El informe de objetivos de BL.21695 leia
`runtime_reports/ventanas/`, el directorio donde el barrido va dejando los `.jsonl` a medida que
corre. El informe se ejecuto a las 18:36:50 y los JSONL de g50t se escribieron a las 18:41: el
informe publico "12 eventos = 7 transiciones sobre 5 juegos" mientras el corpus efectivamente
persistido en `arcReplayFrames` eran 14 eventos / 8 transiciones / 6 juegos. La muestra declarada
contradecia al corpus que el propio BL habia subido, y g50t -- uno de los tres juegos que sostenian
`pintarRegion` -- no estaba en la cuenta.

LA REGLA QUE IMPONE ESTE MODULO. El informe no lee capturas sueltas: lee un EXPORT del corpus
persistido, producido por `node scripts/exportar-ventanas-nivel-arc.cjs`, que deja dos archivos --
`ventanas.jsonl` y `manifiesto.json`. El manifiesto trae el sha256 del JSONL, el host y la base de
los que se leyo, la lista de corridas y la cuenta de documentos. Este lector:
  1. exige los DOS archivos (sin manifiesto no hay informe: fail-closed, no un aviso);
  2. verifica el sha256 -- un export a medias, editado a mano o concatenado con otra captura no
     pasa;
  3. verifica que las ventanas, los juegos y las transiciones distintas que trae el JSONL sean
     EXACTAMENTE las que declara el manifiesto.
  4. verifica el CENSO -- lo unico del manifiesto que NO se deriva del JSONL (correccion de
     BL.21728): las ventanas contra las subidas de nivel contadas DIRECTO sobre los documentos, las
     transiciones contra las del censo, y que no haya documentos con subida de nivel FUERA del
     filtro de runId;
  5. rechaza un export VIEJO (`MAX_ANTIGUEDAD_DEL_EXPORT`), que es la forma exacta que tomo el
     defecto: un directorio que quedo en disco mientras el barrido seguia escribiendo.

POR QUE NO ALCANZABA CON EL SHA256 (refutacion medida de este mismo BL). La cadena de hash ata el
INFORME al export, pero NUNCA el export a la coleccion: armando a mano un export sin las dos lineas
de g50t y recalculando el manifiesto como lo haria el exportador, el informe volvia a publicar
"12 eventos / 7 transiciones / 5 juegos" sin romper un solo hash y sin un solo error. El defecto
estaba cerrado solo para la manipulacion manual del JSONL -- la unica variante que nadie habia
hecho. El censo y la antiguedad cierran las otras dos (export a medias y export viejo).

Stdlib pura. SOLO REPO (vive en `scripts/`, no viaja al entregable de Kaggle)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

#: Nombres FIJOS que escribe el exportador. Fijos y no configurables a proposito: si el informe
#: aceptara "cualquier jsonl que le pases", volveria a existir el camino que produjo el defecto.
ARCHIVO_VENTANAS = "ventanas.jsonl"
ARCHIVO_MANIFIESTO = "manifiesto.json"

#: Antiguedad maxima de un export para que el informe lo acepte. El defecto de BL.21728 fue un
#: directorio intermedio de MINUTOS: el informe corrio a las 18:36:50 y los JSONL de g50t se
#: escribieron a las 18:41. Una hora es holgado para encadenar export + informe + experimentos en
#: una sesion, y corto frente a "el corpus crecio y este export ya no lo describe". Re-exportar
#: cuesta ~15s. Para reproducir una medicion vieja a proposito: `permitir_export_viejo=True`.
MAX_ANTIGUEDAD_DEL_EXPORT = timedelta(hours=1)

COMO_EXPORTAR = (
    "node scripts/exportar-ventanas-nivel-arc.cjs "
    "projects/arc-agi3-kaggle-agent/runtime_reports/corpus"
)


class CorpusInvalido(RuntimeError):
    """El export no existe, no esta completo o no coincide con su manifiesto.

    Es un error y no un aviso: seguir adelante con un corpus que no cierra es exactamente como se
    publico una muestra que contradecia al corpus persistido."""


@dataclass(frozen=True)
class Procedencia:
    """De donde salio este corpus. Va IMPRESA en el informe: un numero sin procedencia es lo que
    permitio que "12 eventos" y "14 eventos" convivieran sin que nadie lo notara."""

    origen: str
    host: str
    base_de_datos: str
    documentos_leidos: int
    documentos_con_nivel: int
    corridas: tuple[str, ...]
    juegos: tuple[str, ...]
    ventanas: int
    transiciones_distintas: tuple[str, ...]
    sha256: str
    exportado_en: str
    #: Regex de `runId` con el que el exportador selecciono los documentos. VA IMPRESO: el lector
    #: no puede saber, si no, que el 95% de la coleccion quedo afuera por una regla (correccion de
    #: BL.21728 -- la procedencia decia "277 documento(s)" de una coleccion de 5.817 sin decir por
    #: que).
    filtro_run_id: str = "?"
    #: Lo unico que NO se puede derivar del JSONL: ver `_verificar_censo`.
    censo: dict[str, Any] = field(default_factory=dict)

    def a_json(self) -> dict[str, Any]:
        return {
            "origen": self.origen,
            "host": self.host,
            "baseDeDatos": self.base_de_datos,
            "documentosLeidos": self.documentos_leidos,
            "documentosConNivel": self.documentos_con_nivel,
            "corridas": list(self.corridas),
            "juegos": list(self.juegos),
            "ventanas": self.ventanas,
            "transicionesDistintas": list(self.transiciones_distintas),
            "sha256": self.sha256,
            "exportadoEn": self.exportado_en,
            "filtroRunId": self.filtro_run_id,
            "censo": dict(self.censo),
        }


def _procedencia_de(crudo: dict[str, Any]) -> Procedencia:
    return Procedencia(
        origen=str(crudo.get("origen", "?")),
        host=str(crudo.get("host", "?")),
        base_de_datos=str(crudo.get("baseDeDatos", "?")),
        documentos_leidos=int(crudo.get("documentosLeidos", 0)),
        documentos_con_nivel=int(crudo.get("documentosConNivel", 0)),
        corridas=tuple(str(c) for c in crudo.get("corridas", ())),
        juegos=tuple(str(j) for j in crudo.get("juegos", ())),
        ventanas=int(crudo.get("ventanas", 0)),
        transiciones_distintas=tuple(str(t) for t in crudo.get("transicionesDistintas", ())),
        sha256=str(crudo.get("sha256", "")),
        exportado_en=str(crudo.get("exportadoEn", "?")),
        filtro_run_id=str(crudo.get("filtroRunId", "?")),
        censo=dict(crudo.get("censo") or {}),
    )


def etiqueta_de_transicion(ventana: dict[str, Any]) -> str:
    """Identidad de una transicion: (juego, nivel alcanzado). Misma forma que escribe el
    exportador, para que las dos listas se puedan comparar sin traducir nada."""
    return f"{ventana.get('juego', '?')}:nivel{ventana.get('nivelNuevo', 0)}"


def _verificar_censo(
    ventanas: list[dict[str, Any]], transiciones: tuple[str, ...], procedencia: Procedencia
) -> None:
    """EL EXPORT CONTRA LA COLECCION -- el chequeo que el sha256 no puede dar.

    El hash ata el informe al export; esto ata el export a lo que habia en `arcReplayFrames`. Son
    tres preguntas y las tres fallan CERRADO:
      1. las ventanas del JSONL contra las subidas de nivel contadas por el SEGUNDO camino del
         exportador (directo sobre los documentos, sin reconstruir ventanas);
      2. las transiciones distintas contra las del censo;
      3. si quedaron documentos con subida de nivel FUERA del filtro de runId, el corpus no es la
         muestra completa y el informe no puede decir "es lo persistido".
    Un manifiesto sin censo tambien falla: es un export anterior a esta correccion y no hay forma de
    saber si describe la coleccion."""
    censo = procedencia.censo
    if not censo:
        raise CorpusInvalido(
            "[corpus] el manifiesto no trae `censo`: es un export anterior a la correccion de "
            "BL.21728 y no hay con que verificar que describa la coleccion (el sha256 solo ata el "
            f"informe al export). Re-exportalo con:\n    {COMO_EXPORTAR}"
        )
    eventos = int(censo.get("eventosDeSubidaEnLosDocumentos", -1))
    if eventos != len(ventanas):
        raise CorpusInvalido(
            f"[corpus] el JSONL trae {len(ventanas)} ventana(s) y el censo de la coleccion cuenta "
            f"{eventos} subida(s) de nivel. El export esta incompleto o quedo viejo: es el defecto "
            f"2 de BL.21728 por otro camino. Re-exportalo con:\n    {COMO_EXPORTAR}"
        )
    del_censo = tuple(sorted(str(x) for x in censo.get("transicionesEnLosDocumentos", ())))
    if del_censo != transiciones:
        raise CorpusInvalido(
            f"[corpus] las transiciones del JSONL {list(transiciones)} no son las que el censo "
            f"conto sobre los documentos {list(del_censo)}."
        )
    fuera = int(censo.get("documentosConNivelFueraDelFiltro", 0))
    if fuera > 0:
        raise CorpusInvalido(
            f"[corpus] hay {fuera} documento(s) con levelsCompleted>0 FUERA del filtro "
            f"{procedencia.filtro_run_id}: el export no es la muestra completa y el informe no "
            "puede declararlo como 'lo persistido'. Ampliar el filtro del exportador y volver a "
            "correrlo."
        )


def _verificar_antiguedad(procedencia: Procedencia, permitir_export_viejo: bool) -> None:
    """UN EXPORT VIEJO ES EXACTAMENTE EL DEFECTO. El informe de BL.21695 corrio a las 18:36:50
    sobre un directorio que el barrido siguio llenando hasta las 18:41. El sha256 no ve esa clase
    de error -- el export es internamente consistente, solo que describe un pasado."""
    if permitir_export_viejo:
        return
    try:
        exportado = datetime.fromisoformat(procedencia.exportado_en.replace("Z", "+00:00"))
    except ValueError:
        raise CorpusInvalido(
            f"[corpus] el manifiesto no trae una fecha de export legible ({procedencia.exportado_en!r})."
        ) from None
    if exportado.tzinfo is None:
        exportado = exportado.replace(tzinfo=timezone.utc)
    antiguedad = datetime.now(timezone.utc) - exportado
    if antiguedad > MAX_ANTIGUEDAD_DEL_EXPORT:
        horas = antiguedad.total_seconds() / 3600.0
        raise CorpusInvalido(
            f"[corpus] el export es de hace {horas:.1f} h y el maximo es "
            f"{MAX_ANTIGUEDAD_DEL_EXPORT.total_seconds() / 3600.0:.0f} h. Un directorio que quedo "
            "en disco mientras el corpus seguia creciendo es la forma EXACTA del defecto 2 de "
            f"BL.21728 (el informe publico 12/7/5 leyendo uno de minutos antes). Re-exportalo:\n"
            f"    {COMO_EXPORTAR}\n"
            "Para reproducir a proposito una medicion vieja: leer_corpus(..., "
            "permitir_export_viejo=True) / --permitir-corpus-viejo."
        )


def leer_corpus(
    directorio: Path, permitir_export_viejo: bool = False
) -> tuple[list[dict[str, Any]], Procedencia]:
    """Ventanas del corpus persistido + su procedencia. Levanta `CorpusInvalido` ante cualquier
    desajuste: no hay modo degradado."""
    jsonl = directorio / ARCHIVO_VENTANAS
    manifiesto = directorio / ARCHIVO_MANIFIESTO
    faltantes = [p.name for p in (jsonl, manifiesto) if not p.is_file()]
    if faltantes:
        raise CorpusInvalido(
            f"[corpus] falta {', '.join(faltantes)} en {directorio}. El informe SOLO lee un export "
            f"del corpus persistido, nunca capturas sueltas. Generalo con:\n    {COMO_EXPORTAR}"
        )

    texto = jsonl.read_text(encoding="utf-8")
    crudo = json.loads(manifiesto.read_text(encoding="utf-8"))
    procedencia = _procedencia_de(crudo)

    calculado = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    if calculado != procedencia.sha256:
        raise CorpusInvalido(
            f"[corpus] el sha256 de {ARCHIVO_VENTANAS} ({calculado[:12]}...) no coincide con el "
            f"del manifiesto ({procedencia.sha256[:12]}...). El export esta a medias, editado a "
            f"mano o mezclado con otra captura. Re-exportalo con:\n    {COMO_EXPORTAR}"
        )

    ventanas = [json.loads(linea) for linea in texto.splitlines() if linea.strip()]
    if len(ventanas) != procedencia.ventanas:
        raise CorpusInvalido(
            f"[corpus] el JSONL trae {len(ventanas)} ventana(s) y el manifiesto declara "
            f"{procedencia.ventanas}."
        )

    juegos = tuple(sorted({str(v.get("juego", "?")) for v in ventanas}))
    if juegos != tuple(sorted(procedencia.juegos)):
        raise CorpusInvalido(
            f"[corpus] los juegos del JSONL {list(juegos)} no son los del manifiesto "
            f"{list(procedencia.juegos)}."
        )

    transiciones = tuple(sorted({etiqueta_de_transicion(v) for v in ventanas}))
    if transiciones != tuple(sorted(procedencia.transiciones_distintas)):
        raise CorpusInvalido(
            f"[corpus] las transiciones del JSONL {list(transiciones)} no son las del manifiesto "
            f"{list(procedencia.transiciones_distintas)}."
        )

    _verificar_censo(ventanas, transiciones, procedencia)
    _verificar_antiguedad(procedencia, permitir_export_viejo)
    return ventanas, procedencia


__all__ = [
    "ARCHIVO_MANIFIESTO",
    "MAX_ANTIGUEDAD_DEL_EXPORT",
    "ARCHIVO_VENTANAS",
    "COMO_EXPORTAR",
    "CorpusInvalido",
    "Procedencia",
    "etiqueta_de_transicion",
    "leer_corpus",
]
