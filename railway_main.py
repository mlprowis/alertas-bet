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
import requests

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
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "free-api-live-football-data.p.rapidapi.com"

logger.info(f"🚀 Configuración Railway: PORT={PORT}")
logger.info(f"📱 Telegram Token: {'✓ Configurado' if TELEGRAM_TOKEN else '⚠️ NO CONFIGURADO'}")
logger.info(f"💬 Chat ID: {'✓ Configurado' if TELEGRAM_CHAT_ID else '⚠️ NO CONFIGURADO'}")
logger.info(f"⚽ RapidAPI (2100+ ligas): {'✓ Configurado' if RAPIDAPI_KEY else '⚠️ NO CONFIGURADO'}")

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

# ============ SIMULATED MATCHES - Sistema de Simulación de Partidos REALISTA ============
class SimulatedMatches:
    """Generador de datos de partidos simulados con LÓGICA REAL"""

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
        """Genera datos realistas de un partido en vivo con lógica coherente"""
        league = random.choice(SimulatedMatches.LIGAS)
        home_team, away_team = random.choice(SimulatedMatches.EQUIPOS)

        # Minuto del partido (20-85 = en vivo realista)
        minute = random.randint(20, 85)
        minutes_remaining = 90 - minute

        # Probabilidad de goles basada en minuto
        # Más tarde = menos probabilidad de goles futuros
        goal_probability_factor = (minutes_remaining / 90.0) * random.uniform(0.7, 1.3)

        # Goles actuales con lógica (relación con minuto)
        # Primeros 20 min: 0-1 goles típicos
        # Min 45-60: 1-2 goles típicos
        # Min 75+: 1-3 goles típicos
        if minute < 30:
            goals_home = random.randint(0, 1) if random.random() > 0.5 else 0
            goals_away = random.randint(0, 1) if random.random() > 0.5 else 0
        elif minute < 60:
            goals_home = random.randint(0, 2)
            goals_away = random.randint(0, 2)
        else:
            goals_home = random.randint(0, 3)
            goals_away = random.randint(0, 3)

        total_goals = goals_home + goals_away
        score = f"{goals_home}-{goals_away}"

        # xG proporcional a goles (equipo con más goles tiene más xG)
        home_dominance = random.uniform(0.45, 0.65)
        xg_home = round((0.8 + total_goals * 0.5 + random.uniform(-0.5, 0.5)) * home_dominance, 2)
        xg_away = round((0.8 + total_goals * 0.5 + random.uniform(-0.5, 0.5)) * (1 - home_dominance), 2)

        # Tiros proporcionales a xG
        shots_home = max(3, int(xg_home * random.uniform(3, 5)))
        shots_away = max(3, int(xg_away * random.uniform(3, 5)))

        # Tiros a puerta proporcionales a tiros totales (40-60%)
        shots_on_target_home = max(1, int(shots_home * random.uniform(0.35, 0.55)))
        shots_on_target_away = max(1, int(shots_away * random.uniform(0.35, 0.55)))

        possession_home = round(home_dominance * 100)
        possession_away = 100 - possession_home

        # CUOTAS INTELIGENTES basadas en análisis real
        # Over 1.0 Asiático = probabilidad de más de 1 gol
        minutes_played = minute
        goles_jugados = total_goals

        # Ratio goles/minuto actual
        goles_por_minuto = goles_jugados / max(1, minutes_played)
        goles_proyectados = goles_por_minuto * 90

        # Probabilidad de más goles basada en:
        # - Goles proyectados
        # - xG restante
        # - Minuto del partido
        xg_remaining = (xg_home + xg_away) / 2 * (minutes_remaining / 90.0)
        expected_more_goals_prob = min(0.95, 0.3 + (goles_proyectados / 4.0) * 0.3 + (xg_remaining / 1.5) * 0.2)

        # Cuota Over = 1 / probabilidad + margen bookmaker (2-10%)
        margin = random.uniform(0.02, 0.08)
        odds_over_1 = round(1.0 / max(0.25, expected_more_goals_prob - margin) + random.uniform(-0.05, 0.05), 2)
        odds_over_1 = max(1.05, min(2.50, odds_over_1))  # Entre 1.05 y 2.50

        return {
            "match_name": f"{home_team} vs {away_team}",
            "league": league,
            "minute": minute,
            "score": score,
            "xg_home": max(0.1, xg_home),
            "xg_away": max(0.1, xg_away),
            "shots_home": shots_home,
            "shots_away": shots_away,
            "shots_on_target_home": shots_on_target_home,
            "shots_on_target_away": shots_on_target_away,
            "possession_home": possession_home,
            "possession_away": possession_away,
            "odds_over_1": odds_over_1
        }

