import os
import zlib
import base64
import re

def deobfuscate_step(content):
    if isinstance(content, str):
        content = content.encode('utf-8', errors='ignore')
    
    # Pattern: exec((_)(b'payload'))
    match = re.search(rb"exec\(\(_\)\(b'([^']+)'\)\)", content)
    if not match:
        return None
    
    payload = match.group(1)[::-1]
    try:
        decoded = base64.b64decode(payload)
        decompressed = zlib.decompress(decoded)
        return decompressed.decode('utf-8', errors='ignore')
    except Exception as e:
        return None

def fully_deobfuscate(content):
    current = content.decode('utf-8', errors='ignore')
    while True:
        next_step = deobfuscate_step(current.encode('utf-8', errors='ignore'))
        if next_step is None:
            break
        current = next_step
    return current

addon_path = r"C:\Users\Christian\AppData\Roaming\Kodi\addons\plugin.video.eagle.blvck"
lib_path = os.path.join(addon_path, "lib")
output_dir = r"c:\Users\Christian\Desktop\App\cbtv\deobfuscated_eagle"

if not os.path.exists(output_dir):
    os.makedirs(output_dir)

for root, dirs, files in os.walk(lib_path):
    for file in files:
        if file.endswith(".py"):
            full_path = os.path.join(root, file)
            with open(full_path, "rb") as f:
                content = f.read()
            
            final_code = fully_deobfuscate(content)
            
            out_path = os.path.join(output_dir, file)
            with open(out_path, "w", encoding="utf-8") as out:
                out.write(final_code)
            print(f"Deobfuscated: {file}")
