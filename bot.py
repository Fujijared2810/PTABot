import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, ChatInviteLink, InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiException
import time
import threading
from datetime import datetime, timedelta
import re
import os
from dotenv import load_dotenv
import logging
import signal
import sys
import pytz
import pymongo
from pymongo import MongoClient
import random
import secrets  # Using secrets module for more secure randomness
from datetime import datetime
from keep_alive import keep_alive
import calendar
from collections import Counter


BOT_VERSION = "Alpha Release 4.1"

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
DB_NAME = os.getenv('DB_NAME', 'PTABotDB')
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_IDS = list(map(int, os.getenv('ADMIN_IDS').split(',')))
PAID_GROUP_ID = int(os.getenv('PAID_GROUP_ID'))
CREATOR_ID = int(os.getenv('CREATOR_ID', '0'))

# Initialize MongoDB connection
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# Define collections
payment_collection = db['payments']
old_members_collection = db['old_members']
pending_collection = db['pending']
changelog_collection = db['changelogs']
settings_collection = db['settings']
scores_collection = db['scores']  # For storing user scores
accountability_collection = db['accountability']  # For tracking submissions
reminder_messages_collection = db['reminder_messages']
gif_status_collection = db['gif_status']

bot = telebot.TeleBot(BOT_TOKEN)

# Function to handle termination signals (Ctrl+C, kill command)
def signal_handler(sig, frame):
    logging.info("Stopping bot...")
    bot.stop_polling()  # Stop bot polling first
    sys.exit(0)  # Exit program

# Attach signal handler for Ctrl+C
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Keep your PhilippineTimeFormatter class
class PhilippineTimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        # Convert the time to Philippine time (UTC+8)
        philippine_time = datetime.fromtimestamp(record.created, pytz.timezone('Asia/Manila'))
        # Format the time in 12-hour format
        return philippine_time.strftime('%Y-%m-%d %I:%M:%S %p')

# Fix for duplicate logging - clear existing handlers first
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create and configure file handler
file_handler = logging.FileHandler('bot.log')
file_handler.setLevel(logging.INFO)

# Create and configure console handler (this sends to terminal)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

# Create formatter
formatter = PhilippineTimeFormatter('%(asctime)s - %(levelname)s - %(message)s')

# Add formatter to handlers
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)

def get_last_gif_message():
    """Get the ID of the last sent GIF message"""
    try:
        status = gif_status_collection.find_one({"_id": "last_gif"})
        if status:
            return status.get("message_id")
        return None
    except Exception as e:
        logging.error(f"Error getting last GIF message ID: {e}")
        return None

def save_last_gif_message(message_id):
    """Save the ID of the last sent GIF message"""
    try:
        gif_status_collection.replace_one(
            {"_id": "last_gif"}, 
            {"_id": "last_gif", "message_id": message_id, "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, 
            upsert=True
        )
        logging.info(f"Saved last GIF message ID: {message_id}")
    except Exception as e:
        logging.error(f"Error saving last GIF message ID: {e}")

def load_reminder_messages():
    """Load reminder messages from MongoDB."""
    try:
        messages = {}
        for doc in reminder_messages_collection.find():
            user_id = int(doc['_id'])
            
            # Convert admin_msg_ids from string keys back to integer keys
            admin_msg_ids = {}
            if 'admin_msg_ids' in doc:
                for admin_id_str, msg_id in doc['admin_msg_ids'].items():
                    admin_msg_ids[int(admin_id_str)] = msg_id
            
            messages[user_id] = {
                'user_msg_id': doc.get('user_msg_id'),
                'admin_msg_ids': admin_msg_ids
            }
            
        logging.info(f"Loaded {len(messages)} reminder messages from MongoDB")
        return messages
    except Exception as e:
        logging.error(f"MongoDB error loading reminder messages: {e}")
        return {}

def save_reminder_message(user_id, data):
    """Save a single reminder message to MongoDB."""
    try:
        # Convert user_id to string for MongoDB _id
        doc = {'_id': str(user_id)}
        
        # Create a copy of the data to avoid modifying the original
        mongo_data = data.copy()
        
        # Convert admin_msg_ids to use string keys for MongoDB compatibility
        if 'admin_msg_ids' in mongo_data:
            string_admin_ids = {}
            for admin_id, msg_id in mongo_data['admin_msg_ids'].items():
                string_admin_ids[str(admin_id)] = msg_id
            mongo_data['admin_msg_ids'] = string_admin_ids
        
        # Update the document with the modified data
        doc.update(mongo_data)
        
        # Use upsert to update if exists or insert if new
        reminder_messages_collection.replace_one({'_id': str(user_id)}, doc, upsert=True)
        logging.info(f"Saved reminder message for user {user_id}")
    except Exception as e:
        logging.error(f"MongoDB error saving reminder message for user {user_id}: {e}")

def delete_reminder_message(user_id):
    """Delete a reminder message from MongoDB."""
    try:
        result = reminder_messages_collection.delete_one({'_id': str(user_id)})
        if result.deleted_count > 0:
            logging.info(f"Deleted reminder message for user {user_id} from MongoDB")
        else:
            logging.info(f"No reminder message for user {user_id} found to delete in MongoDB")
    except Exception as e:
        logging.error(f"Error deleting reminder message for user {user_id} from MongoDB: {e}")

def load_settings():
    """Load bot settings from MongoDB."""
    try:
        settings = settings_collection.find_one({'_id': 'bot_settings'})
        if settings:
            return {k: v for k, v in settings.items() if k != '_id'}
        return {}  # Return empty dict if no settings found
    except Exception as e:
        logging.error(f"MongoDB error loading settings: {e}")
        return {}

# Add this function to save settings to MongoDB
def save_settings(settings):
    """Save bot settings to MongoDB."""
    try:
        doc = {'_id': 'bot_settings'}
        doc.update(settings)
        settings_collection.replace_one({'_id': 'bot_settings'}, doc, upsert=True)
        logging.info("Bot settings saved to MongoDB")
    except Exception as e:
        logging.error(f"MongoDB save error for settings: {e}")

# Load confirmed old members from MongoDB
def load_confirmed_old_members():
    try:
        confirmed = {}
        for doc in old_members_collection.find():
            user_id = doc['_id']
            confirmed[user_id] = {k: v for k, v in doc.items() if k != '_id'}
        return confirmed
    except Exception as e:
        logging.error(f"MongoDB error: {e}")
        return {}

# Save confirmed old members to MongoDB
def save_confirmed_old_members():
    try:
        old_members_collection.delete_many({})
        for user_id, data in CONFIRMED_OLD_MEMBERS.items():
            doc = {'_id': user_id}
            doc.update(data)
            old_members_collection.insert_one(doc)
    except Exception as e:
        logging.error(f"MongoDB save error: {e}")

# Similarly implement load_payment_data() and save_payment_data()
def load_payment_data():
    try:
        payments = {}
        for doc in payment_collection.find():
            user_id = doc['_id']
            payments[user_id] = {k: v for k, v in doc.items() if k != '_id'}
        return payments
    except Exception as e:
        logging.error(f"MongoDB error loading payments: {e}")
        return {}

def save_payment_data():
    try:
        # Use bulk operations for efficiency
        operations = []
        for user_id, data in PAYMENT_DATA.items():
            doc = {'_id': user_id}
            doc.update(data)
            operations.append(
                pymongo.ReplaceOne({'_id': user_id}, doc, upsert=True)
            )
        if operations:
            payment_collection.bulk_write(operations)
    except Exception as e:
        logging.error(f"MongoDB save error: {e}")

# Load changelogs from JSON file
def load_changelogs():
    try:
        doc = changelog_collection.find_one({'_id': 'changelogs'})
        if doc:
            return {k: v for k, v in doc.items() if k != '_id'}
        return {"admin": [], "user": []}
    except Exception as e:
        logging.error(f"MongoDB error loading changelogs: {e}")
        return {"admin": [], "user": []}

# Save changelogs to JSON file
def save_changelogs(changelogs):
    try:
        doc = {'_id': 'changelogs'}
        doc.update(changelogs)
        changelog_collection.replace_one({'_id': 'changelogs'}, doc, upsert=True)
    except Exception as e:
        logging.error(f"MongoDB save error: {e}")

def save_pending_users():
    try:
        operations = []
        for user_id, data in PENDING_USERS.items():
            doc = {'_id': str(user_id)}  # Convert to string for MongoDB _id
            doc.update(data)
            operations.append(
                pymongo.ReplaceOne({'_id': str(user_id)}, doc, upsert=True)
            )
        if operations:
            pending_collection.bulk_write(operations)
        logging.info(f"Saved {len(operations)} pending users to MongoDB")
    except Exception as e:
        logging.error(f"MongoDB save error for pending users: {e}")

def load_pending_users():
    try:
        pending = {}
        for doc in pending_collection.find():
            # Convert string _id back to int for PENDING_USERS dictionary
            user_id = int(doc['_id'])
            pending[user_id] = {k: v for k, v in doc.items() if k != '_id'}
        logging.info(f"Loaded {len(pending)} pending users from MongoDB")
        return pending
    except Exception as e:
        logging.error(f"MongoDB error loading pending users: {e}")
        return {}
    
# Load confession counter from MongoDB on startup
def load_confession_counter():
    try:
        counter_doc = settings_collection.find_one({"_id": "confession_counter"})
        if counter_doc:
            return counter_doc.get("value", 0)
        return 0
    except Exception as e:
        logging.error(f"Error loading confession counter: {e}")
        return 0

# Save confession counter to MongoDB
def save_confession_counter(value):
    try:
        settings_collection.replace_one(
            {"_id": "confession_counter"},
            {"_id": "confession_counter", "value": value},
            upsert=True
        )
    except Exception as e:
        logging.error(f"Error saving confession counter: {e}")

# Dictionaries to store user payment data
USER_PAYMENT_DUE = {}
CONFESSION_COUNTER = 0
USERS_CONFESSING = {}
PAYMENT_DATA = load_payment_data()
CONFIRMED_OLD_MEMBERS = load_confirmed_old_members()
PENDING_USERS = load_pending_users() 
CHANGELOGS = load_changelogs()
BOT_SETTINGS = load_settings()
CONFESSION_COUNTER = load_confession_counter()
CONFESSION_TOPIC_ID = BOT_SETTINGS.get('confession_topic_id', None)
DAILY_CHALLENGE_TOPIC_ID = BOT_SETTINGS.get('daily_challenge_topic_id', None)
ANNOUNCEMENT_TOPIC_ID = BOT_SETTINGS.get('announcement_topic_id', None)
ACCOUNTABILITY_TOPIC_ID = BOT_SETTINGS.get('accountability_topic_id', None)
LEADERBOARD_TOPIC_ID = BOT_SETTINGS.get('leaderboard_topic_id', None)


### Different types of messages for the bot ###

already_confirmed_messages = [
    "❗ You are already confirmed as an old member of PTA.",
    "✅ Your status as an old PTA member is already verified in our system!",
    "ℹ️ No need to verify again - you're already confirmed as an original PTA member.",
    "👍 Great news! You're already verified as a legacy PTA member in our database.",
    "🔄 Your old member status is already active in our system - no further verification needed."
]

confirmation_success_messages = [
    "✅ You have been confirmed as an old member of PTA!",
    "🎉 Great news! Your old member status has been verified successfully.",
    "✅ Verification complete! You've been confirmed as an original PTA member.",
    "🌟 Success! Your long-term membership has been recognized in our system.",
    "✅ Congratulations! Your status as an original PTA member has been verified."
]

admin_confirm_messages = [
    "✅ User confirmed successfully.",
    "✅ Old member status verified!",
    "✅ User has been granted legacy member status.",
    "✅ Member verification completed successfully.",
    "✅ Confirmation process completed - user verified as old member."
]

rejection_messages = [
    "❌ Your request to be an old member has been rejected. Please reach out to the admins for more details or use /start to try again.",
    "❌ Unfortunately, we couldn't verify your old member status at this time. Please contact an admin for clarification or use /start to continue.",
    "❌ Your old member verification was not approved. For more information, please contact the admin team or use /start to explore other options.",
    "❌ We were unable to confirm your previous membership status. Please reach out to our team for assistance or use /start to begin again.",
    "❌ Your legacy membership verification was unsuccessful. Please contact an admin for more details or use /start to see available options."
]

payment_review_messages = [
    "✅ *Verification in progress*\n\nYour payment confirmation is under review. Our admin team will verify it shortly and notify you once complete.",
    
    "✅ *Thank you for your submission*\n\nWe've received your payment proof and it's being reviewed by our team. You'll be notified as soon as it's verified.",
    
    "✅ *Processing payment verification*\n\nYour screenshot has been sent to our admin team for review. We'll update you when the verification is complete.",
    
    "✅ *Payment proof received*\n\nThank you for submitting your payment information. Our team is reviewing it and will notify you once verified.",
    
    "✅ *Verification pending*\n\nWe've received your payment details and they are currently under review. You'll receive a notification once the process is complete."
]

payment_approval_messages = [
    "✅ *Verification Successful!*\n\nWelcome to Prodigy Trading Academy. We're delighted to have you as part of our community!",
    
    "✅ *Great news!* Your payment has been verified successfully! Welcome to the Prodigy Trading Academy family. We're thrilled to have you join us!",
    
    "✅ *Payment verified!*\n\nYour membership has been activated. Welcome to Prodigy Trading Academy! We're excited to have you as part of our trading community.",
    
    "✅ *You're all set!*\n\nYour payment has been verified and your membership is now active. Welcome aboard the Prodigy Trading Academy!",
    
    "✅ *Payment confirmed!*\n\nThank you for joining Prodigy Trading Academy. Your membership has been successfully activated and we're looking forward to helping you on your trading journey!"
]

payment_rejection_messages = [
    "❌ *Verification Failed*\n\nUnfortunately, we couldn't verify your payment. Please check your payment details and try again, or contact our admin team for assistance.",
    
    "❌ *Payment Verification Issue*\n\nWe were unable to confirm your payment. Please ensure you've sent the correct amount and try submitting your proof again.",
    
    "❌ *Payment Not Verified*\n\nThere seems to be an issue with your payment verification. Please submit a clearer screenshot or contact our admin team for help.",
    
    "❌ *Verification Unsuccessful*\n\nYour payment proof couldn't be verified at this time. Please check the payment details and try again with a clearer screenshot.",
    
    "❌ *Payment Rejected*\n\nWe couldn't process your payment verification. Please ensure you've completed the payment correctly and submit a new verification request."
]

pending_verification_messages = [
    "⚠️ You have a pending membership verification request. Admins are reviewing your request. Please wait for their response.",
    "⏳ Your membership verification is still being reviewed by our admin team. We'll notify you as soon as they've made a decision.",
    "📝 We've received your membership verification request and it's currently under review. Our team will get back to you shortly.",
    "⌛ Your verification request is in our admin queue. Thanks for your patience while they review your details.",
    "🔍 Our admin team is still reviewing your membership verification. We'll notify you as soon as there's an update."
]

pending_payment_messages = [
    "⚠️ You have a pending payment verification. Admins are reviewing your payment proof. Please wait for their response.",
    "💼 Your payment is currently being verified by our admin team. We'll notify you once the process is complete.",
    "📊 Thanks for your patience! Your payment proof is still under review by our admins. You'll receive a notification when verified.",
    "⏱️ Our team is reviewing your payment submission. We'll let you know as soon as it's verified.",
    "💳 Your payment verification is in progress. Our admin team is reviewing your submission and will notify you shortly."
]

### COMMAND HANDLERS ###

@bot.message_handler(commands=['dm'])
def handle_dm_command(message):
    if message.chat.type == 'private':
        bot.send_message(message.chat.id, "❌ This command can only be used in a channel.")
        return

    user_id = message.from_user.id
    username = message.from_user.username or "No Username"

    # Check if the bot can send a message to the user
    try:
        bot.send_chat_action(user_id, 'typing')  # Check if the user exists and can receive messages
        bot.send_message(user_id, f"Hello @{username}! Please say /start to begin.")
        bot.send_message(message.chat.id, "Direct Message sent, please check your inbox.")
    except ApiException as e:
        bot.send_message(message.chat.id, f"❌ Failed to send DM: {e.result_json['description']}. Please start a conversation with the bot first by sending /start in a private chat.")

# Add this function to delete a specific user from pending
def delete_pending_user(user_id):
    try:
        result = pending_collection.delete_one({'_id': str(user_id)})
        if result.deleted_count > 0:
            logging.info(f"Deleted pending user {user_id} from MongoDB")
        else:
            logging.info(f"No pending user {user_id} found to delete in MongoDB")
    except Exception as e:
        logging.error(f"Error deleting pending user {user_id} from MongoDB: {e}")

# Start Command - Sends intro message and asks for the payment plan
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.chat.type != 'private':
        bot.send_message(message.chat.id, "Please DM the bot to get started.")
        return  # Ignore if not in private chat
    
    chat_id = message.chat.id
    user_id = message.from_user.id

    # Reload pending users from MongoDB to ensure we have latest data
    global PENDING_USERS
    PENDING_USERS = load_pending_users()

    # Check for pending admin actions
    pending_verification = False
    pending_payment = False
    
    if user_id in PENDING_USERS:
        if PENDING_USERS[user_id].get('status') == 'old_member_request':
            pending_verification = True
            logging.info(f"User {user_id} has pending verification request")
        elif PENDING_USERS[user_id].get('status') == 'waiting_approval':
            pending_payment = True
            logging.info(f"User {user_id} has pending payment verification")
        elif PENDING_USERS[user_id].get('status') in ['rejected', 'payment_rejected']:
            # If status is rejected or payment_rejected, reset their status to allow choosing again
            PENDING_USERS.pop(user_id, None)  # Remove from dictionary
            delete_pending_user(user_id)  # Remove from MongoDB
            logging.info(f"User {user_id} with rejected status has been removed from pending users")
            # Continue to display welcome message
    
    # Handle pending requests first - don't show intro message again
    if pending_verification:
        bot.send_message(chat_id, random.choice(pending_verification_messages))
        return  # Exit the function here - don't show the intro message again
    elif pending_payment:
        bot.send_message(chat_id, random.choice(pending_payment_messages))
        return  # Exit the function here - don't show the intro message again
    
    # Only show the intro message and options if there are no pending requests
    bot.send_message(chat_id, f"""
    🏫 Prodigy Trading Academy Enrollment ({BOT_VERSION})

    Welcome to Prodigy Trading Academy! 🎉

    We're pleased to assist you with joining our academy. This marks a significant step in enhancing your trading expertise.

    📢 Note: This bot is currently in {BOT_VERSION}, so you may experience occasional updates or improvements.

    Please select an option below to proceed:
    """)
    
    # Ask for a payment plan
    markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(KeyboardButton("📅 Purchase Membership"), KeyboardButton("🔍 Existing Member Verification"))
    markup.add(KeyboardButton("🔄 Renew Membership"), KeyboardButton("❌ Cancel Membership"))
    bot.send_message(chat_id, "Which service would you like to access??", reply_markup=markup)
    
    PENDING_USERS[chat_id] = {'status': 'choosing_option'}
    save_pending_users()

    # Check if the user has unseen changelogs - ONLY SHOW THE MOST RECENT ONE
    if str(message.from_user.id) in PAYMENT_DATA and PAYMENT_DATA[str(message.from_user.id)]['haspayed']:
        # Initialize tracking variable
        update_shown = False
        
        # Look for the most recent changelog they haven't seen
        for i, changelog in enumerate(reversed(CHANGELOGS["user"])):
            if not update_shown and str(message.from_user.id) not in changelog.get("seen_by", []):
                # Show the unseen changelog (only the most recent one)
                bot.send_message(
                    message.chat.id,
                    f"📢 *UNREAD UPDATE*\n\n{changelog['content']}\n\n🕒 Posted: {changelog['timestamp']}",
                    parse_mode="Markdown"
                )
                # Mark as seen
                if "seen_by" not in changelog:
                    changelog["seen_by"] = []
                    
                changelog["seen_by"].append(str(message.from_user.id))
                save_changelogs(CHANGELOGS)
                
                # Set flag to prevent showing more updates
                update_shown = True
                logging.info(f"Showed unread changelog to user {message.from_user.id}")
                break



def has_user_paid(user_id):
    return str(user_id) in PAYMENT_DATA and PAYMENT_DATA[str(user_id)]['haspayed']

def can_renew_membership(user_id):
    """Check if user can renew their membership based on expiration date"""
    if str(user_id) not in PAYMENT_DATA:
        # Not a current member, so they can "renew" (actually purchase new)
        return True, None
        
    data = PAYMENT_DATA[str(user_id)]
    if not data['haspayed']:
        # Payment expired, they can renew
        return True, None
        
    # Calculate days until expiration
    try:
        due_date = datetime.strptime(data['due_date'], '%Y-%m-%d %H:%M:%S')
        current_date = datetime.now()
        days_remaining = (due_date - current_date).days
        
        # Allow renewal if within 7 days of expiration
        if days_remaining <= 3:
            return True, None
        else:
            return False, f"You still have {days_remaining} days remaining on your current membership. Early renewal is only available within 3 days of expiration."
    except Exception as e:
        logging.error(f"Error checking renewal eligibility: {e}")
        # If there's an error, let them renew to be safe
        return True, None

# Handle Option Selection
@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'choosing_option')
def choose_option(message):
    if message.chat.type != 'private':
        return  # Ignore if not in private chat
    chat_id = message.chat.id
    user_id = message.from_user.id
    option = message.text

    if option in ["📅 Purchase Membership", "🔄 Renew Membership"]:
        if option == "📅 Purchase Membership" and has_user_paid(user_id):
            bot.send_message(chat_id, "✅ You have already paid for your membership. No further action is required.")
            return
        elif option == "🔄 Renew Membership":
            can_renew, message_text = can_renew_membership(user_id)
            if not can_renew:
                bot.send_message(chat_id, message_text)
                return
                
        # Rest of the function remains the same
        if option == "📅 Purchase Membership":
            PENDING_USERS[chat_id]['status'] = 'buy_membership'
            save_pending_users()
            markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(KeyboardButton("Monthly - 499 PHP"), KeyboardButton("Yearly - 5,988 PHP"))
            bot.send_message(chat_id, "Please select your preferred payment plan:\n\n💰 *Monthly* - 499 PHP\n💰 *Yearly* - 5,988 PHP", reply_markup=markup, parse_mode="Markdown")
        elif option == "🔄 Renew Membership":
            PENDING_USERS[chat_id]['status'] = 'renewal_membership_type'
            save_pending_users()
            markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(KeyboardButton("NEW MEMBER (Enrolled after November 2024)"), KeyboardButton("OG MEMBER (Enrolled before November 2024)"))
            bot.send_message(chat_id, "Are you a new member or an old member?", reply_markup=markup)
    elif option == "🔍 Existing Member Verification":
        username = message.from_user.username
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        
        # Create display name using first name and last name when username is not available
        if not username:
            display_name = f"{first_name} {last_name}".strip() or "No Name"
            user_display = f"{display_name} (No Username)"
        else:
            user_display = f"@{username}"

        # Check if the user is already verified
        if str(user_id) in CONFIRMED_OLD_MEMBERS:
            bot.send_message(chat_id, "❗ You are already confirmed as an old member of PTA.")
            return

        PENDING_USERS[chat_id]['status'] = 'old_member_request'
        PENDING_USERS[chat_id]['request_time'] = datetime.now()  # Add timestamp
        save_pending_users()

        # Escape Markdown characters in user display text
        user_display = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', user_display)

        # Forward the request to admins with inline buttons
        for admin in ADMIN_IDS:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Confirm", callback_data=f"confirm_old_{user_id}"))
            markup.add(InlineKeyboardButton("Reject", callback_data=f"reject_old_{user_id}"))
            bot.send_message(admin, 
                f"🔔 *Existing Member Verification Request:*\n"
                f"🆔 {user_display} (ID: `{user_id}`)\n\n"
                "Please review and confirm this user's status.",
                reply_markup=markup,
                parse_mode="Markdown"
            )

        bot.send_message(chat_id, "Your request has been sent to the admins for verification. Please wait.")

    elif option == "❌ Cancel Membership":
        # Check if user has an active membership
        if str(user_id) not in PAYMENT_DATA:
            bot.send_message(chat_id, "❌ You don't have an active membership to cancel.")
            return
            
        # Check if the membership is already cancelled
        if str(user_id) in PAYMENT_DATA and PAYMENT_DATA[str(user_id)].get('cancelled', False):
            due_date = PAYMENT_DATA[str(user_id)].get('due_date', 'Unknown')
            try:
                due_date_obj = datetime.strptime(due_date, '%Y-%m-%d %H:%M:%S')
                days_remaining = (due_date_obj - datetime.now()).days
                
                bot.send_message(
                    chat_id, 
                    f"ℹ️ Your membership is already cancelled.\n\n"
                    f"You will still have access until {due_date_obj.strftime('%Y-%m-%d')} "
                    f"({days_remaining} days remaining).\n\n"
                    f"If you wish to reactivate your membership, please use /start and select 'Renew Membership'."
                )
            except Exception as e:
                # Fallback if date parsing fails
                bot.send_message(chat_id, "ℹ️ Your membership is already cancelled. You will still have access until the next payment cycle.")
            return

        PENDING_USERS[chat_id]['status'] = 'cancel_membership'
        save_pending_users()
        markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add(KeyboardButton("Yes"), KeyboardButton("No"))
        bot.send_message(chat_id, "Are you sure you want to cancel your membership? You will still have access until next month/year, but you will not be charged. Please confirm.", reply_markup=markup)

    else:
        bot.send_message(chat_id, "❌ Invalid option. Please select from the available options.")