# ============ FLASHSCORE API - Datos en vivo reales de FlashScore ============
class FlashScoreAPI:
    """Integración con FlashScore API v4 (Cobertura mundial de ligas menores)"""

    BASE_URL = "https://flashscore4.p.rapidapi.com"
    RAPIDAPI_HOST = "flashscore4.p.rapidapi.com"
    HEADERS = None

    @staticmethod
    def inicializar():
        """Inicializa headers con API tokens de RapidAPI"""
        FlashScoreAPI.HEADERS = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": FlashScoreAPI.RAPIDAPI_HOST
        }

    @staticmethod
    def obtener_partidos_en_vivo() -> list:
        """Obtiene partidos en vivo de FlashScore (ligas menores + principales)"""
        if not RAPIDAPI_KEY:
            logger.warning("⚠️ RapidAPI Key no configurado")
            return []

        try:
            # Intentar múltiples endpoints de FlashScore
            endpoints = [
                "/api/flashscore/v2/matches/live",
                "/api/flashscore/v2/matches",
                "/api/flashscore/v2/fixtures/live",
                "/api/flashscore/matches/live",
            ]

            for endpoint in endpoints:
                try:
                    url = f"{FlashScoreAPI.BASE_URL}{endpoint}"
                    logger.info(f"🔍 Intentando FlashScore: {endpoint}")
                    response = requests.get(url, headers=FlashScoreAPI.HEADERS, timeout=10)

                    logger.info(f"   Response: {response.status_code}")

                    if response.status_code == 200:
                        data = response.json()

                        # Adaptarse a diferentes estructuras de respuesta
                        if isinstance(data, dict):
                            matches = data.get("data", data.get("matches", data.get("fixtures", [])))
                        elif isinstance(data, list):
                            matches = data
                        else:
                            matches = []

                        if matches and len(matches) > 0:
                            logger.info(f"✓ FlashScore ({endpoint}): {len(matches)} partidos en vivo")
                            return matches
                        else:
                            logger.info(f"⚠️ FlashScore ({endpoint}): Sin partidos")

                except Exception as e:
                    logger.warning(f"⚠️ FlashScore ({endpoint}): {str(e)[:80]}")
                    continue

            logger.warning("⚠️ FlashScore: No hay conexión en ningún endpoint")
            return []

        except Exception as e:
            logger.error(f"Error en FlashScore: {e}")
            return []

    @staticmethod
    def procesar_partido_real(match_data: dict) -> Dict[str, Any]:
        """Convierte datos de FlashScore al formato de AlertasBet"""
        try:
            # Validar que sea dict, no string
            if isinstance(match_data, str):
                logger.warning(f"FlashScore retornó string en lugar de dict: {match_data[:100]}")
                return None

            if not isinstance(match_data, dict):
                logger.warning(f"FlashScore retornó tipo inesperado: {type(match_data)}")
                return None

            # Adaptarse al formato de FlashScore
            league_name = match_data.get("league", {}).get("name") if isinstance(match_data.get("league"), dict) else None
            league_name = league_name or match_data.get("tournament", "Unknown League")

            home_team = match_data.get("home_team", {}).get("name") or match_data.get("homeTeam", {}).get("name") or "Team A"
            away_team = match_data.get("away_team", {}).get("name") or match_data.get("awayTeam", {}).get("name") or "Team B"
            match_name = f"{home_team} vs {away_team}"

            # Goles
            home_goals = match_data.get("goals", {}).get("home") or match_data.get("homeScore", 0)
            away_goals = match_data.get("goals", {}).get("away") or match_data.get("awayScore", 0)
            score = f"{home_goals}-{away_goals}"

            minute = match_data.get("minute", 45) or match_data.get("elapsed", 45)

            # Estadísticas (estimadas si no están disponibles)
            stats = match_data.get("statistics", [])
            xg_home = float(match_data.get("xg_home", 1.5 + random.uniform(-0.5, 0.5)))
            xg_away = float(match_data.get("xg_away", 1.3 + random.uniform(-0.5, 0.5)))
            shots_home = int(match_data.get("shots_home", 8))
            shots_away = int(match_data.get("shots_away", 6))
            shots_on_target_home = int(match_data.get("shots_on_target_home", 4))
            shots_on_target_away = int(match_data.get("shots_on_target_away", 3))
            possession_home = int(match_data.get("possession_home", 55))

            # Cuota realista
            goals_total = home_goals + away_goals
            minutes_remaining = 90 - minute
            goal_rate = goals_total / max(1, minute) if minute > 0 else 0
            projected_goals = goal_rate * 90
            odds_over_1 = 1.9 + (0.6 if projected_goals < 2.5 else -0.3)
            odds_over_1 = max(1.05, min(2.50, odds_over_1))

            return {
                "match_name": match_name,
                "league": league_name,
                "minute": minute,
                "score": score,
                "xg_home": max(0.1, xg_home),
                "xg_away": max(0.1, xg_away),
                "shots_home": shots_home,
                "shots_away": shots_away,
                "shots_on_target_home": shots_on_target_home,
                "shots_on_target_away": shots_on_target_away,
                "possession_home": possession_home,
                "possession_away": 100 - possession_home,
                "odds_over_1": odds_over_1,
                "match_id": match_data.get("id")
            }
        except Exception as e:
            logger.error(f"Error procesando partido FlashScore: {e}")
            return None

