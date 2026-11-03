# Submission package

Deadline: **3 Nov 2026, 09:00 PT / 12:00 ET**. One submission per person.

## Links

| Item | URL |
| --- | --- |
| Repository (public, MIT) | https://github.com/nycomar/metamorph |
| Live app | https://metamorph.meet.thoughtful.events/ |
| Gallery of finished runs | https://metamorph.meet.thoughtful.events/gallery |
| Demo video (34 s) | https://share.dev13.apextech.agency/metamorph-tests/metamorph-demo.mp4 |
| Example clip — skeleton | https://share.dev13.apextech.agency/metamorph-tests/skeleton-h3.mp4 |
| Example clip — ring | https://share.dev13.apextech.agency/metamorph-tests/four-stages.mp4 |
| Workflow graphs (UI format) | https://github.com/nycomar/metamorph/tree/main/workflows/ui |

## Social post (draft — post from your own account, then paste the link into the form)

> Turned one photo of a skeleton into fossil → marble → brass in a single unbroken shot, with sound.
>
> Built for the Comfy Open Source Higgsfield challenge: ComfyUI + Comfy Cloud, SDXL for the stage images,
> H3/LTX-2.5 for the video. The stages are pinned inside one generation, so nothing is stitched.
>
> Repo: https://github.com/nycomar/metamorph
> #OpenSourceHiggsfield

Adjust tone as you like; the only requirement is the hashtag.

## Form answers

- **Repo:** https://github.com/nycomar/metamorph
- **Demo video:** the share link above
- **Live link:** https://metamorph.meet.thoughtful.events/
- **What it is:** one photo in, 1–5 described destinations out, rendered as a single continuous metamorphosis shot with synchronized audio.
- **How it is built:** Comfy Cloud runs a stage graph (SDXL + depth ControlNet + IPAdapter) and one video pass (MiniMax H3 by default; LTX-2.5 as the open-weights alternative). Stage images are pinned to frames as guides; the motion between them is generated, not interpolated.
- **Stack:** FastAPI + `comfy-sdk`, SQLite, React + Vite, ffmpeg, Caddy + systemd.

## Checklist

- [x] Public repo with code, workflow JSONs (API and UI format), MIT licence
- [x] README that works on a clean clone (verified in a fresh directory: venv + pip install + `import app.main`, `npm ci` + `npm run build`)
- [x] README records the prompt finding (describe the destination, never narrate the transformation)
- [x] Demo video under 2 minutes, with sound
- [x] Live app that a stranger can use
- [x] Lawful, SFW, no unlicensed likenesses (test images are synthetic or user-supplied)
- [ ] Social post published, link captured
- [ ] Typeform submitted, confirmation screenshotted

## Known gaps, stated honestly

- The demo video is assembled from screen captures of the live app plus real generated clips, not a continuous screen recording. It shows the work rather than a cursor moving.
- The `pick` state is per-project; there is no multi-user auth, by design for a one-night build.
- Rate limiting is per IP with a global daily cap; there is no account system.
