/**
 * API types, mirroring backend/app/schemas/models.py.
 *
 * The pervasive `| null` on result fields is the "not computed" state from
 * engineering rule 1. It is a different thing from zero, and the UI must
 * render it as an em dash, never as 0.
 */

export interface RiverSummary {
  name: string
  dam_count: number
  states: string[]
}

export interface DamSummary {
  id: string
  name: string
  river: string
  state: string
  lon: number
  lat: number
  dam_type: string
  structural_height_m: number | null
  crest_length_m: number | null
  gross_storage_mcm: number | null
  live_storage_mcm: number | null
  /** Null for every catalog record: the NRLD tables do not carry it. */
  frl_m: number | null
  mddl_m: number | null
  commissioned_year: number | null
  nrld_id: string | null
  notes: string[]
  /** Per-field citation, so any number in the UI traces to a source. */
  sources: Record<string, string>
}

export interface ScenarioSummary {
  id: string
  name: string
  description: string
  dam: string
  river: string
  state: string
  lon: number
  lat: number
  scenario_type: string
  resolution_m: number
  duration_hours: number
  reach_length_km: number
  towns: string[]
  valid: boolean
  error?: string
}

export type EngineKind = 'native' | 'external' | 'unavailable'

export interface EngineStatus {
  id: string
  /** The exact string the badge must display. Never substitute our own wording. */
  display_name: string
  kind: EngineKind
  available: boolean
  is_real_solver: boolean
  version: string | null
  detail: string
  substitute_id: string | null
  evidence: Record<string, unknown>
}

export interface EngineHealth {
  engines: EngineStatus[]
  honesty_statement: string
}

export interface BreachInput {
  shape?: 'trapezoidal' | 'rectangular' | 'triangular'
  growth?: 'linear' | 'sine' | 'parabolic'
  width_m?: number | null
  depth_m?: number | null
  /** Partial breach: breach depth / structural height (a user assumption). */
  depth_fraction?: number | null
  side_slope?: number
  formation_time_min?: number | null
  parameter_model?: string
}

export type ScenarioType =
  | 'complete_dam_break'
  | 'partial_breach'
  | 'piping_failure'
  | 'overtopping'
  | 'controlled_release'
  | 'landslide_dam_breach'

export interface SimulationRequest {
  scenario_id?: string
  dam_id?: string
  scenario_type?: ScenarioType
  reservoir_level_m?: number | null
  breach?: BreachInput
  engines?: string[]
  resolution_m?: number | null
  duration_hours?: number | null
  cfl?: number | null
  wet_threshold_m?: number | null
  manning_n_overrides?: Record<string, number>
  dem_upload_id?: string | null
  hydrograph_upload_id?: string | null
  /** A precomputed preset: the stored run is returned, no solver runs. */
  preset_key?: string | null
  /** Live quick estimate: resolution, duration and engines forced server-side. */
  quick?: boolean
}

export type RunMode = 'precomputed' | 'quick_estimate' | 'full'

export interface SensitivityEnd {
  value: number
  peak_m3s: number
  time_to_peak_min: number
  volume_mcm: number
}

export interface Sensitivity {
  run_id: string
  method: string
  base: { width_m: number; formation_time_min: number; level_m: number; peak_m3s: number }
  factors: Array<{ factor: string; basis: string; base_value: number; low: SensitivityEnd; high: SensitivityEnd; swing_m3s: number }>
  notes: string[]
}

export interface SiteRow {
  scenario_id: string
  name: string
  dam: string
  river: string
  tier: string
  tier_reason: string
  towns: number
  population_raster: boolean
  osm_layers: string[]
  resolutions: Record<string, {
    terrain: { ok: boolean; reason: string }
    presets_defined: number
    presets_stored: number
  }>
}

export interface ProvenanceRow {
  label: string
  value: string | number | boolean
  source: string
}

export interface RunProvenance {
  run_id: string
  labels: Array<{ level: 'info' | 'caution'; text: string; source: string }>
  sections: Array<{ title: string; rows: ProvenanceRow[] }>
}

export interface GaugePoint {
  kind: 'town' | 'channel'
  in_domain: boolean
  max_depth_m: number | null
  max_velocity_ms?: number | null
  arrival_min?: number | null
  peak_frame_min?: number | null
  end_depth_m?: number | null
  rising_at_end?: boolean
  hazard_label?: string | null
  near_domain_edge?: boolean
  series_m: number[] | null
  shared_with?: string[]
  note?: string
}

export interface TownGauge {
  name: string
  population: number | null
  town: GaugePoint
  channel: GaugePoint | null
  chainage_km: number | null
  town_to_channel_km: number | null
}

export interface GaugesResponse {
  run_id: string
  times_min: number[]
  frame_interval_min: number | null
  gauges: TownGauge[]
  notes: string[]
}

