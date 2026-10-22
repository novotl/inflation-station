<!--
Title: imperative, ≤60 chars, no prefix. It becomes the squash-merge subject in `git log`.
Body: ≤15 lines, not counting the diff sketch. Written for the owner in 6 months. No test plan: CI verifies.
-->

## 🎯 Why

<!-- One line that distils the issue. -->

Closes #

## 🔧 What

- <!-- What changed, one bullet each. Optional: a diff sketch, tree or pseudocode block, only if it saves words. -->

## 🚪 Risk

<!--
↩️ two-way · <blast radius>                  `git revert` fully undoes it
⚠️ one-way · <blast radius> · <what is lost, how to recover>   something outside git changes (stored data, schema, settings)
Blast radius: 1–2 words on what breaks if it's wrong, e.g. imports, CLI output, charts, stored data, CI, agent config.
-->
↩️ two-way ·
