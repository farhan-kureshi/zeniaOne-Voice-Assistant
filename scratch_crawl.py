import asyncio
from bs4 import BeautifulSoup

def normalize_extracted_text(text: str) -> str:
    import re
    text = re.sub(r'\n\s*\n', '\n', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines)

def extract_text(html_str):
    soup = BeautifulSoup(html_str, "html.parser")
    for element in soup(["script", "style", "meta", "noscript", "header", "footer", "nav", "svg", "iframe"]):
        element.decompose()
    return soup.get_text(separator="\n")

async def main():
    try:
        from playwright.async_api import async_playwright
        visited_urls = set()
        urls_to_visit = ["https://www.zeniahr.com"]
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            while urls_to_visit and len(visited_urls) < 10:
                current_url = urls_to_visit.pop(0)
                if current_url in visited_urls: continue
                visited_urls.add(current_url)
                
                await page.goto(current_url, timeout=30000, wait_until="networkidle")
                await page.wait_for_timeout(1500)
                html_content = await page.content()
                
                text = extract_text(html_content)
                clean_text = normalize_extracted_text(text)
                print(f"Crawled: {current_url} | Extracted length: {len(clean_text)}")
                
                # grab a couple links just to keep loop going
                soup = BeautifulSoup(html_content, "html.parser")
                for a in soup.find_all('a', href=True):
                    if a['href'].startswith('/'):
                        urls_to_visit.append("https://www.zeniahr.com" + a['href'])
                        
            await browser.close()
    except Exception as e:
        print(e)

if __name__ == "__main__":
    asyncio.run(main())
