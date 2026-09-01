import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from extractor import extract_document_with_metadata

dest = r"C:\Users\feras\Documents\Projects\Bid-Intelligence\tests\fixtures\local\bank_of_canada_2026_026"

manifest = []
for root, dirs, files in os.walk(dest):
    for f in sorted(files):
        fpath = os.path.join(root, f)
        rel_path = os.path.relpath(fpath, dest).replace("\\", "/")
        size = os.path.getsize(fpath)
        ext = os.path.splitext(f)[1].lower()
        with open(fpath, "rb") as fp:
            data = fp.read()
        try:
            text, meta = extract_document_with_metadata(data, rel_path)
            parsed = True
            chars = len(text)
        except Exception as e:
            parsed = False
            meta = {"error": str(e)}
            chars = 0
        manifest.append({
            "filename": rel_path,
            "type": ext,
            "size_bytes": size,
            "parsed_successfully": parsed,
            "char_count": chars,
            "metadata": meta
        })

def _default_serializer(obj):
    if isinstance(obj, set):
        return sorted(list(obj))
    return str(obj)

os.makedirs(r"C:\Users\feras\Documents\Projects\Bid-Intelligence\tests\acceptance", exist_ok=True)
with open(r"C:\Users\feras\Documents\Projects\Bid-Intelligence\tests\acceptance\manifest_data.json", "w", encoding="utf-8") as out:
    json.dump(manifest, out, indent=2, default=_default_serializer)

print("Manifest data generated successfully for", len(manifest), "files.")
