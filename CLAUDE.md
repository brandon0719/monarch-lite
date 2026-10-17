# monarch-lite: agent guide

- **Read `docs/BRD.md` first.** It is the source of truth for scope. Cite requirement IDs (`FR-<MOD>-NN`) in specs, plans, and commit messages.
- **Workflow:** for non-trivial work, invoke `superpowers:using-superpowers`. The path is `brainstorming`, then a spec in `docs/superpowers/specs/`, then `writing-plans`, then `test-driven-development`. Build one BRD milestone (M1–M5) per spec.
- **Keep it small (ponytail):** make the smallest complete change and add nothing "for later". Requirements marked Won't-have stay out.
- **Frontend:** invoke `minimalist-ui` before touching any UI. Invoke `dataviz` before any chart.
- **Secrets:** only in `.env`. Never commit `.env` or `*.db`.
- **Prior art:** `~/Coding/FInance Tracker` has a working SimpleFIN client, tax calculator, and 50/30/20 budget. Read it for ideas, but don't import from it.
