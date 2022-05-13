import os
import time

from selenium.webdriver.chrome.options import Options
from selenium import webdriver
import audible
import isbnlib as isbnlib
from typing import List
from selenium.webdriver.common.by import By


class AudibleAPI:
    def __init__(self, auth_file: str = 'auth'):
        self.auth_file = 'auth'

        if not os.path.exists(auth_file):
            # Authorize and register in one step
            auth = audible.Authenticator.from_login(
                'victor.sonck@gmail.com',
                os.environ.get('AUDIBLE_PASS'),
                locale='uk',
                with_username=False
            )

            # Save credentials to file
            auth.to_file(auth_file)

        self.auth = audible.Authenticator.from_file(self.auth_file)
        self.client = audible.Client(self.auth)
        # self.country_codes = ["us", "uk"]
        self.country_codes = ["uk"]

        self.response_groups = "contributors, customer_rights, media, price, product_attrs, product_desc, " \
                               "product_details, product_extended_attrs, product_plan_details, product_plans, rating, "\
                               "sample, sku, series, reviews, ws4v, origin, relationships, review_attrs, categories, " \
                               "badge_types, category_ladders, claim_code_url, in_wishlist, is_archived, " \
                               "is_downloaded, is_finished, is_playable, is_removable, is_returnable, is_visible, " \
                               "listening_status, order_details, origin_asin, pdf_url, percent_complete, periodicals, "\
                               "provided_review "

    @classmethod
    def _map_goodreads_status(cls, book):
        if not book['is_finished']:
            return 'unfinished'
        if book['is_finished']:
            return 'read'

    def get_books(self) -> List[dict]:
        books = []
        for country in self.country_codes:
            self.client.switch_marketplace(country)
            library = self.client.get("library", response_groups=self.response_groups)
            for book in library["items"]:
                if book['isbn']:
                    print(f"{book['title']} by {book['authors'][0]['name']} has ISBN: {book['isbn']}")
                    book['UNSURE'] = False
                else:
                    probable_isbn = isbnlib.isbn_from_words(f"{book['title']} {book['authors'][0]['name']}")
                    print(f"[UNSURE] {book['title']} by {book['authors'][0]['name']} might have ISBN: {probable_isbn}")
                    book['UNSURE'] = True
                    book['isbn'] = probable_isbn
                book['expected_goodreads_shelf'] = self._map_goodreads_status(book)
                books.append(book)
        return books

def get_chrome_options() -> Options:
    """Sets chrome options for Selenium.
    Chrome options for headless browser is enabled.
    """
    chrome_options = Options()
    # chrome_options.add_argument("--headless")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--proxy-server='direct://'")
    chrome_options.add_argument("--proxy-bypass-list=*")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument('--lang=nl_BE')
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_prefs = dict()
    chrome_options.experimental_options["prefs"] = chrome_prefs
    chrome_prefs["profile.default_content_settings"] = {"images": 2}
    chrome_prefs["download.default_directory"] = "/content"
    return chrome_options


class GoodreadsBrowser:
    def __init__(self):
        self.current_isbn = None
        self.driver = webdriver.Chrome(options=get_chrome_options())
        self.authenticate()

    def authenticate(self):
        self.driver.get('https://www.goodreads.com/user/sign_in')
        # Find the login by email button and click it
        self.driver.find_element(By.XPATH, '//*[@id="choices"]/div/a[2]/button').click()
        # Type in login email
        self.driver.find_element(By.XPATH, '//*[@id="ap_email"]').send_keys(os.environ.get('GR_EMAIL'))
        # Type in password
        self.driver.find_element(By.XPATH, '//*[@id="ap_password"]').send_keys(os.environ.get('GR_PASSWORD'))
        # Press log in button
        self.driver.find_element(By.XPATH, '//*[@id="signInSubmit"]').click()

    def get_shelf(self, isbn, title=None, author=None):
        self.navigate_to_book_page(isbn)
        if self.driver.current_url.startswith('https://www.goodreads.com/search'):
            # We're still in the search page, which means the number was not found!
            print(f'ISBN {isbn} was not found on goodreads, trying title {title} and author {author}')
            # Most likely because it's an audiobook and not added to gr, so search the original ISBN and add that
            if title and author:
                probable_isbn = isbnlib.isbn_from_words(f"{title} {author}")
                second_try_isbn, second_try_shelf = self.get_shelf(probable_isbn)
                if second_try_shelf:
                    return second_try_isbn, second_try_shelf
            return None, None
        goodreads_state = self.driver.find_element(By.CSS_SELECTOR, ".wtrLeft").text
        goodreads_state_color = self.driver.find_element(By.CSS_SELECTOR, ".wtrLeft").value_of_css_property('background-color')
        # 'rgba(242, 242, 242, 1)' is already on shelf
        # 'rgba(64, 157, 105, 1)' is unseen book

        if goodreads_state == 'Read':
            return isbn, 'read'
        if goodreads_state == 'Currently Reading':
            return isbn, 'currently reading'
        if goodreads_state == 'unfinished':
            return isbn, 'unfinished'
        if goodreads_state == 'Want to Read' and goodreads_state_color == 'rgba(242, 242, 242, 1)':
            return isbn, 'want to read'
        if goodreads_state == 'Want to Read' and goodreads_state_color == 'rgba(64, 157, 105, 1)':
            return isbn, 'unread'

    def navigate_to_book_page(self, isbn):
        self.driver.get(f'https://www.goodreads.com/search?q={isbn}')
        self.current_isbn = isbn

    def set_shelf(self, isbn, shelf):
        if not self.current_isbn == isbn:
            self.navigate_to_book_page(isbn)
        # Click open green arrow
        self.driver.find_element(By.CSS_SELECTOR, ".wtrShelfButton").click()
        time.sleep(0.2)
        # Select the required shelf. In my case [read, currenlty-reading, to-read, unfinished]
        self.driver.find_element(By.XPATH, f"//li[@data-shelf-name='{shelf}']").click()
        # if shelf == 'read':
        #     # You'll get a popup asking for review, click away
        #     time.sleep(0.2)
        #     self.driver.find_element(By.XPATH, '//*[@id="close"]').click()
        pass

    def close(self):
        self.driver.close()


if __name__ == '__main__':
    audible_api = AudibleAPI()
    books = audible_api.get_books()
    goodreads_browser = GoodreadsBrowser()
    for book in books:
        if not book['isbn']:
            print(f"Book with title {book['title']} has no ISBN, skipping.")
        possibly_different_isbn, current_shelf = goodreads_browser.get_shelf(
            isbn=book['isbn'],
            title=book['title'],
            author=book['authors'][0]['name']
        )
        if not current_shelf:
            continue
        if book['expected_goodreads_shelf'] != current_shelf:
            goodreads_browser.set_shelf(isbn=possibly_different_isbn, shelf=book['expected_goodreads_shelf'])

    goodreads_browser.close()
