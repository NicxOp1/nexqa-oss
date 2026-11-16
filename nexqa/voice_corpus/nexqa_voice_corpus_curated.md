# NEXQA Voice AI Prompt Engineering Corpus

## Overview

This corpus is NEXQA's internal knowledge base for expert-level voice AI prompt engineering. It synthesizes best practices from **13 major voice AI platforms**, curated specifically for the **Retell AI + Deepgram + ElevenLabs + GPT** stack.

**How to use this document:**
- **Building a new voice agent?** Start with "Cross-Platform Universal Principles", then the Retell deep-dive.
- **Debugging a voice agent?** Check the "Anti-Pattern Reference Table" and platform-specific "Gotchas."
- **Optimizing latency?** Each platform section has "Latency Considerations."
- **Optimizing prompts?** The gene optimizer injects relevant sections as context when mutating genes.

Every parameter name, default value, and code example is extracted directly from official documentation.

---

## Cross-platform universal principles

### The golden rules of voice prompting

These rules hold across **every platform** tested. Violating any one degrades voice agent quality regardless of stack.

**1. Structure prompts with labeled sections using markdown headers.** Retell, Vapi, ElevenLabs, and Bland AI all independently recommend the same pattern: break system prompts into `## Identity`, `## Style`, `## Task`, `## Guardrails` sections. ElevenLabs specifically notes that models are **tuned to pay extra attention** to content under a `# Guardrails` heading. The universal principle: sectional prompts reduce instruction bleed, improve LLM accuracy, and make prompts maintainable.

**2. Keep voice responses to 1–2 sentences per turn.** Every platform emphasizes brevity. Voice is not text — users cannot re-read, scroll back, or skim. Retell recommends "under 2 sentences unless explaining complex topics." Long responses lose user attention and increase interruption probability.

**3. Ask one question at a time, then wait.** Overwhelming users with multiple questions in voice is the single most common design failure. Every orchestration platform and enterprise conversation design system (Dialogflow CX, Amazon Lex, Rasa) implements form-filling patterns that collect one slot per turn.

**4. Normalize all numbers, dates, and symbols for speech.** Every TTS-dependent platform documents this as critical. ElevenLabs warns that "zipcode 10023 will be spoken as 'ten thousand and twenty-three'" without normalization. Retell provides a `normalize_for_speech` toggle. This is **the most common technical failure** in voice agents.

**5. Never expose internal mechanics to the user.** Don't say "function" or "tools" or tool names. Don't say "ending the call" — just trigger the end-call tool silently. Don't mention transfers before executing them. The agent should feel like a person, not a state machine.

**6. Validate and repeat back critical information.** Build validation/verification loops — repeat back critical info ("I got five five five west main street. Did I miss anything?"). This is especially critical for phone numbers, emails, and addresses where ASR errors compound.

**7. Include explicit fallback and error handling in every prompt.** After N failed attempts, escalate to a human or gracefully end the interaction. Three attempts with escalating specificity: (1) gentle rephrase, (2) offer constrained options, (3) escalate to human.

### Universal anti-patterns that break all voice AI

**Markdown formatting in TTS output.** Bullet points, numbered lists, bold markers, headers — all get read aloud as literal characters or cause bizarre TTS behavior. You must explicitly instruct the model to respond conversationally, not in written format.

**Long sentences with parentheticals, em-dashes, and nested clauses.** TTS engines struggle with complex sentence structures. Use short, direct sentences under 20 words.

**Monolithic system prompts for complex workflows.** Every orchestration platform converges on the same insight: single giant prompts lead to higher hallucination, increased token cost, greater latency, and inconsistent behavior. Retell recommends Conversation Flow when you have "more than 3-4 conditional paths or 5+ different functions."

**Telling the agent what NOT to do without providing the positive alternative.** Negative instructions ("don't ask for the credit card number") are weaker than positive ones ("collect the customer's name and email only"). Always pair restrictions with explicit desired behavior.

**Using raw abbreviations, URLs, and email addresses.** "Dr." may be read as "D-R-period." URLs become gibberish. Email addresses need explicit normalization to "john at company dot com."

### Voice vs. text — key differences

