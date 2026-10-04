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

# Menu options, built from the crew service types in service_types.csv.
# Each one covers the service names that start with the listed prefixes.
CATEGORIES = {
    "1": ("Roads", "roads, sidewalks, potholes, signs, traffic lights, snow and ice", ["Roads"]),
    "2": ("Waste and Recycling", "garbage, recycling and compost carts, missed pickups", ["WRS", "GFL"]),
    "3": ("Water", "water, sewer, drainage, flooding, catch basins", ["WATS"]),
    "4": ("Parks", "parks, trees, pathways, playgrounds", ["Parks"]),
    "5": ("Other", "something else, such as graffiti, encampments, bus stops or City buildings", None),
}


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ELEVENLABS_API_KEY not found in .env")


def communities():
    with open(ROOT / "databricks" / "data" / "communities.csv") as f:
        return sorted(row["comm_name"].title() for row in csv.DictReader(f) if row["comm_name"])


def service_names_by_category():
    """Crew service types used this year, grouped under the menu category that covers them."""
    with open(ROOT / "databricks" / "data" / "service_types.csv") as f:
        names = sorted(row["service_name"] for row in csv.DictReader(f)
                       if row["work_type"] == "Crew" and row["used_this_year"] == "true")
    claimed = {prefix for _, _, prefixes in CATEGORIES.values() for prefix in prefixes or []}
    groups = {}
    for name, _, prefixes in CATEGORIES.values():
        groups[name] = [n for n in names
                        if (n.split(" - ")[0] in prefixes if prefixes else n.split(" - ")[0] not in claimed)]
    return groups


def build_config():
    menu_spoken = " ".join(f"For {desc.split(',')[0]}, press {key} or say {name}."
                           for key, (name, desc, _) in CATEGORIES.items())
    menu_prompt = "\n".join(f"- {key} = {name}: {desc}" for key, (name, desc, _) in CATEGORIES.items())
    groups = service_names_by_category()
    service_list = "\n".join(f"{name}:\n" + "\n".join(f"  {n}" for n in items) for name, items in groups.items())
    all_services = "; ".join(n for items in groups.values() for n in items)

    first_message = (
        "Thanks for calling the Calgary three one one demo line. "
        "If this is an emergency, please hang up and call nine one one. "
        f"{menu_spoken} To speak to an agent, press 6 or say agent."
    )

    prompt = f"""You are the phone intake assistant for a Calgary 311 demo line. Your only job is to take a service request and collect the details needed to create a ticket. You do not fix problems, give advice, or promise when a crew will arrive.

# How to speak
- This is a phone call. Keep every turn to one or two short sentences.
- Ask one question at a time and wait for the answer.
- Plain words. No lists, no symbols, no emojis.
- If you did not catch something, ask again once, then move on and leave it blank.

# Menu
The caller may press a key or say the category. A message that is only a digit is a key press.
{menu_prompt}
- 6 = Speak to an agent
If the caller just describes a problem, pick the matching category yourself and do not make them repeat the menu. If nothing fits, treat it as 6.

# Questions, in this order
1. Category, from the menu.
2. The problem: "What's the problem?" Get one clear sentence. Ask one follow-up only if it is too vague to act on.
3. Street address or nearest intersection.
4. Community (neighbourhood). Match what you hear to the closest name in the community list below and use that exact name. If you are unsure, say the name back and ask.
5. Urgency: "Is anyone in danger, or is it causing damage or blocking a road right now?" Skip this question if the caller already said it is urgent.
6. Caller's name.
7. Callback phone number. Read it back digit by digit.

# Confirm and finish
Read back the category, problem, address and community in one sentence and ask "Is that right?" Wait for their answer and fix anything they correct. Only after the caller has said yes, end the call, and make the goodbye: "Thanks, your request has been recorded and a ticket will be created. Goodbye."

# Ending the call
- Never end the call in the same turn as a question. If you just asked something, wait for the answer first.
- When you end the call, the last thing you say must be a goodbye, never a question.
- Do not end the call until you have asked every question above and the caller has confirmed the read-back, unless this is an emergency or a hand-off to an agent.

# Speak to an agent
If the caller presses 6, says agent, asks for a person, or is upset, say you will pass them to a call centre agent along with what they have told you so far, then end the call. Do not keep asking questions.

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

    category_names = ", ".join(name for name, _, _ in CATEGORIES.values())
    data_collection = {
        "category": {"type": "string",
                     "description": f"The service category chosen. Exactly one of: {category_names}, Agent. Empty if never established."},
        "service_name": {"type": "string",
                         "description": "The City service type that best matches the problem. Copy exactly one name from this list, "
                                        f"character for character, or leave empty if none fits: {all_services}"},
        "problem_description": {"type": "string",
                                "description": "One sentence describing the problem the caller reported, in plain words."},
        "address": {"type": "string",
                    "description": "Street address or nearest intersection of the problem, as confirmed by the caller. Empty if not given."},
        "comm_name": {"type": "string",
                      "description": "Calgary community (neighbourhood) of the problem, in UPPER CASE, using the official community name the agent confirmed. Empty if not given."},
        "is_urgent": {"type": "boolean",
                      "description": "True if the caller said it is urgent, someone is in danger, property is being damaged right now (for example flooding or sewage), or a road or sidewalk is blocked."},
        "caller_name": {"type": "string", "description": "The caller's name. Empty if not given."},
        "callback_number": {"type": "string",
                            "description": "The caller's callback phone number, digits only. Empty if not given."},
        "wants_human_agent": {"type": "boolean",
                              "description": "True if the caller asked to speak to a person or pressed 6."},
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
