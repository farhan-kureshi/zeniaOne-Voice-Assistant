import asyncio
import os
import sys

# add zenaipex to path so db.database works
sys.path.append(os.path.join(os.path.dirname(__file__), "zenaipex"))

async def main():
    from db.database import col_documents
    doc = await col_documents().find_one({'filename': 'zeniahr_com.txt'})
    print(doc)

if __name__ == "__main__":
    asyncio.run(main())
