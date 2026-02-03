
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
    parent_folder = os.path.dirname(source_dir)
    addon_id = os.path.basename(source_dir)
    
    with zipfile.ZipFile(output_zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.endswith('.zip') or file.endswith('.pyc') or '.git' in root:
                    continue
                abs_path = os.path.join(root, file)
                # Forza il percorso interno a iniziare con addon_id/
                rel_path = os.path.relpath(abs_path, parent_folder)
                zipf.write(abs_path, rel_path)
    return output_zip_name

def build():
    xml = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<addons>\n"
    addons = ["repository.cbtv", "plugin.video.cbtv"]
    
    created_files = []  # Track created files
    
    for addon_id in addons:
        addon_xml_path = os.path.join(addon_id, "addon.xml")
        if not os.path.exists(addon_xml_path):
            continue
            
        with open(addon_xml_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Estrai versione
        version_match = re.search(r'<addon[^>]+version="([^"]+)"', content)
        version = version_match.group(1) if version_match else "1.0.0"
        
        # Crea ZIP FLAT (nella cartella principale per caricamento facile)
        zip_filename = f"{addon_id}-{version}.zip"
        make_zip_flat(addon_id, zip_filename)
        created_files.append(zip_filename)  # Save for later
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

if __name__ == "__main__":
    build()
