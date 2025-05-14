import cv2
import numpy as np
import yaml
import pandas as pd
import pyautogui
import time
import random
import os
import csv
import platform
import logging
import threading
import keyboard
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException, 
    NoSuchElementException, 
    StaleElementReferenceException
)
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.select import Select
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager

# Set up logging
log = logging.getLogger(__name__)

class EasyApplyBot:
    """LinkedIn Easy Apply Bot for automating job applications."""
    
    # Maximum search time (10 hours by default)
    MAX_SEARCH_TIME = 10 * 60 * 60
    
    def __init__(self, 
                 username, 
                 password, 
                 uploads={},
                 filename='output.csv',
                 blacklist=[],
                 blackListTitles=[],
                 user_data_dir=None,
                 linkedin_search_url=None):
        """
        Initialize the EasyApplyBot.
        
        Args:
            username (str): LinkedIn username/email
            password (str): LinkedIn password
            uploads (dict): Paths to upload files (e.g., resume)
            filename (str): Output CSV filename
            blacklist (list): List of companies to avoid
            blackListTitles (list): List of job title keywords to avoid
            user_data_dir (str): Path to Chrome user data directory
            linkedin_search_url (str): LinkedIn search URL
        """
        self.setup_logger()
        log.info("Welcome to Easy Apply Bot")
        dirpath = os.getcwd()
        log.info("Current directory is: " + dirpath)

        self.uploads = uploads
        past_ids = self.get_applied_ids(filename)
        self.applied_job_ids = past_ids if past_ids is not None else []
        self.filename = filename
        self.options = self.browser_options(user_data_dir)
        self.browser = self.setup_browser()
        self.wait = WebDriverWait(self.browser, 10)
        self.blacklist = blacklist
        self.blackListTitles = blackListTitles
        self.linkedin_search_url = linkedin_search_url
        self.is_paused = False
        self.pause_event = threading.Event()
        self.pause_event.set()  # Not paused initially
        
        self.setup_keyboard_listener()
        self.start_linkedin(username, password)

    def setup_logger(self):
        """Set up logging configuration"""
        dt = datetime.strftime(datetime.now(), "%m_%d_%y_%H_%M_%S")

        if not os.path.isdir('./logs'):
            os.mkdir('./logs')

        logging.basicConfig(
            filename=('./logs/' + str(dt) + '_applyJobs.log'), 
            filemode='w',
            format='%(asctime)s::%(name)s::%(levelname)s::%(message)s', 
            datefmt='%d-%b-%y %H:%M:%S'
        )
        log.setLevel(logging.DEBUG)
        
        c_handler = logging.StreamHandler()
        c_handler.setLevel(logging.DEBUG)
        c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
        c_handler.setFormatter(c_format)
        log.addHandler(c_handler)

    def setup_keyboard_listener(self):
        """Set up keyboard listeners for pause and resume"""
        threading.Thread(target=self.keyboard_listener, daemon=True).start()
    
    def keyboard_listener(self):
        """Listen for keyboard events to pause/resume the bot"""
        while True:
            if keyboard.is_pressed('p'):
                self.pause_bot("User pressed 'p' key")
                time.sleep(0.5)  # Debounce
            elif keyboard.is_pressed('r'):
                self.resume_bot("User pressed 'r' key")
                time.sleep(0.5)  # Debounce
            time.sleep(0.1)  # Reduce CPU usage
    
    def pause_bot(self, reason=""):
        """Pause the bot's operation"""
        if not self.is_paused:
            self.is_paused = True
            self.pause_event.clear()
            message = f"Bot PAUSED: {reason}"
            log.info(message)
            
            # Create and display pause notification on the browser
            self.display_notification("⏸️ BOT PAUSED - Press 'r' to resume", "yellow")
    
    def resume_bot(self, reason=""):
        """Resume the bot's operation"""
        if self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            message = f"Bot RESUMED: {reason}"
            log.info(message)
            
            # Remove the notification
            self.display_notification("▶️ BOT RESUMED", "green", duration=2)
    
    def display_notification(self, message, color="yellow", duration=None):
        """Display a notification in the browser window"""
        script = f"""
        var notification = document.getElementById('easy-apply-bot-notification');
        if (!notification) {{
            notification = document.createElement('div');
            notification.id = 'easy-apply-bot-notification';
            notification.style.position = 'fixed';
            notification.style.bottom = '20px';
            notification.style.left = '50%';
            notification.style.transform = 'translateX(-50%)';
            notification.style.padding = '10px 20px';
            notification.style.borderRadius = '5px';
            notification.style.fontWeight = 'bold';
            notification.style.zIndex = '9999';
            document.body.appendChild(notification);
        }}
        notification.textContent = '{message}';
        notification.style.backgroundColor = '{color}';
        notification.style.color = '{color}' === 'yellow' ? 'black' : 'white';
        notification.style.display = 'block';
        """
        
        try:
            self.browser.execute_script(script)
            if duration:
                threading.Timer(duration, lambda: self.browser.execute_script(
                    "var notification = document.getElementById('easy-apply-bot-notification'); "
                    "if (notification) { notification.style.display = 'none'; }"
                )).start()
        except Exception as e:
            log.error(f"Failed to display notification: {e}")

    def wait_if_paused(self):
        """Wait if the bot is paused"""
        self.pause_event.wait()

    def get_applied_ids(self, filename):
        """
        Load already applied job IDs from CSV file
        
        Args:
            filename (str): Path to the CSV file
            
        Returns:
            list: List of job IDs that have already been applied to
        """
        try:
            df = pd.read_csv(
                filename,
                header=None,
                names=['timestamp', 'jobID', 'job', 'company', 'attempted', 'result'],
                lineterminator='\n',
                encoding='utf-8'
            )

            job_ids = list(df.jobID)
            log.info(f"{len(job_ids)} jobIDs found in previous applications")
            return job_ids
        except Exception as e:
            log.info(f"{str(e)} - jobIDs could not be loaded from CSV {filename}")
            return None

    def browser_options(self, user_data_dir=None):
        """
        Configure Chrome browser options
        
        Args:
            user_data_dir (str): Path to Chrome user data directory
            
        Returns:
            Options: Configured Chrome options
        """
        options = Options()
        
        # Use default Chrome profile if specified
        if user_data_dir:
            options.add_argument(f"user-data-dir={user_data_dir}")
        
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")

        # Disable webdriver flags to avoid detection
        options.add_argument("--disable-blink-features")
        options.add_argument("--disable-blink-features=AutomationControlled")
        
        # Add a custom flag to identify the bot window
        options.add_argument("--window-name=LinkedInEasyApplyBot")
        
        return options
    
    def setup_browser(self):
        """
        Set up and return Chrome WebDriver
        
        Returns:
            WebDriver: Configured Chrome WebDriver
        """
        try:
            service = Service(ChromeDriverManager().install())
            browser = webdriver.Chrome(service=service, options=self.options)
            return browser
        except Exception as e:
            log.error(f"Error setting up browser: {e}")
            raise

    def start_linkedin(self, username, password):
        """
        Log in to LinkedIn account
        
        Args:
            username (str): LinkedIn username/email
            password (str): LinkedIn password
        """
        log.info("Logging in to LinkedIn... Please wait")
        self.browser.get("https://www.linkedin.com/login?trk=guest_homepage-basic_nav-header-signin")

        try:
            # Check if already logged in
            if "feed" in self.browser.current_url:
                log.info("Already logged in!")
                return
                
            user_field = self.browser.find_element(By.NAME, "session_key")
            pw_field = self.browser.find_element(By.NAME, "session_password")
            login_button = WebDriverWait(self.browser, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".btn__primary--large"))
            )

            user_field.send_keys(username)
            user_field.send_keys(Keys.TAB)
            time.sleep(1)
            pw_field.send_keys(password)
            time.sleep(1)
            login_button.click()
            
            # Add 10-second pause for verification after login
            log.info("Pausing for 10 seconds to allow for login verification...")
            time.sleep(10)
            
            # Check if there's a verification challenge
            if "checkpoint" in self.browser.current_url or "challenge" in self.browser.current_url:
                self.pause_bot("Security verification detected. Please complete the verification and then press 'r' to resume.")
                
        except Exception as e:
            log.error(f"Error during login: {str(e)}")
            self.pause_bot("Login error. Please login manually and press 'r' to resume.")

    def start_apply(self, positions, locations, date_range="r2592000"):
        """
        Start applying to jobs based on positions and locations
        
        Args:
            positions (list): List of job positions
            locations (list): List of job locations
            date_range (str): LinkedIn date range filter (default: last 30 days)
        """
        start = time.time()
        self.fill_data()

        # Generate position-location combinations
        combos = []
        for position in positions:
            for location in locations:
                combos.append((position, location))
                
        # Randomize order for natural behavior
        random.shuffle(combos)
        
        for position, location in combos:
            log.info(f"Applying to {position}: {location}")
            self.wait_if_paused()
            
            # Create search URL with filters
            search_url = self.build_search_url(position, location, date_range)
            self.applications_loop(position, location, search_url)

    def build_search_url(self, position, location, date_range="r2592000"):
        """
        Build LinkedIn search URL with all necessary filters
        
        Args:
            position (str): Job position
            location (str): Job location
            date_range (str): LinkedIn date range filter
            
        Returns:
            str: Formatted search URL
        """
        # Encode parameters for URL
        position_encoded = position.replace(' ', '%20')
        location_encoded = location.replace(' ', '%20')
        
        # Build search URL with filters:
        # f_AL=true: Easy Apply only
        # f_TPR=r2592000: Last 30 days (adjustable)
        url = (
            f"https://www.linkedin.com/jobs/search/?f_AL=true&f_TPR={date_range}"
            f"&keywords={position_encoded}&location={location_encoded}"
        )
        
        return url

    def applications_loop(self, position, location, search_url):
        """
        Main loop for applying to jobs
        
        Args:
            position (str): Job position
            location (str): Job location
            search_url (str): LinkedIn search URL
        """
        count_application = 0
        count_job = 0
        jobs_per_page = 0
        start_time = time.time()

        log.info("Looking for jobs.. Please wait..")

        self.browser.set_window_position(1, 1)
        self.browser.maximize_window()
        
        # If we have a custom LinkedIn search URL, use that instead
        url_to_use = self.linkedin_search_url if self.linkedin_search_url else search_url
        self.browser.get(url_to_use)
        time.sleep(3)
        
        while time.time() - start_time < self.MAX_SEARCH_TIME:
            self.wait_if_paused()
            
            log.info(f"{int((self.MAX_SEARCH_TIME - (time.time() - start_time)) // 60)} minutes left in this search")

            # Sleep to make sure everything loads, add random to make us look human
            randoTime = random.uniform(2, 4)
            log.debug(f"Sleeping for {round(randoTime, 1)}")
            time.sleep(randoTime)
            
            # Scroll through job listings
            try:
                self.scroll_job_listings()
            except TimeoutException:
                log.info("Could not find job list element. Continuing without scrolling.")

            time.sleep(2)
            job_listings = self.get_job_listings()
            
            if len(job_listings) == 0:
                log.info("No job listings found. Moving to next page or ending search.")
                break

            job_ids = self.extract_job_ids(job_listings)
            
            # Filter out jobs that have already been applied to
            new_job_ids = [x for x in job_ids if x not in self.applied_job_ids]
            
            log.info(f"Found {len(job_ids)} jobs, {len(new_job_ids)} are new")
            
            if len(new_job_ids) == 0 and len(job_ids) > 23:
                jobs_per_page = jobs_per_page + 25
                count_job = 0
                self.avoid_lock()
                self.go_to_next_jobs_page(position, location, jobs_per_page)
                continue

            for i, job_id in enumerate(new_job_ids):
                self.wait_if_paused()
                count_job += 1
                self.get_job_page(job_id)

                button = self.get_easy_apply_button()
                if button is not False:
                    if any(word in self.browser.title for word in self.blackListTitles):
                        log.info('Skipping this application, a blacklisted keyword was found in the job position')
                        string_easy = "* Contains blacklisted keyword"
                        result = False
                    else:
                        try:
                            string_easy = "* Has Easy Apply Button"
                            log.info("Clicking the EASY apply button")
                            button.click()
                            time.sleep(1.2)
                            result = self.send_resume()
                            count_application += 1
                        except Exception as e:
                            log.error(f"Error while clicking the EASY apply button: {str(e)}")
                            result = False
                else:
                    log.info("The Easy Apply button does not exist.")
                    string_easy = "* Doesn't have Easy Apply Button"
                    result = False
                
                time.sleep(2.2)
                position_number = str(count_job + jobs_per_page)
                log.info(f"\nPosition {position_number}:\n {self.browser.title} \n {string_easy} \n")

                self.write_to_file(button, job_id, self.browser.title, result)

                # Take a break every 20 applications
                if count_application != 0 and count_application % 20 == 0:
                    sleepTime = random.randint(3, 4) * 60  # Sleep for 3-4 minutes
                    log.info(f"Applied to {count_application} jobs. Taking a {sleepTime//60} minute break.")
                    time.sleep(sleepTime)

                # Go to next page if we've processed all jobs on current page
                if count_job == len(new_job_ids):
                    jobs_per_page = jobs_per_page + 25
                    count_job = 0
                    log.info("Going to next jobs page...")
                    self.avoid_lock()
                    self.go_to_next_jobs_page(position, location, jobs_per_page)

    def scroll_job_listings(self):
        """Scroll through job listings to load all content"""
        scrollresults = WebDriverWait(self.browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".jobs-search-results-list, .jobs-search-results__list"))
        )
        self.browser.execute_script("arguments[0].scrollIntoView(true);", scrollresults)
        
        # Smooth scroll to load all job listings
        for i in range(300, 3000, 100):
            self.browser.execute_script("window.scrollBy(0, {})".format(i))
            time.sleep(0.5)

    def get_job_listings(self):
        """Get all job listings from the page"""
        try:
            links = WebDriverWait(self.browser, 10).until(
                EC.presence_of_all_elements_located((By.XPATH, '//div[@data-job-id]'))
            )
            return links
        except TimeoutException:
            return []

    def extract_job_ids(self, links):
        """Extract job IDs from job listings"""
        ids = set()
        
        for link in links:
            children = link.find_elements(by=By.XPATH, value='.//a[@data-control-id]')

            for child in children:
                if child.text not in self.blacklist:
                    temp = link.get_attribute("data-job-id")
                    job_id = temp.split(":")[-1]
                    ids.add(int(job_id))
        
        return list(ids)

    def write_to_file(self, button, job_id, browser_title, result):
        """
        Write job application result to CSV file
        
        Args:
            button (WebElement): Easy Apply button
            job_id (int): Job ID
            browser_title (str): Browser title containing job info
            result (bool): Application result
        """
        import re
        
        def re_extract(text, pattern):
            target = re.search(pattern, text)
            if target:
                target = target.group(1)
            return target

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        attempted = False if button == False else True
        
        title_parts = browser_title.split(' | ')
        job = re_extract(title_parts[0], r"\(?\d?\)?\s?(\w.*)")
        company = re_extract(title_parts[-1], r"(\w.*)") if len(title_parts) > 1 else "Unknown"
        
        # Only add successful applications to the file
        if result:
            to_write = [timestamp, job_id, job, company, attempted, result]
            
            # Append job ID to applied list to avoid reapplying
            if job_id not in self.applied_job_ids:
                self.applied_job_ids.append(job_id)
            
            with open(self.filename, 'a') as f:
                writer = csv.writer(f)
                writer.writerow(to_write)

    def get_job_page(self, job_id):
        """
        Navigate to specific job page
        
        Args:
            job_id (int): Job ID
        """
        job_url = 'https://www.linkedin.com/jobs/view/' + str(job_id)
        self.browser.get(job_url)
        self.load_page(sleep=2)

    def get_easy_apply_button(self):
        """
        Find the Easy Apply button on the job page
        
        Returns:
            WebElement or False: Easy Apply button if found, False otherwise
        """
        try:
            button = self.browser.find_elements(By.XPATH, '//button[contains(@class, "jobs-apply")]/span[1]')
            if button and len(button) >= 2:
                return button[1]
            else:
                log.info("Easy Apply button not found or not accessible")
                return False
        except NoSuchElementException:
            log.info("No Easy Apply button found")
            return False
        except Exception as e:
            log.error(f"Error while finding Easy Apply button: {str(e)}")
            return False

    def send_resume(self):
        """
        Complete the job application form
        
        Returns:
            bool: True if application submitted successfully, False otherwise
        """
        def is_present(button_locator):
            return len(self.browser.find_elements(button_locator[0], button_locator[1])) > 0

        try:
            time.sleep(random.uniform(1.0, 1.5))
            self.load_page()
            
            # Define form field locators
            first_name_locator = (By.XPATH, "//input[contains(@id, 'first-name') or contains(@name, 'first')]")
            last_name_locator = (By.XPATH, "//input[contains(@id, 'last-name') or contains(@name, 'last')]")
            city_locator = (By.XPATH, "//input[contains(@id, 'city') or contains(@name, 'city')]")
            phone_locator = (By.XPATH, "//*[contains(@id, 'phoneNumber-nationalNumber')]")
            
            next_locator = (By.CSS_SELECTOR, "button[aria-label='Continue to next step']")
            review_locator = (By.CSS_SELECTOR, "button[aria-label='Review your application']")
            submit_locator = (By.CSS_SELECTOR, "button[aria-label='Submit application']")
            submit_application_locator = (By.CSS_SELECTOR, "button[aria-label='Submit application'][class*='artdeco-button--primary']")
            
            error_locator = (By.XPATH, "//*[contains(@id, 'error')]")
            upload_locator = (By.CSS_SELECTOR, "input[name='file']")
            question_locator = (By.XPATH, "//*[contains(@id, 'single-line-text-form-component')]")
            radio_locator = (By.XPATH, "//*[contains(@id, 'radio-button-form-component-formElement')]")
            multiple_choice_locator = (By.XPATH, "//*[contains(@id, 'text-entity-list-form')]")
            text_selectable_option_locator = (By.XPATH, "//div[contains(@class, 'fb-text-selectable__option')]")
            label_locator = (By.XPATH, "//label[contains(text(), 'I')]")
            
            def scroll_to_bottom():
                """Scroll to the bottom of the page"""
                self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
            
            submitted = False
            
            # Check for form errors that might require manual intervention
            def check_for_errors():
                if is_present(error_locator):
                    errors = self.browser.find_elements(error_locator[0], error_locator[1])
                    if errors:
                        error_text = " | ".join([e.text for e in errors if e.text])
                        if error_text:
                            self.pause_bot(f"Form error detected: {error_text}. Please fix manually and press 'r' to resume.")
                            return True
                return False
            
            while True:
                self.wait_if_paused()
                
                # Check for errors that might need manual intervention
                if check_for_errors():
                    time.sleep(10)  # Give time for manual correction
                
                scroll_to_bottom()
                
                button = None
                buttons = [next_locator, review_locator, submit_locator, submit_application_locator]
                
                # Fill form fields
                if is_present(first_name_locator):
                    first_name = self.browser.find_element(first_name_locator[0], first_name_locator[1])
                    first_name.clear()
                    first_name.send_keys("Utkrisht")
                    time.sleep(0.5)
                
                if is_present(last_name_locator):
                    last_name = self.browser.find_element(last_name_locator[0], last_name_locator[1])
                    last_name.clear()
                    last_name.send_keys("Sharma")
                    time.sleep(0.5)
                
                if is_present(city_locator):
                    city_input = self.browser.find_element(city_locator[0], city_locator[1])
                    city_input.clear()
                    city_input.send_keys("San Francisco, California, United States")
                    time.sleep(0.5)

                if is_present(radio_locator):
                    radios = self.browser.find_elements(by=By.XPATH, value="//*[contains(@id, 'radio-button-form-component-formElement')]/div[1]/label")
                    for radio in radios:
                        try:
                            radio.click()
                            time.sleep(1)
                        except Exception as e:
                            log.debug(f"Error clicking radio button: {str(e)}")
                    time.sleep(1.5)

                if is_present(text_selectable_option_locator):
                    text_selectable_options = self.browser.find_elements(text_selectable_option_locator[0], text_selectable_option_locator[1])
                    for option in text_selectable_options:
                        try:
                            self.browser.execute_script("arguments[0].scrollIntoView();", option)
                            option.click()
                            time.sleep(1)
                        except StaleElementReferenceException:
                            log.debug("Stale element reference exception occurred. Continuing with the next element.")
                            continue             
                                    
                if is_present(label_locator):
                    label_elements = self.browser.find_elements(label_locator[0], label_locator[1])
                    for label_element in label_elements:
                        try:
                            self.browser.execute_script("arguments[0].scrollIntoView(true);", label_element)
                            label_element.click()
                            time.sleep(0.5)
                        except StaleElementReferenceException:
                            log.debug("Stale element reference exception occurred while clicking the label.")

                if is_present(multiple_choice_locator):
                    mcq = self.browser.find_elements(by=By.XPATH, value="//*[contains(@id, 'text-entity-list-form')]")
                    mcq_exception = self.browser.find_elements(by=By.XPATH, value="//*[contains(@id, 'phoneNumber-country')]")
                    mcq = [x for x in mcq if x not in mcq_exception]
                    
                    for i in range(len(mcq)):
                        try:
                            mcqq = Select(mcq[i])
                            mcqq.select_by_index(1)
                            time.sleep(1)
                        except Exception as e:
                            log.debug(f"Error selecting dropdown option: {str(e)}")

                if is_present(phone_locator):
                    number = self.browser.find_element(by=By.XPATH, value="//*[contains(@id, 'phoneNumber-nationalNumber')]")
                    number.clear()
                    number.send_keys("+1(415)9006948")
                    number.send_keys(Keys.TAB)
                    time.sleep(0.5)

                if is_present(question_locator):
                    questions = self.browser.find_elements(By.XPATH, "//input[contains(@id, 'single-line-text-form-component')]")
                    questions_exception = self.browser.find_elements(By.XPATH, "//input[contains(@id, 'phoneNumber-nationalNumber')]")
                    questions = [x for x in questions if x not in questions_exception]

                    for question in questions:
                        self.browser.implicitly_wait(0.5)
                        question.clear()
                        
                        # Check the name/ID attribute to determine what type of field it is
                        field_id = question.get_attribute('id').lower()
                        field_name = question.get_attribute('name').lower() if question.get_attribute('name') else ""
                        
                        if 'first' in field_id or 'first' in field_name:
                            question.send_keys("Utkrisht")
                        elif 'last' in field_id or 'last' in field_name:
                            question.send_keys("Sharma")
                        else:
                            # Default for other fields
                            question.send_keys(str(random.randint(4, 7)))
                        
                        question.send_keys(Keys.TAB)
                        time.sleep(0.5)
                
                if is_present(upload_locator):
                    input_buttons = self.browser.find_elements(upload_locator[0], upload_locator[1])
                    for input_button in input_buttons:
                        try:
                            resume_path = self.uploads.get("Resume", "")
                            if resume_path and os.path.exists(resume_path):
                                input_button.send_keys(resume_path)
                                time.sleep(2)
                            else:
                                log.error(f"Resume file not found at {resume_path}")
                                self.pause_bot("Resume file missing. Please fix the path and press 'r' to resume.")
                        except Exception as e:
                            log.error(f"Error uploading resume: {str(e)}")

                # Find next action button
                for button_locator in buttons:
                    if is_present(button_locator):
                        button = self.browser.find_element(button_locator[0], button_locator[1])
                        break
                
                if button is None:
                    log.info("No next, review, or submit button found. Stopping application.")
                    return False
                
                button_text = button.text.lower()
                log.info(f"Found button: {button_text}")
                
                # Check if it's the final submit button
                if "submit" in button_text:
                    try:
                        self.browser.execute_script("arguments[0].scrollIntoView(true);", button)
                        button.click()
                        submitted = True
                        log.info("Application submitted successfully!")
                        
                        # Wait for confirmation
                        time.sleep(random.uniform(2.5, 3.5))
                        return True
                    except Exception as e:
                        log.error(f"Error submitting application: {str(e)}")
                        return False
                else:
                    # Click next/review button and continue
                    try:
                        self.browser.execute_script("arguments[0].scrollIntoView(true);", button)
                        button.click()
                        time.sleep(random.uniform(1.5, 2.5))
                    except Exception as e:
                        log.error(f"Error clicking button: {str(e)}")
                        return False
                
                # If we can't find any buttons after several attempts, end the process
                if not any(is_present(loc) for loc in buttons):
                    if submitted:
                        return True
                    log.info("No more buttons found. Application may be incomplete.")
                    return False
                
        except Exception as e:
            log.error(f"Error during application process: {str(e)}")
            return False

    def fill_data(self):
        """Fill out job preferences data"""
        self.resume = self.uploads.get("Resume", "")
        log.info(f"Resume path: {self.resume}")

    def go_to_next_jobs_page(self, position, location, jobs_per_page):
        """
        Navigate to the next page of job listings
        
        Args:
            position (str): Job position
            location (str): Job location
            jobs_per_page (int): Number of jobs per page
        """
        search_url = self.build_search_url(position, location)
        self.browser.get(f"{search_url}&start={jobs_per_page}")
        
        # Random sleep to mimic human behavior
        time.sleep(random.uniform(2.5, 4.0))

    def avoid_lock(self):
        """Avoid LinkedIn locking by adding random actions"""
        if random.random() > 0.85:
            action = random.randint(1, 3)
            if action == 1:
                # Scroll up and down
                log.info("Performing random scroll")
                self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
                time.sleep(random.uniform(1, 2))
                self.browser.execute_script("window.scrollTo(0, document.body.scrollHeight/4);")
            elif action == 2:
                # Wait for random time
                sleep_time = random.uniform(2, 4)
                log.info(f"Performing random wait for {sleep_time:.1f}s")
                time.sleep(sleep_time)
            else:
                # Click somewhere neutral
                try:
                    footer = self.browser.find_element(By.TAG_NAME, "footer")
                    self.browser.execute_script("arguments[0].scrollIntoView();", footer)
                    time.sleep(random.uniform(0.5, 1))
                    self.browser.execute_script("window.scrollBy(0, -200);")
                except:
                    pass
            
    def load_page(self, sleep=1):
        """
        Wait for page to load
        
        Args:
            sleep (int): Time to sleep in seconds
        """
        scroll_page = 0
        while scroll_page < 4000:
            self.browser.execute_script("window.scrollTo(0, {0});".format(scroll_page))
            scroll_page += 200
            time.sleep(sleep/10)
        
        # Scroll back to top
        self.browser.execute_script("window.scrollTo(0, 0);")
        time.sleep(sleep)

    def generate_report(self):
        """Generate a report of application statistics"""
        try:
            df = pd.read_csv(self.filename)
            total_applications = len(df)
            success_applications = len(df[df['result'] == True])
            
            log.info("\n==== Application Summary ====")
            log.info(f"Total applications: {total_applications}")
            log.info(f"Successful applications: {success_applications}")
            log.info(f"Success rate: {success_applications/total_applications*100:.2f}%")
            
            # Company statistics
            companies = df['company'].value_counts().head(5)
            log.info("\nTop companies applied to:")
            for company, count in companies.items():
                log.info(f"- {company}: {count}")
            
            # Save report to file
            report_file = 'application_report.txt'
            with open(report_file, 'w') as f:
                f.write("LinkedIn Easy Apply Bot - Application Report\n")
                f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total applications: {total_applications}\n")
                f.write(f"Successful applications: {success_applications}\n")
                f.write(f"Success rate: {success_applications/total_applications*100:.2f}%\n\n")
                
                f.write("Top companies applied to:\n")
                for company, count in companies.items():
                    f.write(f"- {company}: {count}\n")
            
            log.info(f"Report saved to {report_file}")
        except Exception as e:
            log.error(f"Error generating report: {str(e)}")

    def close(self):
        """Close the browser and perform cleanup"""
        try:
            log.info("Closing browser...")
            self.browser.quit()
            log.info("Browser closed successfully")
        except Exception as e:
            log.error(f"Error closing browser: {str(e)}")

