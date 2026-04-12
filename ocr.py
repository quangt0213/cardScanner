import easyocr
import re

#create OCR reader (loads model into memory)
reader = easyocr.Reader(['en'], gpu=False)

#clean strings
def normalize(text):
	text = text.upper()
	text = re.sub(r'[^A-Z0-9/\- ]', '', text)
	return text.strip()

def extract_text(image_path):
	result = reader.readText(image_path)
	cleaned = []
	
	for detection in result:
		text = detection[1]
		confidence = detection[2]
		cleaned.append({
			"raw": text,
			"cleaned": normalize(text),
			"confidence": float(confidence)
		})
	return cleaned
	
if __name__ == "__main__":
	output = extract_text("test.jpg")
	print(output)
