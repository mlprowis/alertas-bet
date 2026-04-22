#!/usr/bin/env python3
import os, json, logging, asyncio
from datetime import datetime
from typing import Dict, Any
from dataclasses import dataclass
from enum import Enum
from flask import Flask, request, jsonify
from telegram import Bot
from telegram.error import TelegramError
import numpy as np

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PORT = int(os.getenv("PORT", 5000))

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.warning("TELEGRAM_TOKEN y TELEGRAM_CHAT_ID aun no configurados")

if TELEGRAM_TOKEN:
    bot = Bot(token=TELEGRAM_TOKEN)
else:
    bot = None

class PoissonModel:
    @staticmethod
    def calcular_lambda_base(xg_total: float, tiros_totales: int) -> float:
        if xg_total <= 0: return 0.5
        conversion_rate = min(tiros_totales / max(tiros_totales, 1), 1.0)
        return max(xg_total * (0.8 + 0.4 * conversion_rate), 0.1)

    @staticmethod
    def aplicar_factores(lambda_base: float, momentum: float = 1.0, eficiencia: float = 1.0, dominancia: float = 1.0, aceleracion: float = 1.0) -> float:
        return max(lambda_base * momentum * eficiencia * dominancia * aceleracion, 0.1)

    @staticmethod
    def aplicar_penalidad_minuto(lambda_valor: float, minuto: int) -> float:
        periodos_10min = minuto // 10
        return lambda_valor * (0.85 ** min(periodos_10min, 2))

    @staticmethod
    def calcular_probabilidad(lambda_valor: float) -> float:
        return 0.0 if lambda_valor <= 0 else 1 - np.exp(-lambda_valor)

    @staticmethod
    def calcular_value(p_modelo: float, p_mercado: float) -> float:
        return 0.0 if p_mercado <= 0 else (p_modelo - p_mercado) / p_mercado

    @classmethod
    def evaluar_partido(cls, xg_total: float, tiros_totales: int, minuto: int, cuota_over: float, momentum: float = 1.0, eficiencia: float = 1.0, dominancia: float = 1.0, aceleracion: float = 1.0) -> PoissonResult:
        lambda_base = cls.calcular_lambda_base(xg_total, tiros_totales)
        lambda_con_factores = cls.aplicar_factores(lambda_base, momentum, eficiencia, dominancia, aceleracion)
        lambda_final = cls.aplicar_penalidad_minuto(lambda_con_factores, minuto)
        p_gol = cls.calcular_probabilidad(lambda_final)
        p_mercado = 1 / cuota_over if cuota_over > 0 else 0.5
        value = cls.calcular_value(p_gol, p_mercado)
        recomendacion = "Over 1.0 Asiático ⭐⭐" if value >= 0.15 else "Over 1.0 Asiático" if value >= 0.08 else "Evaluar con cuidado"
        return PoissonResult(round(lambda_final, 3), round(p_gol * 100, 1), round(p_mercado * 100, 1), round(value * 100, 1), recomendacion)

class SportAnalyzer:
    @staticmethod
    def calcular_metricas(data: Dict[str, Any]) -> Dict[str, float]:
        try:
            xg_home = float(data.get("xg_home", 0))
            xg_away = float(data.get("xg_away", 0))
            xg_total = xg_home + xg_away
            tiros_totales = int(data.get("shots_home", 0)) + int(data.get("shots_away", 0))
            dominancia = max(float(data.get("possession_home", 50)), float(data.get("possession_away", 50))) / 100
            return {"xg_total": xg_total, "tiros_totales": tiros_totales, "dominancia": dominancia, "momentum": 1.0, "eficiencia": 1.0, "aceleracion": 1.0}
        except Exception as e:
            logger.error(f"Error: {e}")
            return {"xg_total": 0.5, "tiros_totales": 0, "dominancia": 0.5, "momentum": 1.0, "eficiencia": 1.0, "aceleracion": 1.0}

async def enviar_alerta_telegram(match_name: str, league: str, minute: int, score: str, poisson: PoissonResult, metricas: Dict) -> bool:
    if not bot:
        logger.warning("Bot no configurado")
        return False
    try:
        mensaje = f"🟠 ALERTA\n⚽ {match_name}\n📊 Liga: {league}\n🕐 Min: {minute}\n📈 Score: {score}\n\n🔬 POISSON:\nLambda: {poisson.lambda_final:.3f}\nP(Gol): {poisson.p_gol:.1f}%\n\n💰 VALUE: +{poisson.value:.1f}%\n✅ {poisson.recomendacion}"
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje)
        logger.info(f"Alerta: {match_name}")
        return True
    except TelegramError as e:
        logger.error(f"Error: {e}")
        return False

@app.route('/', methods=['GET'])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat(), "version": "1.0.0"}), 200

@app.route('/webhook/match', methods=['POST'])
def webhook_match():
    try:
        data = request.get_json()
        if not data: return jsonify({"error": "No data"}), 400
        metricas = SportAnalyzer.calcular_metricas(data)
        poisson = PoissonModel.evaluar_partido(metricas["xg_total"], metricas["tiros_totales"], int(data.get("minute", 0)), float(data.get("odds_over_1", 1.92)), metricas["momentum"], metricas["eficiencia"], metricas["dominancia"], metricas["aceleracion"])
        if poisson.value >= 8.0:
            if bot:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    success = loop.run_until_complete(enviar_alerta_telegram(data.get("match", "Unknown"), data.get("league", "Unknown"), int(data.get("minute", 0)), data.get("score", "0-0"), poisson, metricas))
                finally:
                    loop.close()
            else:
                success = False
            return jsonify({"status": "alert_sent" if success else "error", "value": poisson.value, "lambda": poisson.lambda_final}), 200
        return jsonify({"status": "no_alert", "value": poisson.value}), 200
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/test', methods=['POST'])
def webhook_test():
    try:
        test_data = {"match": "Test", "xg_home": 1.5, "xg_away": 0.9, "minute": 45, "odds_over_1": 1.92}
        metricas = SportAnalyzer.calcular_metricas(test_data)
        poisson = PoissonModel.evaluar_partido(metricas["xg_total"], metricas["tiros_totales"], 45, 1.92)
        return jsonify({"status": "ok", "value": poisson.value, "lambda": poisson.lambda_final}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"Iniciando en puerto {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
