import sqlite3
from rapidfuzz import fuzz

#matching
def match_card(ocr_results, db_path = "data/carddata.db"):
	ocr_text = " ".join([x["cleaned"] for x in ocr_results 
	if x["confidence"] > 0.30]).upper()
	
	print("OCR Text: ", ocr_text)
	
	if not ocr_text:
		return {
			"best_match": None,
			"score": 0,
			"ocr_text": ""
		}

	#DB connection
	conn = sqlite3.connect(db_path)
	cursor = conn.cursor()

	rows = cursor.execute(
			"SELECT name FROM cards WHERE game= ?",
			("onepiece",)).fetchall()

	conn.close()
	
	best_match = None
	best_score = 0
	
	for row in rows:
		name = row[0].upper()
		score = fuzz.partial_ratio(ocr_text, name)
		
		if score > best_score:
			best_score = score
			best_match = row[0]
			
		return {
			"best match": best_match,
			"score": float(best_score),
			"ocr_text": ocr_text
		}