# Handle Renewal Membership Type Selection
@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'renewal_membership_type')
def choose_renewal_membership_type(message):
    if message.chat.type != 'private':
        return  # Ignore if not in private chat
    chat_id = message.chat.id
    membership_type = message.text

    if membership_type == "NEW MEMBER (Enrolled after November 2024)":
        PENDING_USERS[chat_id]['status'] = 'renewal_membership_new'
        save_pending_users()
        markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add(KeyboardButton("Monthly - 499 PHP"), KeyboardButton("Yearly - 5,988 PHP"))
        bot.send_message(chat_id, "Renewal options for new members:\n\n💰 *Monthly* - 499 PHP\n💰 *Yearly* - 5,988 PHP", reply_markup=markup, parse_mode="Markdown")

    elif membership_type == "OG MEMBER (Enrolled before November 2024)":
        user_id = message.from_user.id

        # Check if the user is already verified
        if str(user_id) in CONFIRMED_OLD_MEMBERS:
            PENDING_USERS[chat_id]['status'] = 'renewal_membership_old'
            save_pending_users()
            markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(KeyboardButton("Monthly - 199 PHP"), KeyboardButton("Yearly - 2,388 PHP"))
            bot.send_message(chat_id, "Renewal options for old members:\n\n💰 *Monthly* - 199 PHP\n💰 *Yearly* - 2,388 PHP", reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, "❌ You are not an old PTA member.")
            return

    else:
        bot.send_message(chat_id, "❌ Invalid option. Please select either 'New Member' or 'Old Member'.")

# Admin Confirms Old Member
@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_old_"))
def callback_confirm_old_member(call):
    user_id = int(call.data.split("_")[2])
    if call.message.chat.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ You are not authorized to use this action.")
        return

    try:

        # Check if user is already confirmed as an old member
        if user_id in CONFIRMED_OLD_MEMBERS:
            bot.answer_callback_query(call.id, "⚠️ This user has already been confirmed as an old member.")
            bot.send_message(user_id, random.choice(already_confirmed_messages))
            return

        # Modified check - accept if status is old_member_request OR if user has gone back to menu
        if user_id not in PENDING_USERS or (
            PENDING_USERS[user_id].get('status') != 'old_member_request' and 
            not (PENDING_USERS[user_id].get('in_menu', False) and 
                 PENDING_USERS[user_id].get('status') == 'old_member_request')
        ):
            bot.answer_callback_query(call.id, "❌ This user is not waiting for confirmation.")
            return

        # Confirm the user as an old member
        PENDING_USERS[user_id]['status'] = 'old_member_confirmed'
        user_info = bot.get_chat(user_id)
        CONFIRMED_OLD_MEMBERS[str(user_id)] = {
            "username": user_info.username or "No Username",
            "confirmed": True
        }
        save_confirmed_old_members()  # Save to JSON file
        save_pending_users()

        bot.send_message(user_id, random.choice(confirmation_success_messages))
        bot.answer_callback_query(call.id, random.choice(admin_confirm_messages))

        # Log admin activity and notify all admins
        admin_username = call.from_user.username or f"Admin ({call.message.chat.id})"
        user_info = bot.get_chat(user_id)
        username = user_info.username or f"ID: {user_id}"

        # Escape Markdown characters in the usernames
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)
        username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} has confirmed user from old PTA member @{username}.", parse_mode="Markdown")

    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Unexpected error confirming old member: {e}")

# Admin Rejects Old Member
@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_old_"))
def callback_reject_old_member(call):
    user_id = int(call.data.split("_")[2])
    if call.message.chat.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ You are not authorized to use this action.")
        return

    try:
        if user_id not in PENDING_USERS or PENDING_USERS[user_id].get('status') != 'old_member_request':
            bot.answer_callback_query(call.id, "❌ This user is not waiting for confirmation.")
            return

        # Completely remove the user from pending instead of just marking as rejected
        PENDING_USERS.pop(user_id, None)  # Remove from dictionary
        delete_pending_user(user_id)  # Remove from MongoDB
        
        bot.send_message(user_id, random.choice(rejection_messages))
        bot.answer_callback_query(call.id, "❌ User rejected successfully.")

        # Log admin activity and notify all admins
        admin_username = call.from_user.username or f"Admin ({call.message.chat.id})"
        user_info = bot.get_chat(user_id)
        username = user_info.username or f"ID: {user_id}"

        # Escape Markdown characters in the usernames
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)
        username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} has rejected user from old PTA member @{username}.", parse_mode="Markdown")

    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Unexpected error rejecting old member: {e}")

# Handle Payment Plan Selection
@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') in ['buy_membership', 'old_member_confirmed', 'renewal_membership_new', 'renewal_membership_old'])
def choose_payment_plan(message):
    if message.chat.type != 'private':
        return  # Ignore if not in private chat
    chat_id = message.chat.id
    plan_text = message.text.lower()

    if "monthly" in plan_text:
        plan = "Monthly"
    elif "yearly" in plan_text:
        plan = "Yearly"
    else:
        bot.send_message(chat_id, "❌ Please choose either 'Monthly' or 'Yearly'.")
        return

    PENDING_USERS[chat_id]['plan'] = plan
    PENDING_USERS[chat_id]['status'] = 'choosing_payment_method'
    save_pending_users()

    # Ask for a payment method
    markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(KeyboardButton("💳 Paypal"), KeyboardButton("📱 GCash"), KeyboardButton("💸 Exness Direct"), KeyboardButton("🏦 Bank Transfer"))
    bot.send_message(chat_id, "Please select your payment method:", reply_markup=markup)

# Handle Payment Method Selection
@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'choosing_payment_method')
def choose_payment_method(message):
    if message.chat.type != 'private':
        return  # Ignore if not in private chat
    chat_id = message.chat.id
    method = message.text

    if method not in ["💳 Paypal", "🏦 Bank Transfer", "📱 GCash", "📱 PayMaya", "💸 Exness Direct"]:
        bot.send_message(chat_id, "❌ Invalid payment method. Please select a valid method.")
        return

    PENDING_USERS[chat_id]['method'] = method
    PENDING_USERS[chat_id]['status'] = 'awaiting_payment'
    save_pending_users()

    # Send payment credentials based on the selected method
    payment_details = {
        "💳 Paypal": "PayPal:\nOption 1: https://paypal.me/daintyrich\n\nOption 2: \nName: R Mina\nEmail: romeomina061109@gmail.com",
        "🏦 Bank Transfer": "🏦 **Bank Details:**\nBank: BDO\nDebit Number: 5210 6912 0103 9329\nAccount Name: Romeo B. Mina III",
        "📱 GCash": "📱 **GCash Number:** 09274478330 (R. U.)",
        # "📱 PayMaya": "📱 **PayMaya Number:** 09998887777",
        "💸 Exness Direct": {
            "account_id_1": "108377569",
            "email_1": "diamondchay626@gmail.com",
            "account_id_2": "217136604",
            "email_2": "romeomina061109@gmail.com"
        }
    }

    # Format the message properly
    if method == "💸 Exness Direct":
        message = (
            "💰 **Payment Instructions:**\n\n"
            "For Exness Direct:\n"
            f"📌 **Exness Account ID 1:** {payment_details['💸 Exness Direct']['account_id_1']}\n"
            f"📧 **Email 1:** {payment_details['💸 Exness Direct']['email_1']}\n\n"
            f"📌 **Exness Account ID 2:** {payment_details['💸 Exness Direct']['account_id_2']}\n"
            f"📧 **Email 2:** {payment_details['💸 Exness Direct']['email_2']}\n\n"
            "After completing your transaction, please use `/verify` to confirm your payment.\n\n"
            "Note: Your Telegram ID and name will be securely recorded."
        )
    else:
        message = (
            "💰 **Payment Instructions:**\n\n"
            f"{payment_details[method]}\n\n"
            "After completing your transaction, please use `/verify` to confirm your payment.\n\n"
            "Note: Your Telegram ID and name will be securely recorded."
        )

    # Send the message
    bot.send_message(chat_id, message, parse_mode="Markdown")

# Verify Command - Asks for proof of payment
@bot.message_handler(commands=['verify'])
def request_payment_proof(message):
    if message.chat.type != 'private':
        bot.send_message(message.chat.id, "Please DM the bot to get started.")
        return  # Ignore if not in private chat
    chat_id = message.chat.id

    if chat_id not in PENDING_USERS or PENDING_USERS[chat_id]['status'] != 'awaiting_payment':
        bot.send_message(chat_id, "❌ You haven't selected a payment plan and method. Please start with /start.")
        return

    PENDING_USERS[chat_id]['status'] = 'awaiting_proof'
    save_pending_users()
    bot.send_message(chat_id, "📸 Please upload a screenshot of your payment proof.")

# Handle Screenshot Upload
@bot.message_handler(content_types=['photo'])
def handle_payment_screenshot(message):
    if message.chat.type != 'private':
        return  # Ignore if not in private chat
    chat_id = message.chat.id
    if chat_id not in PENDING_USERS or PENDING_USERS[chat_id]['status'] != 'awaiting_proof':
        bot.send_message(chat_id, "❌ Please start verification with `/verify`.")
        return

    user_id = message.from_user.id
    username = message.from_user.username or "No Username"
    plan = PENDING_USERS[chat_id]['plan']
    method = PENDING_USERS[chat_id]['method']

    # Escape Markdown characters in username
    if username != "No Username":
        username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', username)

    # Determine and send due date
    if user_id in PENDING_USERS:
        plan = PENDING_USERS[user_id]['plan']
        due_date = datetime.now() + timedelta(days=365) if plan == "Yearly" else datetime.now() + timedelta(days=30)
    else:
        due_date = datetime.now() + timedelta(days=30)  # Default to monthly if no plan is found

    USER_PAYMENT_DUE[user_id] = due_date

    # Forward the screenshot to Admins WITH payment details and inline buttons
    for admin in ADMIN_IDS:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Approve", callback_data=f"approve_payment_{user_id}"))
        markup.add(InlineKeyboardButton("Reject", callback_data=f"reject_payment_{user_id}"))

        bot.forward_message(admin, chat_id, message.message_id)
        bot.send_message(admin,
            f"🔔 *Payment Request:*\n"
            f"🆔 @{username} (ID: `{user_id}`)\n"
            f"💳 Mode of Payment: {method}\n"
            f"📅 Payment Plan: {plan}\n"
            f"📅 Due Date: {USER_PAYMENT_DUE[user_id].strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    PENDING_USERS[chat_id]['status'] = 'waiting_approval'
    PENDING_USERS[chat_id]['request_time'] = datetime.now()  # Add timestamp
    delete_pending_user(user_id)
    save_pending_users()
    bot.send_message(chat_id, random.choice(payment_review_messages), parse_mode="Markdown")

# Admin Approves Payment
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_payment_"))
def callback_approve_payment(call):
    user_id = int(call.data.split("_")[2])
    if call.message.chat.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ You are not authorized to use this action.")
        return

    try:
        # Check if this is a renewal (special case)
        is_renewal = False
        if user_id in PENDING_USERS and PENDING_USERS[user_id].get('status') in ['waiting_approval'] and str(user_id) in PAYMENT_DATA:
            # This is likely a renewal if they went through the workflow and already have payment data
            is_renewal = True

        # Only check if already paid when it's NOT a renewal
        if not is_renewal and str(user_id) in PAYMENT_DATA and PAYMENT_DATA[str(user_id)]['haspayed']:
            bot.answer_callback_query(call.id, "⚠️ This user has already been approved.")
            return

        # Determine the plan and payment mode
        if user_id in PENDING_USERS:
            plan = PENDING_USERS[user_id].get('plan', 'Monthly')  # Default to 'Monthly' if not found
            payment_mode = PENDING_USERS[user_id].get('method', 'Unknown')  # Default to 'Unknown' if not found
            due_date = datetime.now() + timedelta(days=365) if plan == "Yearly" else datetime.now() + timedelta(days=30)
            PENDING_USERS.pop(user_id, None)  # Remove from pending list
            delete_pending_user(user_id)
        else:
            plan = 'Monthly'
            payment_mode = 'Unknown'
            due_date = datetime.now() + timedelta(days=30)  # Default to monthly if no plan is found

        save_pending_users()

        # Get user info directly from Telegram to ensure correct username
        try:
            user_info = bot.get_chat(user_id)
            username = user_info.username or "No Username"
        except Exception:
            username = "No Username"  # Fallback if can't get username

        # Save payment data with USER'S username (not admin's)
        PAYMENT_DATA[str(user_id)] = {
            "username": username,  # Use the user's username instead of admin's
            "payment_plan": plan,
            "payment_mode": payment_mode,
            "due_date": due_date.strftime('%Y-%m-%d %H:%M:%S'),
            "haspayed": True
        }
        logging.info(f"Saving payment data for user {user_id}: {PAYMENT_DATA[str(user_id)]}")
        save_payment_data()  # Ensure this function is called to save the data

        # ✅ Check if the bot can message the user
        try:
            bot.send_chat_action(user_id, 'typing')  # Check if the user exists
        except ApiException:
            bot.answer_callback_query(call.id, "❌ Error: I can't message this user. They need to start the bot first.")
            return

        # Log admin activity and notify all admins
        admin_username = call.from_user.username or f"Admin ({call.message.chat.id})"
        user_info = bot.get_chat(user_id)
        username = user_info.username or f"ID: {user_id}"

        # Escape Markdown characters in the usernames
        username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', username)
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} has approved payment from PTA member @{username}.", parse_mode="Markdown")

        # ✅ Step 1: Verification successful
        bot.send_message(user_id, random.choice(payment_approval_messages), parse_mode="Markdown")
        bot.answer_callback_query(call.id, "✅ Payment approved successfully.")

        # 📅 Step 2: Determine and send due date
        USER_PAYMENT_DUE[user_id] = due_date
        bot.send_message(user_id, f"📅 **Your next payment is due on:** {due_date.strftime('%Y/%m/%d %I:%M:%S %p')}.")

        # 🔍 Step 3: Check if the user is already in the group
        try:
            member = bot.get_chat_member(PAID_GROUP_ID, user_id)
            if member.status in ["member", "administrator", "creator"]:
                bot.send_message(user_id, "✅ You already have access to the group.")
                return  # Stop here, no invite needed
        except Exception:
            pass  # User not found in the group

        # 🚀 Step 4: User is not in the group → Create a one-time use invite link
        try:
            invite_link: ChatInviteLink = bot.create_chat_invite_link(
                PAID_GROUP_ID,
                member_limit=1,  # One-time use only
                creates_join_request=False
            )
            bot.send_message(user_id, f"🔗 Group Access: Please join our members' community here: {invite_link.invite_link}")

            # ⏳ Step 5: Delay revocation and notify admins
            def revoke_link_later(chat_id, invite_link, admin_ids):
                time.sleep(15)  # Wait 15 seconds before revoking
                try:
                    bot.revoke_chat_invite_link(chat_id, invite_link)
                    for admin_id in admin_ids:
                        bot.send_message(admin_id, f"🔒 One-time invite link revoked: {invite_link}")
                except ApiException as e:
                    print(f"⚠️ Failed to revoke invite link: {e}")

            threading.Thread(target=revoke_link_later, args=(PAID_GROUP_ID, invite_link.invite_link, ADMIN_IDS)).start()

        except ApiException as e:
            bot.send_message(call.message.chat.id, f"❌ Link generation failed: {e.result_json['description']}")
            return
        
        # Send thank you message instead of requesting feedback
        bot.send_message(user_id, "Thank you for joining Prodigy Trading Academy! If you have any questions, feel free to ask our admins.")
        # Don't add them to PENDING_USERS for feedback - removed this line:
        # PENDING_USERS[user_id] = {'status': 'awaiting_feedback'}

        # 🔒 Step 6: Ensure bot is an admin before adding restrictions
        try:
            bot.restrict_chat_member(PAID_GROUP_ID, user_id, can_send_messages=True)
        except ApiException as e:
            bot.send_message(call.message.chat.id, f"⚠️ Warning: Could not restrict user in the group. Error: {e}")

    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Unexpected error approving payment: {e}")

