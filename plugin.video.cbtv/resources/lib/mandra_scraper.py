import requests
import json
import re

class MandraScraper:
    def __init__(self):
        self.base_url = "https://oha.to"  # Can switch between oha.to and vavoo.to
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url
        }

    def get_channels(self):
        """Fetches the full channel list and filters for Italy + Sky/PrimaFila"""
        try:
            r = requests.get(f"{self.base_url}/channels", headers=self.headers, timeout=15)
            if r.status_code != 200:
                return []
            
            all_channels = r.json()
            filtered = []
            for ch in all_channels:
                country = ch.get('country', '').lower()
                name = ch.get('name', '').upper()
                
                # Filter for Italy
                if country == 'italy':
                    # Filter for Sky or PrimaFila
                    if 'SKY' in name or 'PRIMAFILA' in name:
                        filtered.append({
                            'name': ch.get('name'),
                            'id': ch.get('id'),
                            'url': f"{self.base_url}/play/{ch.get('id')}/index.m3u8"
                        })
            
            # Sort by name
            filtered.sort(key=lambda x: x['name'])
            return filtered
        except Exception as e:
            print(f"Error fetching channels: {e}")
            return []

    def get_stream_url(self, channel_id):
        """Returns the URL with headers for Kodi playback"""
        # We use oha.to/play/{id}/index.m3u8 which handles redirects
        # Kodi handles the redirect if we provide the right headers for the initial call.
        stream_url = f"{self.base_url}/play/{channel_id}/index.m3u8"
        # Append headers for Kodi
        headers_str = f"|Referer={self.base_url}/&Origin={self.base_url}&User-Agent=iPad"
        return stream_url + headers_str

if __name__ == "__main__":
    scraper = MandraScraper()
    channels = scraper.get_channels()
    print(f"Found {len(channels)} Sky/PrimaFila channels.")
    if channels:
        print(f"Example: {channels[0]['name']} -> {scraper.get_stream_url(channels[0]['id'])}")
