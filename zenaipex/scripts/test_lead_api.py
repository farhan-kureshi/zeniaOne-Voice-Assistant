import asyncio, aiohttp

async def test():
    async with aiohttp.ClientSession() as s:
        async with s.post('http://localhost:8000/api/v1/companies/603d2b5b9f1b2c3d4e5f6a7b/leads/public', json={'name': 'Test Lead', 'phone': '1234567890'}) as r:
            print(r.status, await r.json())

if __name__ == "__main__":
    asyncio.run(test())
