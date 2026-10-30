import type { CardConfig, EntityState, HomeAssistant, RegistryEntity, System, Zone } from "./types";
export const DOMAIN = "actronair_neo";
export const available = (state?: EntityState): state is EntityState =>
  !!state && !["unknown", "unavailable"].includes(state.state);
export const finite = (raw: unknown): number | undefined =>
  (typeof raw === "number" || (typeof raw === "string" && raw.trim() !== "")) &&
  Number.isFinite(Number(raw))
    ? Number(raw)
    : undefined;
export const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
export function systemCandidates(
  hass: HomeAssistant,
  registry: RegistryEntity[],
): RegistryEntity[] {
  return registry.filter((e) => {
    const state = hass.states[e.entity_id];
    return (
      e.platform === DOMAIN &&
      !e.disabled_by &&
      e.device_id &&
      e.entity_id.startsWith("climate.") &&
      state &&
      !e.zone_id &&
      !state.attributes.zone_id &&
      !state.attributes.zone_name
    );
  });
}
export function resolveSystem(
  hass: HomeAssistant,
  registry: RegistryEntity[],
  config: CardConfig,
): System | undefined {
  let candidates = systemCandidates(hass, registry);
  if (config.entity) candidates = candidates.filter((e) => e.entity_id === config.entity);
  if (config.device_id) candidates = candidates.filter((e) => e.device_id === config.device_id);
  // Never fall through from a missing explicit selection, or guess across systems.
  if (candidates.length !== 1) return undefined;
  const selected = candidates[0];
  if (!selected?.device_id || !selected.config_entry_id) return undefined;
  const climate = hass.states[selected.entity_id];
  if (!climate) return undefined;
  return {
    climate,
    deviceId: selected.device_id,
    entryId: selected.config_entry_id,
    entities: registry.filter(
      (e) =>
        e.platform === DOMAIN &&
        e.device_id === selected.device_id &&
        e.config_entry_id === selected.config_entry_id &&
        !e.disabled_by,
    ),
  };
}
export function role(
  hass: HomeAssistant,
  system: System,
  key: string,
  domain?: string,
): EntityState | undefined {
  const matches = system.entities.filter(
    (e) =>
      e.translation_key === key &&
      (!domain || e.entity_id.startsWith(`${domain}.`)) &&
      !e.zone_id &&
      !hass.states[e.entity_id]?.attributes.zone_id,
  );
  return matches.length === 1 ? hass.states[matches[0]?.entity_id ?? ""] : undefined;
}
export function zones(hass: HomeAssistant, system: System): Zone[] {
  const result = new Map<string, Zone>();
  for (const entry of system.entities) {
    const state = hass.states[entry.entity_id];
    const id = entry.zone_id;
    if (!state || typeof id !== "string" || !/^zone_\d+$/.test(id)) continue;
    const zone = result.get(id) ?? {
      id,
      name: typeof entry.zone_name === "string" ? entry.zone_name : `Zone ${id.split("_")[1]}`,
    };
    const domain = entry.entity_id.split(".")[0];
    if (domain === "climate") zone.climate = state;
    else if (domain === "switch" && entry.translation_key === "zone_enable") zone.toggle = state;
    else if (domain === "cover" && entry.translation_key === "zone_damper") zone.damper = state;
    else if (domain === "sensor" && entry.translation_key === "zone_temperature")
      zone.temperature = state;
    else if (domain === "sensor" && entry.translation_key === "zone_humidity")
      zone.humidity = state;
    else if (domain === "sensor" && entry.translation_key === "zone_damper_position")
      zone.position = state;
    result.set(id, zone);
  }
  return [...result.values()].sort(
    (a, b) => Number(a.id.split("_")[1]) - Number(b.id.split("_")[1]),
  );
}
interface DiscoveryData {
  entry_id: string;
  device_id: string;
  system: Record<string, string>;
  zones: { zone_id: string; name: string; roles: Record<string, string> }[];
}
interface Store {
  listeners: Set<(registry: RegistryEntity[] | undefined, error?: string) => void>;
  registry?: RegistryEntity[];
  unsubscribe?: () => void;
  closed: boolean;
  revision: number;
  retryAttempt: number;
  retryTimer?: ReturnType<typeof setTimeout>;
  refresh: () => void;
}
const stores = new WeakMap<object, Map<string, Store>>();
export function subscribeDiscovery(
  hass: HomeAssistant,
  deviceId: string,
  callback: (registry: RegistryEntity[] | undefined, error?: string) => void,
): { unsubscribe: () => void; refresh: () => void } {
  const key = hass.connection ?? hass;
  let devices = stores.get(key);
  if (!devices) {
    devices = new Map();
    stores.set(key, devices);
  }
  let store = devices.get(deviceId);
  if (!store) {
    store = {
      listeners: new Set(),
      closed: false,
      revision: 0,
      retryAttempt: 0,
      refresh: () => {},
    };
    devices.set(deviceId, store);
    const current = store;
    const refresh = async () => {
      if (current.closed) return;
      if (current.retryTimer) clearTimeout(current.retryTimer);
      current.retryTimer = undefined;
      const revision = ++current.revision;
      try {
        const data = await hass.callWS<DiscoveryData>({
          type: "actronair_neo/dashboard/discover",
          device_id: deviceId,
        });
        if (current.closed || revision !== current.revision) return;
        if (data.device_id !== deviceId) throw new Error("Discovery device mismatch");
        const registry: RegistryEntity[] = [];
        const append = (
          roles: Record<string, string>,
          zone?: { zone_id: string; name: string },
        ) => {
          for (const [role, entity_id] of Object.entries(roles))
            registry.push({
              entity_id,
              platform: DOMAIN,
              config_entry_id: data.entry_id,
              device_id: data.device_id,
              translation_key: role,
              dashboard_role: role,
              zone_id: zone?.zone_id,
              zone_name: zone?.name,
            });
        };
        append(data.system);
        for (const zone of data.zones) append(zone.roles, zone);
        current.retryAttempt = 0;
        current.registry = registry;
        for (const listener of current.listeners) listener(registry);
      } catch {
        if (!current.closed && revision === current.revision) {
          current.registry = undefined;
          for (const listener of current.listeners)
            listener(
              undefined,
              "This system is not available or not readable by your account. Check the selected device and reconnect.",
            );
          // A reconnect can precede the integration's loaded state. Share at
          // most six retries across cards, and cancel them on success/unload.
          if (current.retryAttempt < 6) {
            const delay = Math.min(1000 * 2 ** current.retryAttempt++, 30000);
            current.retryTimer = setTimeout(() => void refresh(), delay);
          }
        }
      }
    };
    current.refresh = () => {
      current.retryAttempt = 0;
      void refresh();
    };
    hass.connection?.addEventListener?.("ready", current.refresh);
    if (hass.connection)
      void hass.connection
        .subscribeEvents(current.refresh, "entity_registry_updated")
        .then((unsubscribe) => {
          if (current.closed) unsubscribe();
          else current.unsubscribe = unsubscribe;
          current.refresh();
        })
        .catch(current.refresh);
    else current.refresh();
  }
  store.listeners.add(callback);
  if (store.registry) callback(store.registry);
  const current = store;
  return {
    refresh: current.refresh,
    unsubscribe: () => {
      current.listeners.delete(callback);
      if (!current.listeners.size) {
        current.closed = true;
        if (current.retryTimer) clearTimeout(current.retryTimer);
        current.unsubscribe?.();
        hass.connection?.removeEventListener?.("ready", current.refresh);
        devices?.delete(deviceId);
        if (!devices?.size) stores.delete(key);
      }
    },
  };
}
