import newspaper
from newspaper import Article, build, Config, Source
from transformers import pipeline
import concurrent.futures
from telegram import Bot
import requests

# Telegram Bot Configuration
BOT_TOKEN = "8091285785:AAGXfIVeTI0mj0VKOB22i9lfAidzcLWu3Hs"
CHAT_ID = "6777709867"  # Replace with the actual numeric ID or @channel_username
bot = Bot(token=BOT_TOKEN)

# List of tech-related websites
sources = [
    "https://www.technologyreview.com/feed/",             # MIT Technology Review
    "https://spectrum.ieee.org/rss/fulltext",            # IEEE Spectrum
    "https://www.nature.com/subjects/technology.rss",    # Nature Technology
    "https://feeds.arstechnica.com/arstechnica/index",   # Ars Technica
    "http://feeds.feedburner.com/TechCrunch/",           # TechCrunch
    "https://www.wired.com/feed/",                       # Wired
    "https://openai.com/blog/rss/",                      # OpenAI Blog
    "https://quantumcomputingreport.com/feed/",          # Quantum Computing Report
    "https://hnrss.org/frontpage",                       # Hacker News
]


# Initialize the summarization pipeline
summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")

# Fetch and summarize articles
def fetch_and_summarize(url):
    try:
        article = Article(url)
        article.download()
        article.parse()
        if len(article.text.split()) > 512:
            trimmed_text = " ".join(article.text.split()[:512])
        else:
            trimmed_text = article.text
        summary = summarizer(trimmed_text, max_length=130, min_length=30, do_sample=False)
        return {"title": article.title, "url": url, "summary": summary[0]["summary_text"]}
    except Exception as e:
        print(f"Error summarizing {url}: {e}")
        return {"error": str(e), "url": url}

# Scrape articles from a source
def scrape_articles(source_url):
    try:
        paper = build(source_url, memoize_articles=False)
        return [article.url for article in paper.articles[:5]]
    except:
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

# Send messages to Telegram
def post_to_telegram(summary, url):
    try:
        message = f"Summary: {summary}\nRead more: {url}"
        if len(message) > 4096:
            message = message[:4093] + "..."
        bot.send_message(chat_id=CHAT_ID, text=message)
        print(f"Message sent: {message}")
    except Exception as e:
        print(f"Error sending message to Telegram: {e}")

# Main execution
if __name__ == "__main__":
    summaries = aggregate_summaries()
    print("Summaries:", summaries)
    print("Type of each item in summaries:", [type(item) for item in summaries])

    for item in summaries:  # Use 'item' to avoid confusion with 'summary'
        if isinstance(item, dict) and 'summary' in item and 'url' in item:
            summary_text = str(item['summary'])  # Safely extract 'summary'
            summary_url = str(item['url'])  # Safely extract 'url'
            
            # Construct the Telegram API URL
            base_url = (
                f"https://api.telegram.org/bot8091285785:AAGXfIVeTI0mj0VKOB22i9lfAidzcLWu3Hs/"
                f"sendMessage?chat_id=6777709867&text=Summary: {summary_text} URL: {summary_url}"
            )
            
            # Send the message
            response = requests.get(base_url)

            if response.status_code == 200:
                print(f"Message sent successfully: {summary_text}")
            else:
                print(f"Failed to send message. Error: {response.status_code}")
        else:
            print(f"Unexpected item in summaries: {item}")
