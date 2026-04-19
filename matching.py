from database import get_cards_for_matching
from rapidfuzz import fuzz

#matching
def match_card(ocr_results, game="onepiece"):
	raw_text = " ".join([x["raw"] for x in ocr_results])
	normalized_text = " ".join([x["cleaned"] for x in ocr_results if x["confidence"] > 0.30])
	
	cards = get_cards_for_matching(game)	
 
	best_match = None
	best_score = 0
	
	for card_id, name, normalized_name, set_code in cards:
		score = fuzz.partial_ratio(normalized_text, normalized_name)
		
		if score > best_score:
			best_score = score
			best_match = {
				"card_id": card_id,
				"name": name,
				"set_code": set_code,
				"score": float(score)
            }
			
		return {
			"raw_ocr_text": raw_text,
			"normalized_ocr_text": normalized_text,
			"best_match": best_match
		}
