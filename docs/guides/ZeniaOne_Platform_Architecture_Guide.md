# ZeniaOne Platform Comprehensive Guide & Architecture

## 1. Platform Overview
ZeniaOne is a cutting-edge, enterprise-grade AI Voice Agent and Telephony SaaS platform. It enables businesses, retail stores, and service companies to deploy autonomous AI agents capable of natural human-like voice conversations, instant appointment bookings, payment follow-ups, and 24/7 customer support.

The platform provides end-to-end multi-tenant isolation, real-time barge-in (natural interruption handling), sub-second latency, and native Indian multilingual capabilities across English, Hindi, Hinglish, and Gujarati.

---

## 2. Core Sidebar Navigation & Platform Modules

### 📊 Dashboard & Analytics
The central cockpit for monitoring business performance and call metrics:
- **Total Calls & Minutes:** Live tracking of daily and monthly inbound and outbound call volume.
- **Resolution Rate:** Percentage of customer queries successfully resolved without human intervention.
- **Latency & Performance:** Real-time monitoring of STT (Speech-to-Text), LLM generation, and TTS (Text-to-Speech) latency.
- **Token & Cost Accounting:** Live tracking of API credit usage, tokens consumed, and telephony spend.

### 🤖 AI Agents Management
Create and customize autonomous voice personas tailored to your industry:
- **Voice Personas:** Select from 11 natural Indian voices including Ritu, Rohan, Neha, Kavya, Amit, and Kabir.
- **System Prompts & Behavior:** Configure agent greeting, role-specific instructions, negotiation limits, and brand guidelines.
- **Language Preferences:** Configure native support for English, Hindi, Hinglish, and Gujarati with automatic language switching.
- **Model Tuning:** Adjust temperature, maximum response length, and responsiveness.

### 📚 Knowledge Base & Semantic Indexing
Turn any company document into instant, grounded AI intelligence:
- **Supported Formats:** Upload PDFs, Word documents (.docx), Markdown (.md), and plain text (.txt).
- **Universal Semantic Chunker:** Automatically breaks documents into contextual sections, sub-sections, and tables while preserving hierarchical meaning.
- **Zero Hallucination Retrieval:** Agents only answer based on verified, uploaded documents and company settings.
- **Document Versioning:** Instant re-indexing and document status monitoring.

### 📞 Telephony & Call Automation
Enterprise telephony infrastructure powered by Twilio:
- **Inbound Calling:** Virtual phone numbers that answer incoming customer inquiries 24/7.
- **Outbound Auto-Dialer:** Automated calling campaigns for appointment confirmations, payment reminders, and lead follow-ups.
- **Barge-In (Interruption Handling):** Allows customers to interrupt the AI agent mid-sentence naturally, just like speaking with a human.
- **Live Call Audio & Waveform:** Listen to past call recordings with interactive audio playback.

### 💬 Conversations & Live Transcripts
Comprehensive audit trail for every customer conversation:
- **Full Transcripts:** Accurate bilingual transcripts formatted line-by-line.
- **Sentiment & Intent Analysis:** Automatically detects whether the customer was satisfied, interested, or required follow-up.
- **One-Click WhatsApp:** Directly open customer's WhatsApp chat from the conversation log.

### 📅 Leads, Appointments & CRM
Turn voice calls and website chats into sales appointments and confirmed bookings:
- **Automated Booking:** Extracts customer name, phone number, vehicle/phone model, and preferred date/time.
- **Appointment Pipeline:** Track leads from New -> Called -> Scheduled -> Store Visited -> Closed.
- **Payment Follow-ups:** Automated reminders for pending dues, installments, and invoices with instant UPI links.

### ⚙️ Settings & Customization
Configure company-specific operational parameters:
- **Company Profile:** Company name, industry, description, website, and headquarters.
- **Business Hours & Holidays:** Set daily opening and closing hours, weekend closures, and holiday schedules.
- **Contact Details:** Official support phone numbers, business email addresses, and physical office address.
- **White-Label Branding:** Custom domain (CNAME), company logo, and custom styling.

---

## 3. How to Use ZeniaOne (Step-by-Step Workflow)

1. **Step 1: Upload Company Documents**
   Navigate to the **Knowledge Base** module and upload your product catalogs, FAQs, pricing sheets, or company policy PDFs. The system automatically chunks and indexes the content for vector search.

2. **Step 2: Create Your Custom AI Agent**
   Go to **AI Agents**, click **New Agent**, choose a voice persona (e.g., Ritu or Rohan), and link it to your newly created Knowledge Base.

3. **Step 3: Test in Playground / Web Chat**
   Open the **AI Playground** or test chat to ask questions in Gujarati, Hindi, Hinglish, or English. Test barge-in interruption and verify that all answers match your uploaded documents.

4. **Step 4: Connect Telephony & Go Live**
   Assign a phone number in **Channels** or embed the web widget on your website. Your autonomous voice agent is now ready to receive customer calls and initiate outbound follow-up campaigns.
