#!/bin/bash
# Costruisce la repository usando strumenti nativi macOS (bash, zip, md5)

echo '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' > addons.xml
echo '<addons>' >> addons.xml

html="<html>\n<head><title>CB TV Repo</title></head>\n<body>\n<h1>CB TV Repository</h1>\n<ul>\n"
html+="<li><a href=\"addons.xml\">addons.xml</a></li>\n"
html+="<li><a href=\"addons.xml.md5\">addons.xml.md5</a></li>\n"

for addon in repository.cbtv plugin.video.cbtv; do
  if [ -f "$addon/addon.xml" ]; then
    # Estrai versione
    version=$(grep -E '^<addon' "$addon/addon.xml" | grep -oE 'version="[^"]+"' | cut -d'"' -f2)
    zip_name="${addon}-${version}.zip"
    
    echo "Zipping $addon to $zip_name ..."
    rm -f "${addon}-"*.zip
    zip -r "$zip_name" "$addon" -x "*/.git/*" "*/__pycache__/*" "*.pyc" "*.zip" "*/\.*" > /dev/null
    
    html+="<li><a href=\"$zip_name\">$zip_name</a></li>\n"
    
    # Aggiungi contenuto xml
    grep -v "<?xml" "$addon/addon.xml" >> addons.xml
    echo "" >> addons.xml
  fi
done

echo '</addons>' >> addons.xml

# Genera md5 (nativamente su macOS si usa \`md5\`)
md5 -q addons.xml > addons.xml.md5

html+="</ul>\n</body>\n</html>"
echo -e "$html" > index.html

echo "[OK] Build completata. File md5 e zips rigenerati!"
