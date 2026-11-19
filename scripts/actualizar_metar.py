#!/usr/bin/env python3
"""Publica un resumen geográfico de los METAR actuales del Aviation Weather Center.

El cache XML oficial evita CORS desde GitHub Pages, los límites por bbox
y pedir un recurso por estación. No modifica datos históricos ni pronósticos.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

URL = "https://aviationweather.gov/data/cache/metars.cache.xml.gz"
DESTINO = Path(__file__).resolve().parents[1] / "data" / "metar_latest.json"
MAX_BYTES_GZIP = 16 * 1024 * 1024
MAX_BYTES_XML = 100 * 1024 * 1024
GEOREF_URL = "https://apis.datos.gob.ar/georef/api/v2.0/provincias.geojson"
PROVINCIAS = DESTINO.parent / "provincias.geojson"

# Estaciones publicadas en la AIP/catálogo oficial que deben permanecer en el mapa
# aunque AWC no tenga un METAR en su instantánea actual.
# Fuente SADJ: Ministerio de Transporte, registro de aeródromos.
ESTACIONES_PERMANENTES = {
    "SADJ": {"icao": "SADJ", "name": "Mariano Moreno / VII Brigada Aérea",
             "lat": -34.560000, "lon": -58.78972222},
}
FRESCURA_MAXIMA_SEGUNDOS = 3 * 3600
OBSERVACIONES_MINIMAS_RECIENTES = 20
ESPERAS_DESCARGA = (0, 4, 12, 24)



def numero(valor):
    if valor is None:
        return None
    try:
        n = float(str(valor).strip().replace("+", ""))
        return n if n == n and abs(n) != float("inf") else None
    except (ValueError, TypeError):
        return None


def valor(elemento, nombre):
    nodo = elemento.find(nombre)
    return nodo.text.strip() if nodo is not None and nodo.text else ""


def techo_metra(elemento, texto):
    capas = []
    hay_nubes = False
    techo_sin_altura = False
    for capa in elemento.findall("sky_condition"):
        cobertura = capa.attrib.get("sky_cover", "").upper()
        if cobertura:
            hay_nubes = True
        if cobertura in ("BKN", "OVC", "OVX"):
            alto = numero(capa.attrib.get("cloud_base_ft_agl"))
            if alto is not None:
                capas.append(alto)
            else:
                techo_sin_altura = True
    vv = numero(valor(elemento, "vert_vis_ft"))
    if vv is not None:
        capas.append(vv)
    # Respaldo para nubes presentes en el código pero ausentes en el XML parseado.
    for match in re.finditer(r"\b(?:BKN|OVC|VV)(\d{3})\b", texto.upper()):
        capas.append(int(match.group(1)) * 100)
    if capas:
        return min(capas)
    if techo_sin_altura or re.search(r"\b(?:BKN|OVC|VV)///\b", texto.upper()):
        return None
    # No atribuir cielo despejado si el reporte no informa nubosidad.
    if hay_nubes or re.search(r"\b(?:CAVOK|NSC|NCD|SKC|CLR|FEW\d{3}|SCT\d{3})\b", texto.upper()):
        return 99999.0
    return None


def clasificar(visibilidad_m, techo_pies, texto):
    # Cierre explícito. Nevar (SN) por sí solo NO significa pista cerrada.
    if re.search(r"\b(?:SNOCLO|CLSD|CLOSED)\b", texto.upper()):
        return "negro"
    if visibilidad_m is None or techo_pies is None:
        return "gris"
    if visibilidad_m >= 8000 and techo_pies >= 2500:
        return "azul"
    if visibilidad_m >= 5000 and techo_pies >= 1500:
        return "blanco"
    if visibilidad_m >= 3700 and techo_pies >= 700:
        return "verde"
    if visibilidad_m >= 1600 and techo_pies >= 300:
        return "amarillo"
    if visibilidad_m >= 800 and techo_pies >= 200:
        return "ambar"
    return "rojo"


def procesar(metar):
    codigo = valor(metar, "station_id").upper()
    lat, lon = numero(valor(metar, "latitude")), numero(valor(metar, "longitude"))
    if not re.fullmatch(r"[A-Z]{4}", codigo) or lat is None or lon is None:
        return None
    if not (-85 <= lat <= -17 and -86 <= lon <= -20):
        return None
    raw = valor(metar, "raw_text")
    fecha = valor(metar, "observation_time")
    if not fecha or not raw:
        return None
    try:
        marca = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
        if marca.tzinfo is None:
            return None
    except ValueError:
        return None

    vis_millas = numero(valor(metar, "visibility_statute_mi"))
    vis_metros = round(vis_millas * 1609.344) if vis_millas is not None else None
    # Priorizar visibilidad métrica explícita para evitar que el redondeo
    # al convertir desde millas rebaje erróneamente 8000 m a 7998 m.
    tokens = raw.upper().split()
    vis_metrica = next((int(t) for t in tokens if re.fullmatch(r"\d{4}", t)), None)
    if vis_metrica is not None:
        vis_metros = 10000 if vis_metrica == 9999 else vis_metrica
    if re.search(r"\bCAVOK\b", raw):
        vis_metros = 10000
    techo = techo_metra(metar, raw)
    nombre = valor(metar, "station_name") or valor(metar, "name") or codigo

    return {
        "icao": codigo, "name": nombre[:100],
        "lat": lat, "lon": lon, "time": marca.isoformat().replace("+00:00", "Z"),
        "raw": raw[:400], "visibilityM": vis_metros,
        "ceilingFt": techo, "color": clasificar(vis_metros, techo, raw),
    }


def obtener_xml():
    """Descarga el cache oficial; reintenta errores HTTP y respuestas truncadas."""
    ultimo_error = None
    for intento, pausa in enumerate(ESPERAS_DESCARGA, start=1):
        if pausa:
            print(f"AWC: esperando {pausa} s antes del intento {intento}", flush=True)
            time.sleep(pausa)
        try:
            peticion = urllib.request.Request(URL, headers={
                "User-Agent": "VisualizadorMeteorologico/1.1 (https://github.com/mauricioNico/visualizadorMeteorologico)",
                "Accept": "application/gzip,application/octet-stream",
                "Cache-Control": "no-cache",
            })
            with urllib.request.urlopen(peticion, timeout=35) as respuesta:
                contenido = respuesta.read(MAX_BYTES_GZIP + 1)
            if len(contenido) > MAX_BYTES_GZIP:
                raise RuntimeError("El archivo comprimido excedió el tamaño permitido")
            if contenido[:2] == b"\x1f\x8b":
                contenido = gzip.decompress(contenido)
            if not contenido or len(contenido) > MAX_BYTES_XML:
                raise RuntimeError("XML vacío o demasiado grande")
            # La validación de estructura y antigüedad se efectúa en construir().
            ET.fromstring(contenido)
            print(f"AWC: descarga correcta en intento {intento}, bytes XML={len(contenido)}")
            return contenido
        except (OSError, ValueError, RuntimeError, ET.ParseError, EOFError) as exc:
            ultimo_error = exc
            print(f"AWC: intento {intento}/{len(ESPERAS_DESCARGA)} falló: {exc}", flush=True)
    raise RuntimeError(f"No fue posible descargar un cache METAR válido: {ultimo_error}")


def marcador_sin_reporte(estacion):
    """Sitúa la estación sin atribuirle METAR, visibilidad ni categoría aeronáutica."""
    return {
        "icao": estacion["icao"], "name": estacion.get("name") or estacion["icao"],
        "lat": estacion["lat"], "lon": estacion["lon"],
        "time": None, "raw": "", "visibilityM": None,
        "ceilingFt": None, "color": "gris", "stationOnly": True,
    }


def catalogo_anterior():
    """Conserva posiciones ya conocidas aunque una estación deje de informar."""
    try:
        historico = json.loads(DESTINO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    catalogo = {}
    for x in historico.get("stations", []):
        if not isinstance(x, dict):
            continue
        codigo = x.get("icao")
        lat, lon = numero(x.get("lat")), numero(x.get("lon"))
        if (not isinstance(codigo, str) or not re.fullmatch(r"[A-Z]{4}", codigo)
                or lat is None or lon is None or not (-85 <= lat <= -17 and -86 <= lon <= -20)):
            continue
        catalogo[codigo] = marcador_sin_reporte({
            "icao": codigo, "name": x.get("name") or codigo, "lat": lat, "lon": lon,
        })
    return catalogo


def construir(xml: bytes, ahora=None, catalogo=None):
    ahora = ahora or datetime.now(timezone.utc)
    raiz = ET.fromstring(xml)
    por_codigo = {}
    for nodo in raiz.iter("METAR"):
        registro = procesar(nodo)
        if registro:
            previo = por_codigo.get(registro["icao"])
            if previo is None or registro["time"] > previo["time"]:
                por_codigo[registro["icao"]] = registro
    if len(por_codigo) < 30:
        raise RuntimeError(
            f"Se encontraron solo {len(por_codigo)} METAR válidos; no se publica un cache incompleto."
        )
    actuales = sum(
        0 <= (ahora - datetime.fromisoformat(r["time"].replace("Z", "+00:00"))).total_seconds()
        <= FRESCURA_MAXIMA_SEGUNDOS for r in por_codigo.values()
    )
    if actuales < OBSERVACIONES_MINIMAS_RECIENTES:
        raise RuntimeError(
            f"AWC devolvió {actuales} METAR recientes de {len(por_codigo)}. "
            "La fuente parece desactualizada; se conserva la publicación anterior."
        )

    estaciones = dict(catalogo if catalogo is not None else catalogo_anterior())
    for codigo, fijo in ESTACIONES_PERMANENTES.items():
        estaciones[codigo] = marcador_sin_reporte(fijo)
    estaciones.update(por_codigo)  # Nunca reemplazar un METAR genuino por un marcador fijo.

    return {
        "source": "NOAA Aviation Weather Center - metars.cache.xml.gz",
        "generatedAt": ahora.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reportingStations": len(por_codigo),
        "recentObservations": actuales,
        "stations": sorted(estaciones.values(), key=lambda dato: dato["icao"]),
    }

def actualizar_provincias():
    """Publica la geometría provincial oficial; fallo no interrumpe los METAR."""
    if PROVINCIAS.exists():
        return
    try:
        req = urllib.request.Request(GEOREF_URL, headers={
            "User-Agent": "VisualizadorMeteorologico/1.0",
            "Accept": "application/geo+json,application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as respuesta:
            contenido = respuesta.read(16 * 1024 * 1024 + 1)
        if len(contenido) > 16 * 1024 * 1024:
            raise RuntimeError("Geometría provincial demasiado grande")
        geo = json.loads(contenido)
        if geo.get("type") != "FeatureCollection" or len(geo.get("features", [])) < 20:
            raise RuntimeError("Formato de provincias inesperado")
        PROVINCIAS.parent.mkdir(parents=True, exist_ok=True)
        temp = PROVINCIAS.with_suffix(".tmp")
        temp.write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        temp.replace(PROVINCIAS)
        print("Geometría provincial IGN/GeoRef almacenada")
    except Exception as exc:
        print(f"Aviso: no se pudo actualizar cartografía provincial: {exc}")


def main():
    documento = construir(obtener_xml())
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    temporal = DESTINO.with_suffix(".tmp")
    temporal.write_text(json.dumps(documento, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporal.replace(DESTINO)
    actualizar_provincias()
    print(f"Mapa: {len(documento['stations'])} estaciones; "
          f"{documento['reportingStations']} con METAR; "
          f"{documento['recentObservations']} recientes. "
          f"Generado {documento['generatedAt']}")


if __name__ == "__main__":
    main()
