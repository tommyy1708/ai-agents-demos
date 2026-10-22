# Week 5 · A hotel voice reservation agent, one variable at a time

A voice agent for the made-up Clarium Bay Hotel. It checks availability, books rooms, answers policy questions
from a knowledge file, and hands everything else to the front desk. You build it the way the workshop slide says:
add one variable at a time, and only move on when the step before works.

**Slides**: Week 5, *Voice Agents: From Prototype to Production*
- 41–42: the workshop and its five steps; 44–45: the extensions (the "Try this" list below)
- 17–19: end-of-turn detection and the latency budget; 24: retrieval for policy, tools for changing facts
- 27–29: phone calls, trunks and dispatch rules (step 05)
- 86: the project, a production-style voice reservation agent, starts from this code

## The five steps

| Step | What you add | Run | Needs |
|---|---|---|---|
| 01 Smoke test | the tools only, no model | `uv run hotel smoke` | nothing |
| 02 Text agent | Claude and the policy | `uv run hotel text` | Anthropic key |
| 03 Local voice | VAD, speech-to-text, text-to-speech | `uv run hotel-voice console` | + LiveKit Cloud |
| 04 Room | you and the agent in a WebRTC room | `uv run hotel-voice dev` | + LiveKit Cloud |
| 05 SIP path | a phone call into the room | [guide](sip/README.md) | + a phone number |

The agent is the same in every step from 02 on. Its instructions and tools are in
[`agent.py`](src/hotel_agent/agent.py).

Claude is a text model: it hears what speech-to-text writes down and writes what text-to-speech says. This is the
**cascaded** design from the slides. Speech-to-text (Deepgram Nova-3) and text-to-speech (Cartesia Sonic-3) run on
LiveKit Cloud. Voice activity detection and end-of-turn detection run on your laptop.

## Set up

You need [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd c5-hotel-voice-agent
uv sync
uv run hotel smoke          # step 01 works right away
```

For steps 02–05, copy `.env.example` to `.env` and fill it in:

- `ANTHROPIC_API_KEY`: from your Anthropic Console account, or ask your Clarium Academy admin.
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`: create a free project at
  [cloud.livekit.io](https://cloud.livekit.io) and copy them from the project's API keys settings. Check the free
  tier's current limits for speech-to-text and text-to-speech before a long session.

Before step 03, download the voice activity and end-of-turn models (once):

```bash
uv run hotel-voice download-files
```

## Step by step

**01 Smoke test.** `hotel smoke` calls every tool directly: availability on a weekday and on a weekend (the family
suites are taken on Friday and Saturday nights), a booking, two bad requests, and three policy lookups, one of
which the knowledge file doesn't cover. If a tool is wrong here, no voice will fix it.

**02 Text agent.** `hotel text` is the agent with Claude, in your terminal. It shows each tool call:

```
you> Hi, do you have a room for two adults next Tuesday for two nights?
      tool check_availability({"check_in": "2026-10-27", "check_out": "2026-10-29", "guests": 2})
agent> Yes, we have rooms for two adults next Tuesday, October 27th, checking out Thursday the 29th. ...
you> Great, book the standard queen please. My name is Ana Lima, phone 555 010 0199.
agent> Just to confirm: a Standard Queen for two adults, checking in Tuesday, October 27th ... Shall I book it?
you> Yes, that is all correct.
      tool make_reservation({"guest_name": "Ana Lima", ..., "room_type": "standard_queen", ...})
agent> Your reservation is booked. Your confirmation code is M, N, U, 9, 4, U.
```

**03 Local voice.** `hotel-voice console` uses your laptop's microphone and speaker. Talk to it. After each
reply, the log shows how long you waited and where the time went:

```
caller waited … ms (end of turn …, Claude first token …, first audio …, tools and other steps …)
```

Slide 19 budgets about 700 ms from the end of your turn to the first sound. Compare, and notice what a tool call
adds: the model first asks for the tool, the tool runs, and only then does the model start the reply you hear.
(Press Ctrl+T to switch to text, Ctrl+C to quit. LiveKit is moving console mode into its own CLI as
`lk agent console`; with the version pinned here, `hotel-voice console` works and prints a notice about it.)

**04 Room.** `hotel-voice dev` connects the agent to your LiveKit Cloud project, where it waits for rooms. Open
your project in the [LiveKit Cloud dashboard](https://cloud.livekit.io) and start a session in its Agent Console
(the dashboard's page for talking to your agents): your agent joins the room and you talk to it from the browser. Same agent, new transport.

**05 SIP path.** See [sip/README.md](sip/README.md).

## Tests

```bash
uv run pytest
```

`tests/test_hotel.py` checks the tools and the policy search, with no keys. `tests/test_agent.py` holds evaluation
cases for the agent with Claude: it checks the right dates reach `check_availability`, that policy answers come
from the file, that it reads details back before booking, and that it refuses prompt injection and off-topic
requests. They run when `ANTHROPIC_API_KEY` is set and are skipped otherwise. With Claude Haiku 5.5 all six passed
in each of our four runs.

## Files

| File | What it is | Slides |
|---|---|---|
| `src/hotel_agent/hotel.py` | rooms, rates and bookings, with the rules (step 01) | 23 |
| `knowledge/hotel.md` | the hotel's policies; the agent answers only from here | 24 |
| `src/hotel_agent/knowledge.py` | keyword search over the policy file | 24 |
| `src/hotel_agent/agent.py` | the agent's instructions and tools | 22, 42 |
| `src/hotel_agent/voice.py` | the voice pipeline and the per-turn latency log (steps 03–04) | 17–19 |
| `src/hotel_agent/cli.py` | steps 01 and 02 | 42 |
| `sip/` | the trunk, the dispatch rule and the guide (step 05) | 27–29 |

## Try this

These are the extensions from slides 44–45.

1. **Add a tool.** Add `get_room_service_hours`, returning breakfast, lunch and dinner hours. Register it on
   `HotelAgent`, and add one case to `tests/test_agent.py` proving the agent calls it.
2. **Add knowledge.** Add parking and accessibility policies to `knowledge/hotel.md`, so the agent answers both
   from the file instead of making something up. Today it says it doesn't know, and a test checks that.
3. **Add a guardrail.** Stop the agent from giving medical, legal or financial advice: it should stay polite and
   steer back to reservations. Add one normal case and one prompt-injection case.
4. **Add a language.** Route to French (`fr-FR`) only when the caller asks for it, keep French across turns, and
   switch back to English when asked. Look at the `language` options of the STT and TTS in `voice.py`.
5. **Measure one change.** Run five voice turns and note the latency lines. Change one setting, such as the
   endpointing delays (`turn_handling=TurnHandlingOptions(...)` on `AgentSession`) or the end-of-turn model, and
   compare before and after.

All names, numbers and policies here are made up.
