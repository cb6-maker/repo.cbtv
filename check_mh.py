import requests
import json

s = requests.Session()
s.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
})

# Analisi completa risposta API Britain
print("=== API BRITAIN - STRUTTURA COMPLETA ===")
r = s.get("https://api.screenify.shop/api/regions-mongodb/britain/extended", timeout=10)
d = r.json()
print(json.dumps(d, indent=2)[:3000])

# Cerca endpoint channels
print("\n=== CERCA ALTRI ENDPOINT ===")
for ep in ["channels", "streams", "sky-sport-2", "live", "token"]:
    url = f"https://api.screenify.shop/api/{ep}"
    try:
        r2 = s.get(url, timeout=3)
        print(f"  [{ep}] Status: {r2.status_code} | Bytes: {len(r2.text)}")
    except Exception as e:
        print(f"  [{ep}] Error: {e}")
