import os
import re
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

# Load environment variables from .env file (checks both current directory and backend directory)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
# Enable CORS for frontend compatibility
CORS(app)

# Discover best available model dynamically on startup
MODEL_NAME = "gemini-2.5-flash"
def discover_models():
    global MODEL_NAME
    if not API_KEY:
        return
    try:
        print("Discovering available Gemini models for your API key...")
        # Find all models that support content generation
        supported_models = [
            m.name.replace("models/", "")
            for m in genai.list_models()
            if "generateContent" in getattr(m, "supported_generation_methods", [])
        ]
        print(f"Supported generation models found: {supported_models}")
        
        # Select best available model dynamically based on priority
        preferred_models = [
            "gemini-2.5-flash",
            "gemini-flash-latest",
            "gemini-3.8-flash",
            "gemini-flash-lite-latest",
            "gemini-pro-latest"
        ]
        for pref in preferred_models:
            if pref in supported_models:
                MODEL_NAME = pref
                break
        else:
            if supported_models:
                MODEL_NAME = supported_models[0]
            
        print(f"Successfully configured to use model: {MODEL_NAME}")
    except Exception as e:
        print(f"Warning: Model discovery failed: {e}. Defaulting to {MODEL_NAME}.")

# Initialize Gemini API
# Make sure to set the GEMINI_API_KEY environment variable
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Warning: GEMINI_API_KEY environment variable not found.")
else:
    # Strip quotes, spaces, newlines, and carriage returns (fixes gRPC Illegal header value crashes)
    API_KEY = API_KEY.strip().strip("'\"").strip()
    genai.configure(api_key=API_KEY)
    discover_models()

# Helper to execute generation with automatic model fallback for 429 quota/limit errors
def generate_with_fallback(contents, safety_settings=None, system_instruction=None):
    global MODEL_NAME
    models_to_try = [MODEL_NAME]
    
    # Common standard model fallbacks using currently active models
    candidates = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-3.8-flash", "gemini-flash-lite-latest", "gemini-pro-latest"]
    for c in candidates:
        if c not in models_to_try:
            models_to_try.append(c)
            
    last_error = None
    for model_candidate in models_to_try:
        try:
            print(f"Generating content using model: {model_candidate}")
            if system_instruction:
                model = genai.GenerativeModel(
                    model_name=model_candidate,
                    system_instruction=system_instruction
                )
            else:
                model = genai.GenerativeModel(model_name=model_candidate)
                
            response = model.generate_content(contents, safety_settings=safety_settings)
            
            # If successful, lock in this model for subsequent calls
            MODEL_NAME = model_candidate
            return response
        except Exception as e:
            print(f"Model {model_candidate} failed with error: {e}")
            last_error = e
            err_str = str(e).lower()
            # If rate limited (429), out of quota, or not found, try the next model
            if "429" in err_str or "quota" in err_str or "limit" in err_str or "404" in err_str or "not found" in err_str:
                continue
            else:
                raise e
    raise last_error

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "online",
        "service": "Saarthi AI Health Assistant",
        "model": MODEL_NAME,
        "api_key_configured": bool(API_KEY)
    })

@app.route('/chat', methods=['POST'])
def chat():
    try:
        if not API_KEY:
            return jsonify({
                "reply": "GEMINI_API_KEY is not configured on the backend server. Please set it in your .env file."
            }), 500

        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"reply": "Invalid request. Please provide a message."}), 400
        
        user_message = data['message']
        lang = data.get('lang', 'en')
        
        # System instructions to tailor Gemini responses for rural Indian context
        system_instruction = (
            "You are Saarthi, a friendly AI health assistant helper for rural communities in India. "
            "Help the user understand basic symptoms, common remedies, and hygiene tips in simple language. "
            "Be empathetic and direct. "
            "CRITICAL: Always start or include a clear medical disclaimer explaining that you are an AI "
            "and not a real doctor, and suggest visiting a healthcare provider if symptoms are severe."
        )
        if lang == 'hi':
            system_instruction += " CRITICAL: Write your entire response in Hindi (हिन्दी) only."
        else:
            system_instruction += " CRITICAL: Write your response in English."
        
        response = generate_with_fallback(
            user_message,
            system_instruction=system_instruction
        )
        
        return jsonify({"reply": response.text})
        
    except Exception as e:
        print(f"Error in /chat: {e}")
        return jsonify({"reply": "Unable to connect to Saarthi. Please try again later."}), 500

