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
	result = reader.readtext(image_path)
	output = []
	
	for items in result:
		output.append({
			"raw": items[1],
			"cleaned": normalize(items[1]),
			"confidence": float(items[2])
		})
	return output
	
if __name__ == "__main__":
	print(extract_text("test.jpg"))
