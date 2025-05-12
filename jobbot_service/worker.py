import pika
import json
import time
import random
import logging
import keyboard
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pymongo import MongoClient
from webdriver_manager.chrome import ChromeDriverManager
from flask import Flask, request
import threading

# Setup logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
pause_event = threading.Event()
cancel_event = threading.Event()

class JobBotWorker:
    def __init__(self):
        self.options = Options()
        self.options.add_argument('--no-sandbox')
        self.options.add_argument('--disable-dev-shm-usage')
        self.options.add_argument('--disable-gpu')
        self.driver = webdriver.Chrome(service=ChromeDriverManager().install(), options=self.options)
        self.wait = WebDriverWait(self.driver, 10)
        self.mongo_client = MongoClient('mongodb://mongo:27017/')
        self.db = self.mongo_client['jobbot']
        self.connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue='job_tasks')

    def inject_timer(self, seconds):
        """Inject a countdown timer in the top-left corner."""
        timer_script = f"""
        var timerDiv = document.createElement('div');
        timerDiv.id = 'bot-timer';
        timerDiv.style.position = 'fixed';
        timerDiv.style.top = '10px';
        timerDiv.style.left = '10px';
        timerDiv.style.background = 'rgba(0, 0, 0, 0.7)';
        timerDiv.style.color = 'white';
        timerDiv.style.padding = '10px';
        timerDiv.style.zIndex = '9999';
        timerDiv.innerText = 'Paused: {seconds}s';
        document.body.appendChild(timerDiv);

        var countdown = {seconds};
        var interval = setInterval(function() {{
            countdown--;
            if (countdown <= 0) {{
                clearInterval(interval);
                timerDiv.remove();
            }} else {{
                timerDiv.innerText = 'Paused: ' + countdown + 's';
            }}
        }}, 1000);
        """
        self.driver.execute_script(timer_script)

    def remove_timer(self):
        """Remove the timer from the page."""
        self.driver.execute_script("""
        var timerDiv = document.getElementById('bot-timer');
        if (timerDiv) timerDiv.remove();
        """)

    def pause_for_interaction(self):
        """Pause automation for 10 seconds, allowing user interaction."""
        log.info("Pausing for user interaction...")
        self.inject_timer(10)
        pause_event.set()
        time.sleep(10)
        if cancel_event.is_set():
            log.info("Application cancelled by user")
            pause_event.clear()
            cancel_event.clear()
            return False
        self.remove_timer()
        pause_event.clear()
        log.info("Resuming automation...")
        return True

    def start(self):
        log.info('Starting JobBot Worker...')
        # Start Flask server for API-based pause
        threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 5002}, daemon=True).start()
        # Start keyboard listener for manual pause
        threading.Thread(target=self.keyboard_listener, daemon=True).start()
        self.channel.basic_consume(queue='job_tasks', on_message_callback=self.process_message, auto_ack=True)
        self.channel.start_consuming()

    def keyboard_listener(self):
        """Listen for Ctrl+P to pause or Ctrl+C to cancel."""
        while True:
            if keyboard.is_pressed('ctrl+p'):
                self.pause_for_interaction()
                while keyboard.is_pressed('ctrl+p'):
                    pass
            if keyboard.is_pressed('ctrl+c'):
                cancel_event.set()
                while keyboard.is_pressed('ctrl+c'):
                    pass

    def process_message(self, ch, method, properties, body):
        task = json.loads(body)
        user_id = task['user_id']
        job_id = task.get('job_id')
        user_data = self.db.users.find_one({'_id': user_id})
        if not user_data:
            log.error(f'User {user_id} not found')
            return

        try:
            self.apply_to_job(job_id, user_data)
        except Exception as e:
            log.error(f'Error applying to job {job_id}: {str(e)}')
            self.db.applications.update_one(
                {'user_id': user_id, 'job_id': job_id},
                {'$set': {'status': 'failed', 'error': str(e)}},
                upsert=True
            )

    def apply_to_job(self, job_id, user_data):
        # Login
        self.driver.get('https://www.linkedin.com/login')
        self.wait.until(EC.presence_of_element_located((By.NAME, 'session_key'))).send_keys(user_data['username'])
        self.driver.find_element(By.NAME, 'session_password').send_keys(user_data['password'])
        self.driver.find_element(By.CSS_SELECTOR, '.btn__primary--large').click()
        time.sleep(random.uniform(2, 4))

        # Navigate to job
        job_url = f'https://www.linkedin.com/jobs/view/{job_id}' if job_id else user_data['linkedin_search_url']
        self.driver.get(job_url)
        time.sleep(random.uniform(1, 2))

        # Apply if Easy Apply exists
        try:
            button = self.wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(@class, "jobs-apply")]/span[1]')))
            button.click()
            time.sleep(1)
            if not self.fill_form(user_data):
                return  # Cancelled by user
            self.submit_application(user_id, job_id)
        except Exception as e:
            log.info(f'No Easy Apply button or error: {str(e)}')
            self.db.applications.update_one(
                {'user_id': user_id, 'job_id': job_id},
                {'$set': {'status': 'skipped', 'reason': 'No Easy Apply'}},
                upsert=True
            )

    def fill_form(self, user_data):
        inputs = self.driver.find_elements(By.XPATH, '//input')
        for input_field in inputs:
            if pause_event.is_set():
                if not self.pause_for_interaction():
                    return False
            name = input_field.get_attribute('name').lower()
            if 'first' in name:
                input_field.send_keys('Utkrisht')
            elif 'last' in name:
                input_field.send_keys('Sharma')
            time.sleep(random.uniform(0.5, 1))

        if 'uploads' in user_data and 'Resume' in user_data['uploads']:
            upload = self.driver.find_element(By.CSS_SELECTOR, 'input[name="file"]')
            upload.send_keys(user_data['uploads']['Resume'])

        return True

    def submit_application(self, user_id, job_id):
        if pause_event.is_set():
            if not self.pause_for_interaction():
                return
        submit = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Submit application"]')))
        submit.click()
        time.sleep(2)
        self.db.applications.update_one(
            {'user_id': user_id, 'job_id': job_id},
            {'$set': {'status': 'submitted', 'timestamp': time.time()}},
            upsert=True
        )
        log.info(f'Application submitted for job {job_id}')

# API endpoint to trigger pause
@app.route('/pause', methods=['POST'])
def pause():
    pause_event.set()
    return {'message': 'Paused for 10 seconds'}

# API endpoint to cancel
@app.route('/cancel', methods=['POST'])
def cancel():
    cancel_event.set()
    return {'message': 'Application cancelled'}

if __name__ == '__main__':
    worker = JobBotWorker()
    worker.start()