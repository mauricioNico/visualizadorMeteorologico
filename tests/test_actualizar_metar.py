#!/usr/bin/env python3
"""Pruebas sin acceso a red: preservar estaciones sin inventar METAR y rechazar cache viejo."""
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import actualizar_metar as metar


class CacheMetarTests(unittest.TestCase):
    AHORA = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)

    def xml(self, fecha=None, incluir_sadj=False):
        fecha = fecha or self.AHORA - timedelta(minutes=30)
        iso = fecha.isoformat().replace("+00:00", "Z")
        nodes = []
        for i in range(35):
            codigo = "SA" + chr(65 + i // 26) + chr(65 + i % 26)
            nodes.append(
                f"<METAR><station_id>{codigo}</station_id>"
                "<latitude>-34.56</latitude><longitude>-58.4</longitude>"
                f"<observation_time>{iso}</observation_time>"
                f"<raw_text>METAR {codigo} 190730Z 00000KT CAVOK 20/15 Q1010</raw_text>"
                "</METAR>"
            )
        if incluir_sadj:
            nodes.append(
                "<METAR><station_id>SADJ</station_id>"
                "<latitude>-34.56</latitude><longitude>-58.78972222</longitude>"
                f"<observation_time>{iso}</observation_time>"
                "<raw_text>METAR SADJ 190730Z 08004KT CAVOK 20/15 Q1010</raw_text>"
                "</METAR>"
            )
        return ("<response>" + "".join(nodes) + "</response>").encode("utf-8")

    def test_incluye_sadj_sin_inventar_reporte(self):
        resultado = metar.construir(self.xml(), ahora=self.AHORA, catalogo={})
        sadj = next(x for x in resultado["stations"] if x["icao"] == "SADJ")
        self.assertEqual(sadj["color"], "gris")
        self.assertTrue(sadj["stationOnly"])
        self.assertIsNone(sadj["time"])
        self.assertEqual(sadj["raw"], "")
        self.assertEqual(resultado["reportingStations"], 35)
        self.assertEqual(resultado["recentObservations"], 35)

    def test_muestra_metar_real_de_sadj_si_existe(self):
        resultado = metar.construir(self.xml(incluir_sadj=True), ahora=self.AHORA, catalogo={})
        sadj = next(x for x in resultado["stations"] if x["icao"] == "SADJ")
        self.assertEqual(sadj["raw"].split()[0:2], ["METAR", "SADJ"])
        self.assertEqual(sadj["name"], "Mariano Moreno / VII Brigada Aérea")
        self.assertNotIn("stationOnly", sadj)
        self.assertEqual(resultado["reportingStations"], 36)

    def test_preserva_catalogo_de_ubicaciones(self):
        anterior = {"SAZZ": metar.marcador_sin_reporte({
            "icao": "SAZZ", "name": "Estación temporal",
            "lat": -35.0, "lon": -59.0,
        })}
        resultado = metar.construir(self.xml(), ahora=self.AHORA, catalogo=anterior)
        anterior_en_mapa = next(x for x in resultado["stations"] if x["icao"] == "SAZZ")
        self.assertTrue(anterior_en_mapa["stationOnly"])
        self.assertIsNone(anterior_en_mapa["time"])

    def test_rechaza_fuente_desactualizada(self):
        with self.assertRaisesRegex(RuntimeError, "desactualizada"):
            metar.construir(
                self.xml(fecha=self.AHORA - timedelta(hours=7)),
                ahora=self.AHORA, catalogo={}
            )


if __name__ == "__main__":
    unittest.main()
