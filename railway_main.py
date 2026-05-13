#!/usr/bin/env python3
"""
Bot de Alertas Deportivas - Versión Cloud (Railway.app con Gunicorn)
Servicio webhook que monitorea partidos en vivo y envía alertas a Telegram

⚠️ IMPORTANTE: Este archivo está diseñado para ejecutarse con GUNICORN en Railway
"""

import os
import json
import logging
import math
import asyncio
import random
from datetime import datetime
from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum

from flask import Flask, request, jsonify
from telegram import Bot
from telegram.error import TelegramError
from apscheduler.schedulers.background import BackgroundScheduler

# ============ LOGGING ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ CONFIGURACIÓN ============
PORT = int(os.getenv("PORT", 5000))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logger.info(f"🚀 Configuración Railway: PORT={PORT}")
logger.info(f"📱 Telegram Token: {'✓ Configurado' if TELEGRAM_TOKEN else '⚠️ NO CONFIGURADO'}")
logger.info(f"💬 Chat ID: {'✓ Configurado' if TELEGRAM_CHAT_ID else '⚠️ NO CONFIGURADO'}")

# ============ FLASK APP ============
app = Flask(__name__)

# Inicializar bot de Telegram si hay credenciales
bot = None
if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        logger.info(f"✓ Bot Telegram inicializado para chat {TELEGRAM_CHAT_ID}")
    except Exception as e:
        logger.error(f"✗ Error inicializando Bot Telegram: {e}")
else:
    logger.warning("⚠️ Bot Telegram no será funcional - configura TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en Railway")

# ============ ENUM Y DATACLASSES ============
class AlertLevel(Enum):
    BAJO = "🟢"
    MEDIO = "🟡"
    FUERTE = "🟠"
    CRITICO = "🔴"

@dataclass
class PoissonResult:
    lambda_final: float
    p_gol: float
    p_mercado: float
    value: float
    recomendacion: str

@dataclass
class AlertData:
    partido: str
    liga: str
    minuto: int
    marcador: str
    level: AlertLevel
    score_final: float
    momentum: float
    xg_total: float
    tiros: int
    tiros_puerta: int
    dominancia: float
    eficiencia: float
    lambda_final: float
    p_gol: float
    p_mercado: float
    value: float
    recomendacion: str
    timestamp: str

# ============ POISSON MODEL ============
class PoissonModel:
    """Modelo Poisson para predicción de goles"""

    FACTORES = {
        "momentum": {"min": 0.75, "max": 1.25, "default": 1.0},
        "eficiencia": {"min": 0.95, "max": 1.15, "default": 1.0},
        "dominancia": {"min": 0.95, "max": 1.10, "default": 1.0},
        "aceleracion": {"min": 0.90, "max": 1.20, "default": 1.0}
    }
    PENALIDAD_MINUTO = 0.85
    BOOST_EVENTO = 1.10

    @staticmethod
    def calcular_lambda_base(xg_total: float, tiros_totales: int) -> float:
        """Calcula lambda base usando xG"""
        if xg_total <= 0:
            return 0.5
        conversion_rate = min(tiros_totales / max(tiros_totales, 1), 1.0)
        return max(xg_total * (0.8 + 0.4 * conversion_rate), 0.1)

    @staticmethod
    def aplicar_factores(lambda_base: float, momentum: float = 1.0, eficiencia: float = 1.0,
                        dominancia: float = 1.0, aceleracion: float = 1.0) -> float:
        """Aplica factores al lambda base"""
        lambda_ajustado = lambda_base * momentum * eficiencia * dominancia * aceleracion
        return max(lambda_ajustado, 0.1)

    @staticmethod
    def aplicar_penalidad_minuto(lambda_valor: float, minuto: int) -> float:
        """Aplica penalidad según el minuto del partido"""
        periodos_10min = minuto // 10
        penalidad = PoissonModel.PENALIDAD_MINUTO ** min(periodos_10min, 2)
        return lambda_valor * penalidad

    @staticmethod
    def calcular_probabilidad(lambda_valor: float) -> float:
        """Calcula P(Gol) usando distribución Poisson"""
        if lambda_valor <= 0:
            return 0.0
        return 1 - math.exp(-lambda_valor)

    @staticmethod
    def calcular_value(p_modelo: float, p_mercado: float) -> float:
        """Calcula el value betting"""
        if p_mercado <= 0:
            return 0.0
        return (p_modelo - p_mercado) / p_mercado

    @classmethod
    def evaluar_partido(cls, xg_total: float, tiros_totales: int, minuto: int,
                       cuota_over: float, momentum: float = 1.0, eficiencia: float = 1.0,
                       dominancia: float = 1.0, aceleracion: float = 1.0) -> PoissonResult:
        """Evaluación completa del partido"""
        lambda_base = cls.calcular_lambda_base(xg_total, tiros_totales)
        lambda_con_factores = cls.aplicar_factores(lambda_base, momentum, eficiencia, dominancia, aceleracion)
        lambda_final = cls.aplicar_penalidad_minuto(lambda_con_factores, minuto)
        p_gol = cls.calcular_probabilidad(lambda_final)
        p_mercado = 1 / cuota_over if cuota_over > 0 else 0.5
        value = cls.calcular_value(p_gol, p_mercado)

        recomendacion = (
            "Over 1.0 Asiático ⭐⭐" if value >= 0.15
            else "Over 1.0 Asiático" if value >= 0.08
            else "Evaluar con cuidado"
        )

        return PoissonResult(
            round(lambda_final, 3),
            round(p_gol * 100, 1),
            round(p_mercado * 100, 1),
            round(value * 100, 1),
            recomendacion
        )

