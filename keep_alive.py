from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session, flash
from threading import Thread
import logging
import io
import sys
from datetime import datetime
import pytz
import json
import werkzeug.serving
import os
import secrets
from functools import wraps
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import requests

os.environ['TZ'] = 'Asia/Manila'

# Modify Werkzeug logger to be less verbose
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)  # Only show errors, not regular requests

# Create a filter to ignore logs from /logs/data endpoint
class EndpointFilter(logging.Filter):
    def filter(self, record):
        # Skip log records for /logs/data endpoint requests
        return 'GET /logs/data' not in record.getMessage()

# Apply filter to the Werkzeug logger
werkzeug_logger.addFilter(EndpointFilter())

load_dotenv()

app = Flask('')
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))  # Generate random key or use environment variable

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')  # Change this to a strong password

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            # Store the requested URL for redirecting after login
            session['next_url'] = request.path
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Disable Flask default logging for non-errors
app.logger.setLevel(logging.ERROR)

# Create a StringIO object to capture logs
class WebLoggingHandler(logging.Handler):
    def __init__(self, max_entries=1000):
        super().__init__()
        self.log_entries = []
        self.max_entries = max_entries
        
    def emit(self, record):
        try:
            # Skip logging Flask's internal logs about /logs/data requests
            if 'GET /logs/data' in record.getMessage():
                return
                
            # Format the record
            log_entry = self.format(record)
            
            # Get log level for filtering
            level_name = record.levelname
            
            # Create timestamp with correct timezone and format
            manila_tz = pytz.timezone('Asia/Manila')
            timestamp = datetime.fromtimestamp(record.created)
            # Convert to Manila timezone first
            timestamp = manila_tz.localize(timestamp) if timestamp.tzinfo is None else timestamp.astimezone(manila_tz)
            formatted_time = timestamp.strftime('%Y-%m-%d %I:%M:%S %p')
            
            # Store both formatted log and metadata
            log_data = {
                'message': log_entry,
                'level': level_name,
                'timestamp': formatted_time
            }
            
            # Add to the beginning for reverse chronological order
            self.log_entries.insert(0, log_data)
            
            # Trim if exceeded max entries
            if len(self.log_entries) > self.max_entries:
                self.log_entries = self.log_entries[:self.max_entries]
        except Exception:
            self.handleError(record)

# Create the handler
web_handler = WebLoggingHandler(max_entries=1000)
web_handler.setLevel(logging.INFO)

# Create formatter
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
web_handler.setFormatter(formatter)

# Get the root logger and add our handler
root_logger = logging.getLogger()
root_logger.addHandler(web_handler)

