# aihook Agent Learnings Library

This directory contains agent-specific, reusable learnings about niche topics (e.g., specific Python package quirks, custom workflows) that are too detailed for the main `SKILL.md`.

Each file covers one independent topic, named `topic_<name>.md` (e.g., `topic_numpy.md`, `topic_fastapi.md`). These files are available to all agent sessions when the skill is bootstrapped via `aihook --bootstrap`.

Add your own topic files here as your agents accumulate learnings. The default `README.md` (this file) is copied from the aihook package; user-added files will never be overwritten during bootstrap.