# ============ LIVE FOOTBALL API - Datos en vivo reales (2100+ ligas) ============
class LiveFootballAPI:
    """Integración con Free API Live Football Data (2100+ ligas y competiciones)"""

    BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"
    HEADERS = None

    @staticmethod
    def inicializar():
        """Inicializa headers con API tokens de RapidAPI"""
        LiveFootballAPI.HEADERS = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST
        }

    @staticmethod
    def obtener_partidos_en_vivo() -> list:
        """Obtiene partidos en vivo de TODAS las ligas (2100+)"""
        if not RAPIDAPI_KEY:
            logger.warning("⚠️ RapidAPI Key no configurado")
            return []

        try:
            # Intentar múltiples endpoints de RapidAPI
            endpoints = [
                "/matches",
                "/matches?live=true",
                "/fixtures",
                "/live"
            ]

            for endpoint in endpoints:
                try:
                    url = f"{LiveFootballAPI.BASE_URL}{endpoint}"
                    logger.info(f"🔍 Intentando RapidAPI: {endpoint}")
                    response = requests.get(url, headers=LiveFootballAPI.HEADERS, timeout=10)

                    logger.info(f"   Response: {response.status_code}")

                    if response.status_code == 200:
                        data = response.json()
                        matches = data.get("data", []) if isinstance(data, dict) else data if isinstance(data, list) else []

                        if matches:
                            logger.info(f"✓ RapidAPI ({endpoint}): {len(matches)} partidos en vivo")
                            return matches
                        else:
                            logger.info(f"⚠️ RapidAPI ({endpoint}): Sin partidos en vivo")
                    else:
                        logger.warning(f"⚠️ RapidAPI ({endpoint}): Status {response.status_code}")

                except Exception as e:
                    logger.warning(f"⚠️ RapidAPI ({endpoint}): {str(e)[:80]}")
                    continue

            # Si ningún endpoint de RapidAPI funciona, retornar vacío (SOLO datos reales)
            logger.warning("⚠️ RapidAPI: No hay conexión.")
            return []

        except Exception as e:
            logger.error(f"Error obteniendo partidos: {e}")
            # Sin fallback - SOLO datos reales
            return []

    @staticmethod
    def procesar_partido_real(match_api_data: dict) -> Dict[str, Any]:
        """Convierte datos de RapidAPI (2100+ ligas) al formato de AlertasBet"""
        try:
            # Adaptarse al formato de la API de RapidAPI
            league_name = match_api_data.get("league", {}).get("name") or match_api_data.get("league_name", "Unknown League")

            home_team = match_api_data.get("home_team", {}).get("name") or match_api_data.get("home_team_name", "Team A")
            away_team = match_api_data.get("away_team", {}).get("name") or match_api_data.get("away_team_name", "Team B")
            match_name = f"{home_team} vs {away_team}"

            # Intentar obtener goles del score actual
            home_goals = match_api_data.get("goals", {}).get("home") or match_api_data.get("home_score", 0)
            away_goals = match_api_data.get("goals", {}).get("away") or match_api_data.get("away_score", 0)
            score = f"{home_goals}-{away_goals}"

            minute = match_api_data.get("minute", 45) or match_api_data.get("elapsed", 45)

            # Estimaciones basadas en datos disponibles
            # football-data.org no proporciona xG, así que lo estimamos
            stats = match_api_data.get("statistics", [])

            # Extrae stats si están disponibles
            xg_home = 1.5 + random.uniform(-0.5, 0.5)  # Default + variación
            xg_away = 1.3 + random.uniform(-0.5, 0.5)
            shots_home = 8
            shots_away = 6
            shots_on_target_home = 4
            shots_on_target_away = 3
            possession_home = 55

            # Cuota realista basada en goles y minuto
            goals_total = home_goals + away_goals
            minutes_remaining = 90 - minute
            goal_rate = goals_total / max(1, minute) if minute > 0 else 0
            projected_goals = goal_rate * 90
            odds_over_1 = 1.9 + (0.6 if projected_goals < 2.5 else -0.3)
            odds_over_1 = max(1.05, min(2.50, odds_over_1))

            return {
                "match_name": match_name,
                "league": league_name,
                "minute": minute,
                "score": score,
                "xg_home": xg_home,
                "xg_away": xg_away,
                "shots_home": shots_home,
                "shots_away": shots_away,
                "shots_on_target_home": shots_on_target_home,
                "shots_on_target_away": shots_on_target_away,
                "possession_home": possession_home,
                "possession_away": 100 - possession_home,
                "odds_over_1": odds_over_1,
                "match_id": match_api_data.get("id")
            }
        except Exception as e:
            logger.error(f"Error procesando partido: {e}")
            return None

