import urllib.request
import json

endpoints = [
    "http://127.0.0.1:8000/api/bootstrap",
    "http://127.0.0.1:8000/api/workspaces",
    "http://127.0.0.1:8000/api/chats?workspace_id=1",
    "http://127.0.0.1:8000/api/messages?chat_id=1"
]

for url in endpoints:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            print(f"SUCCESS {url}: {response.getcode()}")
    except urllib.error.HTTPError as e:
        print(f"HTTP_ERROR {url}: {e.code}")
        print(e.read().decode('utf-8'))
    except Exception as e:
        print(f"ERROR {url}: {e}")
