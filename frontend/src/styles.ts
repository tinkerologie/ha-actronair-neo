import { css } from "lit";
export const cardStyles = css`
  :host { display: block; container-type: inline-size; --neo-accent: var(--state-climate-cool-color, var(--primary-color, #0288d1)); color: var(--primary-text-color, #202124); font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, sans-serif)); }
  * { box-sizing: border-box; }
  ha-card { display: block; height: 100%; overflow: hidden; border-radius: var(--ha-card-border-radius, var(--ha-border-radius-xl, 20px)); background: var(--ha-card-background, var(--card-background-color, #fff)); color: inherit; }
  .content { padding: var(--ha-space-5, 20px); }
  header { display: flex; align-items: center; gap: 12px; margin-block-end: 20px; }
  h2, h3, p { margin: 0; }
  h2 { font-size: var(--ha-font-size-l, 20px); line-height: 1.3; font-weight: 600; overflow-wrap: anywhere; }
  h3 { font-size: 15px; font-weight: 600; }
  .heading { flex: 1; min-width: 0; }
  .eyebrow { font-size: 11px; line-height: 1.5; letter-spacing: .12em; text-transform: uppercase; color: var(--secondary-text-color, #666); font-weight: 600; margin-block-end: 3px; }
  .secondary { color: var(--secondary-text-color, #666); font-size: 13px; line-height: 1.5; }
  .state-label { display: inline-flex; gap: 6px; align-items: center; color: var(--primary-text-color, #202124); font-size: 12px; font-weight: 600; }
  ha-icon { --mdc-icon-size: 20px; flex-shrink: 0; }
  button, select, input { font: inherit; color: inherit; }
  button { cursor: pointer; border: 0; background: transparent; min-height: 44px; min-width: 44px; border-radius: var(--ha-border-radius-lg, 12px); display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
  button:focus-visible, select:focus-visible, input:focus-visible, summary:focus-visible { outline: 3px solid var(--primary-color, #0288d1); outline-offset: 3px; }
  button:disabled, select:disabled, input:disabled { cursor: default; opacity: .42; }
  button:not(:disabled):hover { background: var(--secondary-background-color, #f3f4f6); }
  .icon-button { border-radius: 50%; background: var(--secondary-background-color, #f3f4f6); }
  .power[aria-pressed=true], .toggle[aria-pressed=true] { color: var(--neo-accent); background: color-mix(in srgb, var(--neo-accent) 13%, transparent); }
  .metrics { display: flex; justify-content: center; gap: 24px; margin-block: 4px 20px; text-align: center; }
  .metric-value { font-size: 20px; font-variant-numeric: tabular-nums; }
  .metrics > div + div { border-inline-start: 1px solid var(--divider-color, #ddd); padding-inline-start: 24px; }
  .dial-wrap { display: grid; place-items: center; position: relative; margin-inline: auto; width: min(100%, 260px); aspect-ratio: 1; }
  .dial { width: 100%; height: 100%; transform: rotate(135deg); overflow: visible; }
  .track, .arc { fill: none; stroke-width: 4; stroke-linecap: round; }
  .track { stroke: var(--divider-color, #ddd); }
  .arc { stroke: var(--neo-accent); transition: stroke-dasharray .2s ease; }
  .dial-content { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; flex-direction: column; }
  .target { font-size: clamp(44px, 18cqi, 64px); line-height: 1.1; font-weight: 300; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
  .target .unit { font-size: .32em; letter-spacing: 0; margin-inline-start: 3px; vertical-align: super; }
  .dial-caption { margin-block-start: 8px; color: var(--secondary-text-color, #666); font-size: 12px; }
  .steppers { display: flex; justify-content: center; gap: 40px; margin-block: -16px 24px; position: relative; }
  .steppers button { border: 1px solid var(--divider-color, #ddd); border-radius: 50%; background: var(--card-background-color, #fff); }
  .range-targets { display: flex; gap: 10px; margin-block-end: 16px; }
  .range-targets > div { flex: 1; background: var(--secondary-background-color, #f3f4f6); border-radius: 14px; padding: 8px; text-align: center; }
  .range-targets .controls { display: flex; align-items: center; justify-content: space-between; font-size: 20px; }
  .selectors { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  label.field { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--secondary-text-color, #666); }
  select { width: 100%; min-height: 44px; padding-inline: 12px; border: 1px solid var(--divider-color, #ddd); border-radius: 12px; color: var(--primary-text-color, #202124); background: var(--card-background-color, #fff); }
  details { border-block-start: 1px solid var(--divider-color, #ddd); margin-block-start: 20px; padding-block-start: 4px; }
  summary { min-height: 44px; cursor: pointer; font-size: 13px; font-weight: 600; padding-block: 12px; }
  .options { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .option { background: var(--secondary-background-color, #f3f4f6); font-size: 12px; justify-content: flex-start; padding-inline: 12px; }
  .option[aria-pressed=true] { color: var(--primary-text-color, #202124); background: color-mix(in srgb, var(--neo-accent) 13%, transparent); }
  .error { margin-block: 12px 0; padding: 12px; background: var(--ha-color-fill-danger-quiet-resting, color-mix(in srgb, var(--error-color, #db4437) 12%, transparent)); border-radius: 12px; color: var(--error-color, #b3261e); font-size: 13px; }
  .notice { padding: 24px 12px; text-align: center; color: var(--secondary-text-color, #666); font-size: 14px; line-height: 1.6; }
  .pending { font-size: 12px; color: var(--secondary-text-color, #666); margin-block-start: 12px; }
  .zone { padding-block: 14px; border-block-start: 1px solid var(--divider-color, #ddd); }
  .zone:first-child { border-block-start: 0; padding-block-start: 0; }
  .zone-row { display: flex; align-items: center; gap: 12px; }
  .zone-text { flex: 1; min-width: 0; }
  .zone-name { display: block; font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
  .zone-reading { font-size: 20px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .zone-off .zone-name { color: var(--secondary-text-color, #666); }
  .zone details { border: 0; margin: 4px 0 0; padding: 0; }
  .zone summary { color: var(--secondary-text-color, #666); font-weight: 400; padding-inline-start: 56px; }
  .zone-controls { padding: 8px 0 4px 56px; }
  .inline-target { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-block-end: 12px; }
  .inline-target span { font-size: 14px; }
  input[type=range] { width: 100%; min-height: 44px; accent-color: var(--neo-accent); cursor: pointer; }
  .stat-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .stat { padding: 16px; border-radius: 16px; background: var(--secondary-background-color, #f3f4f6); }
  .stat ha-icon { color: var(--neo-accent); margin-block-end: 12px; }
  .stat-value { font-size: 26px; font-weight: 500; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  .stat-value small { font-size: 12px; font-weight: 400; }
  .status-list { margin-block-start: 16px; display: grid; gap: 12px; }
  .status-line { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 13px; }
  .status-line span:first-child { color: var(--secondary-text-color, #666); }
  @container (max-width: 310px) { .content { padding: 16px; } .selectors, .options { grid-template-columns: 1fr; } .zone-row { gap: 8px; } .zone-controls { padding-inline-start: 0; } .stat { padding: 12px; } }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
`;