# Admin Rejects Payment
@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_payment_"))
def callback_reject_payment(call):
    user_id = int(call.data.split("_")[2])
    if call.message.chat.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ You are not authorized to use this action.")
        return

    try:
        # Check if the user already has an approved payment
        if str(user_id) in PAYMENT_DATA and PAYMENT_DATA[str(user_id)]['haspayed']:
            bot.answer_callback_query(call.id, "⚠️ This user has already been approved. Cannot reject.")
            return

        # Check if user is actually waiting for payment verification
        if user_id not in PENDING_USERS or PENDING_USERS[user_id].get('status') != 'waiting_approval':
            bot.answer_callback_query(call.id, "❌ This user is not waiting for payment verification.")
            return

        bot.send_message(user_id, random.choice(payment_rejection_messages), parse_mode="Markdown")
        PENDING_USERS.pop(user_id, None)
        save_pending_users()
        bot.answer_callback_query(call.id, "❌ Payment rejected successfully.")

        # Log admin activity and notify all admins
        admin_username = call.from_user.username or f"Admin ({call.message.chat.id})"
        user_info = bot.get_chat(user_id)
        username = user_info.username or f"ID: {user_id}"

        # Escape Markdown characters in the usernames
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)
        username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} has rejected payment from PTA member @{username}.", parse_mode="Markdown")

    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Unexpected error rejecting payment: {e}")

@bot.message_handler(content_types=['new_chat_members'])
def welcome_new_members(message):
    """Welcome new members when they join the group"""
    try:
        # Only activate in the paid group
        if message.chat.id != PAID_GROUP_ID:
            return
            
        # Process all new members (in case multiple users join at once)
        for new_member in message.new_chat_members:
            # Skip the bot itself
            if new_member.id == bot.get_me().id:
                continue
                
            # Get user's name - use first name, or username as fallback
            user_name = new_member.first_name or new_member.username or "New member"
            # Escape any special Markdown characters
            user_name = safe_markdown_escape(user_name)
            
            # Send welcome message
            welcome_message = (
                f"🎉 *Welcome to Prodigy Trading Academy, {user_name}!* 🎉\n\n"
                f"We're excited to have you join our trading community. "
                f"Here you'll find valuable insights, daily challenges, and a supportive network of fellow traders.\n\n"
                f"📊 *Daily challenges* are posted at 8:00 AM PH time\n"
                f"💡 *Expert guidance* from our community\n"
                f"📚 *Learning resources* to improve your skills\n\n"
                f"If you have any questions, our mentors are here to help!\n"
                f"Happy Trading! 📈"
            )
            
            # Send the welcome message directly to the group
            try:
                bot.send_message(
                    message.chat.id, 
                    welcome_message,
                    parse_mode="Markdown"
                )
                    
                logging.info(f"Sent welcome message for new member {new_member.id} ({user_name})")
            except ApiException as e:
                # If Markdown fails, try without formatting
                logging.error(f"Failed to send welcome with Markdown: {e}")
                bot.send_message(
                    message.chat.id, 
                    welcome_message.replace('*', '')
                )
    except Exception as e:
        logging.error(f"Error in welcome_new_members: {e}")

def safe_markdown_escape(text):
    """
    Comprehensive function to safely escape ANY text for Telegram Markdown
    Returns the escaped text or plain text if the input contains problematic characters
    """
    if text is None:
        return "None"
        
    try:
        # First try with standard escaping pattern
        special_chars = r'_*[]()~`>#+-=|{}.!'
        escaped_text = text
        for char in special_chars:
            escaped_text = escaped_text.replace(char, f"\\{char}")
        return escaped_text
    except Exception:
        # If anything fails, sanitize by removing problematic characters
        return ''.join(c for c in text if c.isalnum() or c.isspace() or c in '.-_')

# Handle Cancel Membership Confirmation
@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'cancel_membership')
def handle_cancel_confirmation(message):
    if message.chat.type != 'private':
        return  # Ignore if not in private chat
    chat_id = message.chat.id
    user_id = message.from_user.id
    confirmation = message.text

    # Check if user actually has an active membership
    if str(user_id) not in PAYMENT_DATA or not PAYMENT_DATA[str(user_id)].get('haspayed', False):
        bot.send_message(chat_id, "❌ You don't have an active membership to cancel.")
        PENDING_USERS.pop(user_id, None)
        delete_pending_user(user_id)
        return

    # Get membership details for better context
    plan = PAYMENT_DATA[str(user_id)].get('payment_plan', 'Unknown')
    due_date = PAYMENT_DATA[str(user_id)].get('due_date', 'Unknown')
    
    if confirmation == "Yes":
        # User confirmed cancellation
        PENDING_USERS[user_id]['status'] = 'membership_cancelled'
        save_pending_users()

        # Set cancellation flags in payment data
        PAYMENT_DATA[str(user_id)]['cancelled'] = True
        PAYMENT_DATA[str(user_id)]['reminder_sent'] = True  # Prevent future reminders
        PAYMENT_DATA[str(user_id)]['cancellation_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        save_payment_data()

        # Get user's information first
        try:
            user_info = bot.get_chat(user_id)
            username = user_info.username or f"User {user_id}"
            username = safe_markdown_escape(username)
        except Exception as e:
            username = f"User {user_id}"  # Fallback if we can't get username

        # Forward the cancellation request to admins with additional context
        for admin in ADMIN_IDS:
            bot.send_message(
                admin, 
                f"🚫 *MEMBERSHIP CANCELLATION*\n\n"
                f"👤 Username: @{username}\n"
                f"🆔 User ID: `{user_id}`\n"
                f"📅 Plan: {plan}\n"
                f"⏰ Due date: {due_date}\n"
                f"📝 Cancelled on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="Markdown"
            )

        # Provide better information to the user
        try:
            due_date_obj = datetime.strptime(due_date, '%Y-%m-%d %H:%M:%S')
            days_remaining = (due_date_obj - datetime.now()).days
            
            bot.send_message(
                chat_id, 
                f"✅ Your membership is cancelled. You will still have access until {due_date_obj.strftime('%Y-%m-%d')} "
                f"({days_remaining} days remaining), but will not be renewed.\n\n"
                f"Thank you for being with us! If you change your mind before expiration, use /start to reactivate.",
                parse_mode="Markdown"
            )
        except Exception as e:
            # Fallback if date parsing fails
            bot.send_message(chat_id, "✅ Your membership is cancelled. You will still have access until the next payment cycle, but will not be charged next month/year. Thank you for being with us!")
            logging.error(f"Error parsing due date during cancellation: {e}")
    
    elif confirmation == "No":
        # User did not confirm cancellation
        bot.send_message(chat_id, "❌ No changes have been made to your membership. You will continue with the current payment plan.")
    
    else:
        bot.send_message(chat_id, "❌ Invalid response. Please choose 'Yes' or 'No'.")
        return  # Don't remove from pending users so they can try again

    PENDING_USERS.pop(user_id, None)  # Remove from dictionary
    delete_pending_user(user_id)  # Remove from MongoDB
    

# Function to remind users 3 days before payment deadline
def escape_markdown(text):
    return re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', text)

def send_payment_reminder():
    """Payment reminder function using scheduled times for consistency."""
    logging.info("Payment reminder thread started")
    
    # Define specific times of day to send reminders (24-hour format in Philippines timezone)
    REMINDER_TIMES = ["09:00"]  # 9:00 AM
    
    # Track the last day we sent reminders to avoid duplicate sends
    last_reminder_dates = {time: None for time in REMINDER_TIMES}
    
    # Load reminder messages from MongoDB for persistence
    global reminder_messages
    reminder_messages = load_reminder_messages()
    
    while True:
        try:
            # Get current time in Philippines timezone
            now = datetime.now(pytz.timezone('Asia/Manila'))
            current_time = now.strftime('%H:%M')
            current_date = now.strftime('%Y-%m-%d')
            
            # Check if it's time to send reminders and we haven't sent them today at this time
            if current_time in REMINDER_TIMES and last_reminder_dates[current_time] != current_date:
                logging.info(f"Scheduled time {current_time} reached - sending payment reminders...")
                
                # Process all users for payment reminders
                for user_id_str, data in PAYMENT_DATA.items():
                    try:
                        user_id = int(user_id_str)
                        # Get the naive datetime first
                        naive_due_date = datetime.strptime(data['due_date'], '%Y-%m-%d %H:%M:%S')
                        
                        # Make it timezone-aware by adding Manila timezone
                        manila_tz = pytz.timezone('Asia/Manila')
                        due_date = manila_tz.localize(naive_due_date)
                        
                        username = data.get('username', None)
                        
                        if username:
                            username = escape_markdown(username)
                            user_display = f"@{username}"
                        else:
                            user_display = f"User {user_id}"

                        # Now both dates are timezone-aware, subtraction will work
                        days_until_due = (due_date - now).days
                        
                        # Check for users in grace period
                        if data.get('grace_period', False):
                            grace_end_date = datetime.strptime(data.get('grace_end_date'), '%Y-%m-%d %H:%M:%S')
                            grace_end_date = manila_tz.localize(grace_end_date)
                            
                            # If grace period has expired
                            if now >= grace_end_date:
                                # Delete previous reminders for this user
                                if user_id in reminder_messages:
                                    try:
                                        # Delete previous user reminder
                                        if 'user_msg_id' in reminder_messages[user_id]:
                                            bot.delete_message(user_id, reminder_messages[user_id]['user_msg_id'])
                                    except Exception as e:
                                        logging.error(f"Failed to delete previous user reminder: {e}")
                                    
                                    # Delete previous admin reminders
                                    for admin_id, msg_id in reminder_messages[user_id].get('admin_msg_ids', {}).items():
                                        try:
                                            bot.delete_message(admin_id, msg_id)
                                        except Exception as e:
                                            logging.error(f"Failed to delete previous admin reminder: {e}")
                                
                                # Notify admins about expired grace period
                                admin_messages = {}
                                for admin_id in ADMIN_IDS:
                                    markup = InlineKeyboardMarkup()
                                    markup.add(
                                        InlineKeyboardButton("✓ Kick Member", callback_data=f"kick_{user_id}"),
                                        InlineKeyboardButton("✗ Keep Member", callback_data=f"keep_{user_id}")
                                    )
                                    
                                    sent_msg = bot.send_message(
                                        admin_id,
                                        f"⚠️ *GRACE PERIOD EXPIRED*\n\n"
                                        f"{user_display}'s grace period has now expired. "
                                        f"Their membership expired on {due_date.strftime('%Y/%m/%d')}.\n\n"
                                        f"What would you like to do with this member?",
                                        parse_mode="Markdown",
                                        reply_markup=markup
                                    )
                                    admin_messages[admin_id] = sent_msg.message_id
                                
                                # Store new message IDs
                                reminder_messages[user_id] = {
                                    'admin_msg_ids': admin_messages
                                }
                                # Save to MongoDB
                                save_reminder_message(user_id, reminder_messages[user_id])
                                
                                # Remove grace period flag after notifying
                                PAYMENT_DATA[user_id_str]['grace_period'] = False
                                PAYMENT_DATA[user_id_str]['grace_end_date'] = None
                                save_payment_data()
                                
                                # Skip to next user since we've handled this case
                                continue
                        
                        # Send reminders for all users within 3 days of expiry
                        if 0 <= days_until_due <= 3 and data['haspayed'] and not data.get('cancelled', False):
                            # Debug information about the existing messages for this user
                            logging.info(f"Processing payment reminder for user {user_id} with {days_until_due} days until due")
                            if user_id in reminder_messages:
                                logging.info(f"Found existing reminder messages for user {user_id}: {reminder_messages[user_id]}")
                            else:
                                logging.info(f"No existing reminder messages for user {user_id}")

                            # Delete previous reminders for this user
                            if user_id in reminder_messages:
                                try:
                                    # Delete previous user reminder
                                    if 'user_msg_id' in reminder_messages[user_id]:
                                        msg_id = reminder_messages[user_id]['user_msg_id']
                                        logging.info(f"Attempting to delete user message {msg_id} for user {user_id}")
                                        try:
                                            bot.delete_message(user_id, msg_id)
                                            logging.info(f"Successfully deleted message {msg_id} for user {user_id}")
                                        except ApiException as e:
                                            error_msg = str(e)
                                            if "message to delete not found" in error_msg:
                                                logging.warning(f"Message {msg_id} for user {user_id} already deleted")
                                            elif "bot was blocked by the user" in error_msg:
                                                logging.warning(f"Cannot delete message for user {user_id} - user blocked the bot")
                                            else:
                                                logging.error(f"Failed to delete previous user reminder: {e}")
                                except Exception as e:
                                    logging.error(f"General error in user message deletion for {user_id}: {e}")
                                
                                # Delete previous admin reminders
                                for admin_id, msg_id in reminder_messages[user_id].get('admin_msg_ids', {}).items():
                                    try:
                                        logging.info(f"Attempting to delete admin message {msg_id} for admin {admin_id}")
                                        bot.delete_message(admin_id, msg_id)
                                        logging.info(f"Successfully deleted admin message {msg_id} for admin {admin_id}")
                                    except ApiException as e:
                                        error_msg = str(e)
                                        if "message to delete not found" in error_msg:
                                            logging.warning(f"Admin message {msg_id} for admin {admin_id} already deleted")
                                        else:
                                            logging.error(f"Failed to delete admin reminder for admin {admin_id}: {e}")
                                    except Exception as e:
                                        logging.error(f"General error in admin message deletion for admin {admin_id}: {e}")
                            
                            try:
                                # Send reminder to user
                                bot.send_chat_action(user_id, 'typing')
                                user_msg = bot.send_message(
                                    user_id, 
                                    f"⏳ Reminder: Your next payment is due in {days_until_due} days: {due_date.strftime('%Y/%m/%d %I:%M:%S %p')}."
                                )
                                logging.info(f"Sent payment reminder to user {user_id}, message ID: {user_msg.message_id}")
                                
                                # Send notification to admins
                                admin_messages = {}
                                for admin_id in ADMIN_IDS:
                                    admin_msg = bot.send_message(
                                        admin_id, 
                                        f"Admin Notice: {user_display} has an upcoming payment due in {days_until_due} days."
                                    )
                                    admin_messages[admin_id] = admin_msg.message_id
                                    logging.info(f"Sent admin notification to {admin_id}, message ID: {admin_msg.message_id}")
                                
                                # Store new message IDs with explicit logging
                                reminder_messages[user_id] = {
                                    'user_msg_id': user_msg.message_id,
                                    'admin_msg_ids': admin_messages
                                }
                                # Save to MongoDB
                                save_reminder_message(user_id, reminder_messages[user_id])
                                logging.info(f"Updated reminder_messages for user {user_id}: {reminder_messages[user_id]}")
                            
                            except ApiException as e:
                                logging.error(f"Failed to send payment reminder to user {user_id}: {e}")
                                
                                # For failed user notifications, still notify admins
                                admin_messages = {}
                                for admin_id in ADMIN_IDS:
                                    admin_msg = bot.send_message(
                                        admin_id, 
                                        f"⚠️ *Failed to send payment reminder*\n\n"
                                        f"Could not send payment reminder to {user_display}.\n"
                                        f"The user hasn't started a conversation with the bot or has blocked it.\n\n"
                                        f"Their payment is due in {days_until_due} days: {due_date.strftime('%Y/%m/%d')}\n\n"
                                        f"Please contact them manually.",
                                        parse_mode="Markdown"
                                    )
                                    admin_messages[admin_id] = admin_msg.message_id
                                
                                # Store only admin message IDs
                                reminder_messages[user_id] = {
                                    'admin_msg_ids': admin_messages
                                }
                                # Save to MongoDB
                                save_reminder_message(user_id, reminder_messages[user_id])
                        
                        # Check if membership has expired
                        elif due_date < now and (data['haspayed'] or data.get('admin_action_pending', False)) and not data.get('grace_period', False):
                            # Delete previous reminders for this user
                            if user_id in reminder_messages:
                                try:
                                    # Delete previous user reminder
                                    if 'user_msg_id' in reminder_messages[user_id]:
                                        bot.delete_message(user_id, reminder_messages[user_id]['user_msg_id'])
                                except Exception as e:
                                    logging.error(f"Failed to delete previous user reminder: {e}")
                                
                                # Delete previous admin reminders
                                for admin_id, msg_id in reminder_messages[user_id].get('admin_msg_ids', {}).items():
                                    try:
                                        bot.delete_message(admin_id, msg_id)
                                    except Exception as e:
                                        logging.error(f"Failed to delete previous admin reminder: {e}")

                                # Update payment data
                                PAYMENT_DATA[user_id_str]['haspayed'] = False
                                PAYMENT_DATA[user_id_str]['admin_action_pending'] = True
                                PAYMENT_DATA[user_id_str]['reminder_sent'] = False
                                save_payment_data()

                                # Calculate days since expiration
                                days_expired = (now - due_date).days
                                
                                # Send notification to admins with action buttons based on expiration duration
                                admin_messages = {}
                                for admin_id in ADMIN_IDS:
                                    markup = InlineKeyboardMarkup()
                                    
                                    # If expired more than 3 days, only offer kick or keep (no grace period)
                                    if days_expired > 3:
                                        markup.add(
                                            InlineKeyboardButton("❌ Kick Member", callback_data=f"kick_{user_id}"),
                                            InlineKeyboardButton("✓ Keep Member", callback_data=f"keep_{user_id}")
                                        )
                                        
                                        admin_msg = bot.send_message(
                                            admin_id, 
                                            f"⚠️ *LONG-EXPIRED MEMBERSHIP*\n\n"
                                            f"{user_display}'s membership has been expired for {days_expired} days.\n\n"
                                            f"What would you like to do with this member?",
                                            parse_mode="Markdown",
                                            reply_markup=markup
                                        )
                                    else:
                                        # For recently expired members, offer grace period
                                        markup.add(
                                            InlineKeyboardButton("⏳ Give 2 Days Grace", callback_data=f"grace_{user_id}"),
                                            InlineKeyboardButton("❌ Kick Member", callback_data=f"kick_{user_id}")
                                        )
                                        
                                        admin_msg = bot.send_message(
                                            admin_id, 
                                            f"⚠️ *MEMBERSHIP EXPIRED*\n\n"
                                            f"{user_display}'s membership has expired and has been marked as unpaid in the system.\n\n"
                                            f"What would you like to do with this member?",
                                            parse_mode="Markdown",
                                            reply_markup=markup
                                        )
                                        
                                    admin_messages[admin_id] = admin_msg.message_id
                            try:
                                # Send expiry notice to user
                                bot.send_chat_action(user_id, 'typing')
                                user_msg = bot.send_message(
                                    user_id, 
                                    "❌ Your membership has expired. Please renew your membership to continue accessing our services."
                                )
                                logging.info(f"Sent expiry notice to user {user_id}")
                                
                                # Update payment data - mark as pending admin action instead of just setting haspayed=False
                                PAYMENT_DATA[user_id_str]['haspayed'] = False
                                PAYMENT_DATA[user_id_str]['admin_action_pending'] = True
                                PAYMENT_DATA[user_id_str]['reminder_sent'] = False
                                save_payment_data()
                                
                                # Send notification to admins with action buttons
                                admin_messages = {}
                                for admin_id in ADMIN_IDS:
                                    markup = InlineKeyboardMarkup()
                                    markup.add(
                                        InlineKeyboardButton("⏳ Give 2 Days Grace", callback_data=f"grace_{user_id}"),
                                        InlineKeyboardButton("❌ Kick Member", callback_data=f"kick_{user_id}")
                                    )
                                    
                                    admin_msg = bot.send_message(
                                        admin_id, 
                                        f"⚠️ *MEMBERSHIP EXPIRED*\n\n"
                                        f"{user_display}'s membership has expired and has been marked as unpaid in the system.\n\n"
                                        f"What would you like to do with this member?",
                                        parse_mode="Markdown",
                                        reply_markup=markup
                                    )
                                    admin_messages[admin_id] = admin_msg.message_id
                                
                                # Store new message IDs
                                reminder_messages[user_id] = {
                                    'user_msg_id': user_msg.message_id,
                                    'admin_msg_ids': admin_messages
                                }
                                # Save to MongoDB
                                save_reminder_message(user_id, reminder_messages[user_id])
                            
                            except ApiException as e:
                                logging.error(f"Failed to send expiry notice to user {user_id}: {e}")
                                PAYMENT_DATA[user_id_str]['haspayed'] = False
                                PAYMENT_DATA[user_id_str]['reminder_sent'] = False
                                save_payment_data()
                                
                                # Still notify admins with action buttons
                                admin_messages = {}
                                for admin_id in ADMIN_IDS:
                                    markup = InlineKeyboardMarkup()
                                    markup.add(
                                        InlineKeyboardButton("⏳ Give 2 Days Grace", callback_data=f"grace_{user_id}"),
                                        InlineKeyboardButton("❌ Kick Member", callback_data=f"kick_{user_id}")
                                    )
                                    
                                    admin_msg = bot.send_message(
                                        admin_id, 
                                        f"⚠️ *FAILED TO NOTIFY USER & MEMBERSHIP EXPIRED*\n\n"
                                        f"Could not notify {user_display} about their expired membership.\n"
                                        f"The user hasn't started a conversation with the bot or has blocked it.\n\n"
                                        f"Their membership has been marked as expired in the system.\n\n"
                                        f"What would you like to do with this member?",
                                        parse_mode="Markdown",
                                        reply_markup=markup
                                    )
                                    admin_messages[admin_id] = admin_msg.message_id
                                
                                # Store only admin message IDs
                                reminder_messages[user_id] = {
                                    'admin_msg_ids': admin_messages
                                }
                                # Save to MongoDB
                                save_reminder_message(user_id, reminder_messages[user_id])
                                    
                    except Exception as e:
                        logging.error(f"Error processing payment reminder for user {user_id_str}: {e}")
                        for admin_id in ADMIN_IDS:
                            bot.send_message(admin_id, f"⚠️ Error processing payment reminder for {user_id_str}: {str(e)}")
                
                # Record that we've sent reminders for this scheduled time today
                last_reminder_dates[current_time] = current_date
                logging.info(f"Completed sending payment reminders at scheduled time {current_time}")
            
            # Calculate the time to sleep until the start of the next minute
            now = datetime.now(pytz.timezone('Asia/Manila'))
            sleep_time = 60 - now.second - now.microsecond / 1_000_000
            time.sleep(sleep_time)
            
        except Exception as e:
            logging.error(f"Error in payment reminder main loop: {e}")
            time.sleep(60)  # Wait a minute on error before trying again

# Handle admin clicking "Give Grace Period" button
@bot.callback_query_handler(func=lambda call: call.data.startswith("grace_"))
def handle_grace_period(call):
    """Handle admin clicking the 'Give 2 Days Grace' button"""
    admin_id = call.from_user.id
    
    # Verify the user is an admin
    if admin_id not in ADMIN_IDS and admin_id != CREATOR_ID:
        bot.answer_callback_query(call.id, "❌ You are not authorized to perform this action.", show_alert=True)
        return
    
    # Extract user ID
    user_id = int(call.data.split("_")[1])
    user_id_str = str(user_id)
    
    try:
        # Get username for display
        if user_id_str in PAYMENT_DATA:
            username = PAYMENT_DATA[user_id_str].get('username', None)
        else:
            try:
                user_info = bot.get_chat(user_id)
                username = user_info.username
            except:
                username = None
                
        user_display = f"@{username}" if username else f"User {user_id}"
        
        # Calculate grace period end date (2 days from now)
        now = datetime.now(pytz.timezone('Asia/Manila'))
        grace_end_date = now + timedelta(days=2)
        
        # Update payment data to add grace period
        if user_id_str in PAYMENT_DATA:
            PAYMENT_DATA[user_id_str]['grace_period'] = True
            PAYMENT_DATA[user_id_str]['grace_end_date'] = grace_end_date.strftime('%Y-%m-%d %H:%M:%S')
            PAYMENT_DATA[user_id_str]['haspayed'] = True  # Temporarily mark as paid during grace period
            PAYMENT_DATA[user_id_str]['admin_action_pending'] = False  # Clear the pending flag
            save_payment_data()
        
        # Notify the user about the grace period
        try:
            bot.send_message(
                user_id,
                "⏳ *Grace Period Granted*\n\n"
                "You have been given a 2-day grace period to renew your membership. "
                f"Please renew before {grace_end_date.strftime('%Y-%m-%d %I:%M:%S %p')} to avoid being removed from the group.",
                parse_mode="Markdown"
            )
            user_notified = True
        except:
            user_notified = False
        
        # Update the button to show action was taken
        bot.edit_message_text(
            f"✅ *ACTION TAKEN: GRACE PERIOD*\n\n"
            f"{user_display} has been given a 2-day grace period until {grace_end_date.strftime('%Y-%m-%d')}.\n"
            f"User notification {'sent' if user_notified else 'FAILED'}.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Notify ALL admins about this action using direct regex escaping
        admin_username = call.from_user.username or f"Admin {admin_id}"
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} gave {user_display} a 2-day grace period until {grace_end_date.strftime('%Y-%m-%d')}.", parse_mode="Markdown")
        
        bot.answer_callback_query(call.id, f"Grace period granted to {user_display} until {grace_end_date.strftime('%Y-%m-%d')}")
        
    except Exception as e:
        logging.error(f"Error in handle_grace_period: {e}")
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

# Handle admin clicking "Kick Member" button
@bot.callback_query_handler(func=lambda call: call.data.startswith("kick_"))
def handle_kick_member(call):
    """Handle admin clicking the 'Kick Member' button"""
    admin_id = call.from_user.id
    
    # Verify the user is an admin
    if admin_id not in ADMIN_IDS and admin_id != CREATOR_ID:
        bot.answer_callback_query(call.id, "❌ You are not authorized to perform this action.", show_alert=True)
        return
    
    # Extract user ID to kick
    user_id = int(call.data.split("_")[1])
    user_id_str = str(user_id)
    
    try:
        # Get username for display
        if user_id_str in PAYMENT_DATA:
            username = PAYMENT_DATA[user_id_str].get('username', None)
        else:
            try:
                user_info = bot.get_chat(user_id)
                username = user_info.username
            except:
                username = None
                
        user_display = f"@{username}" if username else f"User {user_id}"
        
        # First notify the user that they're being removed
        try:
            bot.send_message(
                user_id,
                "❌ *Your membership has expired*\n\n"
                "You are being removed from the group because your membership has expired. "
                "To rejoin, please renew your membership using the /start command.",
                parse_mode="Markdown"
            )
            user_notified = True
        except:
            user_notified = False
        
        # Try to kick the user from the group
        try:
            bot.ban_chat_member(PAID_GROUP_ID, user_id)
            bot.unban_chat_member(PAID_GROUP_ID, user_id)  # Immediately unban so they can rejoin later
            kick_successful = True
        except Exception as e:
            logging.error(f"Failed to kick user {user_id}: {e}")
            kick_successful = False
        
        # Update the button to show action was taken
        bot.edit_message_text(
            f"{'✅' if kick_successful else '❌'} *ACTION TAKEN: KICK MEMBER*\n\n"
            f"{user_display} has {'been removed from' if kick_successful else 'FAILED to be removed from'} the group.\n"
            f"User notification {'sent' if user_notified else 'FAILED'}.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )

        # In handle_kick_member function - after successful kick:
        if kick_successful:
            PAYMENT_DATA[user_id_str]['admin_action_pending'] = False
            save_payment_data()
        
        # Notify ALL admins about this action using direct regex escaping
        admin_username = call.from_user.username or f"Admin {admin_id}"
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} kicked {user_display} from the group.", parse_mode="Markdown")
        
        bot.answer_callback_query(
            call.id, 
            f"User {user_display} has {'been kicked' if kick_successful else 'FAILED to be kicked'} from the group."
        )
        
    except Exception as e:
        logging.error(f"Error in handle_kick_member: {e}")
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

# Handle admin decision to keep member after grace period expires
@bot.callback_query_handler(func=lambda call: call.data.startswith("keep_"))
def handle_keep_member(call):
    """Handle admin clicking 'Keep Member' after grace period expiry"""
    admin_id = call.from_user.id
    
    # Verify the user is an admin
    if admin_id not in ADMIN_IDS and admin_id != CREATOR_ID:
        bot.answer_callback_query(call.id, "❌ You are not authorized to perform this action.", show_alert=True)
        return
    
    # Extract user ID
    user_id = int(call.data.split("_")[1])
    user_id_str = str(user_id)

    PAYMENT_DATA[user_id_str]['admin_action_pending'] = False
    save_payment_data()
    
    try:
        # Get username for display
        if user_id_str in PAYMENT_DATA:
            username = PAYMENT_DATA[user_id_str].get('username', None)
        else:
            try:
                user_info = bot.get_chat(user_id)
                username = user_info.username
            except:
                username = None
                
        user_display = f"@{username}" if username else f"User {user_id}"
        
        # Update the button to show action was taken
        bot.edit_message_text(
            f"✅ *ACTION TAKEN: KEPT MEMBER*\n\n"
            f"{user_display} has been allowed to remain in the group despite expired membership.\n"
            f"Their account is still marked as unpaid in the system.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Notify ALL admins about this action using direct regex escaping
        admin_username = call.from_user.username or f"Admin {admin_id}"
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} allowed {user_display} to remain in the group despite expired membership.", parse_mode="Markdown")
        
        bot.answer_callback_query(call.id, f"Decision recorded: {user_display} will remain in the group")
        
    except Exception as e:
        logging.error(f"Error in handle_keep_member: {e}")
        bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)


