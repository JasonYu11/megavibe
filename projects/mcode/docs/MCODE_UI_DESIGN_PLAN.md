# Mcode UI Design Plan

## Brand Direction

Mcode is a calm local agent workbench for coding. The product should feel precise, quiet, and technical, with the supplied wave mark used as the primary brand element.

The logo image contributes three brand cues:

- deep navy for trust and depth
- cyan wave lines for active agent motion
- circular mark for a compact app/icon identity

The UI stays mostly light and neutral. Navy and cyan are accents, not page backgrounds.

## Visual System

- Background: warm off-white and cool light gray surfaces.
- Text: near-black primary text, muted gray secondary text.
- Accent: cyan-teal for active states, selected rails, focus, and running indicators.
- Borders: 1px hairlines with low contrast.
- Radius: 6-12px, with the logo using a slightly stronger rounded square container.
- Shadows: only for composer, popovers, and the logo lockup; no decorative glow.

## Logo Usage

- Sidebar lockup: 34px square logo plus `Mcode` wordmark.
- Empty state: 58px logo above the `Mcode` title.
- Browser favicon: cropped logo asset.
- Do not show the original `MEGAWAVE` wordmark inside the UI.

## Layout Principles

- Keep the Codex-style three-column workbench.
- Left sidebar is brand and navigation, not a marketing panel.
- Center workspace remains task-oriented: transcript, tool process, final answer, change review, composer.
- Right dock remains an inspector with compact tabs.
- Composer remains the strongest input surface.

## Component Guidance

- Change review cards keep the highest decision weight.
- Tool cards stay compact and collapsible.
- Running state uses cyan-teal sparingly.
- Avoid large dark-blue surfaces, gradient hero treatments, and decorative card grids.
