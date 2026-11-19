# Fantasy NFL Bye Week & Playoff Schedule Grid

An agent skill for fantasy football managers. It shows every NFL team's opponents and BYE weeks for the rest of the regular season, marks the usual fantasy playoff weeks (15-17), and — when you paste your roster — adds a per-player table and the weeks where a position runs short because of byes.

It is a standard agent skill: a `SKILL.md` that tells the agent what to run, and `run.py` (Python 3.8+, standard library only, nothing to install).

## Install

Claude Code (or any agent that reads `SKILL.md` skills):

```bash
git clone https://github.com/dh-soft/fantasy-nfl-bye-grid
cp -r fantasy-nfl-bye-grid ~/.claude/skills/free-nfl-bye-grid
```

or with the skills CLI:

```bash
npx skills add dh-soft/fantasy-nfl-bye-grid
```

Then ask your agent, for example: "Show this week's NFL grid for my roster."

## Your free API key

The schedule comes from [BALLDONTLIE](https://www.balldontlie.io) with your own free key: sign up at https://app.balldontlie.io, copy the key, then set `BALLDONTLIE_API_KEY` or run `python3 run.py setkey` and paste it (input is hidden). The key is stored only on your computer and sent only to api.balldontlie.io.

## Commands

| What | Command |
|---|---|
| Bye and opponent grid for all teams | `python3 run.py grid` |
| Your roster's byes and short weeks | `python3 run.py grid --roster "Josh Allen, Bijan Robinson, BUF DEF, ..."` |
| Only the fantasy playoff weeks | `python3 run.py grid --weeks 15-17` |
| Save your API key (input hidden) | `python3 run.py setkey` |
| Check key and cache | `python3 run.py status` |

## Example output

See [examples/sample-output.md](examples/sample-output.md) (a real run with a sample roster).

## Limits

- Schedules come from the BALLDONTLIE API; flexed or moved games appear after the next refresh.
- BALLDONTLIE's free plan allows 5 requests per minute; the first run can take about a minute.
- Byes are per team; a player's team is his current team in the data.
- Unofficial; not affiliated with the NFL or any team. Not betting or daily fantasy (DFS) advice.

## Want it checked automatically?

[Fantasy NFL Roster Watch](https://capafy.ai/agent/fantasy-nfl-roster-watch-start-sit-waivers/2102998908) on Capafy checks your roster every 4 hours with injury designations, snap shares, start/sit and waiver picks.

## License

MIT — see [LICENSE](LICENSE). Made by DH Soft.