export interface DatasetSource {
  source: string
  licences: string[]
  files: number
  total_bytes: number
  example_url: string | null
  last_fetched_utc: string | null
}

export interface DatasetCatalog {
  sources: DatasetSource[]
  entry_count?: number
  updated_utc?: string
  note: string
}

export interface LifeLossCategory {
  severity: string
  warning: string
  understanding: string
  population_at_risk: number
  fatality_rate: number
  rate_range: [number, number]
  estimate: number
}

/** Graham (1999) loss-of-life estimate; `computed: false` carries the reason. */
export interface LifeLoss {
  method: string
  citation: string
  computed: boolean
  reason?: string
  population_at_risk?: number | null
  estimate?: number | null
  range: [number | null, number | null]
  assumptions?: Record<string, unknown>
  by_category?: LifeLossCategory[]
  par_without_a_rate?: number | null
  notes?: string[]
  caveats: string[]
}

export interface BreachPrediction {
  model: string
  width_m: number
  depth_m: number
  side_slope: number
  formation_time_min: number
  reference: string
  applicable: boolean
  caveats: string[]
}

export interface BreachComparison {
  used: BreachPrediction
  predictions: BreachPrediction[]
  spread: {
    n_models: number
    width_m: { min: number; max: number; mean: number; spread_ratio: number }
    formation_time_min: { min: number; max: number; mean: number; spread_ratio: number }
    interpretation: string
  }
}

export interface JobCreated {
  job_id: string
  status: string
  scenario_id: string
  websocket: string
  run_id: string | null
  mode: RunMode
  mode_label: string | null
  completed_utc: string | null
}

export interface PresetLevel {
  level: string
  label: string
  level_m: number
}

export interface PresetDam {
  scenario_id: string
  name: string
  duration_hours: number
  levels: PresetLevel[]
}

export interface PresetEntry {
  key: string
  scenario_id: string
  scenario_type: string
  type_label: string
  level: string
  level_label: string
  level_m: number
  modelled: boolean
  available: boolean
  reason: string | null
  run_id: string
  completed_utc: string | null
  wall_seconds: number | null
  resolution_m: number
}

export interface QuickSettings {
  resolution_m: number
  duration_hours: number
  engines: string[]
  label: string
}

export interface PresetCatalog {
  resolution_m: number
  resolutions: number[]
  engines: string[]
  dams: PresetDam[]
  failure_types: Record<string, string>
  presets: PresetEntry[]
  quick: QuickSettings
}

export type JobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export interface JobState {
  id: string
  scenario_id: string
  status: JobStatus
  created_utc: string
  fraction: number
  phase: string
  message: string
  log: string[]
  eta_seconds: number | null
  elapsed_seconds: number | null
  error: string | null
}

export interface EngineSummary {
  engine_id: string
  engine_display_name: string
  is_real_solver: boolean
  substituted: boolean
  honesty_note: string
  flooded_area_km2: number | null
  max_depth_m: number | null
  max_velocity_ms: number | null
  earliest_arrival_min: number | null
  max_hazard_m2s: number | null
  runtime_s: number | null
  steps: number | null
  mass_error: number | null
  warnings: string[]
}

export interface DepthBandStat {
  index: number
  min_m: number
  max_m: number | null
  label: string
  colour: string
  cells: number
  area_km2: number
}

export interface HazardStats {
  standard: string
  wet_threshold_m: number
  flooded_area_km2: number
  by_depth_band: DepthBandStat[]
  by_hazard_class: Array<{
    code: number
    label: string
    description: string
    colour: string
    cells: number
    area_km2: number
  }>
  max_depth_m: number | null
  max_velocity_ms: number | null
  max_dv_m2s: number | null
}

export interface ResultSummary {
  run_id: string
  scenario_id: string
  engines: EngineSummary[]
  hazard: HazardStats
  breach: BreachComparison
  peak_discharge_m3s: number | null
  time_to_peak_min: number | null
  total_volume_mcm: number | null
  resolution_m: number | null
  warnings: string[]
  provenance: Record<string, unknown>
  run_mode: RunMode
  run_meta: Record<string, unknown>
  completed_utc: string | null
  duration_hours: number | null
}

export interface ComparisonRow {
  metric: string
  unit: string
  values: Record<string, number | null>
  difference_pct: number | null
}

export interface Comparison {
  run_id: string
  engines: string[]
  engine_display_names: Record<string, string>
  rows: ComparisonRow[]
  critical_success_index: number | null
  extent_rmse_m: number | null
  note: string
}

export interface TownResult {
  name: string
  lon: number
  lat: number
  population: number | null
  population_source: string | null
  max_depth_m: number | null
  max_velocity_ms: number | null
  arrival_min: number | null
  in_domain: boolean
}

export interface ImpactMetric {
  label: string
  value: number | null
  unit: string
  computed: boolean
  reason: string
  assumption: string
  display: string
  detail: Record<string, unknown>
}

