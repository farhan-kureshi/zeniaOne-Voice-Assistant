import re
import logging
logger = logging.getLogger(__name__)
from typing import Dict, Any, Optional
import json

def format_business_hours(bh_str: str, lang: str = "english", script: str = "latin") -> str:
    if not bh_str: return ""
    try:
        data = json.loads(bh_str)
        if not isinstance(data, dict): return bh_str
        lines = []
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        
        # Localize day names if needed, otherwise fallback to English capitalized
        day_names = {
            'monday': 'Monday', 'tuesday': 'Tuesday', 'wednesday': 'Wednesday', 
            'thursday': 'Thursday', 'friday': 'Friday', 'saturday': 'Saturday', 'sunday': 'Sunday'
        }
        
        closed_str = "Closed"
        bh_header = "Our business hours are:"
        holiday_header = "Holidays/Special Closures:"
        
        if script == "devanagari" or lang in ["hindi", "hinglish"]:
            closed_str = "Bandh hai" if lang in ["hindi", "hinglish"] else "बंद है"
            bh_header = "Hamare business hours ye hain:" if lang in ["hindi", "hinglish"] else "हमारे काम करने का समय:"
            holiday_header = "Holidays/Chhutti:" if lang in ["hindi", "hinglish"] else "छुट्टियां:"
        elif script == "gujarati_script" or lang == "gujarati":
            closed_str = "Bandh chhe" if lang == "gujarati" else "બંધ છે"
            bh_header = "Amara business hours aa che:" if lang == "gujarati" else "અમારો કામકાજનો સમય:"
            holiday_header = "Holidays/Raja:" if lang == "gujarati" else "રજાઓ:"
            
        for day in days:
            if day in data:
                day_data = data[day]
                day_display = day_names.get(day, day.capitalize())
                if day_data.get('isOpen'):
                    open_t = day_data.get('openTime') or day_data.get('open') or ''
                    close_t = day_data.get('closeTime') or day_data.get('close') or ''
                    lines.append(f"- {day_display}: {open_t} - {close_t}")
                else:
                    lines.append(f"- {day_display}: {closed_str}")
                    
        holidays = data.get('holidays', [])
        if holidays:
            lines.append(holiday_header)
            for h in holidays:
                lines.append(f"- {h.get('name', 'Holiday')} on {h.get('date', '')}")
        
        if not lines:
            return bh_str
            
        return f"{bh_header}\n" + "\n".join(lines)
    except Exception:
        return bh_str