def parse_config(config_file):
    """
    Parse YAML configuration file
    
    Args:
        config_file (str): Path to config file
        
    Returns:
        dict: Configuration dictionary
    """
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        log.error(f"Error parsing config file: {str(e)}")
        return None

def main():
    """Main function to run the LinkedIn Easy Apply Bot"""
    import argparse
    
    parser = argparse.ArgumentParser(description='LinkedIn Easy Apply Bot')
    parser.add_argument('--config', type=str, help='Path to config file', default='config.yaml')
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    log.info("Starting LinkedIn Easy Apply Bot")
    
    # Parse config
    config = parse_config(args.config)
    if not config:
        log.error("Failed to parse config file. Exiting.")
        return
    
    try:
        # Get credentials and configuration directly from the root of the YAML
        username = config.get('username')
        password = config.get('password')
        
        if not username or not password:
            log.error("LinkedIn username or password not provided in config. Exiting.")
            return
        
        # Get other parameters
        uploads = config.get('uploads', {})
        positions = config.get('positions', [])
        locations = config.get('locations', [])
        blacklist = config.get('blacklist', [])
        blacklist_titles = config.get('blackListTitles', [])  # Note the exact key match
        linkedin_search_url = config.get('linkedin_search_url')
        filename = config.get('output_filename', 'output.csv')
        user_data_dir = config.get('user_data_dir')
        
        # Initialize bot with the correct parameters
        bot = EasyApplyBot(
            username=username,
            password=password,
            uploads=uploads,
            filename=filename,
            blacklist=blacklist,
            blackListTitles=blacklist_titles,
            user_data_dir=user_data_dir,
            linkedin_search_url=linkedin_search_url
        )
        
        # Start applying for jobs
        bot.start_apply(positions, locations)
        
        # Generate report
        bot.generate_report()
        
        # Close the bot
        bot.close()
        
    except KeyboardInterrupt:
        log.info("Bot was manually interrupted")
        try:
            bot.close()
        except:
            pass
    except Exception as e:
        log.error(f"Error running bot: {str(e)}")

if __name__ == "__main__":
    main()
