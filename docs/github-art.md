# GitHub Art

Repository art lives under `assets/`.

## Files

- `assets/readme/hero.png`: README banner, already embedded at the top of `README.md`.
- `assets/social/github-social-preview.png`: upload this in GitHub repository settings as the social preview image.
- `assets/source/ltx-hdr-background.png`: original generated background used by `tools/build_art.py`.

## Updating

After changing `assets/source/ltx-hdr-background.png` or the lockup in `tools/build_art.py`, rebuild:

```bash
python3 tools/build_art.py
```

Then inspect:

- `assets/readme/hero.png`
- `assets/social/github-social-preview.png`

## GitHub Social Preview

GitHub expects a `1280 x 640` image. To set it:

1. Open the repo on GitHub.
2. Go to `Settings`.
3. Scroll to `Social preview`.
4. Upload `assets/social/github-social-preview.png`.
