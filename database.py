import sqlite3

DB_PATH = "data/carddata.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def get_cards_for_matching(game="onepiece"):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        rows = cursor.execute("""
                              SELECT cards.id, cards.namee, cards.normalized_name, sets.set_code
                              FROM cards
                              LEFT JOIN sets ON cards.set_id
                              WHERE cards.gamee = ?
                              """, (game,)).fetchall()
    return rows

def save_scan(image_path, raw_ocr_text, normalized_ocr_text, matched_card_id, match_score):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
                INSERT INTO scans (
                    image_path,
                    raw_ocr_text,
                    normalized_ocr_text,
                    matched_card_id,
                    match_score,
                    scan_time
                ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (image_path, raw_ocr_text, normalized_ocr_text, matched_card_id, match_score))
        conn.commit
