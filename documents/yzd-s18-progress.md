# YZD-S18 build implementation ledger

Plan: user-approved Bookworm USB system / GitHub Actions, 2026-10-08.
Base commit: 7d81e344. Work on main was explicitly requested.

- Inputs: existing USB-fix kernel, fixed clean Bookworm base, validated Mali,
  vendor video firmware and patched FFmpeg; no damaged rootfs copying.
- Interfaces: published input lock feeds builder; builder generates image.json;
  runtime tools consume that manifest; workflow publishes only verified output.
- Ruling: use a dedicated YZD dispatch in rebuild, sharing the repository's
  platform/common overlay, instead of applying vendor assumptions to all boards.
  This avoids altering existing board builds and permits read-only base input.
- Safety RED: missing cleanup helper detected by busy-mount regression.