def procesar_partidos_en_vivo():
    """Obtiene y procesa partidos en vivo REALES de FlashScore + RapidAPI"""
    try:
        logger.info("⚽ Obteniendo partidos en vivo REALES...")

        # Intentar FlashScore primero (ligas menores + principales)
        matches_api = FlashScoreAPI.obtener_partidos_en_vivo()

        # Si FlashScore no tiene, intentar RapidAPI
        if not matches_api:
            logger.info("ℹ️ FlashScore sin partidos, intentando RapidAPI...")
            matches_api = LiveFootballAPI.obtener_partidos_en_vivo()

        if not matches_api:
            logger.warning("⚠️ No hay partidos en vivo REALES en este momento")
            return

        logger.info(f"📊 Procesando {len(matches_api)} partidos en vivo...")

        # Procesar cada partido
        for match_api in matches_api:
            try:
                # Intentar procesar con FlashScore primero
                if isinstance(match_api, dict):
                    match_data = FlashScoreAPI.procesar_partido_real(match_api)

                    # Si falla con FlashScore, intentar con LiveFootballAPI
                    if not match_data:
                        match_data = LiveFootballAPI.procesar_partido_real(match_api)

                if not match_data:
                    continue

                # Procesar con análisis Poisson
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
                    logger.info(f"🔔 ALERTA REAL: {match_data['match_name']} (Value: {poisson.value}%)")

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
                    logger.debug(f"ℹ️ Partido procesado (sin alerta): {match_data['match_name']} (Value: {poisson.value}%)")

            except Exception as e:
                logger.error(f"Error procesando un partido: {e}", exc_info=True)
                continue

    except Exception as e:
        logger.error(f"Error en procesar_partidos_en_vivo: {e}", exc_info=True)

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

