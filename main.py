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

# --- Helper Functions (Unchanged) ---

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

# --- LLM and Authentication Functions (Unchanged) ---

def call_llm(prompt, max_tokens=500):
    """Call Gemini API with the given prompt, wrapped in your original system instructions."""
    try:
        today_info = get_today_info()
        
        system_instructions = f"""You are a helpful assistant for EO Goa members. 

Today's Date Information:
- Today is: {today_info['formatted_readable']}

Guidelines:
- Be friendly, professional, and concise for WhatsApp.
- Use emojis and WhatsApp formatting (*bold*, _italic_) appropriately.
- Base your answers strictly on the provided content. If info isn't there, say so.
- For authentication, be VERY lenient with matching names and dates as instructed.
- When asked about events "today", check against today's date: {today_info['formatted_date']}

User Query and Content:
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
            return "I'm having trouble processing your request right now."
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Gemini API request failed: {e}")
        return "I'm having trouble connecting to the AI service."
    except Exception as e:
        logger.error(f"LLM call failed: {e}", exc_info=True)
        return "I'm having trouble processing your request right now."

def authenticate_user(user_input, content):
    """Your original, proven authentication function."""
    auth_prompt = f"""
You are authenticating a user for EO Goa member support with VERY LENIENT matching criteria.

User provided information: "{user_input}"

Available member database and content:
{content}

Authentication Instructions - BE VERY LENIENT:
1.  Look for member information (names, DOBs).
2.  For NAME matching, accept: First names only, partial names, nicknames, typos.
3.  For DATE matching, accept ANY format: DD-MM-YYYY, DD/MM/YY, 15 March, etc.
4.  If partial info matches 2-3 people, ask for more detail.
5.  Response format:
    - If confident match found: "MATCH_FOUND: [member_name]"
    - If multiple possible matches: "MULTIPLE_MATCHES: [list names] - Please specify which one"
    - If partial match needs clarification: "NEED_MORE_INFO: [specific question]"
    - Only use "NO_MATCH" if absolutely no reasonable connection found.

REMEMBER: Be generous! It's better to authenticate a real member with partial info than to reject them.
"""
    return call_llm(auth_prompt, max_tokens=300)

def handle_authenticated_query(question, member_data, content, conversation_history):
    """Handles an authenticated user's query by finding the answer in the provided content."""
    history_context = "\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history[-5:]])

    query_prompt = f"""
An authenticated EO Goa member has a question.
User's Question: "{question}"

Your task is to answer this question using ONLY the full content provided below.
The content includes all available information: member details, events, birthdays, photo links, etc.
Search the entire content to find the answer.
If the information to answer the question is not in the content, you MUST state that you cannot find the information.

--- FULL CONTENT START ---
{content}
--- FULL CONTENT END ---

Additional context for you (do not state this to the user):
- Authenticated Member Name: {member_data.get('name', 'N/A')}
- Recent Conversation History:
{history_context}
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

# ===============================================================
# === THIS IS THE CORRECTED AND RE-WRITTEN FUNCTION ===
# ===============================================================
@app.route('/twilio_webhook', methods=['POST'])
def twilio_webhook():
    """Main WhatsApp webhook handler with a more robust and direct authentication flow."""
    phone_number = request.form.get('From', '').replace('whatsapp:', '')
    message_body = request.form.get('Body', '').strip()
    
    session = get_user_session(phone_number)
    add_to_history(phone_number, 'user', message_body)
    
    content = load_content()
    response_text = ""
    today_info = get_today_info()
    
    try:
        # --- 1. Handle Reset/Menu Commands (Unchanged) ---
        if message_body.lower() in ['reset', 'restart', 'start', 'hi', 'hello', 'main', 'menu', '9']:
            user_sessions.pop(phone_number, None)
            session = get_user_session(phone_number)
            
            if message_body.lower() in ['hi', 'hello', 'start']:
                response_text = f"👋 *Welcome to EO Goa Member Support!*\n\n📅 Today is {today_info['formatted_readable']}\n\nTo access member information, please provide your *name and date of birth* (e.g., *John Doe, 15-03-1985*)."
            else:
                menu_prompt = f"Extract and format the main menu from the full content below for a WhatsApp display.\n\n---CONTENT---\n{content}"
                response_text = call_llm(menu_prompt, max_tokens=300)

        # --- 2. Handle Authenticated Users (Unchanged) ---
        elif session['authenticated']:
            # User is already authenticated, so just answer their question.
            response_text = handle_authenticated_query(message_body, session['member_data'], content, session['conversation_history'])

        # --- 3. Handle Unauthenticated Users (THIS IS THE NEW, CORRECTED LOGIC) ---
        else:
            # For any unauthenticated user, we ALWAYS try to authenticate them first.
            auth_result = authenticate_user(message_body, content)
            
            if auth_result.startswith("MATCH_FOUND:"):
                # SUCCESS! User is authenticated.
                member_name = auth_result.split("MATCH_FOUND:", 1)[1].strip()
                session['authenticated'] = True
                session['member_data'] = {"name": member_name}
                session['auth_attempts'] = 0 # Reset attempts on success
                
                welcome_msg = f"✅ *Welcome, {member_name}!* You're now authenticated."
                
                # Now, check if there was a question they asked BEFORE this successful auth.
                if session.get('pending_question'):
                    question = session.pop('pending_question')
                    answer = handle_authenticated_query(question, session['member_data'], content, session['conversation_history'])
                    response_text = f"{welcome_msg}\n\nRegarding your earlier question:\n> \"_{question}_\"\n\n{answer}"
                else:
                    # They authenticated directly, no pending question.
                    response_text = f"{welcome_msg}\n\nHow can I help you today?"

            elif auth_result.startswith("MULTIPLE_MATCHES:") or auth_result.startswith("NEED_MORE_INFO:"):
                # Authentication in progress, needs clarification from the user.
                response_text = f"🤔 {auth_result.split(':', 1)[1].strip()}"
                session['auth_attempts'] += 1
            
            else: # NO_MATCH
                # Authentication failed. Now we decide what to do.
                session['auth_attempts'] += 1

                # If this was their VERY FIRST message (auth_attempts is now 1),
                # we assume it was a question, not a failed login attempt.
                if session['auth_attempts'] == 1 and not session.get('pending_question'):
                    session['pending_question'] = message_body
                    response_text = (f"👍 *Sure, I can help with that!* But first, I need to verify your identity.\n\n"
                                     f"> \"_{message_body}_\"\n\n"
                                     f"🔐 Please provide your *name and date of birth* to continue.")
                else:
                    # This is a genuine failed authentication attempt (2nd or 3rd try).
                    if session['auth_attempts'] >= 3:
                        response_text = "❌ *Authentication failed* after multiple attempts. Please contact the admin or type 'reset' to try again."
                        session.pop('pending_question', None) # Clear any saved question
                    else:
                        attempts_left = 3 - session['auth_attempts']
                        response_text = f"❌ I couldn't match those details. Please try again.\n\n_You have {attempts_left} attempt(s) remaining._"

    except Exception as e:
        logger.error(f"Error in webhook for {phone_number}: {e}", exc_info=True)
        response_text = "😔 An unexpected error occurred. Please try again."
    
    add_to_history(phone_number, 'assistant', response_text)
    
    twiml_response = MessagingResponse()
    twiml_response.message(response_text)
    
    return str(twiml_response)
# ===============================================================
# === END OF CORRECTED FUNCTION ===
# ===============================================================


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
