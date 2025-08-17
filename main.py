from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
import os
import requests
from datetime import datetime
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# --- Configuration ---
CONTENT_FILE = 'content.md'
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# Session storage (in production, use Redis or a database)
user_sessions = {}

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def get_today_info():
    """Get today's date information in multiple formats."""
    today = datetime.now()
    return {
        'date': today.strftime('%Y-%m-%d'),
        'formatted_date': today.strftime('%d-%m-%Y'),
        'day_name': today.strftime('%A'),
        'month_name': today.strftime('%B'),
        'day': today.day,
        'month': today.month,
        'year': today.year,
        'formatted_readable': today.strftime('%A, %B %d, %Y')
    }

def load_content():
    """Load the main content from the content.md file."""
    try:
        with open(CONTENT_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Content file '{CONTENT_FILE}' not found.")
        return "Content file not found. Please contact admin."

def get_user_session(phone_number):
    """Get or create a user session."""
    if phone_number not in user_sessions:
        user_sessions[phone_number] = {
            'authenticated': False,
            'member_data': None,
            'pending_question': None,
            'conversation_history': [],
            'auth_attempts': 0
        }
    return user_sessions[phone_number]

def add_to_history(phone_number, role, message):
    """Add a message to the conversation history."""
    session = get_user_session(phone_number)
    session['conversation_history'].append({
        'role': role,
        'content': message,
        'timestamp': datetime.now().isoformat()
    })
    # Keep only the last 10 messages
    if len(session['conversation_history']) > 10:
        session['conversation_history'] = session['conversation_history'][-10:]

def detect_greeting(message):
    """Detect common greetings in the user's message - must be standalone greetings."""
    greetings = {
        "hello": "Hello! Welcome to EO Goa! 🚀", 
        "hi": "Hi there! Welcome to EO Goa! 🚀",
        "hey": "Hey! Welcome to EO Goa! 🚀",
        "good morning": "Good morning! Welcome to EO Goa! 🚀",
        "good afternoon": "Good afternoon! Welcome to EO Goa! 🚀",
        "good evening": "Good evening! Welcome to EO Goa! 🚀",
        "namaste": "Namaste! Welcome to EO Goa! 🚀",
        "namaskar": "Namaskar! Welcome to EO Goa! 🚀",
    }
    message_lower = message.lower().strip()
    
    # Only detect if the greeting is at the start and the message is short (likely just a greeting)
    if len(message_lower.split()) <= 3:
        for greeting, response in greetings.items():
            if message_lower.startswith(greeting):
                return response
    return None

def detect_help_request(message):
    """Detect if user is asking what the bot can help with."""
    help_keywords = ["help", "what can you do", "what do you help with", "services", "features", "capabilities", "assist"]
    message_lower = message.lower().strip()
    for keyword in help_keywords:
        if keyword in message_lower:
            return True
    return False

def detect_birthday_query(message):
    """Detect if user is asking about birthdays."""
    birthday_keywords = [
        "birthday", "birthdays", "bday", "b'day", "born", 
        "birthday this month", "birthdays today", "who has birthday",
        "birthday list", "celebrating", "birth date"
    ]
    message_lower = message.lower().strip()
    for keyword in birthday_keywords:
        if keyword in message_lower:
            return True
    return False

def get_bot_capabilities():
    """Return the list of bot capabilities."""
    return """🤖 *Here's what I can help you with:*

1️⃣ *Birthday/Anniversary* - Member birthdays and anniversaries
2️⃣ *Strategic Alliances* - Partnership opportunities and collaborations  
3️⃣ *Upcoming Events* - Event schedules and details
4️⃣ *Member Engagement System* - Community activities and participation
5️⃣ *Annual Fees* - Membership fee information and payment details
6️⃣ *Event Photos & Videos* - Access to event media and memories
7️⃣ *Member Details* - Contact information and member directory

💬 Just ask me about any of these topics, and I'll be happy to help!

_Example: "Show me upcoming events" or "Show birthdays this month"_"""

# --- LLM and Authentication Functions ---

def call_llm(prompt, max_tokens=500):
    """Call Gemini API with the given prompt, wrapped in EO Goa system instructions."""
    try:
        today_info = get_today_info()
        
        system_instructions = f"""You are a helpful and professional AI assistant for EO Goa (Entrepreneurs' Organization - Goa Chapter).

Today's Date Information:
- Today is: {today_info['formatted_readable']}
- Current month: {today_info['month_name']} ({today_info['month']})
- Current year: {today_info['year']}

Your personality and guidelines:
- Act like a friendly, professional receptionist for EO Goa
- Be warm, welcoming, and entrepreneurial in tone
- Use appropriate WhatsApp formatting (*bold*, _italic_) and emojis
- Keep responses concise but comprehensive for WhatsApp
- Always respond in English and maintain a professional tone
- For any topics unrelated to EO, entrepreneurship, business, or networking, politely redirect back to EO Goa topics
- Base your answers strictly on the provided content/FAQ
- When asked about events "today", check against today's date: {today_info['formatted_date']}
- For birthday queries, extract all relevant birthday information from the content
- If information isn't in the content, clearly state "This information is not available in my current database"
- Always be helpful and offer alternative assistance

Remember: You're representing EO Goa - a global community of successful entrepreneurs focused on learning, networking, and growth.

User Query and Available Content:
---
"""
        
        full_prompt = system_instructions + prompt
        
        headers = {
            'Content-Type': 'application/json',
            'x-goog-api-key': GEMINI_API_KEY
        }
        data = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.7}
        }
        
        response = requests.post(GEMINI_API_URL, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        
        if 'candidates' in result and result.get('candidates'):
            return result['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            logger.error(f"Unexpected Gemini response format: {result}")
            return "I'm having trouble processing your request right now. Please try again."
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Gemini API request failed: {e}")
        return "I'm having trouble connecting right now. Please try again in a moment."
    except Exception as e:
        logger.error(f"LLM call failed: {e}", exc_info=True)
        return "I'm having trouble processing your request right now. Please try again."

def authenticate_user(user_input, content):
    """Authenticate user by checking if their name and DOB match anyone in the member database."""
    auth_prompt = f"""
You are checking if a user's authentication details match any member in the EO Goa database.

User provided: "{user_input}"

Member Database Content:
{content}

TASK: Check if the user's name and date of birth match ANY member in the database.

MATCHING RULES (BE LENIENT):
1. NAME: Accept partial names, nicknames, first name only, last name only, typos
   - "gopal" should match "Gopal Sharma" or "Gopal Kumar" etc.
   - "john" should match "John Doe" or "Jonathan Smith" etc.
   
2. DATE: Accept any date format for the same actual date
   - "31/03/1975" = "31-03-1975" = "March 31, 1975" = "31 Mar 1975"
   - Be flexible with year format: 75 = 1975
   
3. MATCH LOGIC: 
   - If name part matches AND date matches = AUTHENTICATE
   - If name matches multiple people, ask which specific person
   - If no reasonable match found = NO MATCH

RESPONSE FORMAT (EXACTLY):
- If found: "MATCH_FOUND: [Full Name from Database]"
- If multiple matches: "MULTIPLE_MATCHES: [Name1, Name2] - Which person are you?"
- If need clarification: "NEED_MORE_INFO: [specific question]"
- If no match: "NO_MATCH"

Now check: Does "{user_input}" match any member name and DOB in the database above?
"""
    return call_llm(auth_prompt, max_tokens=200)

def handle_authenticated_query(question, member_data, content, conversation_history):
    """Handle an authenticated user's query using EO Goa conversational style."""
    # Check for greeting first (only for short messages)
    if len(question.split()) <= 3:
        greeting_response = detect_greeting(question)
        if greeting_response:
            member_name = member_data.get('name', 'there')
            return f"{greeting_response}\n\n*Welcome back, {member_name}!* 😊\n\nHow may I assist you with EO Goa today?"
    
    # Check for help request
    if detect_help_request(question):
        return get_bot_capabilities()
    
    # Build conversation context
    history_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-6:]])

    # Enhanced query handling - let LLM process everything from content.md
    query_prompt = f"""
An authenticated EO Goa member has asked: "{question}"

MEMBER DATA FROM CONTENT.MD (contains all birthdays, anniversaries, events, etc.):
{content}

Recent Conversation History:
{history_context}

Member Information:
- Authenticated Member: {member_data.get('name', 'N/A')}
- Current Month: August (month 8)
- Current Date: August 17, 2025
- Current Week: August 17-23, 2025

TASK: Answer the user's question by extracting relevant information from the MEMBER DATA above.

IMPORTANT - UNDERSTAND THE DATA STRUCTURE:
- EO MEMBERS: People mentioned as "was born on" (main members like Sandeep Verenkar, Siddharth Goel, etc.)
- FAMILY MEMBERS: 
  * SPOUSES: "His/Her spouse [Name] was born on"
  * CHILDREN: "They have [number] child/children: [Name], born on"

SPECIFIC INSTRUCTIONS:

1. For MEMBER BIRTHDAY queries (asking about "members" birthday):
   - ONLY include EO members (those with "was born on" as main entry)
   - DO NOT include spouses or children
   - Format as: "🎂 *Member Name* - [Date]"

2. For FAMILY MEMBER BIRTHDAY queries (asking about "family members" or "spouses" or "children"):
   - ONLY include spouses and children 
   - DO NOT include main EO members
   - Format as: "🎂 *Family Member Name* ([relationship] of [Member Name]) - [Date]"
   - Example: "🎂 *Sonali* (spouse of Sandeep Verenkar) - December 9th"

3. For GENERAL BIRTHDAY queries (asking about "birthdays" without specifying):
   - Include BOTH members and family members
   - Clearly separate them in sections:
     "*EO Members:*" and "*Family Members:*"

4. For TIME-BASED queries:
   - "this week" = August 17-23, 2025
   - "this month" = August 2025
   - "today" = August 17, 2025

5. If NO matches found:
   - State clearly what was searched for and timeframe

6. RESPONSE FORMAT:
   - Use WhatsApp formatting (*bold*, _italic_)
   - Use appropriate emojis (🎂 for birthdays, 💒 for anniversaries)
   - Keep concise but complete
   - Professional EO Goa tone

Now extract and provide the requested information from the member data above, making sure to distinguish between EO members and their family members.
"""
    return call_llm(query_prompt, max_tokens=600)