def delete_all_reminders():
    """Function to delete all payment reminder messages at midnight."""
    logging.info("Midnight cleanup: Deleting all payment reminder messages")
    
    global reminder_messages
    
    # Make a copy of the keys to avoid modifying dictionary during iteration
    user_ids = list(reminder_messages.keys())
    
    deleted_count = 0
    failed_count = 0
    
    for user_id in user_ids:
        try:
            # Delete user message if it exists
            if 'user_msg_id' in reminder_messages[user_id]:
                try:
                    bot.delete_message(user_id, reminder_messages[user_id]['user_msg_id'])
                    logging.info(f"Midnight cleanup: Deleted user message for {user_id}")
                    deleted_count += 1
                except Exception as e:
                    logging.error(f"Midnight cleanup: Failed to delete user message for {user_id}: {e}")
                    failed_count += 1
            
            # Delete admin messages if they exist
            for admin_id, msg_id in reminder_messages[user_id].get('admin_msg_ids', {}).items():
                try:
                    bot.delete_message(admin_id, msg_id)
                    logging.info(f"Midnight cleanup: Deleted admin message for admin {admin_id}")
                    deleted_count += 1
                except Exception as e:
                    logging.error(f"Midnight cleanup: Failed to delete admin message for admin {admin_id}: {e}")
                    failed_count += 1
                    
            # Delete from MongoDB
            delete_reminder_message(user_id)
            
            # Check if this user's membership has expired
            user_id_str = str(user_id)
            if user_id_str in PAYMENT_DATA:
                due_date = datetime.strptime(PAYMENT_DATA[user_id_str]['due_date'], '%Y-%m-%d %H:%M:%S')
                now = datetime.now()
                if due_date < now and PAYMENT_DATA[user_id_str].get('haspayed', False):
                    # Reset admin_action_pending flag to ensure fresh admin notifications will be sent
                    # at the next scheduled reminder time
                    PAYMENT_DATA[user_id_str]['admin_action_pending'] = True
                    logging.info(f"Midnight cleanup: Marked user {user_id} for admin notification")
            
        except Exception as e:
            logging.error(f"Midnight cleanup: Error processing user {user_id}: {e}")
            failed_count += 1
    
    # Save updates to PAYMENT_DATA
    save_payment_data()
    
    # Clear the reminder_messages dictionary
    reminder_messages.clear()
    
    # Also clear the entire MongoDB collection for a fresh start
    try:
        reminder_messages_collection.delete_many({})
        logging.info("Cleared all reminder messages from MongoDB")
    except Exception as e:
        logging.error(f"Error clearing reminder messages from MongoDB: {e}")
        
    logging.info(f"Midnight cleanup complete: {deleted_count} messages deleted, {failed_count} failures")

def midnight_cleanup_thread():
    """Thread to run at midnight and delete all reminder messages."""
    logging.info("Midnight cleanup thread started")
    
    # Track the last day we performed cleanup
    last_cleanup_date = None
    
    while True:
        try:
            # Get current time in Philippines timezone
            now = datetime.now(pytz.timezone('Asia/Manila'))
            current_time = now.strftime('%H:%M')
            current_date = now.strftime('%Y-%m-%d')
            
            # Check if it's midnight and we haven't cleaned up today
            if current_time == '00:00' and last_cleanup_date != current_date:
                logging.info("Midnight reached - cleaning up all reminder messages")
                delete_all_reminders()
                last_cleanup_date = current_date
            
            # Calculate the time to sleep until the start of the next minute
            sleep_time = 60 - now.second - now.microsecond / 1_000_000
            time.sleep(sleep_time)
            
        except Exception as e:
            logging.error(f"Error in midnight cleanup thread: {e}")
            time.sleep(60)  # Wait a minute on error before trying again

@bot.message_handler(commands=['admin_dashboard'])
def admin_dashboard(message):
    """Send link to the web-based admin dashboard"""
    # Check if user is authorized (admin or creator)
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != CREATOR_ID:
        bot.send_message(message.chat.id, "❌ You are not authorized to use this command.")
        return

    # Get username for logging purposes
    username = message.from_user.username or f"User {message.from_user.id}"
    
    # Send the dashboard link with a simple button
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔐 Open Admin Dashboard", url="https://ptabot.onrender.com/dashboard"))
    
    bot.send_message(
        message.chat.id,
        "Click the button below to access the admin dashboard:",
        reply_markup=markup
    )
    
    # Log the access
    logging.info(f"Admin dashboard accessed by {username} ({message.from_user.id})")

@bot.message_handler(commands=['ping'])
def handle_ping_command(message):
    if message.chat.type in ['group', 'supergroup']:
        bot.send_message(message.chat.id, "🏓 Pong!")
    else:
        bot.send_message(message.chat.id, "❌ This command can only be used in group chats.")

# Define the scheduled times and corresponding GIF URLs
SCHEDULED_TIMES = {
    # Asia Open and Close
    "07:30": "gifs/AsiaOpen.mp4",
    "15:59": "gifs/AsiaClose.mp4",
    # London Open and Close
    "16:00": "gifs/LondonOpen.mp4",
    "00:30": "gifs/LondonClose.mp4",
    # New York Open and Close
    "21:30": "gifs/nyamopen.mp4",
    "23:00": "gifs/nyamclose.mp4",
    # New York Afternoon Open and Close
    "01:30": "gifs/nypmopen.mp4",
    "04:00": "gifs/nypmclose.mp4"
}

def send_scheduled_gifs():
    """Send scheduled GIFs to the group at specific times, deleting previous GIFs before sending new ones"""
    last_message_id = get_last_gif_message()
    logging.info(f"Starting GIF scheduler, last message ID: {last_message_id}")
    
    while True:
        now = datetime.now(pytz.timezone('Asia/Manila'))
        current_time = now.strftime('%H:%M')
        
        # Only proceed if it's a weekday (Monday=0, Sunday=6)
        is_weekday = now.weekday() < 5  # 0-4 are Monday to Friday
        
        if current_time in SCHEDULED_TIMES and is_weekday:
            # First, delete the previous GIF if available
            if last_message_id:
                try:
                    bot.delete_message(PAID_GROUP_ID, last_message_id)
                    logging.info(f"Deleted previous GIF message ID: {last_message_id}")
                except ApiException as e:
                    if "message to delete not found" in str(e):
                        logging.warning(f"Previous GIF message {last_message_id} already deleted")
                    elif "bot was blocked by the user" in str(e):
                        logging.warning("Cannot delete previous GIF - bot was blocked")
                    else:
                        logging.error(f"Failed to delete previous GIF: {e}")
                except Exception as e:
                    logging.error(f"General error deleting previous GIF: {e}")
            
            # Now send the new GIF
            file_path_or_url = SCHEDULED_TIMES[current_time]
            try:
                message = None
                if file_path_or_url.startswith('https'):
                    message = bot.send_animation(PAID_GROUP_ID, file_path_or_url)
                else:
                    with open(file_path_or_url, 'rb') as file:
                        if file_path_or_url.endswith('.gif'):
                            message = bot.send_animation(PAID_GROUP_ID, file)
                        elif file_path_or_url.endswith('.mp4'):
                            message = bot.send_video(PAID_GROUP_ID, file, supports_streaming=True)
                
                if message:
                    # Store the new message ID for future deletion
                    last_message_id = message.message_id
                    save_last_gif_message(last_message_id)
                    
                logging.info(f"Sent scheduled file at {current_time} Philippine time. New message ID: {last_message_id}")
            except Exception as e:
                logging.error(f"Failed to send scheduled file at {current_time}: {e}")
        elif current_time in SCHEDULED_TIMES and not is_weekday:
            logging.info(f"Skipped scheduled file at {current_time}: Weekend.")
        
        # Calculate the time to sleep until the start of the next minute
        now = datetime.now(pytz.timezone('Asia/Manila'))
        sleep_time = 60 - now.second - now.microsecond / 1_000_000
        time.sleep(sleep_time)

CREATOR_USERNAME = "FujiiiiiPTA" 

@bot.message_handler(commands=['tip'])
def handle_tip_command(message):
    if message.chat.type in ['group', 'supergroup']:
        tip_message = (
            f"❤️ Love the bot? Give a tip to the creator! @{CREATOR_USERNAME}!\n\n"
            "💸 *Crypto Payments*:\n\n"
            "*USDT (TRC20)*: `TV9K3DwWLufYU5yeyXZYCtB3QNX1s983wD`\n\n"
            "*Bitcoin*: `3H7uF4H29cqDiUGNd7M9tpWashEfN8a3wP`\n\n"
            "📱 *GCash*:\n"
            "GCash Number: `09763624531` (J. M.)"
        )
        bot.send_message(message.chat.id, tip_message, parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, "❌ This command can only be used in group chats.")

@bot.message_handler(commands=['dashboard', 'status'])
def show_user_dashboard(message):
    """Display the user's membership dashboard with status and details"""
    chat_id = message.chat.id
    user_id = str(message.from_user.id)
    
    # Check if this is a private chat
    if message.chat.type != 'private':
        bot.send_message(chat_id, "🔒 Please use this command in a private message with the bot.")
        return
        
    # Check if the user has membership data
    if user_id in PAYMENT_DATA:
        data = PAYMENT_DATA[user_id]
        username = message.from_user.username or "No Username"
        
        # Calculate days remaining until expiration
        try:
            due_date = datetime.strptime(data['due_date'], '%Y-%m-%d %H:%M:%S')
            current_date = datetime.now()
            days_remaining = (due_date - current_date).days
            hours_remaining = int((due_date - current_date).seconds / 3600)
            
            # Check if membership is cancelled first
            if data.get('cancelled', False):
                status_icon = "🚫"
                status_text = "Cancelled"
            # If not cancelled, format status based on days remaining
            elif days_remaining > 7:
                status_icon = "✅"
                status_text = "Active"
            elif days_remaining > 0:
                status_icon = "⚠️"
                status_text = "Expiring Soon"
            else:
                status_icon = "❌"
                status_text = "Expired"
                
            # Check if they're an OG member
            is_og = "Yes ⭐" if str(user_id) in CONFIRMED_OLD_MEMBERS else "No"
            
            # Create and send the dashboard message
            dashboard_message = (
                f"📊 *MEMBER DASHBOARD*\n\n"
                f"👤 *Username:* @{username}\n"
                f"🆔 *Member ID:* `{user_id}`\n"
                f"📅 *Plan:* {data['payment_plan']}\n"
                f"💳 *Payment Method:* {data['payment_mode']}\n"
                f"🏆 *OG Member:* {is_og}\n\n"
                f"📊 *Status:* {status_icon} {status_text}\n"
                f"⏰ *Expiration Date:* {due_date.strftime('%Y-%m-%d')}\n"
                f"⏳ *Time Remaining:* {days_remaining} days, {hours_remaining} hours\n\n"
            )
            
            # Add renewal instructions if expiring soon (and not cancelled)
            if days_remaining < 7 and days_remaining >= 0 and not data.get('cancelled', False):
                dashboard_message += (
                    "⚠️ *Your membership expires soon!*\n"
                    "Use /start and select 'Renew Membership' to continue access.\n\n"
                )
            # Add special message for cancelled memberships
            elif data.get('cancelled', False):
                dashboard_message += (
                    "🚫 *Your membership has been cancelled*\n"
                    f"You will still have access until {due_date.strftime('%Y-%m-%d')}.\n"
                    "To reactivate before expiration, use /start and select 'Renew Membership'.\n\n"
                )
                
            # Add help information
            dashboard_message += (
                "📋 *Need Help?*\n"
                "Use /start for all available options."
            )
            
            bot.send_message(chat_id, dashboard_message, parse_mode="Markdown")
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error retrieving dashboard: {str(e)}")
            logging.error(f"Dashboard error for user {user_id}: {str(e)}")
    else:
        # User doesn't have membership data
        bot.send_message(
            chat_id, 
            "❌ *No active membership found*\n\nYou don't appear to have an active membership. Use /start to enroll in Prodigy Trading Academy.",
            parse_mode="Markdown"
        )

