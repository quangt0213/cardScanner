from flask import Flask, request, jsonify
from pathlib import Path
from datetime import datetime
from ocr import extract_text
from matching import match_card
from database import save_scan

app = Flask(__name__)
SCAN_DIR = Path("scans")
SCAN_DIR.mkdir(exist_ok=True)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/scan", methods=["POST"])
def scan():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400
    
    file = request.files["image"]
    
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400
    
    filename = datetime.now().strftime("%Y%m%d_%H%M%S.jpg)")
    image_path = SCAN_DIR / filename
    file.save(image_path)
    
    ocr_results = extract_text(str(image_path))
    match_result = match_card(ocr_results, game="onepiece")
    
    matched_card_id = None
    match_score = 0.0
    Min_score = 70.0
    
    if match_result is not None and match_result.get("best_match") is not None:
        matched_card_id = match_result["best_match"].get("card_id")
        match_score = match_result["best_match"].get("score", 0.0)
 
    best = match_result.get("best_match")
    
    if best is not None and best.get("score", 0.0) < Min_score:
        match_result["best_match"] = None
        
    save_scan(
        str(image_path),
        match_result["raw_ocr_text"],
        match_result["normalized_ocr_text"],
        matched_card_id,
        match_score
    )
    
    return jsonify(match_result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