# ============ SPORT ANALYZER ============
class SportAnalyzer:
    """Analizador de métricas deportivas"""

    @staticmethod
    def calcular_metricas(data: Dict[str, Any]) -> Dict[str, float]:
        """Extrae y calcula métricas del partido"""
        try:
            xg_home = float(data.get("xg_home", 0))
            xg_away = float(data.get("xg_away", 0))
            xg_total = xg_home + xg_away
            tiros_totales = int(data.get("shots_home", 0)) + int(data.get("shots_away", 0))
            tiros_puerta = int(data.get("shots_on_target_home", 0)) + int(data.get("shots_on_target_away", 0))
            dominancia = max(
                float(data.get("possession_home", 50)),
                float(data.get("possession_away", 50))
            ) / 100

            return {
                "xg_total": xg_total,
                "tiros_totales": tiros_totales,
                "tiros_puerta": tiros_puerta,
                "dominancia": dominancia,
                "momentum": 1.0,
                "eficiencia": 1.0,
                "aceleracion": 1.0,
            }
        except Exception as e:
            logger.error(f"Error calculando métricas: {e}")
            return {
                "xg_total": 0.5,
                "tiros_totales": 0,
                "tiros_puerta": 0,
                "dominancia": 0.5,
                "momentum": 1.0,
                "eficiencia": 1.0,
                "aceleracion": 1.0,
            }

    @staticmethod
    def calcular_score_alerta(poisson: PoissonResult, metricas: Dict[str, float]) -> tuple:
        """Calcula score y nivel de alerta"""
        score = min(1.0, max(0.0, poisson.value / 100))
        level = (
            AlertLevel.CRITICO if score >= 0.85
            else AlertLevel.FUERTE if score >= 0.65
            else AlertLevel.MEDIO if score >= 0.45
            else AlertLevel.BAJO
        )
        return score, level

# ============ TELEGRAM ALERTS ============
async def enviar_alerta_telegram(alert: AlertData) -> bool:
    """Envía alerta formateada a Telegram"""
    if not bot:
        logger.warning("Bot Telegram no disponible")
        return False

    try:
        mensaje = f"""{alert.level.value} <b>{alert.level.name}</b>

<b>⚽ {alert.partido}</b>
📊 Liga: {alert.liga}
🕐 Minuto: {alert.minuto}
📈 Marcador: {alert.marcador}

<b>📊 ANÁLISIS:</b>
  Score: {alert.score_final:.3f}
  Momentum: {alert.momentum:.2f}
  xG Total: {alert.xg_total:.2f}
  Tiros: {alert.tiros} (en puerta: {alert.tiros_puerta})
  Dominancia: {alert.dominancia:.1f}%

<b>🔬 MODELO POISSON:</b>
  Lambda: {alert.lambda_final:.3f}
  P(Gol): {alert.p_gol:.1f}%

<b>💰 OPORTUNIDAD:</b>
  P(Mercado): {alert.p_mercado:.1f}%
  VALUE: <b>+{alert.value:.1f}%</b>

<b>✅ {alert.recomendacion}</b>

⏰ {alert.timestamp}"""

        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=mensaje,
            parse_mode="HTML"
        )
        logger.info(f"✓ Alerta enviada a Telegram: {alert.partido}")
        return True

    except TelegramError as e:
        logger.error(f"✗ Error enviando a Telegram: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Error inesperado: {e}")
        return False

