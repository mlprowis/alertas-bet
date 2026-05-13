#!/usr/bin/env python3
"""
Script de prueba para diagnosticar la conexión a FlashScore API
Ejecuta esto en Railway para ver qué está retornando la API
"""

import requests
import json
import os

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "flashscore4.p.rapidapi.com"

print("=" * 60)
print("🧪 TEST DE FLASHSCORE API - DIAGNÓSTICO")
print("=" * 60)

if not RAPIDAPI_KEY:
    print("❌ RAPIDAPI_KEY no está configurado")
    exit(1)

print(f"✓ RAPIDAPI_KEY: {RAPIDAPI_KEY[:20]}...***")
print(f"✓ RAPIDAPI_HOST: {RAPIDAPI_HOST}")

headers = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST
}

print("\n" + "=" * 60)
print("Probando endpoints de FlashScore...")
print("=" * 60)

# Lista de endpoints posibles para FlashScore
endpoints = [
    "/api/flashscore/v2/matches/live",
    "/api/flashscore/v2/matches",
    "/api/flashscore/v2/fixtures/live",
    "/api/flashscore/matches/live",
]

for endpoint in endpoints:
    url = f"https://{RAPIDAPI_HOST}{endpoint}"
    print(f"\n🔍 GET {url}")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"   Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            # Analizar estructura
            if isinstance(data, dict):
                print(f"   Tipo: dict")
                print(f"   Keys: {list(data.keys())}")

                # Buscar array de matches
                if "data" in data:
                    print(f"   data[tipo]: {type(data['data'])}")
                    if isinstance(data['data'], list):
                        print(f"   data[length]: {len(data['data'])}")
                        if data['data']:
                            print(f"   data[0][keys]: {list(data['data'][0].keys())}")
                            print(f"   data[0]: {json.dumps(data['data'][0], indent=6)[:300]}...")

                # Mostrar primeros 300 caracteres
                print(f"   Respuesta (primeros 300 chars):\n   {json.dumps(data, indent=2)[:300]}...")

            elif isinstance(data, list):
                print(f"   Tipo: list")
                print(f"   Length: {len(data)}")
                if data:
                    print(f"   [0][keys]: {list(data[0].keys()) if isinstance(data[0], dict) else type(data[0])}")
                    print(f"   [0]: {json.dumps(data[0], indent=6)[:300]}...")

            print(f"   ✅ ENDPOINT FUNCIONA")
            break

        elif response.status_code == 403:
            print(f"   ❌ Acceso prohibido (verifica la API key)")
            print(f"   Response: {response.text[:200]}")
        elif response.status_code == 404:
            print(f"   ❌ Endpoint no encontrado")
        else:
            print(f"   ❌ Error: {response.text[:200]}")

    except requests.exceptions.Timeout:
        print(f"   ⏱️ Timeout (15s)")
    except Exception as e:
        print(f"   💥 Error: {str(e)[:150]}")

print("\n" + "=" * 60)
print("🧪 TEST COMPLETADO")
print("=" * 60)
