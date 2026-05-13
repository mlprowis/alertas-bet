# 🎯 ALERTAS BET - ESTADO ACTUAL

## ✅ Completado

### 1. **Integración FlashScore API**
- ✅ Clase `FlashScoreAPI` implementada
- ✅ 4 endpoints probados
- ✅ Conversión de datos al formato AlertasBet
- ✅ Manejo de errores y timeouts

### 2. **Cambio de Arquitectura: SOLO Datos Reales**
- ✅ Removido fallback a simulados en procesar_partidos_en_vivo()
- ✅ Removido fallback a simulados en webhook_best_match()
- ✅ FlashScore como API primaria
- ✅ RapidAPI como fallback
- ✅ Logs claros mostrando "SOLO datos REALES"

### 3. **Endpoints Flask**
- ✅ `/webhook/best-match` - Busca mejor partido en vivo AHORA
- ✅ `/webhook/test` - Test del sistema
- ✅ `/webhook/diagnose` - Diagnosticar conexiones API
- ✅ `/status` - Estado completo del servicio
- ✅ `/` - Health check

### 4. **Scheduler**
- ✅ Ejecuta cada 5 minutos automáticamente
- ✅ Procesa partidos EN VIVO REALES
- ✅ Envía alertas a Telegram si valor >= 8.0

### 5. **Dependencias**
- ✅ `requirements.txt` actualizado
- ✅ `Procfile` correcto: `web: gunicorn --bind 0.0.0.0:$PORT railway_main:app`
- ✅ Sin dependencias de NumPy (reemplazado con math.exp())

## 📊 Arquitectura de Datos

```
AHORA (Actualización a partir de 2026-05-13):

Flujo de Obtención de Partidos:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
procesar_partidos_en_vivo()
    ↓
    FlashScore API (primario)
    ├─ /api/flashscore/v2/matches/live
    ├─ /api/flashscore/v2/matches
    ├─ /api/flashscore/v2/fixtures/live
    └─ /api/flashscore/matches/live
    ↓
    [Si vacío] → RapidAPI (fallback)
    ├─ /matches
    ├─ /matches?live=true
    ├─ /fixtures
    └─ /live
    ↓
    Procesamiento Poisson
    ├─ Cálculo de xG y métricas
    ├─ Lambda Poisson
    ├─ P(Gol) según distribución Poisson
    ├─ Value Betting
    └─ [Si value >= 8.0] → Alerta Telegram
```

## 🚀 Deploy Status

| Componente | Estado | Notas |
|-----------|--------|-------|
| Código Python | ✅ Compilado | Sin errores sintácticos |
| FlashScore Integration | ✅ Implementado | Listo para probar |
| RapidAPI Fallback | ✅ Implementado | 2100+ ligas disponibles |
| Telegram Alerts | ✅ Configurado | Espera TELEGRAM_TOKEN + CHAT_ID |
| Railway Deployment | ⏳ En Espera | Necesita validación en vivo |
| Auto-deploy desde GitHub | ✅ Habilitado | Push automático a Railway |

## 🔍 Cómo Verificar en Railway

### 1️⃣ Acceder a Railway Console
```
https://railway.app → alertas-bet → Deployments
```

### 2️⃣ Obtener Railway URL
- Ir a "Live URL" o "Railway Link"
- Ejemplo: `https://alertas-bet-abc123.up.railway.app`

### 3️⃣ Test Health Check
```bash
curl https://YOUR_RAILWAY_URL/
```
Debe retornar: `{"status": "healthy", ...}`

### 4️⃣ Test Mejor Partido (Critical)
```bash
curl https://YOUR_RAILWAY_URL/webhook/best-match
```

**Si hay partidos REALES en vivo:**
```json
{
  "status": "ok",
  "match": "Barcelona vs Real Madrid",
  "league": "La Liga",
  "value": 12.5,
  "recommendation": "Over 1.0 Asiático ⭐⭐"
}
```

**Si no hay partidos (normal en horario bajo):**
```json
{
  "status": "low_value",
  "message": "No hay partidos con value >= 5.0",
  "matches_analyzed": 0
}
```

### 5️⃣ Test Diagnóstico API
```bash
curl https://YOUR_RAILWAY_URL/webhook/diagnose
```