# HTML template for the logs page - modern and professional design
LOGS_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PTABot Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
        <style>
        :root {
            --primary-color: #6D5AE6;
            --primary-dark: #5747C9;
            --secondary-color: #22B8CF;
            --dark-bg: #131722;
            --card-bg: #1E222D;
            --text-color: #F9FAFB;
            --muted-text: #9CA3AF;
            --border-color: #2D3748;
            --success-color: #10B981;
            --warning-color: #FBBF24;
            --error-color: #EF4444;
            --info-color: #3B82F6;
            --critical-color: #EC4899;
        }
        
        body {
            background-color: var(--dark-bg);
            color: var(--text-color);
            font-family: 'Inter', 'Segoe UI', sans-serif;
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .navbar {
            background-color: var(--dark-bg) !important;
            border-bottom: 1px solid var(--border-color);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            padding: 0.75rem 1.5rem;
        }
        
        .navbar-brand {
            color: var(--primary-color) !important;
            font-weight: 700;
            font-size: 1.5rem;
            letter-spacing: -0.5px;
        }
        
        .navbar-dark .navbar-nav .nav-link {
            color: var(--text-color);
            font-weight: 500;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            transition: all 0.2s ease;
        }
        
        .navbar-dark .navbar-nav .nav-link:hover,
        .navbar-dark .navbar-nav .nav-link.active {
            color: var(--primary-color);
            background-color: rgba(109, 90, 230, 0.1);
        }
        
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.12);
            margin-bottom: 24px;
            border-radius: 12px;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 20px rgba(0, 0, 0, 0.18);
        }
        
        .card-header {
            background-color: rgba(0, 0, 0, 0.15);
            border-bottom: 1px solid var(--border-color);
            font-weight: 600;
            color: var(--primary-color);
            padding: 1rem 1.25rem;
        }
        
        .card-body {
            padding: 1.25rem;
        }
        
        .btn {
            font-weight: 500;
            border-radius: 8px;
            padding: 0.5rem 1rem;
            transition: all 0.3s ease;
        }
        
        .btn-primary {
            background-color: var(--primary-color);
            border-color: var(--primary-dark);
        }
        
        .btn-primary:hover {
            background-color: var(--primary-dark);
            border-color: var(--primary-dark);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(109, 90, 230, 0.3);
        }
        
        .btn-outline-secondary {
            color: var(--text-color);
            border-color: var(--border-color);
        }
        
        .btn-outline-secondary:hover {
            background-color: rgba(255, 255, 255, 0.05);
            color: var(--primary-color);
            border-color: var(--primary-color);
        }
        
        .btn-outline-danger:hover {
            box-shadow: 0 4px 8px rgba(239, 68, 68, 0.3);
        }
        
        .log-entry {
            padding: 12px 16px;
            margin-bottom: 10px;
            border-radius: 8px;
            border-left: 4px solid transparent;
            background-color: rgba(0, 0, 0, 0.2);
            transition: all 0.2s ease;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        
        .log-entry:hover {
            background-color: rgba(0, 0, 0, 0.3);
            transform: translateX(2px);
        }
        
        .log-level {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 6px;
            margin-right: 10px;
            font-weight: 600;
            font-size: 0.85rem;
            width: 80px;
            text-align: center;
        }
        
        .log-timestamp {
            color: var(--muted-text);
            margin-right: 10px;
            font-size: 0.9em;
            font-weight: 500;
        }
        
        .log-info {
            border-left-color: var(--success-color);
        }
        
        .log-info .log-level {
            background-color: rgba(16, 185, 129, 0.2);
            color: var(--success-color);
        }
        
        .log-error {
            border-left-color: var(--error-color);
        }
        
        .log-error .log-level {
            background-color: rgba(239, 68, 68, 0.2);
            color: var(--error-color);
        }
        
        .log-warning {
            border-left-color: var(--warning-color);
        }
        
        .log-warning .log-level {
            background-color: rgba(251, 191, 36, 0.2);
            color: var(--warning-color);
        }
        
        .log-debug {
            border-left-color: var(--info-color);
        }
        
        .log-debug .log-level {
            background-color: rgba(59, 130, 246, 0.2);
            color: var(--info-color);
        }
        
        .log-critical {
            border-left-color: var(--critical-color);
        }
        
        .log-critical .log-level {
            background-color: rgba(236, 72, 153, 0.2);
            color: var(--critical-color);
        }
        
        .refresh-animation {
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .stats-value {
            font-size: 2.2rem;
            font-weight: 700;
            color: var(--primary-color);
            margin-bottom: 0.5rem;
            letter-spacing: -1px;
        }
        
        .stats-label {
            color: var(--muted-text);
            font-size: 0.9rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        #search-box {
            background-color: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            border-radius: 8px;
            padding: 0.625rem 1rem;
            transition: all 0.3s ease;
        }
        
        #search-box:focus {
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(109, 90, 230, 0.2);
        }
        
        #search-box::placeholder {
            color: var(--muted-text);
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 40px;
            color: var(--muted-text);
        }
        
        .empty-state i {
            font-size: 3rem;
            margin-bottom: 1.5rem;
            color: var(--primary-color);
            opacity: 0.6;
        }
        
        .empty-state p {
            font-size: 1.1rem;
            font-weight: 500;
        }
        
        /* Auto-refresh toggle switch */
        .form-check-input {
            width: 2.5rem;
            height: 1.25rem;
            margin-top: 0.25rem;
        }
        
        .form-check-input:checked {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
        }
        
        .form-check-input:focus {
            box-shadow: 0 0 0 3px rgba(109, 90, 230, 0.25);
        }
        
        .auto-refresh-container {
            display: flex;
            align-items: center;
        }
        
        .auto-refresh-label {
            margin-left: 8px;
            color: var(--muted-text);
            font-weight: 500;
        }
        
        /* Filter buttons when active */
        .btn-outline-secondary.active {
            background-color: var(--primary-color);
            color: white;
            border-color: var(--primary-color);
        }
        
        /* Custom scrollbars */
        ::-webkit-scrollbar {
            width: 10px;
        }
        
        ::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.1);
            border-radius: 10px;
        }
        
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.2);
        }
        
        /* Animations for page load */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .card {
            animation: fadeIn 0.4s ease-out forwards;
        }
        
        .card:nth-child(2) {
            animation-delay: 0.1s;
        }
        
        .log-entry {
            animation: fadeIn 0.3s ease-out forwards;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="bi bi-robot"></i> PTA<span style="font-weight: normal">Bot</span>
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link" href="/"><i class="bi bi-house-door"></i> Home</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/dashboard"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link active" href="/logs"><i class="bi bi-journal-text"></i> Logs</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/changelogs"><i class="bi bi-list-check"></i> Changelogs</a>
                    </li>
                </ul>
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="/logout"><i class="bi bi-box-arrow-right"></i> Logout ({{ session['username'] }})</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container-fluid">
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-info-circle"></i> System Info
                    </div>
                    <div class="card-body">
                        <div class="mb-3">
                            <div class="stats-value">{{ log_count }}</div>
                            <div class="stats-label">Total Log Entries</div>
                        </div>
                        <div>
                            <div class="stats-label">Current Time (Manila)</div>
                            <div>{{ current_time }}</div>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-funnel"></i> Filters
                    </div>
                    <div class="card-body">
                        <div class="mb-3">
                            <label class="form-label">Log Level</label>
                            <div class="d-grid gap-2">
                                <button class="btn btn-sm btn-outline-secondary level-filter active" data-level="all">All Levels</button>
                                <button class="btn btn-sm btn-outline-secondary level-filter" data-level="INFO">Info</button>
                                <button class="btn btn-sm btn-outline-secondary level-filter" data-level="WARNING">Warning</button>
                                <button class="btn btn-sm btn-outline-secondary level-filter" data-level="ERROR">Error</button>
                                <button class="btn btn-sm btn-outline-secondary level-filter" data-level="CRITICAL">Critical</button>
                                <button class="btn btn-sm btn-outline-secondary level-filter" data-level="DEBUG">Debug</button>
                            </div>
                        </div>
                        
                        <div class="mb-3">
                            <label class="form-label">Search Logs</label>
                            <input type="text" id="search-box" class="form-control" placeholder="Type to search...">
                        </div>
                        
                        <div class="d-grid gap-2">
                            <button id="clear-logs" class="btn btn-outline-danger">
                                <i class="bi bi-trash"></i> Clear Logs
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-9">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <div>
                            <i class="bi bi-journal-text"></i> Log Entries
                        </div>
                        <div class="d-flex align-items-center">
                            <div class="auto-refresh-container me-3">
                                <div class="form-check form-switch">
                                    <input class="form-check-input" type="checkbox" id="auto-refresh" checked>
                                </div>
                                <span class="auto-refresh-label">Auto-refresh</span>
                            </div>
                            <button id="refresh-logs" class="btn btn-sm btn-outline-secondary">
                                <i class="bi bi-arrow-clockwise"></i> Refresh
                            </button>
                        </div>
                    </div>
                    <div class="card-body" style="max-height: 800px; overflow-y: auto;" id="logs-container">
                        {% if logs %}
                            {% for log in logs %}
                                <div class="log-entry log-{{ log.level.lower() }}">
                                    <span class="log-level">{{ log.level }}</span>
                                    <span class="log-timestamp">{{ log.timestamp }}</span>
                                    <span class="log-message">{{ log.message }}</span>
                                </div>
                            {% endfor %}
                        {% else %}
                            <div class="empty-state">
                                <i class="bi bi-exclamation-circle" style="font-size: 2rem;"></i>
                                <p class="mt-3">No log entries found</p>
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Filter logs by level
            const levelFilters = document.querySelectorAll('.level-filter');
            levelFilters.forEach(filter => {
                filter.addEventListener('click', function() {
                    // Update active state
                    levelFilters.forEach(btn => btn.classList.remove('active'));
                    this.classList.add('active');
                    
                    const level = this.getAttribute('data-level');
                    filterLogs();
                });
            });
            
            // Search functionality
            const searchBox = document.getElementById('search-box');
            searchBox.addEventListener('input', filterLogs);
            
            function filterLogs() {
                const searchTerm = searchBox.value.toLowerCase();
                const selectedLevel = document.querySelector('.level-filter.active').getAttribute('data-level');
                
                const logEntries = document.querySelectorAll('.log-entry');
                logEntries.forEach(entry => {
                    const logMessage = entry.querySelector('.log-message').textContent.toLowerCase();
                    const logLevel = entry.classList.contains('log-info') ? 'INFO' : 
                                    entry.classList.contains('log-error') ? 'ERROR' :
                                    entry.classList.contains('log-warning') ? 'WARNING' :
                                    entry.classList.contains('log-debug') ? 'DEBUG' :
                                    entry.classList.contains('log-critical') ? 'CRITICAL' : '';
                    
                    const matchesSearch = searchTerm === '' || logMessage.includes(searchTerm);
                    const matchesLevel = selectedLevel === 'all' || logLevel === selectedLevel;
                    
                    entry.style.display = matchesSearch && matchesLevel ? 'block' : 'none';
                });
            }
            
            // Clear logs functionality
            const clearLogsBtn = document.getElementById('clear-logs');
            clearLogsBtn.addEventListener('click', function() {
                if (confirm('Are you sure you want to clear all logs?')) {
                    fetch('/logs/clear')
                        .then(response => response.text())
                        .then(() => {
                            const logsContainer = document.getElementById('logs-container');
                            logsContainer.innerHTML = '<div class="empty-state"><i class="bi bi-exclamation-circle" style="font-size: 2rem;"></i><p class="mt-3">No log entries found</p></div>';
                        });
                }
            });
            
            // Auto-refresh functionality
            const refreshBtn = document.getElementById('refresh-logs');
            const autoRefreshToggle = document.getElementById('auto-refresh');
            
            refreshBtn.addEventListener('click', function() {
                const icon = refreshBtn.querySelector('i');
                icon.classList.add('refresh-animation');
                
                fetch('/logs/data')
                    .then(response => response.json())
                    .then(data => {
                        updateLogs(data);
                        icon.classList.remove('refresh-animation');
                    })
                    .catch(error => {
                        console.error('Error refreshing logs:', error);
                        icon.classList.remove('refresh-animation');
                    });
            });
            
            function updateLogs(data) {
                const logsContainer = document.getElementById('logs-container');
                
                if (data.logs.length === 0) {
                    logsContainer.innerHTML = '<div class="empty-state"><i class="bi bi-exclamation-circle" style="font-size: 2rem;"></i><p class="mt-3">No log entries found</p></div>';
                    return;
                }
                
                let logsHtml = '';
                data.logs.forEach(log => {
                    const level = log.level.toLowerCase();
                    logsHtml += `
                        <div class="log-entry log-${level}">
                            <span class="log-level">${log.level}</span>
                            <span class="log-timestamp">${log.timestamp}</span>
                            <span class="log-message">${log.message}</span>
                        </div>
                    `;
                });
                
                logsContainer.innerHTML = logsHtml;
                
                // Reapply filters after update
                filterLogs();
            }
            
            // Set up auto-refresh interval
            let refreshInterval;
            
            function startAutoRefresh() {
                if (autoRefreshToggle.checked) {
                    refreshInterval = setInterval(() => {
                        fetch('/logs/data')
                            .then(response => response.json())
                            .then(data => {
                                updateLogs(data);
                            })
                            .catch(error => {
                                console.error('Error auto-refreshing logs:', error);
                            });
                    }, 5000); // Refresh every 5 seconds
                }
            }
            
            function stopAutoRefresh() {
                clearInterval(refreshInterval);
            }
            
            autoRefreshToggle.addEventListener('change', function() {
                if (this.checked) {
                    startAutoRefresh();
                } else {
                    stopAutoRefresh();
                }
            });
            
            // Start auto-refresh by default
            startAutoRefresh();
        });
    </script>
