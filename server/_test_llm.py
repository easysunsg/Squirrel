"""Test LLM endpoint connectivity"""
import httpx
import json

api_key = "sk-QyePZyoohF9ZeMTc8we118o2y5NaedUWw8HMz9ldTrFT2WUF"
base_url = "http://43.130.246.3:3000/v1"

print("=== Test 1: API key validity ===")
try:
    r = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "deepseek-v4-flash",
            "messages": [{"role": "user", "content": "say hello"}],
            "temperature": 0.1,
        },
        timeout=15,
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Response: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
    else:
        print(f"Body: {r.text[:500]}")
except httpx.TimeoutException:
    print("TIMEOUT: Server not reachable")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

print("\n=== Test 2: List models ===")
try:
    r = httpx.get(
        f"{base_url}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text[:500]}")
except httpx.TimeoutException:
    print("TIMEOUT")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