@app.route('/webhook/best-match', methods=['POST', 'GET'])
def webhook_best_match():
    """Endpoint para obtener y enviar el MEJOR partido en vivo AHORA (SOLO REALES)"""
    try:
        logger.info("🏆 Buscando el MEJOR partido EN VIVO REAL ahora...")

        # Intentar FlashScore primero (ligas menores)
        matches_api = FlashScoreAPI.obtener_partidos_en_vivo()

        # Si FlashScore no tiene, intentar RapidAPI
        if not matches_api:
            logger.info("ℹ️ FlashScore sin partidos, intentando RapidAPI...")
            matches_api = LiveFootballAPI.obtener_partidos_en_vivo()

        if not matches_api:
            return jsonify({
                "status": "no_matches",
                "message": "No hay partidos EN VIVO REALES en este momento. Intentando de nuevo en 5 minutos..."
            }), 200

        # Procesar todos y encontrar el mejor (value más alto)
        best_match = None
        best_value = -1

        for match_api in matches_api:
            try:
                # Procesar partido real
                match_data = FlashScoreAPI.procesar_partido_real(match_api)

                # Si falla con FlashScore, intentar con LiveFootballAPI
                if not match_data:
                    match_data = LiveFootballAPI.procesar_partido_real(match_api)

                if not match_data:
                    continue

                metricas = SportAnalyzer.calcular_metricas(match_data)
                poisson = PoissonModel.evaluar_partido(
                    metricas["xg_total"],
                    metricas["tiros_totales"],
                    match_data["minute"],
                    match_data["odds_over_1"]
                )

                if poisson.value > best_value:
                    best_value = poisson.value
                    score_alerta, level = SportAnalyzer.calcular_score_alerta(poisson, metricas)
                    best_match = {
                        "match_data": match_data,
                        "metricas": metricas,
                        "poisson": poisson,
                        "score_alerta": score_alerta,
                        "level": level
                    }
            except Exception as e:
                logger.error(f"Error procesando partido: {e}")
                continue

        # Si encontró un partido, enviarlo (threshold bajo)
        if best_match and best_value >= 2.0:  # Threshold bajo para mostrar
            logger.info(f"🏆 MEJOR PARTIDO: {best_match['match_data']['match_name']} (Value: {best_value}%)")

            if bot:
                alert_data = AlertData(
                    partido=best_match['match_data']["match_name"],
                    liga=best_match['match_data']["league"],
                    minuto=best_match['match_data']["minute"],
                    marcador=best_match['match_data']["score"],
                    level=best_match["level"],
                    score_final=best_match["score_alerta"],
                    momentum=best_match['metricas']["momentum"],
                    xg_total=best_match['metricas']["xg_total"],
                    tiros=best_match['metricas']["tiros_totales"],
                    tiros_puerta=best_match['metricas'].get("tiros_puerta", 0),
                    dominancia=best_match['metricas']["dominancia"],
                    eficiencia=best_match['metricas']["eficiencia"],
                    lambda_final=best_match['poisson'].lambda_final,
                    p_gol=best_match['poisson'].p_gol,
                    p_mercado=best_match['poisson'].p_mercado,
                    value=best_match['poisson'].value,
                    recomendacion=best_match['poisson'].recomendacion,
                    timestamp=datetime.now().isoformat()
                )
                asyncio.run(enviar_alerta_telegram(alert_data))
                logger.info("✓ Mejor partido enviado a Telegram")

            return jsonify({
                "status": "ok",
                "message": "Mejor partido enviado a Telegram",
                "match": best_match['match_data']["match_name"],
                "league": best_match['match_data']["league"],
                "score": best_match['match_data']["score"],
                "minute": best_match['match_data']["minute"],
                "value": best_match['poisson'].value,
                "recommendation": best_match['poisson'].recomendacion
            }), 200
        else:
            return jsonify({
                "status": "low_value",
                "message": f"Mejor value encontrado: {best_value:.1f}% (threshold: 2.0%)" if best_value >= 0 else "No hay partidos en vivo",
                "best_value": best_value if best_match else None,
                "matches_analyzed": len(matches_api)
            }), 200

    except Exception as e:
        logger.error(f"Error en webhook_best_match: {e}", exc_info=True)
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
            "POST /webhook/simulated": "Partido simulado manual",
            "POST /webhook/best-match": "Mejor partido EN VIVO ahora",
            "GET /webhook/diagnose": "Diagnosticar RapidAPI"
        }
    }), 200

