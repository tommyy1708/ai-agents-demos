# Clarium Academy · Agent engineering demos

Runnable companions to the *AI Agent Engineering* course on Clarium Academy. Each folder is one demo, tied to the
slides it illustrates. Folders are named `c<week>-<demo>` (c for Clarium): `c4-...` goes with week 4. Clone the repo, open a folder,
and follow its README.

| Week | Demo | Slides | Run |
|---|---|---|---|
| 4 | [A secure customer-support agent (ADK + MCP + A2A)](c4-secure-support-agent/) | W4 21–35, W6 25 and 29–30 | `uv run support-agent demo` |

More demos are on the way, one week at a time.

## How every demo works

- **Runs without an API key.** Mock mode answers model calls with simple scripts, so you can follow the flow and
  run the tests for free. Set `ANTHROPIC_API_KEY` to use Claude.
- **Three commands or fewer** from a fresh clone to something on screen, with [uv](https://docs.astral.sh/uv/).
- **Made-up data only.** Customers, orders and companies are fictional; emails use example.com.
- **Tested.** Each demo has tests that run in mock mode, on every push.
- **Mapped to the slides.** The README says which slides each file illustrates.

`catalog.json` lists the demos in a form Clarium Academy reads to show them next to the slides.

## License

The code is released under the [MIT License](LICENSE).