| Dimension | Text Chat | Voice Agent |
|---|---|---|
| **Response length** | Paragraphs acceptable | 1-2 sentences max per turn |
| **Formatting** | Markdown, bullets, tables | Pure conversational prose, no formatting |
| **Numbers** | "1,234" renders correctly | Must say "one thousand two hundred thirty four" |
| **Error recovery** | User re-reads | User says "what?" — agent must rephrase |
| **Context** | User scrolls up | User has only working memory — repeat key info |
| **Latency tolerance** | 2-5 seconds acceptable | >1 second feels broken; >600ms noticeable |
| **Input quality** | Clean typed text | Disfluencies, accents, background noise, partial utterances |
| **Interruptions** | Not applicable | Must handle gracefully — stop, listen, respond |
| **Turn-taking** | Explicit (user hits send) | Implicit — system must detect end-of-turn |
| **Emotional context** | Emoji, punctuation | Tone of voice, speaking speed, volume |

---

## Platform deep-dives

### Retell AI (Orchestration Layer)

**Overview.** Retell AI is a voice agent orchestration platform offering three response engine types: Retell LLM (managed), Conversation Flow (node-based), and Custom LLM (bring your own via WebSocket). Retell handles audio, turn-taking, and interruptions; you focus on conversation logic. Platform latency is approximately **600ms** end-to-end.

**Prompt structure.** Retell recommends markdown-headed sections: `## Identity`, `## Style Guardrails`, `## Response Guidelines`, `## Task Instructions`, `## Objection Handling`. Dynamic variables use `{{variable_name}}` syntax. All variable values **must be strings** — no numbers or booleans. Unset variables remain visible as raw `{{variable}}` text, so design prompts defensively. Built-in system variables include `{{current_time}}`, `{{user_number}}`, `{{direction}}`, `{{session_type}}`, and `{{current_calendar}}` (14-day calendar).

**Best practices.**
- Use Conversation Flow for complex tasks with 3+ conditional paths or 5+ tools. Each node gets its own shorter prompt, reducing hallucination.
- Reference tools by **exact names** in prompts with explicit trigger conditions. Example: "When user provided the city name, call the `get_weather` function."
- Enable `normalize_for_speech` to automatically convert numbers, dates, and currencies to spoken form.
- Use `boosted_keywords` to improve transcription of proper nouns and domain-specific terms.
- Run simulation testing against past conversations before going live.

**Anti-patterns.**
- Stuffing everything into one prompt leads to hallucination at scale. More than 5 tools in a single prompt context is a documented failure point.
- Skipping server-side validation of function call arguments: "LLM can hallucinate and make mistakes" with tool parameters.
- Ignoring missing variable handling causes raw `{{variable}}` to be spoken aloud.
- Using `stt_mode: "fast"` for number-heavy use cases — `accurate` mode adds ~200ms but significantly improves entity recognition.

**Key configuration parameters.**

| Parameter | Default | Range | What it controls |
|---|---|---|---|
| `responsiveness` | 1 | 0–1 | Response speed. Each 0.1 decrease = +500ms wait. |
| `interruption_sensitivity` | 1 | 0–1 | Interrupt ease. 0 = never interrupted. |
| `enable_backchannel` | false | boolean | "Yeah", "uh-huh" during user speech |
| `backchannel_frequency` | 0.8 | 0–1 | How often backchannels fire |
| `reminder_trigger_ms` | 10000 | positive int | Silence before "are you there?" |
| `reminder_max_count` | 1 | 0+ | Max reminders. 0 = disabled |
| `end_call_after_silence_ms` | 600000 | min 10000 | End call after silence |
| `max_call_duration_ms` | 3600000 | 60K–7.2M | Max call length (1 hr default) |
| `stt_mode` | "fast" | fast/accurate/custom | Latency vs. accuracy tradeoff |
| `normalize_for_speech` | false | boolean | Auto-normalize numbers/dates |
| `voice_speed` | 1 | 0.5–2 | Speech rate multiplier |
| `voice_temperature` | 1 | 0–2 | Voice stability (ElevenLabs only) |
| `ambient_sound` | null | coffee-shop/convention-hall/etc. | Background ambience |
| `begin_message_delay_ms` | 0 | 0–5000 | Delay before first message |

**Voice-specific gotchas.**
- `interruption_sensitivity` doesn't work in Test Agent mode — confirmed community issue. Only functions on live calls.
- `voice_temperature` only works with ElevenLabs voices; `voice_emotion` only with Cartesia and Minimax. Other providers silently ignore these.
- Function call results are capped at **15,000 characters** — larger responses are truncated before reaching the LLM.
- Fallback voice IDs must be from **different TTS providers**.
- Each tool call adds approximately **2x LLM latency** because it requires two LLM calls (decide to call + process result).
- Date parsing with relative terms like "next Wednesday" is notoriously unreliable — use a calendar API function instead.

