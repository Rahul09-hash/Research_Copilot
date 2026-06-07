import asyncio
from research_copilot.config import load_settings
from research_copilot.service_factory import create_services

async def test_ollama():
    services = create_services(load_settings())
    import ollama
    client = ollama.Client(host=services.settings.ollama_host)
    resp = client.list()
    print(resp)
    
if __name__ == "__main__":
    asyncio.run(test_ollama())
