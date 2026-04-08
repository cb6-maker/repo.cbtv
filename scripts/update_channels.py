import cloudscraper
from bs4 import BeautifulSoup
import json
import re
import os
import time

# --- CONFIGURATION ---
SOURCE_URL = "https://freeshot.live/live-tv"
CONFIG_FILE = "channels_config.json"
MAX_PAGES = 30
MIN_VERSION = 55 # Ensure it's higher than the one in addon.py (v50)

# Keywords for International Sports
INT_KEYWORDS = [
    "SPORT", "BEIN", "POLSAT", "ELEVEN", "ARENA", "ZIGGO", "PREMIER", "TNT", 
    "SUPERSPORT", "CANAL+", "DIGI", "PRIMA", "MATCH TV", "VAMOS", "ESPN", "FOX", 
    "WILLOW", "CRICKET", "TENNIS", "NBA", "NFL", "MLB", "UFC"
]

# Country Code Mapping
COUNTRY_MAP = {
    "IT": "Italia",
    "UK": "Regno Unito",
    "FR": "Francia",
    "ES": "Spagna",
    "PL": "Polonia",
    "RO": "Romania",
    "BG": "Bulgaria",
    "GR": "Grecia",
    "AL": "Albania",
    "HR": "Croazia",
    "PT": "Portogallo",
    "US": "USA",
    "DE": "Germania",
    "NL": "Olanda",
    "AR": "Arabia",
    "BR": "Brasile",
    "CZ": "Repubblica Ceca",
    "ZA": "Sud Africa",
    "CA": "Canada",
    "AU": "Australia"
}

def clean_name(name):
    # Remove country code suffix (e.g., "Sky Sport 1 IT" -> "Sky Sport 1")
    name = re.sub(r'\s+[A-Z]{2}$', '', name)
    # Remove common filler
    name = name.replace(" online", "").strip()
    return name

def get_country_from_name(name):
    match = re.search(r'\s+([A-Z]{2})$', name)
    if match:
        code = match.group(1)
        return code, COUNTRY_MAP.get(code, code)
    return "??", "Other"

def filter_channel(name):
    name_up = name.upper()
    
    # Italian Filter: SKY or RAI SPORT
    if " IT" in name_up:
        if "SKY" in name_up or "RAI SPORT" in name_up:
            return "italy"
        return None
        
    # International Filter
    if any(k in name_up for k in INT_KEYWORDS):
        return "intl"
        
    return None

def scrape_freeshot():
    scraper = cloudscraper.create_scraper()
    all_channels = []
    
    for page in range(1, MAX_PAGES + 1):
        print(f"Scraping page {page}...")
        try:
            url = f"{SOURCE_URL}?page={page}"
            r = scraper.get(url, timeout=15)
            if r.status_code != 200:
                print(f"Error status {r.status_code} on page {page}")
                break
                
            soup = BeautifulSoup(r.text, 'html.parser')
            # Look for channel links / cards
            # Structure matches the browser subagent's discovery: <h4> for name, <a> for link
            cards = soup.find_all('div', class_='card') # Assuming typical structure, let's refine
            # If card class is not there, we look for <a> containing /live-tv/
            links = soup.find_all('a', href=re.compile(r'/live-tv/'))
            
            pushed_on_this_page = 0
            for link in links:
                h4 = link.find('h4')
                if not h4: continue
                
                full_name = h4.get_text().strip()
                href = link.get('href')
                
                # Extract ID from https://freeshot.live/live-tv/slug/id
                m = re.search(r'/(\d+)$', href)
                if not m: continue
                channel_id = m.group(1)
                
                all_channels.append({
                    "name": full_name,
                    "code": channel_id
                })
                pushed_on_this_page += 1
            
            print(f"Found {pushed_on_this_page} channels on page {page}")
            if pushed_on_this_page == 0: break
            
            time.sleep(1) # Be nice
        except Exception as e:
            print(f"Error on page {page}: {e}")
            break
            
    return all_channels

def update_config(scraped_channels):
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found!")
        return
        
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    # Increment version
    new_version = config.get("version", 0) + 1
    config["version"] = max(new_version, MIN_VERSION)
    
    italy_list = []
    intl_dict = {} # "Nazione": [channels]
    
    for ch in scraped_channels:
        ctype = filter_channel(ch["name"])
        if not ctype: continue
        
        display_name = clean_name(ch["name"])
        country_code, country_name = get_country_from_name(ch["name"])
        
        entry = {
            "name": display_name,
            "code": ch["code"]
        }
        
        if ctype == "italy":
            # Preservation of sky_id for EPG if it matches exactly
            # We look for old entry in freeshot_v3 if name matches
            old_fs = config.get("freeshot_v3", {}).get("channels", [])
            old_match = next((x for x in old_fs if clean_name(x["name"]) == display_name), None)
            if old_match and "sky_id" in old_match:
                entry["sky_id"] = old_match["sky_id"]
            italy_list.append(entry)
        else:
            if country_name not in intl_dict:
                intl_dict[country_name] = []
            intl_dict[country_name].append(entry)
            
    # Sort dictionaries
    italy_list.sort(key=lambda x: x["name"])
    # Sort intl countries
    sorted_intl = {k: sorted(intl_dict[k], key=lambda x: x["name"]) for k in sorted(intl_dict.keys())}
    
    # Update config
    config["freeshot_v3"]["channels"] = italy_list
    config["international_sport_fs"] = sorted_intl
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        
    print(f"Successfully updated {CONFIG_FILE} to version {config['version']}")
    print(f"Added {len(italy_list)} Italian channels and {len(intl_dict)} countries.")

if __name__ == "__main__":
    print("Starting automated channel update...")
    scraped = scrape_freeshot()
    if scraped:
        update_config(scraped)
    else:
        print("No channels scraped. Update aborted.")