@app.route('/analyze-report', methods=['POST'])
def analyze_report():
    try:
        # Check if API key is configured
        if not API_KEY:
            return jsonify({
                "summary": "GEMINI_API_KEY Missing",
                "advice": "Please set the GEMINI_API_KEY environment variable on your backend server."
            }), 500

        if request.is_json:
            json_body = request.get_json() or {}
            raw_data = json_body.get('fileData', '')
            if not raw_data:
                return jsonify({"summary": "No file provided", "advice": "Please select a file to analyze."}), 400
            if ',' in raw_data:
                raw_data = raw_data.split(',', 1)[1]
            import base64
            file_bytes = base64.b64decode(raw_data)
            filename = (json_body.get('fileName') or '').lower()
            mime_type = json_body.get('mimeType') or 'application/pdf'
            lang = json_body.get('lang', 'en')
        elif 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({"summary": "Empty file name", "advice": "Please select a valid file."}), 400
            file_bytes = file.read()
            filename = file.filename.lower()
            mime_type = file.mimetype
            lang = request.form.get('lang', 'en')
        else:
            return jsonify({"summary": "No file uploaded", "advice": "Please select a file."}), 400
            
        # Infer correct mimetype from file extension to bypass browser generic mimetypes
        if filename.endswith('.pdf'):
            mime_type = 'application/pdf'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            mime_type = 'image/jpeg'
        elif filename.endswith('.png'):
            mime_type = 'image/png'
        
        # Define prompts for medical report analysis
        prompt = (
            "Analyze this medical report image or document. Explain the values and findings in extremely simple, "
            "educational, and rural-friendly language. Avoid complex jargon or explain it if used. "
            "Highlight critical values (e.g. high/low hemoglobin, high blood sugar, etc.) in a friendly way. "
            "Return your analysis structured in two clear parts:\n"
            "1. Summary of the report.\n"
            "2. Simple educational advice and suggested next steps (e.g., whether to see a general practitioner or specialist)."
        )
        if lang == 'hi':
            prompt += " CRITICAL: You must write your entire response (both summary and advice) in Hindi (हिन्दी) only."
        else:
            prompt += " CRITICAL: Write your entire response in English."
        
        # Lower safety thresholds to BLOCK_NONE to prevent false-positives on medical jargon (e.g. tumor, injury, cancer)
        safety_settings = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]

        # Pass multimodal content directly to Gemini using the fallback generator
        response = generate_with_fallback(
            [{"mime_type": mime_type, "data": file_bytes}, prompt],
            safety_settings=safety_settings
        )
        
        # Split response text into Summary and Advice sections cleanly (supports English & Hindi)
        text_output = response.text
        
        split_pattern = r'(?i)(?:\n|\A)\s*[-*_\s]*\s*(?:#{1,4}\s*)?(?:2[\.\)]\s*|part\s*2[:\.\-]?\s*|सलाह|सुझाव|advice\b)[^\n]*\n'
        match = re.search(split_pattern, text_output)
        if match:
            summary = text_output[:match.start()].strip()
            advice = text_output[match.end():].strip()
            summary = re.sub(r'(?i)(?:\n|\A)\s*[-*_\s]*\s*(?:#{1,4}\s*)?(?:1[\.\)]\s*|part\s*1[:\.\-]?\s*|summary\b|सारांश\b)[^\n]*\n', '', summary).strip()
            summary = re.sub(r'[\r\n]+\s*---+\s*$', '', summary).strip()
        else:
            summary = text_output
            advice = "कृपया इन परिणामों की नैदानिक जांच के लिए अपने डॉक्टर से परामर्श लें।" if lang == 'hi' else "Please share these results with your healthcare provider for clinical evaluation."

        return jsonify({
            "summary": summary,
            "advice": advice
        })
        
    except Exception as e:
        print(f"Error in /analyze-report: {e}")
        return jsonify({
            "summary": "Analysis failed",
            "advice": f"Unable to parse report. Error details: {str(e)}"
        }), 500

if __name__ == '__main__':
    # Listen on dynamic PORT for Render, or 5000 for local dev
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
