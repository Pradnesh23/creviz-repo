import json
import urllib.request
import os
from jsonschema import validate, Draft202012Validator
from jsonschema.exceptions import ValidationError

SCHEMA_DIR = r"c:\Users\prads\OneDrive\Desktop\creviz\letta\schemas"
API_URL_KEYS = "http://localhost:5001/api/keys"

def remove_refs(obj):
    if isinstance(obj, dict):
        obj.pop("$ref", None)
        for k, v in obj.items():
            remove_refs(v)
    elif isinstance(obj, list):
        for item in obj:
            remove_refs(item)
    return obj

def load_schema(filename):
    path = os.path.join(SCHEMA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
        return remove_refs(schema)

def main():
    test_key = "metadata:03bae632-9d0d-c91e-581f-189e912cc4a9"
    print(f"Testing with specific key: {test_key}")
    
    req = urllib.request.Request(f"http://localhost:5001/api/metadata/{test_key}")
    with urllib.request.urlopen(req) as response:
        metadata = json.loads(response.read().decode())
        
    app_obj = metadata.get("content", {}).get("application", metadata)
    
    app_schema = load_schema("Application.json")
    page_schema = load_schema("Page.json")
    form_schema = load_schema("Form.json")
    
    print("\n--- Validating Application ---")
    validator = Draft202012Validator(app_schema)
    errors = sorted(validator.iter_errors(app_obj), key=lambda e: e.path)
    if not errors:
        print("Application schema: VALID")
    else:
        print("Application schema: INVALID")
        for error in errors:
            print(f"  - {error.message} at {list(error.path)}")
            
    pages = app_obj.get("pages", [])
    print(f"\n--- Validating Pages ({len(pages)}) ---")
    for i, page in enumerate(pages):
        validator = Draft202012Validator(page_schema)
        errors = sorted(validator.iter_errors(page), key=lambda e: e.path)
        if not errors:
            print(f"  Page {i} ({page.get('name')}): VALID")
        else:
            print(f"  Page {i} ({page.get('name')}): INVALID")
            for error in errors:
                print(f"    - {error.message} at {list(error.path)}")
                
        forms = page.get("forms", [])
        print(f"\n  --- Validating Forms on Page {i} ({len(forms)}) ---")
        for j, form in enumerate(forms):
            validator = Draft202012Validator(form_schema)
            errors = sorted(validator.iter_errors(form), key=lambda e: e.path)
            if not errors:
                print(f"    Form {j} ({form.get('name')}): VALID")
            else:
                print(f"    Form {j} ({form.get('name')}): INVALID")
                for error in errors:
                    print(f"      - {error.message} at {list(error.path)}")

if __name__ == "__main__":
    main()
