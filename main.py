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
    """Detect common greetings in the user's message."""
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
    for greeting, response in greetings.items():
        if greeting in message_lower:
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

_Example: "Show me upcoming events" or "When is John's birthday?"_"""

# --- LLM and Authentication Functions ---

def call_llm(prompt, max_tokens=500):
    """Call Gemini API with the given prompt, wrapped in EO Goa system instructions."""
    try:
        today_info = get_today_info()
        
        system_instructions = f"""You are a helpful and professional AI assistant for EO Goa (Entrepreneurs' Organization - Goa Chapter).

Today's Date Information:
- Today is: {today_info['formatted_readable']}

Your personality and guidelines:
- Act like a friendly, professional receptionist for EO Goa
- Be warm, welcoming, and entrepreneurial in tone
- Use appropriate WhatsApp formatting (*bold*, _italic_) and emojis
- Keep responses concise but comprehensive for WhatsApp
- Always respond in English and maintain a professional tone
- For any topics unrelated to EO, entrepreneurship, business, or networking, politely redirect back to EO Goa topics
- Base your answers strictly on the provided content/FAQ
- When asked about events "today", check against today's date: {today_info['formatted_date']}
- If information isn't in the content, politely say so and offer to help with other EO-related queries

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
    """Authenticate user with VERY LENIENT matching criteria."""
    auth_prompt = f"""
You are authenticating a user for EO Goa member support with VERY LENIENT matching criteria.

User provided information: "{user_input}"

Available member database and content:
{content}

Authentication Instructions - BE VERY LENIENT:
1. Look for member information (names, DOBs).
2. For NAME matching, accept: First names only, partial names, nicknames, typos.
3. For DATE matching, accept ANY format: DD-MM-YYYY, DD/MM/YY, 15 March, etc.
4. If partial info matches 2-3 people, ask for more detail.
5. Response format:
    - If confident match found: "MATCH_FOUND: [member_name]"
    - If multiple possible matches: "MULTIPLE_MATCHES: [list names] - Please specify which one"
    - If partial match needs clarification: "NEED_MORE_INFO: [specific question]"
    - Only use "NO_MATCH" if absolutely no reasonable connection found.

REMEMBER: Be generous! It's better to authenticate a real member with partial info than to reject them.
"""
    return call_llm(auth_prompt, max_tokens=300)

def handle_authenticated_query(question, member_data, content, conversation_history):
    """Handle an authenticated user's query using EO Goa conversational style."""
    # Check for greeting first
    greeting_response = detect_greeting(question)
    if greeting_response:
        member_name = member_data.get('name', 'there')
        return f"{greeting_response}\n\n*Welcome back, {member_name}!* 😊\n\nHow may I assist you with EO Goa today?"
    
    # Check for help request
    if detect_help_request(question):
        return get_bot_capabilities()
    
    # Build conversation context
    history_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-6:]])

    query_prompt = f"""
An authenticated EO Goa member has asked: "{question}"

Your task is to answer this question using the provided content/FAQ, maintaining the friendly EO Goa receptionist tone.

Available Content/FAQ:
{content}

Recent Conversation History:
{history_context}

Member Information:
- Authenticated Member: {member_data.get('name', 'N/A')}

Instructions:
- Answer based on the content provided
- If the information isn't available, politely say so and offer to help with other EO-related queries
- Maintain a warm, professional, entrepreneurial tone
- Keep responses concise for WhatsApp
- Use appropriate formatting and emojis
"""
    return call_llm(query_prompt, max_tokens=400)

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
            # Try to authenticate first
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
                    # Check if their auth message was also a greeting or help request
                    greeting_response = detect_greeting(message_body)
                    if greeting_response:
                        response_text = f"{welcome_msg}\n\nHow may I assist you today? 😊"
                    elif detect_help_request(message_body):
                        capabilities = get_bot_capabilities()
                        response_text = f"{welcome_msg}\n\n{capabilities}"
                    else:
                        response_text = f"{welcome_msg}\n\nHow may I assist you today? Feel free to ask about events, members, or anything EO Goa related!"

            elif auth_result.startswith("MULTIPLE_MATCHES:") or auth_result.startswith("NEED_MORE_INFO:"):
                # Authentication in progress
                response_text = f"🤔 {auth_result.split(':', 1)[1].strip()}"
                session['auth_attempts'] += 1
            
            else: # NO_MATCH
                session['auth_attempts'] += 1

                # If this was their first message, treat it as a question
                if session['auth_attempts'] == 1 and not session.get('pending_question'):
                    # Check if it's a greeting - provide friendly response
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
                else:
                    # Genuine failed authentication attempt
                    if session['auth_attempts'] >= 3:
                        response_text = "❌ *Authentication failed* after multiple attempts. Please contact the admin or type 'reset' to start over."
                        session.pop('pending_question', None)
                    else:
                        attempts_left = 3 - session['auth_attempts']
                        response_text = f"""❌ I couldn't match those details in our member database.

Please try again with your *full name and date of birth*.

_You have {attempts_left} attempt(s) remaining._"""

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
