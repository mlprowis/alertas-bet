# 🚀 ALERTAS BET - RESUMEN DE DEPLOYMENT

## 📌 ¿QUÉ SE HA HECHO?

### 1. ✅ Integración de FlashScore API
Se ha implementado una clase completa `FlashScoreAPI` que se conecta a la API de FlashScore a través de RapidAPI. Esta es la **API primaria** para obtener partidos en vivo de:
- **Ligas menores** (categorías bajas, regionalles)
- **Ligas principales** (Premier, La Liga, Serie A, etc.)

**Endpoints que intenta:**
- `/api/flashscore/v2/matches/live`
- `/api/flashscore/v2/matches`
- `/api/flashscore/v2/fixtures/live`
- `/api/flashscore/matches/live`

### 2. ✅ RapidAPI como Fallback
Si FlashScore no tiene partidos en vivo, se intenta automáticamente RapidAPI que cubre **2100+ ligas**.

**Flujo actualizado (SOLO DATOS REALES):**
```
procesar_partidos_en_vivo()
    ↓
Intenta FlashScore primero
    ↓
Si está vacío: Intenta RapidAPI
    ↓
Si ambos vacíos: "No hay partidos en vivo REALES"
    ↓
Si hay datos: Procesamiento Poisson → Alerta Telegram (si value >= 8.0)
```

### 3. ✅ Cambio Crítico: ELIMINAR Simulados
**Antes:** Cuando ambas APIs fallaban, generaba partidos simulados
**Ahora:** Solo usa partidos REALES. Si no hay partidos en vivo, simplemente espera al siguiente ciclo.

Logs claros:
```
"⚽ Obteniendo partidos en vivo REALES..."
"📊 SOLO datos REALES - Sin simulaciones"
```

### 4. ✅ Endpoints Flask Actualizados

#### `/webhook/best-match` (GET o POST)
Busca el **mejor partido en vivo ahora mismo**:
- Procesa todos los partidos EN VIVO
- Evalúa con modelo Poisson
- Retorna el que tiene mayor value
- Si value >= 5.0: Envía a Telegram

**Respuesta si hay partidos:**
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

#### `/webhook/diagnose` (GET)
Diagnostica qué está pasando con las APIs:
- Verifica RAPIDAPI_KEY
- Prueba cada endpoint
- Muestra cantidad de partidos encontrados
- Identifica problemas

### 5. ✅ Scheduler Automático
- Se ejecuta cada **5 minutos** automáticamente
- Llama a `procesar_partidos_en_vivo()`
- Envía alertas a Telegram si encuentra oportunidades

## 📊 Archivos Commitados

```
4c0f31c - Feature: Agregar FlashScore API como alternativa primaria - SOLO datos REALES
d9713dc - Agregar script de diagnóstico para FlashScore API
12066aa - Add comprehensive FlashScore integration verification plan
781b3af - Add detailed status summary and next steps
```

## 🎯 PRÓXIMOS PASOS - PARA TI

### Paso 1️⃣: Obtener URL de Railway
1. Ir a https://railway.app
2. Seleccionar tu proyecto "alertas-bet"
3. Ir a "Deployments"
4. Copiar la URL del deployment activo
   - Ejemplo: `https://alertas-bet-abc123.up.railway.app`

### Paso 2️⃣: Hacer Push (si no está hecho)
```bash
git push
```

Si hay error de proxy, intenta:
```bash
git push -f origin main
```

### Paso 3️⃣: Esperar Deployment
Railway auto-deployará cuando hagas push. Espera ~2-5 minutos.

Ver estado:
1. En https://railway.app → Deployments
2. Ver que el status sea "Success" (verde)

### Paso 4️⃣: Verificar que Funciona

#### Test 1: Health Check
```bash
curl https://YOUR_RAILWAY_URL/
```

Debe retornar:
```json
{"status": "healthy", "service": "AlertasBet Webhook", ...}
```

#### Test 2: Obtener Mejor Partido EN VIVO AHORA
```bash
curl https://YOUR_RAILWAY_URL/webhook/best-match
```

**Si hay partidos:**
```json
{"status": "ok", "match": "...", "value": 12.5, ...}
```

**Si NO hay partidos (normal si es horario bajo):**
```json
{"status": "low_value", "matches_analyzed": 0}
```

**Si hay ERROR (ej: API key):**
```json
{"status": "no_matches", "message": "..."}
```

#### Test 3: Diagnosticar APIs
```bash
curl https://YOUR_RAILWAY_URL/webhook/diagnose
```

Esto mostrará:
- Si RAPIDAPI_KEY está configurada
- Cuáles endpoints de RapidAPI responden
- Cuántos partidos encuentra cada endpoint

#### Test 4: Ver Logs
1. https://railway.app → alertasbetapi → Logs
2. Buscar líneas que contengan:
   - "FlashScore" o "RapidAPI" = Está intentando APIs
   - "SOLO datos REALES" = Confirmación de cambio
   - "🔔 MEJOR PARTIDO:" = Encontró un partido bueno
   - "Error" o "❌" = Hay un problema

