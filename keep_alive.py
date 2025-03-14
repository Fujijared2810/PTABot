from flask import Flask, render_template_string
from threading import Thread
from datetime import datetime, timedelta
import platform
import os
import time

app = Flask('')

# Track when the server started
START_TIME = datetime.now()

# Track the last heartbeat from the bot
LAST_HEARTBEAT = datetime.now()
BOT_STATUS = "ONLINE"  # Default status when server starts

# HTML template with embedded CSS for a professional look
TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PTA Bot Status</title>
    <style>
        body {
            font-family: 'Arial', sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e6e6e6;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .container {
            background-color: rgba(30, 41, 59, 0.8);
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
            padding: 2rem;
            width: 90%;
            max-width: 600px;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .status {
            display: inline-block;
            padding: 0.5rem 1.5rem;
            color: white;
            border-radius: 50px;
            font-weight: bold;
            margin: 1rem 0;
            animation: pulse 2s infinite;
        }
        .status.online {
            background-color: #10b981;
        }
        .status.offline {
            background-color: #ef4444;
        }
        @keyframes pulse {
            0% {
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
            }
            70% {
                box-shadow: 0 0 0 10px rgba(16, 185, 129, 0);
            }
            100% {
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
            }
        }
        .logo {
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 1rem;
            color: #60a5fa;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
        }
        .info {
            background-color: rgba(17, 24, 39, 0.7);
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1.5rem;
            text-align: left;
            border-left: 4px solid #60a5fa;
        }
        .info p {
            margin: 0.5rem 0;
            display: flex;
            justify-content: space-between;
        }
        .footer {
            margin-top: 2rem;
            font-size: 0.8rem;
            color: #9ca3af;
        }
        .value {
            color: #60a5fa;
            font-family: 'Courier New', monospace;
        }
        .refresh {
            margin-top: 1.5rem;
            color: #9ca3af;
            font-size: 0.8rem;
        }
        .refresh-btn {
            display: inline-block;
            margin-top: 0.5rem;
            padding: 0.5rem 1rem;
            background-color: #3b82f6;
            color: white;
            border-radius: 4px;
            text-decoration: none;
            font-size: 0.9rem;
            transition: background-color 0.3s;
        }
        .refresh-btn:hover {
            background-color: #2563eb;
        }
        .last-seen {
            margin-top: 0.5rem;
            font-style: italic;
            color: #9ca3af;
        }
    </style>
    <script>
        // Auto-refresh the page every 30 seconds
        setTimeout(function() {
            window.location.reload();
        }, 30000);
    </script>
</head>
<body>
    <div class="container">
        <div class="logo">🏫 Prodigy Trading Academy</div>
        <h1>Bot Status Monitor</h1>
        <div class="status {{ status_class }}">{{ status }}</div>
        <p>{{ status_message }}</p>
        {% if status == "OFFLINE" %}
            <p class="last-seen">Last seen: {{ last_seen }}</p>
        {% endif %}
        
        <div class="info">
            <p>
                <span>Server Time:</span>
                <span class="value">{{ time }}</span>
            </p>
            <p>
                <span>Environment:</span>
                <span class="value">{{ platform }}</span>
            </p>
            <p>
                <span>Uptime:</span>
                <span class="value">{{ uptime }}</span>
            </p>
            <p>
                <span>Last Heartbeat:</span>
                <span class="value">{{ heartbeat }}</span>
            </p>
        </div>
        
        <div class="refresh">
            This page auto-refreshes every 30 seconds.
            <br>
            <a href="/" class="refresh-btn">Refresh Now</a>
        </div>
        
        <div class="footer">
            © {{ year }} Prodigy Trading Academy | Bot Version: Alpha Release 3.0
        </div>
    </div>
</body>
</html>
'''

def update_heartbeat():
    """Function for the bot to call periodically to update its status"""
    global LAST_HEARTBEAT, BOT_STATUS
    LAST_HEARTBEAT = datetime.now()
    BOT_STATUS = "ONLINE"

def set_offline():
    """Function to explicitly mark the bot as offline"""
    global BOT_STATUS
    BOT_STATUS = "OFFLINE"

@app.route('/')
def home():
    global LAST_HEARTBEAT, BOT_STATUS
    
    # Calculate uptime
    uptime = datetime.now() - START_TIME
    days, seconds = uptime.days, uptime.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
    
    # Current time
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Check if the heartbeat is recent (within 60 seconds)
    # If not, consider the bot offline
    time_since_heartbeat = datetime.now() - LAST_HEARTBEAT
    if time_since_heartbeat.total_seconds() > 60:
        status = "OFFLINE"
        status_class = "offline"
        status_message = "The PTA Student Bot is currently offline or experiencing issues."
    else:
        status = BOT_STATUS
        status_class = "online" if status == "ONLINE" else "offline"
        status_message = "The PTA Student Bot is currently running and serving members."
    
    # Format last heartbeat time
    heartbeat_time = LAST_HEARTBEAT.strftime('%Y-%m-%d %H:%M:%S')
    last_seen = heartbeat_time  # For the "Last seen" message when offline
    
    # Render the HTML template with dynamic data
    return render_template_string(
        TEMPLATE, 
        time=current_time,
        platform=f"{platform.system()} {platform.release()}",
        uptime=uptime_str,
        year=datetime.now().year,
        status=status,
        status_class=status_class,
        status_message=status_message,
        heartbeat=heartbeat_time,
        last_seen=last_seen
    )

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():  
    t = Thread(target=run)
    t.daemon = True  # Set as daemon so it exits when the main thread exits
    t.start()
    
    # Start heartbeat thread
    heartbeat_thread = Thread(target=heartbeat_loop)
    heartbeat_thread.daemon = True
    heartbeat_thread.start()
    
    return update_heartbeat  # Return the function for the bot to call

def heartbeat_loop():
    """Background thread that updates the heartbeat while the bot is alive"""
    while True:
        # The bot will call update_heartbeat() from its main thread
        # This function just sleeps and continues the loop
        time.sleep(10)  # Sleep for 10 seconds