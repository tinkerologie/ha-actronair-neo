import { NeoClimateCard } from "./climate-card";
import { DOMAIN } from "./discovery";
import { NeoStatusCard } from "./status-card";
import { NeoZonesCard } from "./zones-card";

const cards = [
  [
    "actronair-neo-climate-card",
    NeoClimateCard,
    "ActronAir Neo climate",
    "Neo-style temperature dial, modes, fan speed and quick controls.",
  ],
  [
    "actronair-neo-zones-card",
    NeoZonesCard,
    "ActronAir Neo zones",
    "Zone temperatures, on/off switches and supported airflow controls.",
  ],
  [
    "actronair-neo-status-card",
    NeoStatusCard,
    "ActronAir Neo system",
    "Power, compressor energy, outdoor temperature and system status.",
  ],
] as const;
export function registerCards(): void {
  window.customCards ??= [];
  for (const [type, elementClass, name, description] of cards) {
    if (!customElements.get(type)) customElements.define(type, elementClass);
    if (!window.customCards.some((card) => card.type === type))
      window.customCards.push({
        type,
        name,
        description,
        preview: true,
        documentationURL: "https://github.com/tinkerologie/ha-actronair-neo#dashboard-cards",
        getEntitySuggestion(hass, entityId) {
          const registry = hass.entities?.[entityId],
            state = hass.states[entityId];
          if (
            registry?.platform !== DOMAIN ||
            !entityId.startsWith("climate.") ||
            !state ||
            state.attributes.zone_id ||
            state.attributes.zone_name
          )
            return null;
          return { config: { type: `custom:${type}`, device_id: registry.device_id ?? undefined } };
        },
      });
  }
}
registerCards();
