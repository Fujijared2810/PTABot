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
from keep_alive import keep_alive


BOT_VERSION = "Alpha Release 3.0"

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

# Configure root logger
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

# Dictionaries to store user payment data
USER_PAYMENT_DUE = {}
PAYMENT_DATA = load_payment_data()
CONFIRMED_OLD_MEMBERS = load_confirmed_old_members()
PENDING_USERS = load_pending_users() 
CHANGELOGS = load_changelogs()
#migrate_data_to_mongodb()

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
        bot.send_message(chat_id, "⚠️ You have a pending membership verification request. Admins are reviewing your request. Please wait for their response.")
        return  # Exit the function here - don't show the intro message again
    elif pending_payment:
        bot.send_message(chat_id, "⚠️ You have a pending payment verification. Admins are reviewing your payment proof. Please wait for their response.")
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
        username = message.from_user.username or "No Username"

        # Check if the user is already verified
        if str(user_id) in CONFIRMED_OLD_MEMBERS:
            bot.send_message(chat_id, "❗ You are already confirmed as an old member of PTA.")
            return

        PENDING_USERS[chat_id]['status'] = 'old_member_request'
        PENDING_USERS[chat_id]['request_time'] = datetime.now()  # Add timestamp
        save_pending_users()

        # Escape Markdown characters in username
        username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', username)

        # Forward the request to admins with inline buttons
        for admin in ADMIN_IDS:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Confirm", callback_data=f"confirm_old_{user_id}"))
            markup.add(InlineKeyboardButton("Reject", callback_data=f"reject_old_{user_id}"))
            bot.send_message(admin, 
                f"🔔 *Existing Member Verification Request:*\n"
                f"🆔 @{username} (ID: `{user_id}`)\n\n"
                "Please review and confirm this user's status.",
                reply_markup=markup,
                parse_mode="Markdown"
            )

        bot.send_message(chat_id, "Your request has been sent to the admins for verification. Please wait.")

    elif option == "❌ Cancel Membership":
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
            bot.send_message(user_id, "❗ You are already confirmed as an old member of PTA.")
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

        bot.send_message(user_id, "✅ You have been confirmed as an old member of PTA!")
        bot.answer_callback_query(call.id, "✅ User confirmed successfully.")

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
        
        bot.send_message(user_id, "❌ Your request to be an old member has been rejected. Please reach out to the admins for more details or use /start to try again.")
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
    save_pending_users()
    bot.send_message(chat_id, "✅ Your payment confirmation is under review. We will notify you once verified.")

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
        admin_username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', admin_username)
        username = re.sub(r'([_*[\]()~`>#\+\-=|{}.!])', r'\\\1', username)

        for admin_id in ADMIN_IDS:
            bot.send_message(admin_id, f"📝 *Activity Log*\n\n{admin_username} has approved payment from PTA member @{username}.", parse_mode="Markdown")

        # ✅ Step 1: Verification successful
        bot.send_message(user_id, "✅ Verification Successful!\nWelcome to Prodigy Trading Academy. We're delighted to have you.")
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
    REMINDER_TIMES = ["09:00", "21:00"]  # 9:00 AM and 9:00 PM
    
    # Track the last day we sent reminders to avoid duplicate sends
    last_reminder_dates = {time: None for time in REMINDER_TIMES}
    
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
                        
                        # Send reminders for all users within 3 days of expiry
                        if 0 <= days_until_due <= 3 and data['haspayed'] and not data.get('cancelled', False):
                            try:
                                # Send reminder to user
                                bot.send_chat_action(user_id, 'typing')
                                bot.send_message(user_id, f"⏳ Reminder: Your next payment is due in {days_until_due} days: {due_date.strftime('%Y/%m/%d %I:%M:%S %p')}.")
                                logging.info(f"Sent payment reminder to user {user_id}")
                                
                                # Send notification to admins
                                for admin_id in ADMIN_IDS:
                                    bot.send_message(admin_id, f"Admin Notice: {user_display} has an upcoming payment due in {days_until_due} days.")
                            
                            except ApiException as e:
                                logging.error(f"Failed to send payment reminder to user {user_id}: {e}")
                                
                                for admin_id in ADMIN_IDS:
                                    bot.send_message(
                                        admin_id, 
                                        f"⚠️ *Failed to send payment reminder*\n\n"
                                        f"Could not send payment reminder to {user_display}.\n"
                                        f"The user hasn't started a conversation with the bot or has blocked it.\n\n"
                                        f"Their payment is due in {days_until_due} days: {due_date.strftime('%Y/%m/%d')}\n\n"
                                        f"Please contact them manually.",
                                        parse_mode="Markdown"
                                    )
                        
                        # Check if membership has expired
                        elif due_date < now and data['haspayed']:
                            try:
                                bot.send_chat_action(user_id, 'typing')
                                bot.send_message(user_id, "❌ Your membership has expired. Please renew your membership to continue accessing our services.")
                                logging.info(f"Sent expiry notice to user {user_id}")
                                
                                PAYMENT_DATA[user_id_str]['haspayed'] = False
                                # Reset the reminder flag when payment expires
                                PAYMENT_DATA[user_id_str]['reminder_sent'] = False
                                save_payment_data()
                                
                                # Make sure admins are notified about expired memberships
                                for admin_id in ADMIN_IDS:
                                    bot.send_message(admin_id, f"⚠️ EXPIRED: {user_display}'s membership has expired and has been marked as unpaid in the system.")
                            
                            except ApiException as e:
                                logging.error(f"Failed to send expiry notice to user {user_id}: {e}")
                                PAYMENT_DATA[user_id_str]['haspayed'] = False
                                # Reset the reminder flag when payment expires
                                PAYMENT_DATA[user_id_str]['reminder_sent'] = False
                                save_payment_data()
                                
                                for admin_id in ADMIN_IDS:
                                    bot.send_message(
                                        admin_id, 
                                        f"⚠️ *Failed to send expiry notice*\n\n"
                                        f"Could not notify {user_display} about their expired membership.\n"
                                        f"The user hasn't started a conversation with the bot or has blocked it.\n\n"
                                        f"Their membership has been marked as expired in the system.\n\n"
                                        f"Please contact them manually.",
                                        parse_mode="Markdown"
                                    )
                                    
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