# Command to post a new changelog entry (creator only)
@bot.message_handler(commands=['post_changelog'])
def post_changelog_command(message):
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
        
    # Ask for changelog type
    markup = ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add(KeyboardButton("Admin Changelog"), KeyboardButton("User Changelog"))
    bot.send_message(message.chat.id, "Select the changelog type:", reply_markup=markup)
    PENDING_USERS[message.chat.id] = {'status': 'selecting_changelog_type'}
    save_pending_users()

# Handle changelog type selection
@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'selecting_changelog_type')
def select_changelog_type(message):
    if message.from_user.id != CREATOR_ID:
        return
        
    changelog_type = message.text.lower()
    chat_id = message.chat.id
    
    if "admin" in changelog_type:
        PENDING_USERS[chat_id]['changelog_type'] = 'admin'
        save_pending_users()
        bot.send_message(chat_id, "📝 Please enter the admin changelog entry with the following format:\n\n*Version*\nChangelog details")
    elif "user" in changelog_type:
        PENDING_USERS[chat_id]['changelog_type'] = 'user'
        save_pending_users()
        bot.send_message(chat_id, "📝 Please enter the user changelog entry with the following format:\n\n*Version*\nChangelog details")
    else:
        bot.send_message(chat_id, "❌ Invalid option. Please select either 'Admin Changelog' or 'User Changelog'.")
        return
    
    PENDING_USERS[chat_id]['status'] = 'entering_changelog'
    save_pending_users()

def escape_markdown_v2(text):
    """
    Escape special characters for Markdown V2 format in Telegram
    This handles all special characters that need escaping
    """
    special_chars = r'_*[]()~`>#+-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text

# Handle changelog entry
@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'entering_changelog')
def enter_changelog(message):
    if message.from_user.id != CREATOR_ID:
        return
        
    chat_id = message.chat.id
    changelog_text = message.text
    changelog_type = PENDING_USERS[chat_id]['changelog_type']
    save_pending_users()
    
    # Add timestamp to the changelog
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Store original text in the changelog
    changelog_entry = {
        "timestamp": timestamp,
        "content": changelog_text
    }
    
    CHANGELOGS[changelog_type].append(changelog_entry)
    save_changelogs(CHANGELOGS)
    
    # Confirmation message
    bot.send_message(chat_id, f"✅ {changelog_type.capitalize()} changelog added successfully!")
    
    # For user changelogs, broadcast to all registered users
    if changelog_type == 'admin':
        # Send to admins only - with properly escaped markdown
        for admin_id in ADMIN_IDS:
            try:
                bot.send_chat_action(admin_id, 'typing')  # Check if user can be messaged
                # Try with parse_mode=None first if markdown fails
                try:
                    bot.send_message(
                        admin_id,
                        f"📢 *NEW ADMIN CHANGELOG*\n\n{changelog_text}\n\n🕒 Posted: {timestamp}",
                        parse_mode="Markdown"
                    )
                except Exception:
                    # If Markdown parsing fails, send without formatting
                    bot.send_message(
                        admin_id,
                        f"📢 NEW ADMIN CHANGELOG\n\n{changelog_text}\n\n🕒 Posted: {timestamp}",
                        parse_mode=None
                    )
                    logging.info(f"Sent admin changelog to {admin_id} without markdown formatting")
            except Exception as e:
                logging.error(f"Failed to send admin changelog to {admin_id}: {e}")
                bot.send_message(chat_id, f"⚠️ Warning: Could not send changelog to admin {admin_id}")
    else:
        # For user changelogs - add to pending notifications and broadcast
        # Track successful and failed deliveries
        success_count = 0
        failed_count = 0
        
        # Add a "last_changelog" field to track users who haven't seen latest changelog
        changelog_entry["seen_by"] = []
        
        for user_id_str in PAYMENT_DATA:
            if not PAYMENT_DATA[user_id_str]['haspayed']:
                continue
                
            try:
                user_id = int(user_id_str)
                bot.send_chat_action(user_id, 'typing')  # Check if user can be messaged
                
                # Try with parse_mode=Markdown first, if it fails, try without formatting
                try:
                    bot.send_message(
                        user_id,
                        f"📢 *NEW UPDATE*\n\n{changelog_text}\n\n🕒 Posted: {timestamp}",
                        parse_mode="Markdown"
                    )
                except Exception:
                    bot.send_message(
                        user_id,
                        f"📢 NEW UPDATE\n\n{changelog_text}\n\n🕒 Posted: {timestamp}",
                        parse_mode=None
                    )
                    
                changelog_entry["seen_by"].append(user_id_str)
                success_count += 1
            except Exception as e:
                logging.error(f"Failed to send user changelog to {user_id_str}: {e}")
                failed_count += 1
        
        # Show delivery stats
        bot.send_message(
            chat_id, 
            f"📊 Changelog Delivery Stats:\n✅ Successfully sent: {success_count}\n❌ Failed: {failed_count}"
        )
        
        # Option to also post in group chat for maximum visibility
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Yes", callback_data=f"post_group_changelog_{len(CHANGELOGS[changelog_type])-1}"))
        markup.add(InlineKeyboardButton("No", callback_data="cancel_group_post"))
        
        bot.send_message(
            chat_id,
            "Would you like to also post this changelog in the main group chat?",
            reply_markup=markup
        )
    # Remove user from pending users after successfully processing the changelog
    PENDING_USERS.pop(chat_id, None)  # Remove from dictionary
    delete_pending_user(chat_id)  # Remove from MongoDB

