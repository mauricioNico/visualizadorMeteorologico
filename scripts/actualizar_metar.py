#!/usr/bin/env python3
"""Publica un resumen geográfico de los METAR actuales del Aviation Weather Center.

El cache XML oficial evita CORS desde GitHub Pages, los límites por bbox
y pedir un recurso por estación. No modifica datos históricos ni pronósticos.
"""
from __future__ import annotations

import gzip
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

URL = "https://aviationweather.gov/data/cache/metars.cache.xml.gz"
DESTINO = Path(__file__).resolve().parents[1] / "data" / "metar_latest.json"
MAX_BYTES_GZIP = 16 * 1024 * 1024
MAX_BYTES_XML = 100 * 1024 * 1024


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
    for capa in elemento.findall("sky_condition"):
        cobertura = capa.attrib.get("sky_cover", "").upper()
        if cobertura:
            hay_nubes = True
        if cobertura in ("BKN", "OVC", "OVX"):
            alto = numero(capa.attrib.get("cloud_base_ft_agl"))
            if alto is not None:
                capas.append(alto)
    vv = numero(valor(elemento, "vert_vis_ft"))
    if vv is not None:
        capas.append(vv)
    # Respaldo para nubes presentes en el código pero ausentes en el XML parseado.
    for match in re.finditer(r"\b(?:BKN|OVC|VV)(\d{3})\b", texto.upper()):
        capas.append(int(match.group(1)) * 100)
    if capas:
        return min(capas)
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
    if vis_metros is None and re.search(r"\bCAVOK\b", raw):
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
    peticion = urllib.request.Request(URL, headers={
        "User-Agent": "VisualizadorMeteorologico/1.0 (https://github.com/mauricioNico/visualizadorMeteorologico)",
        "Accept": "application/gzip,application/octet-stream",
    })
    with urllib.request.urlopen(peticion, timeout=50) as respuesta:
        contenido = respuesta.read(MAX_BYTES_GZIP + 1)
    if len(contenido) > MAX_BYTES_GZIP:
        raise RuntimeError("El archivo comprimido excedió el tamaño de seguridad.")
    if contenido[:2] == b"\x1f\x8b":
        contenido = gzip.decompress(contenido)
    if len(contenido) > MAX_BYTES_XML:
        raise RuntimeError("El XML excedió el tamaño de seguridad.")
    return contenido


def construir(xml: bytes):
    raiz = ET.fromstring(xml)
    por_codigo = {}
    for nodo in raiz.iter("METAR"):
        registro = procesar(nodo)
        if registro:
            previo = por_codigo.get(registro["icao"])
            if previo is None or registro["time"] > previo["time"]:
                por_codigo[registro["icao"]] = registro
    if len(por_codigo) < 30:
        raise RuntimeError(f"Se encontraron solo {len(por_codigo)} METAR válidos; no se publican datos incompletos.")
    return {
        "source": "NOAA Aviation Weather Center - metars.cache.xml.gz",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "stations": sorted(por_codigo.values(), key=lambda dato: dato["icao"]),
    }


def main():
    documento = construir(obtener_xml())
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    temporal = DESTINO.with_suffix(".tmp")
    temporal.write_text(json.dumps(documento, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporal.replace(DESTINO)
    print(f"Publicados {len(documento['stations'])} METAR. Generado {documento['generatedAt']}")


if __name__ == "__main__":
    main()
