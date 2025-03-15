from flask import Flask, render_template_string, request, jsonify
from threading import Thread
import logging
import io
import sys
from datetime import datetime
import pytz
import json
import werkzeug.serving

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

app = Flask('')

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
            
            # Store both formatted log and metadata
            log_data = {
                'message': log_entry,
                'level': level_name,
                'timestamp': datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
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
            --primary-color: #4CAF50;
            --primary-dark: #388E3C;
            --secondary-color: #2196F3;
            --dark-bg: #1a1a1a;
            --card-bg: #2d2d2d;
            --text-color: #e0e0e0;
            --muted-text: #a0a0a0;
            --border-color: #444;
        }
        
        body {
            background-color: var(--dark-bg);
            color: var(--text-color);
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
        }
        
        .navbar {
            background-color: var(--card-bg) !important;
            border-bottom: 1px solid var(--border-color);
        }
        
        .navbar-brand {
            color: var(--primary-color) !important;
            font-weight: bold;
            font-size: 1.5rem;
        }
        
        .navbar-dark .navbar-nav .nav-link {
            color: var(--text-color);
        }
        
        .navbar-dark .navbar-nav .nav-link:hover {
            color: var(--primary-color);
        }
        
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.15);
            margin-bottom: 20px;
            border-radius: 10px;
        }
        
        .card-header {
            background-color: rgba(0, 0, 0, 0.2);
            border-bottom: 1px solid var(--border-color);
            font-weight: bold;
            color: var(--primary-color);
        }
        
        .btn-primary {
            background-color: var(--primary-color);
            border-color: var(--primary-dark);
        }
        
        .btn-primary:hover {
            background-color: var(--primary-dark);
            border-color: var(--primary-dark);
        }
        
        .btn-outline-secondary {
            color: var(--text-color);
            border-color: var(--border-color);
        }
        
        .btn-outline-secondary:hover {
            background-color: var(--card-bg);
            color: var(--primary-color);
        }
        
        .log-entry {
            padding: 8px 12px;
            margin-bottom: 8px;
            border-radius: 6px;
            border-left: 4px solid transparent;
            background-color: rgba(0, 0, 0, 0.15);
            transition: all 0.2s ease;
            font-family: 'Consolas', 'Monaco', monospace;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        
        .log-entry:hover {
            background-color: rgba(0, 0, 0, 0.25);
        }
        
        .log-level {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            margin-right: 8px;
            font-weight: bold;
            width: 70px;
            text-align: center;
        }
        
        .log-timestamp {
            color: var(--muted-text);
            margin-right: 8px;
            font-size: 0.9em;
        }
        
        .log-info {
            border-left-color: #4CAF50;
        }
        
        .log-info .log-level {
            background-color: rgba(76, 175, 80, 0.2);
            color: #4CAF50;
        }
        
        .log-error {
            border-left-color: #f44336;
        }
        
        .log-error .log-level {
            background-color: rgba(244, 67, 54, 0.2);
            color: #f44336;
        }
        
        .log-warning {
            border-left-color: #FFC107;
        }
        
        .log-warning .log-level {
            background-color: rgba(255, 193, 7, 0.2);
            color: #FFC107;
        }
        
        .log-debug {
            border-left-color: #2196F3;
        }
        
        .log-debug .log-level {
            background-color: rgba(33, 150, 243, 0.2);
            color: #2196F3;
        }
        
        .log-critical {
            border-left-color: #E91E63;
        }
        
        .log-critical .log-level {
            background-color: rgba(233, 30, 99, 0.2);
            color: #E91E63;
        }
        
        .refresh-animation {
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .stats-value {
            font-size: 1.8rem;
            font-weight: bold;
            color: var(--primary-color);
        }
        
        .stats-label {
            color: var(--muted-text);
            font-size: 0.9rem;
        }
        
        #search-box {
            background-color: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            color: var(--text-color);
        }
        
        #search-box::placeholder {
            color: var(--muted-text);
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--muted-text);
        }
        
        /* Auto-refresh toggle switch */
        .form-check-input:checked {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
        }
        
        .auto-refresh-container {
            display: flex;
            align-items: center;
        }
        
        .auto-refresh-label {
            margin-left: 8px;
            color: var(--muted-text);
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
                        <a class="nav-link active" href="/logs"><i class="bi bi-journal-text"></i> Logs</a>
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
                    --primary-color: #4CAF50;
                    --primary-dark: #388E3C;
                    --secondary-color: #2196F3;
                    --dark-bg: #1a1a1a;
                    --card-bg: #2d2d2d;
                    --text-color: #e0e0e0;
                    --muted-text: #a0a0a0;
                    --border-color: #444;
                }
                
                body {
                    background-color: var(--dark-bg);
                    color: var(--text-color);
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                }
                
                .navbar {
                    background-color: var(--card-bg) !important;
                    border-bottom: 1px solid var(--border-color);
                }
                
                .navbar-brand {
                    color: var(--primary-color) !important;
                    font-weight: bold;
                    font-size: 1.5rem;
                }
                
                .navbar-dark .navbar-nav .nav-link {
                    color: var(--text-color);
                }
                
                .navbar-dark .navbar-nav .nav-link:hover {
                    color: var(--primary-color);
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
                    box-shadow: 0 10px 20px rgba(0, 0, 0, 0.2);
                    border-radius: 12px;
                    padding: 2rem;
                    max-width: 600px;
                    width: 100%;
                }
                
                .welcome-icon {
                    font-size: 5rem;
                    color: var(--primary-color);
                    margin-bottom: 1.5rem;
                }
                
                .welcome-title {
                    font-size: 2.5rem;
                    color: var(--primary-color);
                    margin-bottom: 1rem;
                }
                
                .welcome-subtitle {
                    color: var(--muted-text);
                    margin-bottom: 2rem;
                }
                
                .btn-primary {
                    background-color: var(--primary-color);
                    border-color: var(--primary-dark);
                    padding: 0.75rem 2rem;
                    font-weight: bold;
                    font-size: 1.1rem;
                    transition: all 0.3s ease;
                }
                
                .btn-primary:hover {
                    background-color: var(--primary-dark);
                    transform: translateY(-2px);
                    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
                }
                
                .status-indicator {
                    display: inline-block;
                    width: 15px;
                    height: 15px;
                    border-radius: 50%;
                    background-color: var(--primary-color);
                    margin-right: 8px;
                    animation: pulse 2s infinite;
                }
                
                @keyframes pulse {
                    0% { opacity: 1; }
                    50% { opacity: 0.5; }
                    100% { opacity: 1; }
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
                                <a class="nav-link" href="/logs"><i class="bi bi-journal-text"></i> Logs</a>
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
                    
                    <div class="d-flex justify-content-center mb-4">
                        <span class="status-indicator"></span>
                        <span>Bot is currently operational</span>
                    </div>
                    
                    <a href="/logs" class="btn btn-primary">
                        <i class="bi bi-journal-text"></i> View Logs
                    </a>
                </div>
            </div>
            
            <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
        </body>
        </html>
    ''')

@app.route('/logs')
def logs():
    # Get current time in Philippines timezone
    current_time = datetime.now(pytz.timezone('Asia/Manila')).strftime('%Y-%m-%d %I:%M:%S %p')
    
    return render_template_string(
        LOGS_TEMPLATE,
        logs=web_handler.log_entries,
        log_count=len(web_handler.log_entries),
        current_time=current_time
    )

@app.route('/logs/data')
def logs_data():
    """API endpoint to get logs data for AJAX refresh"""
    return jsonify({
        'logs': web_handler.log_entries,
        'log_count': len(web_handler.log_entries),
        'current_time': datetime.now(pytz.timezone('Asia/Manila')).strftime('%Y-%m-%d %I:%M:%S %p')
    })

@app.route('/logs/clear')
def clear_logs():
    web_handler.log_entries = []
    return "Logs cleared successfully"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():  
    t = Thread(target=run)
    t.daemon = True  # This ensures the thread will exit when the main program exits
    t.start()
    logging.info("Web interface started at http://0.0.0.0:8080")