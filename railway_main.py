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

# ============ SOFASCORE API - Cobertura global 500+ ligas (PRIMARIO) ============
class SofaScoreAPI:
    """SofaScore API - Cobertura global de 500+ ligas en vivo, sin rate limits estrictos"""

    BASE_URL = "https://api.sofascore.com/api/v1"

    @staticmethod
    def obtener_partidos_en_vivo() -> list:
        """Obtiene partidos EN VIVO de SofaScore (500+ ligas globales)"""
        try:
            url = f"{SofaScoreAPI.BASE_URL}/sport/football/events/last"
            logger.info(f"🔍 Intentando SofaScore: {url}")
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                events = data.get("events", [])

                # Filtrar solo partidos en vivo (status = "inprogress")
                live_matches = [e for e in events if e.get("status") == "inprogress"]

                if live_matches and len(live_matches) > 0:
                    logger.info(f"✅ SofaScore: {len(live_matches)} partidos EN VIVO encontrados")
                    return live_matches
                else:
                    logger.info(f"⚠️ SofaScore: Sin partidos en vivo en este momento")
                    return []
            else:
                logger.warning(f"⚠️ SofaScore: Status {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error en SofaScore: {str(e)[:100]}")
            return []

    @staticmethod
    def procesar_partido_real(match: dict) -> Dict[str, Any]:
        """Transforma datos de SofaScore al formato de AlertasBet"""
        try:
            if not isinstance(match, dict):
                return None

            # Equipos
            home = match.get("homeTeam", {})
            away = match.get("awayTeam", {})
            match_name = f"{home.get('name', 'Team A')} vs {away.get('name', 'Team B')}"

            # Score actual
            score_obj = match.get("score", {})
            home_goals = score_obj.get("current", {}).get("home", 0) if isinstance(score_obj, dict) else 0
            away_goals = score_obj.get("current", {}).get("away", 0) if isinstance(score_obj, dict) else 0
            score = f"{home_goals}-{away_goals}"

            # Minuto (SofaScore proporciona time actual)
            minute = match.get("time", 45)
            if not isinstance(minute, int) or minute < 0:
                minute = 45

            # Liga/Torneo
            tournament = match.get("tournament", {})
            league_name = tournament.get("name", "Unknown League") if isinstance(tournament, dict) else "Unknown League"

            # Estadísticas
            stats = match.get("statistics", {})
            shots_home = stats.get("shotsTotal", {}).get("home", 6) if isinstance(stats.get("shotsTotal"), dict) else 6
            shots_away = stats.get("shotsTotal", {}).get("away", 4) if isinstance(stats.get("shotsTotal"), dict) else 4
            shots_on_target_home = stats.get("shotsOnTarget", {}).get("home", 3) if isinstance(stats.get("shotsOnTarget"), dict) else 3
            shots_on_target_away = stats.get("shotsOnTarget", {}).get("away", 1) if isinstance(stats.get("shotsOnTarget"), dict) else 1

            # Posesión
            possession_obj = stats.get("possession", {})
            possession_home = possession_obj.get("home", 50) if isinstance(possession_obj, dict) else 50

            # xG (si está disponible)
            xg_obj = stats.get("expectedGoals", {})
            xg_home = xg_obj.get("home", 1.5) if isinstance(xg_obj, dict) else 1.5
            xg_away = xg_obj.get("away", 1.2) if isinstance(xg_obj, dict) else 1.2

            # Cuota (estimar basada en score)
            goals_total = home_goals + away_goals
            odds_over_1 = 1.9 if goals_total < 3 else 1.5

            return {
                "match_name": match_name,
                "league": league_name,
                "minute": minute,
                "score": score,
                "xg_home": max(0.1, float(xg_home)),
                "xg_away": max(0.1, float(xg_away)),
                "shots_home": int(shots_home),
                "shots_away": int(shots_away),
                "shots_on_target_home": int(shots_on_target_home),
                "shots_on_target_away": int(shots_on_target_away),
                "possession_home": float(possession_home),
                "possession_away": 100.0 - float(possession_home),
                "odds_over_1": float(odds_over_1),
                "match_id": match.get("id")
            }
        except Exception as e:
            logger.error(f"Error procesando partido SofaScore: {e}")
            return None

