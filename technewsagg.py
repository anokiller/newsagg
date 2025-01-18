import os
import json
from newspaper import Article, build, Config
from transformers import pipeline
import concurrent.futures
import requests

# from google.colab import userdata
# BOT_TOKEN = userdata.get('BOT_API_TOKEN')
# CHAT_ID = userdata.get('CHAT_ID')

# Telegram Bot Configuration
BOT_TOKEN = os.getenv("BOT_API_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # Replace with numeric ID or @channel_username

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("BOT_API_TOKEN or CHAT_ID is not set in environment variables.")

# List of tech-related websites
sources = [
    "https://www.technologyreview.com/feed/",
    "https://spectrum.ieee.org/rss/fulltext",
    "https://www.nature.com/subjects/technology.rss",
    "https://feeds.arstechnica.com/arstechnica/index",
    "http://feeds.feedburner.com/TechCrunch/",
    "https://www.wired.com/feed/",
    "https://openai.com/blog/rss/",
    "https://quantumcomputingreport.com/feed/",
    "https://hnrss.org/frontpage",
]

# Initialize the summarization pipeline
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

# Persistent storage for processed URLs
PROCESSED_URLS_FILE = "processed_urls.json"


def load_processed_urls(file_path=PROCESSED_URLS_FILE):
    """Load processed URLs from a file."""
    try:
        with open(file_path, "r") as file:
            return set(json.load(file))
    except FileNotFoundError:
        return set()


def save_processed_urls(urls, file_path=PROCESSED_URLS_FILE):
    """Save processed URLs to a file."""
    with open(file_path, "w") as file:
        json.dump(list(urls), file)

config = Config()
config.browser_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
config.request_timeout = 10

def fetch_and_summarize(url):
    try:
        article = Article(url, config=config)
        article.download()
        article.parse()
        
        tokens = article.text.split()
        
        # Skip articles shorter than a threshold
        if len(tokens) < 60:
            print(f"Skipping short article: {url}")
            return {"error": "Article too short", "url": url}
        
        # Otherwise summarize
        trimmed_text = " ".join(tokens[:512]) if len(tokens) > 512 else article.text
        
        # Ensure max_length isn't more than the text itself:
        max_len = min(60, len(tokens))  # or 130, or any logic you prefer
        summary = summarizer(trimmed_text, max_length=max_len, min_length=30, do_sample=False)
        
        return {
            "title": article.title,
            "url": url,
            "summary": summary[0]["summary_text"]
        }
    except Exception as e:
        print(f"Error summarizing {url}: {e}")
        return {"error": str(e), "url": url}

# Scrape articles from a source
def scrape_articles(source_url):
    try:
        paper = build(source_url, memoize_articles=False)
        return [article.url for article in paper.articles[:5]]
    except Exception as e:
        print(f"Error scraping {source_url}: {e}")
        return []


# Aggregate summaries from all sources
def aggregate_summaries():
    summaries = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_source = {executor.submit(scrape_articles, source): source for source in sources}
        for future in concurrent.futures.as_completed(future_to_source):
            article_urls = future.result()
            future_to_article = {executor.submit(fetch_and_summarize, url): url for url in article_urls}
            for article_future in concurrent.futures.as_completed(future_to_article):
                result = article_future.result()
                if "error" not in result:
                    summaries.append(result)
    return summaries


if __name__ == "__main__":
    # Load previously processed URLs
    processed_urls = load_processed_urls()

    # Aggregate new summaries
    summaries = aggregate_summaries()

    for item in summaries:  # Use 'item' to avoid confusion with 'summary'
        if isinstance(item, dict) and 'summary' in item and 'url' in item:
            summary_text = str(item['summary'])  # Safely extract 'summary'
            summary_url = str(item['url'])  # Safely extract 'url'

            # Skip if the URL has already been processed
            if summary_url in processed_urls:
                print(f"Skipping already processed URL: {summary_url}")
                continue

            # Construct the Telegram API URL
            base_url = (
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?"
                f"chat_id={CHAT_ID}&text=Summary: {summary_text} URL: {summary_url}"
            )
            
            # Send the message
            response = requests.get(base_url)

            if response.status_code == 200:
                print(f"Message sent successfully: {summary_text}")
                processed_urls.add(summary_url)
                save_processed_urls(processed_urls)
            else:
                print(f"Failed to send message. Error: {response.status_code}")
        else:
            print(f"Unexpected item in summaries: {item}")
    
