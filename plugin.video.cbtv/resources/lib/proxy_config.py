"""
proxy_config.py - Webshare Proxy Pool per bypass blocchi AGCOM/ISP
Utilizzato per handshake, create_link e risoluzione Stalker Portal.
"""
import random
import requests

# ---------------------------------------------------------------------------
# Webshare Residential/Datacenter Proxy Pool
# Format: http://username:password@ip:port
# ---------------------------------------------------------------------------
WEBSHARE_PROXIES = []

# Flag per attivare/disattivare i proxy Webshare (False = usa connessione diretta/VPN)
USE_PROXY = False

def get_random_proxy():
    """Restituisce un proxy casuale dal pool Webshare se abilitato."""
    if not USE_PROXY or not WEBSHARE_PROXIES:
        return None
    return random.choice(WEBSHARE_PROXIES)

def get_shuffled_proxies():
    """Restituisce una lista casuale di tutti i proxy disponibili per retry."""
    if not USE_PROXY:
        return []
    pool = list(WEBSHARE_PROXIES)
    random.shuffle(pool)
    return pool

def get_proxy_session(proxy_url=None):
    """Crea una requests.Session. Se i proxy sono disattivati, usa connessione diretta/VPN."""
    session = requests.Session()
    session.trust_env = False
    if USE_PROXY:
        p = proxy_url or get_random_proxy()
        if p:
            session.proxies = {
                "http": p,
                "https": p
            }
    return session