# ============ SIMULATED MATCHES - Sistema de Simulación de Partidos ============
class SimulatedMatches:
    """Generador de datos de partidos simulados realistas"""

    LIGAS = ["Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1"]
    EQUIPOS = [
        ("Manchester United", "Liverpool"),
        ("Real Madrid", "Barcelona"),
        ("Juventus", "AC Milan"),
        ("Bayern Munich", "Dortmund"),
        ("PSG", "Marseille"),
        ("Arsenal", "Tottenham"),
        ("Inter", "Roma"),
        ("Sevilla", "Atletico Madrid"),
    ]

    @staticmethod
    def generar_partido_simulado() -> Dict[str, Any]:
        """Genera datos realistas de un partido en vivo simulado"""
        league = random.choice(SimulatedMatches.LIGAS)
        home_team, away_team = random.choice(SimulatedMatches.EQUIPOS)

        # Minuto aleatorio entre 20 y 85
        minute = random.randint(20, 85)

        # Marcadores realistas
        goals_home = random.randint(0, 3)
        goals_away = random.randint(0, 3)
        score = f"{goals_home}-{goals_away}"

        # Estadísticas realistas que varían
        xg_home = round(random.uniform(0.8, 2.5), 2)
        xg_away = round(random.uniform(0.6, 2.0), 2)

        shots_home = random.randint(4, 15)
        shots_away = random.randint(3, 12)

        shots_on_target_home = max(1, int(shots_home * random.uniform(0.3, 0.6)))
        shots_on_target_away = max(1, int(shots_away * random.uniform(0.3, 0.6)))

        possession_home = random.randint(40, 65)
        possession_away = 100 - possession_home

        # Cuotas realistas para Over 1.0
        odds_over_1 = round(random.uniform(1.85, 2.10), 2)

        return {
            "match_name": f"{home_team} vs {away_team}",
            "league": league,
            "minute": minute,
            "score": score,
            "xg_home": xg_home,
            "xg_away": xg_away,
            "shots_home": shots_home,
            "shots_away": shots_away,
            "shots_on_target_home": shots_on_target_home,
            "shots_on_target_away": shots_on_target_away,
            "possession_home": possession_home,
            "possession_away": possession_away,
            "odds_over_1": odds_over_1
        }

def procesar_partido_simulado():
    """Procesa un partido simulado y envía alerta si es necesario"""
    try:
        logger.info("📊 Procesando partido simulado automático...")

        # Generar datos
        match_data = SimulatedMatches.generar_partido_simulado()

        # Procesar
        metricas = SportAnalyzer.calcular_metricas(match_data)
        poisson = PoissonModel.evaluar_partido(
            metricas["xg_total"],
            metricas["tiros_totales"],
            match_data["minute"],
            match_data["odds_over_1"]
        )

        score_alerta, level = SportAnalyzer.calcular_score_alerta(poisson, metricas)

        # Si value >= 8.0, enviar alerta
        if poisson.value >= 8.0:
            logger.info(f"🔔 ALERTA AUTOMÁTICA: {match_data['match_name']} (Value: {poisson.value}%)")

            if bot:
                alert_data = AlertData(
                    partido=match_data["match_name"],
                    liga=match_data["league"],
                    minuto=match_data["minute"],
                    marcador=match_data["score"],
                    level=level,
                    score_final=score_alerta,
                    momentum=metricas["momentum"],
                    xg_total=metricas["xg_total"],
                    tiros=metricas["tiros_totales"],
                    tiros_puerta=metricas.get("tiros_puerta", 0),
                    dominancia=metricas["dominancia"],
                    eficiencia=metricas["eficiencia"],
                    lambda_final=poisson.lambda_final,
                    p_gol=poisson.p_gol,
                    p_mercado=poisson.p_mercado,
                    value=poisson.value,
                    recomendacion=poisson.recomendacion,
                    timestamp=datetime.now().isoformat()
                )
                asyncio.run(enviar_alerta_telegram(alert_data))
        else:
            logger.info(f"ℹ️ Partido simulado procesado (sin alerta): {match_data['match_name']} (Value: {poisson.value}%)")

    except Exception as e:
        logger.error(f"Error procesando partido simulado: {e}", exc_info=True)

# ============ FLASK ROUTES ============

@app.route('/', methods=['GET'])
def health():
    """Health check - endpoint para verificar que la app está viva"""
    return jsonify({
        "status": "healthy",
        "service": "AlertasBet Webhook",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "telegram_configured": bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
        "port": PORT
    }), 200

