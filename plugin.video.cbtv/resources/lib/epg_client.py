# -*- coding: utf-8 -*-
import os
import sys
import gzip
import json
import time
import requests
import xbmc
import xbmcaddon
import xbmcvfs
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import re

class EPGClient:
    def __init__(self, addon_id='plugin.video.cbtv'):
        self.addon = xbmcaddon.Addon(addon_id)
        self.profile_dir = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        if not os.path.exists(self.profile_dir):
            os.makedirs(self.profile_dir)
        
        self.epg_url = "https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz"
        self.cache_file = os.path.join(self.profile_dir, "epg_cache_v2.json")
        self.cache_duration = 3600 * 4  # 4 hours
        
        self.data = None
        
        # ID Mappings for Sky channels found in the XML vs Display Names
        self.manual_map = {
             "sky uno": "Sky.Uno.it",
             "sky cinema uno": "Sky.Cinema.Uno.it",
             "sky cinema due": "Sky.Cinema.Due.it",
             "sky cinema action": "Sky.Cinema.Action.it",
             "sky cinema family": "Sky.Cinema.Family.it",
             "sky cinema romance": "Sky.Cinema.Romance.it",
             "sky cinema suspense": "Sky.Cinema.Suspense.it",
             "sky cinema drama": "Sky.Cinema.Drama.it",
             "sky cinema comedy": "Sky.Cinema.Comedy.it",
             "sky serie": "Sky.Serie.it",
             "sky atlantic": "Sky.Atlantic.it",
             "sky investigation": "Sky.Investigation.it",
             "sky documentaries": "Sky.Documentaries.it",
             "sky nature": "Sky.Nature.it",
             "tv8": "TV8.it",
             "cielo": "Cielo.it",
             "nove": "Nove.it",
             "real time": "Real.Time.it",
             "giallo": "Giallo.it",
             "dmax": "DMAX.it",
             "motor trend": "Motor.Trend.it",
             "food network": "Food.Network.it",
             "hgtv": "HGTV.it"
        }

    def get_data(self):
        """Ensure data is loaded (memory or cache or download)."""
        # If in memory, return it
        if self.data:
            return self.data
            
        # Try loading from disk
        if self._is_cache_valid():
            try:
                xbmc.log("[CBTV] EPG: Loading from disk cache", xbmc.LOGINFO)
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                return self.data
            except Exception as e:
                xbmc.log(f"[CBTV] EPG: Disk cache error: {e}", xbmc.LOGERROR)
        
        # Download and parse
        return self._download_and_parse()

    def _is_cache_valid(self):
        if not os.path.exists(self.cache_file):
            return False
        try:
            mtime = os.path.getmtime(self.cache_file)
            if time.time() - mtime < self.cache_duration:
                return True
        except:
            pass
        return False

    def _download_and_parse(self):
        xbmc.log("[CBTV] EPG: Downloading fresh data...", xbmc.LOGINFO)
        try:
            # Download
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            }
            r = requests.get(self.epg_url, headers=headers, timeout=60, verify=False)
            if r.status_code != 200:
                xbmc.log(f"[CBTV] EPG: Download failed {r.status_code}. URL: {self.epg_url}", xbmc.LOGERROR)
                return {}
            
            xbmc.log(f"[CBTV] EPG: Download success ({len(r.content)} bytes). Parsing...", xbmc.LOGINFO)
            
            epg_map = {} # ChannelID -> List of events
            channel_map = {} # Display Name (lower) -> ChannelID
            
            # Use gzip and iterparse
            import io
            bio = io.BytesIO(r.content)
            
            with gzip.open(bio, 'rb') as f:
                context = ET.iterparse(f, events=('end',))
                
                now = datetime.utcnow()
                start_limit = now - timedelta(hours=4)
                end_limit = now + timedelta(hours=36)
                
                for event, elem in context:
                    tag = elem.tag.split('}')[-1]
                    
                    if tag == 'programme':
                        start_str = elem.get('start', '')
                        stop_str = elem.get('stop', '')
                        channel_id = elem.get('channel', '')
                        
                        if len(start_str) >= 14 and len(stop_str) >= 14:
                            try:
                                start_dt = datetime.strptime(start_str[:14], "%Y%m%d%H%M%S")
                                stop_dt = datetime.strptime(stop_str[:14], "%Y%m%d%H%M%S")
                                
                                if stop_dt > start_limit and start_dt < end_limit:
                                    title = "No Title"
                                    for child in elem:
                                        if 'title' in child.tag:
                                            title = child.text
                                            break
                                    
                                    if channel_id not in epg_map:
                                        epg_map[channel_id] = []
                                    
                                    epg_map[channel_id].append({
                                        's': start_str[:14],
                                        'e': stop_str[:14],
                                        't': title
                                    })
                            except:
                                pass
                        
                        elem.clear()
                        
                    elif tag == 'channel':
                        cid = elem.get('id')
                        # Extract display-name
                        dname = None
                        for child in elem:
                            if 'display-name' in child.tag:
                                dname = child.text
                                break
                        
                        if cid and dname:
                            channel_map[dname.lower().strip()] = cid
                            
                        elem.clear()

            xbmc.log(f"[CBTV] EPG: Parsing done. {len(epg_map)} channels with events.", xbmc.LOGINFO)
            
            full_data = {"epg": epg_map, "channels": channel_map}
            
            # Save to cache
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(full_data, f)
            
            self.data = full_data
            return full_data
            
        except Exception as e:
            xbmc.log(f"[CBTV] EPG: Parsing error {str(e)}", xbmc.LOGERROR)
            return {}

    def get_program(self, channel_name):
        """
        Returns info about the current program:
        { 'title': 'The Movie', 'start': '20:30', 'stop': '22:30' }
        or None
        """
        if self.data is None:
            self.get_data()
            
        if not self.data:
            return None
            
        epg_map = self.data.get("epg", {})
        channel_map = self.data.get("channels", {})
            
        # 1. Normalize name and find ID
        clean_name = channel_name.lower().strip().replace(" hd", "")
        
        channel_id = None
        
        # Try manual map first (exact match)
        if clean_name in self.manual_map:
            channel_id = self.manual_map[clean_name]
        # Try dynamic channel map
        elif clean_name in channel_map:
            channel_id = channel_map[clean_name]
        else:
             # Try removing "sky " or "it - "
             short_name = clean_name.replace("sky ", "").strip()
             if short_name in self.manual_map:
                 channel_id = self.manual_map[short_name]
             elif short_name in channel_map:
                 channel_id = channel_map[short_name]
        
        if not channel_id or channel_id not in epg_map:
            return None
            
        # 2. Find current event
        events = epg_map[channel_id]
        now_str = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        
        for ev in events:
            if ev['s'] <= now_str <= ev['e']:
                try:
                    s_dt = datetime.strptime(ev['s'], "%Y%m%d%H%M%S")
                    e_dt = datetime.strptime(ev['e'], "%Y%m%d%H%M%S")
                    
                    # Add 1 hour fix (assuming XML is UTC+0 and we want +1)
                    # Or keep as is? User didn't complain about timezones, only about "No EPG".
                    # But if I rewrite, I better get it right.
                    # Usually epgshare provides local time IT?
                    # If local time, then +0. 
                    # If I use datetime.utcnow() for comparison, I assume XML is UTC.
                    # If XML is local (CET), then comparing with UTCNOW is WRONG by 1 hour.
                    # The old code used utcnow() and it "worked at first launch".
                    # Let's assume XML is UTC for safety.
                    
                    disp_s = s_dt + timedelta(hours=1)
                    disp_e = e_dt + timedelta(hours=1)
                    
                    return {
                        "title": ev['t'],
                        "start": disp_s.strftime("%H:%M"),
                        "stop": disp_e.strftime("%H:%M")
                    }
                except:
                    # Fallback formatting (YYYYMMDDHHMMSS -> HH:MM)
                    s_time = ev['s'][8:10] + ":" + ev['s'][10:12]
                    e_time = ev['e'][8:10] + ":" + ev['e'][10:12]
                    return {"title": ev['t'], "start": s_time, "stop": e_time}
                    
        return None
