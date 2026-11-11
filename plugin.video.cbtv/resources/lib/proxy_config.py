htt"""
proxy_config.py - Webshare Proxy Pool per bypass blocchi AGCOM/ISP
Utilizzato ESCLUSIVAMENTE per handshake, create_link e risoluzione del redirect Stalker Portal.
Il flusso video effettivo (CDN) scorre in connessione diretta senza passare dal proxy.
"""
import random
import requests

# ---------------------------------------------------------------------------
# Webshare Residential/Datacenter Proxy Pool aggiornato
# Format: http://username:password@ip:port
# ---------------------------------------------------------------------------
WEBSHARE_PROXIES = [
    "http://anjfzzgf:8z4iqw56jbnh@45.38.107.97:6014",    # UK, London
    "http://anjfzzgf:8z4iqw56jbnh@64.137.96.74:6641",    # Spain, Madrid
    "http://anjfzzgf:8z4iqw56jbnh@198.23.243.226:6361",  # US, Los Angeles
    "http://anjfzzgf:8z4iqw56jbnh@38.154.185.97:6370",   # US, Piscataway
    "http://anjfzzgf:8z4iqw56jbnh@84.247.60.125:6095",   # Poland, Warsaw
    "http://anjfzzgf:8z4iqw56jbnh@191.96.254.138:6185",  # US, Los Angeles
    "http://anjfzzgf:8z4iqw56jbnh@198.46.161.42:5092",   # US, Los Angeles
    "http://anjfzzgf:8z4iqw56jbnh@104.164.49.38:7693",   # US, Santa Clara
    "http://anjfzzgf:8z4iqw56jbnh@23.26.71.145:5628",    # US, Orem
]

# Flag per attivare/disattivare i proxy Webshare (True = attivo per la connessione al portale)
USE_PROXY = True

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
    """Crea una requests.Session con proxy Webshare configurato."""
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
