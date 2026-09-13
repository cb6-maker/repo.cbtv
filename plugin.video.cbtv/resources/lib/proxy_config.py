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
WEBSHARE_PROXIES = [
    "http://anjfzzgf:8z4iqw56jbnh@45.38.107.97:6014",    # UK London (velocità ~0.24s)
    "http://anjfzzgf:8z4iqw56jbnh@64.137.96.74:6641",    # ES Madrid  (velocità ~0.26s)
    "http://anjfzzgf:8z4iqw56jbnh@31.59.20.176:6754",    # UK London (velocità ~0.28s)
    "http://anjfzzgf:8z4iqw56jbnh@198.105.121.200:6462", # UK London (velocità ~0.29s)
    "http://anjfzzgf:8z4iqw56jbnh@84.247.60.125:6095",   # PL Warsaw (velocità ~0.32s)
    "http://anjfzzgf:8z4iqw56jbnh@31.58.9.4:6077",       # DE Frankfurt (velocità ~0.64s)
    "http://anjfzzgf:8z4iqw56jbnh@38.154.185.97:6370",   # US Piscataway
    "http://anjfzzgf:8z4iqw56jbnh@198.23.243.226:6361",  # US Los Angeles
    "http://anjfzzgf:8z4iqw56jbnh@191.96.254.138:6185",  # US Los Angeles
    "http://anjfzzgf:8z4iqw56jbnh@142.111.67.146:5611",  # JP Tokyo
]

def get_random_proxy():
    """Restituisce un proxy casuale dal pool Webshare."""
    if not WEBSHARE_PROXIES:
        return None
    return random.choice(WEBSHARE_PROXIES)

def get_proxy_session(proxy_url=None):
    """Crea una requests.Session preconfigurata con proxy Webshare."""
    session = requests.Session()
    session.trust_env = False
    p = proxy_url or get_random_proxy()
    if p:
        session.proxies = {
            "http": p,
            "https": p
        }
    return session