# Start reminder thread
reminder_thread = threading.Thread(target=send_payment_reminder)
reminder_thread.daemon = True  # This ensures the thread will exit when the main program exits
reminder_thread.start()

@bot.message_handler(commands=['admin_dashboard'])
def admin_dashboard(message):
    if message.chat.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ You are not authorized to use this command.")
        return

    username = message.from_user.username
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📋 List Members", callback_data='list_members'))
    markup.add(InlineKeyboardButton("🔍 Check Payment Status", callback_data='check_payment_status'))
    markup.add(InlineKeyboardButton("🔄 Update Payment Status", callback_data='update_payment_status'))
    bot.send_message(message.chat.id, f"👋 Welcome to the Admin Dashboard, @{username}. Choose an option:", reply_markup=markup)
    PENDING_USERS[message.chat.id] = {'status': 'admin_dashboard'}
    save_pending_users()

@bot.callback_query_handler(func=lambda call: PENDING_USERS.get(call.message.chat.id, {}).get('status') == 'admin_dashboard')
def handle_admin_dashboard(call):
    chat_id = call.message.chat.id
    option = call.data

    if option == 'list_members':
        # Build member list with proper escaping
        members_list = []
        for user_id, data in PAYMENT_DATA.items():
            # Get username and escape special Markdown characters
            username = data.get('username', 'No Username')
            if username:
                username = username.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')
            
            # Format member info
            member_info = f"🔹 User ID: `{user_id}`\n   Username: @{username}\n   Paid: {'✅' if data.get('haspayed', False) else '❌'}"
            members_list.append(member_info)
        
        # Split into chunks to avoid message size limits
        MAX_LENGTH = 3000  # Safe limit for Telegram messages
        members_text = "\n\n".join(members_list)
        
        if len(members_text) <= MAX_LENGTH:
            bot.send_message(chat_id, f"📋 **Members List**:\n\n{members_text}", parse_mode='Markdown')
        else:
            # Send in multiple messages if too long
            chunks = []
            current_chunk = []
            current_length = 0
            
            for member in members_list:
                if current_length + len(member) + 2 > MAX_LENGTH:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = [member]
                    current_length = len(member)
                else:
                    current_chunk.append(member)
                    current_length += len(member) + 2  # +2 for "\n\n"
            
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
            
            for i, chunk in enumerate(chunks):
                bot.send_message(
                    chat_id, 
                    f"📋 **Members List (Part {i+1}/{len(chunks)}):**\n\n{chunk}", 
                    parse_mode='Markdown'
                )
    elif option == 'check_payment_status':
        bot.send_message(chat_id, "🔍 Please enter the user ID to check payment status:")
        PENDING_USERS[chat_id]['status'] = 'check_payment_status'
        save_pending_users()
    elif option == 'update_payment_status':
        bot.send_message(chat_id, "🔄 Please enter the user ID to update payment status:")
        PENDING_USERS[chat_id]['status'] = 'update_payment_status'
        save_pending_users()
    else:
        bot.send_message(chat_id, "❌ Invalid option. Please select from the available options.")

@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'check_payment_status')
def check_payment_status(message):
    chat_id = message.chat.id
    user_id = message.text

    if user_id in PAYMENT_DATA:
        data = PAYMENT_DATA[user_id]
        # Escape any markdown characters in the username
        username = data.get('username', 'No Username')
        if username:
            username = username.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')
            
        bot.send_message(
            chat_id, 
            f"🔍 **User ID**: `{user_id}`\n**Username**: @{username}\n**Paid**: {'✅' if data.get('haspayed', False) else '❌'}\n**Due Date**: {data.get('due_date', 'Not set')}", 
            parse_mode='Markdown'
        )
    else:
        bot.send_message(chat_id, "❌ User not found.")
    PENDING_USERS.pop(chat_id, None)
    save_pending_users()

