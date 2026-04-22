import os
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "Bot running"}), 200

@app.route('/webhook/match', methods=['POST'])
def webhook():
    return jsonify({"status": "received"}), 200

@app.route('/webhook/test', methods=['POST'])
def test():
    return jsonify({"status": "test_ok"}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
