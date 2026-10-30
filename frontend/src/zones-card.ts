import { html, nothing, type TemplateResult } from "lit";
import { NeoCard } from "./base-card";
import { FEATURE, steppedTarget } from "./climate-card";
import { available, finite, zones } from "./discovery";
import type { EntityState, Zone } from "./types";
export class NeoZonesCard extends NeoCard {
  protected static override displayOptions = ["show_humidity", "show_dampers"];
  private async target(zone: Zone, delta: number, key = "temperature"): Promise<void> {
    const current =
      this.hass && this.system
        ? zones(this.hass, this.system).find((z) => z.id === zone.id)?.climate
        : undefined;
    if (
      !current ||
      !(
        (finite(current.attributes.supported_features) ?? 0) &
        (key === "temperature" ? FEATURE.TARGET : FEATURE.RANGE)
      )
    )
      return;
    const target = steppedTarget(current, delta, key, this.unit(current));
    if (target === undefined || target === finite(current.attributes[key])) return;
    const other = key === "target_temp_low" ? "target_temp_high" : "target_temp_low";
    const otherTarget = finite(current.attributes[other]);
    if (key !== "temperature" && otherTarget === undefined) return;
    await this.command(
      current,
      "climate",
      "set_temperature",
      key === "temperature" ? { temperature: target } : { [key]: target, [other]: otherTarget },
    );
  }
  private async damper(zone: Zone, event: Event | number): Promise<void> {
    const position =
      typeof event === "number" ? event : Number((event.target as HTMLInputElement).value);
    const cover =
      this.hass && this.system
        ? zones(this.hass, this.system).find((z) => z.id === zone.id)?.damper
        : undefined;
    if (
      !cover ||
      !((finite(cover.attributes.supported_features) ?? 0) & 4) ||
      !Number.isFinite(position) ||
      position < 0 ||
      position > 100
    )
      return;
    await this.command(cover, "cover", "set_cover_position", { position: Math.round(position) });
    this.requestUpdate();
  }
  private targetRow(zone: Zone, state: EntityState, key: string, label: string): TemplateResult {
    const current = finite(state.attributes[key]);
    return html`<div class="inline-target"><span>${label}</span><div class="controls">${[-1, 1].map((delta, index) => html`${index ? html`<span>${this.number(current)} ${this.unit(state)}</span>` : nothing}<button aria-label=${`${delta > 0 ? "Increase" : "Decrease"} ${zone.name} ${label.toLowerCase()}`} ?disabled=${this.busy || !available(this.system?.climate) || !available(state) || steppedTarget(state, delta, key, this.unit(state)) === undefined || steppedTarget(state, delta, key, this.unit(state)) === current} @click=${() => this.target(zone, delta, key)}><ha-icon .icon=${delta > 0 ? "mdi:plus" : "mdi:minus"}></ha-icon></button>`)}</div></div>`;
  }
  private row(zone: Zone): TemplateResult {
    const climate = zone.climate;
    const temp = available(climate)
      ? finite(climate.attributes.current_temperature)
      : available(zone.temperature)
        ? finite(zone.temperature.state)
        : undefined;
    const humidity = available(zone.humidity)
      ? finite(zone.humidity.state)
      : available(climate)
        ? finite(climate.attributes.current_humidity)
        : undefined;
    const enabled = zone.toggle?.state === "on";
    const features = finite(climate?.attributes.supported_features) ?? 0;
    const unit = climate
      ? this.unit(climate)
      : typeof zone.temperature?.attributes.unit_of_measurement === "string"
        ? zone.temperature.attributes.unit_of_measurement
        : this.system
          ? this.unit(this.system.climate)
          : "°C";
    const control = available(climate) && !!(features & (FEATURE.TARGET | FEATURE.RANGE));
    const damper = this.config.show_dampers !== false ? zone.damper : undefined;
    const position = available(damper)
      ? finite(damper.attributes.current_position)
      : available(zone.position)
        ? finite(zone.position.state)
        : undefined;
    const setpoint = finite(damper?.attributes.airflow_setpoint) ?? position;
    const canDamper =
      available(damper) &&
      !!((finite(damper.attributes.supported_features) ?? 0) & 4) &&
      setpoint !== undefined;
    return html`<section class=${`zone ${enabled ? "" : "zone-off"}`} aria-label=${zone.name}><div class="zone-row">
      ${zone.toggle ? html`<button class="icon-button toggle" aria-label=${`${enabled ? "Turn off" : "Turn on"} ${zone.name}`} aria-pressed=${enabled} ?disabled=${this.busy || !available(this.system?.climate) || !available(zone.toggle)} @click=${() => zone.toggle && this.command(zone.toggle, "switch", enabled ? "turn_off" : "turn_on")}><ha-icon icon="mdi:power"></ha-icon></button>` : html`<ha-icon icon="mdi:home-thermometer-outline"></ha-icon>`}
      <div class="zone-text"><span class="zone-name">${zone.name}</span><span class="secondary">${zone.toggle ? (!available(zone.toggle) ? "Unavailable" : enabled ? "On" : "Off") : "Temperature sensor"}${this.config.show_humidity !== false && humidity !== undefined ? ` · ${this.number(humidity, 0)}% humidity` : ""}</span></div>
      <div class="zone-reading">${this.number(temp)}<span class="secondary"> ${unit}</span></div>
    </div>
    ${
      control || damper || position !== undefined
        ? html`<details><summary>${canDamper || position !== undefined ? `Damper ${position === undefined ? "unavailable" : `${this.number(position, 0)}%`}` : "Temperature controls"}</summary><div class="zone-controls">
      ${control && climate ? (features & FEATURE.RANGE && (climate.state === "auto" || climate.state === "heat_cool" || !(features & FEATURE.TARGET)) ? html`${this.targetRow(zone, climate, "target_temp_low", "Heat to")}${this.targetRow(zone, climate, "target_temp_high", "Cool to")}` : this.targetRow(zone, climate, "temperature", "Target")) : nothing}
      ${damper ? html`<label class="field">Airflow setpoint · ${setpoint === undefined ? "unavailable" : `${this.number(setpoint, 0)}%`}<input aria-label=${`${zone.name} airflow`} type="range" min="0" max="100" step="5" .value=${String(setpoint ?? 0)} ?disabled=${!canDamper || this.busy || !available(this.system?.climate)} @change=${(event: Event) => this.damper(zone, event)}></label><div class="inline-target"><button aria-label=${`Decrease ${zone.name} airflow`} ?disabled=${!canDamper || this.busy || !available(this.system?.climate) || (setpoint ?? 0) <= 0} @click=${() => this.damper(zone, Math.max(0, (setpoint ?? 0) - 5))}><ha-icon icon="mdi:minus"></ha-icon></button><span class="secondary">Damper position ${position === undefined ? "unavailable" : `${this.number(position, 0)}%`}</span><button aria-label=${`Increase ${zone.name} airflow`} ?disabled=${!canDamper || this.busy || !available(this.system?.climate) || (setpoint ?? 100) >= 100} @click=${() => this.damper(zone, Math.min(100, (setpoint ?? 0) + 5))}><ha-icon icon="mdi:plus"></ha-icon></button></div>${!canDamper ? html`<div class="secondary">Airflow is read-only or unavailable for this zone.</div>` : nothing}` : nothing}
    </div></details>`
        : nothing
    }</section>`;
  }
  protected override render(): TemplateResult {
    const system = this.system;
    if (!system || !this.hass) return this.empty();
    const list = zones(this.hass, system);
    const active = list.filter((zone) => zone.toggle?.state === "on").length;
    return html`<ha-card><div class="content">${this.header("Your zones", `${active} of ${list.length} zones on`, "mdi:floor-plan")}
      ${!available(system.climate) ? html`<div class="notice" role="status">System unavailable. Controls are disabled.</div>` : nothing}
      ${list.length ? html`<div>${list.map((zone) => this.row(zone))}</div>` : html`<div class="notice">No zones are exposed by the selected system.</div>`}${this.feedback()}</div></ha-card>`;
  }
  override getCardSize(): number {
    return Math.max(3, 1 + (this.hass && this.system ? zones(this.hass, this.system).length : 3));
  }
}