# --- Routes ---

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "today": get_today_info()['formatted_readable'],
        "gemini_api_configured": bool(GEMINI_API_KEY)
    }), 200

@app.route('/twilio_webhook', methods=['POST'])
def twilio_webhook():
    """Main WhatsApp webhook handler with enhanced conversation layer."""
    phone_number = request.form.get('From', '').replace('whatsapp:', '')
    message_body = request.form.get('Body', '').strip()
    
    session = get_user_session(phone_number)
    add_to_history(phone_number, 'user', message_body)
    
    content = load_content()
    response_text = ""
    today_info = get_today_info()
    
    try:
        # --- 1. Handle Reset/Menu Commands ---
        if message_body.lower() in ['reset', 'restart', 'start', 'hi', 'hello', 'main', 'menu', '9']:
            user_sessions.pop(phone_number, None)
            session = get_user_session(phone_number)
            
            if message_body.lower() in ['hi', 'hello', 'start']:
                response_text = f"""🚀 *Welcome to EO Goa!*

I'm your EO Goa assistant, here to help you connect with our community of successful entrepreneurs.

📅 Today is {today_info['formatted_readable']}

Join a global community by entrepreneurs, for entrepreneurs, designed to help business owners take their leadership and companies to the next level.

🔐 To access member information, please provide your *name and date of birth* (e.g., *John Doe, 15-03-1985*).

*Connect • Learn • Grow* 🌟"""
            else:
                menu_prompt = f"Extract and format the main menu from the full content below for WhatsApp display. Keep it concise and well-formatted.\n\n---CONTENT---\n{content}"
                response_text = call_llm(menu_prompt, max_tokens=300)

        # --- 2. Handle Authenticated Users ---
        elif session['authenticated']:
            # User is already authenticated, handle their query with enhanced conversation layer
            response_text = handle_authenticated_query(message_body, session['member_data'], content, session['conversation_history'])

        # --- 3. Handle Unauthenticated Users ---
        else:
            # Always try to authenticate first for unauthenticated users
            auth_result = authenticate_user(message_body, content)
            
            if auth_result.startswith("MATCH_FOUND:"):
                # SUCCESS! User is authenticated
                member_name = auth_result.split("MATCH_FOUND:", 1)[1].strip()
                session['authenticated'] = True
                session['member_data'] = {"name": member_name}
                session['auth_attempts'] = 0
                
                welcome_msg = f"""✅ *Welcome, {member_name}!* 

You're now authenticated and ready to explore EO Goa! 🚀

I'm here to help you with our entrepreneur community. """
                
                # Check for pending question
                if session.get('pending_question'):
                    question = session.pop('pending_question')
                    # Process the pending question with full conversation layer
                    answer = handle_authenticated_query(question, session['member_data'], content, session['conversation_history'])
                    response_text = f"{welcome_msg}\n\nRegarding your earlier question:\n> \"_{question}_\"\n\n{answer}"
                else:
                    response_text = f"{welcome_msg}\n\nHow may I assist you today? Feel free to ask about events, members, birthdays, or anything EO Goa related! 😊"

            elif auth_result.startswith("MULTIPLE_MATCHES:") or auth_result.startswith("NEED_MORE_INFO:"):
                # Authentication in progress
                response_text = f"🤔 {auth_result.split(':', 1)[1].strip()}"
                session['auth_attempts'] += 1
            
            else: # NO_MATCH
                session['auth_attempts'] += 1

                # Check if this looks like authentication data (contains comma, has numbers, etc.)
                looks_like_auth = any([
                    ',' in message_body and any(c.isdigit() for c in message_body),
                    any(c.isdigit() for c in message_body) and len(message_body.split()) >= 2,
                    '/' in message_body or '-' in message_body
                ])

                if looks_like_auth or session['auth_attempts'] > 1:
                    # This appears to be a failed authentication attempt
                    if session['auth_attempts'] >= 3:
                        response_text = "❌ *Authentication failed* after multiple attempts. Please contact the admin or type 'reset' to start over."
                        session.pop('pending_question', None)
                    else:
                        attempts_left = 3 - session['auth_attempts']
                        response_text = f"""❌ I couldn't match those details in our member database.

Please try again with your *full name and date of birth*.

_You have {attempts_left} attempt(s) remaining._"""
                else:
                    # This is likely a question, not authentication data
                    greeting_response = detect_greeting(message_body)
                    if greeting_response:
                        response_text = f"""{greeting_response}

I'd love to help you explore our entrepreneur community! 

🔐 To get started, please provide your *name and date of birth* for authentication (e.g., *John Doe, 15-03-1985*)."""
                    else:
                        session['pending_question'] = message_body
                        response_text = f"""👍 *Great question!* I'd be happy to help with that.

> \"_{message_body}_\"

🔐 First, I need to verify your identity. Please provide your *name and date of birth* to continue (e.g., *John Doe, 15-03-1985*)."""

    except Exception as e:
        logger.error(f"Error in webhook for {phone_number}: {e}", exc_info=True)
        response_text = "😔 An unexpected error occurred. Please try again or contact support."
    
    add_to_history(phone_number, 'assistant', response_text)
    
    twiml_response = MessagingResponse()
    twiml_response.message(response_text)
    
    return str(twiml_response)

@app.route('/sessions', methods=['GET'])
def get_sessions():
    """Debug endpoint to view active sessions."""
    return jsonify({
        'active_sessions': len(user_sessions),
        'sessions': user_sessions
    })

if __name__ == '__main__':
    if not GEMINI_API_KEY:
        logger.error("FATAL: GEMINI_API_KEY environment variable not set!")
        exit(1)
    
    logger.info(f"Starting EO Goa WhatsApp Bot on port 8000. Today is {get_today_info()['formatted_readable']}")
    app.run(host='0.0.0.0', port=8000, debug=False)