export interface ImpactResponse {
  run_id: string
  metrics: Record<string, ImpactMetric>
  facilities: Array<Record<string, unknown>>
  evacuation_priority: Array<{
    name: string
    population: number | null
    depth_m: number | null
    arrival_min: number | null
  }>
  warnings: string[]
  provenance: Record<string, unknown>
}

export interface HydrographSeries {
  label: string
  unit: string
  times_hours: number[]
  values: Array<number | null>
}

export interface HydrographResponse {
  run_id: string
  series: HydrographSeries[]
  note: string
}

export interface CrossSectionResponse {
  run_id: string
  location: string
  chainage_m: number
  offset_from_path_m: number | null
  offsets_m: number[]
  bed_m: Array<number | null>
  water_surface_m: Array<number | null>
  max_depth_m: number | null
  note: string
}

// --- runs, frames, sharing, uploads, 3D, AOI ------------------------------------

export interface RunListing {
  run_id: string
  scenario_id: string | null
  completed_utc: string
  resolution_m: number | null
  engines: Array<{ id: string; display_name: string; ok: boolean }>
  engine_count: number
  flooded_area_km2: number | null
  max_depth_m: number | null
  has_frames: boolean
  has_impact: boolean
  run_mode: RunMode
  library_key: string | null
}

export interface FramesResponse {
  run_id: string
  engines: Record<string, number[]>
  note: string
}

export interface ShareCreated {
  code: string
  path: string
  run_id: string
  view: Record<string, unknown>
}

export interface ShareResolved {
  code: string
  run_id: string
  view: { layer?: string; engine?: string; frame?: number; tab?: string }
  created_utc: string
}

export type UploadKind = 'dem' | 'hydrograph' | 'aoi'

export interface UploadMeta {
  id: string
  kind: UploadKind
  original_filename: string
  size_bytes: number
  uploaded_utc: string
  ok: boolean
  issues: string[]
  warnings: string[]
  sha256?: string
  // dem
  crs?: string
  resolution_m?: number
  bounds_wgs84?: [number, number, number, number]
  elevation_min_m?: number
  elevation_max_m?: number
  nodata_fraction?: number
  // hydrograph
  rows?: number
  duration_hours?: number
  peak_discharge_m3s?: number
  time_to_peak_min?: number
  volume_mcm?: number
  // aoi
  features?: number
  area_km2?: number
}

export interface Scene3DMeta {
  run_id: string
  bounds: [number, number, number, number]
  size: [number, number]
  bed_min_m: number | null
  bed_max_m: number | null
  max_depth_m: number | null
  encoding: 'terrarium'
  note: string
}

export interface AoiStats {
  run_id: string
  upload_id: string
  aoi_name: string | null
  aoi_area_km2: number
  covered_by_model_km2: number
  coverage_fraction: number | null
  flooded_area_km2: number | null
  flooded_fraction_of_covered?: number
  max_depth_m: number | null
  mean_flooded_depth_m?: number | null
  earliest_arrival_min: number | null
  reason: string
}

export interface LegendBin {
  lower: number | null
  upper: number | null
  label: string
  colour: string
}

export type MapLayer = 'depth' | 'velocity' | 'arrival' | 'hazard' | 'difference'

// --- early warning -------------------------------------------------------------

export type AlertLevel = 'RED' | 'ORANGE' | 'YELLOW' | 'NONE' | 'NOT_ASSESSED'

export interface SafeGround {
  distance_km: number
  bearing_deg: number
  direction: string
  lon: number
  lat: number
  ground_elevation_m: number
  height_above_flood_m: number
}

export interface TownAlert {
  name: string
  lon: number
  lat: number
  level: AlertLevel
  action_en: string
  action_hi: string
  arrival_min: number | null
  max_depth_m: number | null
  max_velocity_ms: number | null
  hazard_class: string | null
  population: number | null
  safe_ground: SafeGround | null
  safe_ground_reason: string
  reasons: string[]
}

export interface SmsMessage {
  town: string
  level: AlertLevel
  text: string
  chars: number
  segments: number
}

export interface WarningBulletin {
  run_id: string
  scenario: string
  issued_utc: string
  towns: TownAlert[]
  counts: Record<AlertLevel, number>
  population_red_orange: number | null
  convention: string
  safe_ground_method: string
  disclaimer_en: string
  disclaimer_hi: string
  note: string
  sms: SmsMessage[]
  sms_hi: SmsMessage[]
}

export interface BreachEnsemble {
  times_hours: number[]
  members: Array<{
    model: string
    applicable: boolean
    used_in_run: boolean
    width_m: number
    formation_time_min: number
    peak_discharge_m3s: number
    time_to_peak_min: number
    volume_mcm: number
    discharge_m3s: number[]
  }>
  peak_spread_ratio: number | null
  note: string
}
