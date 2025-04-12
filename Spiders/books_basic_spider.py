import scrapy

class BooksBasicSpider(scrapy.Spider):
    """
    A basic spider to scrape book information from books.toscrape.com.
    It extracts title, price, rating, availability, and URL for each book
    and follows pagination links to scrape all pages.
    """
    name = 'books_basic' # Spider name used to run it (scrapy crawl books_basic)
    allowed_domains = ['books.toscrape.com']
    start_urls = ['https://books.toscrape.com/']

    # Define a mapping for star ratings (optional, but cleaner)
    RATING_MAP = {
        'One': 1,
        'Two': 2,
        'Three': 3,
        'Four': 4,
        'Five': 5,
    }

    def parse(self, response):
        """
        Default callback method. Parses the main category/listing pages.
        """
        self.logger.info(f'Scraping page: {response.url}')

        # Select each book item on the page
        books = response.css('article.product_pod')

        for book in books:
            # Extract rating text (e.g., "Three")
            rating_text = book.css('p.star-rating::attr(class)').re_first(r'star-rating (\w+)')
            # Convert rating text to number using the map, default to 0 if not found
            rating_num = self.RATING_MAP.get(rating_text, 0)

            # Extract availability text and clean it
            availability_text = book.css('p.availability::text').getall()
            # Join potentially multiple text nodes and strip whitespace
            availability = "".join(availability_text).strip()

            yield {
                'title': book.css('h3 a::attr(title)').get(),
                'price': book.css('p.price_color::text').get(),
                'rating': rating_num, # Store the numeric rating
                # 'rating_text': rating_text, # Optionally store the original text too
                'availability': availability,
                'url': response.urljoin(book.css('h3 a::attr(href)').get())
            }

        # Find and follow the 'next' page link
        next_page_relative_url = response.css('li.next a::attr(href)').get()
        if next_page_relative_url:
            # Use response.follow to automatically handle relative URLs
            yield response.follow(next_page_relative_url, callback=self.parse)
            self.logger.info(f"Following next page: {next_page_relative_url}")
        else:
             self.logger.info("No next page link found. Reached the end.")