@app.route('/webhook/match', methods=['POST'])
def webhook_match():
    """Webhook principal para procesar datos de partidos"""
    try:
        data = request.get_json()

        if not data:
            logger.warning("Request vacío recibido")
            return jsonify({"error": "No data provided"}), 400

        logger.info(f"Partido recibido: {data.get('match_name', 'Unknown')}")

        # Extraer datos
        match_name = data.get('match_name', 'Unknown Match')
        league = data.get('league', 'Unknown League')
        minute = int(data.get('minute', 0))
        score = data.get('score', '0-0')
        odds_over = float(data.get('odds_over_1', 1.92))

        # Calcular métricas
        metricas = SportAnalyzer.calcular_metricas(data)

        # Evaluar con Poisson
        poisson = PoissonModel.evaluar_partido(
            metricas["xg_total"],
            metricas["tiros_totales"],
            minute,
            odds_over,
            momentum=metricas.get("momentum", 1.0),
            eficiencia=metricas.get("eficiencia", 1.0),
            dominancia=metricas.get("dominancia", 1.0),
            aceleracion=metricas.get("aceleracion", 1.0)
        )

        # Calcular score y nivel
        score_alerta, level = SportAnalyzer.calcular_score_alerta(poisson, metricas)

        # Si value >= 8.0, es una alerta
        if poisson.value >= 8.0:
            logger.info(f"🔔 ALERTA GENERADA: {match_name} (Value: {poisson.value}%)")

            # Enviar a Telegram si está configurado
            if bot:
                alert_data = AlertData(
                    partido=match_name,
                    liga=league,
                    minuto=minute,
                    marcador=score,
                    level=level,
                    score_final=score_alerta,
                    momentum=metricas["momentum"],
                    xg_total=metricas["xg_total"],
                    tiros=metricas["tiros_totales"],
                    tiros_puerta=metricas.get("tiros_puerta", 0),
                    dominancia=metricas["dominancia"],
                    eficiencia=metricas["eficiencia"],
                    lambda_final=poisson.lambda_final,
                    p_gol=poisson.p_gol,
                    p_mercado=poisson.p_mercado,
                    value=poisson.value,
                    recomendacion=poisson.recomendacion,
                    timestamp=datetime.now().isoformat()
                )
                # Ejecutar de forma asincrónica
                asyncio.run(enviar_alerta_telegram(alert_data))

            return jsonify({
                "status": "alert",
                "match": match_name,
                "lambda": poisson.lambda_final,
                "p_gol": poisson.p_gol,
                "p_mercado": poisson.p_mercado,
                "value": poisson.value,
                "recommendation": poisson.recomendacion
            }), 200
        else:
            logger.info(f"ℹ️ Sin alerta: {match_name} (Value: {poisson.value}%)")
            return jsonify({
                "status": "no_alert",
                "match": match_name,
                "value": poisson.value,
                "reason": "Value < 8.0"
            }), 200

    except json.JSONDecodeError:
        logger.error("Invalid JSON en request")
        return jsonify({"error": "Invalid JSON"}), 400
    except Exception as e:
        logger.error(f"Error en webhook_match: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/test', methods=['POST', 'GET'])
def webhook_test():
    """Endpoint de test para verificar que la app funciona y envía alertas a Telegram"""
    try:
        logger.info("Test webhook llamado")

        # Datos de prueba
        test_data = {
            "match_name": "Test Match",
            "league": "Test League",
            "minute": 45,
            "score": "1-1",
            "xg_home": 1.5,
            "xg_away": 0.9,
            "shots_home": 5,
            "shots_away": 3,
            "shots_on_target_home": 3,
            "shots_on_target_away": 2,
            "possession_home": 55,
            "possession_away": 45,
            "odds_over_1": 1.92
        }

        # Procesar
        metricas = SportAnalyzer.calcular_metricas(test_data)
        poisson = PoissonModel.evaluar_partido(
            metricas["xg_total"],
            metricas["tiros_totales"],
            45,
            1.92
        )

        # Calcular score y nivel
        score_alerta, level = SportAnalyzer.calcular_score_alerta(poisson, metricas)

        # Si value >= 8.0, enviar alerta a Telegram
        if poisson.value >= 8.0:
            logger.info(f"🔔 ALERTA GENERADA EN TEST: Test Match (Value: {poisson.value}%)")

            # Enviar a Telegram si está configurado
            if bot:
                alert_data = AlertData(
                    partido=test_data["match_name"],
                    liga=test_data["league"],
                    minuto=test_data["minute"],
                    marcador=test_data["score"],
                    level=level,
                    score_final=score_alerta,
                    momentum=metricas["momentum"],
                    xg_total=metricas["xg_total"],
                    tiros=metricas["tiros_totales"],
                    tiros_puerta=metricas.get("tiros_puerta", 0),
                    dominancia=metricas["dominancia"],
                    eficiencia=metricas["eficiencia"],
                    lambda_final=poisson.lambda_final,
                    p_gol=poisson.p_gol,
                    p_mercado=poisson.p_mercado,
                    value=poisson.value,
                    recomendacion=poisson.recomendacion,
                    timestamp=datetime.now().isoformat()
                )
                # Ejecutar de forma asincrónica
                asyncio.run(enviar_alerta_telegram(alert_data))
                logger.info("✓ Alerta TEST enviada a Telegram exitosamente")

        return jsonify({
            "status": "ok",
            "message": "Test exitoso",
            "alert_sent": poisson.value >= 8.0,
            "test_data": {
                "match": "Test Match",
                "xg_total": metricas["xg_total"],
                "shots": metricas["tiros_totales"],
                "lambda": poisson.lambda_final,
                "p_gol": poisson.p_gol,
                "p_mercado": poisson.p_mercado,
                "value": poisson.value,
                "recommendation": poisson.recomendacion
            }
        }), 200

    except Exception as e:
        logger.error(f"Error en webhook_test: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/simulated', methods=['POST', 'GET'])
def webhook_simulated():
    """Endpoint para disparar un partido simulado manual"""
    try:
        logger.info("🎲 Partido simulado disparado manualmente")
        procesar_partido_simulado()
        return jsonify({
            "status": "ok",
            "message": "Partido simulado procesado"
        }), 200
    except Exception as e:
        logger.error(f"Error en webhook_simulated: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Estado completo del servicio"""
    return jsonify({
        "service": "AlertasBet Webhook",
        "status": "running",
        "version": "2.0.0",
        "environment": {
            "port": PORT,
            "telegram_enabled": bool(bot),
            "telegram_token_set": bool(TELEGRAM_TOKEN),
            "chat_id_set": bool(TELEGRAM_CHAT_ID),
        },
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "GET /": "Health check",
            "GET /status": "Estado completo",
            "POST /webhook/test": "Test del sistema",
            "POST /webhook/match": "Procesar partido",
            "POST /webhook/simulated": "Partido simulado manual"
        }
    }), 200

# ============ ERROR HANDLERS ============
@app.errorhandler(404)
def not_found(e):
    """Maneja rutas no encontradas"""
    return jsonify({
        "error": "Endpoint not found",
        "available_endpoints": {
            "GET /": "Health check",
            "GET /status": "Status",
            "POST /webhook/test": "Test",
            "POST /webhook/match": "Match webhook"
        }
    }), 404

@app.errorhandler(500)
def server_error(e):
    """Maneja errores del servidor"""
    logger.error(f"Server error: {e}")
    return jsonify({"error": "Internal server error"}), 500

# ============ SCHEDULER - Tareas automáticas ============
def iniciar_scheduler():
    """Inicializa el scheduler de tareas automáticas"""
    try:
        scheduler = BackgroundScheduler()

        # Programar partido simulado cada 10 minutos
        scheduler.add_job(
            procesar_partido_simulado,
            'interval',
            minutes=10,
            id='simulated_match',
            name='Partido Simulado Automático'
        )

        scheduler.start()
        logger.info("✓ Scheduler iniciado - Partidos simulados cada 10 minutos")
        return scheduler
    except Exception as e:
        logger.error(f"✗ Error inicializando scheduler: {e}")
        return None

# Iniciar scheduler cuando inicia la app
scheduler = iniciar_scheduler()

# ============ MAIN - para ejecución directa ============
if __name__ == '__main__':
    logger.info("="*60)
    logger.info("MODO DESARROLLO: Ejecutando Flask built-in server")
    logger.info("PARA PRODUCCIÓN EN RAILWAY: Usa gunicorn")
    logger.info("="*60)
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)

# ============ NOTA PARA GUNICORN ============
# Cuando gunicorn ejecuta este archivo, carga la variable 'app' directamente
# Procfile: web: gunicorn --bind 0.0.0.0:$PORT railway_main_GUNICORN:app