**Example prompt template.**

```
## Identity
You are Sarah, a scheduling assistant for Apex Medical Group.

## Style Guardrails
Be concise: Keep responses under 2 sentences.
Be conversational: Use natural language and contractions.
Be empathetic: Acknowledge the caller's needs.

## Response Guidelines
Return dates in spoken form: "January fifteenth" not "1/15".
Ask one question at a time.
Confirm understanding by repeating back key details.

## Task Instructions
1. Greet the patient and ask how you can help.
2. If they need an appointment:
   → Call `check_calendar_availability` with preferred date
   → Present 2-3 available slots
   → Call `book_calendar` once confirmed
3. Always confirm: date, time, and doctor name before booking.

## Objection Handling
If no slots available: "I don't see openings on that date. Would {{alternative_day}} work?"
If caller is frustrated: "I understand your frustration. Let me find the earliest available slot."
```

**Tool/function calling.** Retell supports built-in tools (`end_call`, `transfer_call`, `send_sms`, `check_calendar_availability`, `book_calendar`, `press_digit`, `extract_dynamic_variables`, `agent_transfer`) plus custom functions via HTTP webhook. Custom functions receive the full call object including real-time transcript. Configure "Speak during execution" for user-facing actions ("Let me check that for you") and disable it for background tasks. Verify webhook authenticity via `X-Retell-Signature` HMAC header.

**Latency considerations.** Use `stt_mode: "fast"` for general conversation, `"accurate"` for number-heavy flows. Choose GPT-4.1 for the best quality-to-latency ratio. Enable Fast Tier (1.5x cost) for priority compute with consistent low latency. Break complex prompts into Conversation Flow nodes with shorter per-node prompts and fewer tool choices. Monitor P90 latency — trigger troubleshooting if it exceeds 3 seconds.

---

### Deepgram (STT Layer)

**Overview.** Deepgram provides deep-learning ASR with three model tiers: **Flux** (purpose-built for voice agents with semantic end-of-turn detection), **Nova-3** (flagship, 6.84% streaming WER, 45+ languages), and **Nova-2** (previous generation, specialized variants for phonecall/voicemail/meeting).

**Key configuration parameters.**

| Parameter | Default | Range | What it controls |
|---|---|---|---|
| `endpointing` | 10 (ms) | integer ms or false | Silence before `speech_final`. **Default is extremely aggressive.** |
| `utterance_end_ms` | disabled | integer ms (≥1000) | Fallback end-of-utterance timer. Requires `interim_results=true`. |
| `interim_results` | false | boolean | Enable preliminary transcripts |
| `filler_words` | false | boolean | Include "uh", "um" in transcripts |
| `smart_format` | false | boolean | Format dates, numbers, currency. May delay finalization up to 3s. |
| `keywords` | — | keyword:intensifier | Boost uncommon words. **Nova-2 only.** |
| `keyterm` | — | string | Key term prompting. **Nova-3 only.** |
| `vad_events` | false | boolean | Speech start detection events |

**Best practices for voice agents.** Use dual end-of-speech strategy: (1) trigger on `speech_final: true` for normal pauses, (2) use `UtteranceEnd` as fallback for noisy environments where VAD prevents silence detection. Recommended config: `endpointing: 800`, `utterance_end_ms: 2000`, `interim_results: true`, `filler_words: true`. Set `filler_words=true` because it improves turn detector accuracy.

**Gotchas.**
- The `endpointing=10` default is **far too aggressive** for voice agents — set 300-800ms.
- `utterance_end_ms` below 1000 is useless since interim results are sent ~every second.
- `keywords` is Nova-2 only; `keyterm` is Nova-3 only — using the wrong one silently fails.
- `smart_format` can delay streaming results up to 3s while completing entity recognition.

---

### ElevenLabs (TTS Layer)

**Overview.** ElevenLabs provides industry-leading TTS and a Conversational AI agent platform. Key differentiator: the deepest voice control parameters of any platform, plus the most expressive TTS models available.

**Prompt structure.** ElevenLabs recommends markdown headings with specific section names:

```
# Personality
# Environment
# Tone
# Goal
# Tools
# Guardrails
```

The `# Guardrails` heading is **special** — ElevenLabs models are specifically tuned to pay extra attention to rules under this heading. Adding "This step is important" at the end of critical instruction lines reinforces compliance. Prompts over **2,000 tokens** increase latency and cost.

