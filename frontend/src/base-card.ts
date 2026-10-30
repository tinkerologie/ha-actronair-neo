import { html, LitElement, nothing, type PropertyValues, type TemplateResult } from "lit";
import { available, resolveSystem, subscribeDiscovery, systemCandidates } from "./discovery";
import { cardStyles } from "./styles";
import type { CardConfig, EntityState, HomeAssistant, RegistryEntity, System } from "./types";
export const MODE_LABELS: Record<string, string> = {
  cool: "Cool",
  heat: "Heat",
  heat_cool: "Heat / cool",
  auto: "Auto",
  dry: "Dry",
  fan_only: "Fan only",
  off: "Off",
};
export abstract class NeoCard extends LitElement {
  static override styles = cardStyles;
  protected static displayOptions: readonly string[] = ["show_options", "show_humidity"];
  static override properties = {
    hass: { attribute: false },
    config: { state: true },
    registry: { state: true },
    error: { state: true },
    busy: { state: true },
    discoveryError: { state: true },
  };
  declare hass?: HomeAssistant;
  declare protected config: CardConfig;
  declare protected registry?: RegistryEntity[];
  declare protected error: string;
  declare protected busy: boolean;
  declare protected discoveryError: string;
  private subscription?: { unsubscribe: () => void; refresh: () => void };
  private deviceId?: string;
  private registryReference?: HomeAssistant["entities"];
  private connection?: object;
  private pendingId?: string;
  private pendingState?: EntityState;
  private pendingTimer?: ReturnType<typeof setTimeout>;
  private requestId = 0;
  constructor() {
    super();
    this.config = { type: "" };
    this.error = "";
    this.busy = false;
    this.discoveryError = "";
  }
  setConfig(config: CardConfig): void {
    if (!config || typeof config.type !== "string")
      throw new Error("Invalid ActronAir Neo card configuration");
    for (const key of ["entity", "device_id", "title"] as const)
      if (config[key] !== undefined && typeof config[key] !== "string")
        throw new Error(`${key} must be a string`);
    for (const key of [
      "show_options",
      "show_humidity",
      "show_dampers",
      "show_diagnostics",
    ] as const)
      if (config[key] !== undefined && typeof config[key] !== "boolean")
        throw new Error(`${key} must be a boolean`);
    this.config = { ...config };
    this.error = "";
  }
  static getConfigForm() {
    return {
      schema: [
        {
          name: "device_id",
          required: true,
          selector: { device: { integration: "actronair_neo" } },
        },
        { name: "title", selector: { text: {} } },
        {
          type: "expandable",
          name: "",
          title: "Display options",
          // biome-ignore lint/complexity/noThisInStatic: Inherited forms use each subclass's options.
          schema: this.displayOptions.map((name) => ({ name, selector: { boolean: {} } })),
        },
      ],
      computeLabel: (field: { name: string }) =>
        ({
          device_id: "ActronAir Neo device",
          title: "Title",
          show_options: "Show quick controls",
          show_humidity: "Show humidity",
          show_dampers: "Show damper controls",
          show_diagnostics: "Show diagnostics",
        })[field.name as "device_id"],
      computeHelper: (field: { name: string }) =>
        field.name === "device_id"
          ? "Choose your ActronAir Neo system. Its entities and zones are discovered securely."
          : undefined,
    };
  }
  static getStubConfig(hass: HomeAssistant): Partial<CardConfig> {
    const candidates = systemCandidates(hass, Object.values(hass.entities ?? {}));
    return candidates[0]
      ? {
          device_id: candidates[0].device_id ?? undefined,
          show_options: true,
          show_humidity: true,
          show_dampers: true,
        }
      : {};
  }
  override connectedCallback(): void {
    super.connectedCallback();
    this.watchRegistry();
  }
  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.subscription?.unsubscribe();
    this.subscription = undefined;
    this.connection = undefined;
    this.clearPending();
  }
  protected override willUpdate(changed: PropertyValues): void {
    if (changed.has("hass") || changed.has("config")) this.watchRegistry();
    if (this.pendingId && this.hass?.states[this.pendingId] !== this.pendingState)
      this.clearPending();
  }
  private clearPending(): void {
    if (this.pendingTimer) clearTimeout(this.pendingTimer);
    this.pendingTimer = undefined;
    this.pendingId = undefined;
    this.pendingState = undefined;
    this.busy = false;
  }
  private watchRegistry(): void {
    if (!this.hass || !this.isConnected) return;
    const key = this.hass.connection ?? this.hass;
    const deviceId =
      this.config.device_id ??
      (this.config.entity ? this.hass.entities?.[this.config.entity]?.device_id : undefined);
    if (!deviceId) {
      this.subscription?.unsubscribe();
      this.subscription = undefined;
      this.connection = undefined;
      this.deviceId = undefined;
      this.registry = [];
      this.discoveryError = "Select an ActronAir Neo device in the card editor.";
      return;
    }
    if (this.connection === key && this.deviceId === deviceId) {
      if (this.registryReference !== this.hass.entities) {
        this.registryReference = this.hass.entities;
        this.subscription?.refresh();
      }
      return;
    }
    this.subscription?.unsubscribe();
    this.connection = key;
    this.deviceId = deviceId;
    this.registryReference = this.hass.entities;
    this.registry = undefined;
    this.subscription = subscribeDiscovery(this.hass, deviceId, (registry, error) => {
      this.registry = registry;
      this.discoveryError = error ?? "";
    });
  }
  protected get system(): System | undefined {
    return this.hass && this.registry
      ? resolveSystem(this.hass, this.registry, this.config)
      : undefined;
  }
  protected name(state: EntityState, fallback: string): string {
    return (
      this.hass?.formatEntityName?.(state) ||
      (typeof state.attributes.friendly_name === "string"
        ? state.attributes.friendly_name
        : fallback)
    );
  }
  protected number(value: unknown, digits = 1): string {
    const number = typeof value === "number" ? value : Number.NaN;
    return Number.isFinite(number)
      ? new Intl.NumberFormat(this.hass?.locale?.language ?? this.hass?.language, {
          maximumFractionDigits: digits,
          minimumFractionDigits: digits,
        }).format(number)
      : "—";
  }
  protected unit(state: EntityState): string {
    return typeof state.attributes.temperature_unit === "string"
      ? state.attributes.temperature_unit
      : (this.hass?.config?.unit_system?.temperature ?? "°C");
  }
  protected header(
    title: string,
    subtitle: string,
    icon: string,
    action: TemplateResult | typeof nothing = nothing,
  ): TemplateResult {
    return html`<header><ha-icon .icon=${icon}></ha-icon><div class="heading"><div class="eyebrow">ActronAir Neo</div><h2>${this.config.title || title}</h2><div class="secondary">${subtitle}</div></div>${action}</header>`;
  }
  protected feedback(): TemplateResult {
    return html`${
      this.error
        ? html`<div class="error" role="alert">${this.error}<button aria-label="Dismiss error" @click=${() => {
            this.error = "";
          }}>Dismiss</button></div>`
        : nothing
    }${this.busy ? html`<div class="pending" role="status">Sending command…</div>` : nothing}`;
  }
  protected empty(): TemplateResult {
    return html`<ha-card><div class="content">${this.header("Climate control", "Your home, your comfort", "mdi:thermostat")}
      <div class="notice" role="status">${this.discoveryError || (!this.registry ? "Discovering your ActronAir Neo system…" : "Select the main system climate entity in the card editor. The selected system may have been removed or disabled.")}</div></div></ha-card>`;
  }
  protected async command(
    entity: EntityState,
    domain: string,
    service: string,
    data: Record<string, unknown> = {},
  ): Promise<void> {
    if (
      !this.hass ||
      !["climate", "switch", "cover", "number"].includes(domain) ||
      this.busy ||
      !available(this.system?.climate) ||
      !available(this.hass.states[entity.entity_id]) ||
      !this.system?.entities.some((e) => e.entity_id === entity.entity_id)
    )
      return;
    const request = ++this.requestId;
    this.busy = true;
    this.error = "";
    this.pendingId = entity.entity_id;
    this.pendingState = this.hass.states[entity.entity_id];
    this.pendingTimer = setTimeout(() => {
      if (request !== this.requestId) return;
      this.clearPending();
      this.error =
        "The system has not confirmed the change yet. Check its state before trying again.";
    }, 15000);
    try {
      await this.hass.callService(domain, service, { ...data, entity_id: entity.entity_id });
    } catch {
      if (request === this.requestId) {
        this.clearPending();
        this.error = "The command could not be sent. Check the connection and try again.";
      }
    }
  }

  protected moreInfo(entity: EntityState): void {
    this.dispatchEvent(
      new CustomEvent("hass-more-info", {
        detail: { entityId: entity.entity_id },
        bubbles: true,
        composed: true,
      }),
    );
  }
  getCardSize(): number {
    return 5;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto", min_rows: 3 };
  }
  protected abstract override render(): TemplateResult;
}
