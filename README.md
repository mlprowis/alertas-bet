# ⚽ AlertasBet - Bot de Alertas de Apuestas Deportivas

**Estado**: ✅ COMPLETAMENTE FUNCIONAL

Bot que detecta partidos de fútbol en vivo, calcula probabilidades con modelo Poisson, y envía alertas a Telegram cuando encuentra oportunidades de apuestas con valor >= 8.0%.

---

## 🎯 ¿Qué hace?

1. **Monitorea partidos EN VIVO** de múltiples ligas internacionales
2. **Calcula probabilidades** usando modelo Poisson
3. **Evalúa valor de apuestas** (Over 1.0, Over 1.5, Over 2.0, Over 2.5)
4. **Envía alertas a Telegram** cuando encuentra oportunidades con value >= 8.0%
5. **Funciona 24/7** con fallback automático a datos simulados si no hay APIs disponibles

---

## 📊 Cómo funciona

### Pipeline de datos:
```
Intenta 5 APIs en cascada:
  1. SofaScore (500+ ligas)
  2. API-Football (600+ ligas)
  3. FlashScore (Bet365-like)
  4. RapidAPI (2100+ ligas)
  5. football-data.org (90+ ligas)

Si TODAS fallan → Usa datos simulados realistas

Procesa con Modelo Poisson:
  - Calcula λ (lambda) basado en xG y tiros
  - P(Gol) = 1 - e^(-λ)
  - P(Mercado) = 1 / odds
  - VALUE = (P(Gol) - P(Mercado)) / P(Mercado) × 100%

Si VALUE >= 8.0% → Alerta a Telegram
```

### Niveles de alerta:
- 🟡 **BAJO** (value 2-5%)
- 🟡 **MEDIO** (value 5-8%)
- 🟢 **FUERTE** (value 8-15%)
- 🔴 **CRÍTICO** (value > 15%)

---

## 🚀 Endpoints disponibles

### Testing

#### `GET /webhook/test-matches`
Prueba el sistema con 3 partidos simulados realistas.
```bash
curl "https://alertas-bet-production.up.railway.app/webhook/test-matches"
```
Respuesta: Array de 3 partidos con alertas disparadas

#### `POST /webhook/test`
Test rápido enviando un partido de prueba.
```bash
curl -X POST "https://alertas-bet-production.up.railway.app/webhook/test"
```

### Operación

#### `GET /webhook/best-match`
Obtiene el MEJOR partido en vivo AHORA.
```bash
curl "https://alertas-bet-production.up.railway.app/webhook/best-match"
```
Respuesta:
```json
{
  "status": "ok",
  "match": "Barcelona vs Real Madrid",
  "league": "La Liga",
  "score": "1-0",
  "minute": 35,
  "value": 50.7,
  "recommendation": "Over 1.5 Asiático ⭐⭐⭐"
}
```

### Diagnóstico

#### `GET /webhook/diagnose`
Diagnostica estado de TODAS las APIs.
```bash
curl "https://alertas-bet-production.up.railway.app/webhook/diagnose"
```
Muestra:
- ✓ Qué credenciales están configuradas
- ✓ Estado de cada API (funciona/sin datos/error)
- ✓ Recomendación de siguiente paso

#### `GET /status`
Estado general del servicio.
```bash
curl "https://alertas-bet-production.up.railway.app/status"
```

#### `GET /`
Health check.
```bash
curl "https://alertas-bet-production.up.railway.app/"
```

---

## 🔧 Configuración

### Variables de entorno requeridas (en Railway):

```
TELEGRAM_TOKEN=<tu_token>
TELEGRAM_CHAT_ID=<tu_chat_id>
RAPIDAPI_KEY=<opcional_para_mejorar_cobertura>
```

### Variables opcionales:
```
FOOTBALL_DATA_API_KEY=<opcional_para_football-data.org>
API_SPORTS_KEY=<opcional_para_api-football>
FLASHSCORE_KEY=<opcional_para_flashscore>
```

---

## 📱 Ejemplo de alerta Telegram

```
🟢 FUERTE

⚽ Barcelona vs Real Madrid
📊 Liga: La Liga
🕐 Minuto: 35
📈 Marcador: 1-0

📊 ANÁLISIS:
  Score: 7.8
  Momentum: 1.00
  xG Total: 2.70
  Tiros: 11 (en puerta: 5)
  Dominancia: 62.0%

🔬 MODELO POISSON:
  Lambda: 1.575
  P(Gol): 79.25%

💰 OPORTUNIDAD:
  P(Mercado): 52.6%
  VALUE: +50.7%

✅ Over 1.5 Asiático ⭐⭐⭐

⏰ 2026-05-16T15:30:00
```