**Best practices.**
- **Don't recycle human training materials** — LLMs make different assumptions than humans and default to verbose, structured text.
- Gather information incrementally, one field per turn.
- Prompt the LLM to forewarn users of delays: "Give me a moment to examine your case" during tool execution.
- Configure **Tool Call Sounds** (ambient audio) during tool execution to prevent awkward silence.
- Use the **Orchestrator + Specialist pattern** — route via intent classification, then hand off to domain specialists.
- Keep temperature at **0.0-0.3** for customer service, **0.4-0.7** for balanced, **0.8-1.0** for creative/coaching.
- Set Reasoning Effort to **None** for conversational agents — thinking too long disrupts natural flow.

**Anti-patterns.**
- Unformatted numbers, currencies, dates, and times in TTS output.
- Raw URLs and email addresses without spoken-form normalization.
- Excessive `<break>` SSML tags in one generation — causes instability where AI speeds up and introduces artifacts.
- Setting stability too low causes odd, random performances. Setting too high produces monotonous output.
- Style exaggeration > 0 increases latency and reduces stability. **Keep at 0 for all real-time use.**
- Speaker Boost adds computational load and is **not available for Eleven v3**.
- Very short prompts under ~250 characters cause inconsistent outputs with v3.
- Making multiple prompt changes simultaneously — can't attribute improvements vs. regressions.

**Key configuration parameters.**

| Parameter | Default | Range | What it controls |
|---|---|---|---|
| `stability` | ~0.5 | 0–1 | Lower = more emotional/varied; Higher = consistent/monotone. Sweet spot: 0.3–0.5 dynamic, 0.6–0.85 consistent. |
| `similarity_boost` | ~0.75 | 0–1 | Voice adherence. Too high reproduces source artifacts. |
| `style` (exaggeration) | 0 | 0–1 | **Recommend 0 for all agents.** Adds latency. |
| `use_speaker_boost` | false | boolean | **Recommend false for agents.** Not available on v3. |
| `speed` | 1.0 | 0.7–1.2 | Speech rate multiplier |
| `optimize_streaming_latency` | 0 | 0–4 | Higher = lower latency, lower quality |
| `model_id` | — | eleven_flash_v2_5 / eleven_turbo_v2_5 / eleven_multilingual_v2 / eleven_v3 | TTS model selection |

**Voice model selection for agents:**

| Model | Latency | Quality | Languages | Agent suitability |
|---|---|---|---|---|
| Flash v2.5 | ~75ms inference | Good | 32 | **Best for agents** — lowest latency |
| Turbo v2.5 | ~250ms | Very good | 32 | Good balance |
| Multilingual v2 | Highest | Highest | 29 | Quality-critical only |
| Eleven v3 | Too high | Most expressive | Many | **NOT suitable for real-time agents** |

**SSML and pronunciation.** Supported tags: `<break time="x.xs"/>` (pauses up to 3s, non-v3 only), `<phoneme>` (CMU Arpabet or IPA, Flash v2/Turbo v2/English v1 only), and alias/lexeme tags (all models). For v3 models, use audio tags instead of SSML: `[curious]`, `[excited]`, `[whispers]`, `[laughs]`, `[sigh]`.

**Voice-specific gotchas.**
- **Buffer words for custom LLMs**: Return "... " (ellipsis + space) as initial response to maintain natural speech flow. The space after the ellipsis is crucial — without it, audio distortion occurs.
- WebSocket keepalive requires sending `" "` (space character), not `""` (empty string) — empty string closes the connection.
- WebSocket auto-closes after **20 seconds of inactivity**.
- LLM cascading: configure backup LLMs for failover during primary model outages.
- Voice speed fastest-to-slowest: Default/premade voices → Synthetic/IVC → PVC (Professional Voice Clones have highest latency).

**Latency considerations.** Four optimization levers: (1) use Flash models (~75ms inference), (2) leverage streaming — WebSocket for real-time LLM output, (3) choose faster voices (premade > cloned), (4) co-locate geographically (US: 150-200ms TTFB, EU: 230ms, NE Asia: 250-350ms). Target: **sub-second total latency** for conversational AI.

---

## Cross-platform prompting wisdom

### Extracted from platforms not in our stack

These insights come from Vapi, Bland AI, Dialogflow CX, Amazon Lex, Rasa, OpenAI Realtime, and Cartesia. While we don't use these platforms, their prompting wisdom applies universally.

**Emotional prompting shapes voice tone (Vapi).** Fillers ("I-I-I"), hesitations ("uh", "um"), pauses ("…"), and emphasis (CAPS, exclamation marks) in the system prompt directly influence how the LLM generates responses. The TTS then faithfully reproduces these speech patterns. Use this to make agents sound more human.

