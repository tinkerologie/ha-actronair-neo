import { html, nothing, type TemplateResult } from "lit";
import { styleMap } from "lit/directives/style-map.js";
import { MODE_LABELS, NeoCard } from "./base-card";
import { available, finite, role, strings } from "./discovery";
import type { EntityState } from "./types";
export const FEATURE = { TARGET: 1, RANGE: 2, FAN: 8, OFF: 128, ON: 256 };
const ACCENTS: Record<string, string> = {
  cool: "var(--state-climate-cool-color, var(--primary-color, #0288d1))",
  heat: "var(--state-climate-heat-color, var(--warning-color, #e57920))",
  auto: "var(--state-climate-auto-color, var(--accent-color, #8e44ad))",
  heat_cool: "var(--state-climate-heat-cool-color, var(--accent-color, #8e44ad))",
  fan_only: "var(--state-climate-fan-only-color, var(--primary-color, #00a49b))",
  dry: "var(--state-climate-dry-color, var(--primary-color, #c89b20))",
  off: "var(--disabled-text-color, #777)",
};
export function steppedTarget(
  state: EntityState,
  delta: number,
  key = "temperature",
  unit?: string,
): number | undefined {
  const current = finite(state.attributes[key]);
  const min = finite(state.attributes.min_temp),
    max = finite(state.attributes.max_temp);
  const step =
    finite(state.attributes.target_temp_step) ??
    ((unit ?? state.attributes.temperature_unit) === "°F" ? 1 : 0.5);
  if (current === undefined || min === undefined || max === undefined || step <= 0 || min > max)
    return undefined;
  let low = min,
    high = max;
  if (key === "target_temp_low")
    high = Math.min(high, finite(state.attributes.target_temp_high) ?? high);
  if (key === "target_temp_high")
    low = Math.max(low, finite(state.attributes.target_temp_low) ?? low);
  return (
    Math.round(
      Math.min(
        high,
        Math.max(low, min + Math.round((current + delta * step - min) / step) * step),
      ) * 1000,
    ) / 1000
  );
}
export class NeoClimateCard extends NeoCard {
  protected async adjust(delta: number, key = "temperature"): Promise<void> {
    const state = this.system?.climate;
    if (!state) return;
    const features = finite(state.attributes.supported_features) ?? 0;
    if (!(features & (key === "temperature" ? FEATURE.TARGET : FEATURE.RANGE))) return;
    const target = steppedTarget(state, delta, key, this.unit(state));
    if (target === undefined || target === finite(state.attributes[key])) return;
    const range = key !== "temperature";
    const other = key === "target_temp_low" ? "target_temp_high" : "target_temp_low";
    const otherValue = finite(state.attributes[other]);
    if (range && otherValue === undefined) return;
    await this.command(
      state,
      "climate",
      "set_temperature",
      range ? { [key]: target, [other]: otherValue } : { temperature: target },
    );
  }
  private async duration(event: Event): Promise<void> {
    if (!this.hass || !this.system) return;
    const entity = role(this.hass, this.system, "after_hours_duration", "number");
    const value = Number((event.target as HTMLInputElement).value);
    const min = finite(entity?.attributes.min),
      max = finite(entity?.attributes.max),
      step = finite(entity?.attributes.step);
    if (
      !entity ||
      !available(entity) ||
      !Number.isFinite(value) ||
      min === undefined ||
      max === undefined ||
      step === undefined ||
      step <= 0
    )
      return;
    const target = Math.min(max, Math.max(min, min + Math.round((value - min) / step) * step));
    await this.command(entity, "number", "set_value", { value: target });
  }
  private async mode(event: Event): Promise<void> {
    const state = this.system?.climate,
      value = (event.target as HTMLSelectElement).value;
    if (state && strings(state.attributes.hvac_modes).includes(value))
      await this.command(state, "climate", "set_hvac_mode", { hvac_mode: value });
    this.requestUpdate();
  }
  private async fan(event: Event): Promise<void> {
    const state = this.system?.climate,
      value = (event.target as HTMLSelectElement).value;
    if (
      state &&
      (finite(state.attributes.supported_features) ?? 0) & FEATURE.FAN &&
      strings(state.attributes.fan_modes).includes(value)
    )
      await this.command(state, "climate", "set_fan_mode", { fan_mode: value });
    this.requestUpdate();
  }
  private async power(): Promise<void> {
    const state = this.system?.climate;
    if (!state) return;
    const feature = state.state === "off" ? FEATURE.ON : FEATURE.OFF;
    if ((finite(state.attributes.supported_features) ?? 0) & feature)
      await this.command(state, "climate", state.state === "off" ? "turn_on" : "turn_off");
  }
  private stepButton(state: EntityState, delta: number, key = "temperature"): TemplateResult {
    const value = steppedTarget(state, delta, key, this.unit(state));
    const targetName =
      key === "target_temp_low" ? "heating" : key === "target_temp_high" ? "cooling" : "target";
    return html`<button aria-label=${`${delta > 0 ? "Increase" : "Decrease"} ${targetName} temperature`} ?disabled=${this.busy || !available(state) || value === undefined || value === finite(state.attributes[key])} @click=${() => this.adjust(delta, key)}><ha-icon .icon=${delta > 0 ? "mdi:plus" : "mdi:minus"}></ha-icon></button>`;
  }
  protected override render(): TemplateResult {
    const system = this.system,
      hass = this.hass;
    if (!system || !hass) return this.empty();
    const state = system.climate,
      attrs = state.attributes,
      enabled = available(state);
    const features = finite(attrs.supported_features) ?? 0;
    const modes = strings(attrs.hvac_modes),
      fans = strings(attrs.fan_modes);
    const target = finite(attrs.temperature),
      current = finite(attrs.current_temperature),
      humidity = finite(attrs.current_humidity);
    const min = finite(attrs.min_temp),
      max = finite(attrs.max_temp);
    const fraction =
      target !== undefined && min !== undefined && max !== undefined && max > min
        ? Math.max(0, Math.min(1, (target - min) / (max - min)))
        : 0;
    const range =
      !!(features & FEATURE.RANGE) &&
      (state.state === "heat_cool" || state.state === "auto" || !(features & FEATURE.TARGET));
    const action =
      typeof attrs.hvac_action === "string"
        ? ({
            cooling: "Cooling",
            heating: "Heating",
            idle: "At temperature",
            fan: "Fan running",
            drying: "Drying",
            off: "Off",
          }[attrs.hvac_action] ?? MODE_LABELS[state.state])
        : MODE_LABELS[state.state];
    const powerFeature = state.state === "off" ? FEATURE.ON : FEATURE.OFF;
    const duration = role(hass, system, "after_hours_duration", "number");
    const quick = [
      ["quiet_mode", "Quiet", "mdi:volume-low"],
      ["away_mode", "Away", "mdi:home-export-outline"],
      ["continuous_fan", "Continuous fan", "mdi:fan"],
      ["turbo_mode", "Turbo", "mdi:weather-windy"],
      ["after_hours", "After hours", "mdi:timer-outline"],
    ]
      .map(([key, label, icon]) => ({
        state: role(hass, system, key ?? "", "switch"),
        label: label ?? "",
        icon: icon ?? "",
      }))
      .filter((item): item is typeof item & { state: EntityState } => !!item.state);
    return html`<ha-card style=${styleMap({ "--neo-accent": ACCENTS[state.state] ?? ACCENTS.cool })}><div class="content">
      ${this.header(this.name(state, "Climate"), enabled ? (action ?? state.state) : "Unavailable", "mdi:thermostat", features & powerFeature ? html`<button class="icon-button power" aria-label=${state.state === "off" ? "Turn system on" : "Turn system off"} aria-pressed=${state.state !== "off" && enabled} ?disabled=${!enabled || this.busy} @click=${this.power}><ha-icon icon="mdi:power"></ha-icon></button>` : nothing)}
      <div class="metrics"><div><div class="metric-value">${enabled ? this.number(current) : "—"}<small> ${this.unit(state)}</small></div><div class="secondary">Inside temperature</div></div>${this.config.show_humidity !== false && humidity !== undefined ? html`<div><div class="metric-value">${enabled ? this.number(humidity, 0) : "—"}<small> %</small></div><div class="secondary">Humidity</div></div>` : nothing}</div>
      <div class="dial-wrap" role="img" aria-label=${enabled ? `Target ${target ?? "not set"} ${this.unit(state)}, ${action ?? state.state}` : "System unavailable"}>
        <svg class="dial" viewBox="0 0 120 120" aria-hidden="true"><circle class="track" cx="60" cy="60" r="52" stroke-dasharray="245 327"></circle><circle class="arc" cx="60" cy="60" r="52" stroke-dasharray=${`${enabled ? fraction * 245 : 0} 327`}></circle></svg>
        <div class="dial-content"><div class="target">${!enabled ? "—" : range ? "Auto" : target !== undefined ? this.number(target) : (MODE_LABELS[state.state] ?? "—")}${!range && target !== undefined && enabled ? html`<span class="unit">${this.unit(state)}</span>` : nothing}</div><div class="dial-caption">${!enabled ? "System unavailable" : range ? "Heating & cooling range" : target !== undefined ? "Target temperature" : state.state === "off" ? "Choose a mode to start" : "Temperature managed by system"}</div><div class="state-label">${enabled ? action : "Unavailable"}</div></div>
      </div>
      ${!range && features & FEATURE.TARGET && target !== undefined ? html`<div class="steppers">${this.stepButton(state, -1)}${this.stepButton(state, 1)}</div>` : nothing}
      ${
        range
          ? html`<div class="range-targets">${(
              [
                ["target_temp_low", "Heat to"],
                ["target_temp_high", "Cool to"],
              ] as const
            ).map(
              ([key, label]) =>
                html`<div><div class="secondary">${label}</div><div class="controls">${this.stepButton(state, -1, key)}<span>${enabled ? this.number(finite(attrs[key])) : "—"}°</span>${this.stepButton(state, 1, key)}</div></div>`,
            )}</div>`
          : nothing
      }
      <div class="selectors"><label class="field">Mode<select aria-label="HVAC mode" .value=${state.state} ?disabled=${!enabled || this.busy || !modes.length} @change=${this.mode}>${modes.map((mode) => html`<option .value=${mode} ?selected=${mode === state.state}>${MODE_LABELS[mode] ?? mode}</option>`)}</select></label>${features & FEATURE.FAN && fans.length ? html`<label class="field">Fan speed<select aria-label="Fan speed" .value=${attrs.fan_mode ?? ""} ?disabled=${!enabled || this.busy} @change=${this.fan}>${fans.map((fan) => html`<option .value=${fan} ?selected=${fan === attrs.fan_mode}>${fan === "auto" ? "Auto" : fan.charAt(0).toUpperCase() + fan.slice(1)}</option>`)}</select></label>` : nothing}</div>
      ${this.config.show_options !== false && (quick.length || duration) ? html`<details><summary>Options</summary><div class="options">${quick.map((item) => html`<button class="option" aria-pressed=${item.state.state === "on"} ?disabled=${!enabled || !available(item.state) || this.busy} @click=${() => this.command(item.state, "switch", item.state.state === "on" ? "turn_off" : "turn_on")}><ha-icon .icon=${item.icon}></ha-icon>${item.label}</button>`)}</div>${duration ? html`<label class="field" style="margin-block-start:12px">After-hours duration (${typeof duration.attributes.unit_of_measurement === "string" ? duration.attributes.unit_of_measurement : "min"})<input aria-label="After-hours duration" type="number" .value=${available(duration) ? duration.state : ""} min=${finite(duration.attributes.min) ?? 0} max=${finite(duration.attributes.max) ?? 0} step=${finite(duration.attributes.step) ?? 1} ?disabled=${!enabled || !available(duration) || this.busy || finite(duration.attributes.min) === undefined || finite(duration.attributes.max) === undefined || finite(duration.attributes.step) === undefined} @change=${this.duration}></label>` : nothing}</details>` : nothing}
      ${this.feedback()}</div></ha-card>`;
  }
  override getCardSize(): number {
    return 7;
  }
}