# View changelogs command
@bot.message_handler(commands=['changelogs'])
def view_changelogs(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Load the appropriate changelogs based on user role
    is_admin = user_id in ADMIN_IDS
    is_creator = user_id == CREATOR_ID
    
    if is_admin or is_creator:
        # Admins and creator can see both changelogs
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Admin Changelogs", callback_data='view_admin_changelogs'))
        markup.add(InlineKeyboardButton("User Changelogs", callback_data='view_user_changelogs'))
        bot.send_message(chat_id, "Select which changelogs to view:", reply_markup=markup)
    else:
        # Regular users can only see user changelogs
        send_user_changelogs(chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("post_group_changelog_"))
def post_changelog_to_group(call):
    if call.from_user.id != CREATOR_ID:
        bot.answer_callback_query(call.id, "❌ Only the creator can post changelogs to the group.")
        return
        
    changelog_index = int(call.data.split("_")[3])
    changelog = CHANGELOGS["user"][changelog_index]
    
    try:
        # Send to the announcement topic if configured, otherwise to main group
        if ANNOUNCEMENT_TOPIC_ID:
            bot.send_message(
                PAID_GROUP_ID,
                f"📢 *IMPORTANT UPDATE*\n\n{changelog['content']}\n\n🕒 Posted: {changelog['timestamp']}",
                parse_mode="Markdown",
                message_thread_id=ANNOUNCEMENT_TOPIC_ID
            )
            bot.answer_callback_query(call.id, f"✅ Posted to announcements topic (ID: {ANNOUNCEMENT_TOPIC_ID}) successfully!")
            bot.edit_message_text(
                f"Changelog posted to announcements topic (ID: {ANNOUNCEMENT_TOPIC_ID}) successfully!",
                call.message.chat.id,
                call.message.message_id
            )
            logging.info(f"Posted changelog to announcement topic {ANNOUNCEMENT_TOPIC_ID}")
        else:
            # Original behavior - post to main group
            bot.send_message(
                PAID_GROUP_ID,
                f"📢 *IMPORTANT UPDATE*\n\n{changelog['content']}\n\n🕒 Posted: {changelog['timestamp']}",
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id, "✅ Posted to group successfully!")
            bot.edit_message_text(
                "Changelog posted to main group successfully!",
                call.message.chat.id,
                call.message.message_id
            )
            logging.info("Posted changelog to main group (no topic ID set)")
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Failed to post to group.")
        bot.send_message(call.message.chat.id, f"Error: {str(e)}")
        logging.error(f"Error posting changelog: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "cancel_group_post")
def cancel_group_post(call):
    bot.answer_callback_query(call.id, "❌ Cancelled posting to group.")
    bot.edit_message_text(
        "Group posting cancelled.",
        call.message.chat.id,
        call.message.message_id
    )

# Callback handler for changelog viewing
@bot.callback_query_handler(func=lambda call: call.data.startswith('view_'))
def handle_changelog_view(call):
    chat_id = call.message.chat.id
    
    if call.data == 'view_admin_changelogs':
        if call.from_user.id in ADMIN_IDS or call.from_user.id == CREATOR_ID:
            send_admin_changelogs(chat_id)
        else:
            bot.answer_callback_query(call.id, "❌ You don't have permission to view admin changelogs.")
    elif call.data == 'view_user_changelogs':
        send_user_changelogs(chat_id)
    
    bot.answer_callback_query(call.id)

def send_admin_changelogs(chat_id):
    if not CHANGELOGS['admin']:
        bot.send_message(chat_id, "No admin changelogs available yet.")
        return
    
    # Get the latest 5 changelogs
    recent_logs = CHANGELOGS['admin'][-5:]
    
    # First try plain text (no markdown) to be safe
    plain_message = "📋 ADMIN CHANGELOGS\n\n"
    for log in recent_logs:
        plain_message += f"🕒 {log['timestamp']}\n{log['content']}\n\n"
    
    bot.send_message(chat_id, plain_message)

def send_user_changelogs(chat_id):
    if not CHANGELOGS['user']:
        bot.send_message(chat_id, "No changelogs available yet.")
        return
    
    # Get the latest 5 changelogs
    recent_logs = CHANGELOGS['user'][-5:]
    
    # Send as plain text to avoid formatting issues
    plain_message = "📋 RECENT UPDATES\n\n"
    for log in recent_logs:
        plain_message += f"🕒 {log['timestamp']}\n{log['content']}\n\n"
    
    bot.send_message(chat_id, plain_message)

@bot.message_handler(commands=['setannouncementtopic'])
def set_announcement_topic(message):
    """Set or change the topic ID for announcements"""
    global ANNOUNCEMENT_TOPIC_ID
    
    # Only allow the creator to use this command
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
    
    # Extract topic ID from command arguments
    args = message.text.split()
    
    # Show current setting if no arguments provided
    if len(args) == 1:
        current_topic = ANNOUNCEMENT_TOPIC_ID if ANNOUNCEMENT_TOPIC_ID else "Not set (using main group)"
        bot.reply_to(message, f"Current announcement topic ID: `{current_topic}`\n\nTo change, use: `/setannouncementtopic ID`", parse_mode="Markdown")
        return
        
    try:
        # Handle "clear" or "reset" to remove topic ID
        if args[1].lower() in ["clear", "reset", "none"]:
            ANNOUNCEMENT_TOPIC_ID = None
            # Save to database
            BOT_SETTINGS['announcement_topic_id'] = None
            save_settings(BOT_SETTINGS)
            bot.reply_to(message, "✅ Announcements will now be sent to the main group chat.")
            return
            
        # Try to parse as integer
        new_topic_id = int(args[1])
        ANNOUNCEMENT_TOPIC_ID = new_topic_id
        
        # Save to database
        BOT_SETTINGS['announcement_topic_id'] = new_topic_id
        save_settings(BOT_SETTINGS)
        
        bot.reply_to(message, f"✅ Announcements will now be sent to topic ID: `{new_topic_id}`\nThis setting has been saved to the database.", parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid topic ID. Please provide a numeric ID or 'clear' to reset.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error setting topic ID: {str(e)}")

# Modify the post_changelog_to_group function to use the announcement topic ID
@bot.callback_query_handler(func=lambda call: call.data.startswith("post_group_changelog_"))
def post_changelog_to_group(call):
    if call.from_user.id != CREATOR_ID:
        bot.answer_callback_query(call.id, "❌ Only the creator can post changelogs to the group.")
        return
        
    changelog_index = int(call.data.split("_")[3])
    changelog = CHANGELOGS["user"][changelog_index]
    
    try:
        # Send to the announcement topic if configured, otherwise to main group
        if ANNOUNCEMENT_TOPIC_ID:
            bot.send_message(
                PAID_GROUP_ID,
                f"📢 *IMPORTANT UPDATE*\n\n{changelog['content']}\n\n🕒 Posted: {changelog['timestamp']}",
                parse_mode="Markdown",
                message_thread_id=ANNOUNCEMENT_TOPIC_ID
            )
            bot.answer_callback_query(call.id, "✅ Posted to announcements topic successfully!")
            bot.edit_message_text(
                f"Changelog posted to announcements topic (ID: {ANNOUNCEMENT_TOPIC_ID}) successfully!",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            # Original behavior - post to main group
            bot.send_message(
                PAID_GROUP_ID,
                f"📢 *IMPORTANT UPDATE*\n\n{changelog['content']}\n\n🕒 Posted: {changelog['timestamp']}",
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id, "✅ Posted to group successfully!")
            bot.edit_message_text(
                "Changelog posted to group successfully!",
                call.message.chat.id,
                call.message.message_id
            )
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Failed to post to group.")
        bot.send_message(call.message.chat.id, f"Error: {str(e)}")


@bot.message_handler(commands=['check'])
def check_mongodb_connection(message):
    # Restrict access to Creator only
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
    
    try:
        # Test connection with ping
        client.admin.command('ping')
        
        # Get collection stats
        payment_count = payment_collection.count_documents({})
        members_count = old_members_collection.count_documents({})
        pending_count = pending_collection.count_documents({})
        
        status_message = (
            f"✅ **MongoDB Connection Status**\n\n"
            f"🔌 Connected to: `{MONGO_URI}`\n"
            f"📂 Database: `{DB_NAME}`\n\n"
            f"📊 **Collection Stats**\n"
            f"- Payments: {payment_count} records\n"
            f"- Old members: {members_count} records\n"
            f"- Pending users: {pending_count} records\n"
            f"- Changelogs: {len(CHANGELOGS.get('user', []))} user, {len(CHANGELOGS.get('admin', []))} admin\n\n"
            f"🕒 Checked at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        bot.reply_to(message, status_message, parse_mode="Markdown")
        logging.info(f"MongoDB connection check: SUCCESS (requested by Creator ID: {message.from_user.id})")
        
    except Exception as e:
        error_message = f"❌ **MongoDB Connection Error**\n\n{str(e)}"
        bot.reply_to(message, error_message, parse_mode="Markdown")
        logging.error(f"MongoDB connection check: FAILED - {e}")

@bot.message_handler(commands=['remove'])
def remove_self_from_pending(message):
    user_id = message.from_user.id
    
    # Check if admin or creator
    if user_id not in ADMIN_IDS and user_id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to administrators and the creator.")
        return
    
    # Remove self from pending users
    if user_id in PENDING_USERS:
        status = PENDING_USERS[user_id].get('status', 'unknown')
        PENDING_USERS.pop(user_id, None)
        
        # Remove from MongoDB too
        delete_pending_user(user_id)
        
        bot.reply_to(message, f"✅ You've been removed from pending users. Previous status: {status}")
        logging.info(f"Admin {user_id} removed self from pending users (status: {status})")
    else:
        bot.reply_to(message, "✅ You're not in the pending users list.")

@bot.message_handler(commands=['notify'])
def send_manual_reminders(message):
    """Admin command to manually trigger payment reminders only to users at specific day thresholds"""
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to administrators.")
        return
        
    bot.reply_to(message, "🔄 Processing targeted payment reminders for users at 7 days, 3 days, and expiring/expired... Please wait.")
    
    notified_users = 0
    failed_users = 0
    skipped_users = 0
    notified_list = []
    failed_list = []
    
    current_time = datetime.now()
    
    for user_id_str, data in PAYMENT_DATA.items():
        try:
            # Skip users without active payments
            if not data.get('haspayed', False):
                skipped_users += 1
                continue
                
            # Skip cancelled memberships
            if data.get('cancelled', False):
                skipped_users += 1
                continue
                
            user_id = int(user_id_str)
            due_date = datetime.strptime(data['due_date'], '%Y-%m-%d %H:%M:%S')
            days_until_due = (due_date - current_time).days
            username = safe_markdown_escape(data.get('username', None) or f"ID:{user_id}")
            
            # ONLY send reminders at specific thresholds: exactly 7 days, exactly 3 days, or 0/negative days
            if days_until_due == 7:
                reminder_message = (
                    f"📝 *Payment Reminder*\n\n"
                    f"Your membership will expire in *7 days* on {due_date.strftime('%Y-%m-%d')}.\n\n"
                    f"Thank you for being a member of Prodigy Trading Academy! Please prepare to renew soon."
                )
            elif days_until_due == 3:
                reminder_message = (
                    f"⚠️ *Payment Reminder - Action Required Soon*\n\n"
                    f"Your membership will expire in *3 days* on {due_date.strftime('%Y-%m-%d')}.\n\n"
                    f"Please prepare to renew your membership to avoid losing access."
                )
            elif days_until_due <= 0:
                reminder_message = (
                    f"🚨 *URGENT: Payment Overdue*\n\n"
                    f"Your membership has expired or will expire today.\n\n"
                    f"Please renew immediately to maintain your access to Prodigy Trading Academy services."
                )
            else:
                # Skip users who are not at the targeted day thresholds
                skipped_users += 1
                continue
            
            # Try to send the message
            try:
                bot.send_chat_action(user_id, 'typing')
                bot.send_message(user_id, reminder_message, parse_mode="Markdown")
                notified_users += 1
                notified_list.append(f"@{username} ({days_until_due} days left)")
                logging.info(f"Manual reminder sent to user {user_id} ({days_until_due} days remaining)")
            except ApiException as e:
                failed_users += 1
                failed_list.append(f"@{username} ({days_until_due} days left)")
                logging.error(f"Failed to send manual reminder to user {user_id}: {e}")
                
        except Exception as e:
            logging.error(f"Error processing manual reminder for user {user_id_str}: {e}")
            failed_users += 1
    
    # Send summary to admin
    summary = (
        f"📊 *Targeted Payment Reminder Summary*\n\n"
        f"✅ Successfully notified: {notified_users} users\n"
        f"❌ Failed to notify: {failed_users} users\n"
        f"⏩ Skipped (inactive/cancelled/not at threshold): {skipped_users} users\n\n"
    )
    
    # Add the lists of notified and failed users
    if notified_list:
        summary += "✅ *Notified Users:*\n"
        for i, user in enumerate(notified_list, 1):
            if i <= 20:  # Limit to 20 users to avoid message length issues
                summary += f"  {i}. {user}\n"
        if len(notified_list) > 20:
            summary += f"  ...and {len(notified_list) - 20} more\n"
        summary += "\n"
    
    if failed_list:
        summary += "❌ *Failed Users:*\n"
        for i, user in enumerate(failed_list, 1):
            if i <= 20:  # Limit to 20 users to avoid message length issues
                summary += f"  {i}. {user}\n"
        if len(failed_list) > 20:
            summary += f"  ...and {len(failed_list) - 20} more\n"
    
    # Send summary message
    try:
        bot.send_message(message.chat.id, summary, parse_mode="Markdown")
    except ApiException:
        # If markdown parsing fails, send without formatting
        bot.send_message(message.chat.id, summary.replace('*', ''), parse_mode=None)

# Function to handle payment proof and old member verification requests
def send_pending_request_reminders():
    while True:
        try:
            current_time = datetime.now()
            
            for user_id, data in PENDING_USERS.items():
                # Check for payment verification requests
                if data.get('status') == 'waiting_approval':
                    # Check if submission timestamp exists
                    if 'request_time' not in data:
                        # Add timestamp now for existing requests
                        PENDING_USERS[user_id]['request_time'] = current_time
                        save_pending_users()
                        continue
                        
                    # Calculate time elapsed since request
                    request_time = data['request_time']
                    if isinstance(request_time, str):
                        request_time = datetime.strptime(request_time, '%Y-%m-%d %H:%M:%S')
                    
                    time_elapsed = (current_time - request_time).total_seconds() / 60  # in minutes
                    
                    # Check if it's been more than 10 minutes and reminder not sent yet
                    if time_elapsed > 10 and not data.get('reminder_sent', False):
                        # Send reminder to user
                        try:
                            bot.send_message(
                                user_id,
                                "⏳ Your payment verification request is still pending. The admins might be busy at the moment. "
                                "Please be patient as they review your submission."
                            )
                            logging.info(f"Sent waiting reminder to user {user_id} for payment verification")
                        except Exception as e:
                            logging.error(f"Failed to send wait reminder to user {user_id}: {e}")
                        
                        # Send reminder to all admins
                        for admin_id in ADMIN_IDS:
                            try:
                                user_info = bot.get_chat(user_id)
                                username = user_info.username or f"User {user_id}"
                                escaped_username = safe_markdown_escape(username)  # Properly escape the username
                                bot.send_message(
                                    admin_id,
                                    f"⚠️ *Reminder:* @{escaped_username} has been waiting for payment verification for over 10 minutes.",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logging.error(f"Failed to send admin reminder to {admin_id} about user {user_id}: {e}")
                        
                        # Mark reminder as sent
                        PENDING_USERS[user_id]['reminder_sent'] = True
                        save_pending_users()
                
                # Check for old member verification requests
                if data.get('status') == 'old_member_request':
                    # Check if submission timestamp exists
                    if 'request_time' not in data:
                        # Add timestamp now for existing requests
                        PENDING_USERS[user_id]['request_time'] = current_time
                        save_pending_users()
                        continue
                    
                    # Calculate time elapsed since request
                    request_time = data['request_time']
                    if isinstance(request_time, str):
                        request_time = datetime.strptime(request_time, '%Y-%m-%d %H:%M:%S')
                    
                    time_elapsed = (current_time - request_time).total_seconds() / 60  # in minutes
                    
                    # Check if it's been more than 10 minutes and reminder not sent yet
                    if time_elapsed > 10 and not data.get('reminder_sent', False):
                        # Send reminder to user
                        try:
                            bot.send_message(
                                user_id,
                                "⏳ Your old member verification request is still pending. The admins might be busy at the moment. "
                                "Please be patient as they review your submission."
                            )
                            logging.info(f"Sent waiting reminder to user {user_id} for old member verification")
                        except Exception as e:
                            logging.error(f"Failed to send wait reminder to user {user_id}: {e}")
                        
                        # Send reminder to all admins
                        for admin_id in ADMIN_IDS:
                            try:
                                user_info = bot.get_chat(user_id)
                                username = user_info.username or f"User {user_id}"
                                escaped_username = safe_markdown_escape(username)  # Properly escape the username
                                bot.send_message(
                                    admin_id,
                                    f"⚠️ *Reminder:* @{escaped_username} has been waiting for old member verification for over 10 minutes.",
                                    parse_mode="Markdown"
                                )
                            except Exception as e:
                                logging.error(f"Failed to send admin reminder to {admin_id} about user {user_id}: {e}")
                        
                        # Mark reminder as sent
                        PENDING_USERS[user_id]['reminder_sent'] = True
                        save_pending_users()
            
            # Sleep for 1 minute before next check
            time.sleep(60)
            
        except Exception as e:
            logging.error(f"Error in pending request reminder thread: {e}")
            time.sleep(60)  # Wait a minute on error before trying again

def refresh_mongodb_data():
    """Refresh all data from MongoDB to ensure it's up to date."""
    global PAYMENT_DATA, CONFIRMED_OLD_MEMBERS, PENDING_USERS, CHANGELOGS
    
    try:
        PAYMENT_DATA = load_payment_data()
        
        CONFIRMED_OLD_MEMBERS = load_confirmed_old_members()
        
        PENDING_USERS = load_pending_users()
        
        CHANGELOGS = load_changelogs()
        logging.info("MongoDB data refresh completed successfully")
    except Exception as e:
        logging.error(f"Error refreshing MongoDB data: {e}")

def mongodb_refresh_thread():
    """Background thread to periodically refresh MongoDB data."""
    while True:
        try:
            # Sleep first to avoid immediate refresh after startup
            time.sleep(1800)  # 30 minutes = 1800 seconds
            
            # Refresh all data from MongoDB
            refresh_mongodb_data()
            
        except Exception as e:
            logging.error(f"Error in MongoDB refresh thread: {e}")
            time.sleep(300)  # Wait 5 minutes on error before trying again

# Define challenge content
SELF_IMPROVEMENT_CHALLENGES = [
    {"type": "ACTION", "content": "Meditate for 10 minutes today"},
    {"type": "ACTION", "content": "Practice mindful breathing (5 minute deep breathing)"},
    {"type": "QUESTION", "content": "What is one habit you want to build, and why?"},
    {"type": "QUESTION", "content": "Give 5 things you are grateful for today (no repeats)"},
    {"type": "QUESTION", "content": "What did you learn about yourself this week?"},
    {"type": "QUESTION", "content": "What is one small win you can celebrate today?"}
]

TRADING_CHALLENGES = [
    {"type": "ACTION", "content": "Watch the movements of a pair for at least 5 minutes"},
    {"type": "ACTION", "content": "Revisit your trading rules for 3 minutes"},
    {"type": "QUESTION", "content": "Review your last trade (profits, pips, tell us how it went)"},
    {"type": "QUESTION", "content": "Journal one key takeaway from today or yesterday's session"},
    {"type": "QUESTION", "content": "Write about how you felt after your latest win / loss"},
    {"type": "QUESTION", "content": "Write about how you felt during your latest trade"},
    {"type": "QUESTION", "content": "Review your latest loss and what you can learn"}
]

TRADING_PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "NZD/USD", "USD/CAD", 
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "GBP/JPY", "GBP/CHF", "AUD/JPY", "NZD/JPY",
    "USD/SGD", "EUR/AUD", "AUD/CAD", "CAD/JPY", "CHF/JPY", "AUD/NZD", "XAU/USD", "XAG/USD"
]

CHART_ANALYSIS_INSTRUCTIONS = """
Look for:
- Key support / resistance areas
- Trends in the market
- Current market sentiment (bullish, bearish, or stagnant?)
- Possible buy areas
- Possible sell areas
Check in the 5m, 15m, and 1h timeframe. Send the screenshot of the 15M timeframe of your analysis.
"""

def generate_daily_challenge():
    """Generate a truly random daily challenge from the predefined lists."""
    
    # Get today's date with enhanced formatting including day of week
    now = datetime.now(pytz.timezone('Asia/Manila'))
    today = now.strftime("%A, %B %d, %Y").upper()  # Adds day of week (e.g., "MONDAY, MARCH 18, 2025")
    
    # For true randomization, reseed the random generator each time
    random.seed(secrets.randbits(128))
    
    # Select a random self-improvement challenge
    self_improvement = random.choice(SELF_IMPROVEMENT_CHALLENGES)
    
    # Select a random trading challenge
    trading = random.choice(TRADING_CHALLENGES)
    
    # Select a random trading pair for chart analysis
    pair = random.choice(TRADING_PAIRS)
    
    # Format the message with enhanced styling
    message = f"📆 {today}\n"
    message += f"𝗗𝗔𝗜𝗟𝗬 𝗖𝗛𝗔𝗟𝗟𝗘𝗡𝗚𝗘𝗦\n\n"
    
    message += f"💪 *SELF-IMPROVEMENT* (10 POINTS)\n"
    message += f"▫️ *{self_improvement['type']}:* {self_improvement['content']}\n\n"
    
    message += f"📈 *TRADING-RELATED* (10 POINTS)\n"
    message += f"▫️ *{trading['type']}:* {trading['content']}\n\n"
    
    message += f"💻 *DAILY CHARTING* (20 POINTS)\n"
    message += f"▫️ *Pair:* {pair}\n"
    message += CHART_ANALYSIS_INSTRUCTIONS
    
    message += f"⭐ Complete all challenges for 40 TOTAL POINTS!\n"
    message += f"📸 Share your progress in the chat to earn points!"
    
    return message

last_reminder_date = None

def send_daily_challenges():
    """Send daily challenges to the group at a specified time."""
    global last_reminder_date
    logging.info("Daily challenges thread started")
    
    # Track the last day we sent a challenge to avoid duplicates
    last_challenge_date = None
    
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Manila'))
            current_time = now.strftime('%H:%M')
            current_date = now.strftime('%Y-%m-%d')
            
            # Send challenge at 8:00 AM Philippine time every day
            # Only if we haven't already sent one today
            if current_time == '08:00' and last_challenge_date != current_date:
                # Only proceed if it's a weekday (Monday=0, Sunday=6)
                is_weekday = now.weekday() < 5  # 0-4 are Monday to Friday
                
                if is_weekday:
                    challenge_message = generate_daily_challenge()
                    
                    # Send to specific topic if configured, otherwise to main group
                    if DAILY_CHALLENGE_TOPIC_ID:
                        bot.send_message(
                            PAID_GROUP_ID, 
                            challenge_message, 
                            message_thread_id=DAILY_CHALLENGE_TOPIC_ID,
                            parse_mode="Markdown"
                        )
                        logging.info(f"Sent daily challenge to topic {DAILY_CHALLENGE_TOPIC_ID} at {current_time} Philippine time.")
                    else:
                        bot.send_message(
                            PAID_GROUP_ID, 
                            challenge_message,
                            parse_mode="Markdown"
                        )
                        logging.info(f"Sent daily challenge to main group at {current_time} Philippine time.")
                    
                    # Update the last challenge date
                    last_challenge_date = current_date
                    # Reset reminder flag for the new day
                    last_reminder_date = None
                else:
                    logging.info(f"Skipped daily challenge: Weekend.")
                    
            # Send reminder at 8:30 AM if we sent a challenge today but haven't sent a reminder
            if current_time == '08:30' and last_challenge_date == current_date and last_reminder_date != current_date:
                is_weekday = now.weekday() < 5
                
                if is_weekday:
                    # Create a friendly, conversational reminder
                    reminder_messages = [
                        "Hey everyone! 👋 Just a friendly reminder to complete today's challenge. Share your work in the accountability roster to earn points for the leaderboard! 📊",
                        
                        "Good morning traders! ☕ Don't forget to tackle today's challenge - it only takes a few minutes and helps build consistent trading habits. Post your response in the accountability roster!",
                        
                        "Rise and shine, traders! ✨ Have you done today's challenge yet? Remember to post in the accountability roster to get your points for the day!",
                        
                        "Time check! ⏰ The daily challenge is waiting for your participation! Share your insights in the accountability roster and climb the leaderboard."
                    ]
                    
                    reminder = random.choice(reminder_messages)
                    
                    # MODIFIED: Always send reminder to main group chat
                    bot.send_message(
                        PAID_GROUP_ID, 
                        reminder
                    )
                    logging.info(f"Sent challenge reminder to main group at {current_time}.")
                        
                    # Update reminder date
                    last_reminder_date = current_date
            
            # Calculate the time to sleep until the start of the next minute
            sleep_time = 60 - now.second - now.microsecond / 1_000_000
            time.sleep(sleep_time)
            
        except Exception as e:
            logging.error(f"Failed to send daily challenge or reminder: {e}")
            time.sleep(60)  # Wait a minute on error before trying again

# Command to manually trigger a daily challenge (for testing or admin use)
@bot.message_handler(commands=['challenge'])
def manual_challenge(message):
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to administrators.")
        return
    
    try:
        challenge_message = generate_daily_challenge()
        
        # Send to the group chat if command is used in a group
        if message.chat.type in ['group', 'supergroup']:
            # Check if we should send to a specific topic
            if DAILY_CHALLENGE_TOPIC_ID and message.chat.id == PAID_GROUP_ID:
                bot.send_message(
                    message.chat.id, 
                    challenge_message,
                    message_thread_id=DAILY_CHALLENGE_TOPIC_ID,
                    parse_mode="Markdown"  # Add this parameter for formatting
                )
            else:
                # Send to whatever chat or topic the command was used in
                thread_id = message.message_thread_id if hasattr(message, 'message_thread_id') else None
                bot.send_message(
                    message.chat.id, 
                    challenge_message,
                    message_thread_id=thread_id,
                    parse_mode="Markdown"  # Add this parameter for formatting
                )
        # Otherwise send to the admin who requested it
        else:
            bot.send_message(
                message.chat.id, 
                challenge_message,
                parse_mode="Markdown"  # Add this parameter for formatting
            )
            
        bot.reply_to(message, "✅ Challenge generated and sent successfully!")
    except Exception as e:
        bot.reply_to(message, f"❌ Error generating challenge: {e}")

# Command to set the daily challenge topic ID
@bot.message_handler(commands=['setchallengetopic'])
def set_challenge_topic(message):
    """Set or change the topic ID for daily challenges"""
    global DAILY_CHALLENGE_TOPIC_ID
    
    # Only allow the creator to use this command
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
    
    # Extract topic ID from command arguments
    args = message.text.split()
    
    # Show current setting if no arguments provided
    if len(args) == 1:
        current_topic = DAILY_CHALLENGE_TOPIC_ID if DAILY_CHALLENGE_TOPIC_ID else "Not set (using main group)"
        bot.reply_to(message, f"Current daily challenge topic ID: `{current_topic}`\n\nTo change, use: `/setchallengetopic ID`", parse_mode="Markdown")
        return
        
    try:
        # Handle "clear" or "reset" to remove topic ID
        if args[1].lower() in ["clear", "reset", "none"]:
            DAILY_CHALLENGE_TOPIC_ID = None
            # Save to database
            BOT_SETTINGS['daily_challenge_topic_id'] = None
            save_settings(BOT_SETTINGS)
            bot.reply_to(message, "✅ Daily challenges will now be sent to the main group chat.")
            return
            
        # Try to parse as integer
        new_topic_id = int(args[1])
        DAILY_CHALLENGE_TOPIC_ID = new_topic_id
        
        # Save to database
        BOT_SETTINGS['daily_challenge_topic_id'] = new_topic_id
        save_settings(BOT_SETTINGS)
        
        bot.reply_to(message, f"✅ Daily challenges will now be sent to topic ID: `{new_topic_id}`\nThis setting has been saved to the database.", parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid topic ID. Please provide a numeric ID or 'clear' to reset.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error setting topic ID: {str(e)}")

@bot.message_handler(commands=['gettopic'])
def get_topic_id(message):
    """Command to get the topic ID of the current chat or topic."""
    # Check if user is the creator (not available to admins)
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
    
    try:
        # Check if message was sent in a group
        if message.chat.type not in ['group', 'supergroup']:
            bot.reply_to(message, "❌ This command only works in group chats with topics enabled.")
            return
            
        # Get the chat ID and topic ID
        chat_id = message.chat.id
        topic_id = message.message_thread_id if hasattr(message, 'message_thread_id') else None
        
        # Get chat title
        chat_title = message.chat.title
        
        # Send a brief acknowledgment in the group
        bot.reply_to(message, "📝 Topic information has been sent to your DM for privacy.")
        
        # Send the detailed information in a direct message
        if topic_id:
            bot.send_message(
                message.from_user.id, 
                f"📌 *Topic Information*\n\n"
                f"*Chat Title:* {chat_title}\n"
                f"*Chat ID:* `{chat_id}`\n\n"
                f"*Topic ID:* `{topic_id}`\n\n",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                message.from_user.id,
                f"📌 *Main Group Information*\n\n"
                f"*Chat Title:* {chat_title}\n"
                f"*Chat ID:* `{chat_id}`\n\n"
                f"This message is in the main group chat (not in a topic).\n\n",
                parse_mode="Markdown"
            )
            
    except ApiException as e:
        logging.error(f"Error in get_topic_id: {e}")
        if "bot can't initiate conversation with a user" in str(e):
            bot.reply_to(message, "❌ I couldn't send you a DM. Please start a conversation with me first by messaging me directly.")
        else:
            bot.reply_to(message, f"❌ Error retrieving topic information: {str(e)}")
    except Exception as e:
        logging.error(f"Error in get_topic_id: {e}")
        bot.reply_to(message, f"❌ Error retrieving topic information: {str(e)}")
        
@bot.message_handler(commands=['jarvis'])
def handle_jarvis_command(message):
    """Send a Jarvis image to the group chat"""
    if message.chat.type not in ['group', 'supergroup']:
        bot.reply_to(message, "❌ This command can only be used in group chats.")
        return
        
    try:
        # Path to the Jarvis image
        jarvis_image = "gifs/jarvis.png"  # Using existing GIFs directory
        
        # Send the image without caption
        with open(jarvis_image, 'rb') as photo:
            bot.send_photo(message.chat.id, photo)
            logging.info(f"Sent Jarvis image in chat {message.chat.id} (requested by {message.from_user.id})")
    except FileNotFoundError:
        bot.reply_to(message, "❌ Image not found.")
        logging.warning(f"Jarvis image not found (requested by {message.from_user.id})")
    except Exception as e:
        bot.reply_to(message, "❌ Error sending image.")
        logging.error(f"Error in Jarvis command: {e}")

@bot.message_handler(commands=['commands'])
def list_available_commands(message):
    """Send the user a list of available commands based on their permission level"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Define commands by permission level
    user_commands = [
        ("/start", "Begin the bot interaction or return to main menu"),
        ("/verify", "Submit payment proof for verification"),
        ("/dashboard", "View your membership status and details"),
        ("/ping", "Check if the bot is online"),
        ("/tip", "Support the bot creator"),
        ("/jarvis", "Display the Jarvis AI image"),
        ("/changelogs", "View recent updates to the bot/academy")
    ]
    
    admin_commands = [
        ("/notify", "Send payment reminders to users near expiration"),
        ("/challenge", "Manually trigger a daily challenge"),
        ("/admin_dashboard", "Access admin controls"),
        ("/leaderboard", "Manually trigger leaderboard update"),
    ]
    
    creator_commands = [
        ("/post_changelog", "Create and post a new changelog"),
        ("/gettopic", "Get the topic ID of the current chat topic"),
        ("/setchallengetopic", "Set the topic ID for daily challenges"),
        ("/setannouncementtopic", "Set the topic ID for announcements"),
        ("/setaccountabilitytopic", "Set the topic ID for accountability roster"),
        ("/setleaderboardtopic", "Set the topic ID for leaderboards"),
        ("/remove", "Remove yourself from pending users list"),
        ("/check", "Check MongoDB connection status")
    ]
    
    # Check if we're in a group chat - if so, tell the user we've sent a DM
    if message.chat.type in ['group', 'supergroup']:
        bot.reply_to(message, "📝 I've sent you a list of available commands in a private message.")
    
    try:
        # Determine which commands to show based on permission level
        is_admin = user_id in ADMIN_IDS
        is_creator = user_id == CREATOR_ID
        
        # Format the command list message
        message_text = "🤖 *AVAILABLE COMMANDS*\n\n"
        
        # Add user commands for everyone
        message_text += "*General User Commands:*\n"
        for cmd, desc in user_commands:
            message_text += f"`{cmd}` - {desc}\n"
        
        # For admins and creator, show ALL commands for transparency
        if is_admin or is_creator:
            message_text += "\n*Admin Commands:*\n"
            for cmd, desc in admin_commands:
                message_text += f"`{cmd}` - {desc}\n"
            
            message_text += "\n*Creator Commands:*\n"
            for cmd, desc in creator_commands:
                message_text += f"`{cmd}` - {desc}\n"
            
            # Additional note for admins
            if is_admin and not is_creator:
                message_text += "\n*Note:* Creator commands are shown for transparency but can only be used by the bot creator."
        
        # Send the message
        bot.send_message(
            user_id,  # Send as DM to the user
            message_text,
            parse_mode="Markdown"
        )
        
        logging.info(f"Sent command list to user {user_id}")
        
    except ApiException as e:
        # Handle case where bot can't DM the user
        if "bot can't initiate conversation with a user" in str(e):
            bot.reply_to(message, "❌ I couldn't send you a DM. Please start a conversation with me first by sending /start in a private chat.")
        else:
            bot.reply_to(message, f"❌ Error sending command list: {str(e)}")
        logging.error(f"Failed to send command list to user {user_id}: {e}")
    except Exception as e:
        bot.reply_to(message, "❌ An error occurred while processing your request.")
        logging.error(f"Error in list_available_commands: {e}")

@bot.message_handler(commands=['setaccountabilitytopic'])
def set_accountability_topic(message):
    """Set or change the topic ID for accountability posts"""
    global ACCOUNTABILITY_TOPIC_ID
    
    # Only allow the creator to use this command
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
    
    args = message.text.split()
    
    # Show current setting if no arguments provided
    if len(args) == 1:
        current_topic = ACCOUNTABILITY_TOPIC_ID if ACCOUNTABILITY_TOPIC_ID else "Not set"
        bot.reply_to(message, f"Current accountability topic ID: `{current_topic}`\n\nTo change, use: `/setaccountabilitytopic ID`", parse_mode="Markdown")
        return
        
    try:
        # Handle "clear" or "reset" to remove topic ID
        if args[1].lower() in ["clear", "reset", "none"]:
            ACCOUNTABILITY_TOPIC_ID = None
            BOT_SETTINGS['accountability_topic_id'] = None
            save_settings(BOT_SETTINGS)
            bot.reply_to(message, "✅ Accountability topic ID has been cleared.")
            return
            
        # Try to parse as integer
        new_topic_id = int(args[1])
        ACCOUNTABILITY_TOPIC_ID = new_topic_id
        
        # Save to database
        BOT_SETTINGS['accountability_topic_id'] = new_topic_id
        save_settings(BOT_SETTINGS)
        
        bot.reply_to(message, f"✅ Accountability submissions will now be monitored in topic ID: `{new_topic_id}`", parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid topic ID. Please provide a numeric ID or 'clear' to reset.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error setting topic ID: {str(e)}")

@bot.message_handler(commands=['setleaderboardtopic'])
def set_leaderboard_topic(message):
    """Set or change the topic ID for leaderboard posts"""
    global LEADERBOARD_TOPIC_ID
    
    # Only allow the creator to use this command
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
    
    args = message.text.split()
    
    # Show current setting if no arguments provided
    if len(args) == 1:
        current_topic = LEADERBOARD_TOPIC_ID if LEADERBOARD_TOPIC_ID else "Not set"
        bot.reply_to(message, f"Current leaderboard topic ID: `{current_topic}`\n\nTo change, use: `/setleaderboardtopic ID`", parse_mode="Markdown")
        return
        
    try:
        # Handle "clear" or "reset" to remove topic ID
        if args[1].lower() in ["clear", "reset", "none"]:
            LEADERBOARD_TOPIC_ID = None
            BOT_SETTINGS['leaderboard_topic_id'] = None
            save_settings(BOT_SETTINGS)
            bot.reply_to(message, "✅ Leaderboard topic ID has been cleared.")
            return
            
        # Try to parse as integer
        new_topic_id = int(args[1])
        LEADERBOARD_TOPIC_ID = new_topic_id
        
        # Save to database
        BOT_SETTINGS['leaderboard_topic_id'] = new_topic_id
        save_settings(BOT_SETTINGS)
        
        bot.reply_to(message, f"✅ Leaderboard will now be posted in topic ID: `{new_topic_id}`", parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid topic ID. Please provide a numeric ID or 'clear' to reset.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error setting topic ID: {str(e)}")

def save_user_score(user_id, username, first_name, message_id, points, submission_date):
    """Save a user's score for a submission"""
    try:
        # Create a unique identifier for each submission
        submission_id = f"{user_id}_{submission_date.strftime('%Y-%m-%d')}"
        
        # Store the submission data
        submission_data = {
            "_id": submission_id,
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "message_id": message_id,
            "points": points,
            "date": submission_date.strftime('%Y-%m-%d'),
            "timestamp": submission_date.strftime('%Y-%m-%d %H:%M:%S'),
            "month_year": submission_date.strftime('%Y-%m')
        }
        
        # Use upsert to update if exists or insert if new
        scores_collection.replace_one({"_id": submission_id}, submission_data, upsert=True)
        logging.info(f"Saved score for user {user_id}: {points} points")
        return True
    except Exception as e:
        logging.error(f"Error saving score for user {user_id}: {e}")
        return False

def get_daily_leaderboard(date):
    """Get the leaderboard for a specific day"""
    try:
        # Find all scores for the given date
        date_str = date.strftime('%Y-%m-%d')
        scores = list(scores_collection.find({"date": date_str}))
        
        # Sort by points (highest first)
        scores.sort(key=lambda x: x.get('points', 0), reverse=True)
        
        return scores
    except Exception as e:
        logging.error(f"Error getting daily leaderboard: {e}")
        return []

def get_monthly_leaderboard(year_month):
    """Get the leaderboard for a specific month"""
    try:
        # Find all submissions for the given month
        submissions = list(scores_collection.find({"month_year": year_month}))
        
        # Group by user_id and sum points
        user_scores = {}
        for submission in submissions:
            user_id = submission.get('user_id')
            points = submission.get('points', 0)
            
            if user_id not in user_scores:
                user_scores[user_id] = {
                    'user_id': user_id,
                    'username': submission.get('username'),
                    'first_name': submission.get('first_name'),
                    'total_points': 0,
                    'submissions': 0
                }
            
            user_scores[user_id]['total_points'] += points
            user_scores[user_id]['submissions'] += 1
        
        # Convert to list and sort by total points
        leaderboard = list(user_scores.values())
        leaderboard.sort(key=lambda x: x.get('total_points', 0), reverse=True)
        
        return leaderboard
    except Exception as e:
        logging.error(f"Error getting monthly leaderboard: {e}")
        return []

@bot.message_handler(func=lambda message: message.chat.id == PAID_GROUP_ID and 
                    hasattr(message, 'message_thread_id') and 
                    message.message_thread_id == ACCOUNTABILITY_TOPIC_ID)
def handle_accountability_submission(message):
    """Handle messages posted in the accountability roster topic"""
    try:
        # Only process if accountability topic is configured
        if not ACCOUNTABILITY_TOPIC_ID:
            return
            
        user_id = message.from_user.id
        username = message.from_user.username or "No_Username"
        first_name = message.from_user.first_name or username
        
        # Save information about this submission to track it
        submission_date = datetime.now(pytz.timezone('Asia/Manila'))
        submission_id = f"{user_id}_{submission_date.strftime('%Y-%m-%d')}"
        
        # Check if user already submitted today
        existing_submission = accountability_collection.find_one({"_id": submission_id})
        if existing_submission:
            # If they've already been graded, don't allow another submission
            if existing_submission.get("graded", False):
                try:
                    # Try to delete the duplicate message
                    bot.delete_message(message.chat.id, message.message_id)
                    
                    # Send a DM to inform the user
                    bot.send_message(
                        user_id,
                        "⚠️ *You've already submitted today's challenge*\n\n"
                        "I noticed you tried to submit another entry for today's challenge, but you're already "
                        "graded for today. You can only submit once per day.\n\n"
                        "Your earlier submission has been counted and will appear in today's leaderboard.",
                        parse_mode="Markdown"
                    )
                    logging.info(f"Removed duplicate submission from user {user_id}")
                except ApiException as e:
                    # If we can't delete (maybe bot isn't admin), just log it
                    logging.error(f"Failed to delete duplicate submission: {e}")
                
                return
                
            # User already submitted but not graded - update their submission
            accountability_collection.update_one(
                {"_id": submission_id},
                {"$set": {"message_id": message.message_id, "timestamp": submission_date.strftime('%Y-%m-%d %H:%M:%S')}}
            )
            logging.info(f"Updated submission for user {user_id}")
        else:
            # New submission for today
            submission_data = {
                "_id": submission_id,
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "message_id": message.message_id,
                "graded": False,
                "points": 0,
                "date": submission_date.strftime('%Y-%m-%d'),
                "timestamp": submission_date.strftime('%Y-%m-%d %H:%M:%S')
            }
            accountability_collection.insert_one(submission_data)
            logging.info(f"New submission from user {user_id}")
        
        # Add more compact grading buttons
        markup = InlineKeyboardMarkup(row_width=5)  # Make buttons fit in one row if possible
        markup.add(
            InlineKeyboardButton("❌", callback_data=f"grade_{user_id}_0"),
            InlineKeyboardButton("10", callback_data=f"grade_{user_id}_10"),
            InlineKeyboardButton("20", callback_data=f"grade_{user_id}_20"),
            InlineKeyboardButton("30", callback_data=f"grade_{user_id}_30"),
            InlineKeyboardButton("40", callback_data=f"grade_{user_id}_40")
        )
        
        # Send a more minimal message with just the grade buttons
        bot.send_message(
            message.chat.id,
            f"Grade @{username}'s submission: ⤴️",  # Arrow pointing up to indicate this is for the message above
            reply_to_message_id=message.message_id,
            reply_markup=markup,
            message_thread_id=ACCOUNTABILITY_TOPIC_ID
        )
        
    except Exception as e:
        logging.error(f"Error handling accountability submission: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("grade_"))
def handle_grading(call):
    """Handle grading button presses"""
    try:
        # Parse the callback data (format: grade_userId_points)
        parts = call.data.split("_")
        if len(parts) != 3:
            bot.answer_callback_query(call.id, "❌ Invalid callback data")
            return
            
        submission_user_id = int(parts[1])
        points = int(parts[2])
        grader_id = call.from_user.id
        
        # Check if grader is admin or creator
        if grader_id not in ADMIN_IDS and grader_id != CREATOR_ID:
            # User is not authorized - send troll message
            bot.answer_callback_query(call.id, "Nice try! You can't grade yourself, bozo! 🤡", show_alert=True)
            return
        
        # Get the submission from the original message
        original_msg = call.message.reply_to_message
        if not original_msg:
            bot.answer_callback_query(call.id, "❌ Could not find the original submission", show_alert=True)
            return
            
        user_info = original_msg.from_user
        username = user_info.username or "No_Username"
        first_name = user_info.first_name or username
        
        # Get today's date in Manila timezone for the submission ID
        manila_tz = pytz.timezone('Asia/Manila')
        submission_date = datetime.now(manila_tz)
        submission_id = f"{submission_user_id}_{submission_date.strftime('%Y-%m-%d')}"
        
        # Add more debugging
        logging.info(f"Updating accountability for user {submission_user_id}, submission ID: {submission_id}")

        # First, verify if the document exists
        existing_doc = accountability_collection.find_one({"_id": submission_id})
        if not existing_doc:
            logging.warning(f"No document found for submission ID: {submission_id}")
            # Try using the original document submission date
            msg_date = datetime.fromtimestamp(original_msg.date).replace(tzinfo=pytz.UTC)
            alt_submission_date = msg_date.astimezone(manila_tz)
            alt_submission_id = f"{submission_user_id}_{alt_submission_date.strftime('%Y-%m-%d')}"
            logging.info(f"Trying alternative submission ID: {alt_submission_id}")
            submission_id = alt_submission_id
        
        # Update with explicit result verification
        update_result = accountability_collection.update_one(
            {"_id": submission_id},
            {"$set": {"graded": True, "points": points, "graded_by": grader_id}}
        )
        
        if update_result.matched_count == 0:
            logging.error(f"Failed to match document with ID: {submission_id}")
            # Try to find any document for this user today
            today_str = submission_date.strftime('%Y-%m-%d')
            docs = list(accountability_collection.find({"user_id": submission_user_id, "date": today_str}))
            if docs:
                doc_id = docs[0].get("_id")
                logging.info(f"Found alternative document with ID: {doc_id}")
                update_result = accountability_collection.update_one(
                    {"_id": doc_id},
                    {"$set": {"graded": True, "points": points, "graded_by": grader_id}}
                )
                logging.info(f"Update result with alternative ID: matched={update_result.matched_count}, modified={update_result.modified_count}")
        else:
            logging.info(f"Updated accountability document: matched={update_result.matched_count}, modified={update_result.modified_count}")
        
        # Save the score
        save_result = save_user_score(
            submission_user_id, 
            username, 
            first_name,
            original_msg.message_id, 
            points,
            submission_date
        )
        logging.info(f"Score save result: {save_result}")
        
        # Update the accountability collection to mark as graded
        accountability_collection.update_one(
            {"_id": submission_id},
            {"$set": {"graded": True, "points": points, "graded_by": grader_id}}
        )
        
        # After successfully saving the grade, delete the grading buttons message
        try:
            # Delete the original grading message to reduce clutter
            bot.delete_message(call.message.chat.id, call.message.message_id)
            
            # Send a small confirmation in the thread that will auto-delete
            if points > 0:
                confirm_msg = f"✅ @{username}'s submission graded: {points} pts"
            else:
                confirm_msg = f"❌ @{username}'s submission rejected"
                
            temp_msg = bot.send_message(
                call.message.chat.id,
                confirm_msg,
                reply_to_message_id=original_msg.message_id,
                message_thread_id=ACCOUNTABILITY_TOPIC_ID
            )
            
            # Schedule this confirmation to be deleted after 5 seconds
            def delete_later(chat_id, message_id):
                time.sleep(5)
                try:
                    bot.delete_message(chat_id, message_id)
                except:
                    pass  # Ignore errors if message can't be deleted
                
            threading.Thread(target=delete_later, 
                         args=(temp_msg.chat.id, temp_msg.message_id)).start()
            
            bot.answer_callback_query(call.id, f"Successfully graded with {points} points!")
            
        except ApiException as e:
            logging.error(f"Error cleaning up grading UI: {e}")
            # If we can't delete, fall back to just editing the message
            markup = InlineKeyboardMarkup()
            if points > 0:
                btn_text = f"Graded: {points} pts ✅"
            else:
                btn_text = "Rejected ❌"
                
            markup.add(InlineKeyboardButton(btn_text, callback_data="already_graded"))
            
            bot.edit_message_text(
                f"@{username}'s submission graded: {points} pts",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            
            bot.answer_callback_query(call.id, f"Graded with {points} points")
        
        # Notify the user via DM
        try:
            # Random delay to simulate human typing (1-3 seconds)
            time.sleep(1 + random.random() * 2)
            
            # Show typing indicator first
            bot.send_chat_action(submission_user_id, 'typing')
            time.sleep(1.5)  # Simulate thinking time
            
            if points > 0:
                # Add variety to positive notifications
                positive_messages = [
                    f"✅ *Great job on your daily challenge submission!*\n\n"
                    f"Your hard work has been noticed by our admin team. Keep up the excellent work and check the leaderboard at midnight to see where you rank!",
                    
                    f"✅ *Challenge submission graded!*\n\n"
                    f"Thanks for participating in today's challenge! Your submission has been reviewed and points have been awarded. The daily rankings will be posted at midnight - good luck!",
                    
                    f"✅ *Daily challenge completed!*\n\n"
                    f"One of our admins has reviewed your work for today's challenge. Well done on your submission! Daily rankings are posted at midnight."
                ]
                notification_message = random.choice(positive_messages)
            else:
                # Add variety to rejection messages
                rejection_messages = [
                    f"❌ *About your challenge submission...*\n\n"
                    f"Unfortunately, your submission didn't meet all the requirements for today's challenge. Take another look at the instructions and try again tomorrow!",
                    
                    f"❌ *Challenge submission feedback*\n\n"
                    f"It looks like there was an issue with your submission for today's challenge. Review the daily challenge criteria and give it another shot tomorrow!",
                    
                    f"❌ *Daily challenge feedback*\n\n"
                    f"Thanks for participating, but your submission wasn't quite what we were looking for today. Check the challenge requirements and try again tomorrow."
                ]
                notification_message = random.choice(rejection_messages)
                
            bot.send_message(
                submission_user_id,
                notification_message,
                parse_mode="Markdown"
            )
        except ApiException:
            logging.error(f"Could not send grade notification to user {submission_user_id}")
            
    except Exception as e:
        logging.error(f"Error handling grading callback: {e}")
        bot.answer_callback_query(call.id, "❌ Error processing grade", show_alert=True)

# Handle "already graded" button to prevent further clicks
@bot.callback_query_handler(func=lambda call: call.data == "already_graded")
def handle_already_graded(call):
    bot.answer_callback_query(call.id, "This submission has already been graded!")


def generate_daily_leaderboard_text(date):
    """Generate formatted text for daily leaderboard with proper tie handling"""
    scores = get_daily_leaderboard(date)
    
    if not scores:
        return f"📊 *DAILY LEADERBOARD: {date.strftime('%B %d, %Y')}*\n\nNo entries for today!"
    
    # Format the leaderboard message
    leaderboard_text = f"📊 *DAILY LEADERBOARD: {date.strftime('%B %d, %Y')}*\n\n"
    
    # Keep track of the current rank and last score for tie detection
    current_rank = 1
    last_score = None
    
    for i, entry in enumerate(scores):
        points = entry.get('points', 0)
        username = safe_markdown_escape(entry.get('username', 'No_Username'))  # <-- Add safe_markdown_escape
        
        # If this score is different from the previous one, update the rank
        if last_score is not None and points != last_score:
            current_rank = i + 1
        
        last_score = points
        
        # Create emoji for ranks
        if current_rank == 1:
            rank_emoji = "🥇"
        elif current_rank == 2:
            rank_emoji = "🥈"
        elif current_rank == 3:
            rank_emoji = "🥉"
        else:
            rank_emoji = f"{current_rank}."
        
        leaderboard_text += f"{rank_emoji} @{username}: *{points} points*\n"
    
    return leaderboard_text

def generate_monthly_leaderboard_text(year_month_str):
    """Generate formatted text for monthly leaderboard with proper tie handling"""
    # Parse year-month string into a date object to get month name
    try:
        date = datetime.strptime(year_month_str, '%Y-%m')
        month_name = date.strftime('%B %Y')
    except:
        month_name = year_month_str
    
    scores = get_monthly_leaderboard(year_month_str)
    
    if not scores:
        return f"📊 *MONTHLY LEADERBOARD: {month_name}*\n\nNo entries this month!"
    
    # Format the leaderboard message
    leaderboard_text = f"📊 *MONTHLY LEADERBOARD: {month_name}*\n\n"
    
    # Keep track of the current rank and last score for tie detection
    current_rank = 1
    last_score = None
    
    for i, entry in enumerate(scores):
        total_points = entry.get('total_points', 0)
        username = safe_markdown_escape(entry.get('username', 'No_Username'))  # <-- Add safe_markdown_escape
        submissions = entry.get('submissions', 0)
        
        # If this score is different from the previous one, update the rank
        if last_score is not None and total_points != last_score:
            current_rank = i + 1
            
        last_score = total_points
        
        # Create emoji for ranks
        if current_rank == 1:
            rank_emoji = "🥇"
        elif current_rank == 2:
            rank_emoji = "🥈"
        elif current_rank == 3:
            rank_emoji = "🥉"
        else:
            rank_emoji = f"{current_rank}."
        
        leaderboard_text += f"{rank_emoji} @{username}: *{total_points} points* ({submissions} submissions)\n"
    
    leaderboard_text += f"\n🏆 Congratulations to all participants! Keep up the great work!"
    
    return leaderboard_text

def send_daily_leaderboard():
    """Send the daily leaderboard at midnight"""
    logging.info("Daily leaderboard thread started")
    
    # Track last leaderboard sent date
    last_leaderboard_date = None
    
    while True:
        try:
            now = datetime.now(pytz.timezone('Asia/Manila'))
            
            # Check if it's midnight (00:00) and we haven't sent a leaderboard today
            if now.strftime('%H:%M') == '00:00' and now.strftime('%Y-%m-%d') != last_leaderboard_date:
                logging.info("It's midnight - generating daily leaderboard")
                
                # Get yesterday's date (since we're sending at midnight)
                yesterday = now - timedelta(days=1)
                
                # Generate leaderboard text
                leaderboard_text = generate_daily_leaderboard_text(yesterday)
                
                # Send the leaderboard to the designated topic
                if LEADERBOARD_TOPIC_ID:
                    bot.send_message(
                        PAID_GROUP_ID, 
                        leaderboard_text,
                        parse_mode="Markdown",
                        message_thread_id=LEADERBOARD_TOPIC_ID
                    )
                    logging.info(f"Sent daily leaderboard to topic {LEADERBOARD_TOPIC_ID}")
                else:
                    logging.warning("No leaderboard topic ID configured - skipping leaderboard")
                
                # Check if it's also month-end
                if yesterday.day == calendar.monthrange(yesterday.year, yesterday.month)[1]:
                    # It's the last day of the month - send monthly leaderboard too
                    month_year = yesterday.strftime('%Y-%m')
                    monthly_leaderboard = generate_monthly_leaderboard_text(month_year)
                    
                    # Send after a short delay
                    time.sleep(3)
                    
                    if LEADERBOARD_TOPIC_ID:
                        bot.send_message(
                            PAID_GROUP_ID, 
                            monthly_leaderboard,
                            parse_mode="Markdown",
                            message_thread_id=LEADERBOARD_TOPIC_ID
                        )
                        logging.info(f"Sent monthly leaderboard to topic {LEADERBOARD_TOPIC_ID}")
                
                # Update last leaderboard date
                last_leaderboard_date = now.strftime('%Y-%m-%d')
            
            # Sleep until the next minute
            sleep_time = 60 - now.second - now.microsecond / 1_000_000
            time.sleep(sleep_time)
            
        except Exception as e:
            logging.error(f"Error sending leaderboard: {e}")
            time.sleep(60)  # Wait for a minute before trying again

@bot.message_handler(commands=['leaderboard'])
def manual_leaderboard(message):
    """Command to manually generate and send leaderboards for testing"""
    # Check if user is admin or creator
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to administrators.")
        return
    
    args = message.text.split()
    
    try:
        # Default to today's leaderboard
        now = datetime.now(pytz.timezone('Asia/Manila'))
        
        if len(args) > 1 and args[1].lower() == "monthly":
            # Generate monthly leaderboard
            if len(args) > 2:
                # Parse specified month
                try:
                    year_month = args[2]  # Format YYYY-MM
                    leaderboard_text = generate_monthly_leaderboard_text(year_month)
                except:
                    bot.reply_to(message, "❌ Invalid month format. Use YYYY-MM (e.g., 2025-03)")
                    return
            else:
                # Use current month
                year_month = now.strftime('%Y-%m')
                leaderboard_text = generate_monthly_leaderboard_text(year_month)
                
            board_type = "monthly"
        else:
            # Generate daily leaderboard
            if len(args) > 1:
                # Parse specified date
                try:
                    date = datetime.strptime(args[1], '%Y-%m-%d')
                    date = date.replace(tzinfo=pytz.timezone('Asia/Manila'))
                except:
                    bot.reply_to(message, "❌ Invalid date format. Use YYYY-MM-DD")
                    return
            else:
                # Use today's date
                date = now
                
            leaderboard_text = generate_daily_leaderboard_text(date)
            board_type = "daily"
        
        # Send the leaderboard
        if message.chat.type in ['group', 'supergroup'] and message.chat.id == PAID_GROUP_ID:
            # If in the group chat, respect topic configuration
            if LEADERBOARD_TOPIC_ID:
                bot.send_message(
                    PAID_GROUP_ID,
                    leaderboard_text,
                    parse_mode="Markdown",
                    message_thread_id=LEADERBOARD_TOPIC_ID
                )
            else:
                # Send to current topic if in a topic, or main group
                thread_id = message.message_thread_id if hasattr(message, 'message_thread_id') else None
                bot.send_message(
                    message.chat.id,
                    leaderboard_text,
                    parse_mode="Markdown",
                    message_thread_id=thread_id
                )
        else:
            # Send directly to the user
            bot.send_message(
                message.chat.id,
                leaderboard_text,
                parse_mode="Markdown"
            )
            
        bot.reply_to(message, f"✅ {board_type.capitalize()} leaderboard generated successfully!")
    except Exception as e:
        bot.reply_to(message, f"❌ Error generating leaderboard: {str(e)}")
        logging.error(f"Error in manual_leaderboard: {e}")


# Command handler for /setconfessiontopic
@bot.message_handler(commands=['setconfessiontopic'])
def set_confession_topic(message):
    """Set or change the topic ID for confessions"""
    global CONFESSION_TOPIC_ID
    
    # Only allow the creator to use this command
    if message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to the bot creator.")
        return
    
    args = message.text.split()
    
    # Show current setting if no arguments provided
    if len(args) == 1:
        current_topic = CONFESSION_TOPIC_ID if CONFESSION_TOPIC_ID else "Not set (using main group)"
        bot.reply_to(message, f"Current confession topic ID: `{current_topic}`\n\nTo change, use: `/setconfessiontopic ID`", parse_mode="Markdown")
        return
        
    try:
        # Handle "clear" or "reset" to remove topic ID
        if args[1].lower() in ["clear", "reset", "none"]:
            CONFESSION_TOPIC_ID = None
            BOT_SETTINGS['confession_topic_id'] = None
            save_settings(BOT_SETTINGS)
            bot.reply_to(message, "✅ Confessions will now be sent to the main group chat.")
            return
            
        # Try to parse as integer
        new_topic_id = int(args[1])
        CONFESSION_TOPIC_ID = new_topic_id
        
        # Save to database
        BOT_SETTINGS['confession_topic_id'] = new_topic_id
        save_settings(BOT_SETTINGS)
        
        bot.reply_to(message, f"✅ Confessions will now be sent to topic ID: `{new_topic_id}`\nThis setting has been saved to the database.", parse_mode="Markdown")
        
    except ValueError:
        bot.reply_to(message, "❌ Invalid topic ID. Please provide a numeric ID or 'clear' to reset.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error setting topic ID: {str(e)}")

# Command to initiate a confession
@bot.message_handler(commands=['confess'])
def start_confession(message):
    """Start the confession process"""
    # Only allow in private chats
    if message.chat.type != 'private':
        bot.reply_to(message, "🤫 Please send me a direct message to start your confession.")
        return
    
    user_id = message.from_user.id
    
    # Check if user is already confessing
    if user_id in USERS_CONFESSING:
        bot.send_message(user_id, "⏳ You already have a confession in progress. Please complete it or send /cancel to stop.")
        return
    
    USERS_CONFESSING[user_id] = {'status': 'awaiting_confession'}
    
    # Personalize the instruction for better engagement
    welcome_messages = [
        "🔒 *Anonymous Confession*\n\nShare your trading frustrations, wins, or anything on your mind. Your identity will remain hidden.\n\nType your confession now or send /cancel to stop.",
        
        "🤫 *Secret Sharing*\n\nGot something to get off your chest about your trading journey? No one will know it's you.\n\nType your confession now or send /cancel to stop.",
        
        "🎭 *Anonymous Message*\n\nShare your trading experiences, market observations, or personal thoughts anonymously with the community.\n\nType your confession now or send /cancel to stop."
    ]
    
    bot.send_message(user_id, random.choice(welcome_messages), parse_mode="Markdown")

# Command to cancel an in-progress confession
@bot.message_handler(commands=['cancel'])
def cancel_confession(message):
    """Cancel an in-progress confession"""
    # Only process in private chats
    if message.chat.type != 'private':
        return
        
    user_id = message.from_user.id
    
    if user_id in USERS_CONFESSING:
        USERS_CONFESSING.pop(user_id)
        bot.send_message(user_id, "✅ Confession cancelled. Your message wasn't sent.")
    else:
        bot.send_message(user_id, "❓ You don't have any active confession to cancel.")

# Handle confession messages
@bot.message_handler(func=lambda message: message.chat.type == 'private' and 
                    message.from_user.id in USERS_CONFESSING and 
                    USERS_CONFESSING[message.from_user.id]['status'] == 'awaiting_confession')
def handle_confession(message):
    """Process a user's confession"""
    user_id = message.from_user.id
    confession_text = message.text
    
    # Some basic moderation/filtering
    if not confession_text or len(confession_text) < 3:
        bot.send_message(user_id, "❌ Your confession is too short. Please write something meaningful or use /cancel to stop.")
        return
        
    if len(confession_text) > 2000:
        bot.send_message(user_id, "❌ Your confession is too long (max 2000 characters). Please shorten it or use /cancel to stop.")
        return
    
    # Check for offensive content (this is a very basic implementation)
    offensive_words = ["slur1", "slur2", "badword"]  # Replace with actual moderation list
    if any(word in confession_text.lower() for word in offensive_words):
        bot.send_message(user_id, "❌ Your confession contains content that violates our community guidelines. Please revise it or use /cancel to stop.")
        return
    
    # Increment the confession counter
    global CONFESSION_COUNTER
    CONFESSION_COUNTER += 1
    save_confession_counter(CONFESSION_COUNTER)
    
    # Format the confession message
    confession_message = f"🔐 *Confession #{CONFESSION_COUNTER}*\n\n{confession_text}"
    
    try:
        # Send to the group or topic
        if CONFESSION_TOPIC_ID:
            sent_message = bot.send_message(
                PAID_GROUP_ID,
                confession_message,
                parse_mode="Markdown",
                message_thread_id=CONFESSION_TOPIC_ID
            )
        else:
            sent_message = bot.send_message(
                PAID_GROUP_ID, 
                confession_message,
                parse_mode="Markdown"
            )
        
        # Log the confession (not linking to the user for privacy)
        logging.info(f"Confession #{CONFESSION_COUNTER} sent to group")
        
        # Send confirmation to user
        confirmation_messages = [
            "✅ *Confession sent!*\n\nYour message has been posted anonymously. Thank you for sharing.",
            "🤫 *Secret shared!*\n\nYour anonymous confession has been posted to the group.",
            "📨 *Message delivered!*\n\nYour thoughts have been shared anonymously with the community."
        ]
        
        bot.send_message(user_id, random.choice(confirmation_messages), parse_mode="Markdown")
        
        # Get user info
        try:
            user_info = bot.get_chat(user_id)
            username = user_info.username
            first_name = user_info.first_name or ""
            last_name = user_info.last_name or ""
            
            if username:
                user_display = f"@{username}"
            else:
                user_display = f"{first_name} {last_name}".strip() or f"User ID: {user_id}"
                
            # Escape any Markdown characters in user_display
            user_display = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', user_display)
        except Exception as e:
            # Fallback if we can't get user info
            logging.error(f"Error getting user info for confession: {e}")
            user_display = f"User ID: {user_id}"

        # Keep admin record of who sent what confession (for moderation purposes)
        # Only send to CREATOR, not all admins
        admin_record = f"📝 *Admin Log*\n\nConfession #{CONFESSION_COUNTER} was submitted by {user_display}"
        bot.send_message(CREATOR_ID, admin_record, parse_mode="Markdown")
        
    except Exception as e:
        logging.error(f"Error sending confession: {e}")
        bot.send_message(user_id, "❌ There was an error sending your confession. Please try again later.")
    
    # Remove user from confessing dict
    USERS_CONFESSING.pop(user_id, None)

@bot.message_handler(commands=['refreshexpired'])
def refresh_expired_members(message):
    # Check if user is admin
    if message.from_user.id not in CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to Creator only.")
        return
        
    count = 0
    for user_id_str, data in PAYMENT_DATA.items():
        try:
            due_date = datetime.strptime(data['due_date'], '%Y-%m-%d %H:%M:%S')
            now = datetime.now()
            if due_date < now and not data.get('admin_action_pending', False):
                PAYMENT_DATA[user_id_str]['admin_action_pending'] = True
                count += 1
        except Exception as e:
            logging.error(f"Error processing user {user_id_str}: {e}")
    
    save_payment_data()  # Save changes to database
    bot.reply_to(message, f"✅ Added admin_action_pending flag to {count} expired members.")

@bot.message_handler(commands=['resend'])
def resend_reminders(message):
    """Force a cleanup and resend of payment reminders"""
    # Check if user is admin or creator
    if message.from_user.id not in ADMIN_IDS and message.from_user.id != CREATOR_ID:
        bot.reply_to(message, "❌ This command is only available to administrators.")
        return
    
    try:
        # First inform that we're starting the process
        bot.reply_to(message, "🔄 Forcing reminder cleanup and resend... Please wait.")
        
        # Perform midnight cleanup to delete all existing reminders
        delete_all_reminders()
        
        # Track counts for notification results
        upcoming_reminders = 0
        expired_reminders = 0
        failed_reminders = 0
        
        # Process all users for eligible reminders
        current_time = datetime.now(pytz.timezone('Asia/Manila'))
        
        for user_id_str, data in PAYMENT_DATA.items():
            try:
                user_id = int(user_id_str)
                
                # Skip users who don't have active payments or have cancelled
                if not data.get('haspayed', False) or data.get('cancelled', False):
                    continue
                
                # Get user's due date
                due_date_naive = datetime.strptime(data['due_date'], '%Y-%m-%d %H:%M:%S')
                manila_tz = pytz.timezone('Asia/Manila')
                due_date = manila_tz.localize(due_date_naive)
                
                # Calculate days until due
                days_until_due = (due_date - current_time).days
                
                # Get display info
                username = data.get('username', None)
                if username:
                    username = escape_markdown(username)
                    user_display = f"@{username}"
                else:
                    user_display = f"User {user_id}"
                
                # Check if this user should get an upcoming payment reminder (3 days or less)
                if 0 <= days_until_due <= 3:
                    try:
                        # Send reminder to user
                        bot.send_chat_action(user_id, 'typing')
                        user_msg = bot.send_message(
                            user_id, 
                            f"⏳ Reminder: Your next payment is due in {days_until_due} days: {due_date.strftime('%Y/%m/%d %I:%M:%S %p')}."
                        )
                        
                        # Send notification to admins
                        admin_messages = {}
                        for admin_id in ADMIN_IDS:
                            admin_msg = bot.send_message(
                                admin_id, 
                                f"Admin Notice: {user_display} has an upcoming payment due in {days_until_due} days."
                            )
                            admin_messages[admin_id] = admin_msg.message_id
                        
                        # Store new message IDs
                        reminder_messages[user_id] = {
                            'user_msg_id': user_msg.message_id,
                            'admin_msg_ids': admin_messages
                        }
                        # Save to MongoDB
                        save_reminder_message(user_id, reminder_messages[user_id])
                        
                        upcoming_reminders += 1
                        
                    except ApiException:
                        # Failed to send to user, still notify admins
                        admin_messages = {}
                        for admin_id in ADMIN_IDS:
                            admin_msg = bot.send_message(
                                admin_id, 
                                f"⚠️ *Failed to send payment reminder*\n\n"
                                f"Could not send payment reminder to {user_display}.\n"
                                f"The user hasn't started a conversation with the bot or has blocked it.\n\n"
                                f"Their payment is due in {days_until_due} days: {due_date.strftime('%Y/%m/%d')}\n\n"
                                f"Please contact them manually.",
                                parse_mode="Markdown"
                            )
                            admin_messages[admin_id] = admin_msg.message_id
                        
                        # Store only admin message IDs
                        reminder_messages[user_id] = {
                            'admin_msg_ids': admin_messages
                        }
                        # Save to MongoDB
                        save_reminder_message(user_id, reminder_messages[user_id])
                        
                        failed_reminders += 1
                
                # Check if membership has expired
                elif due_date < current_time and not data.get('grace_period', False):
                    # Handle expired membership
                    try:
                        # Calculate days since expiration
                        days_expired = (current_time - due_date).days
                        
                        # Update payment data
                        PAYMENT_DATA[user_id_str]['haspayed'] = False
                        PAYMENT_DATA[user_id_str]['admin_action_pending'] = True
                        PAYMENT_DATA[user_id_str]['reminder_sent'] = False
                        
                        # Send notification to admins with action buttons based on expiration duration
                        admin_messages = {}
                        for admin_id in ADMIN_IDS:
                            markup = InlineKeyboardMarkup()
                            
                            # If expired more than 3 days, only offer kick or keep (no grace period)
                            if days_expired > 3:
                                markup.add(
                                    InlineKeyboardButton("❌ Kick Member", callback_data=f"kick_{user_id}"),
                                    InlineKeyboardButton("✓ Keep Member", callback_data=f"keep_{user_id}")
                                )
                                
                                admin_msg = bot.send_message(
                                    admin_id, 
                                    f"⚠️ *LONG-EXPIRED MEMBERSHIP*\n\n"
                                    f"{user_display}'s membership has been expired for {days_expired} days.\n\n"
                                    f"What would you like to do with this member?",
                                    parse_mode="Markdown",
                                    reply_markup=markup
                                )
                            else:
                                # For recently expired members, offer grace period
                                markup.add(
                                    InlineKeyboardButton("⏳ Give 2 Days Grace", callback_data=f"grace_{user_id}"),
                                    InlineKeyboardButton("❌ Kick Member", callback_data=f"kick_{user_id}")
                                )
                                
                                admin_msg = bot.send_message(
                                    admin_id, 
                                    f"⚠️ *MEMBERSHIP EXPIRED*\n\n"
                                    f"{user_display}'s membership has expired and has been marked as unpaid in the system.\n\n"
                                    f"What would you like to do with this member?",
                                    parse_mode="Markdown",
                                    reply_markup=markup
                                )
                                
                            admin_messages[admin_id] = admin_msg.message_id
                            
                        # Send expiry notice to user
                        try:
                            bot.send_chat_action(user_id, 'typing')
                            user_msg = bot.send_message(
                                user_id, 
                                "❌ Your membership has expired. Please renew your membership to continue accessing our services."
                            )
                            
                            # Store new message IDs
                            reminder_messages[user_id] = {
                                'user_msg_id': user_msg.message_id,
                                'admin_msg_ids': admin_messages
                            }
                            # Save to MongoDB
                            save_reminder_message(user_id, reminder_messages[user_id])
                            
                        except ApiException:
                            # Failed to send to user, store only admin messages
                            reminder_messages[user_id] = {
                                'admin_msg_ids': admin_messages
                            }
                            # Save to MongoDB
                            save_reminder_message(user_id, reminder_messages[user_id])
                            
                        expired_reminders += 1
                        
                    except Exception as e:
                        logging.error(f"Error processing expired membership for user {user_id_str}: {e}")
                        failed_reminders += 1
                        
            except Exception as e:
                logging.error(f"Error processing user {user_id_str} in resend: {e}")
                failed_reminders += 1
        
        # Save updated payment data
        save_payment_data()
        
        # Send summary to admin
        summary = (
            f"✅ *Reminder Resend Complete*\n\n"
            f"📊 *Results:*\n"
            f"• Upcoming payment reminders: {upcoming_reminders}\n"
            f"• Expired membership notifications: {expired_reminders}\n"
            f"• Failed notifications: {failed_reminders}\n\n"
            f"All previous reminder messages have been cleaned up."
        )
        bot.send_message(message.chat.id, summary, parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error during resend operation: {str(e)}")
        logging.error(f"Error in resend_reminders command: {e}")

keep_alive()

# Start reminder thread
reminder_thread = threading.Thread(target=send_payment_reminder)
reminder_thread.daemon = True  # This ensures the thread will exit when the main program exits
reminder_thread.start()

# Start the scheduled GIF thread
scheduled_gif_thread = threading.Thread(target=send_scheduled_gifs, daemon=True)
scheduled_gif_thread.start()

# Start the daily challenge thread
daily_challenge_thread = threading.Thread(target=send_daily_challenges, daemon=True)
daily_challenge_thread.start()

# Start MongoDB refresh thread
refresh_thread = threading.Thread(target=mongodb_refresh_thread)
refresh_thread.daemon = True
refresh_thread.start()

# Start reminder thread
pending_reminder_thread = threading.Thread(target=send_pending_request_reminders)
pending_reminder_thread.daemon = True
pending_reminder_thread.start()

# Start the leaderboard thread
leaderboard_thread = threading.Thread(target=send_daily_leaderboard, daemon=True)
leaderboard_thread.start()

# Add this to your bot startup code
midnight_thread = threading.Thread(target=midnight_cleanup_thread, daemon=True)
midnight_thread.start()
# Function to start the bot with auto-restart
def start_bot():
    while True:
        try:
            logging.info("Starting the bot...")
            # Add these lines to help prevent the 409 conflict error
            bot.delete_webhook()  # Ensure no webhooks are active
            time.sleep(10)  # Wait a moment to ensure previous connections are closed
            bot.polling()
            logging.info("Bot is online")
        except Exception as e:
            logging.error(f"Error occurred: {e}")
            time.sleep(5)  # Wait for 5 seconds before restarting
            logging.info("Restarting the bot...")
if __name__ == "__main__":
    start_bot()
