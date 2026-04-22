from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "ok"}), 200

@app.route('/webhook/match', methods=['POST'])
def webhook():
    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