@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'update_payment_status')
def update_payment_status(message):
    chat_id = message.chat.id
    user_id = message.text

    if user_id in PAYMENT_DATA:
        PAYMENT_DATA[user_id]['haspayed'] = not PAYMENT_DATA[user_id].get('haspayed', False)
        save_payment_data()
        # Escape user_id for markdown if needed
        safe_user_id = user_id.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')
        bot.send_message(chat_id, f"✅ Payment status for user ID `{safe_user_id}` has been updated.", parse_mode='Markdown')
    else:
        bot.send_message(chat_id, "❌ User not found.")
    PENDING_USERS.pop(chat_id, None)
    save_pending_users()

@bot.message_handler(func=lambda message: PENDING_USERS.get(message.chat.id, {}).get('status') == 'update_payment_status')
def update_payment_status(message):
    chat_id = message.chat.id
    user_id = message.text

    if user_id in PAYMENT_DATA:
        PAYMENT_DATA[user_id]['haspayed'] = not PAYMENT_DATA[user_id]['haspayed']
        save_payment_data()
        bot.send_message(chat_id, f"✅ Payment status for user ID `{user_id}` has been updated.", parse_mode='Markdown')
    else:
        bot.send_message(chat_id, "❌ User not found.")
    PENDING_USERS.pop(chat_id, None)
    save_pending_users()

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
    while True:
        now = datetime.now(pytz.timezone('Asia/Manila'))
        current_time = now.strftime('%H:%M')
        
        # Only proceed if it's a weekday (Monday=0, Sunday=6)
        is_weekday = now.weekday() < 5  # 0-4 are Monday to Friday
        
        if current_time in SCHEDULED_TIMES and is_weekday:
            file_path_or_url = SCHEDULED_TIMES[current_time]
            try:
                if file_path_or_url.startswith('https'):
                    bot.send_animation(PAID_GROUP_ID, file_path_or_url)
                else:
                    with open(file_path_or_url, 'rb') as file:
                        if file_path_or_url.endswith('.gif'):
                            bot.send_animation(PAID_GROUP_ID, file)
                        elif file_path_or_url.endswith('.mp4'):
                            bot.send_video(PAID_GROUP_ID, file, supports_streaming=True)
                logging.info(f"Sent scheduled file at {current_time} Philippine time.")
            except Exception as e:
                logging.error(f"Failed to send scheduled file at {current_time}: {e}")
        elif current_time in SCHEDULED_TIMES and not is_weekday:
            logging.info(f"Skipped scheduled file at {current_time}: Weekend.")
        
        # Calculate the time to sleep until the start of the next minute
        now = datetime.now(pytz.timezone('Asia/Manila'))
        sleep_time = 60 - now.second - now.microsecond / 1_000_000
        time.sleep(sleep_time)

scheduled_gif_thread = threading.Thread(target=send_scheduled_gifs, daemon=True)
scheduled_gif_thread.start()

CREATOR_USERNAME = "FujiiiiiPTA" 

@bot.message_handler(commands=['tip'])
def handle_tip_command(message):
    if message.chat.type in ['group', 'supergroup']:
        tip_message = (
            f"❤️ Love the bot? Give a tip to the creator! @{CREATOR_USERNAME}!\n\n"
            "💸 *Crypto Payments*:\n\n"
            "*USDT (TRC20)*: `TV9K3DwWLufYU5yeyXZYCtB3QNX1s983wD`\n\n"
            "*Bitcoin*: `3H7uF4H29cqDiUGNd7M9tpWashEfN8a3wP`\n\n"
            "☕ *Buy Me a Coffee*:\n"
            "[Buy Me a Coffee](buymeacoffee.com/fujii)"
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

# Start reminder thread
pending_reminder_thread = threading.Thread(target=send_pending_request_reminders)
pending_reminder_thread.daemon = True
pending_reminder_thread.start()

def refresh_mongodb_data():
    """Refresh all data from MongoDB to ensure it's up to date."""
    global PAYMENT_DATA, CONFIRMED_OLD_MEMBERS, PENDING_USERS, CHANGELOGS
    
    logging.info("Refreshing data from MongoDB...")
    
    try:
        PAYMENT_DATA = load_payment_data()
        logging.info(f"Refreshed payment data: {len(PAYMENT_DATA)} records")
        
        CONFIRMED_OLD_MEMBERS = load_confirmed_old_members()
        logging.info(f"Refreshed old members: {len(CONFIRMED_OLD_MEMBERS)} records")
        
        PENDING_USERS = load_pending_users()
        logging.info(f"Refreshed pending users: {len(PENDING_USERS)} records")
        
        CHANGELOGS = load_changelogs()
        user_logs = len(CHANGELOGS.get('user', []))
        admin_logs = len(CHANGELOGS.get('admin', []))
        logging.info(f"Refreshed changelogs: {user_logs} user, {admin_logs} admin records")
        
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

# Start MongoDB refresh thread
refresh_thread = threading.Thread(target=mongodb_refresh_thread)
refresh_thread.daemon = True
refresh_thread.start()

keep_alive()
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
