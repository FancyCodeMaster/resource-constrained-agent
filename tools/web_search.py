import multiprocessing as mp
from typing import Optional

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

def _worker_search(query: str, max_results: int, out_q: mp.Queue):
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query.strip(), max_results=max_results))
        out_q.put(("ok", raw))
    except Exception as e:
        out_q.put(("err", f"{type(e).__name__}: {e}"))

def web_search(query: str, max_results: int = 5, timeout: int = 10) -> dict:
    """ 
    Search the web using DuckDuckGo.

    Args:
        query: search query string
        max_results: maximum number of search results to return (default: 5)
        timeout: maximum time in seconds to wait for the search to complete (default: 10)

    Returns:
        dict with keys 'success' , 'results' (list of {title, href, body}), 'error'

    """

    if not query or not query.strip():
        return {"success": False, "results": [], "error": "Empty query provided"}
    
    out_q = mp.Queue()
    p = mp.Process(target=_worker_search, args=(query, max_results, out_q))
    p.start()
    p.join(timeout)

    if p.is_alive():
        p.terminate()
        p.join()
        return {
            "success": False,
            "results": [],
            "error": f"Search timed out after {timeout} seconds"
        }
    
    if out_q.empty():
        return {
            "success": False,
            "results": [],
            "error": "Search failed with no output"
        }
    
    status, payload = out_q.get()
    if status == "err":
        return {
            "success": False,
            "results": [],
            "error": f"Search failed with error: {payload}"
        }
    
    raw = payload
    if not raw:
        return {
            "success": True,
            "results": [],
            "error": "No results for this query"
        }
    
    results = [
        {
            "title": item.get("title", ""),
            "href": item.get("href", ""),
            "body": item.get("body", "")[:200]  # truncate body to first 200 chars
        }
        for item in raw
    ]

    return {
        "success": True,
        "results": results,
        "error": None
    }