# -*- coding: utf-8 -*-
import xbmc
import xbmcaddon

def run():
    addon = xbmcaddon.Addon("plugin.video.cbtv")
    autostart = addon.getSetting("autostart")
    xbmc.log(f"[CBTV-Service] Service di avvio eseguito. autostart={autostart}", xbmc.LOGINFO)
    
    if autostart.lower() == "true":
        monitor = xbmc.Monitor()
        # Attesa di 2 secondi per permettere alla GUI e alla schermata Home di Kodi di essere pronte
        if not monitor.waitForAbort(2):
            xbmc.log("[CBTV-Service] Autostart abilitato: apertura automatica CBTV...", xbmc.LOGINFO)
            xbmc.executebuiltin("ActivateWindow(videos,plugin://plugin.video.cbtv/,return)")

if __name__ == "__main__":
    run()