**Temperature 0.1–0.3 for voice agents (Vapi, ElevenLabs).** Lower temperature = faster, more deterministic responses. Voice agents need speed and consistency over creativity.

**Silent action execution — never announce tool calls (Vapi, Retell, Bland).** When triggering transfers, ending calls, or executing tools: never announce the action. Send no text response — just trigger the tool. "I'm now transferring you" followed by silence is jarring.

**"Don't tell NOT to do without providing what to do instead" (Bland).** Negative instructions are weaker than positive ones. "Don't ask for credit card" is weaker than "Collect only name and email." Always pair restrictions with desired behavior.

**Keep prompts under 2,000 characters for optimal performance (Bland).** Shorter prompts = less hallucination, faster response, more consistent behavior.

**10+ statement example dialogues set tone better than instructions (Bland).** Instead of writing rules about tone, provide a 10-line back-and-forth example showing the ideal interaction. The LLM pattern-matches more reliably from examples than from abstract instructions.

**Conversation repair: 3 retries with escalating specificity (Dialogflow CX, Amazon Lex, Rasa).** (1) "I didn't catch that, could you repeat?" (2) "Could you tell me your zip code? It's a 5-digit number." (3) "Let me connect you with someone who can help." Never trap users in infinite error loops.

**Form-filling: one slot per turn, confirm after each (Dialogflow CX, Amazon Lex).** Collect one piece of information per turn. After each collection, confirm what you heard. Before proceeding, summarize all collected information. This is the universal enterprise pattern.

**Flows ≠ flowcharts — patterns handle deviations automatically (Rasa).** Design conversation flows for the happy path. Use separate "patterns" for handling digressions like "what time is it?" or "can you repeat that?" These patterns automatically activate and return to the previous context.

**Semantic VAD understands conversational context, not just silence (OpenAI Realtime).** Traditional turn detection uses silence duration. Semantic VAD understands that "my phone number is..." followed by a pause means the user is still thinking, not done. Set eagerness low for collection scenarios, high for rapid back-and-forth.

**Buffer first 3-4 words before sending to TTS (Cartesia).** Don't stream word-by-word to TTS. Buffer the first few words so the TTS engine can establish proper prosody for the entire sentence. Spaces and punctuation directly impact prosody quality.

**Confidence score thresholds for fallback (Amazon Lex).** NLU returns scores 0.0-1.0 for intent classification. Set a threshold below which the system triggers a fallback ("I'm not sure I understood. Could you rephrase?"). This prevents confidently wrong responses.

---

## Cross-platform pattern library

### Prompt patterns that work everywhere

**The Sectional Prompt Pattern.** Every major platform converges on this structure:

```
## Identity/Persona
[Who the agent is, their role, expertise]

## Style/Tone
[Communication style, brevity rules, emotional register]

## Response Guidelines
[Voice-specific formatting: dates in words, one question at a time,
no internal mechanics exposed]

## Task/Goal
[Step-by-step workflow with conditional branching]

## Tool Usage
[Explicit trigger conditions for each tool by exact name]

## Guardrails
[Hard constraints, safety rules, scope boundaries]

## Error Handling
[Fallback behavior, escalation paths, retry limits]
```

**The Silent Action Pattern.** When triggering transfers, ending calls, or executing tools: never announce the action. Send no text response — just trigger the tool. This prevents the jarring experience of the agent saying "I'm now transferring you" and then silence.

**The Defensive Variable Pattern.** Always design prompts that work with or without dynamic variables being populated:

```
If the customer's name is available, greet them by name.
If {{customer_name}} appears with curly braces or is empty,
use "there" instead (e.g., "Hi there!").
```

**The Incremental Collection Pattern.** Collect one piece of information per turn. After each collection, confirm what you heard. Before proceeding to the next step, summarize all collected information.

**The Conversation Repair Pattern.** Three attempts with escalating specificity:
1. "I didn't catch that."
2. "Could you tell me your zip code? It's a 5-digit number."
3. "Let me connect you with someone who can help."

### Anti-pattern reference table

