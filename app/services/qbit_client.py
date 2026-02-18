import qbittorrentapi

from app.settings import settings


def get_client() -> qbittorrentapi.Client:
    client = qbittorrentapi.Client(
        host=settings.qbit_host,
        port=settings.qbit_port,
        username=settings.qbit_username,
        password=settings.qbit_password,
        REQUESTS_ARGS={"timeout": 20},
    )
    client.auth_log_in()
    return client


def _extract_info_hash(magnet: str) -> str | None:
    """Extract info hash from magnet link."""
    if not magnet.startswith("magnet:"):
        return None
    # magnet:?xt=urn:btih:HASH...
    for part in magnet.split("&"):
        if part.startswith("xt=urn:btih:"):
            return part.replace("xt=urn:btih:", "").lower()
    return None


def _torrent_exists(client: qbittorrentapi.Client, magnet: str) -> bool:
    """Check if torrent already exists in qBittorrent."""
    info_hash = _extract_info_hash(magnet)
    if not info_hash:
        return False
    
    try:
        # Try to get torrent by hash
        torrent = client.torrents_info(torrent_hashes=info_hash)
        return len(torrent) > 0
    except Exception:
        return False


def add_magnet(magnet: str, save_path: str, category: str | None = None) -> dict:
    """
    Add magnet/torrent to qBittorrent.
    
    Returns:
        dict: {"ok": True, "status": "added|exists", "hash": info_hash}
        Raises RuntimeError on failure
    """
    client = get_client()
    
    # Check if already exists
    if _torrent_exists(client, magnet):
        info_hash = _extract_info_hash(magnet)
        return {"ok": True, "status": "exists", "hash": info_hash}
    
    # Always use urls= parameter — works for both magnet links and .torrent URLs.
    # (torrent_files= with raw bytes fails on qBittorrent 5.x)
    res = client.torrents_add(
        urls=magnet,
        save_path=save_path,
        category=category or settings.qbit_category,
        is_paused=False,
    )

    # qB API may return string statuses instead of raising exceptions.
    txt = str(res or "").strip().lower()
    
    # "Fails." can mean duplicate or actual failure - check if it exists now
    if txt in {"fails.", "fail"}:
        if _torrent_exists(client, magnet):
            info_hash = _extract_info_hash(magnet)
            return {"ok": True, "status": "exists", "hash": info_hash}
        raise RuntimeError(f"qB add rejected: {res}")
    
    if txt and txt not in {"ok.", "ok", "true", "none"}:
        raise RuntimeError(f"qB add rejected: {res}")
    
    info_hash = _extract_info_hash(magnet)
    return {"ok": True, "status": "added", "hash": info_hash}