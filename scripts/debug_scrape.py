import requests
from bs4 import BeautifulSoup

URL = "https://philschatz.com/us-history-book/"

def debug():
    print(f"Fetching {URL}...")
    try:
        res = requests.get(URL)
        res.raise_for_status()
        print(f"Status: {res.status_code}")
        soup = BeautifulSoup(res.text, "html.parser")
        
        links = soup.find_all("a", href=True)
        print(f"Found {len(links)} links.")
        for i, a in enumerate(links[:20]):
            print(f"{i}: {a['href']}")
            
        # Check for contents specific links
        content_links = [a['href'] for a in links if 'contents/' in a['href']]
        print(f"Found {len(content_links)} content links.")
        if content_links:
            print(f"Sample: {content_links[0]}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug()