| Anti-Pattern | Why It Breaks | Fix |
|---|---|---|
| Raw numbers in TTS ("$1,234.56") | TTS reads digits/symbols literally | Normalize to "one thousand two hundred thirty four dollars and fifty six cents" |
| Markdown in responses (bullets, bold) | Read as literal characters or cause artifacts | Instruct model to respond conversationally |
| Long monolithic prompts (>2000 chars) | Hallucination, latency, inconsistency | Break into states/flows/nodes |
| Multiple questions per turn | User overwhelmed, answers only first | One question, wait, confirm |
| Announcing tool calls ("Let me transfer you") | Jarring silence after announcement | Silent execution |
| Negative-only instructions ("Don't do X") | Weaker than positive instructions | Pair with "Do Y instead" |
| `endpointing=10` (Deepgram default) for agents | Cuts off users mid-thought | Set 300-800ms |
| `filler_words=false` for agent STT | Reduces turn detector accuracy | Enable `filler_words=true` |
| Style exaggeration > 0 (ElevenLabs) | Increases latency, reduces stability | Keep at 0 |
| Excessive `<break>` SSML tags | Audio speedup, noise artifacts | Limit break tags per generation |
| Smart format with streaming STT | Up to 3s delay for entity completion | Use `no_delay=true` or disable smart_format |
| Stuffing >5 tools in single prompt | Hallucination at scale | Use Conversation Flow nodes |
| Raw `{{variable}}` without fallback | Variable name spoken aloud if unset | Always provide fallback text |
| Complex sentences with em-dashes/parentheticals | TTS struggles, sounds confusing | Short sentences under 20 words |
| Human training materials as prompts | LLMs default to verbose text output | Write voice-specific prompts from scratch |
| Ignoring ASR errors for critical data | Phone numbers, emails silently wrong | Always repeat back and confirm |

---

## Appendix

### Configuration parameter reference

**Interruption and turn detection (your stack):**

| Platform | Interruption Sensitivity | Turn-End Detection | Backchanneling |
|---|---|---|---|
| **Retell** | `interruption_sensitivity` [0-1], default 1 | Proprietary turn-taking model + `responsiveness` [0-1] | `enable_backchannel`, `backchannel_frequency` [0-1] |

**Silence and timeout parameters:**

| Platform | Silence Timeout | Max Duration | Reminder |
|---|---|---|---|
| **Retell** | `end_call_after_silence_ms` (default 600s) | `max_call_duration_ms` (default 1hr, max 2hr) | `reminder_trigger_ms` (10s), `reminder_max_count` (1) |

**STT model selection (Deepgram):**

| Use Case | Recommended Model | Config |
|---|---|---|
| Voice agents (English) | Flux (semantic EOT) | `endpointing: 800`, `utterance_end_ms: 2000` |
| Voice agents (multilingual) | Nova-3 + `multi` | `interim_results: true` |
| Cost-sensitive | Nova-2 `conversationalai` | Default settings |
| Number-heavy (SSN, phone) | Nova-3 + accurate endpointing | `stt_mode: "accurate"` on Retell |

### Glossary of voice AI terms

| Term | Definition |
|---|---|
| **ASR / STT** | Automatic Speech Recognition / Speech-to-Text. Converts audio to text. |
| **TTS** | Text-to-Speech. Converts text to audio. |
| **VAD** | Voice Activity Detection. Determines when someone is speaking vs. silent. |
| **Endpointing** | Detecting when a user has finished speaking (end of turn). |
| **Semantic VAD** | Context-aware turn detection that understands conversational meaning, not just silence. |
| **Barge-in** | User interrupting the agent while it's speaking. |
| **Backchannel** | Listener feedback sounds ("uh-huh", "yeah") that signal attention without taking a turn. |
| **SSML** | Speech Synthesis Markup Language. XML tags controlling TTS pronunciation, pauses, emphasis. |
| **DTMF** | Dual-Tone Multi-Frequency. Keypad tones on telephone (0-9, *, #). |
| **TTFB / TTFA** | Time-to-First-Byte / Time-to-First-Audio. Key latency metric. |
| **EOT** | End-of-Turn. The moment the system determines the user has finished speaking. |
| **Filler words** | Disfluencies like "uh", "um", "like" that occur naturally in speech. |
| **Smart endpointing** | Analyzing partial transcripts to determine if user is done (vs. just pausing). |
| **Conversation Flow** | Node-based conversation design where each node has its own prompt and tools (Retell). |
| **Warm transfer** | Transferring a call where the receiving party is briefed before the caller is connected. |
| **Cold transfer** | Transferring a call directly without briefing the receiving party. |
| **AMD** | Answering Machine Detection. Determines if a human or voicemail answered. |
| **S2S** | Speech-to-Speech. Native audio-in, audio-out model (no text intermediate). |