### Paso 5️⃣: Esperar Alerta en Telegram

Si en el test anterior salió `"status": "ok"`:
- El bot intentará enviar a Telegram
- Deberías recibir un mensaje HTML con análisis completo
- Formato: 🟡 MEDIO / FUERTE / CRITICO con valor, lambdas, recomendación

Si **NO** recibes nada:
- Verificar que TELEGRAM_TOKEN y TELEGRAM_CHAT_ID están en Railway
- Ejecutar `/webhook/test` manualmente para forzar test

## ⚠️ Solución de Problemas

### Si `/webhook/diagnose` retorna errores:

#### Error: RAPIDAPI_KEY no configurada
```
"rapidapi_configured": false
```
**Solución:**
1. Ir a Railway → alertasbetapi → Variables
2. Verificar RAPIDAPI_KEY está definida
3. Click redeploy

#### Error: Timeout (15s)
```
"error": "Timeout"
```
**Solución:** Esperar e intentar de nuevo. Railway a veces tiene latencia.

#### Error: 403 Forbidden
```
"status_code": 403
```
**Solución:** 
- RAPIDAPI_KEY no es válida
- O el servicio de RapidAPI está caído
- Intenta en https://rapidapi.com para verificar

### Si `/webhook/best-match` siempre retorna "low_value":

**Opciones:**
1. **Normal:** Si es horario bajo (madrugada), no hay partidos en vivo
2. **API vacía:** Las APIs no tienen datos (problema de RapidAPI)
3. **Value bajo:** Hay partidos pero el modelo Poisson los califica con value < 5.0

Para verificar qué es:
```bash
# Ejecuta esto en Railway Console:
python3 test_flashscore.py
# o
python3 test_rapidapi.py
```

Esto mostrará exactamente qué está retornando cada API.

## 🎯 Resumen de Cambios Clave

| Aspecto | Antes | Ahora |
|--------|-------|-------|
| **API Principal** | RapidAPI | FlashScore |
| **Fallback** | Simulados | RapidAPI |
| **Simulados** | Activos | ❌ REMOVIDOS |
| **Ligas Menores** | No cubiertas | ✅ FlashScore |
| **Data Integrity** | Mixtos (real+simulado) | ✅ SOLO REALES |
| **Logs** | Ambiguos | 🔍 Claros (FlashScore vs RapidAPI) |

## 📱 Verifica que Telegram Funciona

1. Envía manualmente un test:
   ```bash
   curl -X POST https://YOUR_RAILWAY_URL/webhook/test
   ```

2. Deberías recibir en Telegram un mensaje similar a:
   ```
   🟡 MEDIO
   ⚽ Test Match
   📊 Liga: Test League
   ...
   ✅ Over 1.0 Asiático
   ```

3. Si NO recibes nada:
   - Verificar TELEGRAM_TOKEN en Railway
   - Verificar TELEGRAM_CHAT_ID en Railway
   - Verificar que el bot está iniciado en Telegram

## ✨ Beneficios de Esta Integración

| Beneficio | Descripción |
|-----------|------------|
| 🌍 **Cobertura Mundial** | FlashScore cubre ligas que RapidAPI no (menores) |
| 📊 **Datos Reales** | Solo partidos EN VIVO, sin simulaciones |
| 🔄 **Fallback Automático** | Si FlashScore falla, intenta RapidAPI |
| ⚡ **Rápido** | Intenta 4 endpoints, usa el primero que funciona |
| 📱 **Alerts en Tiempo Real** | Telegram recibe notificación al encontrar oportunidad |
| 🔍 **Diagnosticable** | `/webhook/diagnose` muestra exactamente qué pasa |

## 📋 Checklist Final

Antes de considerar "Listo":

- [ ] URL de Railway obtenida
- [ ] Git push completado (sin errores)
- [ ] Deployment en Railway visible (status: Success)
- [ ] `curl /` retorna status: healthy
- [ ] `curl /webhook/diagnose` muestra datos
- [ ] `curl /webhook/best-match` retorna respuesta (ok o low_value)
- [ ] Logs de Railway muestran "FlashScore" o "RapidAPI"
- [ ] Al menos 1 alerta recibida en Telegram (si hay partidos en vivo)

## 🎉 Estado Final

```
✅ Código: Compilado y listo
✅ Lógica: FlashScore primario + RapidAPI fallback
✅ Telegram: Integrado
✅ Scheduler: Corre cada 5 minutos
✅ Sin Simulados: Confirmado
⏳ Railway Deployment: Esperando validación del usuario
```

---

**Próximo paso:** Ir a https://railway.app y ejecutar los tests anteriores.

**Cualquier problema:** Revisar `/webhook/diagnose` y logs de Railway.

¡Gracias por confiar en AlertasBet! 🎯
