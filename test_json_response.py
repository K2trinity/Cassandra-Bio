"""测试Gemini JSON响应格式"""
import sys
sys.path.insert(0, r'f:\Visual Studio Code\Cassandra')

from src.llms.gemini_client import GeminiClient
import json

client = GeminiClient()
prompt = """Generate a simple JSON with fields: name, age. 
Example: {"name": "test", "age": 25}"""

print("🔄 Sending request to Gemini...")
response = client.generate_content(
    prompt=prompt,
    response_mime_type='application/json',
    max_output_tokens=500
)

print('\n=== RAW RESPONSE TYPE ===')
print(type(response))

print('\n=== RAW RESPONSE (repr) ===')
print(repr(response[:500]))

print('\n=== FIRST 500 CHARS ===')
print(response[:500])

print('\n=== TRYING TO PARSE AS JSON ===')
try:
    parsed = json.loads(response)
    print("✅ JSON parsed successfully!")
    print(json.dumps(parsed, indent=2))
except json.JSONDecodeError as e:
    print(f"❌ JSON parsing failed: {e}")
    print(f"Error position: {e.pos}")
    if e.pos < len(response):
        print(f"Error context: {response[max(0, e.pos-50):e.pos+50]}")
