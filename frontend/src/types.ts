export interface EntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
  last_changed?: string;
}
export interface RegistryEntity {
  entity_id: string;
  platform: string;
  device_id: string | null;
  config_entry_id?: string | null;
  translation_key?: string | null;
  disabled_by?: string | null;
  unique_id?: string;
  dashboard_role?: string;
  zone_id?: string;
  zone_name?: string;
}
export interface HomeAssistant {
  states: Record<string, EntityState>;
  entities?: Record<string, RegistryEntity>;
  devices?: Record<string, { name: string | null; name_by_user?: string | null }>;
  language?: string;
  locale?: { language?: string };
  config?: { unit_system?: { temperature?: string } };
  connection?: {
    addEventListener?(event: "ready", callback: () => void): void;
    removeEventListener?(event: "ready", callback: () => void): void;
    subscribeEvents(callback: () => void, event: string): Promise<() => void>;
  };
  callWS<T>(message: Record<string, unknown>): Promise<T>;
  callService(domain: string, service: string, data: Record<string, unknown>): Promise<unknown>;
  localize?(key: string): string | undefined;
  formatEntityState?(entity: EntityState): string;
  formatEntityName?(entity: EntityState): string;
}
export interface CardConfig {
  type: string;
  entity?: string;
  device_id?: string;
  title?: string;
  show_options?: boolean;
  show_diagnostics?: boolean;
  show_humidity?: boolean;
  show_dampers?: boolean;
  compact?: boolean;
}
export interface System {
  climate: EntityState;
  deviceId: string;
  entryId: string;
  entities: RegistryEntity[];
}
export interface Zone {
  id: string;
  name: string;
  climate?: EntityState;
  toggle?: EntityState;
  temperature?: EntityState;
  humidity?: EntityState;
  damper?: EntityState;
  position?: EntityState;
}
export interface CustomCard {
  type: string;
  name: string;
  description: string;
  preview: boolean;
  documentationURL: string;
  getEntitySuggestion?(hass: HomeAssistant, entityId: string): { config: CardConfig } | null;
}
declare global {
  interface Window {
    customCards?: CustomCard[];
  }
}