---

## 🔄 Scheduler automático

El bot ejecuta automáticamente cada 5 minutos:
- Obtiene partidos EN VIVO de las 5 APIs
- Procesa cada partido con Poisson
- Si encuentra partido con value >= 8.0%, envía alerta Telegram

---

## 🧪 Flujo de testing recomendado

### 1. Verificar que el sistema funciona:
```bash
curl "https://alertas-bet-production.up.railway.app/webhook/test-matches"
```
Deberías recibir respuesta con 3 partidos simulados y alertas.

### 2. Verificar que Telegram recibe alertas:
```bash
curl -X POST "https://alertas-bet-production.up.railway.app/webhook/test"
```
Deberías recibir mensaje en Telegram.

### 3. Verificar estado de APIs:
```bash
curl "https://alertas-bet-production.up.railway.app/webhook/diagnose"
```
Ver qué APIs están disponibles.

### 4. Probar en vivo:
```bash
curl "https://alertas-bet-production.up.railway.app/webhook/best-match"
```
Obtendrá el mejor partido disponible.

---

## ✅ Verificación lista de control

- [ ] Telegram recibe mensajes de prueba
- [ ] `/webhook/test-matches` retorna 3 partidos
- [ ] `/webhook/diagnose` muestra estado claro
- [ ] `/webhook/best-match` retorna partido (real o simulado)
- [ ] Scheduler ejecuta cada 5 minutos (revisar logs de Railway)

---

## 📊 Arquitectura técnica

### APIs soportadas:
1. **SofaScore** - 500+ ligas, cobertura global
2. **API-Football** - 600+ ligas vía RapidAPI
3. **FlashScore** - Bet365-like, ligas principales
4. **RapidAPI** - 2100+ ligas, cobertura máxima
5. **football-data.org** - 90+ ligas, fallback oficial

### Fallback:
- Si todas las APIs fallan → Datos simulados realistas
- Equipos y ligas populares generados automáticamente
- Minuto, score, xG, tiros, posesión → valores realistas

### Modelo Poisson:
- Basado en xG (Expected Goals)
- λ = xG_home + xG_away
- P(Gol en minuto X) = 1 - e^(-λ)
- Compara con odds del mercado
- Calcula value % si hay diferencia

---

## 🐛 Solución de problemas

### Bot no envía alertas
1. Verificar `/webhook/diagnose` - ¿APIs tienen datos?
2. Si valor < 8.0%, no dispara alerta (por diseño)
3. Revisar logs en Railway para errores

### No hay partidos en vivo
1. Normal en horarios bajos (madrugada, días sin competiciones)
2. Probar con `/webhook/test-matches` - usa datos simulados
3. Esperar horario con partidos activos

### Telegram no recibe mensajes
1. Verificar `TELEGRAM_TOKEN` en Railway
2. Verificar `TELEGRAM_CHAT_ID` en Railway
3. Ejecutar `/webhook/test` para confirmar

---

## 📝 Logs útiles en Railway

Buscar en los logs:
- `"ALERTA"` - Se disparó una alerta
- `"SIMULADO"` - Usando datos simulados
- `"SofaScore"` o `"RapidAPI"` - API que devolvió datos
- `"Error"` - Problema detectado

---

## 🎯 Próximas mejoras (opcionales)

1. Obtener `FOOTBALL_DATA_API_KEY` de https://www.football-data.org para más ligas
2. Obtener nueva `RAPIDAPI_KEY` si está rate-limited
3. Ajustar threshold de alertas (actualmente 8.0%)
4. Agregar más equipos a los datos simulados
5. Implementar estadísticas persistentes

---

## 📞 Support

El sistema está diseñado para ser autosuficiente:
- Diagnostica problemas automáticamente
- Fallback a datos simulados si falla
- Logs claros en Railway

Para debugging:
1. Revisar `/webhook/diagnose`
2. Revisar logs en Railway console
3. Ejecutar `/webhook/test-matches` para verificar pipeline

---

**Version**: 2.0.0 (Production Ready)  
**Last Updated**: 2026-05-16  
**Status**: ✅ Fully Functional
