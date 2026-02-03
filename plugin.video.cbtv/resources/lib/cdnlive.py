import requests
import re
import json
import xbmc
from urllib.parse import unquote, quote_plus

class CDNLiveResolver:
    def __init__(self, user="streamsports99", plan="vip"):
        self.user = user
        self.plan = plan
        self.base_api = "https://api.cdn-live.tv/api/v1"
        self.player_referer = "https://streamsports99.su/"
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def get_headers(self, referer=None):
        return {
            "User-Agent": self.ua,
            "Referer": referer if referer else self.player_referer,
            "Origin": "https://cdn-live.tv"
        }

    def fetch_api(self, endpoint):
        url = f"{self.base_api}/{endpoint}/?user={self.user}&plan={self.plan}"
        xbmc.log(f"CDNLive: Fetching API: {url}", xbmc.LOGINFO)
        try:
            r = requests.get(url, headers=self.get_headers(), timeout=15, verify=False)
            xbmc.log(f"CDNLive: API Status: {r.status_code}", xbmc.LOGINFO)
            r.raise_for_status()
            data = r.json()
            return data
        except Exception as e:
            xbmc.log(f"CDNLive: API Error: {str(e)}", xbmc.LOGERROR)
            return None

    def get_channels(self):
        data = self.fetch_api("channels")
        channels = data.get("channels", []) if data else []
        xbmc.log(f"CDNLive: Total channels from API: {len(channels)}", xbmc.LOGINFO)
        
        # Filter for online channels only
        online = [ch for ch in channels if ch.get("status") == "online"]
        xbmc.log(f"CDNLive: Online channels filter: {len(online)}", xbmc.LOGINFO)
        
        # FALLBACK: If filtering for 'online' results in 0, return all channels
        # This prevents an empty menu if the API status field is temporarily unreliable
        if channels and not online:
            xbmc.log("CDNLive: WARNING: Online filter returned 0, falling back to all channels", xbmc.LOGWARNING)
            return channels
            
        return online

    def get_channels_grouped(self):
        channels = self.get_channels()
        grouped = {}
        for ch in channels:
            # Map code (e.g., 'it', 'en', 'es') to country name
            country_code = ch.get("code", "ot").lower()
            country_map = {
                "it": "Italy", "es": "Spain", "en": "UK / International", "us": "USA",
                "fr": "France", "de": "Germany", "pt": "Portugal", "dk": "Denmark",
                "tr": "Turkey", "ro": "Romania", "pl": "Poland", "ar": "Arabic"
            }
            country_name = country_map.get(country_code, "Other")
            if country_name not in grouped: grouped[country_name] = []
            grouped[country_name].append(ch)
        return grouped

    def get_sports_categories(self):
        data = self.fetch_api("events/sports")
        if not data or "cdn-live-tv" not in data:
            return {}
        return data["cdn-live-tv"]

    @staticmethod
    def _convert_base(s, base):
        result = 0
        for i, digit in enumerate(reversed(s)):
            result += int(digit) * (base ** i)
        return result

    def decode_js(self, html):
        """Mandrakodi JS Decoding Logic"""
        try:
            start = html.find('}("') + 3
            if start == 2: return None
            end = html.find('",', start)
            encoded = html[start:end]
            params_pos = end + 2
            params_str = html[params_pos:params_pos + 150]
            
            m = re.search(r'(\d+),\s*"([^"]+)",\s*(\d+),\s*(\d+),\s*(\d+)', params_str)
            if not m: return None
            
            charset = m.group(2)
            offset = int(m.group(3))
            base = int(m.group(4))
            
            decoded = ""
            split_char = charset[base]
            parts = encoded.split(split_char)
            
            for part in parts:
                if not part: continue
                temp = part
                for idx, c in enumerate(charset):
                    temp = temp.replace(c, str(idx))
                val = self._convert_base(temp, base)
                decoded += chr(val - offset)
            return unquote(decoded)
        except:
            return None

    def resolve(self, player_url, plan=None):
        """Main resolution logic with fallback"""
        current_plan = plan if plan else self.plan
        xbmc.log(f"CDNLive: Resolving {player_url} (Plan: {current_plan})", xbmc.LOGINFO)
        
        url_with_plan = player_url
        if f"plan={self.plan}" in url_with_plan and current_plan != self.plan:
             url_with_plan = url_with_plan.replace(f"plan={self.plan}", f"plan={current_plan}")

        try:
            r = requests.get(url_with_plan, headers=self.get_headers(), timeout=15, verify=False)
            r.raise_for_status()
            
            js = self.decode_js(r.text)
            if not js:
                if current_plan == "vip":
                    xbmc.log("CDNLive: VIP failed, trying FREE fallback", xbmc.LOGINFO)
                    return self.resolve(player_url, plan="free")
                return None
            
            # Find the tokenized URL
            pattern = r'["\']([^"\']*index\.m3u8\?token=[^"\']+)["\']'
            match = re.search(pattern, js)
            if not match:
                if current_plan == "vip":
                    xbmc.log("CDNLive: VIP token not found, trying FREE fallback", xbmc.LOGINFO)
                    return self.resolve(player_url, plan="free")
                return None
            
            final_url = match.group(1).replace("\\/", "/")
            if final_url.startswith("//"): final_url = "https:" + final_url
            
            xbmc.log(f"CDNLive: Resolved to {final_url}", xbmc.LOGINFO)
            return final_url
        except Exception as e:
            if current_plan == "vip":
                xbmc.log("CDNLive: VIP error, trying FREE fallback", xbmc.LOGINFO)
                return self.resolve(player_url, plan="free")
            xbmc.log(f"CDNLive: Resolution Error: {str(e)}", xbmc.LOGERROR)
            return None
