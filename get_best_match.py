#!/usr/bin/env python3
"""
Script para obtener el MEJOR PARTIDO EN VIVO ahora mismo desde Railway
Ejecutar: python3 get_best_match.py
"""

import requests
import json
import time
import sys

print("="*60)
print("🏆 OBTENIENDO MEJOR PARTIDO EN VIVO AHORA")
print("="*60)
print()

# URLs posibles de Railway
possible_urls = [
    "https://alertas-bet-production.up.railway.app",
    "https://alertas-bet.up.railway.app",
    "https://alertas-bet-main.up.railway.app",
]

railway_url = None

# Primero, intentar health check
print("🔍 Buscando URL de Railway...")
for url in possible_urls:
    try:
        print(f"   Intentando: {url}")
        response = requests.get(f"{url}/", timeout=5)
        if response.status_code == 200:
            railway_url = url
            print(f"✅ Encontrado: {railway_url}\n")
            break
    except:
        pass

if not railway_url:
    print("❌ No se pudo encontrar Railway")
    print("\nALTERNATIVA: Ve a https://railway.app → alertas-bet → Deployments")
    print("Copia la URL y ejecuta:")
    print("  python3 get_best_match.py YOUR_URL")
    sys.exit(1)

# Si se proporciona URL como argumento
if len(sys.argv) > 1:
    railway_url = sys.argv[1]
    print(f"📌 Usando URL: {railway_url}\n")

# Obtener mejor partido
print("⏳ Esperando a que Railway esté completamente listo...")
time.sleep(3)

print("\n🎯 Buscando mejor partido EN VIVO...")
try:
    response = requests.get(f"{railway_url}/webhook/best-match", timeout=10)

    if response.status_code == 200:
        data = response.json()

        print("✅ RESPUESTA RECIBIDA\n")

        if data.get("status") == "ok":
            print("🎉 ¡PARTIDO ENCONTRADO!")
            print(f"   ⚽ Partido: {data.get('match')}")
            print(f"   📊 Liga: {data.get('league')}")
            print(f"   📈 Marcador: {data.get('score')}")
            print(f"   🕐 Minuto: {data.get('minute')}")
            print(f"   💰 VALUE: +{data.get('value'):.1f}%")
            print(f"   ✅ {data.get('recommendation')}")
            print(f"\n📱 REVISA TU TELEGRAM - La alerta ya fue enviada\n")

        elif data.get("status") == "low_value":
            print("⚠️  PARTIDOS SIN OPORTUNIDAD CLARA")
            print(f"   Mejor VALUE: {data.get('best_value', 'N/A'):.1f}% (threshold: 2.0%)")
            print(f"   Partidos analizados: {data.get('matches_analyzed')}\n")
            print("💡 El bot está funcionando pero no hay valor suficiente ahora\n")

        elif data.get("status") == "no_matches":
            print("ℹ️  SIN PARTIDOS EN VIVO EN ESTE MOMENTO")
            print(f"   {data.get('message')}\n")
            print("💡 Es normal en horario bajo - el bot seguirá buscando cada 5 minutos\n")

        # Mostrar JSON completo para debugging
        print("📊 RESPUESTA COMPLETA:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

    else:
        print(f"❌ Error: Status {response.status_code}")
        print(response.text)

except requests.exceptions.Timeout:
    print("❌ Timeout - Railway aún está deployando")
    print("⏳ Espera 5-10 minutos e intenta de nuevo\n")

except Exception as e:
    print(f"❌ Error: {e}\n")
    print("⏳ Railway podría estar deployando aún")
    print("   Espera 5-10 minutos e intenta de nuevo\n")

print("="*60)
