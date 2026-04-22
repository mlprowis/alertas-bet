from flask import Flask, jsonify, request
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "ok"}), 200

@app.route('/webhook/test', methods=['POST'])
def test():
    return jsonify({"status": "ok", "value": 20.0}), 200

@app.route('/webhook/match', methods=['POST'])
def match():
    return jsonify({"status": "received"}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"Starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