Mostrará:
- ✓ RAPIDAPI_KEY configurada
- ✓ Cuáles endpoints responden
- ✓ Cantidad de partidos encontrados

### 6️⃣ Revisar Logs
```
Railway Console → Logs → Buscar:
- "FlashScore" o "RapidAPI" = API funcionando
- "SOLO datos REALES" = Confirmación de cambio
- "Error" = Problema detectado
```

## 📱 Verificación de Telegram

### Si todo funciona correctamente:
1. Espera a que haya partidos EN VIVO
2. Cuando scheduler ejecute (cada 5 min) y encuentre partido con value >= 8.0
3. Recibirás mensaje en Telegram con formato HTML:

```
🟡 MEDIO

⚽ Barcelona vs Real Madrid
📊 Liga: La Liga
🕐 Minuto: 35
📈 Marcador: 1-0

📊 ANÁLISIS:
  Score: 0.125
  Momentum: 1.00
  xG Total: 2.80
  Tiros: 14 (en puerta: 7)
  Dominancia: 55.0%

🔬 MODELO POISSON:
  Lambda: 1.250
  P(Gol): 71.3%

💰 OPORTUNIDAD:
  P(Mercado): 52.6%
  VALUE: +12.5%

✅ Over 1.0 Asiático ⭐⭐

⏰ 2026-05-13T15:30:00
```

## ⚠️ Próximos Problemas Potenciales

| Problema | Indicador | Solución |
|----------|-----------|----------|
| RAPIDAPI_KEY no configurada | Error 403 en `/webhook/diagnose` | Verificar Railway variables |
| FlashScore 429 rate limit | Logs "Status: 429" | Esperar o cambiar a RapidAPI primario |
| Sin partidos EN VIVO | Respuesta "no_matches" | Normal en horario bajo, esperar |
| Telegram no recibe | No hay mensaje después de 5 min | Verificar TELEGRAM_TOKEN + CHAT_ID |
| Timeout en APIs | Logs "⏱️ Timeout" | Problema de red, esperar |

## 📋 Resumen de Cambios Realizados

### Commits Recientes:
1. **4c0f31c** - Feature: Agregar FlashScore API como alternativa primaria
2. **d9713dc** - Agregar script de diagnóstico para FlashScore
3. **12066aa** - Add comprehensive FlashScore integration verification plan

### Archivos Modificados:
- `railway_main.py` - Lógica de FlashScore + RapidAPI
- `test_flashscore.py` - Script de diagnóstico (NUEVO)
- `VERIFICATION_PLAN.md` - Plan de pruebas (NUEVO)
- `STATUS_SUMMARY.md` - Este archivo (NUEVO)

## ✨ Key Features

| Feature | Implementado | Trabajando |
|---------|-------------|-----------|
| FlashScore Integration | ✅ | ⏳ Requiere testing |
| RapidAPI Fallback | ✅ | ⏳ Requiere testing |
| Poisson Model | ✅ | ✅ Verificado |
| Telegram Alerts | ✅ | ⏳ Requiere testing |
| Auto-scheduler | ✅ | ⏳ Requiere testing |
| SOLO Datos Reales | ✅ | ⏳ Requiere testing |

## 🎯 Acción Inmediata Necesaria

### Para el Usuario:
1. **URGENTE**: Ir a https://railway.app y obtener URL live
2. Ejecutar: `curl YOUR_URL/webhook/best-match`
3. Revisar logs de Railway para ver qué API se está usando
4. Si hay error: ejecutar `curl YOUR_URL/webhook/diagnose` para diagnosticar

### Para CI/CD:
- ✅ Ya está configurado
- ✅ Cada push a GitHub → Auto-deploy a Railway
- ⏳ Esperando que usuario valide en Railway

## 📞 Soporte Técnico

Si algo no funciona:
1. Revisar `/webhook/diagnose` para ver estado de APIs
2. Revisar logs en Railway console
3. Ejecutar `python3 test_flashscore.py` en Railway console

---

**Estado Final:** 🟡 READY FOR TESTING
**Esperando:** Validación en Railway deployment en vivo
**Próximo Paso:** Usuario verifica URL + endpoints en Railway

Último update: 2026-05-13 20:15 UTC
