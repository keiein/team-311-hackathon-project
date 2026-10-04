"""Create or update the 311 voice intake agent on ElevenLabs.

Run from the repo root:  python3 "11lab Call Agent/create_agent.py"
Needs ELEVENLABS_API_KEY in .env. The agent id is saved to agent_id.txt next to this script,
so running this again updates the same agent instead of making a new one.
"""
import csv
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_ID_FILE = pathlib.Path(__file__).resolve().parent / "agent_id.txt"
API = "https://api.elevenlabs.io/v1/convai/agents"

VOICE_ID = "SAz9YHcvj6GT2YYXdXww"   # River: relaxed, neutral, informative
LLM = "claude-haiku-4-5"

def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ELEVENLABS_API_KEY not found in .env")


def communities():
    with open(ROOT / "databricks" / "data" / "communities.csv") as f:
        return sorted(row["comm_name"].title() for row in csv.DictReader(f) if row["comm_name"])


def service_names():
    """Crew service types used this year."""
    with open(ROOT / "databricks" / "data" / "service_types.csv") as f:
        return sorted(row["service_name"] for row in csv.DictReader(f)
                      if row["work_type"] == "Crew" and row["used_this_year"] == "true")


def build_config():
    services = service_names()
    service_list = "\n".join(services)
    all_services = "; ".join(services)

    first_message = (
        "You have reached the Calgary 311 hotline. "
        "For emergencies, please call 911. "
        "To speak to an agent, press 0 or say agent. "
        "How can I help you today? "
    )

    prompt = f"""You are the phone intake assistant for a Calgary 311 demo line. Your only job is to take a service request and collect the details needed to create a ticket. You do not fix problems, give advice, or promise when a crew will arrive.

# How to speak
- This is a phone call. Keep every turn to one or two short sentences.
- Ask one question at a time and wait for the answer.
- Plain words. No lists, no symbols, no emojis.
- If you did not catch something, ask again once, then move on and leave it blank.

# Conversation
There is no menu. The greeting already asked "How can I help you today?" and offered an agent, so start from whatever the caller says, the way a call centre agent would.
- Listen for every detail in what they say. Never ask for something the caller has already told you.
- A message that is only a digit is a key press. 0 means speak to an agent. Any other key does nothing on this line, so ask the caller to tell you what the problem is.

# Details to collect, in this order
Skip any the caller has already given.
1. The problem. Get one clear sentence. Ask one follow-up only if it is too vague to act on.
2. Street address or nearest intersection.
3. Caller's name.
4. Callback phone number. Read it back digit by digit.

Do not ask which community it is in or how urgent it is. If the caller mentions a community, match it to the closest name in the community list below.

# Confirm and finish
Read back the problem and address in one sentence and ask "Is that right?" Wait for their answer and fix anything they correct. Only after the caller has said yes, end the call, and make the goodbye: "Thanks, your request has been recorded and a ticket will be created. Goodbye."

# Ending the call
- Never end the call in the same turn as a question. If you just asked something, wait for the answer first.
- When you end the call, the last thing you say must be a goodbye, never a question.
- Do not end the call until you have collected every detail above and the caller has confirmed the read-back, unless this is an emergency or a hand-off to an agent.

# Speak to an agent
If the caller presses 0, says agent, asks for a person, or is upset, say you will pass them to a call centre agent along with what they have told you so far, then end the call. Do not keep asking questions.

# Service type
From the problem, silently pick the one service type below that fits best. Never read these names out loud and never ask the caller to choose one. If two could fit, ask one short question that tells them apart (for example "Is it your blue, green or black cart?"). If the problem is not something a City work crew fixes, such as a tax, permit, noise or bylaw question, treat it as "Speak to an agent".
{service_list}

# Emergencies
If the caller describes fire, a crime in progress, a gas smell, downed power lines, or someone hurt, tell them to hang up and call 911 right now, then end the call.

# Limits
- Stay on 311 service requests. Politely decline anything else.
- Never invent an address, a community, or a ticket number.

# Calgary communities
{", ".join(communities())}
"""

    data_collection = {
        "service_name": {"type": "string",
                         "description": "The City service type that best matches the problem. Copy exactly one name from this list, "
                                        f"character for character, or leave empty if none fits: {all_services}"},
        "problem_description": {"type": "string",
                                "description": "One sentence describing the problem the caller reported, in plain words."},
        "address": {"type": "string",
                    "description": "Street address or nearest intersection of the problem, as confirmed by the caller. Empty if not given."},
        "comm_name": {"type": "string",
                      "description": "Calgary community (neighbourhood) of the problem, in UPPER CASE, using the closest official community name. Empty if the caller never mentioned one."},
        "is_urgent": {"type": "boolean",
                      "description": "True if the caller said it is urgent, someone is in danger, property is being damaged right now (for example flooding or sewage), or a road or sidewalk is blocked."},
        "caller_name": {"type": "string", "description": "The caller's name. Empty if not given."},
        "callback_number": {"type": "string",
                            "description": "The caller's callback phone number, digits only. Empty if not given."},
        "wants_human_agent": {"type": "boolean",
                              "description": "True if the caller asked to speak to a person or pressed 0."},
        "caller_confirmed": {"type": "boolean",
                             "description": "True if the agent read the details back and the caller confirmed they were right."},
    }

    return {
        "name": "Calgary 311 Intake",
        "conversation_config": {
            "agent": {
                "first_message": first_message,
                "language": "en",
                "prompt": {
                    "prompt": prompt,
                    "llm": LLM,
                    "temperature": 0.2,
                    "built_in_tools": {
                        "end_call": {
                            "name": "end_call",
                            "description": "End the call with a spoken goodbye. Use only after the caller has confirmed the read-back, after a hand-off to an agent, or after telling the caller to call 911. Never use it in the same turn as a question.",
                            "params": {"system_tool_type": "end_call"},
                        },
                    },
                },
            },
            "tts": {"voice_id": VOICE_ID},
            "conversation": {
                "dtmf_input_settings": {"dtmf_input_timeout": 2.0, "hash_terminator": True, "redact_input": False},
            },
        },
        "platform_settings": {"data_collection": data_collection},
    }


def call(method, url, key, body):
    out = subprocess.run(
        ["curl", "-sS", "-X", method, url, "-H", f"xi-api-key: {key}",
         "-H", "Content-Type: application/json", "-d", json.dumps(body)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def main():
    key = load_env()
    config = build_config()
    if AGENT_ID_FILE.exists():
        agent_id = AGENT_ID_FILE.read_text().strip()
        result = call("PATCH", f"{API}/{agent_id}", key, config)
        action = "Updated"
    else:
        result = call("POST", f"{API}/create", key, config)
        action = "Created"
    if "agent_id" not in result:
        raise SystemExit(f"ElevenLabs returned an error:\n{json.dumps(result, indent=2)[:2000]}")
    AGENT_ID_FILE.write_text(result["agent_id"] + "\n")
    print(f"{action} agent {result['agent_id']}")
    print(f"Open: https://elevenlabs.io/app/agents/agents/{result['agent_id']}")


if __name__ == "__main__":
    main()
