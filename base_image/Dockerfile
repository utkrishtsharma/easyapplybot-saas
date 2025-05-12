FROM python:3.9-slim

# Install dependencies required for Chrome and ChromeDriver
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome 136.0.7103.92 for Linux 64-bit
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/136.0.7103.92/linux64/chrome-linux64.zip \
    && unzip chrome-linux64.zip -d /usr/local/ \
    && ln -s /usr/local/chrome-linux64/chrome /usr/local/bin/google-chrome \
    && rm chrome-linux64.zip

# Install ChromeDriver 136.0.7103.92 for Linux 64-bit
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/136.0.7103.92/linux64/chromedriver-linux64.zip \
    && unzip chromedriver-linux64.zip -d /usr/local/bin/ \
    && mv /usr/local/bin/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && rm -rf chromedriver-linux64.zip /usr/local/bin/chromedriver-linux64

# Copy and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Set working directory
WORKDIR /app

# Keep container running for testing (adjust CMD as needed for your application)
CMD ["tail", "-f", "/dev/null"]