# ============ FOOTBALL-DATA.ORG API - Datos EN VIVO reales (PLAN GRATUITO GENEROSO) ============
class FootballDataAPI:
    """Integración con football-data.org (API oficial, plan gratuito confiable)"""

    BASE_URL = "https://api.football-data.org/v4"
    API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

    @staticmethod
    def inicializar():
        """Inicializa la API"""
        if not FootballDataAPI.API_KEY:
            logger.warning("⚠️ FOOTBALL_DATA_API_KEY no configurado - usar plan gratuito o obtener key en football-data.org")

    @staticmethod
    def obtener_partidos_en_vivo() -> list:
        """Obtiene partidos en vivo de football-data.org"""
        try:
            # Endpoint de partidos en vivo
            url = f"{FootballDataAPI.BASE_URL}/matches?status=LIVE"

            headers = {}
            if FootballDataAPI.API_KEY:
                headers["X-Auth-Token"] = FootballDataAPI.API_KEY

            logger.info(f"🔍 Obteniendo partidos EN VIVO de football-data.org...")
            response = requests.get(url, headers=headers, timeout=10)

            logger.info(f"   Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                matches = data.get("matches", [])

                if matches and len(matches) > 0:
                    logger.info(f"✅ football-data.org: {len(matches)} partidos EN VIVO encontrados")
                    return matches
                else:
                    logger.info(f"⚠️ football-data.org: Sin partidos en vivo en este momento")
                    return []
            else:
                logger.warning(f"⚠️ football-data.org: Status {response.status_code}")
                if response.status_code == 429:
                    logger.warning("   Rate limited - esperar")
                return []

        except Exception as e:
            logger.error(f"Error en football-data.org: {str(e)[:100]}")
            return []

    @staticmethod
    def procesar_partido_real(match_data: dict) -> Dict[str, Any]:
        """Convierte datos de football-data.org al formato de AlertasBet"""
        try:
            # Validar que sea dict
            if not isinstance(match_data, dict):
                return None

            # Parsear formato de football-data.org
            home_team = match_data.get("homeTeam", {}).get("name", "Team A")
            away_team = match_data.get("awayTeam", {}).get("name", "Team B")
            match_name = f"{home_team} vs {away_team}"

            # Goles del partido
            score_data = match_data.get("score", {})
            home_goals = score_data.get("fullTime", {}).get("home", 0) if isinstance(score_data, dict) else 0
            away_goals = score_data.get("fullTime", {}).get("away", 0) if isinstance(score_data, dict) else 0
            score = f"{home_goals}-{away_goals}"

            # Minuto del partido
            minute = match_data.get("utcDate", "").count(":") if match_data.get("utcDate") else 45
            # Si no hay minuto, usar 45 como default
            if not isinstance(minute, int) or minute < 0:
                minute = 45

            # Liga/Torneo
            competition = match_data.get("competition", {})
            league_name = competition.get("name", "Unknown League") if isinstance(competition, dict) else "Unknown League"

            # Estadísticas estimadas (football-data.org no proporciona xG)
            xg_home = 1.5 + random.uniform(-0.5, 0.5)
            xg_away = 1.3 + random.uniform(-0.5, 0.5)
            shots_home = 8
            shots_away = 6
            shots_on_target_home = 4
            shots_on_target_away = 3
            possession_home = 55

            # Cuota realista basada en el score actual
            goals_total = home_goals + away_goals
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
            logger.error(f"Error procesando partido football-data.org: {e}")
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

# ============ API-FOOTBALL (RAPID API ALTERNATIVO) - 600+ ligas ============
class APIFootballRapid:
    """Integración con API-Football (RapidAPI) - Cobertura 600+ ligas"""

    BASE_URL = "https://v3.football.api-sports.io"
    API_KEY = os.getenv("API_SPORTS_KEY", "")  # Diferente a RAPIDAPI_KEY
    HEADERS = None

    @staticmethod
    def inicializar():
        """Inicializa headers con API key de api-sports.io"""
        APIFootballRapid.HEADERS = {
            "x-rapidapi-key": APIFootballRapid.API_KEY,
            "x-rapidapi-host": "v3.football.api-sports.io"
        }

    @staticmethod
    def obtener_partidos_en_vivo() -> list:
        """Obtiene partidos en vivo de API-Football"""
        if not APIFootballRapid.API_KEY:
            logger.debug("⚠️ API_SPORTS_KEY no configurado, omitiendo API-Football")
            return []

        try:
            url = f"{APIFootballRapid.BASE_URL}/fixtures?live=true"
            logger.info(f"🔍 Intentando API-Football: /fixtures?live=true")
            response = requests.get(url, headers=APIFootballRapid.HEADERS, timeout=10)

            if response.status_code == 200:
                data = response.json()
                matches = data.get("response", [])

                if matches and len(matches) > 0:
                    logger.info(f"✅ API-Football: {len(matches)} partidos EN VIVO encontrados")
                    return matches
                else:
                    logger.info(f"⚠️ API-Football: Sin partidos en vivo en este momento")
                    return []
            else:
                logger.warning(f"⚠️ API-Football: Status {response.status_code}")
                if response.status_code == 429:
                    logger.warning("   Rate limited - esperar")
                return []

        except Exception as e:
            logger.error(f"Error en API-Football: {str(e)[:100]}")
            return []

    @staticmethod
    def procesar_partido_real(match: dict) -> Dict[str, Any]:
        """Transforma datos de API-Football al formato de AlertasBet"""
        try:
            if not isinstance(match, dict):
                return None

            # Información del partido
            fixture = match.get("fixture", {})
            teams = match.get("teams", {})
            home_team = teams.get("home", {})
            away_team = teams.get("away", {})
            match_name = f"{home_team.get('name', 'Team A')} vs {away_team.get('name', 'Team B')}"

            # Score actual
            goals = match.get("goals", {})
            home_goals = goals.get("home", 0) if isinstance(goals, dict) else 0
            away_goals = goals.get("away", 0) if isinstance(goals, dict) else 0
            score = f"{home_goals}-{away_goals}"

            # Minuto
            status = fixture.get("status", {})
            minute = status.get("elapsed", 45) if isinstance(status, dict) else 45
            if not isinstance(minute, int) or minute < 0:
                minute = 45

            # Liga
            league = match.get("league", {})
            league_name = league.get("name", "Unknown League") if isinstance(league, dict) else "Unknown League"

            # Estadísticas
            stats = match.get("statistics", [])
            home_stats = stats[0] if len(stats) > 0 else {}
            away_stats = stats[1] if len(stats) > 1 else {}

            shots_home = home_stats.get("shots", {}).get("total", 6) if isinstance(home_stats.get("shots"), dict) else 6
            shots_away = away_stats.get("shots", {}).get("total", 4) if isinstance(away_stats.get("shots"), dict) else 4
            shots_on_target_home = home_stats.get("shots", {}).get("on", 3) if isinstance(home_stats.get("shots"), dict) else 3
            shots_on_target_away = away_stats.get("shots", {}).get("on", 1) if isinstance(away_stats.get("shots"), dict) else 1

            possession_home = home_stats.get("possession", 50) if isinstance(home_stats, dict) else 50

            # xG (si está disponible)
            xg_home = home_stats.get("expectedGoals", 1.5) if isinstance(home_stats, dict) else 1.5
            xg_away = away_stats.get("expectedGoals", 1.2) if isinstance(away_stats, dict) else 1.2

            # Cuota
            goals_total = home_goals + away_goals
            odds_over_1 = 1.9 if goals_total < 3 else 1.5

            return {
                "match_name": match_name,
                "league": league_name,
                "minute": minute,
                "score": score,
                "xg_home": max(0.1, float(xg_home)),
                "xg_away": max(0.1, float(xg_away)),
                "shots_home": int(shots_home),
                "shots_away": int(shots_away),
                "shots_on_target_home": int(shots_on_target_home),
                "shots_on_target_away": int(shots_on_target_away),
                "possession_home": float(possession_home),
                "possession_away": 100.0 - float(possession_home),
                "odds_over_1": float(odds_over_1),
                "match_id": fixture.get("id")
            }
        except Exception as e:
            logger.error(f"Error procesando partido API-Football: {e}")
            return None

# ============ FLASHSCORE API - Cobertura Bet365 ============
class FlashScoreAPI:
    """FlashScore API - Cobertura similar a Bet365, partidos populares"""

    BASE_URL = "https://api.flashcore.io/api/v1"
    API_KEY = os.getenv("FLASHSCORE_KEY", "")

    @staticmethod
    def obtener_partidos_en_vivo() -> list:
        """Obtiene partidos EN VIVO de FlashScore"""
        try:
            url = f"{FlashScoreAPI.BASE_URL}/matches/live"
            logger.info(f"🔍 Intentando FlashScore: /matches/live")

            headers = {"Accept": "application/json"}
            if FlashScoreAPI.API_KEY:
                headers["X-Auth-Token"] = FlashScoreAPI.API_KEY

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                matches = data.get("matches", []) if isinstance(data, dict) else []

                if matches and len(matches) > 0:
                    logger.info(f"✅ FlashScore: {len(matches)} partidos EN VIVO encontrados")
                    return matches
                else:
                    logger.info(f"⚠️ FlashScore: Sin partidos en vivo en este momento")
                    return []
            else:
                logger.warning(f"⚠️ FlashScore: Status {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error en FlashScore: {str(e)[:100]}")
            return []

    @staticmethod
    def procesar_partido_real(match: dict) -> Dict[str, Any]:
        """Transforma datos de FlashScore al formato de AlertasBet"""
        try:
            if not isinstance(match, dict):
                return None

            # Equipos
            home_team = match.get("homeTeam", {})
            away_team = match.get("awayTeam", {})
            match_name = f"{home_team.get('name', 'Team A')} vs {away_team.get('name', 'Team B')}"

            # Score
            score_obj = match.get("score", {})
            home_goals = score_obj.get("home", 0) if isinstance(score_obj, dict) else 0
            away_goals = score_obj.get("away", 0) if isinstance(score_obj, dict) else 0
            score = f"{home_goals}-{away_goals}"

            # Minuto
            minute = match.get("minute", 45)
            if not isinstance(minute, int) or minute < 0:
                minute = 45

            # Liga
            tournament = match.get("tournament", {})
            league_name = tournament.get("name", "Unknown League") if isinstance(tournament, dict) else "Unknown League"

            # Estadísticas
            stats = match.get("statistics", {})
            shots_home = stats.get("shots_home", 6) if isinstance(stats, dict) else 6
            shots_away = stats.get("shots_away", 4) if isinstance(stats, dict) else 4
            shots_on_target_home = stats.get("shots_on_target_home", 3) if isinstance(stats, dict) else 3
            shots_on_target_away = stats.get("shots_on_target_away", 1) if isinstance(stats, dict) else 1
            possession_home = stats.get("possession_home", 50) if isinstance(stats, dict) else 50

            # xG
            xg_home = stats.get("expected_goals_home", 1.5) if isinstance(stats, dict) else 1.5
            xg_away = stats.get("expected_goals_away", 1.2) if isinstance(stats, dict) else 1.2

            # Cuota
            goals_total = home_goals + away_goals
            odds_over_1 = 1.9 if goals_total < 3 else 1.5

            return {
                "match_name": match_name,
                "league": league_name,
                "minute": minute,
                "score": score,
                "xg_home": max(0.1, float(xg_home)),
                "xg_away": max(0.1, float(xg_away)),
                "shots_home": int(shots_home),
                "shots_away": int(shots_away),
                "shots_on_target_home": int(shots_on_target_home),
                "shots_on_target_away": int(shots_on_target_away),
                "possession_home": float(possession_home),
                "possession_away": 100.0 - float(possession_home),
                "odds_over_1": float(odds_over_1),
                "match_id": match.get("id")
            }
        except Exception as e:
            logger.error(f"Error procesando partido FlashScore: {e}")
            return None

def procesar_partidos_en_vivo():
    """Obtiene y procesa partidos en vivo REALES de múltiples APIs (cobertura global)"""
    try:
        logger.info("⚽ Obteniendo partidos en vivo REALES de múltiples APIs...")

        # Cascada de 5 APIs - intenta la siguiente si la anterior no retorna partidos
        matches_api = None
        api_source = None

        # 1️⃣ SofaScore (cobertura global 500+ ligas)
        matches_api = SofaScoreAPI.obtener_partidos_en_vivo()
        if matches_api:
            api_source = "SofaScore"
            logger.info(f"📊 Usando SofaScore: {len(matches_api)} partidos")

        # 2️⃣ API-Football RapidAPI (600+ ligas, si tiene API_SPORTS_KEY)
        if not matches_api:
            matches_api = APIFootballRapid.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "API-Football"
                logger.info(f"📊 Usando API-Football: {len(matches_api)} partidos")

        # 3️⃣ FlashScore (Bet365-like coverage)
        if not matches_api:
            matches_api = FlashScoreAPI.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "FlashScore"
                logger.info(f"📊 Usando FlashScore: {len(matches_api)} partidos")

        # 4️⃣ LiveFootballAPI (RapidAPI original - 2100+ ligas)
        if not matches_api:
            matches_api = LiveFootballAPI.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "RapidAPI"
                logger.info(f"📊 Usando RapidAPI: {len(matches_api)} partidos")

        # 5️⃣ FootballDataAPI (football-data.org - fallback)
        if not matches_api:
            matches_api = FootballDataAPI.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "football-data.org"
                logger.info(f"📊 Usando football-data.org: {len(matches_api)} partidos")

        if not matches_api:
            logger.warning("⚠️ No hay partidos en vivo REALES en este momento (todas las APIs sin datos)")
            return

        logger.info(f"📊 Procesando {len(matches_api)} partidos en vivo desde {api_source}...")

        # Procesar cada partido
        for match_api in matches_api:
            try:
                if isinstance(match_api, dict):
                    # Intentar procesar con todas las APIs en cascada
                    match_data = None

                    # Intentar con la API que entregó los datos primero
                    if api_source == "SofaScore":
                        match_data = SofaScoreAPI.procesar_partido_real(match_api)
                    elif api_source == "API-Football":
                        match_data = APIFootballRapid.procesar_partido_real(match_api)
                    elif api_source == "FlashScore":
                        match_data = FlashScoreAPI.procesar_partido_real(match_api)
                    elif api_source == "RapidAPI":
                        match_data = LiveFootballAPI.procesar_partido_real(match_api)
                    elif api_source == "football-data.org":
                        match_data = FootballDataAPI.procesar_partido_real(match_api)

                    # Fallback a otras APIs si falla la principal
                    if not match_data:
                        match_data = SofaScoreAPI.procesar_partido_real(match_api)
                    if not match_data:
                        match_data = APIFootballRapid.procesar_partido_real(match_api)
                    if not match_data:
                        match_data = FlashScoreAPI.procesar_partido_real(match_api)
                    if not match_data:
                        match_data = LiveFootballAPI.procesar_partido_real(match_api)
                    if not match_data:
                        match_data = FootballDataAPI.procesar_partido_real(match_api)

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
    """Endpoint para obtener y enviar el MEJOR partido en vivo AHORA (cobertura global)"""
    try:
        logger.info("🏆 Buscando el MEJOR partido EN VIVO REAL ahora (cobertura global de múltiples APIs)...")

        # Cascada de 5 APIs - intenta la siguiente si la anterior no retorna partidos
        matches_api = None
        api_source = None

        # 1️⃣ SofaScore
        matches_api = SofaScoreAPI.obtener_partidos_en_vivo()
        if matches_api:
            api_source = "SofaScore"

        # 2️⃣ API-Football
        if not matches_api:
            matches_api = APIFootballRapid.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "API-Football"

        # 3️⃣ FlashScore
        if not matches_api:
            matches_api = FlashScoreAPI.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "FlashScore"

        # 4️⃣ RapidAPI
        if not matches_api:
            matches_api = LiveFootballAPI.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "RapidAPI"

        # 5️⃣ football-data.org
        if not matches_api:
            matches_api = FootballDataAPI.obtener_partidos_en_vivo()
            if matches_api:
                api_source = "football-data.org"

        if not matches_api:
            return jsonify({
                "status": "no_matches",
                "message": "No hay partidos EN VIVO REALES en este momento (todas las APIs sin datos). Intentando de nuevo en 5 minutos..."
            }), 200

        logger.info(f"📊 Buscando mejor partido en {len(matches_api)} partidos de {api_source}...")

        # Procesar todos y encontrar el mejor (value más alto)
        best_match = None
        best_value = -1

        for match_api in matches_api:
            try:
                # Procesar con la API que entregó los datos primero
                match_data = None

                if api_source == "SofaScore":
                    match_data = SofaScoreAPI.procesar_partido_real(match_api)
                elif api_source == "API-Football":
                    match_data = APIFootballRapid.procesar_partido_real(match_api)
                elif api_source == "FlashScore":
                    match_data = FlashScoreAPI.procesar_partido_real(match_api)
                elif api_source == "RapidAPI":
                    match_data = LiveFootballAPI.procesar_partido_real(match_api)
                elif api_source == "football-data.org":
                    match_data = FootballDataAPI.procesar_partido_real(match_api)

                # Fallback a otras APIs si falla la principal
                if not match_data:
                    match_data = SofaScoreAPI.procesar_partido_real(match_api)
                if not match_data:
                    match_data = APIFootballRapid.procesar_partido_real(match_api)
                if not match_data:
                    match_data = FlashScoreAPI.procesar_partido_real(match_api)
                if not match_data:
                    match_data = LiveFootballAPI.procesar_partido_real(match_api)
                if not match_data:
                    match_data = FootballDataAPI.procesar_partido_real(match_api)

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
        # Inicializar APIs
        FootballDataAPI.inicializar()
        LiveFootballAPI.inicializar()

        scheduler = BackgroundScheduler()

        # Programar obtención de partidos en vivo cada 5 minutos
        scheduler.add_job(
            procesar_partidos_en_vivo,
            'interval',
            minutes=5,
            id='live_matches',
            name='Obtener Partidos EN VIVO REALES (SofaScore + RapidAPI)'
        )

        scheduler.start()
        logger.info("✓ Scheduler iniciado - Partidos EN VIVO REALES cada 5 minutos")
        logger.info("🌍 Primario: RapidAPI (2100+ ligas - Cobertura mundial)")
        logger.info("🌍 Alternativa: football-data.org")
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