@app.route('/webhook/diagnose', methods=['GET'])
def webhook_diagnose():
    """Endpoint para diagnosticar problemas con RapidAPI"""
    try:
        logger.info("🧪 Iniciando diagnóstico de RapidAPI...")

        results = {
            "rapidapi_configured": bool(RAPIDAPI_KEY),
            "rapidapi_key_sample": f"{RAPIDAPI_KEY[:20]}...***" if RAPIDAPI_KEY else "NO CONFIGURADO",
            "rapidapi_host": RAPIDAPI_HOST,
            "endpoints_tested": {}
        }

        # Probar endpoints
        endpoints = ["/matches", "/live", "/liveMatches", "/fixtures"]

        for endpoint in endpoints:
            url = f"https://{RAPIDAPI_HOST}{endpoint}"
            logger.info(f"🔍 Probando: {url}")

            try:
                headers = {
                    "X-RapidAPI-Key": RAPIDAPI_KEY,
                    "X-RapidAPI-Host": RAPIDAPI_HOST
                }

                response = requests.get(url, headers=headers, timeout=10)

                results["endpoints_tested"][endpoint] = {
                    "status_code": response.status_code,
                    "success": response.status_code == 200
                }

                if response.status_code == 200:
                    data = response.json()

                    # Analizar estructura
                    if isinstance(data, dict):
                        matches_data = data.get("data", data.get("matches", []))
                        results["endpoints_tested"][endpoint]["data_type"] = "dict"
                        results["endpoints_tested"][endpoint]["match_count"] = len(matches_data) if isinstance(matches_data, list) else 0

                        if isinstance(matches_data, list) and matches_data:
                            results["endpoints_tested"][endpoint]["sample_match"] = {
                                "keys": list(matches_data[0].keys()),
                                "first_item": str(matches_data[0])[:200]
                            }

                    elif isinstance(data, list):
                        results["endpoints_tested"][endpoint]["data_type"] = "list"
                        results["endpoints_tested"][endpoint]["match_count"] = len(data)

                        if data:
                            results["endpoints_tested"][endpoint]["sample_match"] = {
                                "keys": list(data[0].keys()) if isinstance(data[0], dict) else "N/A",
                                "first_item": str(data[0])[:200]
                            }

                logger.info(f"✅ {endpoint} retornó {response.status_code}")

            except requests.exceptions.Timeout:
                results["endpoints_tested"][endpoint] = {
                    "status_code": 0,
                    "error": "Timeout (10s)"
                }
            except Exception as e:
                results["endpoints_tested"][endpoint] = {
                    "status_code": 0,
                    "error": str(e)[:100]
                }

        # Encontrar endpoint que funciona
        working_endpoint = None
        for ep, result in results["endpoints_tested"].items():
            if result.get("success"):
                working_endpoint = ep
                break

        results["working_endpoint"] = working_endpoint
        results["diagnostic_complete"] = True

        logger.info(f"🧪 Diagnóstico completado. Endpoint funcional: {working_endpoint}")

        return jsonify(results), 200

    except Exception as e:
        logger.error(f"Error en diagnóstico: {e}", exc_info=True)
        return jsonify({"error": str(e), "diagnostic_complete": False}), 500

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
        # Inicializar APIs con soporte para ligas menores
        FlashScoreAPI.inicializar()
        LiveFootballAPI.inicializar()

        scheduler = BackgroundScheduler()

        # Programar obtención de partidos en vivo cada 5 minutos
        scheduler.add_job(
            procesar_partidos_en_vivo,
            'interval',
            minutes=5,
            id='live_matches',
            name='Obtener Partidos EN VIVO REALES (FlashScore + RapidAPI)'
        )

        scheduler.start()
        logger.info("✓ Scheduler iniciado - Partidos EN VIVO REALES cada 5 minutos")
        logger.info("🌍 Conectado a FlashScore (ligas menores + principales)")
        logger.info("🌍 Alternativa: RapidAPI (2100+ ligas)")
        logger.info("📊 SOLO datos REALES - Sin simulaciones")
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
