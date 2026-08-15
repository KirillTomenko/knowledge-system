import json
import sys

import requests

# Defaults to local dev server. To load documents into a deployed instance
# instead, pass the base URL as an argument — no need to edit this file:
#   python load_test_documents.py https://your-app.onrender.com
base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

with open("tests_data/kb_documents.jsonl", encoding="utf-8") as f:
    for line in f:
        doc = json.loads(line)
        response = requests.post(f"{base_url}/kb/documents", json=doc)
        print(doc["title"], "->", response.status_code)

print("Готово")