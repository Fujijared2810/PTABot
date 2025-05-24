from bot import server, bot, WEBHOOK_SECRET_PATH

# Register webhook route explicitly here
from flask import request
import telebot
import logging

@server.route('/' + WEBHOOK_SECRET_PATH, methods=['POST'])
def webhook():
    try:
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    except Exception as e:
        logging.error(f"Error in webhook handler: {e}", exc_info=True)
        return '', 500

# Add a health check endpoint for monitoring
@server.route('/health', methods=['GET'])
def health_check():
    return 'Bot is running', 200

# Add a root endpoint
@server.route('/', methods=['GET'])
def index():
    return 'PTA Bot is running', 200

if __name__ == "__main__":
    # Import the bot setup function and run it
    from bot import set_webhook
    set_webhook()
    
    # Run the server
    server.run(host='0.0.0.0', port=5000)