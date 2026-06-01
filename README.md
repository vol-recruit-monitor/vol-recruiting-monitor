# Volcruit 2026 Offer Monitor

A password-gated public GitHub Pages dashboard for monitoring college football offer announcements, with X as the primary source. The site is styled around the provided Tennessee recruiting graphic: orange punch, cream paper texture, charcoal contrast, mountain/burst shapes, and a compact war-room layout.

## What It Does

- Checks X every 20 minutes through GitHub Actions.
- Looks for offer announcements from recruits, coaches, reporters, and recruiting accounts.
- Categorizes offer activity into SEC, P4, G6 footprint, and hidden gems.
- Filters every board by grad year, position, state, and search text.
- Tracks X link, Hudl link, UC Report link, height, weight, high school, city/state, offer school, strengths, weaknesses, and confidence.
- Encrypts the data file before publishing so the public website does not expose the raw board.
- Can send every new offer to a Discord, Slack, or Teams webhook.

## Important Privacy Note

This is built for a public GitHub Pages website with a password gate. The dashboard data is encrypted before it is deployed, which is much stronger than hiding a normal JSON file behind a login screen.

Still, GitHub Pages is static hosting. It does not provide true server-side authentication. Do not put NCAA-protected, paid database, medical, family, transcript, or internal staff-only notes in this project.

## Beginner Setup

1. Create a public GitHub repository for this folder.
2. In GitHub, open repository Settings, then Secrets and variables, then Actions.
3. Add these repository secrets:

| Secret | Required | What to enter |
| --- | --- | --- |
| `SITE_PASSWORD` | Yes | Your case-sensitive site password |
| `X_BEARER_TOKEN` | Yes for live X monitoring | Bearer token from your X Developer app |
| `OPENAI_API_KEY` | Optional | Adds stronger extraction and brief evaluations |
| `ALERT_WEBHOOK_URL` | Optional | Discord, Slack, or Teams webhook for new-offer alerts |

4. In GitHub Pages settings, choose GitHub Actions as the source.
5. Open the Actions tab and run `Recruiting Offer Agent` once manually.
6. After it finishes, open the Pages URL and enter the site password.

## X Setup

Use the X API v2 Recent Search endpoint. X states that recent search covers posts from the last 7 days and requires an approved developer app plus a bearer token.

Recommended first search strategy:

- Offer phrases: "blessed to receive an offer", "received an offer", "earned an offer", "honored to receive an offer".
- Football terms: QB, RB, WR, TE, OL, DL, LB, DB, ATH, football.
- Location terms inside the Tennessee footprint.
- School names from SEC, P4, and G6 lists.

You can tune the actual queries in `config/search-queries.json`.

## 20-Minute Schedule

GitHub Actions supports scheduled workflows with POSIX cron syntax. This project uses:

```yaml
*/20 * * * *
```

That means every 20 minutes. GitHub can delay scheduled jobs during heavy platform load, so treat the monitor as near-real-time rather than instant.

## Files To Know

| File | Purpose |
| --- | --- |
| `index.html` | Website shell and password gate |
| `styles.css` | Tennessee-inspired visual design |
| `app.js` | Dashboard, filters, decryption, rendering |
| `scripts/update-offers.mjs` | X monitor, parser, scorer, AI evaluator, encryption |
| `scripts/validate-data.mjs` | Checks that encrypted board data is readable and valid |
| `config/search-queries.json` | X queries and trusted handles |
| `config/schools.json` | SEC, P4, G6, and footprint configuration |
| `.github/workflows/recruiting-agent.yml` | Runs the agent every 20 minutes and deploys the site |

## Hidden Gem Scoring

The hidden gem score is a rule-based starting point. It compares height and weight to position profiles, gives extra value to Tennessee-footprint location, looks for production words in the announcement, and discounts players who already have obvious SEC/P4 attention.

This should be treated as a sorting aid, not a final scouting grade.

## Safer Operating Rules

- Use X API access rather than scraping pages.
- Keep paid-site content out of this repo unless you have explicit rights to republish it.
- Keep the password only in GitHub Secrets.
- Rotate the password any time access should change.
- Review the hidden gem formula after a few weeks of real results.

