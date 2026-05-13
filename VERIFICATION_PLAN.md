# Plan de Verificación - FlashScore Integration + Railway Deployment

## 📊 Estado Actual
- ✅ Código de integración de FlashScore completado
- ✅ Sintaxis Python verificada (railway_main.py)
- ✅ Lógica de FlashScore como primario + RapidAPI como fallback
- ⏳ Esperando verificación en Railway deployment

## 🎯 Cambios Realizados

### 1. **FlashScoreAPI Class** (líneas 370-492)
```
- BASE_URL: https://flashscore4.p.rapidapi.com
- HEADERS: X-RapidAPI-Key + X-RapidAPI-Host
- obtener_partidos_en_vivo(): Intenta 4 endpoints
- procesar_partido_real(): Convierte formato FlashScore → AlertasBet
```

### 2. **Jerarquía de Datos (Sin Simulados)**
```
procesar_partidos_en_vivo():
├─ FlashScore API (primario)
│  ├─ /api/flashscore/v2/matches/live
│  ├─ /api/flashscore/v2/matches
│  ├─ /api/flashscore/v2/fixtures/live
│  └─ /api/flashscore/matches/live
└─ RapidAPI (fallback si FlashScore vacío)
   ├─ /matches
   ├─ /matches?live=true
   ├─ /fixtures
   └─ /live
```

### 3. **Endpoints Flask Actualizados**
- `POST /webhook/best-match` (líneas 888-994): Busca mejor partido REAL ahora
- `POST /webhook/test` (líneas 803-886): Test del sistema
- `GET /webhook/diagnose` (líneas 1035-1122): Diagnosticar RapidAPI

### 4. **Scheduler**
- ✅ Inicializa FlashScoreAPI
- ✅ Inicializa LiveFootballAPI  
- ✅ Ejecuta `procesar_partidos_en_vivo()` cada 5 minutos
- ✅ Log: "SOLO datos REALES - Sin simulaciones"

## 🔍 Cómo Verificar

### Opción 1: Test Manual en Railway (Recomendado)

#### Paso 1: Encontrar URL de Railway
1. Ir a https://railway.app
2. Ir a tu proyecto "alertas-bet"
3. Hacer click en "Deployments"
4. Ver el dominio en "Live URL" o "Railway Link"

Ejemplo: `https://alertas-bet-abc123.up.railway.app`

#### Paso 2: Test Health Check
```bash
curl https://YOUR_RAILWAY_URL/
# Debe retornar: {"status": "healthy", ...}
```

#### Paso 3: Test /webhook/best-match (CRITICAL)
```bash
curl https://YOUR_RAILWAY_URL/webhook/best-match
```

**Esperado si hay partidos EN VIVO:**
```json
{
  "status": "ok",
  "message": "Mejor partido enviado a Telegram",
  "match": "Barcelona vs Real Madrid",
  "league": "La Liga",
  "score": "1-0",
  "minute": 35,
  "value": 12.5,
  "recommendation": "Over 1.0 Asiático ⭐⭐"
}
```

**Esperado si NO hay partidos (normal en horario bajo):**
```json
{
  "status": "low_value",
  "message": "No hay partidos con value >= 5.0 en vivo ahora",
  "best_value": null,
  "matches_analyzed": 0
}
```

#### Paso 4: Test /webhook/diagnose (Diagnosticar API)
```bash
curl https://YOUR_RAILWAY_URL/webhook/diagnose
```

Esto mostrará:
- Estado de RAPIDAPI_KEY
- Cuáles endpoints de RapidAPI responden
- Estructura de datos

#### Paso 5: Verificar Telegram
- Si hay partidos EN VIVO con value >= 5.0, deberías recibir alerta en Telegram
- Formato HTML con análisis completo

### Opción 2: Script de Diagnóstico Automatizado

```bash
# En Railway console, ejecutar:
python3 test_flashscore.py
# o
python3 test_rapidapi.py
```

Esto hará:
- ✅ Verificar RAPIDAPI_KEY está configurada
- ✅ Probar todos los endpoints
- ✅ Mostrar estructura de datos
- ✅ Identificar cuál endpoint funciona

