import { html, nothing, type TemplateResult } from "lit";
import { NeoCard } from "./base-card";
import { available, finite, role } from "./discovery";
export class NeoStatusCard extends NeoCard {
  protected static override displayOptions = ["show_diagnostics"];
  protected override render(): TemplateResult {
    const system = this.system,
      hass = this.hass;
    if (!system || !hass) return this.empty();
    const metrics = [
      { key: "indoor_temperature", title: "Inside", icon: "mdi:home-thermometer-outline" },
      { key: "compressor_power", title: "Compressor power", icon: "mdi:lightning-bolt" },
      { key: "compressor_energy", title: "Estimated energy", icon: "mdi:chart-line" },
      { key: "outdoor_temperature", title: "Outside", icon: "mdi:thermometer" },
    ]
      .map((item) => ({ ...item, state: role(hass, system, item.key, "sensor") }))
      .filter((item) => item.state);
    const filter = role(hass, system, "service_reminder", "sensor");
    const connection = role(hass, system, "connectivity_status", "sensor");
    const diagnostics = this.config.show_diagnostics
      ? [
          ["system_state", "System state"],
          ["system_health", "System health"],
          ["active_warnings", "Warnings"],
        ]
          .map(([key, label]) => ({ label, state: role(hass, system, key ?? "") }))
          .filter((item) => item.state)
      : [];
    return html`<ha-card><div class="content">${this.header("System insights", available(system.climate) ? "Live system readings" : "System unavailable", "mdi:chart-box-outline")}
      ${metrics.length ? html`<div class="stat-grid">${metrics.map((item) => html`<button class="stat" @click=${() => item.state && this.moreInfo(item.state)}><div><ha-icon .icon=${item.icon}></ha-icon><div class="stat-value">${available(item.state) ? this.number(finite(item.state.state), item.key === "compressor_power" ? 0 : 1) : "—"} <small>${typeof item.state?.attributes.unit_of_measurement === "string" ? item.state.attributes.unit_of_measurement : ""}</small></div><div class="secondary">${item.title}</div></div></button>`)}</div>` : html`<div class="notice">No optional system telemetry is enabled. Enable the system's sensors in Home Assistant to show their readings here.</div>`}
      <div class="status-list"><div class="status-line"><span>System</span><span>${available(system.climate) ? "Connected" : "Unavailable"}</span></div>${connection ? html`<div class="status-line"><span>Connection</span><span>${available(connection) ? (hass.formatEntityState?.(connection) ?? connection.state) : "Unavailable"}</span></div>` : nothing}${filter ? html`<div class="status-line"><span>Service reminder</span><span>${available(filter) ? (hass.formatEntityState?.(filter) ?? filter.state) : "Unavailable"}</span></div>` : nothing}${diagnostics.map((item) => html`<div class="status-line"><span>${item.label}</span><span>${available(item.state) ? (hass.formatEntityState?.(item.state) ?? item.state.state) : "Unavailable"}</span></div>`)}</div>
      ${metrics.some((item) => item.key === "compressor_energy") ? html`<p class="secondary" style="margin-block-start:16px">Energy is the integration's cumulative compressor estimate.</p>` : nothing}
    </div></ha-card>`;
  }
  override getCardSize(): number {
    return 4;
  }
}
