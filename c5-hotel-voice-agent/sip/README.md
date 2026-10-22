# Step 05 · The SIP path: a phone call into the room

Steps 01–04 never leave your laptop and a LiveKit Cloud project. A real phone call needs a phone number from a
carrier, which costs money and an account, so this step is a guide: follow it when you're ready to call the agent
from a phone. The agent code doesn't change. Only the way the caller reaches the room does.

**Slides**: Week 5, slide 27 (signaling and media), slide 28 (trunks and dispatch rules map calls into rooms) and
slide 29 (local room, self-hosted SIP, production phone network).

```
phone ──► carrier ──► SIP trunk ──► dispatch rule ──► room "call-…" ◄── hotel agent
          (number)    (who may call)  (which room)
```

## 1. Get a phone number

Pick one:

- **A LiveKit Phone Number.** Buy it in the LiveKit Cloud dashboard, in the telephony section. You don't need an
  inbound trunk: skip step 2.
- **A number from a SIP provider** such as Twilio or Telnyx. Point the number at your LiveKit project's SIP URI,
  which the dashboard shows in the project settings. Then create the inbound trunk in step 2.

## 2. Create the inbound trunk (SIP provider only)

Put your number in [`inbound-trunk.json`](inbound-trunk.json), in E.164 format (`+15105550100`), then:

```bash
lk cloud auth                              # once: log the LiveKit CLI in to your project
lk sip inbound create sip/inbound-trunk.json
```

Create one trunk per number and reuse it. Never create one per call.

## 3. Create the dispatch rule

[`dispatch-rule.json`](dispatch-rule.json) puts every caller in their own new room, named `call-…`:

```bash
lk sip dispatch create sip/dispatch-rule.json
```

## 4. Run the agent and call

```bash
uv run hotel-voice dev
```

Call the number. The call lands in a new `call-…` room, the agent joins it, and you're talking to the same agent
you tested in steps 02–04.

The agent here uses **automatic dispatch**: it joins every new room in the project. That keeps the workshop
simple. In production, give the agent a name (`@server.rtc_session(agent_name="hotel-agent")`) and add
`"room_config": {"agents": [{"agent_name": "hotel-agent"}]}` to the dispatch rule, so only calls reach it.

## What changes on a phone line

- **Audio is 8 kHz.** Speech recognition gets worse, especially on names, numbers and dates. Slide 21: test with
  phone audio, not only your laptop's microphone.
- **Transfers become real.** `transfer_to_front_desk` only logs today. On a phone line it would move the caller to
  the front desk with a SIP transfer (LiveKit's `TransferSIPParticipant` API), and the front desk needs a number
  of its own.
- **Ending the call hangs up.** The `end_call` tool deletes the room, which disconnects the caller.
- **Latency adds up.** The phone network adds its own delay on top of the budget you measured in step 03.
