import { afterEach, describe, expect, it, vi } from "vitest";
import { type NeoClimateCard, steppedTarget } from "../src/climate-card";
import { resolveSystem, zones } from "../src/discovery";
import { registerCards } from "../src/index";
import type { EntityState, HomeAssistant, RegistryEntity } from "../src/types";

registerCards();
const state = (
  id: string,
  attributes: Record<string, unknown> = {},
  value = "cool",
): EntityState => ({ entity_id: id, state: value, attributes });
const climate = state("climate.renamed", {
  temperature: 24,
  current_temperature: 25,
  min_temp: 16,
  max_temp: 30,
  target_temp_step: 0.5,
  temperature_unit: "°C",
  hvac_modes: ["off", "cool", "heat"],
  fan_modes: ["auto", "low", "high"],
  fan_mode: "low",
  supported_features: 393,
});
function fixture(): HomeAssistant {
  return {
    states: { [climate.entity_id]: structuredClone(climate) },
    entities: {
      [climate.entity_id]: {
        entity_id: climate.entity_id,
        platform: "actronair_neo",
        device_id: "one",
        config_entry_id: "entry",
      },
    },
    callWS: vi.fn().mockResolvedValue({
      device_id: "one",
      entry_id: "entry",
      system: { system_climate: climate.entity_id },
      zones: [],
    }),
    callService: vi.fn().mockResolvedValue(undefined),
    language: "en",
    config: { unit_system: { temperature: "°C" } },
  };
}
async function mount(hass: HomeAssistant): Promise<NeoClimateCard> {
  const card = document.createElement("actronair-neo-climate-card") as NeoClimateCard;
  card.setConfig({ type: "custom:actronair-neo-climate-card", device_id: "one" });
  card.hass = hass;
  document.body.append(card);
  await new Promise((resolve) => setTimeout(resolve, 0));
  await card.updateComplete;
  return card;
}
function click(card: NeoClimateCard, selector: string): void {
  const button = card.shadowRoot?.querySelector(selector);
  if (!(button instanceof HTMLButtonElement)) throw new Error(`Missing button ${selector}`);
  button.click();
}
afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});
describe("temperature steps", () => {
  it("clamps bounds and snaps to steps", () => {
    expect(steppedTarget(climate, 100)).toBe(30);
    expect(steppedTarget(climate, -100)).toBe(16);
    expect(steppedTarget(climate, 1)).toBe(24.5);
  });
  it("uses Fahrenheit's default one-degree step", () => {
    const value = state("climate.f", {
      temperature: 72,
      min_temp: 60,
      max_temp: 85,
      temperature_unit: "°F",
    });
    expect(steppedTarget(value, 1)).toBe(73);
  });
  it("never crosses range targets", () => {
    const value = state("climate.range", {
      target_temp_low: 20,
      target_temp_high: 21,
      min_temp: 16,
      max_temp: 30,
      target_temp_step: 0.5,
    });
    expect(steppedTarget(value, 100, "target_temp_low")).toBe(21);
  });
  it("does not fabricate unknown values", () => {
    expect(steppedTarget(state("climate.empty"), 1)).toBeUndefined();
  });
});
describe("discovery", () => {
  it("suggests a device from HA display entries without a config entry id", () => {
    const hass = fixture();
    delete hass.entities?.[climate.entity_id]?.config_entry_id;
    const cardClass = customElements.get("actronair-neo-climate-card") as typeof NeoClimateCard;
    expect(cardClass.getStubConfig(hass).device_id).toBe("one");
    expect(
      resolveSystem(hass, Object.values(hass.entities ?? {}), { type: "test", device_id: "one" }),
    ).toBeUndefined();
  });
  it("drops discovery after the configured device is cleared", async () => {
    const hass = fixture();
    const card = await mount(hass);
    expect(card.shadowRoot?.textContent).toContain("24.0");
    card.setConfig({ type: "custom:actronair-neo-climate-card" });
    await card.updateComplete;
    expect(card.shadowRoot?.textContent).toContain("Select an ActronAir Neo device");
    expect(card.shadowRoot?.querySelector("select")).toBeNull();
  });
  it("rejects foreign and ambiguous systems", () => {
    const hass = fixture();
    const entries = Object.values(hass.entities ?? {});
    expect(resolveSystem(hass, entries, { type: "x", device_id: "foreign" })).toBeUndefined();
  });
  it("uses explicit zone roles despite duplicate names or renamed entities", () => {
    const hass = fixture();
    hass.states["switch.any_name"] = state("switch.any_name", {}, "on");
    const registry: RegistryEntity[] = [
      ...Object.values(hass.entities ?? {}),
      {
        entity_id: "switch.any_name",
        platform: "actronair_neo",
        config_entry_id: "entry",
        device_id: "one",
        zone_id: "zone_2",
        zone_name: "Bedroom",
        translation_key: "zone_enable",
      },
    ];
    const system = resolveSystem(hass, registry, { type: "x", device_id: "one" });
    expect(system).toBeDefined();
    if (!system) throw new Error("Expected system");
    expect(zones(hass, system)[0]?.toggle?.entity_id).toBe("switch.any_name");
  });
});
describe("climate card controls", () => {
  it("sends a bounded service request to the discovered entity and waits for confirmation", async () => {
    const hass = fixture(),
      card = await mount(hass);
    click(card, '[aria-label="Increase target temperature"]');
    await card.updateComplete;
    expect(hass.callService).toHaveBeenCalledWith("climate", "set_temperature", {
      entity_id: climate.entity_id,
      temperature: 24.5,
    });
    expect(card.shadowRoot?.textContent).toContain("Sending command");
    hass.states[climate.entity_id] = state(climate.entity_id, {
      ...climate.attributes,
      temperature: 24.5,
    });
    card.hass = { ...hass };
    await card.updateComplete;
    expect(card.shadowRoot?.textContent).not.toContain("Sending command");
  });
  it("shows errors and re-enables controls after rejection", async () => {
    const hass = fixture();
    hass.callService = vi.fn().mockRejectedValue(new Error("fan rejected"));
    const card = await mount(hass);
    click(card, '[aria-label="Increase target temperature"]');
    await new Promise((resolve) => setTimeout(resolve, 0));
    await card.updateComplete;
    expect(card.shadowRoot?.querySelector('[role="alert"]')?.textContent).toContain(
      "could not be sent",
    );
  });
  it("disables controls for an unavailable system", async () => {
    const hass = fixture();
    hass.states[climate.entity_id] = state(climate.entity_id, climate.attributes, "unavailable");
    const card = await mount(hass);
    const buttons = card.shadowRoot?.querySelectorAll("button") ?? [];
    expect([...buttons].every((button) => button.disabled)).toBe(true);
    expect(hass.callService).not.toHaveBeenCalled();
  });
  it("hides setpoint and fan controls when capabilities are absent", async () => {
    const hass = fixture();
    hass.states[climate.entity_id] = state(
      climate.entity_id,
      { ...climate.attributes, supported_features: 0, temperature: null },
      "fan_only",
    );
    const card = await mount(hass);
    expect(card.shadowRoot?.querySelector('[aria-label="Increase target temperature"]')).toBeNull();
    expect(card.shadowRoot?.querySelector('[aria-label="Fan speed"]')).toBeNull();
  });
  it("rejects mismatched discovery responses", async () => {
    const hass = fixture();
    hass.callWS = vi.fn().mockResolvedValue({
      device_id: "other",
      entry_id: "entry",
      system: { system_climate: climate.entity_id },
      zones: [],
    });
    const card = await mount(hass);
    expect(card.shadowRoot?.textContent).toContain("not readable");
    expect(hass.callService).not.toHaveBeenCalled();
  });
  it("registers each card exactly once", () => {
    registerCards();
    expect(
      window.customCards?.filter((card) => card.type.startsWith("actronair-neo-")).length,
    ).toBe(3);
  });
});
