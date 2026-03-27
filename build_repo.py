
import os
import hashlib
import zipfile
import re

# Configurazione
GITHUB_USERNAME = "cb6-maker" 
REPO_NAME = "repo.cbtv"

def get_md5(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def make_zip_flat(source_dir, output_zip_name):
    """Crea uno zip con la cartella radice corretta per Kodi."""
    source_dir = os.path.abspath(source_dir)
    # parent_folder = os.path.dirname(source_dir) # OLD
    # Per Kodi, lo zip deve contenere una cartella con il nome dell'addon id
    
    addon_id = os.path.basename(source_dir)
    
    with zipfile.ZipFile(output_zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                # Escludi file inutili e zip ricorsivi
                if file.endswith('.zip') or file.endswith('.pyc') or '.git' in root or '__pycache__' in root:
                    continue
                
                abs_path = os.path.join(root, file)
                
                # Calcola percorso relativo rispetto alla cartella in cui siamo
                # Esempio: root = C:\...\plugin.video.streamphis_test
                # rel_path = .
                rel_from_source = os.path.relpath(abs_path, source_dir)
                
                # Nello zip vogliamo: plugin.video.streamphis_test/addon.xml
                zip_path = os.path.join(addon_id, rel_from_source)
                
                zipf.write(abs_path, zip_path)
    return output_zip_name

def build(target_addon=None):
    xml = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<addons>\n"
    all_addons = ["repository.cbtv", "plugin.video.cbtv"]
    
    # Se specificato un target, costruiamo zip solo di quello, ma regeneriamo comunque addons.xml completo
    
    created_files = []  # Track created files
    
    for addon_id in all_addons:
        addon_xml_path = os.path.join(addon_id, "addon.xml")
        if not os.path.exists(addon_xml_path):
            continue
            
        with open(addon_xml_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Estrai versione
        version_match = re.search(r'<addon[^>]+version="([^"]+)"', content)
        version = version_match.group(1) if version_match else "1.0.0"
        
        # Se target_addon è specificato, saltiamo la creazione zip per gli altri
        if target_addon and target_addon != addon_id:
             pass # Skip zip creation
        else:
            # Crea ZIP FLAT
            zip_filename = f"{addon_id}-{version}.zip"
            make_zip_flat(addon_id, zip_filename)
            created_files.append(zip_filename)
            print(f"Creato file zip pronto per l'upload: {zip_filename}")
        
        # Componi addons.xml
        lines = content.split('\n')
        if lines[0].startswith("<?xml"):
            content = "\n".join(lines[1:])
        xml += content.strip() + "\n"
        
    xml += "</addons>\n"
    
    with open("addons.xml", "w", encoding="utf-8") as f:
        f.write(xml)
    
    md5_hash = get_md5("addons.xml")
    with open("addons.xml.md5", "w", encoding="utf-8") as f:
        f.write(md5_hash)
        
    print("\n[OK] Tutto generato! Ora carica questi FILE SINGOLI su GitHub:")
    print("1. addons.xml")
    print("2. addons.xml.md5")
    print("3. config.json")
    for i, fname in enumerate(created_files, start=4):
        print(f"{i}. {fname}")

    # Genera index.html per navigazione facile
    print("Generazione index.html...")
    html = """<html>
<head><title>CB TV Repo</title></head>
<body>
<h1>CB TV Repository</h1>
<ul>
<li><a href="addons.xml">addons.xml</a></li>
<li><a href="addons.xml.md5">addons.xml.md5</a></li>
"""
    # Ordina i file per avere prima la repo, poi i plugin
    files_sorted = sorted(created_files)
    
    for z in files_sorted:
        if "repository.cbtv" in z:
             # Repo zip -> linkiamo alla ROOT per facilitare l'installazione manuale
             # IMPORTANTE: L'utente deve copiare questo zip anche nella root!
             html += f'<li><a href="{z}">{z}</a></li>\n'
        elif "plugin.video.cbtv" in z:
             # Plugin zip -> nella cartella plugin.video.cbtv/ (questo lo gestisce Kodi in automatico dopo)
             html += f'<li><a href="{z}">{z}</a></li>\n'
    
    html += """</ul>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else None
    build(target)