def check_deterministic_fast_path(
    message: str,
    company: Dict[str, Any],
    agent: Dict[str, Any],
    detected_lang: str,
    detected_script: str,
    preferred_lang: Optional[str] = None
) -> Optional[str]:
    """
    Checks if a user message can be answered deterministically from the company profile
    or as a basic social greeting, bypassing LLM generation and RAG entirely.
    """
    import string
    msg_clean = message.lower().strip()
    msg_clean_no_punct = msg_clean.translate(str.maketrans('', '', string.punctuation)).strip()

    # Apply preferred language override if specified
    if preferred_lang == "hinglish":
        detected_lang = "hinglish"
        detected_script = "latin"
    elif preferred_lang == "gujarati":
        detected_lang = "gujarati"
        detected_script = "gujarati_script"
    elif preferred_lang == "english":
        detected_lang = "english"
        detected_script = "latin"

    # ── Gender Determination (Male vs Female Agent Persona) ──
    voice_name = (agent.get("tts_voice") or "").lower()
    MALE_VOICES = {"rohan", "rahul", "aditya", "kabir", "amit", "dev", "varun", "sumit", "arjun", "ashutosh", "ratan", "manan", "aayan", "shubh", "advait", "anand", "tarun", "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham"}
    is_male = voice_name in MALE_VOICES
    help_verb = "sakta" if is_male else "sakti"
    hear_verb = "raha" if is_male else "rahi"
    dev_help = "सकता" if is_male else "सकती"
    dev_hear = "रहा" if is_male else "रही"

    # ── Language Switch Commands ──
    if re.search(r"\b(hinglish|roman\s+hindi)\b", msg_clean_no_punct) and any(w in msg_clean_no_punct for w in ["baat", "bolo", "bol", "talk", "speak", "karo", "switch", "change", "use", "me", "mein"]):
        return f"Bilkul! Ab se hum Hinglish mein baat karenge. Bataiye, main aapki kya madad kar {help_verb} hoon?"
    if re.search(r"\b(gujarati|gujrati)\b", msg_clean_no_punct) and any(w in msg_clean_no_punct for w in ["baat", "vaat", "bolo", "bol", "talk", "speak", "karo", "switch", "change", "use", "ma", "me"]):
        return "ચોક્કસ! હવેથી આપણે ગુજરાતીમાં વાત કરીશું. કહો, હું તમારી શું મદદ કરી શકું?"
    if re.search(r"\b(english|angrezi)\b", msg_clean_no_punct) and any(w in msg_clean_no_punct for w in ["baat", "bolo", "bol", "talk", "speak", "karo", "switch", "change", "use", "in"]):
        return "Sure! I will speak with you in English from now on. How can I help you today?"
    if re.search(r"\b(hindi|shuddh\s+hindi)\b", msg_clean_no_punct) and any(w in msg_clean_no_punct for w in ["baat", "bolo", "bol", "talk", "speak", "karo", "switch", "change", "use"]):
        return f"बिल्कुल! अब से हम हिंदी में बात करेंगे। बताइए, मैं आपकी क्या मदद कर {dev_help} हूँ?"
    
    # Use regex to handle repeated characters like hiiii, heyyy, hellooo without false positives
    # Expanded with Indian greetings per user request
    is_greeting = bool(re.match(r"^(h[iy]+|he+l+o+|he+y+|h[iy]+\s+there|good\s+(morning|afternoon|evening)|namaste|kem\s*cho|नमस्कार|નમસ્તે|हेलो|હેલો)$", msg_clean_no_punct))
    is_how_are_you = msg_clean_no_punct in [
        "how are you", "how r u", "how are u", "how are you doing", "kaise ho", "kese ho", "kaise ho aap", 
        "kese ho aap", "kese ho app", "kaise ho app", "aap kaise ho", "app kaise ho", "sab theek", 
        "sab kaisa hai", "kem cho", "kem chho", "kem cho tame", "kem cho tamne", "kema cho tame", 
        "kem chho tame", "tame kem cho", "tame kem chho", "हाउ आर यू", "कैसे हो", "કેમ છો"
    ]
    is_thanks = msg_clean_no_punct in [
        "thanks", "thank you", "dhanyawad", "dhanyvad", "dhanyavad", "shukriya", 
        "bahut shukriya", "bohot shukriya", "bahut dhanyavad", "bohot dhanyavad", 
        "aabhar", "આભાર", "धन्यवाद", "thx", "thank u", "many thanks", "kya hai dhanyvad", "dhanyvad kya hai"
    ]
    is_hear_me = msg_clean_no_punct in [
        "can you hear me", "are you there", "sun rahe ho", "kya aap sun rahe ho", 
        "kya app sun rahe ho", "suno", "meri awaz aa rahi hai", "awaz aa rahi hai", 
        "awaz sun rahe ho", "sun pa rahe ho"
    ]
    
    c_name = company.get("name", "our company") if company else "our company"
    if c_name.upper() == "INTERNAL / PLATFORM" or c_name == "ZeniaAI Internal Workspace":
        c_name = "ZeniaOne"
    
    settings = company.get("settings", {}) if company else {}
    
    is_profile_query = False
    profile_response = None
    
    # ── Product Overview Fast Paths ───────────────────────────────────────────
    _z_names = r"(?:zeniaone|zinnia one|zenia one|zenya one|zeniaai|zenia ai|zeniya one|zeniya ai|zene one|zene ai|sania one|सानिया वन|ज़ेनिया वन|ज़ेनियावन|zenia|ज़ेनिया|जानेमन|you|the\s+platform)"
    z_one_pattern = re.compile(
        rf"^(what(?:\s+is|'?s)?|tell\s+me\s+(?:more\s+)?about|explain|who\s+are\s+you|who\s+r\s+u|kon\s+cho|व्हाट\s+इस)\s+{_z_names}$|"
        rf"^{_z_names}\s+(kya hai|kya he|kya che|su che|su chhe|ke bare mein batao|ke bare me batao|na vara ma|vishe|vishe janavo|kya karta hai|features kya hain|features batao|modules kya hain)$|"
        rf"^(kya hai|kya he|kya che|su che|su chhe)\s+{_z_names}$|"
        rf"^tame\s+{_z_names}\s+(?:chho|cho)\s+ke\s+{_z_names}$|"
        rf"^are\s+you\s+{_z_names}\s+or\s+{_z_names}$|"
        rf"^tame\s+{_z_names}\s+(?:na\s+vara\s+ma\s+su\s+janavso|vishe\s+shu\s+janavo|vishe\s+shu\s+janavso)(?:\s+amne)?$", 
        re.IGNORECASE
    )
    z_hr_pattern = re.compile(
        r"^(what(?:\s+is|'?s)?|tell\s+me\s+(?:more\s+)?about|explain)\s+(zeniahr|zinnia hr|zenia hr|zenya hr|zene hr)$|"
        r"^(zeniahr|zinnia hr|zenia hr|zenya hr|zene hr)\s+(kya hai|kya he|ke bare mein batao|ke bare me batao|kya karta hai|features kya hain|features batao|modules kya hain)$|"
        r"^(kya hai|kya he)\s+(zeniahr|zinnia hr|zenia hr|zenya hr|zene hr)$", 
        re.IGNORECASE
    )

    # ── Proactive Features, Scope & Capabilities Suggestion Fast Path ──
    capabilities_pattern = re.compile(
        r"^(?:"
        r"what\s+can\s+you\s+(?:do|help(?:\s+me)?(?:\s+with)?)|"
        r"how\s+can\s+you\s+help(?:\s+me)?|"
        r"what\s+are\s+your\s+capabilities|"
        r"aap\s+(?:kya\s+kya\s+)?(?:kar\s+sakte\s+ho|madad\s+kar\s+sakte\s+ho)|"
        r"mujhe\s+kya\s+help\s+kar\s+sakte\s+ho|"
        r"tame\s+(?:mane\s+)?(?:shu|su)\s+madad\s+kari\s+shako|"
        r"tame\s+(?:shu|su)\s+kari\s+shako\s+cho|"
        r"what\s+do\s+you\s+know"
        r")$",
        re.IGNORECASE
    )
    if capabilities_pattern.search(msg_clean_no_punct):
        logger.info("[PRODUCT_FAST_PATH] topic=capabilities_suggestions matched=true")
        agent_display_name = agent.get("name", "ZeniaOne Assistant")
        if detected_lang == "gujarati" or detected_script == "gujarati_script":
            return (
                f"હું {c_name} ના ઓફિશિયલ AI વોઇસ આસિસ્ટન્ટ ({agent_display_name}) છું. મારી પાસે તમારા માટે આ તમામ માહિતી અને સુવિધાઓ ઉપલબ્ધ છે:\n\n"
                f"1. 📞 AI વોઇસ એજન્ટ & કોલિંગ: કુદરતી માનવ અવાજમાં ઓટોમેટેડ વોઇસ કોલિંગ અને રીઅલ-ટાઇમ અવાજ સહાયતા.\n"
                f"2. 🏢 કંપની પ્રોફાઇલ & વિગતો: {c_name} ના બિઝનેસ ટાઇમિંગ્સ, ઓફિસ સરનામું, સંપર્ક વિગતો અને સેવાઓ.\n"
                f"3. 📚 નોલેજ બેઝ & પ્રોડક્ટ્સ: અપલોડ કરેલા ડોક્યુમેન્ટ્સ, પ્રોડક્ટ કેટલોગ અને FAQs માંથી સચોટ જવાબો.\n"
                f"4. 🌐 મલ્ટિલિંગ્વલ સપોર્ટ: ગુજરાતી, હિંગ્લિશ, હિન્દી અને અંગ્રેજીમાં રીઅલ-ટાઇમ વાતચીત.\n\n"
                f"💡 તમે મને આ સવાલો પૂછી શકો છો:\n"
                f"• '{c_name} ના મુખ્ય ફીચર્સ શું છે?'\n"
                f"• 'ઓફિસનો સમય અને કોન્ટેક્ટ નંબર આપો.'\n"
                f"• 'વોઇસ એજન્ટ કેવી રીતે કામ કરે છે?'\n\n"
                f"તમે કઈ માહિતી વિશે જાણવા માંગો છો?"
            )
        elif detected_lang in ["hindi", "hinglish"]:
            return (
                f"Main {c_name} ki official AI Voice Assistant ({agent_display_name}) hoon. Mere paas aapke liye yeh sabhi jaankari aur services available hain:\n\n"
                f"1. 📞 AI Voice Agent & Calling: Natural human voice mein automated customer calling, inbound/outbound calls aur voice assistance.\n"
                f"2. 🏢 Company & Business Details: {c_name} ke business timings, office address, contact number aur company policies.\n"
                f"3. 📚 Knowledge Base & Products: Hamare system mein uploaded product catalogs, services, pricing, manuals aur FAQs ke exact answers.\n"
                f"4. 🌐 Multilingual Support: Hinglish, Hindi, Gujarati aur English mein live dynamic baat-cheet (barge-in interruption ke sath).\n\n"
                f"💡 Aap mujhse yeh sawaal pooch sakte hain:\n"
                f"• '{c_name} ke main features aur demo batao.'\n"
                f"• 'Aapke business timings aur contact details kya hain?'\n"
                f"• 'Voice agent setup aur pricing kya hai?'\n\n"
                f"Aap inme se kiske baare mein jaanna chahte hain?"
            )
        else:
            return (
                f"I am the official AI Voice Assistant ({agent_display_name}) for {c_name}. Here is all the information and capabilities available:\n\n"
                f"1. 📞 AI Voice Agent & Calling: Natural human-sounding automated voice calling and interactive assistance.\n"
                f"2. 🏢 Company & Business Details: {c_name}'s business hours, office location, contact details, and policies.\n"
                f"3. 📚 Knowledge Base & Products: Instant, grounded answers from uploaded product catalogs, services, and FAQs.\n"
                f"4. 🌐 Multilingual Capabilities: Seamless real-time conversations across Hinglish, Hindi, Gujarati, and English.\n\n"
                f"💡 Suggested questions you can ask:\n"
                f"• 'What are the main features and capabilities of {c_name}?'\n"
                f"• 'What are your business hours and contact info?'\n"
                f"• 'How do voice agents work?'\n\n"
                f"Which of these would you like to explore?"
            )

    # ── Agent Setup & Document Upload Workflow Fast Path ──
    setup_pattern = re.compile(
        r"(?:"
        r"(?:kaise|how\s+to|process|tarika|steps?)\s+(?:setup|create|banaye|configure|start|upload)|"
        r"(?:setup|create|banane|upload\s+karke|document\s+upload).*(?:process|tarika|kaise|steps?)|"
        r"how\s+(?:can\s+i|to)\s+(?:setup|create|integrate|configure)\s+(?:voice\s+)?agent"
        r")",
        re.IGNORECASE
    )
    if setup_pattern.search(msg_clean_no_punct):
        logger.info("[PRODUCT_FAST_PATH] topic=agent_setup_workflow matched=true")
        if detected_lang == "gujarati" or detected_script == "gujarati_script":
            return (
                f"{c_name} માં કસ્ટમ AI વોઇસ એજન્ટ સેટઅપ કરવાની સ્ટેપ-બાય-સ્ટેપ પ્રક્રિયા:\n\n"
                f"1. 📄 ડોક્યુમેન્ટ અપલોડ: 'Knowledge Base' માં તમારી કંપનીના PDF, Word અથવા ટેક્સ્ટ ડોક્યુમેન્ટ્સ અપલોડ કરો.\n"
                f"2. 🤖 એજન્ટ ક્રિએશન: 'AI Agents' સેક્શનમાં નવો એજન્ટ બનાવો અને તેને નોલેજ બેઝ સાથે જોડો.\n"
                f"3. 🎙️ વોઇસ પસંદગી: રિતુ, રોહન, કાવ્યા અથવા નેહા જેવા નેચરલ ઇન્ડિયન વોઇસ પર્સના પસંદ કરો.\n"
                f"4. 🚀 લાઈવ ટેસ્ટિંગ: વેબ વોઇસ ચેટ અથવા ટેલિફોની ઇન્ટિગ્રેશન સાથે તરત જ કસ્ટમર કોલિંગ શરૂ કરો.\n\n"
                f"શું તમે નોલેજ બેઝ અપલોડ કરવા વિશે વધુ માહિતી મેળવવા માંગો છો?\n\n"
                f"Suggested questions:\n"
                f"- નોલેજ બેઝ અપલોડ કેવી રીતે કરવું?\n"
                f"- વોઇસ પર્સના કેવી રીતે પસંદ કરવી?"
            )
        elif detected_lang in ["hindi", "hinglish"]:
            return (
                f"{c_name} mein custom AI Voice Agent setup karne ka aasan step-by-step process yeh hai:\n\n"
                f"1. 📄 Documents Upload: 'Knowledge Base' section mein apni company ke PDFs, FAQs ya documentation upload karein. Hamara system inka automatic semantic indexing karta hai.\n"
                f"2. 🤖 Agent Creation: 'AI Agents' tab mein naya agent create karein aur use Knowledge Base se link karein.\n"
                f"3. 🎙️ Voice Persona Selection: 11 distinct natural Indian voices (Ritu, Rohan, Neha, Kavya, Amit) me se suitable voice persona select karein.\n"
                f"4. 🚀 Live Deployment: Web Voice Chat ya Twilio Calling telephony ke zariye agent ko customer calling aur support ke liye live karein.\n\n"
                f"Kya aap kisi specific step ke baare mein vistaar se jaanna chahte hain?\n\n"
                f"Suggested questions:\n"
                f"- Knowledge base mein documents kaise upload karein?\n"
                f"- Voice persona kaise select karein?"
            )
        else:
            return (
                f"Here is the step-by-step process to set up a custom AI Voice Agent on {c_name}:\n\n"
                f"1. 📄 Upload Documents: Go to 'Knowledge Base' and upload your company PDFs, manuals, or FAQs. The system automatically indexes them for semantic retrieval.\n"
                f"2. 🤖 Create Agent: Navigate to 'AI Agents', create your agent, and link it to your Knowledge Base.\n"
                f"3. 🎙️ Choose Voice Persona: Pick from 11 natural Indian voices (Ritu, Rohan, Neha, Kavya, etc.) tailored for your business tone.\n"
                f"4. 🚀 Deploy & Call: Go live with interactive Web Voice Chat or integrate with Twilio for inbound/outbound telephony.\n\n"
                f"Would you like detailed guidance on any of these steps?\n\n"
                f"Suggested questions:\n"
                f"- How do I upload documents to the Knowledge Base?\n"
                f"- How do I create a new AI agent?"
            )

    if z_one_pattern.match(msg_clean_no_punct) or msg_clean_no_punct in ["who are you", "who r u", "what is your name", "tum kaun ho", "tame kon cho", "kon cho"]:
        logger.info("[PRODUCT_FAST_PATH] product=ZeniaOne matched=true llm_called=false rag_called=false source=authoritative_product_profile")
        
        # Override language if explicit markers are present
        if any(w in msg_clean_no_punct for w in ["kya hai", "kya he", "kya karta", "batao", "kaun ho"]):
            detected_lang = "hinglish"
        elif any(w in msg_clean_no_punct for w in ["su che", "su chhe", "kya che", "vishe", "janavo", "tame kon cho", "kon cho"]):
            detected_lang = "gujarati"
            
        if detected_lang == "gujarati" or detected_script == "gujarati_script":
            return (
                "ZeniaOne અમારું અદ્યતન AI-driven વોઇસ એજન્ટ પ્લેટફોર્મ છે જે કુદરતી માનવ અવાજમાં વાતચીત કરે છે.\n\n"
                "અમારી પાસે આ મુખ્ય માહિતી ઉપલબ્ધ છે:\n"
                "1. AI વોઇસ એજન્ટ અને કોલિંગ\n"
                "2. મલ્ટિલિંગ્વલ સપોર્ટ (હિંગ્લિશ, ગુજરાતી, હિન્દી, અંગ્રેજી)\n"
                "3. નોલેજ બેઝ અને ડોક્યુમેન્ટ સર્ચ\n"
                "4. લાઇવ ઇન્ટરપ્શન (બાર્જ-ઇન)\n"
                "5. ટેલિફોની અને સપોર્ટ વર્કફ્લો\n\n"
                "તમે આમાંથી કયા ફીચર વિશે વધુ જાણવા માંગો છો?\n\n"
                "Suggested questions:\n"
                "- લાઇવ બાર્જ-ઇન શું છે?\n"
                "- ટેલિફોની કેવી રીતે કામ કરે છે?"
            )
        elif detected_lang in ["hindi", "hinglish"]:
            return (
                "ZeniaOne hamara primary AI-driven voice agent platform hai jo natural human sound mein customer calls aur support handle karta hai.\n\n"
                "Mere paas yeh sab details available hain:\n"
                "1. AI Voice Agent & Calling\n"
                "2. Multilingual Support (Hinglish, Gujarati, Hindi, English)\n"
                "3. Knowledge Base & Document Search\n"
                "4. Live Interruption & Barge-in\n"
                "5. Telephony & Support Workflows\n\n"
                "Aap inme se kiske baare mein vistaar se jaanna chahte hain?\n\n"
                "Suggested questions:\n"
                "- Live barge-in kya hai?\n"
                "- Telephony workflow samjhao"
            )
        else:
            return (
                "ZeniaOne is our primary AI-driven voice agent platform that handles customer interactions in a natural human voice.\n\n"
                "I have the following topics available:\n"
                "1. AI Voice Agent & Calling\n"
                "2. Multilingual Support (Hinglish, Gujarati, Hindi, English)\n"
                "3. Knowledge Base & Document Search\n"
                "4. Live Barge-in & Interruption\n"
                "5. Telephony & Support Workflows\n\n"
                "Which of these would you like to know more about?\n\n"
                "Suggested questions:\n"
                "- What is live barge-in?\n"
                "- Explain telephony workflows"
            )
            
    if z_hr_pattern.match(msg_clean_no_punct):
        logger.info("[PRODUCT_FAST_PATH] product=ZeniaHR matched=true llm_called=false rag_called=false source=authoritative_product_profile")
        if detected_lang in ["hindi", "hinglish"]:
            return "ZeniaHR ek comprehensive human resources management product hai. Yeh attendance tracking, payroll, aur policies ko manage karne mein madad karta hai."
        else:
            return "ZeniaHR is a comprehensive human resources management product. It streamlines attendance tracking, payroll processing, and policy management."
            
    # ── GUARD: Do not use simple topic fast-paths for relationship/comparison/detailed questions ──
    has_detail_intent = any(pat in msg_clean_no_punct for pat in [
        "relationship", "relation", "difference", "differences", "connect", "connected", "aur", "se kya", "between",
        "step", "steps", "detail", "details", "process", "workflow", "feature", "features", "options", "rule", "rules",
        "kaise", "samjhao", "batao", "list", "push to", "pf", "esic", "pt", "tds", "gst"
    ])
            
    # Deterministic Cache for high-frequency queries
    if not has_detail_intent and "attendance" in msg_clean_no_punct and ("what is" in msg_clean_no_punct or "kya hai" in msg_clean_no_punct):
        logger.info("[PRODUCT_FAST_PATH] topic=attendance matched=true")
        if detected_lang in ["hindi", "hinglish"]:
            return "Attendance module aapko employees ki in aur out timings track karne, leaves manage karne, aur working hours monitor karne ki suvidha deta hai."
        else:
            return "The attendance module allows you to track employee clock-in and clock-out times, manage leaves, and monitor total working hours."
            
    if not has_detail_intent and "payroll" in msg_clean_no_punct and ("what is" in msg_clean_no_punct or "kya hai" in msg_clean_no_punct or "kaise work karta hai" in msg_clean_no_punct):
        logger.info("[PRODUCT_FAST_PATH] topic=payroll matched=true")
        if detected_lang in ["hindi", "hinglish"]:
            return "Payroll module employees ki salary, taxes, deductions, aur bonuses ko calculate aur process karne ka kaam karta hai, taaki salary payment automated ho sake."
        else:
            return "The payroll module automatically calculates and processes employee salaries, taxes, deductions, and bonuses to streamline payments."


    # ── Settings-based Metadata Fast Paths ────────────────────────────────────
    
    # ADDRESS
    if not is_profile_query and settings.get("address"):
        _ADDRESS_RE = re.compile(
            r"""
            ^
            (?:
                (?:what(?:'?s)?|whats|tell\s+me|bata(?:\s+do)?|where(?:'?s)?)\s+
                (?:(?:is|are)\s+)?
                (?:(?:your|ur|aapka|aapki|apki|apna|apni|tamari|aa|the|this|this\s+company(?:s)?)\s+)?
            )?
            (?:address|location|headquarters|hq|city|state|postal\s+code)
            (?:
                \s+(?:kya\s+hai|shu\s+che|che|hai|kaha\s+hai|kahan\s+hai|he|su\s+che)
            |
                \s+are\s+you\s+(?:located|based)
            |
                \s+is\s+(?:it|the\s+company)\s+(?:located|based)
            )?
            $
            |
            ^where\s+are\s+you\s+(?:located|situated|based)$
            |
            ^where\s+is\s+(?:it|the\s+company)$
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _ADDRESS_RE.match(msg_clean_no_punct):
            is_profile_query = True
            if detected_lang in ["hindi", "hinglish"]:
                profile_response = f"Hamara address hai: {settings['address']}"
            elif detected_lang == "gujarati":
                profile_response = f"Amaru address chhe: {settings['address']}"
            else:
                profile_response = f"Our address is: {settings['address']}"

    # PHONE
    if not is_profile_query and settings.get("phone"):
        _PHONE_RE = re.compile(
            r"""
            ^
            (?:(?:what(?:'?s)?|whats|tell\s+me|bata(?:\s+do)?)\s+(?:(?:is)\s+)?)?
            (?:(?:your|ur|aapka|aapki|apki|apna|apni|tamaro|aa|the|this\s+company(?:s)?)\s+)?
            (?:phone(?:|s)|phone\s+number(?:s)?|contact(?:|s)|contact\s+number(?:s)?|mobile(?:|s)|whatsapp(?:|s)|whatsapp\s+number)
            (?:
                \s+(?:kya\s+hai|shu\s+che|che|hai|su\s+che)
            |
                \s+is
            )?
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _PHONE_RE.match(msg_clean_no_punct):
            is_profile_query = True
            if detected_lang in ["hindi", "hinglish"]:
                profile_response = f"Aap hume is number par contact kar sakte hain: {settings['phone']}"
            elif detected_lang == "gujarati":
                profile_response = f"Tame amne aa number par sampark kari shako chho: {settings['phone']}"
            else:
                profile_response = f"You can contact us at: {settings['phone']}"

    # EMAIL
    if not is_profile_query and settings.get("business_email"):
        _EMAIL_RE = re.compile(
            r"""
            ^
            (?:(?:what(?:'?s)?|whats|tell\s+me|bata(?:\s+do)?)\s+(?:(?:is)\s+)?)?
            (?:(?:your|ur|aapka|aapki|apki|apna|apni|tamaro|aa|the|this\s+company(?:s)?)\s+)?
            (?:email|email\s+address|email\s+id)
            (?:
                \s+(?:kya\s+hai|shu\s+che|che|hai|su\s+che)
            |
                \s+is
            )?
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _EMAIL_RE.match(msg_clean_no_punct):
            is_profile_query = True
            if detected_lang in ["hindi", "hinglish"]:
                profile_response = f"Hamara email address hai: {settings['business_email']}"
            elif detected_lang == "gujarati":
                profile_response = f"Amaru email address chhe: {settings['business_email']}"
            else:
                profile_response = f"Our email address is: {settings['business_email']}"

    # WEBSITE
    if not is_profile_query and settings.get("website"):
        _WEBSITE_RE = re.compile(
            r"""
            ^
            (?:(?:what(?:'?s)?|whats|tell\s+me|bata(?:\s+do)?)\s+(?:(?:is)\s+)?)?
            (?:(?:your|ur|aapka|aapki|apki|apna|apni|tamari|aa|the|this\s+company(?:s)?)\s+)?
            (?:website|site|url|web\s+address)
            (?:
                \s+(?:kya\s+hai|shu\s+che|che|hai|su\s+che)
            |
                \s+is
            )?
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _WEBSITE_RE.match(msg_clean_no_punct):
            is_profile_query = True
            if detected_lang in ["hindi", "hinglish"]:
                profile_response = f"Hamari website hai: {settings['website']}"
            elif detected_lang == "gujarati":
                profile_response = f"Amari website chhe: {settings['website']}"
            else:
                profile_response = f"Our website is: {settings['website']}"

    # DESCRIPTION / ABOUT
    desc = settings.get("description") or company.get("description")
    if not is_profile_query and desc:
        _DESC_RE = re.compile(
            r"""
            ^
            (?:
                (?:what(?:\s+does)?|what\s+do|how\s+does)\s+
                (?:(?:your|the|this|aa)\s+)?
                (?:company|business)\s+
                (?:do|make|karti\s+hai|kare\s+chhe)
            |
                (?:(?:what(?:'?s)?|whats|tell\s+me|bata(?:\s+do)?|about)\s+)?
                (?:(?:your|ur|the|this|aa)\s+)?
                (?:company|business)\s+
                (?:description|profile|info(?:rmation)?|kya\s+karti\s+hai|shu\s+kare\s+che|kya\s+hai|shu\s+che)
            |
                what\s+services\s+do\s+you\s+provide
            |
                what\s+do\s+you\s+do
            |
                company\s+kya\s+karti\s+hai
            |
                company\s+shu\s+kare\s+chhe
            |
                business
            |
                about\s+company
            )
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _DESC_RE.match(msg_clean_no_punct):
            is_profile_query = True
            profile_response = desc

    # BUSINESS HOURS
    if not is_profile_query and settings.get("business_hours"):
        _HOURS_RE = re.compile(
            r"""
            ^
            (?:
                (?:(?:what|which)\s+(?:time|days?)|when)\s+
                (?:are\s+you\s+)?
                (?:open|closed)
            |
                (?:(?:your|ur|the|this\s+company(?:s)?)\s+)?
                (?:business\s+hours|timings?|hours|office\s+time|opening\s+hours|closing\s+hours|working\s+hours)
                (?:\s+(?:kya\s+hai|shu\s+che|che|hai|su\s+che))?
            |
                (?:time\s+kya\s+hai|kab\s+open\s+hota\s+hai|office\s+kab\s+khulta\s+hai|office\s+kab\s+band\s+hota\s+hai|kitni\s+din\s+close\s+rehta(?:he|hai))
            |
                (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:ka|no|nu|ni|ko|morning|evening|afternoon))?
            )
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _HOURS_RE.match(msg_clean_no_punct):
            is_profile_query = True
            profile_response = format_business_hours(settings['business_hours'], detected_lang, detected_script)

    # LANGUAGES
    lang_info = settings.get("supported_languages") or settings.get("default_language")
    if not is_profile_query and lang_info:
        _LANG_RE = re.compile(
            r"""
            ^
            (?:
                (?:what|which|how\s+many)\s+
                (?:languages?|bhasha)
                (?:
                    \s+do\s+you\s+(?:support|speak|know)
                |
                    \s+are\s+supported
                |
                    \s+(?:support\s+karte\s+ho|support\s+karo\s+cho)
                )?
            |
                (?:supported\s+languages?)
            |
                (?:languages?)
                (?:\s+(?:supported|kya\s+hai|shu\s+che|che|hai))?
            )
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _LANG_RE.match(msg_clean_no_punct):
            is_profile_query = True
            profile_response = f"We support the following languages: {lang_info}"

    # POLICIES
    if not is_profile_query:
        for policy_key in ["refund_policy", "cancellation_policy", "privacy_policy", "return_policy", "employee_leave_policy"]:
            if settings.get(policy_key):
                clean_key = policy_key.replace("_", " ")
                if clean_key in msg_clean_no_punct or clean_key.replace(" policy", "") in msg_clean_no_punct:
                    is_profile_query = True
                    profile_response = settings[policy_key]
                    break
    
    # ── Regex-based fuzzy matching for direct company metadata ────────────────
    # Runs independently (not as elif) so it catches queries even when the
    # message doesn't match the exact-string timings/hours checks above.
    #
    # Pattern strategy:
    #   - Allow common question prefixes (what is, what's, whats, tell me, bata do …)
    #   - Allow filler words (your, ur, aapka, apki, aapki, aa, tamari, …)
    #   - Allow TYPOS in "company" → comp?a?n?y? fuzzy, and "name" → na?m?e?
    #   - Cover Hinglish & Roman Gujarati equivalents
    #   - Avoid matching broad phrases like "what is your refund policy"

    if not is_profile_query and company and company.get("name"):
        # Fuzzy "company name" detector
        # Matches: company name, compny name, company ka naam, company nu naam shu che,
        #          what is company name, what is ur compny nam, aapki company ka naam kya hai, etc.
        _COMPANY_NAME_RE = re.compile(
            r"""
            (?:                         # optional question prefix
                (?:what(?:'?s)?|whats|bata(?:\s+do)?|tell\s+me|what\s+is|batao|batavo)
                \s+
                (?:(?:is|are|your|ur|aapka|aapki|apki|apna|apni|tamari|aa|tari)\s+)?
            )?
            (?:                         # fuzzy "company" — allow 1–2 dropped vowels
                comp(?:a?n?y?|nay?|eny?|ony?)
                |business
                |vyavsay                # Hindi
                |dhandha                # Hindi/Gujarati colloquial
                |aapki\s+comp\w*        # Hinglish possessive
            )
            (?:                         # optional connector (ka, nu, ki, …)
                \s+(?:ka|ki|nu|na|no|da|di|of)\s+
                |\s+
            )
            (?:                         # fuzzy "name" — allow dropped vowels
                na?m?e?
                |naam
                |nam
                |naaam
                |name\s+(?:kya\s+hai|shu\s+che|che|hai)
                |naam\s+(?:kya\s+hai|shu\s+che|che|hai|bata)
            )
            (?:                         # optional suffix (kya hai, shu che, ?)
                \s*(?:\?|kya\s+hai|shu\s+che|che|hai|batao|batavo)?
            )?
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _COMPANY_NAME_RE.fullmatch(msg_clean_no_punct.strip()) or \
           _COMPANY_NAME_RE.search(msg_clean_no_punct) and len(msg_clean_no_punct.split()) <= 10:
            is_profile_query = True
            if detected_script == "devanagari":
                profile_response = f"व्यवसाय का नाम {c_name} है।"
            elif detected_script == "gujarati_script":
                profile_response = f"બિઝનેસનું નામ {c_name} છે."
            elif detected_lang in ["hindi", "hinglish"]:
                profile_response = f"Business ka naam {c_name} hai."
            elif detected_lang == "gujarati":
                profile_response = f"Business nu naam {c_name} chhe."
            else:
                profile_response = f"The company name is {c_name}."

    if not is_profile_query and company and company.get("industry"):
        # Matches all natural variations of industry questions.
        # Key gaps fixed vs previous version:
        #   - "what is your industry" (prefix: what is)
        #   - "what industry are you in" (keyword in middle)
        #   - "aap kis industry mein ho" (Hinglish)
        #   - "company nu industry shu che" (Gujarati)
        _INDUSTRY_RE = re.compile(
            r"""
            ^
            (?:
                # English patterns with keyword in middle or end
                (?:what(?:\s+is)?(?:'?s)?|whats|which)
                \s+
                (?:(?:your|ur|the|this\s+company['']?s?)\s+)?
                industry
                (?:\s+(?:are\s+you\s+(?:in|part\s+of)|is\s+this|do\s+you\s+work\s+in))?
            |
                # Short forms: "your industry", "industry"
                (?:(?:your|ur|aapki?|apki?|tamari|aa\s+company(?:\s+ni)?)\s+)?
                industry
                (?:\s+(?:kya\s+hai|shu\s+che|che|hai))?
            |
                # Hinglish: "aap kis industry mein ho"
                aap\s+kis\s+industry\s+(?:mein|me|mai)\s+(?:ho|hain|hai)
            |
                # Gujarati: "company nu industry shu che"
                (?:company\s+(?:nu|ni|na|no)\s+)?industry\s+(?:shu\s+che|che|shun\s+chhe)
            |
                # Hindi: "kya industry hai"
                (?:kya\s+)?(?:aapki|apki)\s+industry\s+(?:hai|kya\s+hai)
            |
                # Tell/bata variants
                (?:tell\s+me|bata(?:o|vo)?)\s+(?:(?:your|ur|aapki?)\s+)?industry
            )
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _INDUSTRY_RE.match(msg_clean_no_punct):
            is_profile_query = True
            ind = company["industry"]
            if detected_script == "devanagari":
                profile_response = f"हम {ind} इंडस्ट्री में काम करते हैं।"
            elif detected_script == "gujarati_script":
                profile_response = f"અમે {ind} ઇન્ડસ્ટ્રીમાં કામ કરીએ છીએ."
            elif detected_lang in ["hindi", "hinglish"]:
                profile_response = f"Aapki company ki industry {ind} hai."
            elif detected_lang == "gujarati":
                profile_response = f"Company ni industry {ind} chhe."
            else:
                profile_response = f"The industry is {ind}."

    if not is_profile_query and company and company.get("country"):
        # Expand ISO-2 country codes to full names for readable answers
        _ISO2_NAMES = {
            "IN": "India", "US": "United States", "GB": "United Kingdom",
            "AU": "Australia", "CA": "Canada", "SG": "Singapore",
            "AE": "United Arab Emirates", "DE": "Germany", "FR": "France",
            "NZ": "New Zealand", "ZA": "South Africa", "NL": "Netherlands",
        }
        raw_country = company["country"]
        country_display = _ISO2_NAMES.get(raw_country.upper(), raw_country) if len(raw_country) <= 3 else raw_country

        # Matches all natural country-query variations.
        # Key gaps fixed vs previous version:
        #   - "what country are you based in" (suffix "are you based in")
        #   - "which country are you in" (which + suffix)
        #   - "country kaha hai" (Hinglish)
        #   - "aap kis country mein ho" (Hinglish)
        #   - "company nu country shu che" (Gujarati)
        _COUNTRY_RE = re.compile(
            r"""
            ^
            (?:
                # "what/which country are you [based] in/from"
                (?:what|which)\s+country\s+(?:are\s+you\s+(?:based\s+)?(?:in|from)|is\s+this)
            |
                # "where are you based/from"
                where\s+are\s+you\s+(?:based|from)
            |
                # Short: "your country", "country"
                (?:(?:your|ur|aapka|aapki?|apki?|tamaro|tamara|aa\s+company(?:\s+no)?)\s+)?
                country
                (?:\s+(?:kya\s+hai|shu\s+che|che|hai|kaha\s+hai|kahan\s+hai))?
            |
                # Hinglish: "aap kis country mein ho" / "country kaha hai"
                aap\s+kis\s+country\s+(?:mein|me|mai)\s+(?:ho|hain|hai)
                | country\s+(?:kaha|kahan)\s+(?:hai|he)
                | kaha\s+(?:based|se)\s+(?:ho|hain|hai)
            |
                # Gujarati: "company nu country shu che"
                (?:company\s+(?:nu|ni|na|no)\s+)?country\s+(?:shu\s+che|che|shun\s+chhe)
            |
                # Tell/bata variants
                (?:tell\s+me|bata(?:o|vo)?)\s+(?:(?:your|ur|aapka?)\s+)?country
            )
            $
            """,
            re.VERBOSE | re.IGNORECASE,
        )
        if _COUNTRY_RE.match(msg_clean_no_punct):
            is_profile_query = True
            if detected_script == "devanagari":
                profile_response = f"हम {country_display} में स्थित हैं।"
            elif detected_script == "gujarati_script":
                profile_response = f"અમે {country_display} માં સ્થિત છીએ."
            elif detected_lang in ["hindi", "hinglish"]:
                profile_response = f"Aapki company {country_display} mein based hai."
            elif detected_lang == "gujarati":
                profile_response = f"Company {country_display} ma based chhe."
            else:
                profile_response = f"We are based in {country_display}."
    
    # Regex-based descriptive/founder queries
    if not is_profile_query:
        c_name_lower = c_name.lower()
        desc_pattern = rf"^(?:{re.escape(c_name_lower)}\s+)?(what is|who are you|company description|kya hai|what is this|about company)(?:\s+{re.escape(c_name_lower)})?$"
        if re.match(desc_pattern, msg_clean_no_punct) and company.get("description"):
            is_profile_query = True
            profile_response = company.get("description")
            
        founder_pattern = rf"^(?:{re.escape(c_name_lower)}\s+)?(who developed|who created|kisne banaya|kisne develop kiya|founder|creator)(?:\s+{re.escape(c_name_lower)}|.*)?$"
        if re.match(founder_pattern, msg_clean_no_punct):
            is_profile_query = True
            founder_info = settings.get("founder") or "ZeniaOne AI Platform"
            profile_response = f"{c_name} is powered by {founder_info}."

    is_capability_query = msg_clean_no_punct in ["what can you help me with", "what can you do", "help me", "how can you help", "what are your capabilities", "mujhe kya help kar sakte ho"]

    if is_profile_query:
        logger.info("[COMPANY_SETTINGS_FAST_PATH] field=company_metadata source=company_settings")
        return profile_response
        
    elif is_capability_query:
        if detected_script == "devanagari":
            return f"मैं {c_name} की ओर से आपकी मदद के लिए यहाँ हूँ। मैं आपको हमारे बारे में जानकारी देने, आपके सवालों के जवाब देने और सपोर्ट में मदद कर {dev_help} हूँ।"
        elif detected_script == "gujarati_script":
            return f"હું {c_name} તરફથી તમારી મદદ માટે અહી છું. હું તમને અમારા વિશે માહિતી આપવામાં, તમારા પ્રશ્નોના જવાબ આપવામાં અને સપોર્ટમાં મદદ કરી શકું છું."
        elif detected_lang in ["hindi", "hinglish"]:
            return f"Main {c_name} ki taraf se aapki madad ke liye yahan hoon. Main aapko hamare baare mein jaankari dene, aapke sawalon ke jawab dene aur support mein madad kar {help_verb} hoon."
        elif detected_lang == "gujarati":
            return f"Hu {c_name} taraf thi tamari madad mate ahi chu. Hu tamne amara vishe mahiti aavpa ma, tamara prashno na javab aavpa ma ane support ma madad kari shaku chu."
        else:
            return f"I'm here to help you with {c_name}. I can provide information about our business, answer your questions, and assist with support."
            
    elif is_hear_me:
        if detected_script == "devanagari":
            return f"हाँ बिल्कुल! मैं आपको अच्छी तरह सुन पा {dev_hear} हूँ। कहिए, मैं आपकी क्या मदद कर {dev_help} हूँ?"
        elif detected_script == "gujarati_script":
            return "હા ચોક્કસ! હું તમને બરાબર સાંભળી શકું છું. કહો, હું તમારી શી મદદ કરી શકું?"
        elif detected_lang in ["hindi", "hinglish"]:
            return f"Haan bilkul! Main aapko ache se sun {hear_verb} hoon. Kahiye, main aapki kya help kar {help_verb} hoon?"
        elif detected_lang == "gujarati":
            return "Ha bilkul! Hu tamne barabar sambhli shaku chu. Kaho, hu tamari shu madad kari shaku?"
        else:
            return "Yes, I can hear you clearly! How can I help you today?"

    elif is_greeting or is_how_are_you or is_thanks:
        # Override name if this is the internal admin workspace but a custom customer agent
        if c_name == "ZeniaOne" and agent.get("agent_type") != "platform_admin":
            c_name = agent.get("name", "our company").replace(" Agent", "").replace("ZeniaAI", "ZeniaOne").replace("Zenia AI", "ZeniaOne").strip() or "our company"
        
        if is_how_are_you:
            if detected_script == "devanagari":
                return f"मैं बिल्कुल ठीक और बढ़िया हूँ, धन्यवाद! आप बताइए, आप कैसे हैं? आज मैं आपकी क्या मदद कर {dev_help} हूँ?"
            elif detected_script == "gujarati_script":
                return "હું એકદમ મજામાં છું, આભાર! તમે કેમ છો? આજે હું તમારી શું મદદ કરી શકું?"
            elif detected_lang in ["hindi", "hinglish"]:
                return f"Main bilkul badhiya hoon, shukriya! Aap bataiye aap kaise hain? Main aapki kya madad kar {help_verb} hoon?"
            elif detected_lang == "gujarati":
                return "Hu ekdam majama chu, aabhar! Tame kem cho? Hu tamari shu madad kari shaku?"
            else:
                return "I'm doing great, thank you! How are you doing today? How can I help you?"
                
        elif is_thanks:
            if detected_script == "devanagari":
                return "आपका बहुत-बहुत स्वागत है! कोई और बात हो या सवाल हो तो बेझिझक पूछिए, मुझे आपकी मदद करके खुशी होगी।"
            elif detected_script == "gujarati_script":
                return "તમારું ખૂબ ખૂબ સ્વાગત છે! બીજું કંઈ પૂછવું હોય તો ચોક્કસ જણાવો, તમારી મદદ કરીને મને આનંદ થશે."
            elif detected_lang in ["hindi", "hinglish"]:
                return "Aapka bohot-bohot swagat hai! Aur kuch poochna ho ya koi bhi madad chahiye ho toh zaroor batayein."
            elif detected_lang == "gujarati":
                return "Tamaru khub swagat chhe! Biju kai puchvu hoy to zaroor batavo."
            else:
                return "You're most welcome! Feel free to ask if you need any other help."
                
        else: # is_greeting
            if detected_script == "devanagari":
                return f"नमस्ते! कहिए, आज मैं आपकी किस तरह मदद कर {dev_help} हूँ?"
            elif detected_script == "gujarati_script":
                return "નમસ્તે! કહો, આજે હું તમારી શું મદદ કરી શકું?"
            elif detected_lang in ["hindi", "hinglish"]:
                return f"Namaste! Kahiye, main aapki kya help kar {help_verb} hoon?"
            elif detected_lang == "gujarati":
                return "Namaste! Kaho, hu tamari shu madad kari shaku?"
            else:
                return "Hello! How can I help you today?"
                
    return None
