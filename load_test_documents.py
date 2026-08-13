import json
import requests

with open("tests_data/kb_documents.jsonl", encoding="utf-8") as f:
    for line in f:
        doc = json.loads(line)
        response = requests.post("http://localhost:8000/kb/documents", json=doc)
        print(doc["title"], "->", response.status_code)

print("Готово")