</body>
</html>
'''

@app.route('/')
@login_required
def home():
    return render_template_string('''
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>PTABot Dashboard</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
            <style>
                :root {
                    --primary-color: #6D5AE6;
                    --primary-dark: #5747C9;
                    --secondary-color: #22B8CF;
                    --dark-bg: #131722;
                    --card-bg: #1E222D;
                    --text-color: #F9FAFB;
                    --muted-text: #9CA3AF;
                    --border-color: #2D3748;
                    --success-color: #10B981;
                }
                
                body {
                    background-color: var(--dark-bg);
                    color: var(--text-color);
                    font-family: 'Inter', 'Segoe UI', sans-serif;
                    line-height: 1.6;
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                }
                
                .navbar {
                    background-color: var(--dark-bg) !important;
                    border-bottom: 1px solid var(--border-color);
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
                    padding: 0.75rem 1.5rem;
                }
                
                .navbar-brand {
                    color: var(--primary-color) !important;
                    font-weight: 700;
                    font-size: 1.5rem;
                    letter-spacing: -0.5px;
                }
                
                .navbar-dark .navbar-nav .nav-link {
                    color: var(--text-color);
                    font-weight: 500;
                    padding: 0.5rem 1rem;
                    border-radius: 6px;
                    transition: all 0.2s ease;
                }
                
                .navbar-dark .navbar-nav .nav-link:hover,
                .navbar-dark .navbar-nav .nav-link.active {
                    color: var(--primary-color);
                    background-color: rgba(109, 90, 230, 0.1);
                }
                
                .welcome-container {
                    flex: 1;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    padding: 2rem;
                }
                
                .welcome-card {
                    background-color: var(--card-bg);
                    border: 1px solid var(--border-color);
                    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
                    border-radius: 16px;
                    padding: 3rem 2rem;
                    max-width: 600px;
                    width: 100%;
                    animation: fadeIn 0.6s ease-out forwards;
                }
                
                .welcome-icon {
                    font-size: 5rem;
                    color: var(--primary-color);
                    margin-bottom: 1.5rem;
                    opacity: 0;
                    animation: iconFloat 0.8s ease-out forwards 0.3s;
                }
                
                .welcome-title {
                    font-size: 2.5rem;
                    font-weight: 700;
                    color: var(--primary-color);
                    margin-bottom: 1rem;
                    letter-spacing: -0.5px;
                }
                
                .welcome-subtitle {
                    color: var(--muted-text);
                    margin-bottom: 2.5rem;
                    font-weight: 500;
                    font-size: 1.1rem;
                }
                
                .btn-primary {
                    background-color: var(--primary-color);
                    border-color: var(--primary-dark);
                    padding: 0.75rem 2rem;
                    font-weight: 600;
                    font-size: 1.1rem;
                    transition: all 0.3s ease;
                    border-radius: 10px;
                }
                
                .btn-primary:hover {
                    background-color: var(--primary-dark);
                    border-color: var(--primary-dark);
                    transform: translateY(-2px);
                    box-shadow: 0 6px 15px rgba(109, 90, 230, 0.4);
                }
                
                .status-indicator {
                    display: inline-block;
                    width: 14px;
                    height: 14px;
                    border-radius: 50%;
                    background-color: var(--success-color);
                    margin-right: 10px;
                    animation: pulse 2s infinite;
                    box-shadow: 0 0 0 rgba(16, 185, 129, 0.4);
                }
                
                .status-text {
                    font-weight: 500;
                }
                
                @keyframes pulse {
                    0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
                    70% { box-shadow: 0 0 0 10px rgba(16, 185, 129, 0); }
                    100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
                }
                
                @keyframes fadeIn {
                    from { opacity: 0; transform: translateY(20px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                
                @keyframes iconFloat {
                    from { opacity: 0; transform: translateY(10px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                
                /* Custom scrollbars */
                ::-webkit-scrollbar {
                    width: 10px;
                }
                
                ::-webkit-scrollbar-track {
                    background: rgba(0, 0, 0, 0.1);
                    border-radius: 10px;
                }
                
                ::-webkit-scrollbar-thumb {
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 10px;
                }
                
                ::-webkit-scrollbar-thumb:hover {
                    background: rgba(255, 255, 255, 0.2);
                }
            </style>
        </head>
        <body>
            <nav class="navbar navbar-expand-lg navbar-dark mb-4">
                <div class="container-fluid">
                    <a class="navbar-brand" href="/">
                        <i class="bi bi-robot"></i> PTA<span style="font-weight: normal">Bot</span>
                    </a>
                    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                        <span class="navbar-toggler-icon"></span>
                    </button>
                    <div class="collapse navbar-collapse" id="navbarNav">
                        <ul class="navbar-nav">
                            <li class="nav-item">
                                <a class="nav-link active" href="/"><i class="bi bi-house-door"></i> Home</a>
                            </li>
                            <li class="nav-item">
                                <a class="nav-link" href="/dashboard"><i class="bi bi-speedometer2"></i> Dashboard</a>
                            </li>
                            <li class="nav-item">
                                <a class="nav-link" href="/logs"><i class="bi bi-journal-text"></i> Logs</a>
                            </li>
                            <li class="nav-item">
                                <a class="nav-link" href="/changelogs"><i class="bi bi-list-check"></i> Changelogs</a>
                            </li>
                        </ul>
                        <ul class="navbar-nav ms-auto">
                            <li class="nav-item">
                                <a class="nav-link" href="/logout"><i class="bi bi-box-arrow-right"></i> Logout ({{ session['username'] }})</a>
                            </li>
                        </ul>
                    </div>
                </div>
            </nav>
            
            <div class="welcome-container">
                <div class="welcome-card">
                    <div class="welcome-icon">
                        <i class="bi bi-robot"></i>
                    </div>
                    <h1 class="welcome-title">Welcome to PTABot</h1>
                    <p class="welcome-subtitle">Prodigy Trading Academy Telegram Bot Dashboard</p>
                    
                    <div class="d-flex justify-content-center align-items-center mb-4">
                        <span class="status-indicator"></span>
                        <span class="status-text">Bot is currently operational</span>
                    </div>
                    
                    <a href="/logs" class="btn btn-primary">
                        <i class="bi bi-journal-text me-2"></i> View Logs
                    </a>
                </div>
            </div>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
        </body>
        </html>
    ''')

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PTABot Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        :root {
            --primary-color: #6D5AE6;
            --primary-dark: #5747C9;
            --secondary-color: #22B8CF;
            --dark-bg: #131722;
            --card-bg: #1E222D;
            --text-color: #F9FAFB;
            --muted-text: #9CA3AF;
            --border-color: #2D3748;
            --success-color: #10B981;
            --warning-color: #FBBF24;
            --error-color: #EF4444;
            --info-color: #3B82F6;
        }
        
        body {
            background-color: var(--dark-bg);
            color: var(--text-color);
            font-family: 'Inter', 'Segoe UI', sans-serif;
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .navbar {
            background-color: var(--dark-bg) !important;
            border-bottom: 1px solid var(--border-color);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            padding: 0.75rem 1.5rem;
        }
        
        .navbar-brand {
            color: var(--primary-color) !important;
            font-weight: 700;
            font-size: 1.5rem;
            letter-spacing: -0.5px;
        }
        
        .navbar-dark .navbar-nav .nav-link {
            color: var(--text-color);
            font-weight: 500;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            transition: all 0.2s ease;
        }
        
        .navbar-dark .navbar-nav .nav-link:hover,
        .navbar-dark .navbar-nav .nav-link.active {
            color: var(--primary-color);
            background-color: rgba(109, 90, 230, 0.1);
        }
        
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.12);
            margin-bottom: 24px;
            border-radius: 12px;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 20px rgba(0, 0, 0, 0.18);
        }
        
        .card-header {
            background-color: rgba(0, 0, 0, 0.15);
            border-bottom: 1px solid var(--border-color);
            font-weight: 600;
            color: var(--primary-color);
            padding: 1rem 1.25rem;
        }
        
        .card-body {
            padding: 1.25rem;
        }
        
        .btn {
            font-weight: 500;
            border-radius: 8px;
            padding: 0.5rem 1rem;
            transition: all 0.3s ease;
        }
        
        .btn-primary {
            background-color: var(--primary-color);
            border-color: var(--primary-dark);
        }
        
        .btn-primary:hover {
            background-color: var(--primary-dark);
            border-color: var(--primary-dark);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(109, 90, 230, 0.3);
        }
        
        .stats-card {
            text-align: center;
            padding: 1.5rem;
        }
        
        .stats-value {
            font-size: 2.2rem;
            font-weight: 700;
            color: var(--primary-color);
            margin-bottom: 0.5rem;
            letter-spacing: -1px;
        }
        
        .stats-label {
            color: var(--muted-text);
            font-size: 0.9rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .stats-icon {
            font-size: 2.5rem;
            margin-bottom: 1rem;
            display: block;
        }
        
        .stats-active .stats-icon {
            color: var(--success-color);
        }
        
        .stats-expiring .stats-icon {
            color: var(--warning-color);
        }
        
        .stats-expired .stats-icon {
            color: var(--error-color);
        }
        
        .membership-card {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            background-color: rgba(0, 0, 0, 0.2);
            border-left: 4px solid transparent;
            transition: all 0.2s ease;
        }
        
        .membership-card:hover {
            background-color: rgba(0, 0, 0, 0.3);
            transform: translateX(2px);
        }
        
        .membership-active {
            border-left-color: var(--success-color);
        }
        
        .membership-expiring {
            border-left-color: var(--warning-color);
        }
        
        .membership-expired {
            border-left-color: var(--error-color);
        }
        
        .membership-name {
            font-weight: 600;
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
        }
        
        .membership-plan {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 30px;
            font-size: 0.8rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
            background-color: rgba(109, 90, 230, 0.2);
            color: var(--primary-color);
        }
        
        .membership-dates {
            display: flex;
            justify-content: space-between;
            color: var(--muted-text);
            font-size: 0.9rem;
        }
        
        .days-remaining {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 30px;
            font-size: 0.8rem;
            font-weight: 600;
            margin-left: 0.75rem;
            vertical-align: middle;
        }
        
        .days-active {
            background-color: rgba(16, 185, 129, 0.2);
            color: var(--success-color);
        }
        
        .days-expiring {
            background-color: rgba(251, 191, 36, 0.2);
            color: var(--warning-color);
        }
        
        .days-expired {
            background-color: rgba(239, 68, 68, 0.2);
            color: var(--error-color);
        }
        
        .tab-content {
            padding-top: 1.5rem;
        }
        
        .nav-tabs {
            border-bottom-color: var(--border-color);
        }
        
        .nav-tabs .nav-link {
            color: var(--muted-text);
            border: none;
            border-bottom: 2px solid transparent;
            padding: 0.75rem 1rem;
            font-weight: 500;
            background-color: transparent;
            transition: all 0.2s ease;
        }
        
        .nav-tabs .nav-link:hover {
            color: var(--text-color);
            border-bottom-color: var(--border-color);
        }
        
        .nav-tabs .nav-link.active {
            color: var(--primary-color);
            background-color: transparent;
            border-bottom-color: var(--primary-color);
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 40px;
            color: var(--muted-text);
        }
        
        .empty-state i {
            font-size: 3rem;
            margin-bottom: 1.5rem;
            color: var(--primary-color);
            opacity: 0.6;
        }
        
        .empty-state p {
            font-size: 1.1rem;
            font-weight: 500;
        }
        
        /* Custom scrollbars */
        ::-webkit-scrollbar {
            width: 10px;
        }
        
        ::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.1);
            border-radius: 10px;
        }
        
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.2);
        }
        
        /* Search box */
        .search-container {
            position: relative;
            margin-bottom: 1.5rem;
        }
        
        #search-box {
            background-color: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            border-radius: 8px;
            padding: 0.625rem 1rem;
            width: 100%;
            transition: all 0.3s ease;
        }
        
        #search-box:focus {
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(109, 90, 230, 0.2);
        }
        
        #search-box::placeholder {
            color: var(--muted-text);
        }
        
        .search-icon {
            position: absolute;
            right: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--muted-text);
        }
        
        /* Animations for page load */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .card {
            animation: fadeIn 0.4s ease-out forwards;
        }
        
        .card:nth-child(2) {
            animation-delay: 0.1s;
        }
        
        .card:nth-child(3) {
            animation-delay: 0.2s;
        }
        
        .membership-card {
            animation: fadeIn 0.3s ease-out forwards;
        }
        
        .membership-card:nth-child(even) {
            animation-delay: 0.1s;
        }
        
        /* Badge styles */
        .badge-cancelled {
            background-color: rgba(239, 68, 68, 0.2);
            color: var(--error-color);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 500;
            margin-left: 0.5rem;
        }

        /* Modal styles */
        .modal-content {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
            border-radius: 12px;
        }

        .modal-header {
            border-bottom: 1px solid var(--border-color);
            padding: 1rem 1.25rem;
        }

        .modal-header .btn-close {
            filter: invert(1) grayscale(100%) brightness(200%);
        }

        .modal-footer {
            border-top: 1px solid var(--border-color);
            padding: 1rem;
        }

        .member-detail {
            display: flex;
            justify-content: space-between;
            padding: 0.75rem 0;
            border-bottom: 1px solid var(--border-color);
        }

        .member-detail:last-child {
            border-bottom: none;
        }

        .detail-label {
            font-weight: 500;
            color: var(--muted-text);
        }

        .detail-value {
            font-weight: 600;
        }

        /* Make membership cards clickable */
        .membership-card {
            cursor: pointer;
            position: relative;
        }

        .membership-card::after {
            content: "\\F132";
            font-family: "bootstrap-icons";
            position: absolute;
            top: 1rem;
            right: 1rem;
            color: var(--muted-text);
            opacity: 0.5;
            transition: all 0.2s ease;
        }

        .membership-card:hover::after {
            opacity: 1;
            transform: translateX(-2px);
            color: var(--primary-color);
        }

        .btn-outline-primary {
            color: var(--primary-color);
            border-color: var(--primary-color);
            background-color: transparent;
        }

        .btn-outline-primary:hover {
            background-color: rgba(109, 90, 230, 0.1);
            color: var(--primary-color);
            border-color: var(--primary-color);
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(109, 90, 230, 0.2);
        }

        .export-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.3s ease;
        }

        .export-btn i {
            font-size: 0.9rem;
        }

        .export-btn:active {
            transform: translateY(0);
        }

        .spin {
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .toast {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.3);
        }

        .toast-header {
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding: 0.75rem 1rem;
        }

        .toast-body {
            padding: 0.75rem 1rem;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="bi bi-robot"></i> PTA<span style="font-weight: normal">Bot</span>
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link" href="/"><i class="bi bi-house-door"></i> Home</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link active" href="/dashboard"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/logs"><i class="bi bi-journal-text"></i> Logs</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/changelogs"><i class="bi bi-list-check"></i> Changelogs</a>
                    </li>
                </ul>
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="/logout"><i class="bi bi-box-arrow-right"></i> Logout ({{ session['username'] }})</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container">
        <div class="row mb-4">
            <div class="col-12">
                <h1 class="h3 mb-4 text-light">Membership Dashboard</h1>
            </div>
        </div>
        
        <!-- Stats Overview -->
        <div class="row mb-4">
            <div class="col-md-4">
                <div class="card stats-card stats-active">
                    <i class="bi bi-person-check-fill stats-icon"></i>
                    <div class="stats-value">{{ active_count }}</div>
                    <div class="stats-label">Active Members</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card stats-card stats-expiring">
                    <i class="bi bi-clock-history stats-icon"></i>
                    <div class="stats-value">{{ expiring_soon_count }}</div>
                    <div class="stats-label">Expiring Soon</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card stats-card stats-expired">
                    <i class="bi bi-person-x-fill stats-icon"></i>
                    <div class="stats-value">{{ expired_count }}</div>
                    <div class="stats-label">Expired Members</div>
                </div>
            </div>
        </div>
        
        <!-- Current time display and search -->
        <div class="row mb-3">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center">
                            <div class="d-flex align-items-center">
                                <a href="/export/members.csv" class="btn btn-outline-primary me-2 export-btn">
                                    <i class="bi bi-download me-1"></i> Export CSV
                                </a>
                                <button class="btn btn-outline-secondary" onclick="window.location.reload()">
                                    <i class="bi bi-arrow-clockwise me-1"></i> Refresh
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <div class="search-container">
                            <input type="text" id="search-box" placeholder="Search members..." onkeyup="searchMembers()">
                            <i class="bi bi-search search-icon"></i>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Membership tabs and content -->
        <div class="row">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <ul class="nav nav-tabs card-header-tabs" id="membershipTabs" role="tablist">
                            <li class="nav-item" role="presentation">
                                <button class="nav-link active" id="active-tab" data-bs-toggle="tab" data-bs-target="#active" type="button" role="tab" aria-controls="active" aria-selected="true">
                                    <i class="bi bi-person-check"></i> Active ({{ active_count }})
                                </button>
                            </li>
                            <li class="nav-item" role="presentation">
                                <button class="nav-link" id="expiring-tab" data-bs-toggle="tab" data-bs-target="#expiring" type="button" role="tab" aria-controls="expiring" aria-selected="false">
                                    <i class="bi bi-clock"></i> Expiring Soon ({{ expiring_soon_count }})
                                </button>
                            </li>
                            <li class="nav-item" role="presentation">
                                <button class="nav-link" id="expired-tab" data-bs-toggle="tab" data-bs-target="#expired" type="button" role="tab" aria-controls="expired" aria-selected="false">
                                    <i class="bi bi-person-x"></i> Expired ({{ expired_count }})
                                </button>
                            </li>
                        </ul>
                    </div>
                    <div class="card-body">
                        <div class="tab-content" id="membershipTabContent">
                            <!-- Active Members Tab -->
                            <div class="tab-pane fade show active" id="active" role="tabpanel" aria-labelledby="active-tab">
                                {% if active_memberships %}
                                    {% for member in active_memberships %}
                                        <!-- For Active Members Tab -->
                                        <div class="membership-card membership-active">
                                                <div class="d-flex justify-content-between align-items-start">
                                                    <div>
                                                        <h5 class="membership-name">
                                                            {{ member.name }}
                                                            {% if member.cancelled %}
                                                            <span class="badge-cancelled">CANCELLED</span>
                                                            {% endif %}
                                                        </h5>
                                                        <span class="membership-plan">{{ member.plan }}</span>
                                                        <span class="days-remaining days-active">{{ member.days_remaining }} days left</span>
                                                    </div>
                                                </div>
                                            <div class="membership-dates mt-2">
                                                <div>End: <strong>{{ member.end_date }}</strong></div>
                                            </div>
                                        </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="empty-state">
                                        <i class="bi bi-people"></i>
                                        <p>No active memberships found</p>
                                    </div>
                                {% endif %}
                            </div>
                            
                            <!-- Expiring Soon Tab -->
                            <div class="tab-pane fade" id="expiring" role="tabpanel" aria-labelledby="expiring-tab">
                                {% if expiring_soon %}
                                    {% for member in expiring_soon %}
                                        <div class="membership-card membership-expiring">
                                                <div class="d-flex justify-content-between align-items-start">
                                                    <div>
                                                        <h5 class="membership-name">
                                                            {{ member.name }}
                                                            {% if member.cancelled %}
                                                            <span class="badge-cancelled">CANCELLED</span>
                                                            {% endif %}
                                                        </h5>
                                                        <span class="membership-plan">{{ member.plan }}</span>
                                                        <span class="days-remaining days-expiring">{{ member.days_remaining }} days left</span>
                                                    </div>
                                                </div>
                                            <div class="membership-dates mt-2">
                                                <div>End: <strong>{{ member.end_date }}</strong></div>
                                            </div>
                                        </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="empty-state">
                                        <i class="bi bi-clock"></i>
                                        <p>No memberships expiring soon</p>
                                    </div>
                                {% endif %}
                            </div>
                            
                            <!-- Expired Tab -->
                            <div class="tab-pane fade" id="expired" role="tabpanel" aria-labelledby="expired-tab">
                                {% if expired_memberships %}
                                    {% for member in expired_memberships %}
                                        <div class="membership-card membership-expired">
                                                <div class="d-flex justify-content-between align-items-start">
                                                    <div>
                                                        <h5 class="membership-name">{{ member.name }}</h5>
                                                        <span class="membership-plan">{{ member.plan }}</span>
                                                        <span class="days-remaining days-expired">Expired</span>
                                                    </div>
                                                </div>
                                            <div class="membership-dates mt-2">
                                                <div>End: <strong>{{ member.end_date }}</strong></div>
                                            </div>
                                        </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="empty-state">
                                        <i class="bi bi-person-x"></i>
                                        <p>No expired memberships found</p>
                                    </div>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Member Details Modal -->
    <div class="modal fade" id="memberDetailsModal" tabindex="-1" aria-labelledby="memberDetailsModalLabel" aria-hidden="true">
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="memberDetailsModalLabel">Member Details</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <div class="member-detail">
                        <span class="detail-label">Username:</span>
                        <span id="member-name" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">User ID:</span>
                        <span id="member-id" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">Plan:</span>
                        <span id="member-plan" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">Start Date:</span>
                        <span id="member-start-date" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">End Date:</span>
                        <span id="member-end-date" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">Days Remaining:</span>
                        <span id="member-days-remaining" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">Payment Method:</span>
                        <span id="member-payment-method" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">Payment Status:</span>
                        <span id="member-payment-status" class="detail-value">-</span>
                    </div>
                    <div class="member-detail">
                        <span class="detail-label">Cancellation Status:</span>
                        <span id="member-cancellation" class="detail-value">-</span>
                    </div>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-primary btn-modal-close" data-bs-dismiss="modal">
                        <i class="bi bi-x-circle me-1"></i> Close
                    </button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Add export button loading state
        document.addEventListener('DOMContentLoaded', function() {
            // Export duration in milliseconds - can be adjusted as needed
            const exportDuration = 9000; // 2 seconds for faster feedback
            
            const exportBtn = document.querySelector('a[href="/export/members.csv"]');
            
            exportBtn.addEventListener('click', function() {
                const originalContent = this.innerHTML;
                this.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Exporting...';
                this.classList.add('disabled');
                
                setTimeout(() => {
                    // Show success notification
                    showNotification('Export Successful', 'Members data has been exported to CSV.');
                    
                    // Reset button state
                    this.innerHTML = originalContent;
                    this.classList.remove('disabled');
                }, exportDuration);
            });
            
            // Create notification container if it doesn't exist
            if (!document.getElementById('notification-container')) {
                const notificationContainer = document.createElement('div');
                notificationContainer.id = 'notification-container';
                notificationContainer.className = 'position-fixed bottom-0 end-0 p-3';
                notificationContainer.style.zIndex = '5';
                document.body.appendChild(notificationContainer);
            }
        });

        // Function to show notification
        function showNotification(title, message) {
            const toastId = 'toast-' + Date.now();
            const toastHtml = `
                <div id="${toastId}" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
                    <div class="toast-header bg-success text-white">
                        <i class="bi bi-check-circle me-2"></i>
                        <strong class="me-auto">${title}</strong>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
                    </div>
                    <div class="toast-body bg-dark text-light">
                        ${message}
                    </div>
                </div>
            `;
            
            document.getElementById('notification-container').innerHTML += toastHtml;
            const toastElement = document.getElementById(toastId);
            const toast = new bootstrap.Toast(toastElement, { delay: 5000 });
            toast.show();
            
            // Auto-remove toast element after it's hidden
            toastElement.addEventListener('hidden.bs.toast', function() {
                this.remove();
            });
        }

        function searchMembers() {
            // Get the search term
            const searchTerm = document.getElementById('search-box').value.toLowerCase();
            
            // Get all membership cards
            const membershipCards = document.querySelectorAll('.membership-card');
            
            // Loop through the cards and hide/show based on the search term
            membershipCards.forEach(card => {
                const cardContent = card.textContent.toLowerCase();
                if (cardContent.includes(searchTerm)) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
            
            // Show empty state message if no results in active tab
            const activeTab = document.querySelector('.tab-pane.active');
            const visibleCards = activeTab.querySelectorAll('.membership-card[style="display: block;"]');
            const emptyState = activeTab.querySelector('.empty-state');
            
            if (visibleCards.length === 0 && searchTerm) {
                // If there's an existing empty state, update its message
                if (emptyState) {
                    emptyState.querySelector('p').textContent = 'No members found matching your search';
                } else {
                    // Create a new empty state
                    const newEmptyState = document.createElement('div');
                    newEmptyState.className = 'empty-state';
                    newEmptyState.innerHTML = `
                        <i class="bi bi-search"></i>
                        <p>No members found matching your search</p>
                    `;
                    activeTab.appendChild(newEmptyState);
                }
            } else if (emptyState && !searchTerm) {
                // Restore original message if search is cleared
                if (activeTab.id === 'active') {
                    emptyState.querySelector('p').textContent = 'No active memberships found';
                } else if (activeTab.id === 'expiring') {
                    emptyState.querySelector('p').textContent = 'No memberships expiring soon';
                } else if (activeTab.id === 'expired') {
                    emptyState.querySelector('p').textContent = 'No expired memberships found';
                }
            }
        }

        // Store all member data in a global variable for easy access
        const memberData = {
            active: [
                {% for member in active_memberships %}
                    {
                        name: "{{ member.name }}",
                        userId: "{{ member.user_id }}",
                        plan: "{{ member.plan }}",
                        startDate: "{{ member.start_date }}",
                        endDate: "{{ member.end_date }}",
                        daysRemaining: "{{ member.days_remaining }}",
                        paymentMethod: "{{ member.payment_method }}",
                        hasPaid: {% if member.has_paid %}true{% else %}false{% endif %},
                        cancelled: {% if member.cancelled %}true{% else %}false{% endif %}
                    }{% if not loop.last %},{% endif %}
                {% endfor %}
            ],
            expiring: [
                {% for member in expiring_soon %}
                    {
                        name: "{{ member.name }}",
                        userId: "{{ member.user_id }}",
                        plan: "{{ member.plan }}",
                        startDate: "{{ member.start_date }}",
                        endDate: "{{ member.end_date }}",
                        daysRemaining: "{{ member.days_remaining }}",
                        paymentMethod: "{{ member.payment_method }}",
                        hasPaid: {% if member.has_paid %}true{% else %}false{% endif %},
                        cancelled: {% if member.cancelled %}true{% else %}false{% endif %}
                    }{% if not loop.last %},{% endif %}
                {% endfor %}
            ],
            expired: [
                {% for member in expired_memberships %}
                    {
                        name: "{{ member.name }}",
                        userId: "{{ member.user_id }}",
                        plan: "{{ member.plan }}",
                        startDate: "{{ member.start_date }}",
                        endDate: "{{ member.end_date }}",
                        daysRemaining: "{{ member.days_remaining }}",
                        paymentMethod: "{{ member.payment_method }}",
                        hasPaid: {% if member.has_paid %}true{% else %}false{% endif %},
                        cancelled: {% if member.cancelled %}true{% else %}false{% endif %}
                    }{% if not loop.last %},{% endif %}
                {% endfor %}
            ]
        };

        // Initialize the modal
        const memberModal = new bootstrap.Modal(document.getElementById('memberDetailsModal'));

        // Add click events to membership cards
        document.addEventListener('DOMContentLoaded', function() {
            // Set up click handlers for active members
            const activeCards = document.querySelectorAll('#active .membership-card');
            activeCards.forEach((card, index) => {
                card.addEventListener('click', () => showMemberDetails('active', index));
            });
            
            // Set up click handlers for expiring members
            const expiringCards = document.querySelectorAll('#expiring .membership-card');
            expiringCards.forEach((card, index) => {
                card.addEventListener('click', () => showMemberDetails('expiring', index));
            });
            
            // Set up click handlers for expired members
            const expiredCards = document.querySelectorAll('#expired .membership-card');
            expiredCards.forEach((card, index) => {
                card.addEventListener('click', () => showMemberDetails('expired', index));
            });
        });

        // Function to show member details in the modal
        function showMemberDetails(category, index) {
            const member = memberData[category][index];
            if (!member) return;
            
            // Update modal title
            document.getElementById('memberDetailsModalLabel').textContent = `Member Details: ${member.name}`;
            
            // Populate member details
            document.getElementById('member-name').textContent = member.name;
            document.getElementById('member-id').textContent = member.userId;
            document.getElementById('member-plan').textContent = member.plan;
            document.getElementById('member-start-date').textContent = member.startDate;
            document.getElementById('member-end-date').textContent = member.endDate;
            document.getElementById('member-days-remaining').textContent = 
                category === 'expired' ? 'Expired' : `${member.daysRemaining} days`;
            document.getElementById('member-payment-method').textContent = member.paymentMethod;
            document.getElementById('member-payment-status').textContent = member.hasPaid ? 'Paid' : 'Unpaid';
            document.getElementById('member-cancellation').textContent = member.cancelled ? 'Cancelled' : 'Active';
            
            // Show the modal
            memberModal.show();
        }
    </script>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PTABot Admin Login</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            :root {
                --primary-color: #6D5AE6;
                --primary-dark: #5747C9;
                --dark-bg: #131722;
                --card-bg: #1E222D;
                --text-color: #F9FAFB;
                --muted-text: #9CA3AF;
                --border-color: #2D3748;
            }
            
            body {
                background-color: var(--dark-bg);
                color: var(--text-color);
                font-family: 'Inter', 'Segoe UI', sans-serif;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .login-container {
                background-color: var(--card-bg);
                border-radius: 12px;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
                padding: 2rem;
                width: 100%;
                max-width: 400px;
                border: 1px solid var(--border-color);
            }
            
            .login-header {
                text-align: center;
                margin-bottom: 2rem;
            }
            
            .login-icon {
                font-size: 3rem;
                color: var(--primary-color);
                margin-bottom: 1rem;
            }
            
            .login-title {
                font-size: 1.75rem;
                font-weight: 600;
                color: var(--text-color);
                margin-bottom: 0.5rem;
            }
            
            .login-subtitle {
                color: var(--muted-text);
                font-size: 0.9rem;
            }
            
            .form-label {
                color: var(--muted-text);
                font-weight: 500;
                margin-bottom: 0.5rem;
            }
            
            .form-control {
                background-color: rgba(0, 0, 0, 0.2);
                border: 1px solid var(--border-color);
                color: var(--text-color);
                border-radius: 8px;
                padding: 0.625rem 1rem;
            }
            
            .form-control:focus {
                box-shadow: 0 0 0 3px rgba(109, 90, 230, 0.25);
                border-color: var(--primary-color);
            }
            
            .btn-primary {
                background-color: var(--primary-color);
                border-color: var(--primary-dark);
                padding: 0.625rem 1rem;
                font-weight: 500;
            }
            
            .btn-primary:hover {
                background-color: var(--primary-dark);
                transform: translateY(-1px);
                box-shadow: 0 4px 8px rgba(109, 90, 230, 0.3);
            }
            
            .alert {
                border-radius: 8px;
                padding: 0.75rem;
                margin-bottom: 1.5rem;
            }
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="login-header">
                <div class="login-icon">
                    <i class="bi bi-shield-lock"></i>
                </div>
                <h1 class="login-title">PTABot Admin</h1>
                <p class="login-subtitle">Sign in to access the dashboard</p>
            </div>
            
            {% if error %}
            <div class="alert alert-danger">{{ error }}</div>
            {% endif %}
            
            <form method="post">
                <div class="mb-3">
                    <label for="username" class="form-label">Username</label>
                    <input type="text" class="form-control" id="username" name="username" required>
                </div>
                <div class="mb-4">
                    <label for="password" class="form-label">Password</label>
                    <input type="password" class="form-control" id="password" name="password" required>
                </div>
                <div class="d-grid">
                    <button type="submit" class="btn btn-primary">Sign In</button>
                </div>
            </form>
            
            <div class="text-center mt-4">
                <small class="text-muted">Authorized personnel only</small>
            </div>
        </div>
        
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    </body>
    </html>
'''


# Add this login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page for admin dashboard"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Get admin credentials from environment variables using the SINGULAR names
        admin_usernames = os.getenv('ADMIN_USERNAME', 'admin').split(',')
        admin_passwords = os.getenv('ADMIN_PASSWORD', '1234').split(',')
        
        # Create a dictionary of valid username-password pairs
        valid_credentials = {
            username.strip(): password.strip() 
            for username, password in zip(admin_usernames, admin_passwords)
        }
        
        # Check if the submitted credentials match any valid pair
        if username in valid_credentials and password == valid_credentials[username]:
            session['logged_in'] = True
            session['username'] = username
            return redirect('/dashboard')
        else:
            flash('Invalid credentials', 'danger')
    
    return render_template_string(LOGIN_TEMPLATE)

CHANGELOGS_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PTABot Changelogs</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        :root {
            --primary-color: #6D5AE6;
            --primary-dark: #5747C9;
            --secondary-color: #22B8CF;
            --dark-bg: #131722;
            --card-bg: #1E222D;
            --text-color: #F9FAFB;
            --muted-text: #9CA3AF;
            --border-color: #2D3748;
            --success-color: #10B981;
            --warning-color: #FBBF24;
            --error-color: #EF4444;
            --info-color: #3B82F6;
        }
        
        body {
            background-color: var(--dark-bg);
            color: var(--text-color);
            font-family: 'Inter', 'Segoe UI', sans-serif;
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .navbar {
            background-color: var(--dark-bg) !important;
            border-bottom: 1px solid var(--border-color);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
            padding: 0.75rem 1.5rem;
        }
        
        .navbar-brand {
            color: var(--primary-color) !important;
            font-weight: 700;
            font-size: 1.5rem;
            letter-spacing: -0.5px;
        }
        
        .navbar-dark .navbar-nav .nav-link {
            color: var(--text-color);
            font-weight: 500;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            transition: all 0.2s ease;
        }
        
        .navbar-dark .navbar-nav .nav-link:hover,
        .navbar-dark .navbar-nav .nav-link.active {
            color: var(--primary-color);
            background-color: rgba(109, 90, 230, 0.1);
        }
        
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.12);
            margin-bottom: 24px;
            border-radius: 12px;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 20px rgba(0, 0, 0, 0.18);
        }
        
        .card-header {
            background-color: rgba(0, 0, 0, 0.15);
            border-bottom: 1px solid var(--border-color);
            font-weight: 600;
            color: var(--primary-color);
            padding: 1rem 1.25rem;
        }
        
        .card-body {
            padding: 1.25rem;
        }
        
        .changelog-item {
            padding: 1rem;
            margin-bottom: 1rem;
            border-radius: 8px;
            background-color: rgba(0, 0, 0, 0.2);
            border-left: 4px solid var(--primary-color);
        }
        
        .changelog-item.user {
            border-left-color: var(--info-color);
        }
        
        .changelog-item.admin {
            border-left-color: var(--primary-color);
        }
        
        .changelog-timestamp {
            color: var(--muted-text);
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
        }
        
        .changelog-content {
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .nav-pills .nav-link {
            color: var(--muted-text);
            background-color: transparent;
            border-radius: 8px;
            padding: 0.75rem 1.25rem;
            transition: all 0.2s ease;
        }
        
        .nav-pills .nav-link.active {
            color: var(--text-color);
            background-color: rgba(109, 90, 230, 0.2);
        }
        
        .nav-pills .nav-link:hover:not(.active) {
            background-color: rgba(255, 255, 255, 0.05);
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 40px;
            color: var(--muted-text);
        }
        
        .empty-state i {
            font-size: 3rem;
            margin-bottom: 1.5rem;
            color: var(--primary-color);
            opacity: 0.6;
        }
        
        .empty-state p {
            font-size: 1.1rem;
            font-weight: 500;
        }
        
        /* Custom scrollbars */
        ::-webkit-scrollbar {
            width: 10px;
        }
        
        ::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.1);
            border-radius: 10px;
        }
        
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.2);
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .changelog-item {
            animation: fadeIn 0.4s ease-out forwards;
        }
        
        .changelog-item:nth-child(even) {
            animation-delay: 0.1s;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="bi bi-robot"></i> PTA<span style="font-weight: normal">Bot</span>
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link" href="/"><i class="bi bi-house-door"></i> Home</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/dashboard"><i class="bi bi-speedometer2"></i> Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/logs"><i class="bi bi-journal-text"></i> Logs</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link active" href="/changelogs"><i class="bi bi-list-check"></i> Changelogs</a>
                    </li>
                </ul>
                <ul class="navbar-nav ms-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="/logout"><i class="bi bi-box-arrow-right"></i> Logout ({{ session['username'] }})</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container">
        <div class="row mb-4">
            <div class="col-12">
                <h1 class="h3 mb-4 text-light">System Changelogs</h1>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-3">
                <div class="card mb-4">
                    <div class="card-header">
                        <i class="bi bi-info-circle"></i> Info
                    </div>
                    <div class="card-body">
                        <div class="mb-3">
                            <div class="text-light-muted small mb-1">Current Time (Manila)</div>
                            <div class="text-light fw-semibold">{{ current_time }}</div>
                        </div>
                        <div>
                            <div class="text-light-muted small mb-1">Total Changelogs</div>
                            <div class="text-light fw-semibold">{{ admin_changelogs|length + user_changelogs|length }}</div>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-header">
                        <i class="bi bi-filter"></i> Navigation
                    </div>
                    <div class="card-body">
                        <div class="nav flex-column nav-pills" role="tablist">
                            <button class="nav-link active" data-bs-toggle="pill" data-bs-target="#user-tab" type="button" role="tab">
                                <i class="bi bi-people"></i> User Changelogs <span class="badge bg-primary">{{ user_changelogs|length }}</span>
                            </button>
                            <button class="nav-link" data-bs-toggle="pill" data-bs-target="#admin-tab" type="button" role="tab">
                                <i class="bi bi-shield"></i> Admin Changelogs <span class="badge bg-primary">{{ admin_changelogs|length }}</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-9">
                <div class="tab-content">
                    <!-- User Changelogs Tab -->
                    <div class="tab-pane fade show active" id="user-tab" role="tabpanel">
                        <div class="card">
                            <div class="card-header">
                                <i class="bi bi-people"></i> User Changelogs
                            </div>
                            <div class="card-body">
                                {% if user_changelogs %}
                                    {% for changelog in user_changelogs|reverse %}
                                        <div class="changelog-item user">
                                            <div class="changelog-timestamp">
                                                <i class="bi bi-clock"></i> {{ changelog.timestamp }}
                                            </div>
                                            <div class="changelog-content">{{ changelog.content }}</div>
                                            {% if changelog.seen_by %}
                                            <div class="mt-2 text-light-muted small">
                                                <i class="bi bi-eye"></i> Seen by {{ changelog.seen_by|length }} users
                                            </div>
                                            {% endif %}
                                        </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="empty-state">
                                        <i class="bi bi-journal-x"></i>
                                        <p>No user changelogs found</p>
                                    </div>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    
                    <!-- Admin Changelogs Tab -->
                    <div class="tab-pane fade" id="admin-tab" role="tabpanel">
                        <div class="card">
                            <div class="card-header">
                                <i class="bi bi-shield"></i> Admin Changelogs
                            </div>
                            <div class="card-body">
                                {% if admin_changelogs %}
                                    {% for changelog in admin_changelogs|reverse %}
                                        <div class="changelog-item admin">
                                            <div class="changelog-timestamp">
                                                <i class="bi bi-clock"></i> {{ changelog.timestamp }}
                                            </div>
                                            <div class="changelog-content">{{ changelog.content }}</div>
                                        </div>
                                    {% endfor %}
                                {% else %}
                                    <div class="empty-state">
                                        <i class="bi bi-journal-x"></i>
                                        <p>No admin changelogs found</p>
                                    </div>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# Add a logout route
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))


@app.route('/logs')
@login_required
def logs():
    # Get current time in Philippines timezone
    # Use system time instead of hardcoded date
    current_time = datetime.now(pytz.timezone('Asia/Manila')).strftime('%Y-%m-%d %I:%M:%S %p')
    
    return render_template_string(
        LOGS_TEMPLATE,
        logs=web_handler.log_entries,
        log_count=len(web_handler.log_entries),
        current_time=current_time
    )

@app.route('/logs/data')
@login_required
def logs_data():
    """API endpoint to get logs data for AJAX refresh"""
    # Use system time instead of hardcoded date
    
    return jsonify({
        'logs': web_handler.log_entries,
        'log_count': len(web_handler.log_entries),
        'current_time': datetime.now(pytz.timezone('Asia/Manila')).strftime('%Y-%m-%d %I:%M:%S %p')
    })

@app.route('/logs/clear')
@login_required
def clear_logs():
    web_handler.log_entries = []
    return "Logs cleared successfully"

@app.route('/dashboard')
@login_required
def dashboard():
    """Membership dashboard showing active, expiring, and expired memberships"""
    # Connect to the MongoDB database that's already set up in bot.py
    from pymongo import MongoClient
    import os
    from datetime import datetime, timedelta
    
    # Get MongoDB connection details from environment
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    DB_NAME = os.getenv('DB_NAME', 'PTABotDB')
    
    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    payment_collection = db['payments']
    
    # Get current time in Philippines timezone
    manila_tz = pytz.timezone('Asia/Manila')
    current_time = datetime.now(manila_tz)
    
    # Fetch all membership data
    all_memberships = list(payment_collection.find())
    
    # Categorize memberships
    active_memberships = []
    expiring_soon = []
    expired_memberships = []

    def calculate_start_date(end_date_str, plan_name):
        try:
            # Parse the end date string to a datetime object
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')
            
            # Determine plan duration
            if 'yearly' in plan_name.lower() or '1 year' in plan_name.lower():
                # Yearly plan (subtract 365 days)
                start_date = end_date - timedelta(days=365)
            else:
                # Default to monthly plan (subtract 30 days)
                start_date = end_date - timedelta(days=30)
                
            # Return formatted date string
            return start_date.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return 'Unknown'
    
    for member in all_memberships:
        # Skip members that don't have due_date
        if 'due_date' not in member:
            continue
            
        # Convert due_date string to datetime and make it timezone-aware
        try:
            due_date = datetime.strptime(member['due_date'], '%Y-%m-%d %H:%M:%S')
            # Make the datetime timezone-aware by attaching the Manila timezone
            due_date = manila_tz.localize(due_date)
            
            # Format the username safely
            username = member.get('username', 'No Username') or 'No Username'
            
            # Create a membership entry with all necessary data
            membership = {
                "name": f"@{username}" if username != 'No Username' else f"User {member['_id']}",
                "user_id": member['_id'],
                "plan": member.get('payment_plan', 'Unknown'),
                "start_date": calculate_start_date(member['due_date'], member.get('payment_plan', '')),
                "end_date": member['due_date'],
                "payment_method": member.get('payment_mode', 'Unknown'),
                "days_remaining": (due_date - current_time).days,
                "has_paid": member.get('haspayed', False),
                "cancelled": member.get('cancelled', False)
            }
            
            # Categorize based on payment status and expiration
            if not member.get('haspayed', False):
                expired_memberships.append(membership)
            elif (due_date - current_time).days <= 7:
                expiring_soon.append(membership)
            else:
                active_memberships.append(membership)
                
        except Exception as e:
            print(f"Error processing member {member['_id']}: {e}")
    
    # Sort all categories by days_remaining
    active_memberships.sort(key=lambda x: x['days_remaining'])
    expiring_soon.sort(key=lambda x: x['days_remaining'])
    expired_memberships.sort(key=lambda x: x.get('days_remaining', -9999), reverse=True)
    
    return render_template_string(DASHBOARD_TEMPLATE,
        current_time=current_time.strftime('%Y-%m-%d %I:%M:%S %p'),
        active_count=len(active_memberships),
        expiring_soon_count=len(expiring_soon),
        expired_count=len(expired_memberships),
        active_memberships=active_memberships,
        expiring_soon=expiring_soon,
        expired_memberships=expired_memberships
    )

@app.route('/export/members.csv')
@login_required
def export_members():
    from pymongo import MongoClient
    import os
    from datetime import datetime, timedelta
    import csv
    from io import StringIO
    from flask import Response
    
    # Get MongoDB connection details from environment
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    DB_NAME = os.getenv('DB_NAME', 'PTABotDB')
    
    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    payment_collection = db['payments']
    
    # Get all members
    all_memberships = list(payment_collection.find())
    
    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header row
    writer.writerow(['User ID', 'Username', 'Plan', 'Start Date', 'End Date', 
                     'Days Remaining', 'Payment Method', 'Payment Status', 'Cancellation Status'])
    
    # Get current time for calculating days remaining
    manila_tz = pytz.timezone('Asia/Manila')
    current_time = datetime.now(manila_tz)
    
    # Process each member and add to CSV
    for member in all_memberships:
        # Skip members that don't have due_date
        if 'due_date' not in member:
            continue
            
        # Calculate days remaining
        try:
            due_date = datetime.strptime(member['due_date'], '%Y-%m-%d %H:%M:%S')
            due_date = manila_tz.localize(due_date)
            days_remaining = (due_date - current_time).days
        except:
            days_remaining = 'Unknown'
        
        # Get username safely
        username = member.get('username', 'No Username') or 'No Username'
        
        # Calculate start date from end date and plan
        start_date = 'Unknown'
        try:
            plan_name = member.get('payment_plan', '')
            if 'yearly' in plan_name.lower() or '1 year' in plan_name.lower():
                start_date = (due_date - timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S')
            else:  # Default to monthly
                start_date = (due_date - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
        
        # Write member data to CSV
        writer.writerow([
            member['_id'],
            username,
            member.get('payment_plan', 'Unknown'),
            start_date,
            member.get('due_date', 'Unknown'),
            days_remaining,
            member.get('payment_mode', 'Unknown'),
            'Paid' if member.get('haspayed', False) else 'Unpaid',
            'Cancelled' if member.get('cancelled', False) else 'Active'
        ])
    
    # Create response with CSV data
    response = Response(
        output.getvalue(), 
        mimetype='text/csv', 
        headers={'Content-Disposition': f'attachment; filename=ptabot_members_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'}
    )
    
    # Log the export action
    logging.info(f"Admin {session['username']} exported members data to CSV")
    
    return response

@app.route('/changelogs')
@login_required
def changelogs_page():
    """Display admin and user changelogs"""
    # Get changelogs from MongoDB
    from pymongo import MongoClient
    import os

    # Get MongoDB connection details from environment
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    DB_NAME = os.getenv('DB_NAME', 'PTABotDB')
    
    # Connect to MongoDB
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    changelog_collection = db['changelogs']
    
    # Get changelogs from MongoDB
    doc = changelog_collection.find_one({'_id': 'changelogs'})
    if doc:
        changelogs = {k: v for k, v in doc.items() if k != '_id'}
    else:
        changelogs = {"admin": [], "user": []}
    
    # Get current time in Philippines timezone
    current_time = datetime.now(pytz.timezone('Asia/Manila')).strftime('%Y-%m-%d %I:%M:%S %p')
    
    return render_template_string(
        CHANGELOGS_TEMPLATE,
        admin_changelogs=changelogs.get('admin', []),
        user_changelogs=changelogs.get('user', []),
        current_time=current_time
    )

def ping_server():
    """Send a request to keep the server alive"""
    try:
        # Replace with your actual Render.com URL
        url = "https://ptabot.onrender.com"  # Replace this with your actual URL
        
        # Get current time in Philippines timezone for logging
        manila_time = datetime.now(pytz.timezone('Asia/Manila')).strftime('%Y-%m-%d %I:%M:%S %p')
        
        # Send the request
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            logging.info(f"[{manila_time}] Keep-alive ping successful")
        else:
            logging.warning(f"[{manila_time}] Keep-alive ping failed with status code: {response.status_code}")
    
    except Exception as e:
        logging.error(f"Error sending keep-alive ping: {e}")

def setup_keep_alive_scheduler():
    """Set up a scheduler to keep the server alive"""
    scheduler = BackgroundScheduler()
    
    # Add job to run every 14 minutes (just like the JS version)
    scheduler.add_job(
        ping_server,
        IntervalTrigger(minutes=14),
        id='keep_alive_job',
        name='Keep server alive',
        replace_existing=True
    )
    
    # Start the scheduler
    scheduler.start()
    logging.info("Keep-alive scheduler started - pinging every 14 minutes")
    
    return scheduler

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    # Start the web server in a separate thread
    t = Thread(target=run)
    t.daemon = True
    t.start()
    logging.info("Web interface started at http://0.0.0.0:8080")
    
    # Set up the ping scheduler
    scheduler = setup_keep_alive_scheduler()
    
    # Log that both systems are running
    logging.info("PTABot server and keep-alive system are now running")