### Opción 3: Ver Logs de Railway

1. Ir a https://railway.app → tu proyecto
2. Click en "alertasbetapi" (o tu servicio)
3. Ver Logs
4. Buscar:
   - "✓ FlashScore" = Funciona FlashScore
   - "✓ RapidAPI" = Funciona RapidAPI
   - "SOLO datos REALES" = Confirmación sin simulados
   - "Error" = Problemas de conexión

## 🧪 Escenarios Esperados

### Escenario 1: TODO FUNCIONA ✅
```
Logs:
🏆 Buscando el MEJOR partido EN VIVO REAL ahora...
✓ FlashScore (endpoint): N partidos en vivo
📊 Procesando N partidos en vivo...
🔔 MEJOR PARTIDO: Barcelona vs Real Madrid (Value: 12.5%)
✓ Mejor partido enviado a Telegram
```

### Escenario 2: FlashScore vacío, RapidAPI funciona
```
Logs:
🏆 Buscando el MEJOR partido EN VIVO REAL ahora...
⚠️ FlashScore sin partidos, intentando RapidAPI...
✓ RapidAPI (/matches): N partidos en vivo
📊 Procesando N partidos en vivo...
```

### Escenario 3: Sin partidos en vivo (normal en horario bajo)
```
Logs:
🏆 Buscando el MEJOR partido EN VIVO REAL ahora...
⚠️ FlashScore: Sin partidos
⚠️ RapidAPI (/matches): Sin partidos en vivo
⚠️ No hay partidos EN VIVO REALES en este momento
```

### Escenario 4: ERROR - RAPIDAPI_KEY no configurada
```
Logs:
⚠️ RapidAPI Key no configurado
❌ RAPIDAPI_KEY no está configurado
```

**Solución:**
1. Ir a Railway → alertasbetapi → Variables
2. Verificar que RAPIDAPI_KEY está definida
3. Redeploy

### Escenario 5: ERROR - Timeout en APIs
```
Logs:
⏱️ Timeout (10s) en FlashScore
⏱️ Timeout (10s) en RapidAPI
```

**Solución:** Esperar e intentar de nuevo, o verificar que Railway tiene acceso a internet

## 📋 Checklist de Verificación

- [ ] Railway URL encontrada y accesible
- [ ] `GET /` retorna status: "healthy"
- [ ] `GET /webhook/diagnose` retorna endpoints probados
- [ ] `GET /webhook/best-match` retorna partidos (o "no_matches" si es horario bajo)
- [ ] Logs muestran "FlashScore" o "RapidAPI" (no "simulados")
- [ ] Si hay alerta, Telegram recibe mensaje HTML formateado
- [ ] Scheduler corre cada 5 minutos (ver logs)

## ⚠️ Posibles Problemas y Soluciones

| Problema | Solución |
|----------|----------|
| `403 Forbidden` en diagnóstico | Verificar RAPIDAPI_KEY es válida |
| `404` en endpoints | Verificar Procfile usa railway_main:app |
| Timeout | Esperar, o verificar conexión a internet |
| No se reciben alertas Telegram | Verificar TELEGRAM_TOKEN y TELEGRAM_CHAT_ID |
| "Sin partidos" todo el tiempo | Normal si es horario bajo, esperar a partidos en vivo |

## 🚀 Próximos Pasos

1. **AHORA**: Ir a Railway y verificar URL + ejecutar `/webhook/diagnose`
2. **Después**: Ir a `/webhook/best-match` y revisar respuesta
3. **Si hay partidos**: Esperar a recibir alerta Telegram
4. **Si hay error**: Revisar logs de Railway para diagnosticar

## 📞 Soporte

Si hay problemas:
1. Revisar logs de Railway (ícono de "Logs" en el servicio)
2. Ejecutar `/webhook/diagnose` para ver detalles
3. Verificar variables de entorno en Railway

---

**Última actualización:** 2026-05-13
**Estado:** FlashScore Integration + Ready for Testing
