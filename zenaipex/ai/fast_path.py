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
    detected_script: str
) -> Optional[str]:
    """
    Checks if a user message can be answered deterministically from the company profile
    or as a basic social greeting, bypassing LLM generation and RAG entirely.
    """
    import string
    msg_clean = message.lower().strip()
    msg_clean_no_punct = msg_clean.translate(str.maketrans('', '', string.punctuation)).strip()
    
    # Use regex to handle repeated characters like hiiii, heyyy, hellooo without false positives
    # Expanded with Indian greetings per user request
    is_greeting = bool(re.match(r"^(h[iy]+|he+l+o+|he+y+|h[iy]+\s+there|good\s+(morning|afternoon|evening)|namaste|kem\s*cho|नमस्कार|નમસ્તે)$", msg_clean_no_punct))
    is_how_are_you = msg_clean_no_punct in ["how are you", "how r u", "how are u", "kaise ho", "kese ho", "kaise ho aap", "kese ho aap", "kese ho app", "kaise ho app", "kem cho", "kem chho", "kem cho tame", "kem cho tamne", "kema cho tame", "kem chho tame", "tame kem cho", "tame kem chho"]
    is_thanks = msg_clean_no_punct in ["thanks", "thank you", "dhanyawad", "shukriya", "aabhar", "આભાર", "धन्यवाद"]
    
    c_name = company.get("name", "our company") if company else "our company"
    if c_name.upper() == "INTERNAL / PLATFORM" or c_name == "ZeniaAI Internal Workspace":
        c_name = "ZeniaOne"
    
    settings = company.get("settings", {}) if company else {}
    
    is_profile_query = False
    profile_response = None
    
    # ── Product Overview Fast Paths ───────────────────────────────────────────
    _z_names = r"(?:zeniaone|zinnia one|zenia one|zenya one|zeniaai|zenia ai|zeniya one|zeniya ai|zene one|zene ai|you|the\s+platform)"
    z_one_pattern = re.compile(
        rf"^(what(?:\s+is|'?s)?|tell\s+me\s+(?:more\s+)?about|explain|who\s+are\s+you|who\s+r\s+u|kon\s+cho)\s+{_z_names}$|"
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

    if z_one_pattern.match(msg_clean_no_punct) or msg_clean_no_punct in ["who are you", "who r u", "what is your name", "tum kaun ho", "tame kon cho", "kon cho"]:
        logger.info("[PRODUCT_FAST_PATH] product=ZeniaOne matched=true llm_called=false rag_called=false source=authoritative_product_profile")
        if detected_script == "devanagari":
            return "ZeniaOne हमारा प्राइमरी AI-driven वॉयस एजेंट प्लेटफॉर्म है। यह कस्टमर इंटरैक्शन को कन्वर्सेशनल AI के ज़रिए हैंडल करने, सपोर्ट स्केल करने और टेलीफोनी वर्कफ़्लो को ऑटोमेट करने के लिए बनाया गया है। क्या आप ZeniaOne के फीचर्स के बारे में और जानना चाहेंगे?"
        elif detected_script == "gujarati_script":
            return "ZeniaOne અમારું પ્રાઇમરી AI-driven વોઇસ એજન્ટ પ્લેટફોર્મ છે. આ કસ્ટમર ઇન્ટરેક્શન્સ ને કન્વર્સેશનલ AI થી હેન્ડલ કરવા, સપોર્ટ સ્કેલ કરવા અને ટેલિફોની વર્કફ્લોઝ ઓટોમેટ કરવા માટે બનાવેલું છે. શું તમે ZeniaOne ના ફીચર્સ વિશે વધુ જાણવા માંગો છો?"
        elif detected_lang == "gujarati":
            return "ZeniaOne amaru primary AI-driven voice agent platform che. Aa customer interactions ne conversational AI thi handle karva, support scale karva ane telephony workflows automate karva mate banavelu che. Shu tame ZeniaOne na features vishe vadhu janva mango cho?"
        elif detected_lang in ["hindi", "hinglish"]:
            return "ZeniaOne hamara primary AI-driven voice agent platform hai. Yeh customer interactions ko conversational AI ke zariye handle karne, support scale karne aur telephony workflows ko automate karne ke liye banaya gaya hai. Kya aap ZeniaOne ke features ke baare mein aur jaanna chahenge?"
        else:
            return "ZeniaOne is our primary AI-driven voice agent platform. It provides conversational AI capabilities to handle customer interactions, scale support, and automate telephony workflows effortlessly. Would you like to know more about ZeniaOne's features?"
            
    if z_hr_pattern.match(msg_clean_no_punct):
        logger.info("[PRODUCT_FAST_PATH] product=ZeniaHR matched=true llm_called=false rag_called=false source=authoritative_product_profile")
        if detected_lang in ["hindi", "hinglish"]:
            return "ZeniaHR ek comprehensive human resources management product hai. Yeh attendance tracking, payroll, aur policies ko manage karne mein madad karta hai."
        else:
            return "ZeniaHR is a comprehensive human resources management product. It streamlines attendance tracking, payroll processing, and policy management."
            
    # ── GUARD: Do not use simple topic fast-paths for relationship/comparison questions ──
    is_relationship = False
    for pat in ["relationship", "relation", "difference", "differences", "connect", "connected", "aur", "se kya", "between"]:
        if pat in msg_clean_no_punct:
            is_relationship = True
            break
            
    # Deterministic Cache for high-frequency queries
    if not is_relationship and "attendance" in msg_clean_no_punct and ("what is" in msg_clean_no_punct or "kya hai" in msg_clean_no_punct):
        logger.info("[PRODUCT_FAST_PATH] topic=attendance matched=true")
        if detected_lang in ["hindi", "hinglish"]:
            return "Attendance module aapko employees ki in aur out timings track karne, leaves manage karne, aur working hours monitor karne ki suvidha deta hai."
        else:
            return "The attendance module allows you to track employee clock-in and clock-out times, manage leaves, and monitor total working hours."
            
    if not is_relationship and "payroll" in msg_clean_no_punct and ("what is" in msg_clean_no_punct or "kya hai" in msg_clean_no_punct or "kaise work karta hai" in msg_clean_no_punct):
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
            return f"मैं {c_name} की ओर से आपकी मदद के लिए यहाँ हूँ। मैं आपको हमारे बारे में जानकारी देने, आपके सवालों के जवाब देने और सपोर्ट में मदद कर सकता हूँ।"
        elif detected_script == "gujarati_script":
            return f"હું {c_name} તરફથી તમારી મદદ માટે અહી છું. હું તમને અમારા વિશે માહિતી આપવામાં, તમારા પ્રશ્નોના જવાબ આપવામાં અને સપોર્ટમાં મદદ કરી શકું છું."
        elif detected_lang in ["hindi", "hinglish"]:
            return f"Main {c_name} ki taraf se aapki madad ke liye yahan hoon. Main aapko hamare baare mein jaankari dene, aapke sawalon ke jawab dene aur support mein madad kar sakta hoon."
        elif detected_lang == "gujarati":
            return f"Hu {c_name} taraf thi tamari madad mate ahi chu. Hu tamne amara vishe mahiti aavpa ma, tamara prashno na javab aavpa ma ane support ma madad kari shaku chu."
        else:
            return f"I'm here to help you with {c_name}. I can provide information about our business, answer your questions, and assist with support."
            
    elif is_greeting or is_how_are_you or is_thanks:
        # Override name if this is the internal admin workspace but a custom customer agent
        if c_name == "ZeniaOne" and agent.get("agent_type") != "platform_admin":
            c_name = agent.get("name", "our company").replace(" Agent", "").replace("ZeniaAI", "ZeniaOne").replace("Zenia AI", "ZeniaOne").strip() or "our company"
        
        if is_how_are_you:
            if detected_script == "devanagari":
                return f"मैं ठीक हूँ, धन्यवाद! आप {c_name} के बारे में क्या जानना चाहेंगे?"
            elif detected_script == "gujarati_script":
                return f"હું મજામાં છું, આભાર! તમે {c_name} વિશે શું જાણવા માંગો છો?"
            elif detected_lang in ["hindi", "hinglish"]:
                return f"Main theek hoon, shukriya! Aap {c_name} ke baare mein kya jaanna chahenge?"
            elif detected_lang == "gujarati":
                return f"Hu majama chu, aabhar! Tame {c_name} vishe shu janva mango cho?"
            else:
                return f"I'm doing well, thank you! What would you like to know about {c_name}?"
                
        elif is_thanks:
            if detected_script == "devanagari":
                return "आपका स्वागत है! कोई और सवाल हो तो ज़रूर पूछें।"
            elif detected_script == "gujarati_script":
                return "તમારો આભાર! બીજું કંઈ જાણવું હોય તો કહો."
            elif detected_lang in ["hindi", "hinglish"]:
                return "Aapka swagat hai! Koi aur sawal ho toh zaroor poochein."
            elif detected_lang == "gujarati":
                return "Tamaro aabhar! Biju kai janvu hoy to kaho."
            else:
                return "You're welcome! Let me know if you have any other questions."
                
        else: # is_greeting
            if detected_script == "devanagari":
                return f"नमस्ते! आप {c_name} के बारे में क्या जानना चाहेंगे?"
            elif detected_script == "gujarati_script":
                return f"નમસ્તે! તમે {c_name} વિશે શું જાણવા માંગો છો?"
            elif detected_lang in ["hindi", "hinglish"]:
                return f"Hello! Aap {c_name} ke baare mein kya jaanna chahenge?"
            elif detected_lang == "gujarati":
                return f"Namaste! Tame {c_name} vishe shu janva mango cho?"
            else:
                return f"Hello! What would you like to know about {c_name}?"
                
    return None
