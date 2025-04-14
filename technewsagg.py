import os
import json
import feedparser
from newspaper import Article, Config
from transformers import pipeline
import concurrent.futures
import requests
from urllib.parse import urlparse

# Telegram Bot Configuration
BOT_TOKEN = os.getenv("BOT_API_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # Replace with numeric ID or @channel_username

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError("BOT_API_TOKEN or CHAT_ID is not set in environment variables.")

# List of tech-related RSS feed URLs
sources = [
    "https://www.technologyreview.com/feed/",
    "https://spectrum.ieee.org/rss/fulltext",
    "https://www.nature.com/subjects/technology.rss",
    "https://feeds.arstechnica.com/arstechnica/index",
    "http://feeds.feedburner.com/TechCrunch/",
    "https://www.wired.com/feed/",
    "https://quantumcomputingreport.com/feed/",
    "https://hnrss.org/frontpage",
    "https://www.engadget.com/rss.xml",
    "https://rss.slashdot.org/Slashdot/slashdotMain",
    "https://www.theverge.com/rss/index.xml",
    "https://thenextweb.com/feed/",
    "https://www.fastcompany.com/technology/rss",
    "https://futurism.com/feed",
    "https://singularityhub.com/feed/",
    "https://news.mit.edu/rss/topic/technology",
    "https://arxiv.org/rss/cs.AI",
    "https://tech.eu/feed/",
    "https://news.crunchbase.com/feed/",
]

# Initialize summarization pipeline (using google/pegasus-cnn_dailymail as an example)
summarizer = pipeline("summarization", model="google/pegasus-cnn_dailymail")

# File for persistent storage of processed URLs
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

# Newspaper config
config = Config()
config.browser_user_agent = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)
config.request_timeout = 10

def get_domain_name(url):
    """Extract domain name (e.g., 'arstechnica.com') from a full URL."""
    parsed = urlparse(url)
    domain = parsed.netloc
    if domain.startswith("www."):
        domain = domain[4:]
    return domain

def hierarchical_summarize(text, max_input_tokens=1024, summary_max_length=120, summary_min_length=30):
    """
    Split a long text into chunks (each of at most max_input_tokens tokens),
    summarize each chunk, and then summarize the concatenated summaries.
    """
    tokenizer = summarizer.tokenizer
    # Encode the text without truncation so we can split manually.
    token_ids = tokenizer.encode(text, add_special_tokens=False)
    
    # If the text is short enough, just summarize directly.
    if len(token_ids) <= max_input_tokens:
        summary = summarizer(
            text,
            max_length=summary_max_length,
            min_length=summary_min_length,
            do_sample=False,
            truncation=True  # safety in case the text slightly exceeds limit
        )
        return summary[0]["summary_text"]
    
    # Otherwise, split the token_ids into chunks.
    chunks = []
    for i in range(0, len(token_ids), max_input_tokens):
        chunk_ids = token_ids[i:i + max_input_tokens]
        # Decode each chunk back to text.
        chunk_text = tokenizer.decode(chunk_ids, skip_special_tokens=True)
        chunks.append(chunk_text)
    
    # Summarize each chunk separately.
    chunk_summaries = []
    for chunk in chunks:
        out = summarizer(
            chunk,
            max_length=summary_max_length,
            min_length=summary_min_length,
            do_sample=False,
            truncation=True
        )
        chunk_summaries.append(out[0]["summary_text"])

    combined_text = " ".join(chunk_summaries)
    token_length = len(tokenizer.encode(combined_text, add_special_tokens=True))
    if token_length < 1.5 * summary_max_length:
        return combined_text
    else:
        final_summary = summarizer(
            combined_text,
            max_length=summary_max_length,
            min_length=summary_min_length,
            do_sample=False,
            truncation=True
        )
        return final_summary[0]["summary_text"]


def fetch_and_summarize(url):
    """
    Download an article via newspaper3k and summarize it using hierarchical summarization.
    """
    try:
        article = Article(url, config=config)
        article.download()
        article.parse()

        tokens = summarizer.tokenizer.encode(article.text, add_special_tokens=True)
        # Skip articles that are too short.
        if len(tokens) < 120:
            print(f"Skipping short article: {url}")
            return {"error": "Article too short", "url": url}
        
        # Use hierarchical summarization to handle long articles.
        summary_text = hierarchical_summarize(article.text)
        return {
            "title": article.title,
            "url": url,
            "summary": summary_text
        }
    except Exception as e:
        print(f"Error summarizing {url}: {e}")
        return {"error": str(e), "url": url}

def scrape_articles(feed_url):
    """
    Parse an RSS feed with feedparser and return up to 3 article links.
    """
    try:
        parsed_feed = feedparser.parse(feed_url)
        if parsed_feed.bozo:
            print(f"Feed parse error for {feed_url}: {parsed_feed.bozo_exception}")
            return []
        articles = []
        for entry in parsed_feed.entries[:3]:
            if hasattr(entry, 'link'):
                articles.append(entry.link)
        return articles
    except Exception as e:
        print(f"Error scraping feed {feed_url}: {e}")
        return []

def aggregate_summaries():
    summaries = []
    processed_in_this_run = set()
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Scrape feeds concurrently.
        future_to_source = {executor.submit(scrape_articles, src): src for src in sources}
        for future in concurrent.futures.as_completed(future_to_source):
            article_urls = future.result()
            future_to_article = {}
            for url in article_urls:
                if url in processed_in_this_run:
                    continue
                processed_in_this_run.add(url)
                future_to_article[executor.submit(fetch_and_summarize, url)] = url
            for article_future in concurrent.futures.as_completed(future_to_article):
                result = article_future.result()
                if "error" not in result:
                    summaries.append(result)
    return summaries

if __name__ == "__main__":
    processed_urls = load_processed_urls()
    summaries = aggregate_summaries()

    for item in summaries:
        if "summary" in item and "url" in item:
            summary_text = item["summary"]
            summary_url = item["url"]

            if summary_url in processed_urls:
                print(f"Skipping already processed URL: {summary_url}")
                continue

            domain = get_domain_name(summary_url)
            hyperlink = f"<a href='{summary_url}'>{domain}</a>"
            message_html = f"Summary: {summary_text}\nSource: {hyperlink}"
            message_html = message_html.replace("<n>", "\n")

            payload = {
                "chat_id": CHAT_ID,
                "text": message_html,
                "parse_mode": "HTML"
            }

            base_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            response = requests.post(base_url, data=payload)

            if response.status_code == 200:
                print(f"Message sent successfully (with hyperlink)! -> {domain}")
                processed_urls.add(summary_url)
                save_processed_urls(processed_urls)
            else:
                print(f"Failed to send message. Error: {response.status_code}")
                print("Response content:", response.text)
        else:
            print(f"Unexpected item in summaries: {item}")
